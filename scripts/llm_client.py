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

MALFORMED-KEY VARIANT FIX (2026-09-13) - CONFIRMED via a live run's raw
candidate: a second, distinct malformed-key shape was found, e.g.:
    "lens_effect": "none",
    sfx_cue": "Low wind howling across frozen ground, distant muffled gunfire",
Here the key has a STRAY TRAILING QUOTE but no matching leading quote
(`sfx_cue"` instead of `sfx_cue` or `"sfx_cue"`) - this is different from
the fully-unquoted case above, which _quote_unquoted_keys()'s original
regex could not catch, since that regex required the identifier to be
followed directly by whitespace-then-colon with nothing in between; here
a stray `"` sits between the identifier and the colon, so the match
failed and every one of the 8 repair combinations still failed, dying
after all 3 content attempts. Widened _quote_unquoted_keys()'s regex to
optionally consume a leading and/or trailing quote around the identifier
and always re-emit exactly one well-formed quoted pair - this is a strict
superset of the old behavior (idempotent on already-correctly-quoted
keys, still fixes the fully-bare case, and now also fixes the
stray-trailing-quote case) rather than a separate new function, so no
change to the 8-entry attempts list in extract_json() is needed.

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

SCHEMA-CONSTRAINED GENERATION (2026-09-13): every fix above (2026-08-19,
2026-09-11, 2026-09-13 key-quote widening) has been another regex patch
reacting to one more distinct shape of malformed JSON that Gemini
produced anyway. Rather than waiting for the next malformed-key variant
to show up live and adding a 9th regex, call_llm now accepts an optional
response_schema, forwarded as generationConfig.responseSchema - Gemini's
structured-output mode, which constrains decoding to actually match a
supplied JSON Schema. Checked against Google's own docs before writing
this: the correct field names are camelCase (responseMimeType,
responseSchema) - the generationConfig dict below was previously using
response_mime_type (snake_case), which is NOT the documented field name,
even though it had apparently been working (Google's API is evidently
lenient about this). Both fields are now written in the documented
camelCase form rather than relying on that leniency continuing to hold.
This does not remove any of the repair functions below - they stay as a
safety net for whichever caller doesn't pass a schema, or in case
Gemini's structured-output support (documented as only a SUBSET of full
OpenAPI/JSON Schema - some keywords may be silently ignored) has gaps for
a given schema - but the shot-breakdown stage (the only caller with a
JSON payload complex enough to have hit these bugs) now passes one, which
should make this entire repair list fire far less often going forward.

GEMINI_API_KEY IMPORT CRASH FIX (2026-09-14) - CONFIRMED, root cause of
every single Video Generation workflow failure: GEMINI_KEY was read at
MODULE IMPORT TIME via os.environ["GEMINI_API_KEY"] (a bare dict lookup,
raises KeyError if absent). video_generation.py imports this module only
for retryable_request/SUPABASE_URL/HEADERS - it has never called call_llm
or needed Gemini at all (it uses Agnes for video, not Gemini) - and
video_generation.yml correctly has no GEMINI_API_KEY secret configured,
since it genuinely doesn't need one. The result: `from llm_client import
retryable_request, SUPABASE_URL, HEADERS` crashed with an uncaught
KeyError on the very first line of video_generation.py, before main() -
or even the module's own try/except around get_ready_scripts() from the
2026-09-14 INFRA-CRASH FIX - ever ran. Every prior fix aimed at
video_generation.py's own logic was correct but irrelevant, since the
process never got far enough to reach any of it. Fixed by making
GEMINI_KEY/GEMINI_URL lazy: the module-level constant is now
os.environ.get("GEMINI_API_KEY") (None if absent, no crash), and
call_llm() itself raises a clear, specific RuntimeError up front if it's
None - so a script that actually needs Gemini still fails loudly and
immediately if the key is missing, but a script that merely imports this
module for its Supabase helpers is completely unaffected either way.

FAILURE-WINDOW LOGGING FIX (2026-09-19): confirmed live - a run hit
"Expecting value: line 217 column 24 (char 12915)" in extract_json() and
every one of the 8 repairs still failed, but the failure log only printed
the first 1500 chars of the candidate - useless for an error 12,915 chars
in, hiding the actual evidence needed to diagnose this new malformed-JSON
shape (distinct from the unquoted-key/trailing-comma cases already fixed
above). Per this repo's standing rule against fixing without live
evidence, no new repair regex is being guessed at here. extract_json()'s
total-failure log now also prints a window of text centered on the
JSONDecodeError's own reported character offset (its .pos attribute) -
the actual text at and around the real failure point, wherever in the
candidate that falls - so the next occurrence of this shape gives real
evidence instead of another guess from an offset alone.
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

# GEMINI_API_KEY IMPORT CRASH FIX (2026-09-14): see module docstring. Was
# os.environ["GEMINI_API_KEY"] (crashes on import if unset) - now a lazy,
# non-crashing lookup. Any caller that actually needs Gemini gets a clear,
# specific error from call_llm() itself instead of an opaque KeyError
# thrown from deep inside an unrelated import chain.
GEMINI_KEY = os.environ.get("GEMINI_API_KEY")
GEMINI_MODEL = "gemini-3.5-flash-lite"
GEMINI_URL = (
    f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GEMINI_KEY}"
    if GEMINI_KEY else None
)

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


def call_llm(prompt, response_schema=None):
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
    shot list fits in a single call. responseMimeType forces native JSON
    output so it's never wrapped in markdown fences.

    SCHEMA-CONSTRAINED GENERATION (2026-09-13): optional response_schema
    param, forwarded as generationConfig.responseSchema - see module
    docstring, including the camelCase field-name correction made at the
    same time. None by default so every existing caller (narration_stage.py,
    quality_checker.py) is unaffected; only shot_breakdown_stage.py passes
    one so far.

    GEMINI_API_KEY IMPORT CRASH FIX (2026-09-14): GEMINI_KEY/GEMINI_URL are
    now lazily-None if the env var is absent (see module docstring) rather
    than crashing on import - so this function raises the clear error
    instead, at the point something actually tried to use Gemini."""
    if not GEMINI_KEY:
        raise RuntimeError(
            "call_llm() was invoked but GEMINI_API_KEY is not set in this environment - "
            "add it as a secret to whichever workflow's env block is calling this."
        )

    generation_config = {
        "responseMimeType": "application/json",
        "maxOutputTokens": GEMINI_MAX_OUTPUT_TOKENS,
    }
    if response_schema is not None:
        generation_config["responseSchema"] = response_schema

    body = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": generation_config,
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
    near the end of the response.

    MALFORMED-KEY VARIANT FIX (2026-09-13, confirmed - see module
    docstring): widened to also catch a key with a STRAY TRAILING quote
    and no leading quote (e.g. `sfx_cue": "..."`), which the original
    stricter regex (identifier directly followed by whitespace-then-colon)
    could not match. The optional `"?` around the identifier consumes
    either shape - and consumes a pre-existing correctly-placed quote pair
    too - so the substitution always re-emits exactly one well-formed
    quoted key regardless of which malformed (or already-correct) shape
    it started as. This only touches an identifier immediately following
    an opening `{` or a `,` (the only positions a JSON key can legally
    appear), so it will not touch identifiers that happen to appear inside
    already-quoted string values."""
    return re.sub(r'([{,]\s*)"?([A-Za-z_][A-Za-z0-9_]*)"?(\s*:)', r'\1"\2"\3', text)


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
    or together in the same response.

    MALFORMED-KEY VARIANT FIX (2026-09-13): _quote_unquoted_keys()'s regex
    was widened (see its docstring) rather than adding a 9th/10th repair
    entry - it now covers both the fully-unquoted and stray-trailing-quote
    shapes under the same repair name, so the existing 8-entry attempts
    list below did not need to change.

    FAILURE-WINDOW LOGGING FIX (2026-09-19): confirmed live - a run hit
    "Expecting value: line 217 column 24 (char 12915)" and every one of
    the 8 repairs still failed, but the existing log only printed the
    first 1500 chars of the candidate - useless for an error 12,915 chars
    in, hiding the actual evidence needed to diagnose this new malformed-
    JSON shape (distinct from the unquoted-key/trailing-comma cases already
    fixed). Per this repo's standing rule against fixing without live
    evidence, no new repair is being guessed at here. Instead: on total
    failure, the log now also prints a window centered on the
    JSONDecodeError's own reported character offset (via its .pos
    attribute) - the actual text at and around the real failure point -
    regardless of how far into the candidate that is, so the next
    occurrence gives real evidence instead of another guess from an
    offset alone."""
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
                print(f"[extract_json] raw candidate failed to parse; repair '{label}' fixed it.")
            return parsed
        except json.JSONDecodeError as e:
            last_error = e
            continue

    # FAILURE-WINDOW LOGGING FIX (2026-09-19): print the real text around
    # the actual reported failure offset, not just the start of the
    # candidate - the start is often nowhere near where parsing broke.
    print(f"[extract_json] all repair attempts failed ({last_error}).")
    if last_error is not None and hasattr(last_error, "pos"):
        pos = last_error.pos
        window_start = max(0, pos - 300)
        window_end = min(len(candidate), pos + 300)
        print(
            f"[extract_json] text around reported failure offset (char {pos}), "
            f"showing chars {window_start}-{window_end}: "
            f"{candidate[window_start:window_end]!r}"
        )
    print(f"[extract_json] raw candidate (first 1500 chars, for overall shape context): {candidate[:1500]!r}")
    raise last_error
