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

MALFORMED-JSON REPAIR FIX (2026-08-19) - HYPOTHESIS, NOT YET CONFIRMED:
a live run showed repeated "Expecting property name enclosed in double
quotes" / "Expecting value" JSON parse failures at a range of small
character offsets (691-4484 chars into the candidate) - too early to be
maxOutputTokens truncation (already fixed 2026-08-18; truncation fails
near the END of a candidate, not a few hundred/thousand chars in). The
LEADING THEORY is genuine malformed JSON despite Gemini's native JSON
mode being enabled - most commonly a trailing comma before a closing }
or ] - but per this repo's DEBUGGING_METHODOLOGY.md, that has NOT been
proven: the actual raw failing response text was never captured/logged
anywhere, so the trailing-comma theory could not be tested against real
data, only reasoned about from the error offsets alone. Two things were
done as a result: (1) added _strip_trailing_commas() as one candidate in
extract_json()'s repair sequence - safe either way, since it's a no-op if
the real cause turns out to be something else; (2) added diagnostic
logging (see extract_json() below) so the NEXT parse failure captures
which repair (if any) actually fixed it, or the raw text if none did -
turning the next occurrence into real evidence instead of another guess.
Do not treat the trailing-comma theory as confirmed until that log output
is reviewed.

UNQUOTED-KEY REPAIR FIX (2026-09-11) - CONFIRMED, not a hypothesis: a live
run's diagnostic logging (added above) finally captured the real raw
failing text, and it was NOT a trailing comma. Gemini was emitting bare/
unquoted object keys for one specific field, e.g.:
    "lens_effect": "none",
    sfx_cue: "distant harbor foghorn and low wind howling over concrete",
`sfx_cue` (and potentially any other key) appearing without quotes breaks
standard JSON parsing with exactly the "Expecting property name enclosed
in double quotes" error seen in the logs - at small offsets, matching the
observed 691-4484 char range (wherever that key first appears), not near
the end of the candidate. None of the four existing repair attempts
(raw / control-char-escaped / trailing-comma-stripped / both) fix this,
since they don't touch key names at all. Added _quote_unquoted_keys() as
a new repair candidate below. The trailing-comma hypothesis is NEITHER
confirmed nor refuted by this - both bugs can and likely do occur
independently in different Gemini responses, so both repairs are kept.

SILENT ZERO-ROW PATCH FIX (2026-09-12): found live - topic
a8512686-efde-41f0-8b65-039d12d23c3a was logged as "marked
generation_failed" by mark_topic_generation_failed (script_writing.py),
including the FIX print statement that only runs after the PATCH request
object returns without raising, but the topic's actual row in Supabase
was untouched (still status='pending', last_failure_reason=null) an hour
later, confirmed by direct SQL read and by successfully applying the same
UPDATE manually via SQL with no trigger/RLS/constraint blocking it. Root
cause: PostgREST returns 200 OK / 204 No Content for a PATCH even when
the WHERE clause matches ZERO rows - there is no error, no non-2xx status,
nothing for resp.raise_for_status() to catch. retryable_request had no way
to distinguish "updated the row" from "matched nothing and updated
nothing" for PATCH/DELETE calls, so a caller like mark_topic_generation_failed
could print a false success message while silently doing nothing - the
exact same failure class TechPulse hit once with a missing RLS policy,
just a different mechanism (row-match, not permissions) producing the same
"looked fine, changed nothing" symptom.

Fix: for PATCH and DELETE, retryable_request now automatically adds
`Prefer: return=representation` (unless the caller already set a Prefer
header) so PostgREST returns the actually-affected row(s) as JSON instead
of an empty 204 body, then explicitly checks that list is non-empty -
raising a clear RuntimeError naming the exact URL if zero rows came back,
instead of returning a "successful" response that updated nothing. GET/
POST are untouched. This makes the exact bug that hid for over one hour
loud and immediate everywhere retryable_request is used (script_writing.py,
video_generation.py's mark_* functions, etc.) the next time it happens for
any reason (wrong id, row deleted elsewhere, wrong table, wrong project).
"""

import os
import re
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

# SILENT ZERO-ROW PATCH FIX (2026-09-12): see module docstring.
ROW_CHECKED_METHODS = {"PATCH", "DELETE"}


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
    """SILENT ZERO-ROW PATCH FIX (2026-09-12): see module docstring. For
    PATCH/DELETE, this now injects `Prefer: return=representation` (only if
    the caller didn't already set a Prefer header - never overrides an
    explicit caller choice) and treats an empty returned list as a hard
    failure, not a success. GET/POST behavior is completely unchanged."""
    method_upper = method.upper()
    if method_upper in ROW_CHECKED_METHODS:
        headers = dict(kwargs.get("headers") or {})
        headers.setdefault("Prefer", "return=representation")
        kwargs = {**kwargs, "headers": headers}

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

        if method_upper in ROW_CHECKED_METHODS and headers.get("Prefer") == "return=representation":
            try:
                affected = resp.json()
            except (requests.exceptions.JSONDecodeError, ValueError):
                affected = None
            if isinstance(affected, list) and len(affected) == 0:
                raise RuntimeError(
                    f"Supabase {method_upper} to {url} returned 2xx but matched ZERO rows - "
                    f"nothing was actually updated/deleted. This is NOT a success, even though "
                    f"no error was raised - check the id/filter in the URL is correct and the "
                    f"row actually exists in THIS project."
                )

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


def _strip_trailing_commas(text):
    """MALFORMED-JSON REPAIR FIX (2026-08-19, hypothesis - see module
    docstring). Removes a comma that appears right before a closing } or
    ] (with only whitespace between them) - the most common cause of
    "Expecting property name enclosed in double quotes" / "Expecting
    value" parse errors from LLM-generated JSON, IF that turns out to be
    the real cause here. Safe no-op on text that doesn't have this
    problem."""
    return re.sub(r",\s*([}\]])", r"\1", text)


def _quote_unquoted_keys(text):
    """UNQUOTED-KEY REPAIR FIX (2026-09-11, confirmed - see module
    docstring). Gemini has been observed emitting a bare/unquoted object
    key (e.g. `sfx_cue: "..."` instead of `"sfx_cue": "..."`), which is
    invalid JSON and breaks parsing exactly where the key appears - not
    near the end of the response. This only quotes an identifier that
    immediately follows an opening `{` or a `,` (the only positions a
    JSON key can legally appear), so it will not touch identifiers that
    happen to appear inside already-quoted string values. Safe no-op on
    text that doesn't have this problem."""
    return re.sub(r'([{,]\s*)([A-Za-z_][A-Za-z0-9_]*)(\s*:)', r'\1"\2"\3', text)


def extract_json(raw_text):
    """DIAGNOSTIC LOGGING ADDED (2026-08-19): see module docstring - the
    trailing-comma repair below is an unconfirmed hypothesis, not a proven
    fix. Every repair attempt is now logged so the NEXT parse failure (or
    the next successful repair) leaves real evidence in the Actions log:
    which candidate (if any) actually worked, or - if all four fail - a
    preview of the real raw text, so the actual cause can be read directly
    instead of guessed at again from an offset.

    UNQUOTED-KEY REPAIR ADDED (2026-09-11): see _quote_unquoted_keys()
    docstring - this was the actual confirmed cause of the failures the
    2026-08-19 logging captured. Repair list expanded from 4 to 8 entries
    to cover the unquoted-key fix alone and combined with the existing
    two repairs, in every order, since either bug can occur independently
    or together in the same response."""
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

    control_escaped = sanitize_json_control_chars(candidate)
    comma_stripped = _strip_trailing_commas(candidate)
    keys_quoted = _quote_unquoted_keys(candidate)

    attempts = [
        ("raw", candidate),
        ("control-char-escaped", control_escaped),
        ("trailing-comma-stripped", comma_stripped),
        ("unquoted-keys-fixed", keys_quoted),
        ("control-char-escaped + trailing-comma-stripped", _strip_trailing_commas(control_escaped)),
        ("control-char-escaped + unquoted-keys-fixed", _quote_unquoted_keys(control_escaped)),
        ("trailing-comma-stripped + unquoted-keys-fixed", _quote_unquoted_keys(comma_stripped)),
        ("all three combined", _quote_unquoted_keys(_strip_trailing_commas(control_escaped))),
    ]
    last_error = None
    for label, attempt_text in attempts:
        try:
            parsed = json.loads(attempt_text)
            if label != "raw":
                # PROOF POINT: this line firing is what confirms (or, for a
                # different label, refutes) which repair actually mattered -
                # check this log if a new failure pattern ever shows up.
                print(f"[extract_json] raw candidate failed to parse; repair '{label}' fixed it.")
            return parsed
        except json.JSONDecodeError as e:
            last_error = e
            continue

    print(f"[extract_json] all repair attempts failed ({last_error}). Raw candidate (first 1500 chars): {candidate[:1500]!r}")
    raise last_error
