"""
Marius Command Center - beat director (2026-09-19).

PROBLEM: a shot longer than one Agnes generation (MAX_CLIP_SECONDS, ~7s) is
produced by chaining extension segments in clip_generation.generate_shot_clip.
Every segment used the SAME prompt (same visual_description, camera,
shot_type) with only the last-frame image anchor changing, so a 16s shot
played as the same ~7s moment repeated 2-3 times.

FIX: for a shot that actually needs chaining, ask Gemini once for N short
follow-on "beats" (one per chain segment): a concrete continuation action
plus a different camera_movement / shot_type for each. clip_generation
swaps the beat into a copy of the shot for that segment only.

FAIL-SOFT BY DESIGN: every failure path (no GEMINI_API_KEY, network error,
bad JSON, wrong beat count, modern-object keyword, anything else) returns
None, and clip_generation then behaves exactly as it did before this file
existed. Bounded: 2 attempts x 45s max, never the long retry loops in
llm_client.call_llm, so it cannot eat the workflow's 60-minute budget.
"""

import os
import time
import requests

from llm_client import extract_json, GEMINI_MODEL

BEAT_CALL_TIMEOUT_SECONDS = 45
BEAT_CALL_ATTEMPTS = 2
BEAT_RETRY_WAIT_SECONDS = 4
MIN_ACTION_CHARS = 20
MAX_ACTION_CHARS = 450

VALID_SHOT_TYPES = {
    "wide", "medium", "close_up", "extreme_close_up", "establishing", "detail_insert",
}
VALID_CAMERA_MOVEMENTS = {
    "static", "pan_left", "pan_right", "tilt_up", "tilt_down", "zoom_in", "zoom_out",
    "push_in", "pull_out", "dolly_in", "dolly_out", "tracking", "crash_zoom",
    "whip_pan", "handheld_shake", "orbit", "drone_rise", "drone_descend",
    "parallax", "focus_pull", "dutch_angle", "snap_zoom", "speed_ramp",
}

ROTATION_MOVEMENTS = [
    "pan_right", "tracking", "pull_out", "orbit", "tilt_up", "dolly_out", "parallax", "pan_left",
]

MODERN_OBJECT_KEYWORDS = (
    "laptop", "computer", "smartphone", "cell phone", "cellphone", "mobile phone",
    "iphone", "tablet", "ipad", "drone", "screen", "monitor", "led ", "usb",
    "bluetooth", "wifi", "cctv", "security camera", "plastic",
)


def _build_prompt(shot, setting_and_characters, num_beats):
    return f"""You are the shot director for a period documentary. One shot is
too long for a single AI video generation, so it is being produced as a
chain of {num_beats + 1} consecutive clips. Clip 1 is already fixed (below).
Write {num_beats} follow-on beats, one per remaining clip, in order.

SETTING AND CHARACTERS (fixed, do not contradict):
{setting_and_characters}

CLIP 1 (already generated):
- visual_description: {shot.get("visual_description", "")}
- narration_excerpt: {shot.get("narration_excerpt", "")}
- shot_type: {shot.get("shot_type", "medium")}
- camera_movement: {shot.get("camera_movement", "static")}
- lighting: {shot.get("lighting", "midday")}

RULES FOR EVERY BEAT:
- Same location, same era, same lighting, same people as clip 1. No new
  named characters, no new locations, no modern objects of any kind.
- "action": 1-2 sentences describing what the frame shows AS a natural,
  already-in-progress continuation of the previous clip's final moment.
  It must add something visibly NEW (a different detail, object, person's
  action, or part of the space) - never repeat the previous beat.
- Each beat uses a DIFFERENT camera_movement than the beat before it and
  than clip 1. Vary shot_type too.
- camera_movement must be one of: {", ".join(sorted(VALID_CAMERA_MOVEMENTS))}
- shot_type must be one of: {", ".join(sorted(VALID_SHOT_TYPES))}

Return ONLY valid JSON, no markdown fences, exactly this shape:
{{"beats": [{{"action": "...", "camera_movement": "pan_right", "shot_type": "medium"}}]}}
with exactly {num_beats} items in "beats"."""


def _call_gemini_once(prompt):
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise RuntimeError("GEMINI_API_KEY not set in this workflow's env")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"
    resp = requests.post(
        url,
        headers={"Content-Type": "application/json", "x-goog-api-key": key},
        json={
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"responseMimeType": "application/json", "maxOutputTokens": 2048},
        },
        timeout=BEAT_CALL_TIMEOUT_SECONDS,
    )
    resp.raise_for_status()
    return resp.json()["candidates"][0]["content"]["parts"][0]["text"]


def _validate_beats(parsed, num_beats, first_camera):
    beats = parsed.get("beats") if isinstance(parsed, dict) else None
    if not isinstance(beats, list) or len(beats) != num_beats:
        return None

    out = []
    prev_move = first_camera
    for i, b in enumerate(beats):
        if not isinstance(b, dict):
            return None
        action = (b.get("action") or "").strip()
        if not (MIN_ACTION_CHARS <= len(action) <= MAX_ACTION_CHARS):
            return None
        low = action.lower()
        if any(kw in low for kw in MODERN_OBJECT_KEYWORDS):
            return None

        move = b.get("camera_movement")
        if move not in VALID_CAMERA_MOVEMENTS:
            move = ROTATION_MOVEMENTS[i % len(ROTATION_MOVEMENTS)]
        if move == prev_move:
            move = next(m for m in ROTATION_MOVEMENTS[i % len(ROTATION_MOVEMENTS):] + ROTATION_MOVEMENTS if m != prev_move)

        stype = b.get("shot_type")
        if stype not in VALID_SHOT_TYPES:
            stype = "medium"

        out.append({"action": action, "camera_movement": move, "shot_type": stype})
        prev_move = move
    return out


def author_chain_beats(shot, setting_and_characters, num_beats):
    """Returns a list of exactly num_beats dicts
    ({"action", "camera_movement", "shot_type"}) or None on ANY failure."""
    try:
        if num_beats <= 0:
            return None
        prompt = _build_prompt(shot, setting_and_characters or "", num_beats)
        first_camera = shot.get("camera_movement") or "static"

        for attempt in range(BEAT_CALL_ATTEMPTS):
            try:
                raw = _call_gemini_once(prompt)
                beats = _validate_beats(extract_json(raw), num_beats, first_camera)
                if beats:
                    print(f"[beat_director] authored {len(beats)} chain beat(s) for this shot.")
                    return beats
                print(f"[beat_director] attempt {attempt + 1}/{BEAT_CALL_ATTEMPTS}: response failed validation.")
            except Exception as e:
                print(f"[beat_director] attempt {attempt + 1}/{BEAT_CALL_ATTEMPTS} failed ({e.__class__.__name__}).")
            if attempt < BEAT_CALL_ATTEMPTS - 1:
                time.sleep(BEAT_RETRY_WAIT_SECONDS)
    except Exception as e:
        print(f"[beat_director] unexpected error ({e.__class__.__name__}).")

    print("[beat_director] falling back to the original repeated-prompt chain behavior for this shot.")
    return None


def apply_beat_to_shot(shot, beat):
    """Returns a COPY of shot with the beat's action/camera/shot_type swapped
    in. Every other field (lighting, lens_effect, ...) is left untouched."""
    chained = dict(shot)
    chained["visual_description"] = beat["action"]
    chained["camera_movement"] = beat["camera_movement"]
    chained["shot_type"] = beat["shot_type"]
    return chained
