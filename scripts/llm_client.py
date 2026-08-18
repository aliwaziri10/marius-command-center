"""
Marius Command Center - LLM Client
Shared Gemini call wrapper, Supabase retry helper, and JSON extraction
utilities used by both the narration stage and the shot-breakdown stage.

SPLIT OUT (2026-08-18): previously all of this lived inline in
script_writing.py alongside the narration/shot-breakdown logic, making that
one file very long and hard to navigate. Split into separate modules with
no behavior change - every constant, function, and exception here is
byte-for-byte the same logic as before, just relocated. See
script_writing.py's module docstring for the full provider-switch history
(Gemini -> Groq -> back to Gemini) that led to the current call_llm().
"""

import os
import json
import time
import requests

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SECRET_KEY"]

HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
}

# FALSE-POSITIVE DAILY-QUOTA ABORT FIX (2026-08-17, later): see original
# script_writing.py history. Bumped from 2 so call_llm can actually survive
# a real per-minute TPM window without running out of attempts first.
MAX_RETRIES = 4
MAX_INFRA_ATTEMPTS = 4
CONTENT_RETRY_WAIT_SECONDS = 25

# TRUNCATED-JSON FIX (2026-08-18): a chunk's shot_list JSON response can run
# long; without an explicit ceiling this was left on Gemini's default
# maxOutputTokens, which could truncate mid-object on a large chunk and
# produce invalid JSON.
GEMINI_MAX_OUTPUT_TOKENS = 8192

GEMINI_KEY = os.environ["GEMINI_API_KEY"]
GEMINI_MODEL = "gemini-3.5-flash-lite"
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GEMINI_KEY}"

RETRYABLE_NETWORK_EXCEPTIONS = (
    requests.exceptions.ChunkedEncodingError,
    requests.exceptions.ConnectionError,
    requests.exceptions.Timeout,
)
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


class InfraFailure(RuntimeError):
    """Raised when Gemini never returned a usable response within the infra
    retry budget - meaning the topic's actual content was never evaluated
    at all. This must NOT be treated the same as a real content failure:
    the topic itself did nothing wrong, so it must stay 'pending' for the
    next scheduled run to retry once Gemini's quota/availability recovers,
    instead of being permanently blacklisted as generation_failed."""
    pass


class DailyQuotaExhausted(RuntimeError):
    """PROVIDER SWITCH (2026-08-17): replaces Groq's SuspectedDailyQuotaExhausted
    guesswork. Gemini's 429 body is structured JSON with an explicit
    quotaMetric/quotaId naming the exact limit that was hit (e.g.
    "generate_content_free_tier_requests") - no more inferring daily-vs-
    per-minute from ambiguous headers. Raised only when the response body
    itself names a free-tier daily/per-day quota. Unlike InfraFailure, not
    retried within the same run - every further call will hit the same
    wall until Google's daily reset."""
    pass


def retryable_request(method, url, max_retries=MAX_RETRIES, **kwargs):
    last_error = None
    for attempt in range(max_retries):
        try:
            resp = requests.request(method, url, **kwargs)
        except RETRYABLE_NETWORK_EXCEPTIONS as e:
            wait = (attempt + 1) * 10
            print(f"Supabase network error ({e.__class__.__name__}: {e}), waiting {wait}s before retry...")
            last_error = e
            time.sleep(wait)
            continue

        if resp.status_code in RETRYABLE_STATUS_CODES:
            wait = (attempt + 1) * 10
            print(f"Supabase transient error {resp.status_code}, waiting {wait}s before retry: {resp.text}")
            last_error = resp
            time.sleep(wait)
            continue

        resp.raise_for_status()
        return resp

    if isinstance(last_error, Exception):
        raise RuntimeError(f"Supabase call still failing after {max_retries} attempts: {last_error}")
    raise RuntimeError(f"Supabase call still failing after {max_retries} attempts: {last_error.status_code if last_error else 'unknown'} {last_error.text if last_error else ''}")


def call_llm(prompt):
    """PROVIDER SWITCH (2026-08-17): Groq replaced with Gemini
    (gemini-3.5-flash-lite), same call_gemini() pattern already proven
    working in TechPulse's script/generate_script.py. Reasons: (1) Groq's
    daily (TPD) cap is completely invisible in its response headers -
    every diagnostic fix attempted on 2026-08-15/17 was reading headers
    that structurally cannot reflect TPD exhaustion, so the pipeline kept
    silently producing zero scripts with no reliable way to detect why.
    (2) Gemini's 429 body is structured JSON naming the exact quota
    metric hit (e.g. "generate_content_free_tier_requests") - an
    unambiguous signal Groq never gave us. (3) Gemini's free tier (1,500
    requests/day, 1M token context) removes the need for the
    shot-breakdown chunking hack entirely - the full prompt + narration +
    shot list fits in a single call. response_mime_type forces native
    JSON output so it's never wrapped in markdown fences."""
    body = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "response_mime_type": "application/json",
            "maxOutputTokens": GEMINI_MAX_OUTPUT_TOKENS,
        },
    }).encode()
    last_error = None
    for attempt in range(MAX_RETRIES):
        try:
            resp = requests.post(
                GEMINI_URL,
                data=body,
                headers={"Content-Type": "application/json"},
                timeout=180,
            )
        except RETRYABLE_NETWORK_EXCEPTIONS as e:
            wait = (attempt + 1) * 15
            print(f"Gemini network error ({e.__class__.__name__}: {e}), waiting {wait}s before retry...")
            last_error = e
            time.sleep(wait)
            continue

        if resp.status_code == 429:
            body_text = resp.text[:800]
            print(f"Gemini rate limited (429): {body_text}")

            is_daily = False
            try:
                err_json = resp.json()
                for detail in err_json.get("error", {}).get("details", []):
                    for violation in detail.get("violations", []):
                        metric = violation.get("quotaMetric", "") or violation.get("quotaId", "")
                        if "per_day" in metric.lower() or "daily" in metric.lower() or "free_tier" in metric.lower():
                            is_daily = True
            except (requests.exceptions.JSONDecodeError, AttributeError):
                pass

            if is_daily:
                raise DailyQuotaExhausted(
                    f"Gemini 429 explicitly names a free-tier/daily quota metric - will not clear "
                    f"until Google's daily reset. Body: {body_text}"
                )

            wait = (attempt + 1) * 15
            print(f"Ordinary rate limit (not daily-quota-named) - waiting {wait}s before retry...")
            last_error = resp
            time.sleep(wait)
            continue

        try:
            resp.raise_for_status()
        except requests.exceptions.HTTPError as e:
            wait = (attempt + 1) * 15
            print(f"Gemini HTTP error {resp.status_code} ({e}): {resp.text[:300]}, waiting {wait}s before retry...")
            last_error = resp
            time.sleep(wait)
            continue

        try:
            result = resp.json()
        except requests.exceptions.JSONDecodeError as e:
            wait = (attempt + 1) * 15
            print(f"Gemini response envelope malformed/unparseable ({e}), waiting {wait}s before retry...")
            last_error = e
            time.sleep(wait)
            continue

        try:
            return result["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError, TypeError) as e:
            wait = (attempt + 1) * 15
            print(f"Unexpected Gemini response shape ({e}): {json.dumps(result)[:500]}, waiting {wait}s before retry...")
            last_error = e
            time.sleep(wait)
            continue

    raise RuntimeError(f"Gemini still failing after {MAX_RETRIES} attempts: {last_error}")


def sanitize_json_control_chars(text):
    out = []
    in_string = False
    escaped = False
    for ch in text:
        code = ord(ch)
        if in_string:
            if escaped:
                out.append(ch)
                escaped = False
                continue
            if ch == "\\":
                out.append(ch)
                escaped = True
                continue
            if ch == '"':
                out.append(ch)
                in_string = False
                continue
            if code < 0x20:
                if ch == "\n":
                    out.append("\\n")
                elif ch == "\r":
                    out.append("\\r")
                elif ch == "\t":
                    out.append("\\t")
                continue
            out.append(ch)
        else:
            if ch == '"':
                in_string = True
            out.append(ch)
    return "".join(out)


def extract_json(raw_text):
    if not raw_text:
        raise ValueError("Model returned empty/None content (likely a dropped or refused generation).")
    text = raw_text.strip()

    if "```" in text:
        parts = text.split("```")
        for part in parts:
            candidate = part.strip()
            if candidate.startswith("json"):
                candidate = candidate[4:].strip()
            if candidate.startswith("{"):
                text = candidate
                break

    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("No JSON object found in model output.")

    candidate = text[start:end + 1]
    try:
        return json.loads(candidate)
    except json.JSONDecodeError as e:
        if "Invalid control character" not in str(e):
            raise
        return json.loads(sanitize_json_control_chars(candidate))
