"""
Marius Command Center - prompt building (split from video_generation.py,
2026-09-06, same pattern as the 2026-08-18 script_writing.py split).

Everything that turns a shot dict + episode anchor text into the final
Agnes prompt string: all guard constants (quality/skin-realism,
anachronism, distinct-individuals, crowd-anatomy-safety, orientation,
purposeful-action, object-permanence, motion-continuity), the lighting
cue map, the content-policy fallback sanitizers, and the two prompt
builders (per-shot, and the character-reference portrait). No Agnes HTTP
logic and no moviepy/ffmpeg logic live here - just prompt text assembly.

RECOVERY NOTE (2026-09-06): this file was believed committed in an
earlier session handoff but never actually existed in the repo -
clip_generation.py's `from prompt_builder import ...` was broken on
every run until this file was created. CROWD_ANATOMY_SAFETY_GUARD below
is a fresh rewrite matching the originally-described intent (cap sharp
foreground figures, push crowds to out-of-focus background) - the exact
wording of whatever was drafted in the earlier session was never
actually captured, so this is not guaranteed byte-identical to that.
"""

import re

# LIGHTING FIELD FIX (2026-08-22): the shot's own "lighting" field
# (dawn/morning/midday/golden_hour/dusk/night/overcast/firelight/
# interior_lamp/moonlight - added 2026-08-20 in shot_breakdown_stage.py,
# validated by the checker) is read here instead of guessing lighting
# from free text in visual_description - two conflicting lighting
# instructions in one prompt was the confirmed cause of daytime shots
# rendering dark/underlit.
LIGHTING_PROMPT_MAP = {
    "dawn": "soft dawn light, pale golden horizon glow, gentle long shadows, clearly visible detail",
    "morning": "clear bright morning daylight, soft directional sunlight, well-exposed, vivid colors",
    "midday": "bright natural daylight, high-key lighting, well-exposed, vivid colors",
    "golden_hour": "warm golden hour sunlight, long soft shadows, rich amber tones, well-exposed",
    "dusk": "fading dusk light, deep blue-orange twilight sky, moody but clearly visible detail",
    "night": "deliberate nighttime lighting, moonlit or artificial light sources, intentionally low-key",
    "overcast": "soft diffused overcast daylight, even flat lighting, muted but clearly visible, no harsh shadows, not dark",
    "firelight": "warm flickering firelight or lantern light, intentionally low-key, orange glow, clearly visible subject",
    "interior_lamp": "warm interior lamp or candle lighting, intentionally low-key, intimate glow, clearly visible subject",
    "moonlight": "cool pale moonlight, intentionally low-key night lighting, clearly visible subject",
}

DEFAULT_LIGHTING_KEY = "midday"

ANACHRONISM_GUARD = (
    "historically accurate to this exact time period and setting, no modern technology, "
    "no cars, no drones, no modern clothing, no digital devices, no anachronistic objects of any kind, "
    "no laptops, no computers, no smartphones, no tablets, no screens or monitors of any kind, "
    "no modern furniture, no electrical wiring or outlets, no plastic objects"
)

# ANACHRONISM GUARD REPOSITIONING (2026-08-24): repeated in short form
# immediately after visual_description (recency-authority positioning),
# since a single negative-instruction block stated once early in a long
# combined prompt is known to lose weight the further it sits from the
# end of the prompt.
ANACHRONISM_GUARD_SHORT = (
    "strictly no laptops, no computers, no smartphones, no tablets, no drones, "
    "no screens or monitors of any kind, no modern technology of any kind"
)

# SKIN-REALISM STRENGTHENING (2026-08-22): concrete texture language
# (pore detail, imperfections, matte finish) rather than only negative
# instructions - generation models respond more reliably to being told
# what TO render than only what to avoid.
QUALITY_GUARD = (
    "modern high-end digital cinema, crisp sharp clarity, professional color grading, "
    "shallow depth of field, cinematic lighting, vivid saturated color, no sepia tone, "
    "no heavy desaturation, no muted documentary color grading, no grainy vintage film look, "
    "natural realistic human skin with visible pore texture and natural skin imperfections, "
    "matte skin finish, not glossy, not waxy, not airbrushed, not overly smooth, no beauty-filter look, "
    "no artificial CGI look, no flat synthetic AI look, no plastic skin, no doll-like skin, "
    "no candy-coated or glazed look, photographically real, not illustrated, not animated, not stylized"
)

DISTINCT_INDIVIDUALS_GUARD = (
    "every person visible in this shot is a distinct, unique individual with "
    "a different face, body, and clothing from every other person in the "
    "frame - never repeat or clone one character's likeness onto more than "
    "one person, even in a crowd, group, or background. If this shot has a "
    "named recurring character as its primary subject, that person appears "
    "EXACTLY ONCE in the frame - never render two, a duplicate, a mirrored "
    "copy, or a second instance of the same named character anywhere in the "
    "same shot, including reflections or background figures"
)

# FIX 2 - CLONED/IDENTICAL CROWD FACES (2026-09-06): models default to
# duplicated "copy-paste" faces in crowds unless structurally prevented -
# a negative instruction alone (DISTINCT_INDIVIDUALS_GUARD above) is
# known-unreliable by itself, so this caps how many sharp, individuated
# faces appear in the foreground and pushes any remaining crowd into an
# out-of-focus background instead, same structural fix already confirmed
# live and working on Nova's video_planning_agent.py
# (CROWD_ANATOMY_SAFETY_RULE).
CROWD_ANATOMY_SAFETY_GUARD = (
    "if this shot contains a crowd or group larger than 4-5 people, only 4-5 "
    "of them are sharp, individuated, foreground figures with distinct faces "
    "and clothing - everyone beyond that is rendered soft-focus, out-of-focus, "
    "or partially obscured in the background, never as additional sharp "
    "duplicate faces. Do not render a large crowd as a uniform wall of "
    "identical, equally-sharp people"
)

MOTION_CONTINUITY_GUARD = (
    "motion continues smoothly and continuously in the same direction and "
    "speed as the moment just before this - no reversing, no snapping "
    "backward, no sudden stop-and-restart, no pausing mid-motion"
)

ORIENTATION_CONSISTENCY_GUARD = (
    "each person's body orientation, facing direction, and pose stay logically "
    "consistent for the full duration of this shot - a person's back, front, "
    "or profile does not suddenly swap or flip to a different orientation "
    "mid-shot"
)

PURPOSEFUL_ACTION_GUARD = (
    "every person visible in this shot is doing a specific, purposeful action "
    "tied to the scene - no one stands frozen, idle, or posed like a statue "
    "with nothing to do; if a person has no active role in this moment, they "
    "are not included in the frame"
)

OBJECT_PERMANENCE_GUARD = (
    "objects only move when a visible person is actively holding, touching, "
    "or manipulating them - no object moves, stirs, or animates on its own "
    "with no hand present"
)

# FALLBACK TIER 1 (2026-08-07): content_flagged scripts were flagged on
# individually mundane shots, with the original hypothesis being that
# setting_and_characters itself (routinely containing ethnic-group names
# and genocide/war-crime context) is the trigger.
FALLBACK_STRIP_KEYWORDS = [
    "hutu", "tutsi", "bosniak", "serb", "serbian", "croat", "nazi", "ss ",
    "gestapo", "genocide", "ethnic", "siege", "concentration camp",
    "holocaust", "massacre", "militia", "death camp", "war crime",
]


def _sanitize_anchor_for_fallback(anchor):
    """Drops clauses/sentences containing ethnicity- or atrocity-related
    keywords from an anchor string, for use only on content-policy fallback
    tier 1. Keeps whatever's left (era, location, physical character
    description) so continuity/likeness isn't lost entirely."""
    if not anchor:
        return anchor
    pieces = re.split(r'(?<=[.;])\s+', anchor)
    kept = [
        p for p in pieces
        if not any(kw in p.lower() for kw in FALLBACK_STRIP_KEYWORDS)
    ]
    return " ".join(kept).strip()


CROWD_OR_GROUP_KEYWORDS = (
    "two ", "three ", "four ", "five ", "several", "group of", "crowd",
    "family", "villagers", "workers", "neighbors", "neighbours", "soldiers",
    "colleagues", "team", "both", "twins", "pair of", "everyone", "people",
    "others", "onlookers", "bystanders", "crew", "townspeople", "children",
)


def _strip_named_characters_for_group_shot(anchor):
    if not anchor:
        return anchor
    pieces = re.split(r'(?<=[.;])\s+', anchor)
    kept = [
        p for p in pieces
        if "recurring character" not in p.lower() and "main character" not in p.lower()
    ]
    return " ".join(kept).strip()


def build_agnes_prompt(shot, setting_and_characters="", fallback_level=0):
    """
    fallback_level 0 (primary): full anchor + full visual_description.
    fallback_level 1: sanitized anchor (ethnicity/atrocity clauses stripped)
        + generic shot-type description, no visual_description text at all.
    fallback_level 2 (TIER 2, ultra-safe): drops the anchor entirely -
        carries zero episode-specific content so a single stubborn shot
        can no longer take down the whole episode.

    MOTION/ORIENTATION/ACTION/OBJECT/CROWD-SAFETY guards are added to
    every fallback tier, since they're generic technical instructions
    with zero episode-specific content - they cannot be what triggers a
    content-policy rejection, so there's no reason to withhold them even
    on the ultra-safe tier 2 path.

    ANACHRONISM GUARD REPOSITIONING: ANACHRONISM_GUARD (long form) runs
    early alongside the other guards; ANACHRONISM_GUARD_SHORT is also
    appended immediately after visual_description on every fallback
    tier, for the same recency-authority reason lighting_cue is placed
    last.
    """
    shot_type = (shot.get("shot_type") or "medium").replace("_", " ")
    camera_movement = (shot.get("camera_movement") or "static").replace("_", " ")
    lens_effect = shot.get("lens_effect") or "none"
    anchor = (setting_and_characters or "").strip()

    lighting_key = shot.get("lighting") or DEFAULT_LIGHTING_KEY
    lighting_cue = LIGHTING_PROMPT_MAP.get(lighting_key, LIGHTING_PROMPT_MAP[DEFAULT_LIGHTING_KEY])

    if fallback_level == 0:
        visual = shot.get("visual_description", "").strip()
        if any(kw in visual.lower() for kw in CROWD_OR_GROUP_KEYWORDS):
            anchor = _strip_named_characters_for_group_shot(anchor)
        parts = []
        if anchor:
            parts.append(anchor)
        parts.append(QUALITY_GUARD)
        parts.append(ANACHRONISM_GUARD)
        parts.append(DISTINCT_INDIVIDUALS_GUARD)
        parts.append(CROWD_ANATOMY_SAFETY_GUARD)
        parts.append(ORIENTATION_CONSISTENCY_GUARD)
        parts.append(PURPOSEFUL_ACTION_GUARD)
        parts.append(OBJECT_PERMANENCE_GUARD)
        parts.append(visual)
        parts.append(ANACHRONISM_GUARD_SHORT)
        # Lighting cue placed LAST, so it is the most recent/authoritative
        # instruction and matches the shot's own validated lighting field.
        parts.append(lighting_cue)
        parts.append(f"{shot_type} shot")
    elif fallback_level == 1:
        anchor = _sanitize_anchor_for_fallback(anchor)
        parts = []
        if anchor:
            parts.append(anchor)
        parts.append(QUALITY_GUARD)
        parts.append(ANACHRONISM_GUARD)
        parts.append(CROWD_ANATOMY_SAFETY_GUARD)
        parts.append(ORIENTATION_CONSISTENCY_GUARD)
        parts.append(PURPOSEFUL_ACTION_GUARD)
        parts.append(OBJECT_PERMANENCE_GUARD)
        parts.append(ANACHRONISM_GUARD_SHORT)
        parts.append(lighting_cue)
        parts.append(f"{shot_type} modern high-production cinematic shot")
    else:
        parts = [
            "generic historical documentary reenactment scene, unspecified period figures",
            QUALITY_GUARD,
            ANACHRONISM_GUARD,
            CROWD_ANATOMY_SAFETY_GUARD,
            ORIENTATION_CONSISTENCY_GUARD,
            PURPOSEFUL_ACTION_GUARD,
            OBJECT_PERMANENCE_GUARD,
            ANACHRONISM_GUARD_SHORT,
            lighting_cue,
            f"{shot_type} modern high-production cinematic shot",
        ]

    if camera_movement != "static":
        parts.append(f"camera {camera_movement}")
    if lens_effect != "none":
        parts.append(lens_effect.replace("_", " "))
    parts.append(MOTION_CONTINUITY_GUARD)

    return ", ".join(p for p in parts if p)


def build_character_reference_prompt(setting_and_characters):
    parts = [
        setting_and_characters.strip(),
        "character reference portrait, full figure visible, neutral pose, clear face and clothing detail",
        "bright natural daylight, high-key lighting, well-exposed, vivid colors",
        QUALITY_GUARD,
        ANACHRONISM_GUARD,
        ANACHRONISM_GUARD_SHORT,
    ]
    return ", ".join(p for p in parts if p)
