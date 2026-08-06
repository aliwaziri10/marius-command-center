"""
Marius Command Center - Script Writing Agent
Takes the oldest pending topic and turns it into a full narration script
plus a shot-by-shot visual production plan for "Erased."

SETTING/CHARACTER CONSISTENCY (2026-07-29): shots were drifting visually -
wrong ethnicity/location shown for a scene (e.g. a story set in Gambia
showing Chinese faces and Chinese military troops), and recurring people
(e.g. "the mother") changing appearance between shots with no visual
anchor tying them together. Root cause: each shot's visual_description was
generated independently with no persistent reference for what the real-world
setting looks like or what recurring characters look like. Added a new
top-level "setting_and_characters" field: a short paragraph fixing the
real-world location/era/ethnicity of the story and describing the physical
appearance of every recurring named person, generated once per episode and
required to be respected by every shot. video_generation.py now injects
this into every single shot's Agnes prompt so the anchor is never lost or
forgotten partway through the episode.

SFX COVERAGE FIX (2026-08-03): sfx_cue guidance previously told the model
to only add a sound cue for LOUD/dramatic moments (explosions, gunfire,
crashes) and leave everything else empty. Confirmed in production: quiet,
reflective true stories (a lighthouse keeper, a genocide-rescue story)
genuinely have zero loud/dramatic beats, so every single shot's sfx_cue
came back empty and the finished video had no sound design at all beyond
narration and score. Broadened the guidance to also cover ambient/
atmospheric sound (footsteps, wind, fire, doors, distant voices, etc.) so
quiet episodes still get some sound design instead of none.

CTA RELIABILITY FIX (2026-08-03): the prompt already instructed the model to
weave a like/subscribe/comment call-to-action into the narration right after
the emotional climax, but this was never validated, so it was silently
optional in practice - confirmed in production that some episodes got a
well-written in-voice CTA and others got none at all, with the exact same
prompt. Added a validation check (same pattern as the hook_text checks
below) that fails and retries generation if no CTA-shaped language is found
in the back portion of narration_text, so a missing CTA is now a hard
regeneration trigger instead of a coin flip.

NETWORK RETRY FIX (2026-08-04): script writing was crashing the entire
workflow (uncaught ChunkedEncodingError / ConnectionError / Timeout) whenever
OpenRouter's connection dropped mid-response, even though a retry loop
already existed right next to it for HTTP 429. A dropped connection happens
before any status code is returned, so it was never hitting the 429 branch -
it just killed the whole run instantly. call_openrouter now catches
network-level exceptions (not just 429 responses) and retries those too,
using the same backoff pattern.

ZOOM FAMILY UPDATE (2026-08-04): added "dolly_in" to ZOOM_FAMILY_MOVEMENTS,
so it now counts toward the zoom-shot ratio/consecutive-zoom limits the same
way push_in, crash_zoom, zoom_in, and snap_zoom already do.

NULL CONTENT FIX (2026-08-04): extract_json crashed with an uncaught
AttributeError ('NoneType' object has no attribute 'strip') whenever
OpenRouter returned a response with content: null - a dropped/refused
generation with no error code, distinct from a 429 or network failure.
This killed the entire workflow run instead of being treated as a normal
failed attempt. extract_json now raises a ValueError on empty/None input
instead, which the existing retry loop in generate_script already catches
and retries like any other parse failure.

SUPABASE CALL HARDENING (2026-08-05): the NETWORK RETRY FIX above only
covered the OpenRouter call inside generate_script(). The three Supabase
calls in main() - get_next_pending_topic(), save_script(), and
mark_topic_scripted() - had zero retry/exception handling: a single
transient network blip or Supabase hiccup on any of them raised an
uncaught exception straight out of main() and killed the whole workflow
run (this is the direct cause of the repeated "Script Writing workflow
failed" issues - GitHub confirms this crashed intermittently even on runs
where generate_script() itself succeeded). All three now go through the
same retryable_request() helper, using the same network-exception/5xx
retry pattern already proven in call_openrouter.

DUPLICATE-SHOT / SHORT-NARRATION PADDING FIX (2026-08-06): found in
production via an uploaded video ("The Lighthouse Keeper of Sable Island")
that came out ~2 minutes long and visually looped the same handful of shots
over and over. Root cause: the model wrote a narration_text of only ~320
words (well under the 1200-1500 word target) and only 10 genuinely distinct
shots, then padded the shot_list to the required MIN_SHOTS by repeating
that same block of 10 shots six times over. The existing empty-shot check
(find_empty_shots, still below) only rejects shots with blank text - a
duplicated-but-non-empty shot passed it every time, and there was no floor
on narration length at all. Fixed two ways: validate_and_normalize now
hard-rejects narration_text under MIN_NARRATION_WORDS words, and
find_duplicate_shots now rejects any script where the same
(visual_description, narration_excerpt) pair appears more than
MAX_SHOT_REPEAT_COUNT times - both trigger a retry/regeneration exactly
like the other validation failures in this file, instead of silently
saving a script that will play as a frozen, repeating video.

ATTEMPT BUDGET FIX (2026-08-06): confirmed in production the same day the
fix above shipped - Script Writing run #76 burned all 5 of
MAX_GENERATION_ATTEMPTS and ended with the topic marked
'generation_failed', producing zero new scripts, even though the workflow
itself reported a clean "completed" run (main() catches the exhausted-
attempts RuntimeError and returns normally, so this fails silently with no
GitHub issue opened - only visible by checking the topics table directly).
The new validation now stacks FIVE independent hard requirements on every
single attempt (900+ word narration, a valid CTA, correct hook text, no
empty shots, no shot repeated more than twice) - a free/weaker model needs
more than 5 tries to land all of them at once. Raised to 8 attempts. This
does not weaken any check; it just gives the model a fairer number of
shots at clearing the same bar.

CONTROL-CHARACTER JSON FIX (2026-08-06): confirmed in production - a real
run failed its first attempt with "Invalid control character at: line 3
column 504" (a raw unescaped newline/tab inside a JSON string value in the
model's output, which json.loads rejects outright per the JSON spec). This
was burning a full attempt for a purely mechanical parsing issue, unrelated
to actual content quality - the underlying narration/shot content may have
been perfectly fine. extract_json now sanitizes raw control characters
found inside JSON string literals (escaping \n, \r, \t and stripping any
other stray control byte) before handing the text to json.loads, so a
model that forgets to escape a newline inside a string no longer costs a
full generation attempt.

HTTP-ENVELOPE JSON FIX (2026-08-06): a malformed/truncated response body
from OpenRouter itself (not the model's script JSON) used to crash the
whole workflow uncaught, since only 429s and network-level exceptions were
retried. call_openrouter now also retries a malformed/unparseable response
envelope the same way.

INDENTATION FIX (2026-08-06): the HTTP-ENVELOPE JSON FIX above was pasted
with the "if resp.status_code == 429:" line one level under-indented
relative to the surrounding try/except block. Python raised an
IndentationError on module load, so the ENTIRE script crashed before
executing a single line - every script_writing.py run failed instantly
from the moment that commit landed. This is why 200 topics backed up in
'pending' with zero new scripts reaching the scripts table, which in turn
starved the narration workflow (correctly running every 30 min, but with
nothing in the queue to narrate). Fixed by restoring the correct
indentation - no logic changed, this is a pure syntax fix.
"""

import os
import json
import time
import requests
from collections import Counter

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SECRET_KEY"]
OPENROUTER_KEY = os.environ["OPENROUTER_API_KEY"]

HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
}

MAX_RETRIES = 4
MIN_SHOTS = 60
MAX_SHOTS = 85
MAX_GENERATION_ATTEMPTS = 8
MAX_HOOK_TEXT_CHARS = 40
MAX_HOOK_TEXT_WORDS = 5
MIN_SETTING_CHARS = 40
MAX_SETTING_CHARS = 900
MIN_NARRATION_WORDS = 900
MAX_SHOT_REPEAT_COUNT = 2

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

RETRYABLE_NETWORK_EXCEPTIONS = (
    requests.exceptions.ChunkedEncodingError,
    requests.exceptions.ConnectionError,
    requests.exceptions.Timeout,
)
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


def retryable_request(method, url, max_retries=MAX_RETRIES, **kwargs):
    """
    SUPABASE CALL HARDENING (2026-08-05): shared retry wrapper for the
    Supabase REST calls in this file, mirroring the same network-exception
    and 5xx/429 retry pattern already used for OpenRouter in
    call_openrouter(). Raises the underlying exception (or the last bad
    response's HTTPError) after exhausting retries, so a genuinely broken
    call still surfaces as a real failure - it just no longer dies on the
    first transient blip.
    """
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


def get_next_pending_topic():
    resp = retryable_request(
        "GET",
        f"{SUPABASE_URL}/rest/v1/topics?status=eq.pending&order=created_at.asc&limit=1",
        headers=HEADERS,
        timeout=30,
    )
    rows = resp.json()
    return rows[0] if rows else None


def call_openrouter(prompt):
    last_error = None
    for attempt in range(MAX_RETRIES):
        try:
            resp = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {OPENROUTER_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "openrouter/free",
                    "messages": [{"role": "user", "content": prompt}],
                },
                timeout=90,
            )
        except RETRYABLE_NETWORK_EXCEPTIONS as e:
            wait = (attempt + 1) * 15
            print(f"Network error ({e.__class__.__name__}: {e}), waiting {wait}s before retry...")
            last_error = e
            time.sleep(wait)
            continue

        if resp.status_code == 429:
            wait = (attempt + 1) * 15
            print(f"Rate limited, waiting {wait}s before retry...")
            time.sleep(wait)
            last_error = resp
            continue
        resp.raise_for_status()

        try:
            return resp.json()["choices"][0]["message"]["content"]
        except (requests.exceptions.JSONDecodeError, KeyError, IndexError) as e:
            # HTTP-ENVELOPE JSON FIX (2026-08-06): a malformed/truncated
            # response body from OpenRouter itself (not the model's script
            # JSON - that's handled separately in extract_json) used to
            # crash the whole workflow uncaught here, since only 429s and
            # network-level exceptions were retried. This is a transient
            # upstream issue like any other - retry it the same way.
            wait = (attempt + 1) * 15
            print(f"OpenRouter response envelope malformed/unparseable ({e}), waiting {wait}s before retry...")
            last_error = e
            time.sleep(wait)
            continue

    if isinstance(last_error, Exception) and not hasattr(last_error, "text"):
        raise RuntimeError(f"OpenRouter still failing after {MAX_RETRIES} attempts: {last_error}")
    raise RuntimeError(f"OpenRouter still rate-limited after {MAX_RETRIES} attempts: {last_error.text if last_error else 'unknown'}")


def sanitize_json_control_chars(text):
    """
    CONTROL-CHARACTER JSON FIX (2026-08-06): the free model sometimes emits
    a raw, unescaped control character (most often a literal newline or tab)
    inside a JSON string value instead of the required \\n / \\t escape
    sequence. The JSON spec forbids raw control characters (0x00-0x1F)
    inside string literals, so json.loads rejects the entire payload with
    an "Invalid control character" error even when the actual content is
    otherwise fine. This walks the text once, tracking whether we're
    inside a string literal (respecting backslash-escapes and skipping
    content outside strings entirely so structural whitespace/formatting
    is untouched), and escapes/strips any raw control byte found inside a
    string so json.loads can parse it normally.
    """
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
                # any other stray control byte is dropped silently
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


def narration_has_engagement_cta(narration_text):
    if not narration_text:
        return False

    window = narration_text[-CTA_SEARCH_WINDOW_CHARS:].lower()
    return any(keyword in window for keyword in CTA_KEYWORDS)


def find_duplicate_shots(normalized_shots):
    """DUPLICATE-SHOT PADDING FIX (2026-08-06): the free model sometimes
    runs out of real story before reaching MIN_SHOTS and pads the remainder
    by repeating an earlier block of shots verbatim (same
    visual_description + narration_excerpt) instead of leaving them empty -
    which the older find_empty_shots check below can't catch, since the
    repeated shots aren't empty. Confirmed in production: one uploaded
    video looped the same 10 shots six times, producing a frozen-looking,
    ~2-minute video instead of the intended 8-10 minute episode. Returns a
    list of (visual_description, narration_excerpt, count) tuples for any
    shot pair that appears more than MAX_SHOT_REPEAT_COUNT times."""
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
    """EMPTY-SHOT PADDING FIX (2026-08-03): the free model sometimes runs out
    of real story to break into shots before reaching MIN_SHOTS, and pads the
    remainder of the list with placeholder shot objects that have an empty
    visual_description and/or narration_excerpt. Those shots still cost a
    real Agnes video generation downstream and end up discarded to zero
    duration in the final cut - so this must be caught here and rejected,
    not silently saved."""
    return [
        i for i, s in enumerate(normalized_shots)
        if not (s["visual_description"] or "").strip() or not (s["narration_excerpt"] or "").strip()
    ]


def validate_and_normalize(result):
    if "narration_text" not in result or not result["narration_text"].strip():
        return False, "missing narration_text"

    narration_word_count = len(result["narration_text"].split())
    if narration_word_count < MIN_NARRATION_WORDS:
        return False, (
            f"narration_text is only {narration_word_count} words - need at least "
            f"{MIN_NARRATION_WORDS} (target is 1200-1500 for an 8-10 minute episode). "
            f"A short narration doesn't have enough real story content to fill "
            f"{MIN_SHOTS}+ distinct shots and forces padding the shot list with "
            f"repeated shots instead of real coverage."
        )

    setting_and_characters = (result.get("setting_and_characters") or "").strip()
    if len(setting_and_characters) < MIN_SETTING_CHARS:
        return False, (
            f"setting_and_characters missing or too short "
            f"({len(setting_and_characters)} chars, need at least {MIN_SETTING_CHARS}) - "
            f"must fix the real-world location/era/ethnicity and describe every "
            f"recurring character's appearance"
        )
    result["setting_and_characters"] = setting_and_characters[:MAX_SETTING_CHARS]

    if not narration_has_engagement_cta(result["narration_text"]):
        return False, (
            "narration_text is missing an in-voice engagement call-to-action "
            "(like/subscribe/comment) near the end - must weave one in right "
            "after the emotional climax, before the closing line"
        )

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

    if not hook_text_matches_story(result["hook_text"], result["narration_text"]):
        return False, f"hook_text {result['hook_text']!r} doesn't appear related to this story's narration"

    return True, result


def generate_script(title, angle):
    prompt = f"""You are the head writer for "Erased," a YouTube documentary
channel telling real, historically documented true stories of ordinary people
caught in extraordinary historical moments, whose names history left out.

Episode topic: {title}
Angle: {angle}

SETTING AND CHARACTERS - write this FIRST, before anything else, as a fixed
visual anchor for the whole episode. This is the single most important
field for keeping the episode visually consistent, so treat it as
non-negotiable:
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
generation prompt later in the pipeline, so write it as a standalone
paragraph that makes sense with no other context - 2-5 sentences.

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

Write a complete 8-10 minute narration script of AT LEAST 1200 words
(target 1200-1500 words) with this opening structure, a clear narrative arc
through the rest of the story, and a reflective closing line. This length is
a hard requirement, not a suggestion - a short narration doesn't have enough
real content to fill the shot list below without repeating shots, and will
be rejected. If you don't know enough real detail about this specific story
to reach 1200 words, expand on documented historical context, setting, and
the emotional experience of the people involved - do not pad with repetition
or filler, and do not submit a short script expecting it to be padded later.

CALL TO ACTION - THIS IS REQUIRED, NOT OPTIONAL: immediately after the
emotional climax of the story and before the final reflective closing line,
you MUST write one natural, in-voice sentence encouraging the viewer to
like, subscribe, and share their own thoughts in the comments so more of
these erased stories get told. Every single script must include this - a
script with no call to action will be rejected and regenerated. It must
NOT be a generic "smash that like button" line - write it in the tone and
voice of this specific episode, using imagery or phrasing that echoes the
story just told, and vary the wording from episode to episode. It is part
of the narration_text itself, not a separate field. Use natural language
that clearly asks the viewer to like/share/subscribe and to respond in the
comments (for example, weaving in words like "comment," "share," or
"subscribe" naturally) so the ask is unambiguous, not just implied.

THUMBNAIL HOOK TEXT - separate from the narration, also write a short,
punchy line of thumbnail cover text that would make someone scrolling
YouTube stop and click. This is NOT a narration sentence - it should read
like a headline: concrete, high-stakes, and built around the single most
shocking number, name, or fact in THIS SPECIFIC STORY (the one named in
"Episode topic" above) - never a different story.

THE 2-SECOND RULE: a thumbnail gets about 2 seconds of a scrolling viewer's
attention before they move on, and most viewers see it shrunk down on a
phone screen. The hook text must be absorbable in that window - which
means SHORT: {MAX_HOOK_TEXT_WORDS} words maximum, ideally 3-4, under
{MAX_HOOK_TEXT_CHARS} characters. This is not a summary of the story - the
video title already gives that context. This is the single emotional
spike: one number, one name, or one consequence. Use short punchy
fragments separated by periods, not one flowing sentence - fragments let
the eye grab each piece independently instead of having to read
start-to-finish.

The example below shows the STYLE only - a short fragment built from a real
number/name/consequence. It is NOT about this episode's topic. Do not reuse
it, copy it, or adapt it - write an entirely new line using facts that
actually appear in the narration you write for THIS episode.
   Bad (too long/sentence-like): "When a bomb hit the pub, 312 diaries were
   buried under the rubble."
   Style example only, from an unrelated story - never copy this line
   itself: "312 DIARIES. ONE BOMB. GONE IN SECONDS."

CINEMATIC DIRECTOR - shot list requirements:
Break the episode into EXACTLY between {MIN_SHOTS} and {MAX_SHOTS} shots -
this is a hard requirement, not a suggestion. This is a dense, sub-sentence
level breakdown - a single narration sentence should often span 2-3 separate
shots, not one. Do not write sparse, paragraph-level shots.

EVERY SHOT MUST BE DISTINCT - THIS IS ALSO A HARD REQUIREMENT: every shot
must have its own real visual_description and narration_excerpt drawn from
a different part of the narration you wrote. NEVER repeat an earlier shot
(same visual_description and narration_excerpt) later in the list just to
reach the shot count - a script that repeats any shot more than twice will
be rejected and regenerated. If your narration doesn't naturally break into
{MAX_SHOTS} distinct shots, write a longer narration and break it more
finely instead of looping earlier shots.

Every shot's "visual_description" must stay consistent with the
"setting_and_characters" anchor above - same location/era/ethnicity, and
any recurring person described there must match their fixed appearance in
every shot they appear in. Do not introduce a different ethnicity, region,
or unplanned recurring character partway through.

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
  "none" - use sparingly and only where it heightens the moment (e.g.
  shallow_depth_of_field on an emotional close-up, lens_flare on a
  triumphant reveal). Most shots should be "none".

PACING RHYTHM (Gen Z attention span - keep it moving):
- Default to quick shots (roughly 2-4 seconds of narration each). Avoid long
  static stretches.
- Only use a held/static shot deliberately, right before a big reveal or
  emotional gut-punch, to let it land. These held shots should be rare -
  most of the episode should feel fast-cut.
- Vary shot_type, camera_movement, and lens_effect constantly - never repeat
  the same camera_movement more than twice in a row.

ZOOM DISCIPLINE (avoid an all-close-up, all-zoomed-in episode): push_in,
crash_zoom, zoom_in, snap_zoom, and extreme_close_up all tighten the frame.
Used too often, back-to-back, the whole episode feels claustrophobic and
zoomed-in with no sense of place - this has been a real problem, so treat
this as a hard budget, not a suggestion:
- At most 1 in 4 shots may use a zoom-in-family movement (push_in,
  crash_zoom, zoom_in, snap_zoom) or an extreme_close_up shot_type. Never
  use two zoom-in-family movements back to back.
- At least 1 in 4 shots must be "wide" or "establishing" shot_type, spread
  through the episode (not clustered only at the start), so the viewer
  keeps a sense of location and space between tight moments.
- For the remaining shots, favor movements that add energy WITHOUT
  tightening the frame: pan_left, pan_right, tilt_up, tilt_down, tracking,
  dolly_in, dolly_out, whip_pan, orbit, drone_rise, drone_descend,
  parallax, handheld_shake, dutch_angle, speed_ramp, pull_out, zoom_out.
  These give the same fast-cut, premium-AI-video energy without the
  claustrophobic zoomed-in feel.

SOUND DESIGNER - audio requirements:
- At the top level, include "music_mood": a single descriptive prompt (for
  an AI music generator) describing the background score for the WHOLE
  episode. Score it like a THRILLER MOVIE, not a somber museum documentary:
  it should build tension progressively through the episode - start
  restrained and low-key, add layers/intensity as the story escalates, and
  peak into a dramatic, percussive climax at the episode's biggest reveal
  or emotional gut-punch, before resolving. Describe the specific arc
  explicitly in the prompt. Favor modern, high-energy scoring over
  classical/orchestral-documentary tropes - think trailer music and
  true-crime thriller scoring, not elevator-music strings.
- For each shot, include "sfx_cue": a short sound-effect prompt for
  BOTH loud dramatic moments (explosions, gunfire, crashes, sudden
  reveals, door slams, crowd roars) AND quieter ambient/atmospheric
  sound that grounds a scene in physical reality (footsteps on a
  specific surface, wind, rain, fire crackling, a door creaking, distant
  voices/crowd murmur, birds, waves, rustling paper/fabric, a clock
  ticking). Many true stories are quiet, not explosive - if every shot's
  sfx_cue is left empty because nothing "loud" happens, the finished
  video plays with no sound design at all, which is worse than a subtle
  ambient cue. Aim for at least half of all shots to carry SOME sfx_cue
  (loud or ambient), and only leave "sfx_cue" as an empty string for
  shots where truly no distinct sound would be audible (e.g. a static
  wide shot of an empty landscape with only score playing).

Return ONLY valid JSON, no other text, no markdown fences, in this exact
format:

{{
  "setting_and_characters": "2-5 sentence fixed anchor: real-world location/era/ethnicity of this story, plus a fixed physical description of every recurring named/identifiable character.",
  "narration_text": "The full narration script as one string, written to be read aloud.",
  "hook_text": "Short punchy thumbnail cover line, max {MAX_HOOK_TEXT_WORDS} words and under {MAX_HOOK_TEXT_CHARS} characters, readable in a 2-second glance, written specifically for THIS episode's topic - never the style example above.",
  "music_mood": "Background score prompt for the whole episode, describing its build-up arc.",
  "shot_list": [
    {{
      "shot_number": 1,
      "visual_description": "Detailed description for AI image/video generation, consistent with setting_and_characters above",
      "narration_excerpt": "The exact portion of narration this shot covers",
      "shot_type": "wide",
      "camera_movement": "push_in",
      "camera_reason": "Why this movement fits this beat",
      "lens_effect": "none",
      "sfx_cue": ""
    }}
  ]
}}

Include between {MIN_SHOTS} and {MAX_SHOTS} shots covering the full narration - every shot must be distinct, never repeat an earlier shot."""

    last_reason = None
    for attempt in range(MAX_GENERATION_ATTEMPTS):
        raw = call_openrouter(prompt)
        try:
            parsed = extract_json(raw)
        except (ValueError, json.JSONDecodeError) as e:
            last_reason = f"JSON parse failed: {e}"
            print(f"Attempt {attempt + 1}/{MAX_GENERATION_ATTEMPTS} failed - {last_reason}")
            continue

        is_valid, result = validate_and_normalize(parsed)
        if is_valid:
            return result

        last_reason = result
        print(f"Attempt {attempt + 1}/{MAX_GENERATION_ATTEMPTS} failed - {last_reason}")

    raise RuntimeError(f"Script generation failed after {MAX_GENERATION_ATTEMPTS} attempts. Last reason: {last_reason}")


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
        json={"status": "generation_failed"},
        timeout=30,
    )
    print(f"Topic {topic_id} marked generation_failed - will be skipped by future runs until manually "
          f"reset. Last reason: {reason}")
    print(f"FIX: review/reword the topic's title or angle in the topics table for {topic_id}, then "
          f"reset status back to 'pending' to retry it.")


def main():
    topic = get_next_pending_topic()
    if not topic:
        print("No pending topics found. Nothing to do.")
        return

    print(f"Writing script for: {topic['title']}")
    try:
        result = generate_script(topic["title"], topic["angle"])
    except RuntimeError as e:
        mark_topic_generation_failed(topic["id"], str(e))
        return

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


if __name__ == "__main__":
    main()
