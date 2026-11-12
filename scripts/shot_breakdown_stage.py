"""
Marius Command Center - Shot Breakdown Stage
Stage 2 of script generation: from a confirmed-length narration, build the
shot-by-shot visual production plan.

REWRITE 2026-11-12 (quality fix plan, step 1). Script 17fc73b3 produced a
video with one woman on screen for 17 minutes, morphing faces and objects
appearing from nowhere. Measured causes fixed here:
  1. 30 shots for 1,020 s of narration = 34 s per shot. The Kaggle clip
     generator chains 4 s pieces, so long shots drift and morph. The planner
     now writes about ONE SHOT PER 4-6 SECONDS of narration (about 200 shots
     for a 17 minute script). Narration length is estimated from word count
     (WORDS_PER_SECOND) and split into segments of about CHUNK_TARGET_SECONDS.
  2. The protagonist limit was blind: it only counted shots whose
     primary_subject tag was filled in, and the tags were empty. The
     protagonist is now counted BY NAME (prompt_focus.protagonist_name) in
     visual_description and primary_subject, with a hard cap of
     PROTAGONIST_MAX_RATIO (30%) per segment and over the whole episode.
  3. Every shot is written as ONE visible action given as a direct command,
     with every object in frame named (nothing may appear from nowhere).
  4. The video model draws faces badly: wide/medium shots are preferred, and
     face close-ups are repaired to medium shots.
Each segment is validated and retried on its own (up to CHUNK_MAX_ATTEMPTS)
with the reason fed back into the prompt, so one bad segment no longer throws
away the whole 17-segment run. Checks that are always mechanically fixable
(zoom ratio, location establishing, subject runs, face close-ups, readable
text) are repaired in place instead of rejecting.

DOCUMENTARY VFX + SURROUND AMBIENCE (2026-11-12): the final videos had no
continuous sound of the place (only one short sound clip per shot, plain
stereo) and almost no visual effects (the rules said lens_effect "none" on
most shots). Two changes here, both mechanically guaranteed:
  1. New per-shot field "ambience_cue": the continuous environment bed
     (wind, room tone, distant traffic ...). Required on every shot. Shots in
     the same location share the SAME cue word for word so the bed runs
     unbroken; assembly_stage/ambience_mix build the actual bed from it.
     auto_repair_ambience() fills empty cues from the lighting/location and
     unifies cues inside one location, so this can never reject a plan.
  2. At least MIN_VFX_RATIO (about 1 in 3) of shots now carry a real
     lens_effect (film grain on wides, shallow depth of field on details and
     mediums, lens flare only in dawn/golden/dusk light, at most 10%).
     auto_repair_vfx() tops the share up, spread evenly, if the model wrote
     too few. The final grade/vignette is applied in assembly_stage.

HISTORY (condensed; full text is in git history before this rewrite):
  2026-08-15 chunked breakdown; 08-20 director fields + writer/checker split;
  08-24 anachronism gate; 08-25 duplicate-character gate; 09-08 documentary
  tightening; 09-10 idle-crowd gate; 09-12/13 onscreen-text auto-repair;
  09-13/14 subject and location auto-repair; 09-14 Gemini response_schema
  tried and reverted (400 INVALID_ARGUMENT, cause never found) - this file
  does NOT use response_schema, only prose rules plus extract_json repair.
"""

import math
import re
import time
from collections import Counter

from llm_client import call_llm, extract_json, DailyQuotaExhausted, InfraFailure
from quality_checker import grade_shot_breakdown
from prompt_focus import protagonist_name, visual_has_people

# --- sizing -----------------------------------------------------------------
WORDS_PER_SECOND = 2.5            # narration pace used to estimate length
TARGET_SHOT_SECONDS = 5.0         # aim: one shot every ~5 s
MIN_AVG_SHOT_SECONDS = 3.0        # more choppy than this is rejected
MAX_AVG_SHOT_SECONDS = 7.0        # slower than this is rejected
HARD_MAX_SHOT_SECONDS = 12.0      # no single shot may cover more narration
CHUNK_TARGET_SECONDS = 60.0       # narration seconds per LLM call
MIN_COVERAGE = 0.80               # shots must quote >= this share of the segment
MIN_SHOTS = 25                    # sanity floor (matches verify_run_output.py)
MAX_SHOTS = 450                   # sanity ceiling (matches verify_run_output.py)

# --- retries ----------------------------------------------------------------
MAX_GENERATION_ATTEMPTS = 2       # whole-plan attempts (checker rejection etc.)
CHUNK_MAX_ATTEMPTS = 3            # attempts per segment
MAX_INFRA_ATTEMPTS = 4
CHUNK_RETRY_WAIT_SECONDS = 10
SHOT_CHUNK_CALL_DELAY_SECONDS = 15
CHECKER_WINDOW = 20               # shots per window sent to the checker
CHECKER_WINDOWS = 3               # start, middle, end

# --- text limits ------------------------------------------------------------
MAX_HOOK_TEXT_CHARS = 40
MAX_HOOK_TEXT_WORDS = 5
MIN_SETTING_CHARS = 40
MAX_SETTING_CHARS = 900
MIN_PALETTE_CHARS = 20
MAX_PALETTE_CHARS = 400
MAX_SHOT_REPEAT_COUNT = 2

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
VALID_LENS_EFFECTS = {"shallow_depth_of_field", "lens_flare", "film_grain", "none"}
VALID_LIGHTING = {
    "dawn", "morning", "midday", "golden_hour", "dusk", "night",
    "overcast", "firelight", "interior_lamp", "moonlight",
}
DEFAULT_LIGHTING = "midday"
VALID_FRAMING_ANGLE = {"eye_level", "low_angle", "high_angle", "overhead"}
DEFAULT_FRAMING_ANGLE = "eye_level"
VALID_DEPTH_OF_FIELD = {"shallow", "deep", "standard"}
DEFAULT_DEPTH_OF_FIELD = "standard"
VALID_BEAT_INTENSITY = {"low", "mid", "high"}
DEFAULT_BEAT_INTENSITY = "mid"

ZOOM_FAMILY_MOVEMENTS = {"push_in", "crash_zoom", "zoom_in", "snap_zoom", "dolly_in"}
MAX_ZOOM_SHOT_RATIO = 0.32
MAX_CONSECUTIVE_ZOOM_SHOTS = 2

# --- documentary VFX + ambience (2026-11-12) --------------------------------
MIN_VFX_RATIO = 0.34              # at least this share of shots carry a lens_effect
MAX_LENS_FLARE_RATIO = 0.10       # lens flare is rare: at most 1 in 10 shots
MIN_AMBIENCE_WORDS = 3            # shorter ambience_cue counts as missing
MAX_AMBIENCE_WORDS = 14           # longer ambience_cue is trimmed
FLARE_LIGHTING = ("golden_hour", "dawn", "dusk")
AMBIENCE_BY_LIGHTING = {
    "night": "quiet night air, faint distant wind",
    "moonlight": "quiet night air, faint distant wind",
    "dawn": "early morning air, distant birdsong, soft wind",
    "morning": "morning air, distant street life",
    "midday": "open air, faint distant street life",
    "golden_hour": "warm evening air, soft wind",
    "dusk": "evening air, distant dogs barking, soft wind",
    "overcast": "overcast air, steady low wind",
    "firelight": "crackling fire, quiet night air",
    "interior_lamp": "quiet room tone, faint clock ticking",
}

PROTAGONIST_MAX_RATIO = 0.30      # protagonist named in at most 30% of shots
MAX_CONSECUTIVE_SAME_SUBJECT = 2
MAX_SUBJECT_SHOT_RATIO = 0.30

# Only phrases that make a shot depend on the shot before/after it. A single
# visible action ("a clerk stamps a file") is now REQUIRED, so action verbs
# are no longer banned.
CONTINUATION_BANNED_PHRASES = (
    "continues to", "continues ", "continuing to", "then walks", "then runs",
    "then turns", "then opens", "then reaches", "then picks", "then lifts",
    "then carries", "then hands", "then pours", "begins to ", "starts to ",
    "proceeds to", "a moment later", "seconds later", "afterwards",
)

LOITERING_BANNED_PHRASES = (
    "standing around", "standing there", "standing nearby", "standing idly",
    "just standing", "simply standing", "standing quietly with no",
    "waiting there", "waiting around", "sitting there doing nothing",
    "looking around aimlessly", "with nothing in particular",
)

IDLE_CROWD_BANNED_PHRASES = (
    "crowd stands", "crowd standing", "crowd stood", "crowd gathered watching",
    "crowd looks on", "crowd looking on", "crowd watches silently",
    "onlookers stand", "onlookers standing", "onlookers watch silently",
    "bystanders stand", "bystanders standing", "bystanders watch silently",
    "people standing around", "people stand around", "people milling about",
    "villagers stand", "villagers standing", "crowd of people standing",
    "group of people standing", "spectators standing", "spectators stand",
)

ONSCREEN_TEXT_KEYWORDS = (
    "newspaper", "letter", "document", "sign", "headline", "inscription",
    "poster", "map", "book", "plaque", "telegram", "postcard", "banner",
    "ledger", "diary", "certificate", "gravestone", "tombstone",
)

MODERN_OBJECT_KEYWORDS = (
    "laptop", "computer screen", "computer monitor", "desktop computer",
    "smartphone", "smart phone", "cell phone", "cellphone", "mobile phone",
    "iphone", "tablet computer", "ipad", "drone", "quadcopter",
    "flat screen", "flatscreen", "led screen", "led display", "lcd screen",
    "digital display", "digital screen", "touchscreen", "touch screen",
    "wifi router", "bluetooth", "usb", "solar panel", "security camera",
    "cctv", "led light strip", "plastic water bottle",
)

DUPLICATE_CHARACTER_KEYWORDS = (
    "her own reflection standing", "his own reflection standing",
    "mirror image of her", "mirror image of him",
    "twin of her", "twin of him", "her twin", "his twin",
    "double of her", "double of him", "her double", "his double",
    "duplicate of her", "duplicate of him",
    "clone of her", "clone of him",
    "two versions of her", "two versions of him",
    "second copy of her", "second copy of him",
    "identical copies of her", "identical copies of him",
    "both her and her", "both him and him",
)

FACE_WORDS = ("face", "faces", "eye", "eyes", "gaze", "stare", "staring", "portrait", "expression")


class ChunkFailure(Exception):
    """A segment could not be produced after CHUNK_MAX_ATTEMPTS attempts."""


# --- sizing helpers ----------------------------------------------------------

def estimate_seconds(text):
    return len((text or "").split()) / WORDS_PER_SECOND


def plan_chunking(narration_text):
    total = estimate_seconds(narration_text)
    return total, max(1, int(round(total / CHUNK_TARGET_SECONDS)))


def shot_bounds(seconds):
    lo = max(1, int(seconds // MAX_AVG_SHOT_SECONDS))
    hi = max(lo + 1, int(math.ceil(seconds / MIN_AVG_SHOT_SECONDS)))
    return lo, hi


def protagonist_cap(shot_count):
    return max(1, int(shot_count * PROTAGONIST_MAX_RATIO))


def split_narration_into_chunks(narration_text, num_chunks):
    """Splits narration into num_chunks pieces at sentence boundaries,
    balancing word count as evenly as possible."""
    sentences = re.split(r"(?<=[.!?])\s+", narration_text.strip())
    sentences = [s for s in sentences if s.strip()]
    if len(sentences) <= num_chunks:
        return [s.strip() for s in sentences] or [narration_text.strip()]
    total_words = sum(len(s.split()) for s in sentences)
    target_words = total_words / num_chunks
    chunks, current, current_words = [], [], 0
    for sentence in sentences:
        current.append(sentence)
        current_words += len(sentence.split())
        if current_words >= target_words and len(chunks) < num_chunks - 1:
            chunks.append(" ".join(current).strip())
            current, current_words = [], 0
    if current:
        chunks.append(" ".join(current).strip())
    return chunks


# --- normalisation -----------------------------------------------------------

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
    framing_angle = shot.get("framing_angle")
    if framing_angle not in VALID_FRAMING_ANGLE:
        framing_angle = DEFAULT_FRAMING_ANGLE
    depth_of_field = shot.get("depth_of_field")
    if depth_of_field not in VALID_DEPTH_OF_FIELD:
        depth_of_field = DEFAULT_DEPTH_OF_FIELD
    return {
        "shot_number": shot.get("shot_number", index + 1),
        "visual_description": shot.get("visual_description", "") or "",
        "narration_excerpt": shot.get("narration_excerpt", "") or "",
        "shot_type": shot_type,
        "camera_movement": camera_movement,
        "camera_reason": shot.get("camera_reason", "") or "",
        "lens_effect": lens_effect,
        "sfx_cue": shot.get("sfx_cue", "") or "",
        "ambience_cue": (shot.get("ambience_cue") or "").strip(),
        "primary_subject": (shot.get("primary_subject") or "").strip(),
        "required_onscreen_text": (shot.get("required_onscreen_text") or "").strip(),
        "lighting": lighting,
        "beat_intensity": beat_intensity,
        "location_tag": (shot.get("location_tag") or "").strip(),
        "framing_angle": framing_angle,
        "depth_of_field": depth_of_field,
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
    return len(hook_text.split()) > MAX_HOOK_TEXT_WORDS


def hook_text_matches_story(hook_text, narration_text):
    if not hook_text or not narration_text:
        return False
    narration_lower = narration_text.lower()
    hook_words = [w.strip(".,!?\"'").lower() for w in hook_text.split()]
    meaningful_words = [w for w in hook_words if len(w) >= 4]
    if not meaningful_words:
        return True
    return any(w in narration_lower for w in meaningful_words)


# --- detectors ---------------------------------------------------------------

def find_duplicate_shots(shots):
    pair_counts = Counter(
        ((s["visual_description"] or "").strip().lower(), (s["narration_excerpt"] or "").strip().lower())
        for s in shots
    )
    return [(v, n, c) for (v, n), c in pair_counts.items() if v and c > MAX_SHOT_REPEAT_COUNT]


def find_empty_shots(shots):
    return [
        i for i, s in enumerate(shots)
        if not (s["visual_description"] or "").strip() or not (s["narration_excerpt"] or "").strip()
    ]


def _phrase_hits(shots, phrases):
    hits = []
    for i, s in enumerate(shots):
        desc = (s["visual_description"] or "").lower()
        for phrase in phrases:
            if phrase in desc:
                hits.append((i, phrase))
                break
    return hits


def find_continuation_language_shots(shots):
    return _phrase_hits(shots, CONTINUATION_BANNED_PHRASES)


def find_loitering_shots(shots):
    return _phrase_hits(shots, LOITERING_BANNED_PHRASES)


def find_idle_crowd_shots(shots):
    return _phrase_hits(shots, IDLE_CROWD_BANNED_PHRASES)


def find_anachronistic_object_shots(shots):
    return _phrase_hits(shots, MODERN_OBJECT_KEYWORDS)


def find_duplicate_character_shots(shots):
    return _phrase_hits(shots, DUPLICATE_CHARACTER_KEYWORDS)


def find_missing_onscreen_text_shots(shots, skip_indices=None):
    skip_indices = skip_indices or set()
    hits = []
    for i, s in enumerate(shots):
        if i in skip_indices:
            continue
        desc = (s["visual_description"] or "").lower()
        if any(kw in desc for kw in ONSCREEN_TEXT_KEYWORDS) and not s["required_onscreen_text"]:
            hits.append(i)
    return hits


def shot_mentions_protagonist(shot, name):
    text = " ".join([shot.get("visual_description") or "", shot.get("primary_subject") or ""]).lower()
    if name and re.search(r"\b" + re.escape(name.lower()) + r"\b", text):
        return True
    return "protagonist" in text or "main character" in text


def protagonist_shot_indices(shots, name):
    return [i for i, s in enumerate(shots) if shot_mentions_protagonist(s, name)]


def seconds_for_excerpt(excerpt):
    return estimate_seconds(excerpt)


def find_dominant_subject(shots):
    subject_counts = Counter(s["primary_subject"].lower() for s in shots if s["primary_subject"])
    if not subject_counts:
        return None
    subject, count = subject_counts.most_common(1)[0]
    ratio = count / len(shots)
    if ratio > MAX_SUBJECT_SHOT_RATIO:
        return subject, count, ratio
    return None


def find_excessive_consecutive_subject(shots):
    run_subject, run_length = None, 0
    for i, s in enumerate(shots):
        subject = s["primary_subject"].lower()
        if subject and subject == run_subject:
            run_length += 1
        else:
            run_subject = subject
            run_length = 1 if subject else 0
        if run_length > MAX_CONSECUTIVE_SAME_SUBJECT:
            return i, run_subject, run_length
    return None


def find_location_change_without_establishing(shots, prev_location=None):
    hits = []
    for i, s in enumerate(shots):
        loc = s["location_tag"]
        if loc and prev_location and loc.lower() != prev_location.lower():
            if s["shot_type"] not in ("wide", "establishing"):
                hits.append((i, prev_location, loc))
        if loc:
            prev_location = loc
    return hits


# --- auto-repairs (always safe, mechanical) ----------------------------------

def auto_repair_missing_onscreen_text(shots):
    repaired = set()
    for i, s in enumerate(shots):
        desc = s["visual_description"] or ""
        if any(kw in desc.lower() for kw in ONSCREEN_TEXT_KEYWORDS) and not s["required_onscreen_text"]:
            s["visual_description"] = desc.rstrip(". ") + ", angled and lit so no text on it is legible to the viewer."
            repaired.add(i)
    return repaired


def auto_repair_excessive_consecutive_subject(shots):
    repaired = set()
    run_subject, run_length = None, 0
    for i, s in enumerate(shots):
        subject_lower = s["primary_subject"].lower()
        if subject_lower and subject_lower == run_subject:
            run_length += 1
        else:
            run_subject = subject_lower
            run_length = 1 if subject_lower else 0
        if subject_lower and run_length > MAX_CONSECUTIVE_SAME_SUBJECT:
            s["primary_subject"] = ""
            repaired.add(i)
            run_subject, run_length = None, 0
    return repaired


def auto_repair_dominant_subject(shots):
    repaired = set()
    total = len(shots)
    if total == 0:
        return repaired
    max_allowed = int(total * MAX_SUBJECT_SHOT_RATIO)
    while True:
        counts = Counter(s["primary_subject"].lower() for s in shots if s["primary_subject"])
        if not counts:
            break
        subject, count = counts.most_common(1)[0]
        if count <= max_allowed:
            break
        indices = [i for i, s in enumerate(shots) if s["primary_subject"].lower() == subject]
        idx = indices[len(indices) // 2]
        shots[idx]["primary_subject"] = ""
        repaired.add(idx)
    return repaired


def auto_repair_location_change_without_establishing(shots, prev_location=None):
    repaired = set()
    for i, s in enumerate(shots):
        loc = s["location_tag"]
        if loc and prev_location and loc.lower() != prev_location.lower():
            if s["shot_type"] not in ("wide", "establishing"):
                s["shot_type"] = "establishing"
                if s["depth_of_field"] == "shallow":
                    s["depth_of_field"] = "standard"
                repaired.add(i)
        if loc:
            prev_location = loc
    return repaired


def auto_repair_zoom_discipline(shots):
    """Breaks zoom runs and trims the zoom share to MAX_ZOOM_SHOT_RATIO by
    switching offending shots to a calm camera. Returns repaired indices."""
    repaired = set()
    run = 0
    for i, s in enumerate(shots):
        if s["camera_movement"] in ZOOM_FAMILY_MOVEMENTS:
            run += 1
            if run > MAX_CONSECUTIVE_ZOOM_SHOTS:
                s["camera_movement"] = "pan_right" if i % 2 else "pan_left"
                repaired.add(i)
                run = 0
        else:
            run = 0

    def zoomy(s):
        return s["camera_movement"] in ZOOM_FAMILY_MOVEMENTS or s["shot_type"] == "extreme_close_up"

    limit = int(len(shots) * MAX_ZOOM_SHOT_RATIO)
    for i, s in enumerate(shots):
        if sum(1 for x in shots if zoomy(x)) <= limit:
            break
        if zoomy(s):
            if s["camera_movement"] in ZOOM_FAMILY_MOVEMENTS:
                s["camera_movement"] = "static"
            if s["shot_type"] == "extreme_close_up":
                s["shot_type"] = "close_up"
            repaired.add(i)
    return repaired


def auto_repair_face_closeups(shots):
    """The video model draws faces badly: a close-up whose description is
    about a face/eyes becomes a medium shot."""
    repaired = set()
    for i, s in enumerate(shots):
        if s["shot_type"] not in ("close_up", "extreme_close_up"):
            continue
        desc = (s["visual_description"] or "").lower()
        if visual_has_people(desc) and any(re.search(r"\b" + w + r"\b", desc) for w in FACE_WORDS):
            s["shot_type"] = "medium"
            if s["depth_of_field"] == "shallow":
                s["depth_of_field"] = "standard"
            repaired.add(i)
    return repaired


def auto_repair_ambience(shots):
    """Every shot needs a continuous ambience bed (ambience_cue). Fills empty
    or too-short cues from the previous shot when it is in the same location,
    otherwise from the lighting; trims over-long cues; and makes consecutive
    shots in one location share the SAME cue so the bed runs unbroken.
    Returns the set of repaired indices."""
    repaired = set()
    prev = None
    for i, s in enumerate(shots):
        cue = (s["ambience_cue"] or "").strip()
        words = cue.split()
        if len(words) > MAX_AMBIENCE_WORDS:
            cue = " ".join(words[:MAX_AMBIENCE_WORDS]).rstrip(",;")
            words = cue.split()
            repaired.add(i)
        same_place = (
            prev is not None and s["location_tag"] and prev["location_tag"]
            and s["location_tag"].lower() == prev["location_tag"].lower()
        )
        if len(words) < MIN_AMBIENCE_WORDS:
            cue = prev["ambience_cue"] if same_place else AMBIENCE_BY_LIGHTING.get(
                s["lighting"], AMBIENCE_BY_LIGHTING[DEFAULT_LIGHTING])
            repaired.add(i)
        elif same_place and cue.lower() != prev["ambience_cue"].lower():
            cue = prev["ambience_cue"]
            repaired.add(i)
        s["ambience_cue"] = cue
        prev = s
    return repaired


def auto_repair_vfx(shots):
    """Tops the share of shots with a real lens_effect up to MIN_VFX_RATIO,
    spread evenly through the episode. Wide/establishing shots get film grain
    (or a rare lens flare in dawn/golden/dusk light, at most
    MAX_LENS_FLARE_RATIO of shots); detail inserts and mediums get shallow
    depth of field; anything else gets film grain. Returns repaired indices."""
    repaired = set()
    n = len(shots)
    if n == 0:
        return repaired
    target = int(math.ceil(n * MIN_VFX_RATIO))
    have = sum(1 for s in shots if s["lens_effect"] != "none")
    if have >= target:
        return repaired
    candidates = [i for i, s in enumerate(shots) if s["lens_effect"] == "none"]
    need = min(target - have, len(candidates))
    step = len(candidates) / need
    flare_limit = int(n * MAX_LENS_FLARE_RATIO)
    flares = sum(1 for s in shots if s["lens_effect"] == "lens_flare")
    for k in range(need):
        s = shots[candidates[int(k * step)]]
        is_wide = s["shot_type"] in ("wide", "establishing")
        if is_wide and s["lighting"] in FLARE_LIGHTING and flares < flare_limit:
            s["lens_effect"] = "lens_flare"
            flares += 1
        elif not is_wide and s["shot_type"] in ("detail_insert", "medium", "close_up") \
                and s["depth_of_field"] != "deep":
            s["lens_effect"] = "shallow_depth_of_field"
        else:
            s["lens_effect"] = "film_grain"
        repaired.add(candidates[int(k * step)])
    return repaired


def scrub_protagonist(shot, name):
    """LAST RESORT when a segment still names the protagonist too often:
    the name is replaced so the shot no longer carries the protagonist."""
    desc = shot["visual_description"]
    if name:
        desc = re.sub(r"\b" + re.escape(name) + r"\b", "an unidentified person", desc)
    desc = re.sub(r"\bthe (?:recurring )?protagonist\b", "an unidentified person", desc, flags=re.IGNORECASE)
    desc = re.sub(r"\bthe main character\b", "an unidentified person", desc, flags=re.IGNORECASE)
    shot["visual_description"] = desc
    shot["primary_subject"] = ""


def enforce_protagonist_cap(shots, name):
    """Scrubs the middle occurrences until the cap holds. Returns the count scrubbed."""
    if not name and not any("protagonist" in (s["visual_description"] or "").lower() for s in shots):
        return 0
    scrubbed = 0
    cap = protagonist_cap(len(shots))
    while True:
        idx = protagonist_shot_indices(shots, name)
        if len(idx) <= cap:
            break
        pick = idx[len(idx) // 2]
        scrub_protagonist(shots[pick], name)
        scrubbed += 1
        if scrubbed > len(shots):
            break
    return scrubbed


# --- validation --------------------------------------------------------------

def anchor_problem(setting, palette):
    if len(setting) < MIN_SETTING_CHARS:
        return (f"setting_and_characters missing or too short ({len(setting)} chars, need at least "
                f"{MIN_SETTING_CHARS}) - fix the real-world location/era/ethnicity and describe every "
                f"recurring character's appearance")
    if len(palette) < MIN_PALETTE_CHARS:
        return (f"color_palette missing or too short ({len(palette)} chars, need at least "
                f"{MIN_PALETTE_CHARS}) - give a concrete episode-wide color and mood palette")
    return None


def anchor_declares_no_protagonist(anchor):
    low = (anchor or "").lower()
    return "no single recurring protagonist" in low or "no individually" in low or "no recurring protagonist" in low


def hook_problem(parsed, shot_list_raw, narration_text):
    hook = normalize_hook_text({"hook_text": parsed.get("hook_text"), "shot_list": shot_list_raw})
    if hook_text_matches_prompt_example(hook):
        return "hook_text copied the prompt's example verbatim - write a real one from this story"
    if hook_text_too_long_to_glance(hook):
        return f"hook_text is {len(hook.split())} words - max {MAX_HOOK_TEXT_WORDS}"
    if not hook_text_matches_story(hook, narration_text):
        return f"hook_text {hook!r} does not appear related to this story's narration"
    return None


def content_problems(shots):
    """Hard content checks shared by segment and whole-list validation.
    Returns a reason string, or None when everything passes."""
    empty = find_empty_shots(shots)
    if empty:
        return (f"{len(empty)} shot(s) have an empty visual_description and/or narration_excerpt "
                f"(first at shot {empty[0] + 1}) - every shot needs real content")
    dups = find_duplicate_shots(shots)
    if dups:
        worst = max(dups, key=lambda d: d[2])
        return (f"a shot is repeated {worst[2]} times ({worst[0][:70]!r}) - every shot must be distinct "
                f"and cover new narration")
    hits = find_anachronistic_object_shots(shots)
    if hits:
        return (f"{len(hits)} shot(s) name a modern object (first at shot {hits[0][0] + 1}, "
                f"{hits[0][1]!r}) - use only objects that existed in this story's era")
    hits = find_duplicate_character_shots(shots)
    if hits:
        return (f"shot {hits[0][0] + 1} shows the same character twice ({hits[0][1]!r}) - a named "
                f"character appears exactly once per shot")
    hits = find_continuation_language_shots(shots)
    if hits:
        return (f"shot {hits[0][0] + 1} depends on another shot or describes a sequence "
                f"({hits[0][1]!r}) - each shot is ONE self-contained visible action")
    hits = find_loitering_shots(shots)
    if hits:
        return (f"shot {hits[0][0] + 1} has a person doing nothing ({hits[0][1]!r}) - give every "
                f"person a concrete task")
    hits = find_idle_crowd_shots(shots)
    if hits:
        return (f"shot {hits[0][0] + 1} has an idle crowd ({hits[0][1]!r}) - give the crowd an "
                f"activity or remove it")
    return None


def validate_chunk(raw_shots, chunk_text, name, prev_location=None):
    """Validates ONE segment. Returns (ok, reason_or_None, normalized_shots)."""
    chunk_seconds = estimate_seconds(chunk_text)
    lo, hi = shot_bounds(chunk_seconds)
    target = max(1, int(round(chunk_seconds / TARGET_SHOT_SECONDS)))
    if len(raw_shots) < lo or len(raw_shots) > hi:
        return False, (f"you wrote {len(raw_shots)} shots but this segment (about {chunk_seconds:.0f} s of "
                       f"narration) needs between {lo} and {hi}, aiming for about {target} - one shot per "
                       f"4-6 seconds of narration"), []
    shots = [normalize_shot(s, i) for i, s in enumerate(raw_shots)]

    problem = content_problems(shots)
    if problem:
        return False, problem, []

    too_long = [i for i, s in enumerate(shots)
                if seconds_for_excerpt(s["narration_excerpt"]) > HARD_MAX_SHOT_SECONDS]
    if too_long:
        words = len(shots[too_long[0]]["narration_excerpt"].split())
        return False, (f"shot {too_long[0] + 1} covers {words} words (about "
                       f"{seconds_for_excerpt(shots[too_long[0]]['narration_excerpt']):.0f} s) - split it; "
                       f"no shot may cover more than about {int(HARD_MAX_SHOT_SECONDS * WORDS_PER_SECOND)} words"), []

    chunk_words = len(chunk_text.split())
    covered = sum(len(s["narration_excerpt"].split()) for s in shots)
    if chunk_words and covered < MIN_COVERAGE * chunk_words:
        return False, (f"your narration_excerpt fields only cover {covered} of the segment's "
                       f"{chunk_words} words - the excerpts must quote the WHOLE segment, in order, "
                       f"with no skipped sentences"), []

    auto_repair_missing_onscreen_text(shots)
    auto_repair_face_closeups(shots)
    auto_repair_location_change_without_establishing(shots, prev_location)

    if name:
        idx = protagonist_shot_indices(shots, name)
        cap = protagonist_cap(len(shots))
        if len(idx) > cap:
            return False, (f"{name} appears in {len(idx)} of {len(shots)} shots (shots "
                           f"{', '.join(str(i + 1) for i in idx[:12])}) but at most {cap} are allowed - "
                           f"rewrite the extra ones as B-roll: places, objects, documents, other unnamed "
                           f"people doing tasks, landscapes, aftermath - and do not name {name} in them"), []
    return True, None, shots


def validate_and_normalize_shot_response(result, narration_text):
    """Whole-list validation after all segments are stitched. Mostly
    mechanical repairs, because every segment was already validated."""
    setting = (result.get("setting_and_characters") or "").strip()
    palette = (result.get("color_palette") or "").strip()
    problem = anchor_problem(setting, palette)
    if problem:
        return False, problem
    result["setting_and_characters"] = setting[:MAX_SETTING_CHARS]
    result["color_palette"] = palette[:MAX_PALETTE_CHARS]

    shot_list = result.get("shot_list")
    if not isinstance(shot_list, list) or not shot_list:
        return False, "missing or empty shot_list"

    total_seconds = estimate_seconds(narration_text)
    lo, hi = shot_bounds(total_seconds)
    min_ok = max(MIN_SHOTS, int(lo * 0.85))
    max_ok = min(MAX_SHOTS, int(math.ceil(hi * 1.15)))
    if len(shot_list) < min_ok or len(shot_list) > max_ok:
        return False, (f"shot count {len(shot_list)} outside {min_ok}-{max_ok} for about "
                       f"{total_seconds:.0f} s of narration")

    shots = [normalize_shot(s, i) for i, s in enumerate(shot_list)]
    for i, s in enumerate(shots):
        s["shot_number"] = i + 1

    problem = content_problems(shots)
    if problem:
        return False, problem

    fixed = auto_repair_zoom_discipline(shots)
    if fixed:
        print(f"[shots] Auto-repaired {len(fixed)} shot(s) for zoom discipline.")
    fixed = auto_repair_missing_onscreen_text(shots)
    if fixed:
        print(f"[shots] Auto-repaired {len(fixed)} shot(s) with unreadable-text wording.")
    fixed = auto_repair_face_closeups(shots)
    if fixed:
        print(f"[shots] Auto-repaired {len(fixed)} face close-up(s) to medium shots.")
    auto_repair_excessive_consecutive_subject(shots)
    auto_repair_dominant_subject(shots)
    auto_repair_location_change_without_establishing(shots)

    fixed = auto_repair_ambience(shots)
    if fixed:
        print(f"[shots] Auto-repaired the ambience cue on {len(fixed)} shot(s).")
    fixed = auto_repair_vfx(shots)
    if fixed:
        print(f"[shots] Added a lens effect to {len(fixed)} shot(s) to reach {MIN_VFX_RATIO:.0%} VFX coverage.")

    name = protagonist_name(setting)
    scrubbed = enforce_protagonist_cap(shots, name)
    if scrubbed:
        print(f"[shots] Last-resort: removed the protagonist from {scrubbed} shot(s) to hold the "
              f"{PROTAGONIST_MAX_RATIO:.0%} cap.")
    if name:
        n_prot = len(protagonist_shot_indices(shots, name))
        print(f"[shots] {name} is named in {n_prot}/{len(shots)} shots ({n_prot / len(shots):.0%}).")

    result["shot_list"] = shots
    result["music_mood"] = (result.get("music_mood") or "").strip() or (
        "Tense cinematic thriller score, sparse low piano and rising strings "
        "at the start, driving percussion and brass stabs building through "
        "the middle, explosive full-orchestra climax at the reveal, "
        "tapering to a quiet resolution."
    )
    result["hook_text"] = normalize_hook_text(result)
    result["narration_text"] = narration_text
    return True, result


# --- prompts -----------------------------------------------------------------

def build_shot_rules_block(target, lo, hi, cap, name):
    who = name if name else "the protagonist"
    return f"""CINEMATIC DIRECTOR - shot list requirements:

SHOT LENGTH AND COUNT (HARD RULE): every shot lasts about 4-6 seconds of
narration (roughly 10-15 spoken words). Write about {target} shots for this
segment, never fewer than {lo} and never more than {hi}. Every
"narration_excerpt" must be an exact, verbatim substring of the NARRATION
SEGMENT, in order, and together the excerpts must cover the WHOLE segment
with no sentence skipped. No excerpt may be longer than 30 words. Never
repeat an earlier shot.

ONE ACTION PER SHOT, WRITTEN AS A COMMAND (HARD RULE): "visual_description"
is one subject + ONE single, clearly visible action + one location, written
as a direct present-tense instruction to a video model, for example:
"A clerk in a grey wool coat stamps a thick file at a wooden desk, a green
desk lamp beside him, medium shot." Name every object that is in the frame.
Nothing may appear from nowhere, no sequences, no "then", no "continues",
no two actions in one shot, and nothing that depends on the shot before or
after it. Every shot must match what the narration line is about at that
exact moment.

PROTAGONIST LIMIT (HARD RULE): {who} may appear in at most {cap} shots of
this segment (counted by name in visual_description or primary_subject).
Refer to the protagonist by first name only. Every other shot is B-roll that
shows what the narration describes: places, buildings, objects, documents,
hands doing a task, other unnamed people doing tasks, landscapes, weather,
the wider event, aftermath. Set primary_subject to the protagonist's first
name when featured, otherwise "". Never name the protagonist in a B-roll shot.

FACES (HARD RULE): the video model draws faces badly. Prefer wide and medium
shots. Show people from behind, from a distance, from the side, in
silhouette, or only through their hands and the objects they work with.
Avoid close_up and extreme_close_up of a face. Never describe eyes, gaze,
staring or detailed facial expressions.

PERIOD ACCURACY (HARD RULE): this is a real historical episode. Never name
a modern object (laptops, computers, smartphones, tablets, drones, screens
or monitors, modern vehicles, other technology that did not exist in the
story's era). Use era-correct equivalents (paper letter, ledger, compass,
wall map, rotary telephone, printed newspaper).

CONSISTENCY: every shot must stay consistent with the "setting_and_characters"
anchor - same location/era/ethnicity, and every recurring person must match
their fixed description. Every shot's mood and lighting must belong to the
same graded film as the "color_palette" anchor.

ONE INSTANCE PER CHARACTER PER SHOT (HARD RULE): a named character appears
exactly once in a shot - never a reflection, double, twin or duplicate. If a
shot needs two people they are two genuinely different people.

PURPOSEFUL PEOPLE (HARD RULE): every person in frame is doing one specific
concrete task. Never "standing around", "standing there", "waiting there",
"looking around". Crowds must be doing something (working, moving with
purpose, reacting physically) - never a motionless row of onlookers. When
in doubt leave the crowd out.

LOCATION CHANGES MUST RE-ESTABLISH: fill "location_tag" with a short
consistent place name. The FIRST shot in a new location must use shot_type
"wide" or "establishing". Use "" when no clear location.

LEGIBLE ON-SCREEN TEXT (HARD RULE): if a visual_description mentions any of
newspaper, letter, document, sign, headline, inscription, poster, map, book,
plaque, telegram, postcard, banner, ledger, diary, certificate, gravestone,
tombstone, either fill "required_onscreen_text" with the exact correctly
spelled wording, or write the shot so that object is present but not
readable (a closed book on a shelf, a letter held face-down).

VARY REACTIONS: do not default to "gasps"; vary physical reactions (a held
breath, a stiffened body, a dropped object, trembling hands).

For each shot provide:
- "shot_type": one of "wide", "medium", "close_up", "extreme_close_up",
  "establishing", "detail_insert" (mostly wide, medium, establishing and
  detail_insert of objects)
- "camera_movement": one of "static", "pan_left", "pan_right", "tilt_up",
  "tilt_down", "zoom_in", "zoom_out", "push_in", "pull_out", "dolly_in",
  "dolly_out", "tracking", "crash_zoom", "whip_pan", "handheld_shake",
  "orbit", "drone_rise", "drone_descend", "parallax", "focus_pull",
  "dutch_angle", "snap_zoom", "speed_ramp" - keep it gentle; the generator
  makes 4-6 s clips
- "camera_reason": one short sentence
- "lens_effect": one of "shallow_depth_of_field", "lens_flare", "film_grain",
  "none". At least 1 in 3 shots must use a real effect: "film_grain" for the
  period-film look on wide and establishing shots, "shallow_depth_of_field"
  on detail_insert and medium shots, "lens_flare" only on sunlit exterior
  shots in dawn, golden_hour or dusk light (at most 1 shot in 10)
- "ambience_cue": REQUIRED on every shot. The continuous sound of the place
  the shot is in, 4-12 words, keyword style, for example "cold wind, distant
  gulls, creaking wooden pier" or "quiet office room tone, faint typewriter
  clatter". Shots in the same location use the SAME ambience_cue word for
  word so the sound bed runs unbroken; change it only when the location
  changes. Sounds of the place only: no music and no spoken words
- "sfx_cue": ONE specific sound that matches the visible action in the shot
  (a stamp thudding on paper, a door latch clicking, boots on gravel), short
  and keyword style, different from the ambience. "" only where silence is
  deliberate
- "primary_subject", "required_onscreen_text", "location_tag" as above
- "lighting": one of "dawn", "morning", "midday", "golden_hour", "dusk",
  "night", "overcast", "firelight", "interior_lamp", "moonlight" - consistent
  with the story's timeline
- "beat_intensity": one of "low", "mid", "high" - building toward the climax
- "framing_angle": one of "eye_level", "low_angle", "high_angle", "overhead"
- "depth_of_field": one of "shallow", "deep", "standard" (never shallow on
  wide/establishing)

PACING: vary shot_type and camera_movement; never the same camera_movement
more than twice in a row. At most 1 in 4 shots may use a zoom-in-family
movement (push_in, crash_zoom, zoom_in, snap_zoom, dolly_in) and never two
in a row. At least 1 in 4 shots must be "wide" or "establishing"."""


def build_shot_breakdown_chunk_prompt(
    title, angle, chunk_text, chunk_index, num_chunks,
    setting_and_characters=None, color_palette=None, name=None,
    prior_last_subject=None, prior_last_movement=None, feedback=None,
):
    segment_label = f"segment {chunk_index + 1} of {num_chunks}"
    chunk_seconds = estimate_seconds(chunk_text)
    lo, hi = shot_bounds(chunk_seconds)
    target = max(1, int(round(chunk_seconds / TARGET_SHOT_SECONDS)))
    cap = protagonist_cap(target)

    if chunk_index == 0:
        anchor_block = f"""SETTING AND CHARACTERS - write a fixed visual anchor for the WHOLE episode, as one
standalone paragraph of 2-5 sentences:
- State the real-world location, country/region, era, and the actual
  ethnicity/culture of the people in this story, explicit and concrete.
- Introduce the main character with EXACTLY this wording so software can find
  the name: "The recurring protagonist is <FirstName> <Surname>, a <age>-year-old
  ..." followed by one fixed physical description (build, hair, clothing).
  Later, refer to them by first name only. If the story has no single
  recurring person, write exactly: "There is no single recurring protagonist."
- Give any other recurring person one fixed physical description too.

COLOR PALETTE - include "color_palette": a fixed episode-wide color and mood
grade, 1-3 sentences.

THUMBNAIL HOOK TEXT - include "hook_text": a short punchy thumbnail line built
around the most shocking number, name or fact in THIS story: {MAX_HOOK_TEXT_WORDS}
words maximum, under {MAX_HOOK_TEXT_CHARS} characters, short fragments
separated by periods. Style example only, never copy it: "{EXAMPLE_HOOK_TEXT}"

MUSIC MOOD - include "music_mood": one prompt for an AI music generator
describing a thriller-style score for the whole episode, building tension,
peaking at the biggest reveal, then resolving.

"""
        json_extra_fields = (
            '  "setting_and_characters": "2-5 sentence fixed anchor for the WHOLE episode.",\n'
            '  "color_palette": "1-3 sentence fixed color/mood grade for the WHOLE episode.",\n'
            f'  "hook_text": "Short punchy thumbnail cover line, max {MAX_HOOK_TEXT_WORDS} words.",\n'
            '  "music_mood": "Background score prompt for the whole episode.",\n'
        )
        continuity_note = ""
        rules_name = None
    else:
        anchor_block = f"""SETTING AND CHARACTERS - ALREADY FIXED for the whole episode. Stay strictly
consistent with it:

---
{setting_and_characters}
---

COLOR PALETTE - ALREADY FIXED for the whole episode:

---
{color_palette}
---

Do NOT invent a new setting_and_characters, color_palette, hook_text or
music_mood - this segment only returns a shot_list.

"""
        json_extra_fields = ""
        bits = []
        if prior_last_subject:
            bits.append(f'the previous segment ended on a shot with primary_subject "{prior_last_subject}" - '
                        f"do not open this segment with more shots of that subject if you can avoid it")
        if prior_last_movement:
            bits.append(f'the previous segment\'s last shot used camera_movement "{prior_last_movement}" - '
                        f"do not repeat it as this segment's first shot")
        continuity_note = ("CONTINUITY: " + "; also ".join(bits) + ".\n\n") if bits else ""
        rules_name = name

    feedback_block = ""
    if feedback:
        feedback_block = (f"PREVIOUS ATTEMPT WAS REJECTED BECAUSE: {feedback}\n"
                          f"Fix exactly that problem and keep every other rule.\n\n")

    rules = build_shot_rules_block(target, lo, hi, cap, rules_name)

    return f"""You are the visual director and sound designer for "Erased," a YouTube
documentary channel. The narration for this episode is FINAL - do not rewrite,
shorten or alter it. Your job is ONLY the shot-by-shot breakdown for
{segment_label} of the narration (given below as NARRATION SEGMENT), which will
be stitched together with the other segments into one continuous shot list.

Episode topic: {title}
Angle: {angle}

{anchor_block}NARRATION SEGMENT ({segment_label}, about {chunk_seconds:.0f} seconds when spoken, do not change this text):
---
{chunk_text}
---

{continuity_note}{feedback_block}Break the NARRATION SEGMENT into between {lo} and {hi} shots, aiming for about
{target} (one shot per 4-6 seconds of narration), covering this segment start
to finish. This is a hard requirement.

{rules}

Return ONLY valid JSON, no other text, no markdown fences, in this exact format:

{{
{json_extra_fields}  "shot_list": [
    {{
      "shot_number": 1,
      "visual_description": "ONE subject doing ONE visible action in one place, as a direct command, every object named",
      "narration_excerpt": "The exact, verbatim portion of THIS SEGMENT's narration this shot covers",
      "shot_type": "wide",
      "camera_movement": "pan_left",
      "camera_reason": "Why this movement fits this beat",
      "lens_effect": "none",
      "sfx_cue": "a stamp thudding on paper",
      "ambience_cue": "quiet office room tone, faint typewriter clatter",
      "primary_subject": "",
      "required_onscreen_text": "",
      "lighting": "midday",
      "beat_intensity": "mid",
      "location_tag": "short consistent location name, or empty string",
      "framing_angle": "eye_level",
      "depth_of_field": "standard"
    }}
  ]
}}

Include between {lo} and {hi} shots for this segment - every shot distinct."""


# --- generation --------------------------------------------------------------

def _call_with_infra_retry(prompt, state):
    """One LLM call; infra failures (timeouts, 5xx) are retried with backoff
    and never count against content attempts."""
    while True:
        try:
            return call_llm(prompt)
        except DailyQuotaExhausted:
            raise
        except RuntimeError as e:
            state["infra"] += 1
            state["last_reason"] = f"LLM call failed: {e}"
            print(f"[shots] Infra retry {state['infra']}/{MAX_INFRA_ATTEMPTS} failed - {e}")
            if state["infra"] >= MAX_INFRA_ATTEMPTS:
                if state["reached"]:
                    raise RuntimeError(f"Shot breakdown failed after repeated LLM errors. Last: {e}")
                raise InfraFailure(
                    f"LLM never returned a usable response after {state['infra']} infra retries "
                    f"during shot-breakdown stage (narration was already confirmed good). Last: {e}")
            wait = state["infra"] * 20
            print(f"[shots] Backing off {wait}s before the next infra retry...")
            time.sleep(wait)


def _build_full_plan(title, angle, narration_text, chunks, state):
    num_chunks = len(chunks)
    setting = color_palette = hook_text = music_mood = None
    name = None
    stitched = []

    for idx, chunk_text in enumerate(chunks):
        if idx > 0:
            time.sleep(SHOT_CHUNK_CALL_DELAY_SECONDS)
        feedback = None
        chunk_shots = None
        last_why = None
        for attempt in range(1, CHUNK_MAX_ATTEMPTS + 1):
            prompt = build_shot_breakdown_chunk_prompt(
                title, angle, chunk_text, idx, num_chunks,
                setting_and_characters=setting, color_palette=color_palette, name=name,
                prior_last_subject=stitched[-1]["primary_subject"] if stitched else None,
                prior_last_movement=stitched[-1]["camera_movement"] if stitched else None,
                feedback=feedback,
            )
            raw = _call_with_infra_retry(prompt, state)
            state["reached"] = True
            try:
                parsed = extract_json(raw)
            except ValueError as e:
                last_why = f"your JSON could not be parsed ({e}) - return ONLY valid JSON"
                feedback = last_why
                print(f"[shots] Segment {idx + 1}/{num_chunks} attempt {attempt}: {last_why}")
                time.sleep(CHUNK_RETRY_WAIT_SECONDS)
                continue

            raw_shots = parsed.get("shot_list")
            if not isinstance(raw_shots, list) or not raw_shots:
                last_why = "shot_list was missing or empty"
                feedback = last_why
                print(f"[shots] Segment {idx + 1}/{num_chunks} attempt {attempt}: {last_why}")
                time.sleep(CHUNK_RETRY_WAIT_SECONDS)
                continue

            if idx == 0:
                cand_setting = (parsed.get("setting_and_characters") or "").strip()
                cand_palette = (parsed.get("color_palette") or "").strip()
                why = anchor_problem(cand_setting, cand_palette)
                cand_name = protagonist_name(cand_setting)
                if not why and not cand_name and not anchor_declares_no_protagonist(cand_setting):
                    why = ('setting_and_characters must contain the exact sentence '
                           '"The recurring protagonist is <FirstName> <Surname>, a <age>-year-old ..." '
                           'or "There is no single recurring protagonist."')
                if not why:
                    why = hook_problem(parsed, raw_shots, narration_text)
                if why:
                    last_why = why
                    feedback = why
                    print(f"[shots] Segment 1/{num_chunks} attempt {attempt}: {why}")
                    time.sleep(CHUNK_RETRY_WAIT_SECONDS)
                    continue
                cand_name_for_check = cand_name
            else:
                cand_name_for_check = name

            ok, why, shots = validate_chunk(
                raw_shots, chunk_text, cand_name_for_check,
                prev_location=next((s["location_tag"] for s in reversed(stitched) if s["location_tag"]), None),
            )
            if not ok:
                last_why = why
                feedback = why
                print(f"[shots] Segment {idx + 1}/{num_chunks} attempt {attempt}/{CHUNK_MAX_ATTEMPTS}: {why}")
                if attempt < CHUNK_MAX_ATTEMPTS:
                    time.sleep(CHUNK_RETRY_WAIT_SECONDS)
                continue

            if idx == 0:
                setting, color_palette = cand_setting, cand_palette
                hook_text = (parsed.get("hook_text") or "").strip()
                music_mood = (parsed.get("music_mood") or "").strip()
                name = cand_name
                print(f"[shots] Protagonist: {name or 'none'}.")
            chunk_shots = shots
            break

        if chunk_shots is None:
            raise ChunkFailure(f"segment {idx + 1}/{num_chunks} failed {CHUNK_MAX_ATTEMPTS} attempts - {last_why}")
        stitched.extend(chunk_shots)
        print(f"[shots] Segment {idx + 1}/{num_chunks} done: {len(chunk_shots)} shots "
              f"({len(stitched)} so far).")

    return {
        "setting_and_characters": setting,
        "color_palette": color_palette,
        "hook_text": hook_text,
        "music_mood": music_mood,
        "shot_list": stitched,
    }


def _checker_sample(shots):
    """The checker reads three windows (start, middle, end) so its prompt
    stays small even for 200+ shots."""
    if len(shots) <= CHECKER_WINDOW * CHECKER_WINDOWS:
        return shots
    mid = len(shots) // 2 - CHECKER_WINDOW // 2
    return shots[:CHECKER_WINDOW] + shots[mid:mid + CHECKER_WINDOW] + shots[-CHECKER_WINDOW:]


def generate_shot_breakdown(title, angle, narration_text):
    total_seconds, num_chunks = plan_chunking(narration_text)
    chunks = split_narration_into_chunks(narration_text, num_chunks)
    print(f"[shots] Narration is about {total_seconds:.0f} s; planning in {len(chunks)} segment(s), "
          f"about one shot every {TARGET_SHOT_SECONDS:.0f} s.")

    state = {"infra": 0, "reached": False, "last_reason": None}
    last_reason = None

    for attempt in range(1, MAX_GENERATION_ATTEMPTS + 1):
        try:
            result = _build_full_plan(title, angle, narration_text, chunks, state)
        except ChunkFailure as e:
            last_reason = str(e)
            print(f"[shots] Attempt {attempt}/{MAX_GENERATION_ATTEMPTS} failed - {last_reason}")
            continue

        ok, validated = validate_and_normalize_shot_response(result, narration_text)
        if not ok:
            last_reason = validated
            print(f"[shots] Attempt {attempt}/{MAX_GENERATION_ATTEMPTS} failed - {last_reason}")
            continue

        sample = _checker_sample(validated["shot_list"])
        passed, grade_reason = grade_shot_breakdown(
            title, angle, validated["setting_and_characters"], validated["color_palette"], sample)
        if not passed:
            last_reason = f"checker rejected shot list - {grade_reason}"
            print(f"[shots] Attempt {attempt}/{MAX_GENERATION_ATTEMPTS} failed - {last_reason}")
            continue
        print(f"[shots] Checker passed on {len(sample)} sampled shots ({grade_reason}).")
        print(f"[shots] Done: {len(validated['shot_list'])} shots.")
        return validated

    raise RuntimeError(f"Shot breakdown failed after {MAX_GENERATION_ATTEMPTS} attempts. Last reason: {last_reason}")
