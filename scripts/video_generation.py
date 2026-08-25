import os
import re
import json
import math
import time
import base64
import traceback
import requests
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from moviepy import (
    VideoFileClip,
    AudioFileClip,
    ImageClip,
    CompositeAudioClip,
    CompositeVideoClip,
    concatenate_videoclips,
    concatenate_audioclips,
)
from moviepy.video.fx import FadeIn, FadeOut
from moviepy.audio.fx import AudioFadeIn, AudioFadeOut

FADE_IN_SECONDS = 0.75
FADE_OUT_SECONDS = 1.5
TRAIL_SECONDS = 3.0

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SECRET_KEY"]
AGNES_API_KEY = os.environ["AGNES_API_KEY"]
FREESOUND_API_KEY = os.environ.get("FREESOUND_API_KEY")
ACE_MUSIC_API_KEY = os.environ.get("ACE_MUSIC_API_KEY")
HF_TOKEN = os.environ.get("HF_TOKEN")

HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
}

AGNES_BASE = "https://apihub.agnes-ai.com/v1"
AGNES_POLL_URL = "https://apihub.agnes-ai.com/agnesapi"
AGNES_IMAGE_URL = f"{AGNES_BASE}/images/generations"
AGNES_HEADERS = {
    "Authorization": f"Bearer {AGNES_API_KEY}",
    "Content-Type": "application/json",
}

ACE_MUSIC_BASES = ["https://api.acemusic.ai", "https://ai.acemusic.ai"]
ACE_MUSIC_HEADERS = {
    "Authorization": f"Bearer {ACE_MUSIC_API_KEY}",
    "Content-Type": "application/json",
}

HF_MUSICGEN_URL = "https://api-inference.huggingface.co/models/facebook/musicgen-small"

VIDEO_BUCKET = "videos"
CLIP_BUCKET = "video_clips"
WIDTH, HEIGHT = 1280, 720
FRAME_RATE = 24
MIN_FRAMES = 49
MAX_FRAMES = 169
MAX_CLIP_SECONDS = MAX_FRAMES / FRAME_RATE

CLIP_BATCH_LIMIT = 8          # total shots generated per run, across ALL candidates combined
CANDIDATE_POOL_SIZE = 15      # raised from 5 (2026-07-25) so every currently-stuck script is in rotation

NARRATION_VOLUME = 1.0
MUSIC_VOLUME = 0.18
SFX_VOLUME = 0.85
ORIGINAL_CLIP_AUDIO_VOLUME = 0.30
LIMITER_CEILING = 0.98

AGNES_RETRYABLE_CODES = {429, 500, 502, 503, 504}
AGNES_MAX_RETRIES = 4

AGNES_IMAGE_MAX_RETRIES = 3

CLIP_VERIFY_RETRIES = 3
CLIP_VERIFY_RETRY_WAIT = 5

# SMOOTH-EXTENSION FIX (2026-08-01): when a shot (or the final trail) needs
# more duration than one Agnes generation can produce (MAX_CLIP_SECONDS),
# this used to freeze the last frame for the remainder - visible as a
# "stuck" still image, happening at every sentence-boundary pause across
# an episode plus every single video's outro. MAX_CHAIN_SEGMENTS caps how
# many additional REAL Agnes clips we'll chain (each anchored to the
# previous clip's own last frame, same mechanism as cross-shot continuity)
# to cover the overflow with real motion instead.
#
# CHAIN-BUDGET FIX (2026-08-23): 3 segments (~21s of overflow, ~28s total
# per shot) was sized for short pauses, but confirmed live on the Bosnia
# episode (script 40ffc83c, 33 shots / ~19min = ~35s per shot average) -
# almost every shot in a real full-length episode needs MORE than 28s
# total, so nearly every shot was hitting the chain-budget ceiling and
# silently freeze-holding the remainder, exactly matching Zia's report of
# "multiple freeze frames, narrator keeps speaking." Raised to 6 segments
# (~42s of overflow, ~49s total per shot) to comfortably cover this
# format's real average shot length with headroom, not just short pauses.
MAX_CHAIN_SEGMENTS = 6

# LIGHTING FIELD FIX (2026-08-22): the shot's own "lighting" field
# (dawn/morning/midday/golden_hour/dusk/night/overcast/firelight/
# interior_lamp/moonlight - added 2026-08-20 in shot_breakdown_stage.py,
# validated by the checker) was never actually read here. This file was
# still keyword-scanning visual_description text and unconditionally
# appending "bright natural daylight" whenever no DARK_SCENE_KEYWORDS
# matched - but words like "overcast", "hazy", "grey sky" never matched
# that list, so shots correctly written as overcast/dusk/hazy still got
# a contradicting "bright daylight" cue jammed into the same prompt as
# their own moody sky description. Two conflicting lighting instructions
# in one prompt is the confirmed cause of daytime shots rendering dark/
# underlit. Fix: derive the lighting cue from the shot's own validated
# "lighting" field instead of guessing from free text.
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

CAPTION_FONT_PATHS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]
CAPTION_FONT_SIZE = 28
CAPTION_MAX_WIDTH_RATIO = 0.70
CAPTION_BOTTOM_MARGIN = 60
CAPTION_LINE_SPACING = 10
CAPTION_TEXT_COLOR = (255, 255, 255, 255)
CAPTION_STROKE_COLOR = (0, 0, 0, 255)
CAPTION_STROKE_WIDTH = 3
CAPTION_BG_COLOR = (0, 0, 0, 140)
CAPTION_BG_PADDING = 16

# CHUNKED-UPLOAD QUALITY FIX (2026-08-20, replaces UPLOAD SIZE FIX from
# earlier the same day): the earlier same-day fix kept every video under
# Supabase's 50MB free-tier cap by CRUSHING bitrate to whatever fit in one
# file - fine for short episodes, but for this pipeline's typical 15-20+
# minute episodes it forced the video down to ~144p-equivalent quality
# (confirmed directly by Zia watching a 19-minute upload). Two of the
# earlier uploads (shorter episodes) looked fine under that scheme; the
# 19-minute one did not - proving the bitrate-crushing approach doesn't
# scale with episode length. Root fix, per Zia's explicit direction:
# NEVER shrink bitrate to hit a size cap again. Bitrate is now fixed at a
# genuinely good quality level regardless of duration
# (QUALITY_VIDEO_BITRATE_KBPS). If the resulting file would exceed the
# 50MB cap, the final video is instead split into multiple sequential
# chunks - each safely under MAX_CHUNK_MB - uploaded as separate files
# (script_id/part_001.mp4, part_002.mp4, ...), with all chunk URLs saved
# to the new video_chunk_urls column. video_url (singular) is still set
# ONLY when the episode fit in one file, for backward compatibility with
# anything downstream still reading that column.
QUALITY_VIDEO_BITRATE_KBPS = 3000   # fixed, duration-independent - healthy 720p HEVC quality
MAX_CHUNK_MB = 45                   # target used to decide how many chunks to aim for up front

# CHUNK-SIZE VERIFICATION FIX (2026-08-23): MAX_CHUNK_MB above is only an
# up-front ESTIMATE (total file size / target = number of chunks, then
# split by even time slices) - it assumes every second of the video
# encodes to roughly the same size, which isn't true. Confirmed live on
# script 40ffc83c: part_002 already encoded to 48.3MB (over the 45MB
# target but still under Supabase's real cap, so it slipped through),
# and part_005 encoded dense enough to land OVER Supabase's real object
# size limit, which rejects the PUT with a bare 400 and no useful body.
# HARD_CHUNK_LIMIT_MB is the real ceiling every chunk is now verified
# against AFTER encoding (not just estimated before) - see
# _encode_subclip_safe below, which recursively re-splits and re-encodes
# any segment that comes out over this limit until every real on-disk
# chunk file is safely under it, regardless of how densely a particular
# segment happens to compress.
HARD_CHUNK_LIMIT_MB = 48


class ContentPolicyRejection(Exception):
    pass


class AgnesOverloadedError(Exception):
    pass


def round_to_valid_frames(num_frames):
    # FREEZE-FRAME FIX (2026-08-03): was using round() to the nearest valid
    # frame count, which rounds DOWN roughly half the time - producing a
    # clip up to ~0.3s shorter than the target duration, which then had to
    # be covered by a frozen final frame. Using ceiling instead guarantees
    # the generated clip is always >= target duration, so there's nothing
    # left to freeze except sub-frame remainders (a few milliseconds).
    n = math.ceil((num_frames - 1) / 8)
    n = max(0, n)
    return 8 * n + 1


def get_ready_scripts(limit=CANDIDATE_POOL_SIZE):
    resp = requests.get(
        f"{SUPABASE_URL}/rest/v1/scripts?status=eq.images_generated&order=created_at.asc&limit={limit}",
        headers=HEADERS,
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def download_file(url, out_path):
    r = requests.get(url, timeout=120)
    r.raise_for_status()
    with open(out_path, "wb") as f:
        f.write(r.content)
    return out_path


def record_error(script_id, error_text):
    """
    VERIFIER-GATE FIX (2026-08-22): persists the real exception (full
    traceback) for a script to scripts.last_error/last_error_at, instead of
    letting it disappear into an Actions log that's hard to get to. This is
    what makes a failure diagnosable from Supabase alone. Best-effort only -
    if even this write fails, we print and move on rather than compounding
    the original failure.
    """
    try:
        resp = requests.patch(
            f"{SUPABASE_URL}/rest/v1/scripts?id=eq.{script_id}",
            headers=HEADERS,
            json={
                "last_error": error_text[-8000:],
                "last_error_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            },
            timeout=30,
        )
        resp.raise_for_status()
    except Exception as e:
        print(f"Could not record last_error for script {script_id} (secondary failure, non-fatal): {e}")


def clear_error(script_id):
    """Clears a previously recorded last_error once a script succeeds, so
    Supabase never shows a stale failure for a script that's now fine."""
    try:
        resp = requests.patch(
            f"{SUPABASE_URL}/rest/v1/scripts?id=eq.{script_id}",
            headers=HEADERS,
            json={"last_error": None},
            timeout=30,
        )
        resp.raise_for_status()
    except Exception as e:
        print(f"Could not clear last_error for script {script_id} (non-fatal): {e}")


ANACHRONISM_GUARD = (
    "historically accurate to this exact time period and setting, no modern technology, "
    "no cars, no drones, no modern clothing, no digital devices, no anachronistic objects of any kind, "
    "no laptops, no computers, no smartphones, no tablets, no screens or monitors of any kind, "
    "no modern furniture, no electrical wiring or outlets, no plastic objects"
)

# ANACHRONISM GUARD REPOSITIONING (2026-08-24): a single negative-instruction
# block stated ONCE, early in a long combined prompt (anchor + 6 other
# guard blocks + visual_description + lighting + shot type, all
# concatenated into one string) is known to lose weight with video
# generation models the further it sits from the end of the prompt -
# confirmed against Zia's report of laptops/drones still appearing in
# period episodes even though this exact guard has been present in every
# single prompt since 2026-08-02. Repeating a short-form version
# immediately after visual_description (the same recency-authority logic
# already used for LIGHTING_PROMPT_MAP cues below) gives it the same
# "most recent = most authoritative" positioning. This is a mitigation on
# the generation side; the real primary defense is now the deterministic
# keyword gate in shot_breakdown_stage.py (find_anachronistic_object_shots)
# that rejects a shot list at the SOURCE if its own visual_description
# names a modern object - the negative prompt alone was never reliable as
# the only line of defense.
ANACHRONISM_GUARD_SHORT = (
    "strictly no laptops, no computers, no smartphones, no tablets, no drones, "
    "no screens or monitors of any kind, no modern technology of any kind"
)

# VISUAL-STYLE MODERNIZATION (2026-08-15): previously "shot on film, natural
# film grain" - which fought sepia/washed-out grading but still read as
# classic analog rather than modern digital cinema. Now describes a
# modern high-end digital cinema look instead (crisp clarity, shallow
# depth of field, professional color grading, cinematic lighting), while
# still explicitly guarding against a flat/synthetic AI look so dropping
# the grain cue doesn't let AI artifacts show through more.
#
# SKIN-REALISM STRENGTHENING (2026-08-22): "no plastic skin" alone was too
# weak - Zia flagged real output as "chocolaty", "fluid", "candy", "not
# natural" skin/rendering (confirmed against 2 screenshots he provided).
# Added specific, concrete texture language (pore detail, imperfections,
# matte finish) rather than only negative instructions, since generation
# models respond more reliably to being told what TO render than only
# what to avoid.
QUALITY_GUARD = (
    "modern high-end digital cinema, crisp sharp clarity, professional color grading, "
    "shallow depth of field, cinematic lighting, vivid saturated color, no sepia tone, "
    "no heavy desaturation, no muted documentary color grading, no grainy vintage film look, "
    "natural realistic human skin with visible pore texture and natural skin imperfections, "
    "matte skin finish, not glossy, not waxy, not airbrushed, not overly smooth, no beauty-filter look, "
    "no artificial CGI look, no flat synthetic AI look, no plastic skin, no doll-like skin, "
    "no candy-coated or glazed look, photographically real, not illustrated, not animated, not stylized"
)


# FALLBACK TIER 1 (2026-08-07): content_flagged scripts (9404bc29 - Bosnian
# siege, 716623f1 - Rwandan genocide, 92dec2f9 - Nazi-era Germany) were all
# flagged on individually mundane shots (a ration stamp, a loaf of bread, a
# boot-step tilt-up). The original hypothesis was that setting_and_characters
# itself (prepended to every shot's prompt) is the trigger, since it
# routinely contains ethnic-group names and genocide/war-crime context
# (Hutu, Tutsi, Bosniak, Serb, Nazi, SS, siege, ...).
# FALLBACK_STRIP_KEYWORDS is used on tier-1 fallback attempts to drop
# ethnicity/genocide/war-crime clauses from the anchor. Confirmed (2026-08-12)
# this is NOT a complete fix on its own - see TIER 2 below.
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

MOTION_CONTINUITY_GUARD = (
    "motion continues smoothly and continuously in the same direction and "
    "speed as the moment just before this - no reversing, no snapping "
    "backward, no sudden stop-and-restart, no pausing mid-motion"
)

# NEW GUARDS (2026-08-22) - added directly from Zia's review of a live
# published video against 2 screenshots he provided:
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
    fallback_level 1: sanitized anchor (ethnicity/atrocity clauses stripped
        via _sanitize_anchor_for_fallback) + generic shot-type description,
        no visual_description text at all.
    fallback_level 2 (2026-08-12, TIER 2): ULTRA-SAFE - drops the anchor
        entirely, not just sanitizes it. Added because content_flagged
        scripts kept recurring even on stories with NO ethnicity/atrocity
        words whatsoever (e.g. "The Mechanic Who Kept Solidarity Rolling",
        a 1980s communist Poland story with no ethnic/atrocity content in
        its anchor at all) - proving the level-1 keyword list doesn't cover
        every trigger Agnes reacts to on some shots. Level 2 carries zero
        episode-specific content (no names, no location, no ethnicity) so
        a single stubborn shot can no longer take down the whole episode.

    MOTION/ORIENTATION/ACTION/OBJECT guards (2026-08-22): added to every
    fallback tier, since they're generic technical instructions with zero
    episode-specific content - they cannot be what triggers a content-policy
    rejection, so there's no reason to withhold them even on the ultra-safe
    tier 2 path.

    ANACHRONISM GUARD REPOSITIONING (2026-08-24): ANACHRONISM_GUARD (the
    long form) still runs early alongside the other guards, but
    ANACHRONISM_GUARD_SHORT is now ALSO appended immediately after
    visual_description on every fallback tier, for the same
    recency-authority reason lighting_cue is placed last. See its own
    comment above for the full rationale.
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
        parts.append(ORIENTATION_CONSISTENCY_GUARD)
        parts.append(PURPOSEFUL_ACTION_GUARD)
        parts.append(OBJECT_PERMANENCE_GUARD)
        parts.append(visual)
        # ANACHRONISM GUARD REPOSITIONING (2026-08-24): short-form repeat
        # placed right after visual_description, before lighting, so it's
        # one of the last things the model reads.
        parts.append(ANACHRONISM_GUARD_SHORT)
        # Lighting cue placed LAST, after visual_description, so it is the
        # most recent/authoritative instruction and matches the shot's own
        # validated lighting field instead of conflicting with whatever
        # mood language the script wrote into visual_description.
        parts.append(lighting_cue)
        parts.append(f"{shot_type} shot")
    elif fallback_level == 1:
        anchor = _sanitize_anchor_for_fallback(anchor)
        parts = []
        if anchor:
            parts.append(anchor)
        parts.append(QUALITY_GUARD)
        parts.append(ANACHRONISM_GUARD)
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
    # MOTION_CONTINUITY_GUARD now applied unconditionally (2026-08-22 fix).
    # Previously gated on shot.get("_has_motion_anchor"), but cross-shot
    # image anchoring is dormant (see CONTINUITY-CHAIN REMOVED, 2026-08-18) -
    # nothing sets an anchor image for primary shots anymore, so
    # _has_motion_anchor was False almost always, meaning this guard was
    # silently never applied where it mattered most. Confirmed as the
    # direct cause of the forward-then-snap-back motion Zia flagged.
    # Motion consistency within a single generated clip is wanted
    # regardless of whether cross-shot anchoring is active.
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


def generate_character_reference(script):
    """
    Generates ONE reference image per script (via agnes-image-2.1-flash),
    anchored to the episode's setting_and_characters text, so every shot's
    video call has a consistent character/setting to hold onto instead of
    starting blind. Persists the result to scripts.character_reference_url
    so this only ever runs once per script, even across resumed runs.
    Returns None (and skips silently) if there's no setting_and_characters
    text to anchor to, or if Agnes's image endpoint fails after retries -
    the pipeline still works without it, just without the consistency
    boost.

    DORMANT since 2026-08-18 (see CONTINUITY-CHAIN REMOVED in the file
    header) - no longer called from process_script's per-shot loop. Left
    defined in case cross-shot chaining is wanted back for a future
    single-protagonist format.
    """
    script_id = script["id"]
    existing = script.get("character_reference_url")
    if existing:
        return existing

    anchor = (script.get("setting_and_characters") or "").strip()
    if not anchor:
        print("No setting_and_characters text on this script - skipping character reference image.")
        return None

    prompt = build_character_reference_prompt(anchor)
    last_error_text = None

    for attempt in range(AGNES_IMAGE_MAX_RETRIES):
        try:
            resp = requests.post(
                AGNES_IMAGE_URL,
                headers=AGNES_HEADERS,
                json={
                    "model": "agnes-image-2.1-flash",
                    "prompt": prompt,
                    "size": f"{WIDTH}x{HEIGHT}",
                    "extra_body": {"response_format": "url"},
                },
                timeout=60,
            )
        except requests.RequestException as e:
            last_error_text = str(e)
            print(f"Character reference image request raised an exception (attempt {attempt + 1}/{AGNES_IMAGE_MAX_RETRIES}): {e}")
            time.sleep(10 * (attempt + 1))
            continue

        if resp.status_code in AGNES_RETRYABLE_CODES:
            last_error_text = resp.text
            print(f"Character reference image transient error {resp.status_code} (attempt {attempt + 1}/{AGNES_IMAGE_MAX_RETRIES}): {resp.text}")
            time.sleep(10 * (attempt + 1))
            continue

        if resp.status_code >= 400:
            print(f"Character reference image generation failed permanently ({resp.status_code}): {resp.text} - continuing without a reference image.")
            return None

        data = resp.json()
        image_url = None
        for entry in data.get("data", []):
            if isinstance(entry, dict) and entry.get("url"):
                image_url = entry["url"]
                break
        if not image_url:
            image_url = data.get("url")

        if not image_url:
            print(f"Character reference image response had no usable URL: {data} - continuing without a reference image.")
            return None

        resp2 = requests.patch(
            f"{SUPABASE_URL}/rest/v1/scripts?id=eq.{script_id}",
            headers=HEADERS,
            json={"character_reference_url": image_url},
            timeout=30,
        )
        resp2.raise_for_status()
        print(f"Character reference image generated and saved for script {script_id}.")
        return image_url

    print(f"Character reference image generation exhausted all retries ({last_error_text}) - continuing without one.")
    return None


def upload_reference_image(script_id, file_name, local_path):
    with open(local_path, "rb") as f:
        file_bytes = f.read()
    dest = f"{script_id}/refs/{file_name}"
    resp = requests.put(
        f"{SUPABASE_URL}/storage/v1/object/{CLIP_BUCKET}/{dest}",
        headers={
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
            "Content-Type": "image/png",
            "x-upsert": "true",
        },
        data=file_bytes,
        timeout=60,
    )
    if resp.status_code >= 400:
        print(f"Reference frame upload failed - status {resp.status_code}: {resp.text}")
        return None
    return f"{SUPABASE_URL}/storage/v1/object/public/{CLIP_BUCKET}/{dest}"


def extract_last_frame_url(script_id, shot_index, local_video_path):
    """
    Pulls the final frame of a just-generated (or already-downloaded) shot
    clip and uploads it as a small PNG, so it can be passed as the "image"
    anchor for the NEXT shot's Agnes call - this is what chains shots
    together visually instead of each one being generated blind. Fails
    soft (returns None) on any error, same fail-soft pattern as
    music/SFX/captions elsewhere in this file - continuity is a quality
    improvement, not something that should ever crash a run.

    DORMANT since 2026-08-18 (see CONTINUITY-CHAIN REMOVED in the file
    header) - no longer called from process_script's per-shot loop. Left
    defined in case cross-shot chaining is wanted back for a future
    single-protagonist format.
    """
    try:
        clip = VideoFileClip(local_video_path)
        frame = clip.get_frame(max(clip.duration - 1 / FRAME_RATE, 0))
        clip.close()
        img = Image.fromarray(frame)
        png_path = local_video_path.replace(".mp4", "_lastframe.png")
        img.save(png_path)
        url = upload_reference_image(script_id, f"shot_{shot_index:03d}_lastframe.png", png_path)
        os.remove(png_path)
        return url
    except Exception as e:
        print(f"Could not extract/upload last frame for shot {shot_index}, continuing without a continuity anchor for the next shot: {e}")
        return None


def get_continuity_anchor(script, video_urls):
    """
    Reconstructs the correct anchor image for the NEXT shot to generate:
    - if at least one shot is already done, downloads the most recently
      completed clip and extracts its last frame (this is what makes
      continuity survive across resumed runs, not just within one run)
    - otherwise falls back to the script's character reference image
      (generating it if it doesn't exist yet)

    DORMANT since 2026-08-18 (see CONTINUITY-CHAIN REMOVED in the file
    header) - no longer called from process_script's per-shot loop. Left
    defined in case cross-shot chaining is wanted back for a future
    single-protagonist format.
    """
    if video_urls:
        try:
            tmp_path = "/tmp/_anchor_source.mp4"
            download_file(video_urls[-1], tmp_path)
            url = extract_last_frame_url(script["id"], len(video_urls) - 1, tmp_path)
            os.remove(tmp_path)
            if url:
                return url
        except Exception as e:
            print(f"Could not rebuild continuity anchor from the last completed clip, falling back to character reference: {e}")

    return generate_character_reference(script)


def create_agnes_task(prompt, num_frames, image_url=None):
    last_error_text = None

    for attempt in range(AGNES_MAX_RETRIES):
        payload = {
            "model": "agnes-video-v2.0",
            "prompt": prompt,
            "height": HEIGHT,
            "width": WIDTH,
            "num_frames": num_frames,
            "frame_rate": FRAME_RATE,
        }
        if image_url:
            payload["image"] = image_url

        resp = requests.post(
            f"{AGNES_BASE}/videos",
            headers=AGNES_HEADERS,
            json=payload,
            timeout=60,
        )

        if resp.status_code == 400 and "content_policy_violation" in resp.text:
            raise ContentPolicyRejection(resp.text)

        if resp.status_code in AGNES_RETRYABLE_CODES:
            last_error_text = resp.text
            wait = 20 * (attempt + 1)
            print(f"AGNES transient error {resp.status_code} (attempt {attempt + 1}/{AGNES_MAX_RETRIES}): {resp.text}")
            print(f"Retrying in {wait}s...")
            time.sleep(wait)
            continue

        if resp.status_code >= 400:
            print(f"AGNES ERROR {resp.status_code}: {resp.text}")
        resp.raise_for_status()
        data = resp.json()
        return data.get("video_id") or data.get("id") or data.get("task_id")

    raise AgnesOverloadedError(f"Agnes still failing after {AGNES_MAX_RETRIES} attempts: {last_error_text}")


def extract_video_url(data):
    for key in ("video_url", "url", "remixed_from_video_id"):
        val = data.get(key)
        if isinstance(val, str) and val.startswith("http"):
            return val
    for val in data.values():
        if isinstance(val, str) and val.startswith("http") and val.endswith(".mp4"):
            return val
    return None


def poll_agnes_task(video_id, max_wait=300, interval=10):
    waited = 0
    while waited < max_wait:
        resp = requests.get(
            AGNES_POLL_URL,
            params={"video_id": video_id, "model_name": "agnes-video-v2.0"},
            headers=AGNES_HEADERS,
            timeout=30,
        )
        if resp.status_code == 400 and "content_policy_violation" in resp.text:
            raise ContentPolicyRejection(resp.text)
        if resp.status_code >= 400:
            print(f"AGNES POLL ERROR {resp.status_code}: {resp.text}")
        resp.raise_for_status()
        data = resp.json()
        status = data.get("status")
        if status == "completed":
            url = extract_video_url(data)
            if url:
                return url
            raise RuntimeError(f"Completed but no video URL found: {data}")
        if status == "failed":
            raise RuntimeError(f"Agnes generation failed: {data}")
        time.sleep(interval)
        waited += interval
    raise AgnesOverloadedError(f"Agnes generation timed out after {max_wait}s for video_id {video_id}")


def _generate_one_segment(shot, segment_duration, out_path, setting_and_characters="", anchor_image_url=None):
    raw_frames = int(segment_duration * FRAME_RATE)
    raw_frames = max(MIN_FRAMES, min(MAX_FRAMES, raw_frames))
    num_frames = round_to_valid_frames(raw_frames)
    num_frames = max(MIN_FRAMES, min(MAX_FRAMES, num_frames))

    prompt = build_agnes_prompt(shot, setting_and_characters, fallback_level=0)
    try:
        video_id = create_agnes_task(prompt, num_frames, image_url=anchor_image_url)
    except ContentPolicyRejection:
        print("Content policy rejection on primary prompt - retrying with sanitized-anchor fallback "
              "(tier 1, image anchor also dropped this attempt)...")
        try:
            fallback_prompt = build_agnes_prompt(shot, setting_and_characters, fallback_level=1)
            video_id = create_agnes_task(fallback_prompt, num_frames, image_url=None)
        except ContentPolicyRejection:
            print("Sanitized-anchor fallback ALSO rejected - retrying once more with a fully generic, "
                  "anchor-free prompt AND no image anchor (tier 2, last resort before giving up on this shot)...")
            ultra_prompt = build_agnes_prompt(shot, setting_and_characters, fallback_level=2)
            video_id = create_agnes_task(ultra_prompt, num_frames, image_url=None)

    video_url = poll_agnes_task(video_id)
    download_file(video_url, out_path)
    return out_path


def _extract_last_frame_local(video_path):
    """Extracts the last frame of a local clip file and uploads it nowhere -
    returns a local PNG path for immediate reuse as the next Agnes anchor
    within the same shot's chain-extension. Separate from
    extract_last_frame_url (which uploads to storage) because chain
    segments are purely intra-shot and never need to survive a resumed run."""
    clip = VideoFileClip(video_path)
    frame = clip.get_frame(max(clip.duration - 1 / FRAME_RATE, 0))
    clip.close()
    png_path = video_path.replace(".mp4", "_lastframe.png")
    Image.fromarray(frame).save(png_path)
    return png_path


def _upload_local_image_for_anchor(script_id, tag, png_path):
    """Chain-extension anchors must be passed to Agnes as a URL (same as
    every other anchor in this file), so the local last-frame PNG gets
    uploaded to storage just like extract_last_frame_url does, then
    removed locally."""
    url = upload_reference_image(script_id, tag, png_path)
    os.remove(png_path)
    return url


def generate_shot_clip(shot, target_duration, out_path, setting_and_characters="", anchor_image_url=None, script_id=None):
    capped_duration = min(target_duration, MAX_CLIP_SECONDS)
    _generate_one_segment(shot, capped_duration, out_path, setting_and_characters, anchor_image_url=anchor_image_url)

    if target_duration <= MAX_CLIP_SECONDS:
        return out_path

    remaining = target_duration - capped_duration
    segment_paths = [out_path]
    current_anchor_path = out_path
    chain_used = 0

    print(f"Shot needs {target_duration:.1f}s (over the ~{MAX_CLIP_SECONDS:.1f}s per-generation cap) - "
          f"chaining real continuation clips for the remaining {remaining:.1f}s instead of freezing.")

    while remaining > 0.05 and chain_used < MAX_CHAIN_SEGMENTS:
        seg_duration = min(remaining, MAX_CLIP_SECONDS)
        seg_out_path = out_path.replace(".mp4", f"_chain{chain_used + 1}.mp4")

        # CHAIN-RETRY FIX (2026-08-23): a single transient Agnes hiccup
        # (momentary overload/rate-limit) used to immediately give up on
        # the ENTIRE remaining chain and freeze-hold the rest of the shot -
        # even though AgnesOverloadedError is, by definition, a transient
        # condition create_agnes_task already retried AGNES_MAX_RETRIES
        # times internally. One extra attempt at the chain-segment level
        # (separate from that internal retry) catches the case where the
        # segment simply landed during a bad moment, without extending
        # runtime much - a genuine/permanent failure still falls through
        # to the freeze-hold exactly as before.
        # FREEZE-FRAME REDUCTION FIX (2026-08-25): raised from 2 attempts to
        # 3, with a shorter backoff between them (10s -> 6s), directly per
        # Zia's report that freeze-holds still show up on a minority of
        # shots. A single retry was giving up too early on transient Agnes
        # hiccups; a third attempt (with a faster retry cadence so it
        # doesn't meaningfully slow down a run) lets more segments recover
        # instead of falling through to the freeze-hold fallback below.
        segment_ok = False
        last_chain_error = None
        for chain_attempt in range(3):
            try:
                local_frame_path = _extract_last_frame_local(current_anchor_path)
                chain_anchor_url = _upload_local_image_for_anchor(
                    script_id or "unknown", f"chain_{os.path.basename(seg_out_path)}", local_frame_path
                )
                _generate_one_segment(shot, seg_duration, seg_out_path, setting_and_characters, anchor_image_url=chain_anchor_url)
                segment_ok = True
                break
            except (ContentPolicyRejection, AgnesOverloadedError, Exception) as e:
                last_chain_error = e
                if chain_attempt < 2:
                    print(f"Chain-extension segment {chain_used + 1} failed on attempt "
                          f"{chain_attempt + 1}/3 ({e}) - retrying before falling back to a freeze-hold.")
                    time.sleep(6)

        if not segment_ok:
            print(f"Chain-extension segment {chain_used + 1} failed after retry ({last_chain_error}) - "
                  f"falling back to a freeze-hold for the remaining {remaining:.1f}s instead of losing the whole shot.")
            break

        segment_paths.append(seg_out_path)
        current_anchor_path = seg_out_path
        remaining -= seg_duration
        chain_used += 1

    clips = [VideoFileClip(p) for p in segment_paths]
    combined = concatenate_videoclips(clips, method="compose")

    if remaining > 0.05:
        combined = fit_clip_to_duration(combined, combined.duration + remaining)

    tmp_path = out_path.replace(".mp4", "_extended.mp4")
    combined.write_videofile(tmp_path, fps=FRAME_RATE, codec="libx264", audio=False, threads=2, logger=None)
    for c in clips:
        c.close()
    for p in segment_paths[1:]:
        if os.path.exists(p):
            os.remove(p)
    os.replace(tmp_path, out_path)

    return out_path


def fit_clip_to_duration(clip, target):
    if clip.duration >= target:
        return clip.subclipped(0, target)

    extra = target - clip.duration
    freeze_frame = clip.to_ImageClip(t=max(clip.duration - 1 / FRAME_RATE, 0))
    freeze_frame = freeze_frame.with_duration(extra).with_fps(FRAME_RATE)
    return concatenate_videoclips([clip, freeze_frame])


def fit_audio_to_duration(audio_clip, target):
    if audio_clip.duration >= target:
        return audio_clip.subclipped(0, target)
    reps = int(target // audio_clip.duration) + 1
    looped = concatenate_audioclips([audio_clip] * reps)
    return looped.subclipped(0, target)


def upload_clip(script_id, index, file_path):
    file_name = f"{script_id}/shot_{index:03d}.mp4"
    with open(file_path, "rb") as f:
        file_bytes = f.read()
    resp = requests.put(
        f"{SUPABASE_URL}/storage/v1/object/{CLIP_BUCKET}/{file_name}",
        headers={
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
            "Content-Type": "video/mp4",
            "x-upsert": "true",
        },
        data=file_bytes,
        timeout=300,
    )
    if resp.status_code >= 400:
        print(f"Clip upload failed - status {resp.status_code}: {resp.text}")
    resp.raise_for_status()
    return f"{SUPABASE_URL}/storage/v1/object/public/{CLIP_BUCKET}/{file_name}"


def save_progress(script_id, video_urls, next_index):
    resp = requests.patch(
        f"{SUPABASE_URL}/rest/v1/scripts?id=eq.{script_id}",
        headers=HEADERS,
        json={"video_urls": video_urls, "video_next_index": next_index},
        timeout=30,
    )
    resp.raise_for_status()


def mark_content_flagged(script_id, shot_index, reason):
    resp = requests.patch(
        f"{SUPABASE_URL}/rest/v1/scripts?id=eq.{script_id}",
        headers=HEADERS,
        json={"status": "content_flagged"},
        timeout=30,
    )
    resp.raise_for_status()
    print(f"Script {script_id} marked content_flagged (shot {shot_index + 1}) - will be skipped by future runs until manually reset. Reason: {reason}")


def compute_shot_durations(shot_list, total_duration):
    weights = [max(len(s.get("narration_excerpt", "")), 20) for s in shot_list]
    total_weight = sum(weights)
    return [(weight / total_weight) * total_duration for weight in weights]


def get_shot_durations(script, shot_list, audio_clip):
    stored = script.get("shot_durations")
    if (
        isinstance(stored, list)
        and len(stored) == len(shot_list)
        and all(isinstance(d, (int, float)) and d >= 0 for d in stored)
    ):
        print("Using real per-shot narration durations from shot_durations column.")
        return list(stored)
    print("shot_durations column missing/invalid for this script - falling back to text-length estimate.")
    return compute_shot_durations(shot_list, audio_clip.duration)


def compute_shot_start_times(shot_durations):
    starts = []
    t = 0.0
    for d in shot_durations:
        starts.append(t)
        t += d
    return starts


def compute_target_bitrate(duration_seconds=None, audio_kbps=128):
    # CHUNKED-UPLOAD QUALITY FIX (2026-08-20): no longer takes duration or
    # target_mb into account at all - bitrate used to be squeezed down as
    # episodes got longer, which is exactly what produced the ~144p-looking
    # 19-minute upload Zia flagged. Video bitrate is now a FIXED quality
    # value (QUALITY_VIDEO_BITRATE_KBPS) regardless of how long the episode
    # is. If a fixed-bitrate encode would be too big for one 50MB file,
    # that's handled by chunking the output afterward (see
    # split_video_into_chunks / upload_video_chunked below) - never by
    # dropping quality. duration_seconds/audio_kbps args kept for call-site
    # compatibility but no longer change the result.
    return f"{QUALITY_VIDEO_BITRATE_KBPS}k"


def estimate_output_size_mb(duration_seconds, video_kbps=QUALITY_VIDEO_BITRATE_KBPS, audio_kbps=128):
    total_kbps = video_kbps + audio_kbps
    total_bits = total_kbps * 1000 * duration_seconds
    return total_bits / 8 / 1024 / 1024


def _encode_subclip_safe(clip, start, end, out_path, depth=0):
    """
    CHUNK-SIZE VERIFICATION FIX (2026-08-23): encodes clip[start:end] to
    out_path, then checks the REAL on-disk size against
    HARD_CHUNK_LIMIT_MB (Supabase's real object size ceiling - confirmed
    hit live on script 40ffc83c/part_005, which encoded denser than the
    MAX_CHUNK_MB estimate predicted and got rejected outright with a bare
    400). If the real file is still too big, the segment is split into
    two equal halves and each half is recursively encoded on its own -
    this guarantees every chunk that reaches upload_video_chunk is
    verified safe, regardless of how densely a particular segment's
    actual content happens to compress. depth caps recursion as a safety
    net only (5 levels = the segment would have to still be oversized at
    1/32nd its original slice, which should never happen in practice) -
    if that ever triggers, the oversized file is uploaded anyway with a
    loud warning rather than silently dropping content.
    """
    sub = clip.subclipped(start, end)
    sub.write_videofile(
        out_path,
        fps=FRAME_RATE,
        codec="libx265",
        audio_codec="aac",
        audio_bitrate="128k",
        bitrate=f"{QUALITY_VIDEO_BITRATE_KBPS}k",
        threads=2,
        logger=None,
        ffmpeg_params=["-preset", "fast", "-tag:v", "hvc1"],
    )
    size_mb = os.path.getsize(out_path) / (1024 * 1024)

    if size_mb <= HARD_CHUNK_LIMIT_MB or depth >= 5 or (end - start) < 2:
        if size_mb > HARD_CHUNK_LIMIT_MB:
            print(f"  WARNING: segment [{start:.1f}s-{end:.1f}s] still {size_mb:.1f}MB after "
                  f"{depth} re-split attempts (hit the recursion safety cap) - uploading anyway, "
                  f"this may still fail upstream.")
        return [out_path]

    print(f"  Segment [{start:.1f}s-{end:.1f}s] encoded to {size_mb:.1f}MB, over the "
          f"{HARD_CHUNK_LIMIT_MB}MB real limit - re-splitting in half (depth {depth + 1}).")
    os.remove(out_path)
    mid = (start + end) / 2
    left_path = out_path.replace(".mp4", "a.mp4")
    right_path = out_path.replace(".mp4", "b.mp4")
    left_results = _encode_subclip_safe(clip, start, mid, left_path, depth + 1)
    right_results = _encode_subclip_safe(clip, mid, end, right_path, depth + 1)
    return left_results + right_results


def split_video_into_chunks(local_path, max_chunk_mb=MAX_CHUNK_MB):
    """
    Splits an already-encoded local video file into N sequential chunks.
    max_chunk_mb only decides how many EVENLY-TIMED segments to aim for up
    front (an estimate); every segment is then encoded and verified for
    real size via _encode_subclip_safe, which recursively re-splits any
    segment that comes out over HARD_CHUNK_LIMIT_MB after encoding - so
    the up-front estimate no longer has to be exact, only a reasonable
    starting point.
    Returns a list of local file paths (chunk_paths), NOT URLs - caller is
    responsible for uploading and cleanup.
    """
    actual_size_mb = os.path.getsize(local_path) / (1024 * 1024)
    if actual_size_mb <= max_chunk_mb:
        return [local_path]

    num_chunks = math.ceil(actual_size_mb / max_chunk_mb)
    clip = VideoFileClip(local_path)
    total_duration = clip.duration
    chunk_duration = total_duration / num_chunks

    print(f"Final video is {actual_size_mb:.1f}MB, over the {max_chunk_mb}MB per-file chunk target - "
          f"splitting into {num_chunks} initial segments (~{chunk_duration:.1f}s each), each verified "
          f"and re-split as needed to stay under the real {HARD_CHUNK_LIMIT_MB}MB limit.")

    all_chunk_paths = []
    for i in range(num_chunks):
        start = i * chunk_duration
        end = min((i + 1) * chunk_duration, total_duration)
        tmp_path = local_path.replace(".mp4", f"_seg{i + 1:02d}.mp4")
        safe_paths = _encode_subclip_safe(clip, start, end, tmp_path)
        all_chunk_paths.extend(safe_paths)

    clip.close()

    for idx, p in enumerate(all_chunk_paths, start=1):
        size_mb = os.path.getsize(p) / (1024 * 1024)
        print(f"  Final chunk {idx}/{len(all_chunk_paths)}: {size_mb:.1f}MB ({p})")

    return all_chunk_paths


def poll_ace_music_task(task_id, out_path, base_url=None, max_wait=180, interval=8):
    waited = 0
    while waited < max_wait:
        resp = requests.post(
            f"{base_url}/query_result",
            headers=ACE_MUSIC_HEADERS,
            json={"task_id_list": [task_id]},
            timeout=30,
        )
        if resp.status_code >= 400:
            print(f"ACE MUSIC POLL ERROR ({base_url}) {resp.status_code}: {resp.text}")
            return None
        entries = resp.json().get("data", [])
        if not entries:
            time.sleep(interval)
            waited += interval
            continue
        entry = entries[0]
        status = entry.get("status")
        if status == 1:
            result_list = json.loads(entry.get("result", "[]"))
            if not result_list or not result_list[0].get("file"):
                print(f"ACE Music task succeeded but no file in result: {result_list}")
                return None
            file_path = result_list[0]["file"]
            audio_resp = requests.get(f"{base_url}{file_path}", timeout=60)
            audio_resp.raise_for_status()
            with open(out_path, "wb") as f:
                f.write(audio_resp.content)
            return out_path
        if status == 2:
            print(f"ACE Music task failed: {entry}")
            return None
        time.sleep(interval)
        waited += interval
    print(f"ACE Music task {task_id} timed out after {max_wait}s")
    return None


def generate_background_music(prompt, duration, out_path, debug=None):
    """
    AUDIO-DEBUG FIX (2026-08-23): music_generated has been false on every
    single episode ever assembled, with no way to see why without GitHub
    Actions log access (which Zia does not have). `debug`, when passed a
    dict by the caller, gets the LAST real error string written to it
    under debug["music_error"] on total failure - this dict is threaded
    all the way up to mark_video_generated and persisted to the new
    scripts.audio_debug column, so the real cause becomes queryable
    directly from Supabase instead of requiring log access at all.
    Behavior/return value is otherwise unchanged.
    """
    if not ACE_MUSIC_API_KEY:
        msg = "No ACE_MUSIC_API_KEY set - skipping background music."
        print(msg)
        if debug is not None:
            debug["music_error"] = msg
        return None

    last_error = None
    for base in ACE_MUSIC_BASES:
        try:
            resp = requests.post(
                f"{base}/release_task",
                headers=ACE_MUSIC_HEADERS,
                json={
                    "prompt": prompt,
                    "audio_duration": max(10, min(int(duration) + 5, 600)),
                    "thinking": True,
                },
                timeout=60,
            )
            if resp.status_code >= 400:
                last_error = f"ACE MUSIC ERROR ({base}) {resp.status_code}: {resp.text[:500]}"
                print(last_error)
                continue
            task_id = resp.json().get("data", {}).get("task_id")
            if not task_id:
                last_error = f"ACE Music response had no task_id ({base}): {str(resp.json())[:500]}"
                print(last_error)
                continue
            result = poll_ace_music_task(task_id, out_path, base_url=base)
            if result:
                return result
            last_error = f"ACE Music task on {base} did not return a usable file (see poll log)."
        except Exception as e:
            last_error = f"ACE Music generation raised an exception on {base}: {e}"
            print(f"{last_error} - trying next host.")

    print("Every ACE Music host failed - trying free Hugging Face MusicGen fallback.")
    result = generate_background_music_musicgen(prompt, duration, out_path, debug=debug)
    if result is None and debug is not None and "music_error" not in debug:
        debug["music_error"] = last_error or "ACE Music failed on all hosts (no specific error captured)."
    return result


def generate_background_music_musicgen(prompt, duration, out_path, debug=None):
    if not HF_TOKEN:
        msg = "No HF_TOKEN set - skipping MusicGen fallback, continuing without background music."
        print(msg)
        if debug is not None:
            debug["music_error"] = msg
        return None
    try:
        resp = requests.post(
            HF_MUSICGEN_URL,
            headers={"Authorization": f"Bearer {HF_TOKEN}"},
            json={"inputs": prompt},
            timeout=120,
        )
        if resp.status_code == 503:
            wait_for = 20
            try:
                wait_for = min(int(resp.json().get("estimated_time", 20)) + 2, 60)
            except Exception:
                pass
            print(f"MusicGen is cold-loading on Hugging Face - waiting {wait_for}s and retrying once.")
            time.sleep(wait_for)
            resp = requests.post(
                HF_MUSICGEN_URL,
                headers={"Authorization": f"Bearer {HF_TOKEN}"},
                json={"inputs": prompt},
                timeout=120,
            )
        if resp.status_code >= 400:
            msg = f"MusicGen fallback failed ({resp.status_code}): {resp.text[:500]}"
            print(msg)
            if debug is not None:
                debug["music_error"] = msg
            return None
        content_type = resp.headers.get("content-type", "")
        if "audio" not in content_type:
            msg = f"MusicGen fallback returned unexpected content-type '{content_type}' (likely an HTML/JSON error page, not audio)."
            print(msg)
            if debug is not None:
                debug["music_error"] = msg
            return None
        with open(out_path, "wb") as f:
            f.write(resp.content)
        print(f"MusicGen fallback succeeded - background music generated via Hugging Face free tier.")
        return out_path
    except Exception as e:
        msg = f"MusicGen fallback raised an exception: {e}"
        print(f"{msg}, continuing without background music.")
        if debug is not None:
            debug["music_error"] = msg
        return None


def search_freesound_sfx(query, out_path, debug=None):
    """
    AUDIO-DEBUG FIX (2026-08-23): same rationale as generate_background_music.
    On failure, appends a short reason string to debug["sfx_errors"] (capped
    at 5 entries so a whole-episode SFX outage doesn't bloat the column)
    instead of only printing it.

    SFX QUERY SIMPLIFICATION (2026-08-24): sfx_cue text written by the
    shot-breakdown LLM is a full descriptive sentence (e.g. "Howling cold
    wind and distant creaking wooden pilings"), but Freesound's search is
    tag-based and matches short keyword-style queries far better -
    confirmed live via audio_debug on script 4fe33993 (Lighthouse Keeper),
    where all 5 SFX cues returned "No results" verbatim. Before hitting
    Freesound, the query is now trimmed to its first few significant words
    (stopwords and filler dropped) as a keyword-style fallback query if the
    full-sentence query returns nothing, instead of giving up after one
    literal-sentence search.
    """
    if not FREESOUND_API_KEY:
        if debug is not None and "sfx_errors" not in debug:
            debug.setdefault("sfx_errors", []).append("No FREESOUND_API_KEY set.")
        return None

    def _try_query(q):
        resp = requests.get(
            "https://freesound.org/apiv2/search/text/",
            params={
                "query": q,
                "token": FREESOUND_API_KEY,
                "fields": "id,previews",
                "filter": "duration:[0.1 TO 8]",
                "sort": "score",
                "page_size": 1,
            },
            timeout=30,
        )
        if resp.status_code >= 400:
            return None, f"FREESOUND ERROR {resp.status_code} for '{q}': {resp.text[:300]}"
        results = resp.json().get("results", [])
        if not results:
            return None, f"No results for cue: {q}"
        previews = results[0].get("previews", {})
        preview_url = previews.get("preview-hq-mp3") or previews.get("preview-lq-mp3")
        if not preview_url:
            return None, f"Result for '{q}' had no preview URL."
        return preview_url, None

    _STOPWORDS = {
        "a", "an", "the", "of", "in", "on", "at", "and", "or", "with",
        "distant", "background", "faint", "loud", "soft", "sudden", "slight",
        "some", "into", "from", "as", "is", "are", "being", "nearby",
    }

    def _keyword_fallback_query(q):
        words = [w.strip(".,!?;:'\"()").lower() for w in q.split()]
        meaningful = [w for w in words if w and w not in _STOPWORDS]
        return " ".join(meaningful[:3]) if meaningful else q

    try:
        preview_url, err = _try_query(query)

        if not preview_url:
            fallback_q = _keyword_fallback_query(query)
            if fallback_q and fallback_q.lower() != query.strip().lower():
                print(f"Freesound literal-sentence query failed ({err}) - retrying with "
                      f"keyword fallback query '{fallback_q}'.")
                preview_url, err2 = _try_query(fallback_q)
                if not preview_url:
                    err = f"{err} | keyword fallback '{fallback_q}' also failed: {err2}"

        if not preview_url:
            print(err)
            if debug is not None and len(debug.get("sfx_errors", [])) < 5:
                debug.setdefault("sfx_errors", []).append(err)
            return None

        download_file(preview_url, out_path)
        return out_path
    except Exception as e:
        msg = f"Freesound lookup raised an exception for cue '{query}': {e}"
        print(f"{msg}, skipping this SFX.")
        if debug is not None and len(debug.get("sfx_errors", [])) < 5:
            debug.setdefault("sfx_errors", []).append(msg)
        return None


def apply_safety_limiter(audio_clip, ceiling=LIMITER_CEILING):
    try:
        samples = audio_clip.to_soundarray(fps=44100)
    except Exception as e:
        print(f"Safety limiter: could not analyze mixed audio ({e}) - skipping peak check, using mix as-is.")
        return audio_clip
    peak = float(np.max(np.abs(samples))) if samples.size else 0.0

    if peak <= 0:
        print("Safety limiter: mixed audio is silent, nothing to scale.")
        return audio_clip
    if peak <= ceiling:
        print(f"Safety limiter: peak was {peak:.3f} (ceiling {ceiling}), no scaling needed.")
        return audio_clip

    scale = ceiling / peak
    print(f"Safety limiter: peak was {peak:.3f}, exceeds ceiling {ceiling} - scaling whole mix by {scale:.3f} to prevent clipping.")
    return audio_clip.with_volume_scaled(scale)


def extract_original_clip_audio(video_clips, shot_durations, shot_starts, total_duration):
    layers = []
    for i, clip in enumerate(video_clips):
        try:
            if clip.audio is None:
                continue
            seg_audio = clip.audio
            max_len = shot_durations[i]
            if seg_audio.duration and seg_audio.duration > max_len:
                seg_audio = seg_audio.subclipped(0, max_len)
            seg_audio = seg_audio.with_volume_scaled(ORIGINAL_CLIP_AUDIO_VOLUME).with_start(shot_starts[i])
            layers.append(seg_audio)
        except Exception as e:
            print(f"Could not extract original audio from shot {i}, skipping that layer: {e}")
    return layers


def build_audio_mix(narration_path, music_mood, shot_list, shot_durations, shot_starts, total_duration, original_clip_audio_layers=None):
    layers = [AudioFileClip(narration_path).with_volume_scaled(NARRATION_VOLUME)]
    stats = {"music_generated": False, "sfx_cues_total": 0, "sfx_applied_count": 0}
    # AUDIO-DEBUG FIX (2026-08-23): collects the real failure reasons from
    # generate_background_music/search_freesound_sfx so they can be
    # persisted to scripts.audio_debug (see mark_video_generated) and
    # queried directly from Supabase - no GitHub Actions log access needed.
    audio_debug = {}

    if original_clip_audio_layers:
        layers.extend(original_clip_audio_layers)

    if music_mood:
        music_path = "/tmp/background_music.mp3"
        if generate_background_music(music_mood, total_duration, music_path, debug=audio_debug):
            music_clip = AudioFileClip(music_path)
            music_clip = fit_audio_to_duration(music_clip, total_duration)
            music_clip = music_clip.with_volume_scaled(MUSIC_VOLUME)
            layers.append(music_clip)
            stats["music_generated"] = True
    else:
        audio_debug["music_error"] = "No music_mood set on this script - music generation never attempted."

    for i, shot in enumerate(shot_list):
        cue = (shot.get("sfx_cue") or "").strip()
        if not cue:
            continue
        stats["sfx_cues_total"] += 1
        sfx_path = f"/tmp/sfx_{i:03d}.mp3"
        if search_freesound_sfx(cue, sfx_path, debug=audio_debug):
            sfx_clip = AudioFileClip(sfx_path)
            max_len = shot_durations[i]
            if sfx_clip.duration > max_len:
                sfx_clip = sfx_clip.subclipped(0, max_len)
            sfx_clip = sfx_clip.with_volume_scaled(SFX_VOLUME).with_start(shot_starts[i])
            layers.append(sfx_clip)
            stats["sfx_applied_count"] += 1

    if audio_debug:
        stats["audio_debug"] = audio_debug

    mixed = CompositeAudioClip(layers)
    if mixed.duration and mixed.duration > total_duration:
        mixed = mixed.subclipped(0, total_duration)
    print(f"Audio mix stats: music_generated={stats['music_generated']}, "
          f"sfx_applied={stats['sfx_applied_count']}/{stats['sfx_cues_total']} cues, "
          f"original_clip_audio_layers={len(original_clip_audio_layers or [])}")
    return apply_safety_limiter(mixed), stats


def _load_caption_font(size=CAPTION_FONT_SIZE):
    for path in CAPTION_FONT_PATHS:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    print("Caption font not found at any known path - falling back to PIL's default font (captions will be smaller/plainer).")
    return ImageFont.load_default()


def _wrap_caption_text(text, font, max_width, draw):
    words = text.split()
    lines = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        bbox = draw.textbbox((0, 0), candidate, font=font)
        if bbox[2] - bbox[0] <= max_width or not current:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def render_caption_image(text, video_width=WIDTH, video_height=HEIGHT):
    text = (text or "").strip()
    if not text:
        return None

    font = _load_caption_font()
    img = Image.new("RGBA", (video_width, video_height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    max_text_width = int(video_width * CAPTION_MAX_WIDTH_RATIO)
    lines = _wrap_caption_text(text, font, max_text_width, draw)
    if not lines:
        return None

    line_heights = []
    line_widths = []
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        line_widths.append(bbox[2] - bbox[0])
        line_heights.append(bbox[3] - bbox[1])

    line_height = max(line_heights) if line_heights else CAPTION_FONT_SIZE
    block_height = len(lines) * line_height + (len(lines) - 1) * CAPTION_LINE_SPACING
    block_width = max(line_widths) if line_widths else 0

    block_bottom = video_height - CAPTION_BOTTOM_MARGIN
    block_top = block_bottom - block_height

    bg_left = (video_width - block_width) // 2 - CAPTION_BG_PADDING
    bg_right = (video_width + block_width) // 2 + CAPTION_BG_PADDING
    bg_top = block_top - CAPTION_BG_PADDING
    bg_bottom = block_bottom + CAPTION_BG_PADDING
    draw.rounded_rectangle([bg_left, bg_top, bg_right, bg_bottom], radius=14, fill=CAPTION_BG_COLOR)

    y = block_top
    for line, lw in zip(lines, line_widths):
        x = (video_width - lw) // 2
        draw.text(
            (x, y), line, font=font, fill=CAPTION_TEXT_COLOR,
            stroke_width=CAPTION_STROKE_WIDTH, stroke_fill=CAPTION_STROKE_COLOR,
        )
        y += line_height + CAPTION_LINE_SPACING

    return img


def build_caption_clip(text, start, duration, video_width=WIDTH, video_height=HEIGHT):
    try:
        img = render_caption_image(text, video_width, video_height)
        if img is None:
            return None
        frame = np.array(img)
        clip = ImageClip(frame, transparent=True, duration=duration)
        clip = clip.with_start(start)
        return clip
    except Exception as e:
        print(f"Caption render failed for text {text[:60]!r}, skipping this caption: {e}")
        return None


def build_caption_clips(shot_list, shot_durations, shot_starts, video_width=WIDTH, video_height=HEIGHT):
    caption_clips = []
    for i, shot in enumerate(shot_list):
        text = (shot.get("narration_excerpt") or "").strip()
        if not text:
            continue
        clip = build_caption_clip(text, shot_starts[i], shot_durations[i], video_width, video_height)
        if clip is not None:
            caption_clips.append(clip)
    print(f"Built {len(caption_clips)}/{len(shot_list)} caption overlays.")
    return caption_clips


def assemble_final_video(script_id, video_urls, narration_path, music_mood, shot_list, shot_durations, output_path, setting_and_characters=""):
    clips = []
    for i, url in enumerate(video_urls):
        raw_path = f"/tmp/final_shot_{i:03d}.mp4"
        download_file(url, raw_path)

        if i == len(video_urls) - 1:
            clip = VideoFileClip(raw_path)
            clip = clip.resized(new_size=(WIDTH, HEIGHT))
            if clip.duration < shot_durations[i]:
                try:
                    local_frame_path = _extract_last_frame_local(raw_path)
                    chain_anchor_url = _upload_local_image_for_anchor(
                        script_id, f"trail_{os.path.basename(raw_path)}", local_frame_path
                    )
                    trail_out_path = raw_path.replace(".mp4", "_trail.mp4")
                    remaining = shot_durations[i] - clip.duration
                    _generate_one_segment(
                        shot_list[i], min(remaining, MAX_CLIP_SECONDS), trail_out_path,
                        setting_and_characters, anchor_image_url=chain_anchor_url,
                    )
                    trail_clip = VideoFileClip(trail_out_path).resized(new_size=(WIDTH, HEIGHT))
                    combined = concatenate_videoclips([clip, trail_clip], method="compose")
                    if combined.duration < shot_durations[i]:
                        combined = fit_clip_to_duration(combined, shot_durations[i])
                    clip = combined
                except Exception as e:
                    print(f"Trail chain-extension failed ({e}) - falling back to freeze-hold for the outro: {e}")
                    clip = fit_clip_to_duration(clip, shot_durations[i])
        else:
            clip = VideoFileClip(raw_path)
            clip = clip.resized(new_size=(WIDTH, HEIGHT))
            clip = fit_clip_to_duration(clip, shot_durations[i])

        clips.append(clip)

    total_duration = sum(shot_durations)
    shot_starts = compute_shot_start_times(shot_durations)

    original_clip_audio_layers = extract_original_clip_audio(clips, shot_durations, shot_starts, total_duration)

    final_audio, audio_stats = build_audio_mix(
        narration_path, music_mood, shot_list, shot_durations, shot_starts, total_duration,
        original_clip_audio_layers=original_clip_audio_layers,
    )

    final_audio = final_audio.with_effects(
        [AudioFadeIn(FADE_IN_SECONDS), AudioFadeOut(FADE_OUT_SECONDS)]
    )

    final = concatenate_videoclips(clips, method="compose")

    final = final.with_effects([FadeIn(FADE_IN_SECONDS), FadeOut(FADE_OUT_SECONDS)])
    final = final.with_audio(final_audio)
    # CHUNKED-UPLOAD QUALITY FIX (2026-08-20): bitrate is now fixed/quality-
    # driven (see compute_target_bitrate above) - duration no longer
    # affects it, so the encode below is always done at full quality.
    # Whether the result needs chunking to fit Supabase's 50MB cap is
    # decided AFTER this encode, in process_script, based on the real
    # output file size - not by lowering bitrate ahead of time.
    target_bitrate = compute_target_bitrate()
    print(f"Target video bitrate: {target_bitrate} (fixed, quality-driven - duration was {total_duration:.1f}s)")
    final.write_videofile(
        output_path,
        fps=FRAME_RATE,
        codec="libx265",
        audio_codec="aac",
        audio_bitrate="128k",
        bitrate=target_bitrate,
        threads=2,
        logger=None,
        ffmpeg_params=["-preset", "fast", "-tag:v", "hvc1"],
    )
    return output_path, audio_stats


def upload_video(script_id, file_path):
    file_name = f"{script_id}.mp4"
    file_size_mb = os.path.getsize(file_path) / (1024 * 1024)
    print(f"Final video size: {file_size_mb:.1f}MB")
    with open(file_path, "rb") as f:
        file_bytes = f.read()

    resp = requests.put(
        f"{SUPABASE_URL}/storage/v1/object/{VIDEO_BUCKET}/{file_name}",
        headers={
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
            "Content-Type": "video/mp4",
            "x-upsert": "true",
        },
        data=file_bytes,
        timeout=300,
    )
    if resp.status_code >= 400:
        print(f"Upload failed - status {resp.status_code}: {resp.text}")
    resp.raise_for_status()
    return f"{SUPABASE_URL}/storage/v1/object/public/{VIDEO_BUCKET}/{file_name}"


def upload_video_chunk(script_id, chunk_index, file_path):
    file_name = f"{script_id}/part_{chunk_index:03d}.mp4"
    file_size_mb = os.path.getsize(file_path) / (1024 * 1024)
    print(f"Uploading chunk {chunk_index}: {file_size_mb:.1f}MB")
    with open(file_path, "rb") as f:
        file_bytes = f.read()

    resp = requests.put(
        f"{SUPABASE_URL}/storage/v1/object/{VIDEO_BUCKET}/{file_name}",
        headers={
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
            "Content-Type": "video/mp4",
            "x-upsert": "true",
        },
        data=file_bytes,
        timeout=300,
    )
    if resp.status_code >= 400:
        print(f"Chunk upload failed - status {resp.status_code}: {resp.text}")
    resp.raise_for_status()
    return f"{SUPABASE_URL}/storage/v1/object/public/{VIDEO_BUCKET}/{file_name}"


def upload_video_chunked(script_id, local_path):
    """
    CHUNKED-UPLOAD QUALITY FIX (2026-08-20): replaces a single upload_video
    call at the point where the final assembled video is uploaded.
    Checks the real on-disk size of the already-encoded (full-quality)
    output file; if it fits under Supabase's 50MB cap as one file, uploads
    it exactly as before (single video_url, unchanged behavior). If not,
    splits it into multiple full-quality chunks (split_video_into_chunks,
    now with per-chunk real-size verification as of 2026-08-23) and
    uploads each separately, returning a list of chunk URLs instead.
    Local chunk files are cleaned up after upload either way.
    Returns (video_url_or_None, video_chunk_urls_list_or_None) - exactly
    one of the two will be non-None.
    """
    chunk_paths = split_video_into_chunks(local_path)

    if len(chunk_paths) == 1 and chunk_paths[0] == local_path:
        video_url = upload_video(script_id, local_path)
        return video_url, None

    chunk_urls = []
    for i, chunk_path in enumerate(chunk_paths, start=1):
        chunk_url = upload_video_chunk(script_id, i, chunk_path)
        chunk_urls.append(chunk_url)
        os.remove(chunk_path)

    print(f"Uploaded {len(chunk_urls)} chunks for script {script_id}. "
          f"NOTE: re-stitching into one file happens in youtube_upload.py before the YouTube upload - "
          f"chunk_urls are stored in order and are individually complete, playable video files in the meantime.")
    return None, chunk_urls


def mark_video_generated(script_id, video_url=None, video_chunk_urls=None, audio_stats=None):
    update = {"status": "video_generated"}
    if video_url is not None:
        update["video_url"] = video_url
    if video_chunk_urls is not None:
        update["video_chunk_urls"] = video_chunk_urls
    if audio_stats is not None:
        update["music_generated"] = audio_stats.get("music_generated", False)
        update["sfx_applied_count"] = audio_stats.get("sfx_applied_count", 0)
        # AUDIO-DEBUG FIX (2026-08-23): persists the real failure reason(s)
        # collected in build_audio_mix to scripts.audio_debug, queryable
        # directly from Supabase - no GitHub Actions log access needed to
        # diagnose why music/SFX didn't apply on a given episode.
        update["audio_debug"] = audio_stats.get("audio_debug")
    resp = requests.patch(
        f"{SUPABASE_URL}/rest/v1/scripts?id=eq.{script_id}",
        headers=HEADERS,
        json=update,
        timeout=30,
    )
    resp.raise_for_status()


def process_script(script, shot_limit=CLIP_BATCH_LIMIT):
    script_id = script["id"]
    if not script.get("narration_url"):
        print(f"Script {script_id} has no narration_url yet. Skipping.")
        return 0

    print(f"Working on script {script_id}")

    shot_list = script["shot_list"]
    if isinstance(shot_list, str):
        shot_list = json.loads(shot_list)
    total_shots = len(shot_list)
    music_mood = script.get("music_mood") or ""
    setting_and_characters = script.get("setting_and_characters", "")

    video_urls = script.get("video_urls") or []
    next_index = script.get("video_next_index") or 0

    verified_urls = []
    for i, url in enumerate(video_urls):
        verified = False
        last_error = None
        for attempt in range(CLIP_VERIFY_RETRIES):
            try:
                head = requests.head(url, timeout=30)
                if head.status_code == 200:
                    verified = True
                    break
                last_error = f"status {head.status_code}"
            except requests.RequestException as e:
                last_error = str(e)
            if attempt < CLIP_VERIFY_RETRIES - 1:
                time.sleep(CLIP_VERIFY_RETRY_WAIT)
        if verified:
            verified_urls.append(url)
        else:
            print(f"Clip {i} failed verification after {CLIP_VERIFY_RETRIES} attempts ({last_error}), will regenerate: {url}")
            break

    if len(verified_urls) != len(video_urls):
        video_urls = verified_urls
        next_index = len(verified_urls)
        save_progress(script_id, video_urls, next_index)
        print(f"Corrected progress after verification: {next_index}/{total_shots} shots actually confirmed done")

    shots_used = 0

    if next_index >= total_shots:
        print(f"All {total_shots} shots already generated, video_urls has {len(video_urls)} entries. Skipping to assembly check.")
    elif shot_limit <= 0:
        print(f"No shot budget remaining this run for script {script_id} - will get a turn on the next scheduled run.")
        return 0
    else:
        audio_path = "/tmp/narration_audio"
        audio_path += ".mp3" if script["narration_url"].endswith(".mp3") else ".wav"
        download_file(script["narration_url"], audio_path)
        audio_clip = AudioFileClip(audio_path)
        shot_durations = get_shot_durations(script, shot_list, audio_clip)

        batch_end = min(next_index + shot_limit, total_shots)
        print(f"Resuming from shot {next_index + 1}/{total_shots} ({len(video_urls)} already done) - generating up to shot {batch_end} this run (budget this call: {shot_limit})")

        anchor_image_url = None

        for i in range(next_index, batch_end):
            shot = shot_list[i]
            raw_path = f"/tmp/shot_{i:03d}.mp4"
            print(f"Generating shot {i+1}/{total_shots} (~{shot_durations[i]:.1f}s)...")
            try:
                generate_shot_clip(shot, shot_durations[i], raw_path, setting_and_characters, anchor_image_url=anchor_image_url, script_id=script_id)
            except ContentPolicyRejection as e:
                mark_content_flagged(script_id, i, str(e))
                print(f"Rejected visual_description: {shot.get('visual_description', '')!r}")
                print(f"FIX: reword shot_list[{i}].visual_description for script {script_id} in the "
                      f"scripts table, then reset status to 'images_generated' to resume from exactly "
                      f"this shot. Moving on to the next-oldest eligible candidate for now.")
                return shots_used
            except AgnesOverloadedError as e:
                print(f"Agnes appears overloaded (upstream load saturated) on shot {i+1}/{total_shots} after all retries: {e}")
                if shots_used:
                    print(f"Progress already saved through shot {i}/{total_shots} ({len(video_urls)} clips done) "
                          f"this run - stopping here instead of crashing; next scheduled run resumes from here.")
                else:
                    print(f"Zero progress made on this script this run - moving on to the next-oldest "
                          f"eligible candidate instead of ending the run. This script's own turn will "
                          f"come back around once Agnes's load eases.")
                return shots_used

            clip_url = upload_clip(script_id, i, raw_path)
            video_urls.append(clip_url)
            save_progress(script_id, video_urls, i + 1)
            shots_used += 1
            print(f"Saved progress: {i + 1}/{total_shots} shots done")

            os.remove(raw_path)
            time.sleep(4)

        if batch_end < total_shots:
            print(f"Shot budget for this candidate used up this run ({shots_used} shots). {total_shots - batch_end} shots remain - resuming on a future run.")
            return shots_used

    if len(video_urls) >= total_shots:
        print("All shots done. Assembling final video...")
        try:
            audio_path = "/tmp/narration_audio_final"
            audio_path += ".mp3" if script["narration_url"].endswith(".mp3") else ".wav"
            download_file(script["narration_url"], audio_path)
            audio_clip = AudioFileClip(audio_path)
            shot_durations = get_shot_durations(script, shot_list, audio_clip)
            shot_durations[-1] += TRAIL_SECONDS

            output_path = "/tmp/final_video.mp4"
            output_path, audio_stats = assemble_final_video(script_id, video_urls, audio_path, music_mood, shot_list, shot_durations, output_path, setting_and_characters=setting_and_characters)

            video_url, video_chunk_urls = upload_video_chunked(script_id, output_path)
            if video_url:
                print(f"Uploaded as a single file: {video_url}")
            else:
                print(f"Uploaded as {len(video_chunk_urls)} chunks (single-file would have exceeded 50MB at full quality).")

            mark_video_generated(script_id, video_url=video_url, video_chunk_urls=video_chunk_urls, audio_stats=audio_stats)
            clear_error(script_id)
            print("Done.")
        except Exception as e:
            # VERIFIER-GATE FIX (2026-08-22): assembly used to be
            # unprotected - any exception here (bad clip download, ffmpeg
            # failure, upload timeout, a shot duration far exceeding what
            # chaining can cover, etc.) propagated all the way up through
            # process_script and main(), crashing the ENTIRE run before any
            # other candidate script got a turn. This is the confirmed
            # cause of 177 straight failed Video Generation runs even
            # though per-shot clip generation itself was working fine. The
            # real exception is now recorded to scripts.last_error /
            # last_error_at so the actual cause is visible directly in
            # Supabase, the run keeps going, and this script just retries
            # assembly again next run instead of blocking every other
            # script in the queue.
            error_text = traceback.format_exc()
            print(f"Assembly FAILED for script {script_id} - recording error and moving on: {e}")
            record_error(script_id, error_text)

    return shots_used


def main():
    candidates = get_ready_scripts(CANDIDATE_POOL_SIZE)
    if not candidates:
        print("No scripts with images ready for video generation. Nothing to do.")
        return

    remaining_budget = CLIP_BATCH_LIMIT
    any_progress = False

    for script in candidates:
        if remaining_budget <= 0:
            print(f"Per-run shot budget ({CLIP_BATCH_LIMIT}) fully used - stopping here to respect Agnes's "
                  f"quota ceiling. Remaining candidates get their turn on the next scheduled run.")
            break

        try:
            shots_used = process_script(script, shot_limit=remaining_budget)
        except Exception as e:
            # VERIFIER-GATE FIX (2026-08-22): a crash ANYWHERE inside
            # process_script (not just assembly) used to kill this whole
            # run, leaving every other queued script untouched until the
            # next cron tick. Catching here means one broken script can
            # never block the rest of the batch again - the real exception
            # is still recorded to last_error for diagnosis.
            error_text = traceback.format_exc()
            print(f"Unexpected error processing script {script['id']} - recording error and moving to next candidate: {e}")
            record_error(script['id'], error_text)
            shots_used = 0

        if shots_used > 0:
            any_progress = True
            remaining_budget -= shots_used
            print(f"Script {script['id']} used {shots_used} shot(s) this run - {remaining_budget} left in this run's shared budget.")
        else:
            print(f"No progress on script {script['id']} this run (overloaded, content-flagged, or already "
                  f"fully assembled) - trying the next candidate with the same remaining budget.")

    if not any_progress:
        print(f"No progress possible on any of the {len(candidates)} candidate scripts this run "
              f"(all stalled or not ready) - next scheduled run will retry.")


if __name__ == "__main__":
    main()
