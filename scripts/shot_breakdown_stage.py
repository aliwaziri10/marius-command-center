"""
Marius Command Center - Shot Breakdown Stage
Stage 2 of script generation: from a confirmed-length narration, build the
shot-by-shot visual production plan, in chunks small enough to fit under
the LLM's per-request token ceiling.

SPLIT OUT (2026-08-18): relocated from script_writing.py with no behavior
change. See script_writing.py's module docstring for full history.

DIRECTOR FEATURES ADDED (2026-08-20): lighting, beat_intensity, and
location_tag per-shot fields, plus an episode-wide color_palette anchor
(carried across chunks the same way setting_and_characters is).
"""

import re
import time
from collections import Counter

from llm_client import call_llm, extract_json, DailyQuotaExhausted, InfraFailure

MIN_SHOTS = 25
MAX_SHOTS = 35
MAX_GENERATION_ATTEMPTS = 3
MAX_INFRA_ATTEMPTS = 4
MAX_HOOK_TEXT_CHARS = 40
MAX_HOOK_TEXT_WORDS = 5
MIN_SETTING_CHARS = 40
MAX_SETTING_CHARS = 900
MIN_PALETTE_CHARS = 20
MAX_PALETTE_CHARS = 400
MAX_SHOT_REPEAT_COUNT = 2
CONTENT_RETRY_WAIT_SECONDS = 25

# CHUNKED SHOT BREAKDOWN (2026-08-15): see script_writing.py history.
# Splitting one large shot request into smaller pieces keeps each call
# comfortably under the provider's free-tier token ceiling.
NUM_SHOT_CHUNKS = 2
CHUNK_MIN_SHOTS = MIN_SHOTS // NUM_SHOT_CHUNKS
CHUNK_MAX_SHOTS = -(-MAX_SHOTS // NUM_SHOT_CHUNKS)  # ceil division
SHOT_CHUNK_CALL_DELAY_SECONDS = 20

EXAMPLE_HOOK_TEXT = "312 DIARIES. ONE BOMB. GONE IN SECONDS."

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

# DIRECTOR FEATURES (2026-08-20)
VALID_LIGHTING = {
    "dawn", "morning", "midday", "golden_hour", "dusk", "night",
    "overcast", "firelight", "interior_lamp", "moonlight",
}
DEFAULT_LIGHTING = "midday"

VALID_BEAT_INTENSITY = {"low", "mid", "high"}
DEFAULT_BEAT_INTENSITY = "mid"

ZOOM_FAMILY_MOVEMENTS = {"push_in", "crash_zoom", "zoom_in", "snap_zoom", "dolly_in"}
MAX_ZOOM_SHOT_RATIO = 0.32
MAX_CONSECUTIVE_ZOOM_SHOTS = 2

MAX_CONSECUTIVE_SAME_SUBJECT = 3
MAX_SUBJECT_SHOT_RATIO = 0.30

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


def split_narration_into_chunks(narration_text, num_chunks):
    """Splits narration into num_chunks pieces, breaking only at sentence
    boundaries (never mid-sentence) and balancing word count across pieces
    as evenly as possible. Each chunk becomes its own, much smaller,
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

    lighting = shot.get("lighting")
    if lighting not in VALID_LIGHTING:
        lighting = DEFAULT_LIGHTING

    beat_intensity = shot.get("beat_intensity")
    if beat_intensity not in VALID_BEAT_INTENSITY:
        beat_intensity = DEFAULT_BEAT_INTENSITY

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
        "lighting": lighting,
        "beat_intensity": beat_intensity,
        "location_tag": (shot.get("location_tag") or "").strip(),
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


def find_location_change_without_establishing(normalized_shots):
    """DIRECTOR FEATURE (2026-08-20): whenever location_tag changes between
    consecutive shots (and both are non-empty), the new shot must be
    'wide' or 'establishing' shot_type. Shots with no location_tag set are
    skipped entirely (opt-in field, never blocks scripts that don't use it)."""
    hits = []
    prev_location = None
    for i, s in enumerate(normalized_shots):
        loc = s["location_tag"]
        if loc and prev_location and loc.lower() != prev_location.lower():
            if s["shot_type"] not in ("wide", "establishing"):
                hits.append((i, prev_location, loc))
        if loc:
            prev_location = loc
    return hits


def validate_and_normalize_shot_response(result, narration_text):
    """Validates everything EXCEPT narration_text/CTA, since those were
    already confirmed during the narration stage before this is ever called.
    Runs on the FULL stitched shot list (all chunks combined), so every
    episode-wide check here (total shot count, zoom ratio, subject
    dominance, location/establishing discipline, etc.) still applies
    exactly as before chunking was added."""
    setting_and_characters = (result.get("setting_and_characters") or "").strip()
    if len(setting_and_characters) < MIN_SETTING_CHARS:
        return False, (
            f"setting_and_characters missing or too short "
            f"({len(setting_and_characters)} chars, need at least {MIN_SETTING_CHARS}) - "
            f"must fix the real-world location/era/ethnicity and describe every "
            f"recurring character's appearance"
        )
    result["setting_and_characters"] = setting_and_characters[:MAX_SETTING_CHARS]

    color_palette = (result.get("color_palette") or "").strip()
    if len(color_palette) < MIN_PALETTE_CHARS:
        return False, (
            f"color_palette missing or too short ({len(color_palette)} chars, need "
            f"at least {MIN_PALETTE_CHARS}) - must give a concrete episode-wide color "
            f"and mood palette (e.g. dominant tones, saturation, contrast feel)"
        )
    result["color_palette"] = color_palette[:MAX_PALETTE_CHARS]

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

    location_hits = find_location_change_without_establishing(normalized_shots)
    if location_hits:
        idx, prev_loc, new_loc = location_hits[0]
        return False, (
            f"shot {idx} moves location from {prev_loc!r} to {new_loc!r} without using "
            f"a 'wide' or 'establishing' shot_type - whenever the story cuts to a new "
            f"location, the first shot there must re-establish it wide before cutting "
            f"closer, exactly like a real documentary edit."
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

COLOR AND LIGHT (episode-wide "color_palette" anchor given below): every
shot's mood and lighting choice must feel like it belongs to the same
graded film - do not swing from warm golden tones to cold blue tones and
back without a real story reason (time-of-day or location change).

VARY PHYSICAL REACTIONS - DO NOT DEFAULT TO GASPING: when a shot's
visual_description shows a character reacting to shock, danger, or a
sudden turn in the story, do not default to "gasps" / "gasping" / "a sharp
gasp" as the go-to reaction. Draw from a wide range of physical reactions
instead - a held breath, a stiffened body, a hand frozen mid-motion, wide
unmoving eyes, a dropped object, trembling hands, a clenched jaw, a
sudden stillness - and pick whichever fits this specific character and
moment. Across a full shot list, no single reaction beat (gasping
included) should repeat more than once or twice.

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

LOCATION CHANGES MUST RE-ESTABLISH (HARD RULE): fill "location_tag" with a
short consistent name for where the shot physically takes place (e.g.
"village square", "riverbank", "soldier's tent"). Whenever the story moves
to a new location, the FIRST shot in that new location must use shot_type
"wide" or "establishing" before cutting closer - never open a new location
on a medium or close_up shot. If a shot doesn't have a clearly defined
location, leave location_tag as "".

MATCH CUTS AND VISUAL RHYMES: where two moments in the story naturally
echo each other (e.g. hands closing a diary early on, hands closing a
coffin later), compose both shots with matching framing/composition so the
visual rhyme reads clearly - this is a major driver of a "crafted" feel.

SILENCE AS A TOOL: not every shot needs an sfx_cue. Before a major reveal
or emotional beat, it is often stronger to deliberately leave sfx_cue as ""
and let the moment sit in silence rather than filling it with sound.

LEGIBLE ON-SCREEN TEXT (HARD RULE - THIS IS THE #1 CAUSE OF REJECTED SHOT
LISTS): if a shot's visual_description mentions ANY of the following words -
newspaper, letter, document, sign, headline, inscription, poster, map,
book, plaque, telegram, postcard, banner, ledger, diary, certificate,
gravestone, tombstone - you MUST either (a) fill "required_onscreen_text"
with the exact wording that must appear on it, correctly spelled, or (b)
rewrite the visual_description so that object is present but not the
readable focus of the shot (e.g. a closed book on a shelf, a letter held
face-down). A shot that names one of these objects with
required_onscreen_text left empty is an automatic rejection of the entire
shot list - check every single shot against this list before finishing
your response.

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
- "lighting": one of "dawn", "morning", "midday", "golden_hour", "dusk",
  "night", "overcast", "firelight", "interior_lamp", "moonlight" - must
  stay consistent with the story's actual timeline, not jump around
  without reason.
- "beat_intensity": one of "low", "mid", "high" - how emotionally charged
  this exact moment is. Use this to shape pacing: mostly "low"/"mid" early,
  building toward more "high" beats near the episode's climax.
- "location_tag": short consistent name for where this shot takes place,
  or "" if not clearly a distinct location.

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
  be audible or where silence is the deliberate choice (see SILENCE AS A
  TOOL above)."""


def build_shot_breakdown_chunk_prompt(
    title, angle, chunk_text, chunk_index, num_chunks,
    min_shots_chunk, max_shots_chunk,
    setting_and_characters=None, color_palette=None,
    prior_last_subject=None, prior_last_movement=None,
):
    """Builds the prompt for ONE narration chunk's shot breakdown. The
    first chunk (chunk_index == 0) also produces the episode-wide
    setting_and_characters/hook_text/music_mood/color_palette anchor; later
    chunks are handed that same anchor text back so every shot stays
    visually consistent, and are given a short note on the previous
    chunk's last shot so cutaway discipline carries across the chunk
    boundary."""
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

COLOR PALETTE - include "color_palette": a fixed episode-wide color and
mood grade (e.g. "desaturated blues and greys with warm amber highlights
at emotional peaks, high contrast, slightly crushed blacks"). This will
also be attached to every shot's generation prompt, so every shot stays
visually part of the same graded film rather than looking like disconnected
images. 1-3 sentences.

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
  "color_palette": "1-3 sentence fixed color/mood grade for the WHOLE episode.",
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

COLOR PALETTE - this is ALSO ALREADY FIXED for the whole episode. Every
shot's lighting/mood must stay consistent with it:

---
{color_palette}
---

Do NOT invent a new setting_and_characters, color_palette, hook_text, or
music_mood in this response - this segment only returns a shot_list.

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
required_onscreen_text left empty will be rejected outright. Also confirm
every shot has "lighting", "beat_intensity", and "location_tag" filled in,
and that any location change is opened with a wide/establishing shot.

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
      "required_onscreen_text": "REQUIRED if visual_description names a newspaper/letter/sign/document/etc - the exact wording, otherwise leave as empty string",
      "lighting": "midday",
      "beat_intensity": "mid",
      "location_tag": "short consistent location name, or empty string"
    }}
  ]
}}

Include between {min_shots_chunk} and {max_shots_chunk} shots covering this
segment's narration above - every shot must be distinct, never repeat an
earlier shot."""


def generate_shot_breakdown(title, angle, narration_text):
    """CHUNKED (2026-08-15): splits narration into NUM_SHOT_CHUNKS pieces and
    makes one small LLM call per piece (spaced SHOT_CHUNK_CALL_DELAY_SECONDS
    apart), instead of one huge call that structurally cannot fit under the
    provider's free-tier token ceiling. All chunk shot_lists are stitched
    and renumbered, then validated with the exact same episode-wide rules
    as before chunking (validate_and_normalize_shot_response is unchanged
    in structure, only extended with the new color_palette/location checks)."""
    chunks = split_narration_into_chunks(narration_text, NUM_SHOT_CHUNKS)
    num_chunks = len(chunks)

    last_reason = None
    ever_reached_content = False
    content_attempt = 0
    infra_attempt = 0

    while content_attempt < MAX_GENERATION_ATTEMPTS:
        setting_and_characters = None
        color_palette = None
        hook_text = None
        music_mood = None
        stitched_shots = []
        infra_failed_this_round = False
        content_failure_reason = None

        for idx, chunk_text in enumerate(chunks):
            if idx > 0:
                print(f"[shots] Waiting {SHOT_CHUNK_CALL_DELAY_SECONDS}s before segment "
                      f"{idx + 1}/{num_chunks} call...")
                time.sleep(SHOT_CHUNK_CALL_DELAY_SECONDS)

            prior_last_subject = stitched_shots[-1].get("primary_subject") if stitched_shots else None
            prior_last_movement = stitched_shots[-1].get("camera_movement") if stitched_shots else None

            prompt = build_shot_breakdown_chunk_prompt(
                title, angle, chunk_text, idx, num_chunks,
                CHUNK_MIN_SHOTS, CHUNK_MAX_SHOTS,
                setting_and_characters=setting_and_characters,
                color_palette=color_palette,
                prior_last_subject=prior_last_subject,
                prior_last_movement=prior_last_movement,
            )

            try:
                raw = call_llm(prompt)
            except DailyQuotaExhausted:
                # FIX (2026-08-15, later): propagate straight up, do not
                # treat as an ordinary per-chunk infra retry.
                raise
            except RuntimeError as e:
                infra_attempt += 1
                last_reason = f"LLM call failed on segment {idx + 1}/{num_chunks}: {e}"
                print(f"[shots] Infra retry {infra_attempt}/{MAX_INFRA_ATTEMPTS} failed - {last_reason} "
                      f"(does not count against the {MAX_GENERATION_ATTEMPTS} content attempts)")
                infra_failed_this_round = True
                break

            ever_reached_content = True
            try:
                parsed = extract_json(raw)
            except ValueError as e:
                content_failure_reason = f"JSON parse failed on segment {idx + 1}/{num_chunks}: {e}"
                break

            if idx == 0:
                setting_and_characters = (parsed.get("setting_and_characters") or "").strip()
                color_palette = (parsed.get("color_palette") or "").strip()
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
                      f"(prevents bursting past the free-tier RPM ceiling)...")
                time.sleep(CONTENT_RETRY_WAIT_SECONDS)
            continue

        for i, shot in enumerate(stitched_shots):
            shot["shot_number"] = i + 1

        result = {
            "setting_and_characters": setting_and_characters,
            "color_palette": color_palette,
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
                  f"(prevents bursting past the free-tier RPM ceiling)...")
            time.sleep(CONTENT_RETRY_WAIT_SECONDS)

    if not ever_reached_content:
        raise InfraFailure(
            f"LLM never returned a usable response after {infra_attempt} infra "
            f"retries during shot-breakdown stage (narration was already confirmed "
            f"good). Last reason: {last_reason}"
        )
    raise RuntimeError(f"Shot breakdown failed after {content_attempt} content attempts. Last reason: {last_reason}")
