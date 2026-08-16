"""
Marius Command Center - Script Writing Agent
Takes the oldest pending topic and turns it into a full narration script
plus a shot-by-shot visual production plan for "Erased."

PROVIDER SWITCH (2026-08-06): OpenRouter's free-tier request cap was being
exhausted, causing sustained 429s. First fix kept OpenRouter as a fallback
behind Gemini. Zia then asked directly why keep a provider that's already
proven unreliable at all, even as a fallback - fair point, since a run that
falls through to OpenRouter just re-hits the same rate-limit wall. Removed
OpenRouter entirely. Gemini (same free key/approach TDP's
generate_script.py already uses successfully) is now the ONLY provider.
Requires the GEMINI_API_KEY secret in this repo (already added).

CONTENT-RETRY BACKOFF FIX (2026-08-15): previously, a content/validation
failure (bad word count, duplicate shots, etc.) retried immediately with
ZERO wait - only infra failures (network/429 errors inside call_llm) had
backoff. With 5 topics x up to 3 content attempts each, this could burst
10-15+ Gemini calls within the first minute of a run, blowing through
free-tier Gemini's ~10-15 RPM ceiling almost immediately - after which
every subsequent call in that run also 429'd, since the per-minute window
doesn't clear for 60s. Confirmed via GitHub issue history: the last real
"Script Writing workflow failed" issue was Aug 9, but zero scripts saved
since - because when all 5 topics hit InfraFailure, main() exits cleanly
(code 0), so the failure never surfaces as a GitHub issue. Added a real
sleep between content attempts below to stop the self-inflicted burst.

PROVIDER SWITCH (2026-08-15): Gemini removed, Groq is now the ONLY provider.
Gemini's free-tier RPM ceiling (~10-15 RPM) kept getting blown through by
this script's own retry bursts even with the 25s backoff fix above. Groq's
free tier (30 RPM, 12,000 TPM, 1,000 requests/day on llama-3.3-70b-versatile)
gives a materially higher per-minute ceiling, and its 128K context window
comfortably fits this script's large prompt + long narration + 60-85 shot
JSON output - unlike Cerebras, whose free tier is capped at 8,192 tokens
total (input+output combined) and would fail on nearly every real request
here. Requires the GROQ_API_KEY secret in this repo (get one free, no
credit card, at console.groq.com).

TWO-STAGE GENERATION (2026-08-15): live data showed a consistent pattern -
narration_text landing at 200-550 words against the 1500-word floor, on the
SAME call that also had to produce a full 60-85 shot structured JSON
breakdown. Root cause: asking one model call to write 1700+ words of prose
AND decompose it into a large structured shot list spends the model's
effective output budget on the shot list, cutting the narration short. Split
into two calls: (1) generate_narration() writes ONLY the narration, and if
it comes back short, does a CONTINUATION call (feeds back what was written
and asks the model to continue seamlessly to the target length) instead of
discarding and starting over - continuation is far more reliable for
hitting a hard word floor than a fresh retry. (2) generate_shot_breakdown()
takes the now-confirmed-length narration and builds setting_and_characters,
hook_text, music_mood, and the shot_list from it. This also means a narration
that already passed validation is never thrown away just because the shot
list failed a check - only the shot-list stage retries in that case.

CHUNKED SHOT BREAKDOWN (2026-08-15): even after splitting narration from
shot-breakdown above, the shot-breakdown call ALONE was still structurally
too big for Groq's free tier - it embeds the full ~2,400-token narration
plus ~1,500-2,000 tokens of shot-writing rules as input, then asks for a
60-85 shot structured JSON array (150-250 output tokens per shot), landing
at 15,000-22,000 tokens in a single request - 25-85% over Groq's entire
12,000 TPM ceiling before generation even starts. No amount of retry/backoff
timing fixes this, because the very first attempt in a fresh 60-second
window is already too big to fit. Fix: generate_shot_breakdown() now splits
the narration into NUM_SHOT_CHUNKS roughly-equal, sentence-aligned pieces
and makes one small Groq call per chunk (each individually well under
12,000 TPM), spaced SHOT_CHUNK_CALL_DELAY_SECONDS apart so they land in
separate rate-limit windows instead of stacking. The first chunk's call
also produces the episode-wide setting_and_characters/hook_text/music_mood
anchor; later chunks are given that same anchor text to keep every shot
visually consistent. All chunk shot_lists are stitched together and
renumbered, then run through the exact same validate_and_normalize_shot_
response() checks (duplicates, zoom ratio, consecutive-subject, onscreen
text, etc.) as before - only how the request reaches Groq changed, not the
quality bar a shot list has to clear.

SUSPECTED-DAILY-QUOTA-EXHAUSTION EARLY ABORT (2026-08-15, later): a live run
showed every single Groq call 429ing from the very first topic onward, but
the logged x-ratelimit-remaining-requests (999-1000) and remaining-tokens
(12000, freshly reset) both looked essentially full/healthy - impossible if
per-minute RPM/TPM were the real constraint. Root cause: per Groq's own
documented header semantics, x-ratelimit-*-requests actually refers to RPD
(requests per DAY), not RPM, and Groq ALSO enforces a separate TPD
(tokens-per-day) cap that is NEVER exposed in any response header at all
(confirmed via Groq docs/community sources - commonly ~100K tokens/day for
llama-3.3-70b-versatile on free tier). This pipeline switched to the
chunked two-stage approach (multiple large calls per script) the SAME DAY,
on top of several earlier same-day test/fix cycles already hitting Groq -
very likely already exhausting the invisible daily token budget, which
only resets at UTC midnight regardless of any backoff/retry tuning here.
Previously, call_llm()'s 429 diagnostic logging only surfaced the
per-minute/RPD headers, which actively look healthy/misleading in exactly
this scenario, and main() would burn ~10-15 minutes per run blindly
retrying 5 topics x 4 infra attempts each, all doomed until the daily
reset. Fix: detect the "high remaining requests+tokens but still 429"
signature as SuspectedDailyQuotaExhausted and abort the ENTIRE run
immediately with a clear diagnostic, instead of retrying uselessly. This
does not fix the underlying cause (nothing can succeed again until Groq's
daily reset) - if this keeps recurring, the real fix is reducing total
tokens/script (fewer/smaller chunked shot-breakdown calls), since a paid
Groq tier is not allowed under the standing no-spend-until-$5,000-revenue
rule.

TOKEN-BUDGET TRIM (2026-08-17): the Aug 16 fix already cut shots per script
(MIN_SHOTS 60->25, MAX_SHOTS 85->35, NUM_SHOT_CHUNKS 3->2), but zero new
scripts had landed since Aug 6 as of this edit - still consistent with the
invisible Groq TPD cap above being hit before a script completes. This is
the next lever flagged in the handoff doc: trim narration's own token cost
too. Lowered NARRATION_TARGET_WORDS 1800->1600 (still comfortably above the
1500-word floor) and NARRATION_MAX_CONTINUATIONS 3->2 (each continuation
round is a full extra Groq call). Both reduce worst-case tokens spent
before a script completes, without changing the acceptance bar.
"""

import os
import re
import json
import time
import requests
from collections import Counter

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SECRET_KEY"]
GROQ_KEY = os.environ["GROQ_API_KEY"]

HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
}

MAX_RETRIES = 2
MIN_SHOTS = 25
MAX_SHOTS = 35
MAX_GENERATION_ATTEMPTS = 3
MAX_INFRA_ATTEMPTS = 4
MAX_HOOK_TEXT_CHARS = 40
MAX_HOOK_TEXT_WORDS = 5
MIN_SETTING_CHARS = 40
MAX_SETTING_CHARS = 900
MIN_NARRATION_WORDS = 1500
MAX_SHOT_REPEAT_COUNT = 2
CONTENT_RETRY_WAIT_SECONDS = 25

NARRATION_MAX_ATTEMPTS = 3
NARRATION_MAX_CONTINUATIONS = 2
NARRATION_TARGET_WORDS = 1600

# CHUNKED SHOT BREAKDOWN (2026-08-15): see module docstring. Splitting one
# 60-85 shot request (15,000-22,000 tokens) into 3 smaller requests keeps
# each call comfortably under Groq's 12,000 TPM free-tier ceiling.
NUM_SHOT_CHUNKS = 2
CHUNK_MIN_SHOTS = MIN_SHOTS // NUM_SHOT_CHUNKS
CHUNK_MAX_SHOTS = -(-MAX_SHOTS // NUM_SHOT_CHUNKS)  # ceil division
SHOT_CHUNK_CALL_DELAY_SECONDS = 20

GROQ_MODEL = "llama-3.3-70b-versatile"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
# TRUNCATED-JSON FIX (2026-08-15 evening): no max_tokens was ever set on the
# Groq request, so a large shot-breakdown segment (~29 shots of structured
# JSON) could get silently cut off mid-object by Groq's own default output
# cap - producing exactly the "Expecting ',' delimiter" parse errors seen on
# live runs. Setting this explicitly, well above what any single call here
# needs, removes that as a failure mode entirely. response_format forces
# Groq's native JSON mode so output is never wrapped in markdown fences or
# truncated by a stray non-JSON preamble.
GROQ_MAX_TOKENS = 8000
GROQ_RESPONSE_FORMAT = {"type": "json_object"}
# BURST-RISK FIX (2026-08-15 evening): every other retry path in this file
# waits between Groq calls except the narration continuation loop, which
# fired back-to-back with zero delay. Closing that gap so this script never
# self-inflicts a burst against Groq's 30 RPM ceiling.
CONTINUATION_CALL_DELAY_SECONDS = 10

# SUSPECTED-DAILY-QUOTA-EXHAUSTION FIX (2026-08-15, later): see module
# docstring. If a 429 comes back with BOTH remaining-requests and
# remaining-tokens still above these fractions of their reported limits,
# the per-minute/RPD headers are lying about being the real constraint -
# treat it as the invisible daily token (TPD) cap instead, which only
# clears at UTC midnight no matter how this script backs off.
SUSPECTED_DAILY_QUOTA_REMAINING_RATIO = 0.5

EXAMPLE_HOOK_TEXT = "312 DIARIES. ONE BOMB. GONE IN SECONDS."

CTA_KEYWORDS = (
    "comment", "comments", "subscribe", "share this", "share it",
    "like this", "like and", "tell us", "let us know", "hit follow",
    "hit that", "follow along", "leave a", "drop a",
)
CTA_SEARCH_WINDOW_CHARS = 700

VALID_SHOT_TYPES = {
    "wide", "medium", "close_up", "extreme_close_up", "establishing", "detail_insert"
}
VALID_CAMERA_MOVEMENTS = {
    "static", "pan_left", "pan_right", "tilt_up", "tilt_down", "zoom_in", "zoom_out",
    "push_in", "pull_out", "dolly_in", "dolly_out", "tracking", "crash_zoom",
    "whip_pan", "handheld_shake", "orbit", "drone_rise", "drone_descend",
    "parallax", "focus_pull", "dutch_angle", "snap_zoom", "speed_ramp",
}
VALID_LENS_EFFECTS = {
    "shallow_depth_of_field", "lens_flare", "film_grain", "none"
}

ZOOM_FAMILY_MOVEMENTS = {"push_in", "crash_zoom", "zoom_in", "snap_zoom", "dolly_in"}
MAX_ZOOM_SHOT_RATIO = 0.32
MAX_CONSECUTIVE_ZOOM_SHOTS = 2

MAX_CONSECUTIVE_SAME_SUBJECT = 3
MAX_SUBJECT_SHOT_RATIO = 0.45

CONTINUATION_BANNED_PHRASES = (
    "continues to", "continues ", "then walks", "then runs", "then turns",
    "then opens", "then reaches", "then picks", "then lifts", "then carries",
    "then hands", "then pours", "still walking", "still running", "still turning",
    "begins to walk", "begins to run", "begins to turn", "begins to open",
    "starts to walk", "starts to run", "starts to turn", "starts to open",
    "walking toward", "walking to ", "walks toward", "walks to ",
    "running toward", "running to ", "runs toward", "runs to ",
    "turning to", "turns to face", "reaching for", "reaches for",
    "picks up and carries", "lifts and carries", "carries the",
    "hands over the", "pours the", "opens the door and", "proceeds to",
)

LOITERING_BANNED_PHRASES = (
    "standing around", "standing there", "standing nearby", "standing idly",
    "just standing", "simply standing", "standing quietly with no",
    "waiting there", "waiting around", "sitting there doing nothing",
    "looking around aimlessly", "with nothing in particular",
)

ONSCREEN_TEXT_KEYWORDS = (
    "newspaper", "letter", "document", "sign", "headline", "inscription",
    "poster", "map", "book", "plaque", "telegram", "postcard", "banner",
    "ledger", "diary", "certificate", "gravestone", "tombstone",
)

RETRYABLE_NETWORK_EXCEPTIONS = (
    requests.exceptions.ChunkedEncodingError,
    requests.exceptions.ConnectionError,
    requests.exceptions.Timeout,
)
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


class InfraFailure(RuntimeError):
    """Raised when Groq never returned a usable response within the infra
    retry budget - meaning the topic's actual content was never evaluated
    at all. This must NOT be treated the same as a real content failure:
    the topic itself did nothing wrong, so it must stay 'pending' for the
    next scheduled run to retry once Groq's quota/availability recovers,
    instead of being permanently blacklisted as generation_failed."""
    pass


class SuspectedDailyQuotaExhausted(RuntimeError):
    """Raised (2026-08-15, later fix) when a 429 comes back with
    remaining-requests and remaining-tokens headers BOTH still showing
    plenty of headroom - meaning the visible per-minute/RPD limits are not
    the real constraint. Groq also enforces an undocumented, header-invisible
    TPD (tokens-per-day) cap that only resets at UTC midnight. Unlike
    InfraFailure, this should NOT be retried within the same run - every
    further call will hit the exact same wall, so the whole run should abort
    immediately instead of burning ~10-15 minutes on doomed retries across
    every remaining topic."""
    pass


def _parse_ratio(remaining_str, limit_str):
    try:
        remaining = float(remaining_str)
        limit = float(limit_str)
        if limit <= 0:
            return None
        return remaining / limit
    except (TypeError, ValueError):
        return None


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


def get_pending_topics(limit=5):
    """HEAD-OF-LINE FIX (2026-08-14): previously fetched only the single
    oldest pending topic. If that topic hit InfraFailure, main() returned
    cleanly (exit 0, no GitHub issue) and left it 'pending' for the next
    run to retry - which then hit the exact same topic again. Confirmed
    live: 'The Manzanar Teacher Who Taught in Secret' (created 2026-07-17)
    sat retried on every 12h run for over a week while 240+ newer pending
    topics never got a turn. Mirrors the same fix already proven in
    video_generation.py's get_ready_scripts()."""
    resp = retryable_request(
        "GET",
        f"{SUPABASE_URL}/rest/v1/topics?status=eq.pending&order=created_at.asc&limit={limit}",
        headers=HEADERS,
        timeout=30,
    )
    return resp.json()


def call_llm(prompt):
    """PROVIDER SWITCH (2026-08-15): Groq only, using llama-3.3-70b-versatile.
    OpenAI-compatible chat completions endpoint - 30 RPM / 12,000 TPM /
    1,000 requests per day free tier, no credit card, 128K context window
    (comfortably fits this script's large prompt + long JSON output)."""
    body = json.dumps({
        "model": GROQ_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": GROQ_MAX_TOKENS,
        "response_format": GROQ_RESPONSE_FORMAT,
    }).encode()
    last_error = None
    for attempt in range(MAX_RETRIES):
        try:
            resp = requests.post(
                GROQ_URL,
                data=body,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {GROQ_KEY}",
                },
                timeout=120,
            )
        except RETRYABLE_NETWORK_EXCEPTIONS as e:
            wait = (attempt + 1) * 15
            print(f"Groq network error ({e.__class__.__name__}: {e}), waiting {wait}s before retry...")
            last_error = e
            time.sleep(wait)
            continue

        if resp.status_code == 429:
            wait = (attempt + 1) * 15
            remaining_requests = resp.headers.get('x-ratelimit-remaining-requests', '?')
            limit_requests = resp.headers.get('x-ratelimit-limit-requests', '?')
            remaining_tokens = resp.headers.get('x-ratelimit-remaining-tokens', '?')
            limit_tokens = resp.headers.get('x-ratelimit-limit-tokens', '?')
            # DIAGNOSTIC FIX (2026-08-15 evening): previously logged nothing
            # but "rate limited" - impossible to tell RPM vs TPM vs RPD from
            # that alone. Groq returns the real remaining budget on every
            # response; log it so the next failure is diagnosable from the
            # Actions log instead of guessed at.
            print(
                f"Groq rate limited (429) - "
                f"remaining requests: {remaining_requests} "
                f"(resets in {resp.headers.get('x-ratelimit-reset-requests', '?')}), "
                f"remaining tokens: {remaining_tokens} "
                f"(resets in {resp.headers.get('x-ratelimit-reset-tokens', '?')}). "
                f"Waiting {wait}s before retry..."
            )

            # SUSPECTED-DAILY-QUOTA-EXHAUSTION FIX (2026-08-15, later): see
            # module docstring and class docstring above. If the headers
            # Groq itself just sent us show plenty of headroom on BOTH
            # remaining-requests and remaining-tokens, this 429 cannot be
            # explained by the visible per-minute/RPD limits - it's almost
            # certainly the invisible daily token (TPD) cap, which will not
            # clear until UTC midnight no matter how long we wait/retry
            # here. Abort immediately instead of wasting the local backoff.
            req_ratio = _parse_ratio(remaining_requests, limit_requests)
            tok_ratio = _parse_ratio(remaining_tokens, limit_tokens)
            if (
                req_ratio is not None and req_ratio > SUSPECTED_DAILY_QUOTA_REMAINING_RATIO
                and tok_ratio is not None and tok_ratio > SUSPECTED_DAILY_QUOTA_REMAINING_RATIO
            ):
                raise SuspectedDailyQuotaExhausted(
                    f"Got 429 but remaining-requests ({remaining_requests}/{limit_requests}) and "
                    f"remaining-tokens ({remaining_tokens}/{limit_tokens}) both still show plenty of "
                    f"headroom - this is very likely Groq's undocumented daily token (TPD) cap, not "
                    f"real-time RPM/TPM throttling. TPD only resets at UTC midnight; no retry/backoff "
                    f"here can fix this today."
                )

            last_error = resp
            time.sleep(wait)
            continue

        try:
            resp.raise_for_status()
        except requests.exceptions.HTTPError as e:
            wait = (attempt + 1) * 15
            print(f"Groq HTTP error {resp.status_code} ({e}): {resp.text[:300]}, waiting {wait}s before retry...")
            last_error = resp
            time.sleep(wait)
            continue

        try:
            return resp.json()["choices"][0]["message"]["content"]
        except (requests.exceptions.JSONDecodeError, KeyError, IndexError) as e:
            wait = (attempt + 1) * 15
            print(f"Groq response envelope malformed/unparseable ({e}), waiting {wait}s before retry...")
            last_error = e
            time.sleep(wait)
            continue

    raise RuntimeError(f"Groq still failing after {MAX_RETRIES} attempts: {last_error}")


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


def narration_has_engagement_cta(narration_text):
    if not narration_text:
        return False
    window = narration_text[-CTA_SEARCH_WINDOW_CHARS:].lower()
    return any(keyword in window for keyword in CTA_KEYWORDS)


# ---------------------------------------------------------------------------
# STAGE 1: NARRATION ONLY
# ---------------------------------------------------------------------------

def build_narration_prompt(title, angle):
    return f"""You are the head writer for "Erased," a YouTube documentary
channel telling real, historically documented true stories of ordinary people
caught in extraordinary historical moments, whose names history left out.

Episode topic: {title}
Angle: {angle}

Your ONLY job in this response is to write the full narration script. Do not
write anything else - no shot list, no JSON metadata, nothing but the
narration itself, wrapped in the JSON format specified at the bottom.

OPENING HOOK - this is the most important part of the script. The first 8
seconds of narration determine whether the viewer stays or leaves, so follow
this exact structure for the opening lines:

1. STAKE (first 1-2 sentences): State the single most dramatic, concrete fact
   of the story immediately. Do NOT say "today we'll look at" or "this is the
   story of" or introduce the channel/topic first. Lead with the fact itself,
   as if the viewer already knows what's at risk. Use a real, specific number,
   name, or consequence from the story - not a vague tease.
   Bad: "Today we're going to talk about a forgotten hero of history."
   Good: "140,000 men dug the trenches of the Western Front - and history
   erased every one of their names."

2. VISUAL LOCK (next 1 sentence): A concrete, specific image or moment that
   proves the stake is real - not generic scene-setting.

3. CURIOSITY GAP (next 1-2 sentences): Pose the specific question the rest of
   the episode answers, so the viewer needs to keep watching to find out.

Only after these opening beats should the script settle into the normal
narrative arc. No channel intro, no "welcome back," no restating the title -
go straight into the stake.

LENGTH IS A HARD REQUIREMENT: write a complete 10-12 minute narration script
of AT LEAST {MIN_NARRATION_WORDS} words - target {NARRATION_TARGET_WORDS}
words. This is not a suggestion or a rough guide - a narration under
{MIN_NARRATION_WORDS} words will be rejected outright and you will be asked
to continue writing from where you stopped. Do not stop early. Do not
summarize the rest of the story to wrap up quickly. Build a full narrative
arc: setup and stakes, rising complications, the core dramatic turn, the
emotional climax, and a reflective closing line - give each of these real
space, not a sentence or two each. If you don't know enough documented detail
about this specific story to reach the target, expand on the real historical
context, setting, sensory detail, and the emotional experience of the people
involved - do not pad with repetition or filler, and do not write a short
script assuming it will be extended later.

CALL TO ACTION - THIS IS REQUIRED, NOT OPTIONAL: immediately after the
emotional climax of the story and before the final reflective closing line,
you MUST write one natural, in-voice sentence encouraging the viewer to
like, subscribe, and share their own thoughts in the comments so more of
these erased stories get told. Every single script must include this - a
script with no call to action will be rejected and regenerated. It must
NOT be a generic "smash that like button" line - write it in the tone and
voice of this specific episode, using imagery or phrasing that echoes the
story just told, and vary the wording from episode to episode. It is part
of the narration itself, not a separate field. Use natural language that
clearly asks the viewer to like/share/subscribe and to respond in the
comments (for example, weaving in words like "comment," "share," or
"subscribe" naturally) so the ask is unambiguous, not just implied.

Return ONLY valid JSON, no other text, no markdown fences, in this exact
format:

{{
  "narration_text": "The full narration script as one string, written to be read aloud, at least {MIN_NARRATION_WORDS} words."
}}"""


def build_narration_continuation_prompt(title, angle, so_far, words_so_far):
    return f"""You are continuing a narration script for "Erased," a YouTube
documentary channel, that you started writing but stopped too early.

Episode topic: {title}
Angle: {angle}

Here is everything you have written so far ({words_so_far} words - the
target is at least {MIN_NARRATION_WORDS}, ideally {NARRATION_TARGET_WORDS}):

---
{so_far}
---

Continue writing EXACTLY where this leaves off. Do not repeat or rephrase
anything already written above. Do not restart the story or re-introduce it.
Pick up mid-narrative and keep building: more rising complications, sensory
and historical detail, the dramatic turn, the emotional climax, and (if not
already present above) end with the required call-to-action sentence
(naturally asking the viewer to like/subscribe/comment, in the voice of this
story) followed by a reflective closing line. Write enough new material to
bring the total well past {MIN_NARRATION_WORDS} words.

Return ONLY valid JSON, no other text, no markdown fences, in this exact
format:

{{
  "continuation_text": "Only the NEW text that continues on from where the narration above left off - do not repeat any of the text already given to you."
}}"""


def generate_narration(title, angle):
    """Stage 1: produce a narration that already clears the word-count and
    CTA bar before the (expensive, easy-to-fail) shot-list stage ever runs.
    A short first draft is extended via continuation calls rather than
    thrown away - continuation is far more reliable than a fresh retry for
    hitting a hard word floor, since the model is extending known-good text
    instead of trying to nail the whole length in one shot."""
    infra_attempt = 0
    content_attempt = 0
    last_reason = None
    ever_reached_content = False

    while content_attempt < NARRATION_MAX_ATTEMPTS:
        try:
            raw = call_llm(build_narration_prompt(title, angle))
        except SuspectedDailyQuotaExhausted:
            # FIX (2026-08-15, later): must NOT be swallowed by the generic
            # RuntimeError/infra-retry handling below - propagate straight
            # up so main() can abort the whole run instead of retrying.
            raise
        except RuntimeError as e:
            infra_attempt += 1
            last_reason = f"Groq call failed: {e}"
            print(f"[narration] Infra retry {infra_attempt}/{MAX_INFRA_ATTEMPTS} failed - {last_reason}")
            if infra_attempt >= MAX_INFRA_ATTEMPTS:
                break
            time.sleep(infra_attempt * 20)
            continue

        ever_reached_content = True
        content_attempt += 1
        try:
            parsed = extract_json(raw)
            narration = (parsed.get("narration_text") or "").strip()
        except (ValueError, json.JSONDecodeError) as e:
            last_reason = f"JSON parse failed: {e}"
            print(f"[narration] Attempt {content_attempt}/{NARRATION_MAX_ATTEMPTS} failed - {last_reason}")
            if content_attempt < NARRATION_MAX_ATTEMPTS:
                time.sleep(CONTENT_RETRY_WAIT_SECONDS)
            continue

        if not narration:
            last_reason = "narration_text missing/empty"
            print(f"[narration] Attempt {content_attempt}/{NARRATION_MAX_ATTEMPTS} failed - {last_reason}")
            if content_attempt < NARRATION_MAX_ATTEMPTS:
                time.sleep(CONTENT_RETRY_WAIT_SECONDS)
            continue

        # Continuation loop: extend a short draft instead of discarding it.
        continuation_rounds = 0
        while (
            len(narration.split()) < MIN_NARRATION_WORDS
            and continuation_rounds < NARRATION_MAX_CONTINUATIONS
        ):
            continuation_rounds += 1
            words_so_far = len(narration.split())
            print(f"[narration] Draft is {words_so_far} words, below {MIN_NARRATION_WORDS} - "
                  f"continuation round {continuation_rounds}/{NARRATION_MAX_CONTINUATIONS}")
            time.sleep(CONTINUATION_CALL_DELAY_SECONDS)
            try:
                raw_cont = call_llm(build_narration_continuation_prompt(title, angle, narration, words_so_far))
                parsed_cont = extract_json(raw_cont)
                cont_text = (parsed_cont.get("continuation_text") or "").strip()
            except SuspectedDailyQuotaExhausted:
                raise
            except (RuntimeError, ValueError, json.JSONDecodeError) as e:
                print(f"[narration] Continuation round {continuation_rounds} failed ({e}), stopping continuation "
                      f"for this draft")
                break
            if cont_text:
                narration = narration.rstrip() + "\n\n" + cont_text.strip()

        word_count = len(narration.split())
        if word_count < MIN_NARRATION_WORDS:
            last_reason = f"narration still only {word_count} words after {continuation_rounds} continuation round(s)"
            print(f"[narration] Attempt {content_attempt}/{NARRATION_MAX_ATTEMPTS} failed - {last_reason}")
            if content_attempt < NARRATION_MAX_ATTEMPTS:
                time.sleep(CONTENT_RETRY_WAIT_SECONDS)
            continue

        if not narration_has_engagement_cta(narration):
            last_reason = "narration is missing the required like/subscribe/comment call-to-action near the end"
            print(f"[narration] Attempt {content_attempt}/{NARRATION_MAX_ATTEMPTS} failed - {last_reason}")
            if content_attempt < NARRATION_MAX_ATTEMPTS:
                time.sleep(CONTENT_RETRY_WAIT_SECONDS)
            continue

        print(f"[narration] Confirmed at {word_count} words.")
        return narration

    if not ever_reached_content:
        raise InfraFailure(
            f"Groq never returned a usable response after {infra_attempt} infra retries during "
            f"narration stage. Last reason: {last_reason}"
        )
    raise RuntimeError(f"Narration generation failed after {content_attempt} content attempts. Last reason: {last_reason}")


# ---------------------------------------------------------------------------
# STAGE 2: SHOT BREAKDOWN (from a confirmed-length narration, in chunks)
# ---------------------------------------------------------------------------

def split_narration_into_chunks(narration_text, num_chunks):
    """Splits narration into num_chunks pieces, breaking only at sentence
    boundaries (never mid-sentence) and balancing word count across pieces
    as evenly as possible. Each chunk becomes its own, much smaller, Groq
    shot-breakdown call."""
    sentences = re.split(r"(?<=[.!?])\s+", narration_text.strip())
    sentences = [s for s in sentences if s.strip()]

    if len(sentences) <= num_chunks:
        return [s.strip() for s in sentences] or [narration_text.strip()]

    total_words = sum(len(s.split()) for s in sentences)
    target_words = total_words / num_chunks

    chunks = []
    current = []
    current_words = 0
    for sentence in sentences:
        current.append(sentence)
        current_words += len(sentence.split())
        if current_words >= target_words and len(chunks) < num_chunks - 1:
            chunks.append(" ".join(current).strip())
            current = []
            current_words = 0
    if current:
        chunks.append(" ".join(current).strip())

    return chunks


def normalize_shot(shot, index):
    shot_type = shot.get("shot_type")
    if shot_type not in VALID_SHOT_TYPES:
        shot_type = "medium"

    camera_movement = shot.get("camera_movement")
    if camera_movement not in VALID_CAMERA_MOVEMENTS:
        camera_movement = "static"

    lens_effect = shot.get("lens_effect")
    if lens_effect not in VALID_LENS_EFFECTS:
        lens_effect = "none"

    return {
        "shot_number": shot.get("shot_number", index + 1),
        "visual_description": shot.get("visual_description", ""),
        "narration_excerpt": shot.get("narration_excerpt", ""),
        "shot_type": shot_type,
        "camera_movement": camera_movement,
        "camera_reason": shot.get("camera_reason", ""),
        "lens_effect": lens_effect,
        "sfx_cue": shot.get("sfx_cue", ""),
        "primary_subject": (shot.get("primary_subject") or "").strip(),
        "required_onscreen_text": (shot.get("required_onscreen_text") or "").strip(),
    }


def normalize_hook_text(result):
    hook_text = (result.get("hook_text") or "").strip()
    if hook_text:
        return hook_text[:MAX_HOOK_TEXT_CHARS].rstrip()

    shot_list = result.get("shot_list") or []
    if shot_list:
        fallback = (shot_list[0].get("narration_excerpt") or "").strip()
        if len(fallback) <= MAX_HOOK_TEXT_CHARS:
            return fallback
        if fallback:
            return fallback[:MAX_HOOK_TEXT_CHARS].rsplit(" ", 1)[0] + "..."

    return ""


def hook_text_matches_prompt_example(hook_text):
    def _simplify(s):
        return "".join(ch.lower() for ch in s if ch.isalnum())

    return _simplify(hook_text) == _simplify(EXAMPLE_HOOK_TEXT)


def hook_text_too_long_to_glance(hook_text):
    word_count = len(hook_text.split())
    return word_count > MAX_HOOK_TEXT_WORDS


def hook_text_matches_story(hook_text, narration_text):
    if not hook_text or not narration_text:
        return False

    narration_lower = narration_text.lower()
    hook_words = [w.strip(".,!?\"'").lower() for w in hook_text.split()]
    meaningful_words = [w for w in hook_words if len(w) >= 4]

    if not meaningful_words:
        return True

    return any(w in narration_lower for w in meaningful_words)


def find_duplicate_shots(normalized_shots):
    pair_counts = Counter(
        ((s["visual_description"] or "").strip().lower(), (s["narration_excerpt"] or "").strip().lower())
        for s in normalized_shots
    )
    return [
        (visual, narration, count)
        for (visual, narration), count in pair_counts.items()
        if visual and count > MAX_SHOT_REPEAT_COUNT
    ]


def find_empty_shots(normalized_shots):
    return [
        i for i, s in enumerate(normalized_shots)
        if not (s["visual_description"] or "").strip() or not (s["narration_excerpt"] or "").strip()
    ]


def find_continuation_language_shots(normalized_shots):
    hits = []
    for i, s in enumerate(normalized_shots):
        desc = (s["visual_description"] or "").lower()
        for phrase in CONTINUATION_BANNED_PHRASES:
            if phrase in desc:
                hits.append((i, phrase))
                break
    return hits


def find_loitering_shots(normalized_shots):
    hits = []
    for i, s in enumerate(normalized_shots):
        desc = (s["visual_description"] or "").lower()
        for phrase in LOITERING_BANNED_PHRASES:
            if phrase in desc:
                hits.append((i, phrase))
                break
    return hits


def find_missing_onscreen_text_shots(normalized_shots):
    hits = []
    for i, s in enumerate(normalized_shots):
        desc = (s["visual_description"] or "").lower()
        if any(kw in desc for kw in ONSCREEN_TEXT_KEYWORDS) and not s["required_onscreen_text"]:
            hits.append(i)
    return hits


def find_dominant_subject(normalized_shots):
    subject_counts = Counter(
        s["primary_subject"].lower() for s in normalized_shots if s["primary_subject"]
    )
    if not subject_counts:
        return None
    subject, count = subject_counts.most_common(1)[0]
    ratio = count / len(normalized_shots)
    if ratio > MAX_SUBJECT_SHOT_RATIO:
        return subject, count, ratio
    return None


def find_excessive_consecutive_subject(normalized_shots):
    run_subject = None
    run_length = 0
    for i, s in enumerate(normalized_shots):
        subject = s["primary_subject"].lower()
        if subject and subject == run_subject:
            run_length += 1
        else:
            run_subject = subject
            run_length = 1 if subject else 0
        if run_length > MAX_CONSECUTIVE_SAME_SUBJECT:
            return i, run_subject, run_length
    return None


def validate_and_normalize_shot_response(result, narration_text):
    """Validates everything EXCEPT narration_text/CTA, since those were
    already confirmed during the narration stage before this is ever called.
    Runs on the FULL stitched shot list (all chunks combined), so every
    episode-wide check here (total shot count, zoom ratio, subject
    dominance, etc.) still applies exactly as before chunking was added."""
    setting_and_characters = (result.get("setting_and_characters") or "").strip()
    if len(setting_and_characters) < MIN_SETTING_CHARS:
        return False, (
            f"setting_and_characters missing or too short "
            f"({len(setting_and_characters)} chars, need at least {MIN_SETTING_CHARS}) - "
            f"must fix the real-world location/era/ethnicity and describe every "
            f"recurring character's appearance"
        )
    result["setting_and_characters"] = setting_and_characters[:MAX_SETTING_CHARS]

    shot_list = result.get("shot_list")
    if not isinstance(shot_list, list) or len(shot_list) == 0:
        return False, "missing or empty shot_list"

    if len(shot_list) < MIN_SHOTS or len(shot_list) > MAX_SHOTS:
        return False, f"shot count {len(shot_list)} outside {MIN_SHOTS}-{MAX_SHOTS} range"

    normalized_shots = [normalize_shot(s, i) for i, s in enumerate(shot_list)]

    empty_shots = find_empty_shots(normalized_shots)
    if empty_shots:
        return False, (
            f"{len(empty_shots)} of {len(normalized_shots)} shots have an empty "
            f"visual_description and/or narration_excerpt (first at shot index "
            f"{empty_shots[0]}) - every shot must have real content, do not pad "
            f"the list with placeholder shots just to reach {MIN_SHOTS} total; "
            f"split the real narration into more/finer shots instead"
        )

    duplicate_shots = find_duplicate_shots(normalized_shots)
    if duplicate_shots:
        worst_visual, _, worst_count = max(duplicate_shots, key=lambda d: d[2])
        return False, (
            f"{len(duplicate_shots)} shot(s) are repeated more than "
            f"{MAX_SHOT_REPEAT_COUNT} times instead of being distinct - worst case "
            f"repeated {worst_count} times ({worst_visual[:80]!r}...). This means the "
            f"shot list was padded by looping an earlier block of shots instead of "
            f"covering new narration - write more real, distinct shots covering the "
            f"full story instead of repeating any."
        )

    zoom_count = sum(
        1 for s in normalized_shots
        if s["camera_movement"] in ZOOM_FAMILY_MOVEMENTS or s["shot_type"] == "extreme_close_up"
    )
    zoom_ratio = zoom_count / len(normalized_shots)
    if zoom_ratio > MAX_ZOOM_SHOT_RATIO:
        return False, (
            f"too many zoomed-in shots: {zoom_count}/{len(normalized_shots)} "
            f"({zoom_ratio:.0%}) use a zoom-in-family movement or extreme_close_up, "
            f"over the {MAX_ZOOM_SHOT_RATIO:.0%} ceiling - spread in more wide/establishing shots"
        )

    consecutive_zoom = 0
    max_consecutive_zoom = 0
    for s in normalized_shots:
        if s["camera_movement"] in ZOOM_FAMILY_MOVEMENTS:
            consecutive_zoom += 1
            max_consecutive_zoom = max(max_consecutive_zoom, consecutive_zoom)
        else:
            consecutive_zoom = 0
    if max_consecutive_zoom > MAX_CONSECUTIVE_ZOOM_SHOTS:
        return False, (
            f"{max_consecutive_zoom} zoom-in-family shots in a row (max {MAX_CONSECUTIVE_ZOOM_SHOTS}) "
            f"- too claustrophobic back to back, spread zoom movements out through the episode"
        )

    continuation_hits = find_continuation_language_shots(normalized_shots)
    if continuation_hits:
        worst_i, worst_phrase = continuation_hits[0]
        return False, (
            f"{len(continuation_hits)} shot(s) describe an action IN PROGRESS or "
            f"continuing across a cut instead of an already-resolved end state "
            f"(first at shot {worst_i}, phrase {worst_phrase!r}) - every shot must "
            f"show the action already complete/stable (e.g. 'already holding the "
            f"letter', not 'reaches for the letter'). This causes objects to morph "
            f"mid-action and forces the next shot to fake-continue motion it never "
            f"actually generated."
        )

    loitering_hits = find_loitering_shots(normalized_shots)
    if loitering_hits:
        worst_i, worst_phrase = loitering_hits[0]
        return False, (
            f"{len(loitering_hits)} shot(s) describe a character just standing/"
            f"waiting/sitting with no active task (first at shot {worst_i}, phrase "
            f"{worst_phrase!r}) - every shot with a person in frame must anchor on "
            f"a specific ongoing task or intent, already mid-task (e.g. 'already "
            f"kneeling, mending a fishing net' not 'standing near the shore'). "
            f"A character present in frame with nothing to do reads as aimless "
            f"loitering on screen, not a purposeful, stable moment."
        )

    missing_text_hits = find_missing_onscreen_text_shots(normalized_shots)
    if missing_text_hits:
        return False, (
            f"{len(missing_text_hits)} shot(s) deliberately show a newspaper/letter/"
            f"sign/document/etc. (first at shot {missing_text_hits[0]}) but "
            f"required_onscreen_text is empty - either state the exact wording that "
            f"must appear, or rewrite visual_description so no readable text is the "
            f"focus of the shot."
        )

    excessive_subject = find_excessive_consecutive_subject(normalized_shots)
    if excessive_subject:
        idx, subject, run_length = excessive_subject
        return False, (
            f"'{subject}' is the primary_subject of {run_length} consecutive shots "
            f"ending at shot {idx} (max {MAX_CONSECUTIVE_SAME_SUBJECT}) - cut away to "
            f"a different subject, angle, or B-roll before returning to this "
            f"character, instead of holding on the same face shot after shot."
        )

    dominant_subject = find_dominant_subject(normalized_shots)
    if dominant_subject:
        subject, count, ratio = dominant_subject
        return False, (
            f"'{subject}' is the primary_subject of {count}/{len(normalized_shots)} shots "
            f"({ratio:.0%}), over the {MAX_SUBJECT_SHOT_RATIO:.0%} episode-wide ceiling - "
            f"even with cutaways breaking up consecutive runs, this character is in nearly "
            f"every scene, which doesn't read as a real documentary. Replace enough of "
            f"their shots with pure B-roll (landscapes, objects, documents, crowds, other "
            f"people mentioned in the story) so they're a strong presence, not the subject "
            f"of almost every single shot."
        )

    result["shot_list"] = normalized_shots
    result["music_mood"] = result.get("music_mood", "").strip() or (
        "Tense cinematic thriller score, sparse low piano and rising strings "
        "at the start, driving percussion and brass stabs building through "
        "the middle, explosive full-orchestra climax at the reveal, "
        "tapering to a quiet resolution."
    )
    result["hook_text"] = normalize_hook_text(result)

    if hook_text_matches_prompt_example(result["hook_text"]):
        return False, "hook_text copied the prompt's example verbatim instead of writing a real one"

    if hook_text_too_long_to_glance(result["hook_text"]):
        return False, f"hook_text is {len(result['hook_text'].split())} words - too long to read in a 2-second glance (max {MAX_HOOK_TEXT_WORDS})"

    if not hook_text_matches_story(result["hook_text"], narration_text):
        return False, f"hook_text {result['hook_text']!r} doesn't appear related to this story's narration"

    result["narration_text"] = narration_text
    return True, result


SHOT_RULES_BLOCK = f"""CINEMATIC DIRECTOR - shot list requirements:
This is a dense, sub-sentence level breakdown - a single narration sentence
should often span 2-3 separate shots, not one. Do not write sparse,
paragraph-level shots. Every "narration_excerpt" must be an exact, verbatim
substring taken from the NARRATION SEGMENT below, in order, covering it
start to finish.

EVERY SHOT MUST BE DISTINCT - THIS IS ALSO A HARD REQUIREMENT: every shot
must have its own real visual_description and narration_excerpt drawn from
a different part of the narration segment. NEVER repeat an earlier shot
(same visual_description and narration_excerpt) later in the list just to
reach the shot count - a script that repeats any shot more than twice will
be rejected and regenerated.

Every shot's "visual_description" must stay consistent with the
"setting_and_characters" anchor given below - same location/era/ethnicity,
and any recurring person described there must match their fixed appearance
in every shot they appear in. Do not introduce a different ethnicity,
region, or unplanned recurring character partway through.

DOCUMENTARY SHOT INDEPENDENCE (HARD RULE): write the shot list as a
documentary editor, not a movie storyboard. Every shot must be a complete,
independent visual composition that starts from an already-stable moment
and makes sense on its own, without depending on the shot before or after
it. Never write a shot as a continuation of physical motion from the
previous one, and never leave an action unresolved expecting the next shot
to finish it - each shot must reach a complete, stable end state within
itself (the door already open, the letter already unfolded, the cup
already set down). Do not use words like walking, running, turning,
opening, reaching, continues, then, next, still, or begins to when
describing what's happening RIGHT NOW in the shot - instead describe the
subject already in position: "standing beside the open door," "already
seated at the table," "holding the letter, already unfolded."

PURPOSEFUL STILLNESS, NOT LOITERING (HARD RULE): "already in position" does
NOT mean "just standing/sitting there with nothing to do." Every shot with a
person in frame must anchor them in a specific, concrete, already-in-progress
task or intent - not a static end-state with no purpose. Instead of "already
standing near the field," write "already kneeling in the field, both hands
gripping the plow mid-furrow." Every shot must answer: what is this person
doing, and why, at this exact frozen moment. Never use phrasing like
"standing around," "standing there," "waiting there," "sitting there doing
nothing," or "looking around" with no stated task or focus.

OBJECT INTEGRITY: every object named in a shot must remain that same
object for the whole shot - never describe an action mid-transformation.
Favor "already holding," "already placed," "already resting on" phrasing
over active verbs like "lifts," "pours," "hands over," which invite the
video model to try to render (and lose track of) motion it can't sustain.

CUTAWAY DISCIPLINE: the same character must not appear as the
primary_subject of more than 3 consecutive shots. Frequently cut to B-roll
- landscapes, buildings, documents, objects, hands, tools, crowds, weather,
architecture. Whenever the same character reappears after a cutaway, change
the camera angle, framing, and body orientation, but keep their fixed
physical description IDENTICAL to what's stated in "setting_and_characters"
every single time.

LEGIBLE ON-SCREEN TEXT: if a shot deliberately shows readable text (a
newspaper headline, a letter, a sign, a document, an inscription), you must
state the exact required wording in "required_onscreen_text", and describe
it explicitly in visual_description. If no specific wording is required,
do NOT make readable text the focus of the shot at all.

For each shot, provide:
- "shot_type": one of "wide", "medium", "close_up", "extreme_close_up",
  "establishing", "detail_insert"
- "camera_movement": one of "static", "pan_left", "pan_right", "tilt_up",
  "tilt_down", "zoom_in", "zoom_out", "push_in", "pull_out", "dolly_in",
  "dolly_out", "tracking", "crash_zoom", "whip_pan", "handheld_shake",
  "orbit", "drone_rise", "drone_descend", "parallax", "focus_pull",
  "dutch_angle", "snap_zoom", "speed_ramp"
- "camera_reason": one short sentence on why this movement was chosen for
  this specific narration beat
- "lens_effect": one of "shallow_depth_of_field", "lens_flare", "film_grain",
  "none" - use sparingly. Most shots should be "none".
- "primary_subject": a short consistent tag for the main character/subject
  of this shot, matching how they're named in setting_and_characters. Use
  "" for pure B-roll shots.
- "required_onscreen_text": if this shot deliberately shows readable text,
  the exact wording that must appear, correctly spelled. Otherwise "".

PACING RHYTHM (Gen Z attention span - keep it moving):
- Default to quick shots (roughly 2-4 seconds of narration each).
- Only use a held/static shot deliberately, right before a big reveal.
- Vary shot_type, camera_movement, and lens_effect constantly - never repeat
  the same camera_movement more than twice in a row.

ZOOM DISCIPLINE:
- At most 1 in 4 shots may use a zoom-in-family movement (push_in,
  crash_zoom, zoom_in, snap_zoom) or an extreme_close_up shot_type. Never
  use two zoom-in-family movements back to back.
- At least 1 in 4 shots must be "wide" or "establishing" shot_type, spread
  through this segment.
- For the remaining shots, favor movements that add energy WITHOUT
  tightening the frame: pan_left, pan_right, tilt_up, tilt_down, tracking,
  dolly_in, dolly_out, whip_pan, orbit, drone_rise, drone_descend,
  parallax, handheld_shake, dutch_angle, speed_ramp, pull_out, zoom_out.

SOUND DESIGNER:
- For each shot, include "sfx_cue" for both loud dramatic moments and
  quieter ambient/atmospheric sound. Aim for at least half of all shots to
  carry some sfx_cue, leaving "" only where truly no distinct sound would
  be audible."""


def build_shot_breakdown_chunk_prompt(
    title, angle, chunk_text, chunk_index, num_chunks,
    min_shots_chunk, max_shots_chunk,
    setting_and_characters=None, prior_last_subject=None, prior_last_movement=None,
):
    """Builds the prompt for ONE narration chunk's shot breakdown. The
    first chunk (chunk_index == 0) also produces the episode-wide
    setting_and_characters/hook_text/music_mood anchor; later chunks are
    handed that same anchor text back so every shot stays visually
    consistent, and are given a short note on the previous chunk's last
    shot so cutaway discipline carries across the chunk boundary."""
    segment_label = f"segment {chunk_index + 1} of {num_chunks}"

    if chunk_index == 0:
        anchor_block = f"""SETTING AND CHARACTERS - write this as a fixed visual anchor for the WHOLE
episode (not just this segment). This is the single most important field for
keeping the episode visually consistent across all {num_chunks} segments, so
treat it as non-negotiable:
- State the real-world location, country/region, era, and the actual
  ethnicity/culture of the people in this specific story. Be explicit and
  concrete (e.g. "rural Gambia, West Africa, 1981 - Gambian people, dark
  skin, traditional and period-appropriate West African dress" NOT vague
  phrasing that a video model could misread as a different region).
- For every recurring named or clearly-identifiable person in the story
  (e.g. "the mother," "the young soldier," "the porter"), give one fixed,
  concrete physical description (approximate age, build, hair, distinctive
  clothing) that must be repeated consistently - this person must look the
  same in every shot they appear in, not reinterpreted shot to shot.
  If the story has no individually-tracked recurring character (e.g. it
  follows a crowd or an unnamed narrator's perspective), say so explicitly
  instead of inventing one.
This full anchor will be attached to every single shot's image/video
generation prompt later in the pipeline (across all {num_chunks} segments),
so write it as a standalone paragraph that makes sense with no other
context - 2-5 sentences.

THUMBNAIL HOOK TEXT - a short, punchy line of thumbnail cover text that
would make someone scrolling YouTube stop and click. This is NOT a
narration sentence - it should read like a headline: concrete, high-stakes,
and built around the single most shocking number, name, or fact in THIS
SPECIFIC STORY (you may draw on the full episode topic/angle above, not
just this first segment).

THE 2-SECOND RULE: a thumbnail gets about 2 seconds of a scrolling viewer's
attention, and most viewers see it shrunk down on a phone screen. The hook
text must be absorbable in that window - which means SHORT:
{MAX_HOOK_TEXT_WORDS} words maximum, ideally 3-4, under {MAX_HOOK_TEXT_CHARS}
characters. Use short punchy fragments separated by periods, not one
flowing sentence.

The example below shows the STYLE only. Do not reuse or adapt it - write an
entirely new line using facts that actually appear in the story.
   Style example only, from an unrelated story - never copy this line
   itself: "312 DIARIES. ONE BOMB. GONE IN SECONDS."

MUSIC MOOD - include "music_mood": a single descriptive prompt for an AI
music generator describing the background score for the WHOLE episode -
scored like a thriller movie, building tension progressively, peaking at
the biggest reveal, then resolving.

"""
        json_extra_fields = """  "setting_and_characters": "2-5 sentence fixed anchor for the WHOLE episode.",
  "hook_text": "Short punchy thumbnail cover line, max {max_words} words and under {max_chars} characters.",
  "music_mood": "Background score prompt for the whole episode, describing its build-up arc.",
""".format(max_words=MAX_HOOK_TEXT_WORDS, max_chars=MAX_HOOK_TEXT_CHARS)
        continuity_note = ""
    else:
        anchor_block = f"""SETTING AND CHARACTERS - this is ALREADY FIXED for the whole episode. Every
shot you write below must stay strictly consistent with it (same location,
era, ethnicity, and exact fixed physical description for any recurring
character named in it):

---
{setting_and_characters}
---

Do NOT invent a new setting_and_characters, hook_text, or music_mood in
this response - this segment only returns a shot_list.

"""
        json_extra_fields = ""
        continuity_bits = []
        if prior_last_subject:
            continuity_bits.append(
                f'the previous segment\'s last shot had primary_subject "{prior_last_subject}" - '
                f"avoid opening this segment with more consecutive shots of that same subject; "
                f"cut to something else first if this segment's narration allows it"
            )
        if prior_last_movement:
            continuity_bits.append(
                f'the previous segment\'s last shot used camera_movement "{prior_last_movement}" - '
                f"don't repeat that exact movement as this segment's first shot"
            )
        continuity_note = (
            "CONTINUITY WITH THE PREVIOUS SEGMENT: " + "; also ".join(continuity_bits) + ".\n\n"
            if continuity_bits else ""
        )

    return f"""You are the visual director and sound designer for "Erased," a
YouTube documentary channel. The narration script for this episode has
ALREADY been written and finalized - do not rewrite, shorten, or alter it.
Your job right now is ONLY to build the shot-by-shot breakdown for
{segment_label} of this episode's narration (given below as NARRATION
SEGMENT). This segment will later be stitched together with the other
{num_chunks - 1} segment(s) into one continuous shot list, so treat the
NARRATION SEGMENT below as a slice of a longer script, not a complete story
by itself.

Episode topic: {title}
Angle: {angle}

{anchor_block}NARRATION SEGMENT ({segment_label}, do not change this text):
---
{chunk_text}
---

{continuity_note}Break the NARRATION SEGMENT above into EXACTLY between
{min_shots_chunk} and {max_shots_chunk} shots covering this segment only,
start to finish - this is a hard requirement, not a suggestion.

{SHOT_RULES_BLOCK}

FINAL CHECK before you output: for every shot whose visual_description
mentions a newspaper, letter, sign, document, headline, inscription,
poster, map, book, plaque, telegram, postcard, banner, ledger, diary,
certificate, or gravestone/tombstone - you MUST fill in
required_onscreen_text with the exact wording, or rewrite that shot so no
readable text is the focus. A shot with one of those words present and
required_onscreen_text left empty will be rejected outright.

Return ONLY valid JSON, no other text, no markdown fences, in this exact
format:

{{
{json_extra_fields}  "shot_list": [
    {{
      "shot_number": 1,
      "visual_description": "Detailed description for AI image/video generation, consistent with setting_and_characters",
      "narration_excerpt": "The exact, verbatim portion of THIS SEGMENT's narration this shot covers",
      "shot_type": "wide",
      "camera_movement": "push_in",
      "camera_reason": "Why this movement fits this beat",
      "lens_effect": "none",
      "sfx_cue": "",
      "primary_subject": "",
      "required_onscreen_text": ""
    }}
  ]
}}

Include between {min_shots_chunk} and {max_shots_chunk} shots covering this
segment's narration above - every shot must be distinct, never repeat an
earlier shot."""


def generate_shot_breakdown(title, angle, narration_text):
    """CHUNKED (2026-08-15): splits narration into NUM_SHOT_CHUNKS pieces and
    makes one small Groq call per piece (spaced SHOT_CHUNK_CALL_DELAY_SECONDS
    apart), instead of one huge call that structurally cannot fit under
    Groq's free-tier 12,000 TPM ceiling. All chunk shot_lists are stitched
    and renumbered, then validated with the exact same episode-wide rules
    as before chunking (validate_and_normalize_shot_response is unchanged)."""
    chunks = split_narration_into_chunks(narration_text, NUM_SHOT_CHUNKS)
    num_chunks = len(chunks)

    last_reason = None
    ever_reached_content = False
    content_attempt = 0
    infra_attempt = 0

    while content_attempt < MAX_GENERATION_ATTEMPTS:
        setting_and_characters = None
        hook_text = None
        music_mood = None
        stitched_shots = []
        infra_failed_this_round = False
        content_failure_reason = None

        for idx, chunk_text in enumerate(chunks):
            if idx > 0:
                print(f"[shots] Waiting {SHOT_CHUNK_CALL_DELAY_SECONDS}s before segment "
                      f"{idx + 1}/{num_chunks} call (keeps each Groq call in its own TPM window)...")
                time.sleep(SHOT_CHUNK_CALL_DELAY_SECONDS)

            prior_last_subject = stitched_shots[-1].get("primary_subject") if stitched_shots else None
            prior_last_movement = stitched_shots[-1].get("camera_movement") if stitched_shots else None

            prompt = build_shot_breakdown_chunk_prompt(
                title, angle, chunk_text, idx, num_chunks,
                CHUNK_MIN_SHOTS, CHUNK_MAX_SHOTS,
                setting_and_characters=setting_and_characters,
                prior_last_subject=prior_last_subject,
                prior_last_movement=prior_last_movement,
            )

            try:
                raw = call_llm(prompt)
            except SuspectedDailyQuotaExhausted:
                # FIX (2026-08-15, later): propagate straight up, do not
                # treat as an ordinary per-chunk infra retry.
                raise
            except RuntimeError as e:
                infra_attempt += 1
                last_reason = f"Groq call failed on segment {idx + 1}/{num_chunks}: {e}"
                print(f"[shots] Infra retry {infra_attempt}/{MAX_INFRA_ATTEMPTS} failed - {last_reason} "
                      f"(does not count against the {MAX_GENERATION_ATTEMPTS} content attempts)")
                infra_failed_this_round = True
                break

            ever_reached_content = True
            try:
                parsed = extract_json(raw)
            except (ValueError, json.JSONDecodeError) as e:
                content_failure_reason = f"JSON parse failed on segment {idx + 1}/{num_chunks}: {e}"
                break

            if idx == 0:
                setting_and_characters = (parsed.get("setting_and_characters") or "").strip()
                hook_text = (parsed.get("hook_text") or "").strip()
                music_mood = (parsed.get("music_mood") or "").strip()

            chunk_shot_list = parsed.get("shot_list")
            if not isinstance(chunk_shot_list, list) or len(chunk_shot_list) == 0:
                content_failure_reason = f"segment {idx + 1}/{num_chunks} returned missing/empty shot_list"
                break
            if len(chunk_shot_list) < CHUNK_MIN_SHOTS or len(chunk_shot_list) > CHUNK_MAX_SHOTS:
                content_failure_reason = (
                    f"segment {idx + 1}/{num_chunks} shot count {len(chunk_shot_list)} outside "
                    f"{CHUNK_MIN_SHOTS}-{CHUNK_MAX_SHOTS} range"
                )
                break

            stitched_shots.extend(chunk_shot_list)

        if infra_failed_this_round:
            if infra_attempt >= MAX_INFRA_ATTEMPTS:
                break
            wait = infra_attempt * 20
            print(f"Backing off {wait}s before next infra retry...")
            time.sleep(wait)
            continue

        content_attempt += 1

        if content_failure_reason:
            last_reason = content_failure_reason
            print(f"[shots] Attempt {content_attempt}/{MAX_GENERATION_ATTEMPTS} failed - {last_reason}")
            if content_attempt < MAX_GENERATION_ATTEMPTS:
                print(f"Waiting {CONTENT_RETRY_WAIT_SECONDS}s before next content attempt "
                      f"(prevents bursting past Groq's free-tier RPM ceiling)...")
                time.sleep(CONTENT_RETRY_WAIT_SECONDS)
            continue

        for i, shot in enumerate(stitched_shots):
            shot["shot_number"] = i + 1

        result = {
            "setting_and_characters": setting_and_characters,
            "hook_text": hook_text,
            "music_mood": music_mood,
            "shot_list": stitched_shots,
        }

        is_valid, validated = validate_and_normalize_shot_response(result, narration_text)
        if is_valid:
            return validated

        last_reason = validated
        print(f"[shots] Attempt {content_attempt}/{MAX_GENERATION_ATTEMPTS} failed - {last_reason}")
        if content_attempt < MAX_GENERATION_ATTEMPTS:
            print(f"Waiting {CONTENT_RETRY_WAIT_SECONDS}s before next content attempt "
                  f"(prevents bursting past Groq's free-tier RPM ceiling)...")
            time.sleep(CONTENT_RETRY_WAIT_SECONDS)

    if not ever_reached_content:
        raise InfraFailure(
            f"Groq never returned a usable response after {infra_attempt} infra "
            f"retries during shot-breakdown stage (narration was already confirmed "
            f"good). Last reason: {last_reason}"
        )
    raise RuntimeError(f"Shot breakdown failed after {content_attempt} content attempts. Last reason: {last_reason}")


def generate_script(title, angle):
    """Orchestrates the two stages. If the narration stage hits InfraFailure,
    that propagates up untouched (topic stays pending). If the shot-breakdown
    stage fails after narration already succeeded, that's still surfaced as
    a real failure - but note the narration itself was proven fine, so a
    generation_failed topic reset for this reason should retry fast."""
    narration_text = generate_narration(title, angle)
    return generate_shot_breakdown(title, angle, narration_text)


def save_script(topic_id, narration_text, shot_list, music_mood, hook_text, setting_and_characters):
    retryable_request(
        "POST",
        f"{SUPABASE_URL}/rest/v1/scripts",
        headers={**HEADERS, "Prefer": "return=representation"},
        json={
            "topic_id": topic_id,
            "narration_text": narration_text,
            "shot_list": shot_list,
            "music_mood": music_mood,
            "hook_text": hook_text,
            "setting_and_characters": setting_and_characters,
            "status": "pending",
        },
        timeout=30,
    )
    print("Script saved.")


def mark_topic_scripted(topic_id):
    retryable_request(
        "PATCH",
        f"{SUPABASE_URL}/rest/v1/topics?id=eq.{topic_id}",
        headers=HEADERS,
        json={"status": "scripted"},
        timeout=30,
    )


def mark_topic_generation_failed(topic_id, reason):
    retryable_request(
        "PATCH",
        f"{SUPABASE_URL}/rest/v1/topics?id=eq.{topic_id}",
        headers=HEADERS,
        json={"status": "generation_failed", "last_failure_reason": str(reason)[:2000]},
        timeout=30,
    )
    print(f"Topic {topic_id} marked generation_failed - will be skipped by future runs until manually "
          f"reset. Last reason: {reason}")
    print(f"FIX: review/reword the topic's title or angle in the topics table for {topic_id}, then "
          f"reset status back to 'pending' to retry it.")


def main():
    topics = get_pending_topics(limit=5)
    if not topics:
        print("No pending topics found. Nothing to do.")
        return

    for topic in topics:
        print(f"Writing script for: {topic['title']}")
        try:
            result = generate_script(topic["title"], topic["angle"])
        except SuspectedDailyQuotaExhausted as e:
            # FIX (2026-08-15, later): see module docstring. Every remaining
            # topic in this batch would hit the exact same wall - stop the
            # whole run immediately instead of burning ~10-15 more minutes
            # on doomed retries. Topic stays 'pending', same as InfraFailure,
            # since this is not the topic's fault either.
            print(
                f"ABORTING RUN - suspected Groq daily token quota (TPD) exhaustion on topic "
                f"{topic['id']} ({topic['title']}): {e}"
            )
            print("This will not clear until Groq's daily reset (UTC midnight) - not retrying "
                  "further topics this run. Next scheduled run will retry from the top.")
            return
        except InfraFailure as e:
            print(f"Groq infra failure on topic {topic['id']} ({topic['title']}) - not the "
                  f"topic's fault, leaving it pending and trying the next-oldest candidate "
                  f"this run instead of exiting: {e}")
            continue
        except RuntimeError as e:
            mark_topic_generation_failed(topic["id"], str(e))
            continue

        save_script(
            topic["id"],
            result["narration_text"],
            result["shot_list"],
            result["music_mood"],
            result["hook_text"],
            result["setting_and_characters"],
        )
        mark_topic_scripted(topic["id"])
        print("Done.")
        return

    print("No candidate in this batch produced a script this run (all hit infra failures or "
          "were marked generation_failed) - next scheduled run will re-fetch and retry.")


if __name__ == "__main__":
    main()
