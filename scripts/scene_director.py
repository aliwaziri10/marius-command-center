"""
Marius Command Center - scene director (NEW, 2026-09-19)

Builds ONE instruction per ~7s Agnes clip ("beat") instead of reusing one
prompt for every chained clip of a long shot.

Rules enforced here:
- The protagonist's description is only sent on shots where the plan says
  the protagonist is present (shot["primary_subject"] non-empty).
- Inside a long shot the protagonist appears only on every
  SUBJECT_BEAT_EVERY-th beat; the other beats are cutaways (details,
  environment, other people) so the camera never follows her everywhere.
- Every beat is a fresh text-to-video cut (no last-frame chaining), so
  scenes stop repeating and people stop appearing/vanishing.
- Short prompt, film-look realism instead of a wall of guard text.
"""

import re

from prompt_builder import (
    ANACHRONISM_GUARD_SHORT,
    CROWD_OR_GROUP_KEYWORDS,
    _sanitize_anchor_for_fallback,
)

# 2 = protagonist on beats 0, 2, 4, 6 of a shot that features her.
# 3 = beats 0, 3, 6 (less of her). 1 = every beat (old behaviour, not advised).
SUBJECT_BEAT_EVERY = 2

STYLE_LOOK = (
    "shot on 35mm film with vintage lenses, natural documentary realism, "
    "visible film grain, subtle lens imperfections, muted natural period color, "
    "real human skin with visible pores, fine facial hair, uneven skin tone, "
    "sweat and dirt, matte skin, unretouched"
)

RULES_LINE = (
    "every person has a different face, age, height and build, "
    "nobody appears from nowhere or vanishes, nobody is duplicated, "
    "exactly one of each object, held objects stay in hands or rest on a surface"
)

NEGATIVE_PROMPT_V2 = (
    "waxy skin, plastic skin, glossy skin, airbrushed skin, doll-like skin, "
    "beauty filter, CGI look, 3D render look, synthetic AI look, HDR look, "
    "oversaturated colors, oversharpened, blurry face, deformed face, "
    "duplicate person, cloned faces, identical faces, twin, same person repeated, "
    "person appearing from nowhere, person vanishing, ghost, transparent body, "
    "floating objects, objects defying gravity, duplicate objects, "
    "extra limbs, extra fingers, morphing, warping, melting, flickering, "
    "watermark, text overlay, low quality"
)

LIGHT_MAP = {
    "dawn": "soft dawn light with pale haze",
    "morning": "clear morning daylight",
    "midday": "hard overhead daylight with small shadows",
    "golden_hour": "low warm golden-hour sun",
    "dusk": "fading dusk light",
    "night": "night, only moonlight or small artificial lights, deliberately low-key",
    "overcast": "flat overcast daylight",
    "firelight": "flickering firelight",
    "interior_lamp": "dim warm lamp light",
    "moonlight": "cool pale moonlight",
}

CUTAWAY_COVERAGE = [
    ("extreme close-up detail shot",
     "hands, tools, fabric, paper or objects belonging to this scene, no faces visible"),
    ("wide observational shot",
     "the whole location and its surroundings, any people are small, distant, seen from behind and busy with their own tasks"),
    ("medium shot",
     "a different person with a different face and clothing quietly doing their own task, not looking at the camera"),
    ("low close shot",
     "ground, walls, weather, smoke, breath in cold air or light moving across surfaces, no people"),
    ("high wide shot",
     "looking down over the location from above, tiny distant figures moving with purpose"),
    ("macro detail shot",
     "worn textures, hands at work, one small object in sharp focus, no faces visible"),
]

ALT_ANGLES = [
    "over-the-shoulder view from behind, face not visible",
    "side profile at a distance in a wider frame",
    "wide frame where the person is small against the surroundings",
    "close view of hands and the object being handled, face out of frame",
]

FOLLOWING_MOVES = {
    "tracking", "orbit", "handheld_shake", "whip_pan", "crash_zoom",
    "snap_zoom", "speed_ramp", "dolly_in", "push_in", "zoom_in",
}

PRONOUNS = {"she", "her", "hers", "herself", "he", "his", "him", "himself"}

GENERIC_SUBJECT_WORDS = {
    "young", "woman", "women", "girl", "child", "children", "soldier",
    "soldiers", "prisoner", "prisoners", "people", "group", "crowd",
    "worker", "workers", "guard", "guards",
}

CHARACTER_CUE = re.compile(
    r"\b\d{1,3}[- ]year[- ]old\b|\baged\s+\d{1,3}\b|\bgreying\b|\bgraying\b|"
    r"\bgrey-haired\b|\bgray-haired\b|\bhair\b|\bbeard\b|\bmustache\b",
    re.IGNORECASE,
)


def _subject_tokens(subject):
    return [
        w for w in re.findall(r"\w+", (subject or "").lower())
        if len(w) >= 4 and w not in GENERIC_SUBJECT_WORDS
    ]


def split_anchor(anchor, subject=""):
    """Splits the episode anchor into (setting_text, character_text).
    Sentences describing one individual (age, hair, the subject's name)
    go to character_text; everything else is setting_text."""
    sentences = [
        s.strip() for s in re.split(r"(?<=[.;])\s+", (anchor or "").strip()) if s.strip()
    ]
    tokens = _subject_tokens(subject)
    setting, character = [], []
    for s in sentences:
        low = s.lower()
        if CHARACTER_CUE.search(s) or any(t in low for t in tokens):
            character.append(s)
        else:
            setting.append(s)
    if not setting and sentences:
        setting = [sentences[0]]
    return " ".join(setting), " ".join(character)


def _strip_subject_clauses(text, subject):
    tokens = _subject_tokens(subject)
    clauses = re.split(r"(?<=[,.;])\s+", (text or "").strip())
    kept = []
    for c in clauses:
        low = c.lower()
        words = set(re.findall(r"\w+", low))
        if words & PRONOUNS:
            continue
        if tokens and any(t in low for t in tokens):
            continue
        kept.append(c)
    return " ".join(kept).strip(" ,;")


def _narration_moment(shot, beat_index):
    text = (shot.get("narration_excerpt") or "").strip()
    if not text:
        return ""
    sentences = [s for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
    if not sentences:
        return ""
    return sentences[min(beat_index, len(sentences) - 1)][:200].strip()


def beat_kind(shot, beat_index):
    has_subject = bool((shot.get("primary_subject") or "").strip())
    if beat_index == 0:
        return "primary"
    if has_subject and beat_index % SUBJECT_BEAT_EVERY == 0:
        return "subject_alt"
    return "cutaway"


def _movement_phrase(shot, has_subject_in_frame):
    movement = shot.get("camera_movement") or "static"
    if movement == "static":
        return "static camera"
    if has_subject_in_frame and movement in FOLLOWING_MOVES:
        return "locked-off camera with a very slow drift, does not follow the person"
    return f"camera {movement.replace('_', ' ')}"


def build_beat_prompt(shot, anchor, beat_index=0, shot_index=0, fallback_level=0):
    subject = (shot.get("primary_subject") or "").strip()
    kind = beat_kind(shot, beat_index)
    setting, character = split_anchor(anchor, subject)
    location = (shot.get("location_tag") or "").strip()
    light = LIGHT_MAP.get(shot.get("lighting"), LIGHT_MAP["midday"])
    shot_type = (shot.get("shot_type") or "medium").replace("_", " ")
    angle = (shot.get("framing_angle") or "eye_level").replace("_", " ")
    visual = (shot.get("visual_description") or "").strip()

    if fallback_level >= 2:
        parts = [
            "generic historical documentary scene, unspecified period figures",
            f"{shot_type} shot", light, STYLE_LOOK, RULES_LINE,
            ANACHRONISM_GUARD_SHORT,
        ]
        return ", ".join(parts)

    if fallback_level == 1:
        parts = [
            _sanitize_anchor_for_fallback(setting),
            f"{shot_type} documentary cutaway of this location",
            light, STYLE_LOOK, RULES_LINE, ANACHRONISM_GUARD_SHORT,
        ]
        return ", ".join(p for p in parts if p)

    parts = []

    if kind == "cutaway":
        cut_type, coverage = CUTAWAY_COVERAGE[(beat_index - 1 + shot_index) % len(CUTAWAY_COVERAGE)]
        context = _strip_subject_clauses(visual, subject)[:240] if subject else visual[:240]
        moment = _narration_moment(shot, beat_index)
        parts.append(f"{cut_type}, {angle} angle, slow gentle camera drift")
        if location:
            parts.append(f"Location: {location}")
        if setting:
            parts.append(f"Setting: {setting}")
        parts.append(f"Show: {coverage}")
        if context:
            parts.append(f"Same scene as: {context}")
        if moment:
            parts.append(f"Story moment being illustrated: {moment}")
        if subject:
            parts.append("the main character is not in this shot")
    else:
        in_frame = bool(subject)
        parts.append(f"{shot_type} shot, {angle} angle, {_movement_phrase(shot, in_frame)}")
        if location:
            parts.append(f"Location: {location}")
        if setting:
            parts.append(f"Setting: {setting}")
        if subject and character:
            parts.append(
                f"Main person: {character} Exactly one such person is in frame, "
                f"every other person looks clearly different from them."
            )
        if kind == "subject_alt":
            alt = ALT_ANGLES[(beat_index // SUBJECT_BEAT_EVERY - 1 + shot_index) % len(ALT_ANGLES)]
            parts.append(f"A slightly later moment of the same scene, seen as: {alt}")
        parts.append(f"Action: {visual}")
        if any(kw in visual.lower() for kw in CROWD_OR_GROUP_KEYWORDS):
            parts.append(
                "group: only 4 to 5 people are sharp in the foreground, everyone else is "
                "soft-focus in the background, each person busy with a different purposeful task"
            )

    parts.extend([light, STYLE_LOOK, RULES_LINE, ANACHRONISM_GUARD_SHORT])
    return ". ".join(p.strip().rstrip(".") for p in parts if p and p.strip())
