"""
Marius Command Center - clip generation.

SCENE-BY-SCENE REWRITE (2026-09-19): a shot longer than one Agnes clip
(~7s) used to be filled by chaining continuation clips, each started from
the previous clip's last frame with the SAME prompt. Confirmed live on
script e086c4f2 (30 shots, avg 27s, max 45s): that repeated the same
action every ~7s, made people vanish/duplicate, and carried the
protagonist into every frame.

Now every ~7s clip is its own "beat" with its own instruction from
scene_director.py, generated as a fresh text-to-video cut (no image
anchor, no last-frame chaining). Number of Agnes calls per shot is the
same as before, so no extra credit cost.

get_continuity_anchor / extract_last_frame_url are kept (video_generation.py
still calls them) but intentionally return None.
"""

import os
import math
import time
import hashlib
import requests
from moviepy import VideoFileClip, concatenate_videoclips

import storage_b2
from agnes_client import (
    AGNES_HEADERS,
    AGNES_IMAGE_URL,
    AGNES_RETRYABLE_CODES,
    AGNES_IMAGE_MAX_RETRIES,
    WIDTH,
    HEIGHT,
    FRAME_RATE,
    MIN_FRAMES,
    MAX_FRAMES,
    MAX_CLIP_SECONDS,
    ContentPolicyRejection,
    AgnesOverloadedError,
    round_to_valid_frames,
    create_agnes_task,
    poll_agnes_task,
)
from prompt_builder import build_character_reference_prompt
from scene_director import build_beat_prompt, beat_kind, NEGATIVE_PROMPT_V2

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SECRET_KEY"]

HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
}

# Max beats (Agnes clips) per shot: 1 main + 6 extra, same ceiling as before.
MAX_CHAIN_SEGMENTS = 6
MAX_BEATS = MAX_CHAIN_SEGMENTS + 1


def _derive_seed(script_id, shot_index, variant=0):
    """Deterministic per-(script, shot, variant) seed so a resumed shot
    reproduces the same result. Returns None if ids are missing."""
    if script_id is None or shot_index is None:
        return None
    digest = hashlib.md5(f"{script_id}:{shot_index}:{variant}".encode()).hexdigest()
    return int(digest[:8], 16)


def download_file(url, out_path):
    r = requests.get(url, timeout=120)
    r.raise_for_status()
    with open(out_path, "wb") as f:
        f.write(r.content)
    return out_path


def upload_reference_image(script_id, file_name, local_path):
    """Returns the B2 object KEY (not a URL)."""
    dest = f"{script_id}/refs/{file_name}"
    try:
        return storage_b2.upload_file(dest, local_path, content_type="image/png")
    except Exception as e:
        print(f"Reference frame upload failed: {e}")
        return None


def generate_character_reference(script):
    """Kept for compatibility. No longer called by the pipeline (image
    anchoring is disabled - see module docstring)."""
    script_id = script["id"]
    existing = script.get("character_reference_url")
    if existing:
        return existing

    anchor = (script.get("setting_and_characters") or "").strip()
    if not anchor:
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
            time.sleep(10 * (attempt + 1))
            continue

        if resp.status_code in AGNES_RETRYABLE_CODES:
            last_error_text = resp.text
            time.sleep(10 * (attempt + 1))
            continue

        if resp.status_code >= 400:
            print(f"Character reference image failed permanently ({resp.status_code}): {resp.text}")
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
            return None

        resp2 = requests.patch(
            f"{SUPABASE_URL}/rest/v1/scripts?id=eq.{script_id}",
            headers=HEADERS,
            json={"character_reference_url": image_url},
            timeout=30,
        )
        resp2.raise_for_status()
        return image_url

    print(f"Character reference image exhausted retries ({last_error_text}).")
    return None


def extract_last_frame_url(script_id, shot_index, local_video_path):
    """Intentionally returns None: cross-shot last-frame anchoring is off,
    every shot starts as an independent documentary cut."""
    return None


def get_continuity_anchor(script, video_urls):
    """Intentionally returns None (text-to-video only, no image anchor)."""
    return None


def _generate_one_segment(shot, segment_duration, out_path, setting_and_characters="",
                          seed=None, beat_index=0, shot_index=0):
    raw_frames = int(segment_duration * FRAME_RATE)
    raw_frames = max(MIN_FRAMES, min(MAX_FRAMES, raw_frames))
    num_frames = round_to_valid_frames(raw_frames)
    num_frames = max(MIN_FRAMES, min(MAX_FRAMES, num_frames))

    prompt = build_beat_prompt(shot, setting_and_characters, beat_index, shot_index, fallback_level=0)
    print(f"  PROMPT (beat {beat_index + 1}, first 500 chars): {prompt[:500]}")
    try:
        video_id = create_agnes_task(prompt, num_frames, image_url=None,
                                     negative_prompt=NEGATIVE_PROMPT_V2, seed=seed)
    except ContentPolicyRejection:
        print("Content policy rejection on primary prompt - retrying with sanitized fallback (tier 1)...")
        try:
            fallback_prompt = build_beat_prompt(shot, setting_and_characters, beat_index, shot_index, fallback_level=1)
            video_id = create_agnes_task(fallback_prompt, num_frames, image_url=None,
                                         negative_prompt=NEGATIVE_PROMPT_V2, seed=seed)
        except ContentPolicyRejection:
            print("Tier 1 also rejected - retrying with fully generic prompt (tier 2)...")
            ultra_prompt = build_beat_prompt(shot, setting_and_characters, beat_index, shot_index, fallback_level=2)
            video_id = create_agnes_task(ultra_prompt, num_frames, image_url=None,
                                         negative_prompt=NEGATIVE_PROMPT_V2, seed=seed)

    video_url = poll_agnes_task(video_id)
    download_file(video_url, out_path)
    return out_path


def generate_shot_clip(shot, target_duration, out_path, setting_and_characters="",
                       anchor_image_url=None, script_id=None, shot_index=None):
    idx = shot_index or 0
    total_beats = max(1, min(MAX_BEATS, math.ceil(target_duration / MAX_CLIP_SECONDS)))
    beat_duration = min(MAX_CLIP_SECONDS, target_duration / total_beats)

    kinds = [beat_kind(shot, b) for b in range(total_beats)]
    print(f"Shot {idx + 1}: {target_duration:.1f}s -> {total_beats} beat(s) of ~{beat_duration:.1f}s, plan: {kinds}")

    # Beat 0 errors propagate (content flag / stall / overload handling in
    # video_generation.py depends on that).
    _generate_one_segment(
        shot, beat_duration, out_path, setting_and_characters,
        seed=_derive_seed(script_id, shot_index, variant=0),
        beat_index=0, shot_index=idx,
    )

    if total_beats == 1:
        return out_path

    beat_paths = [out_path]
    for beat in range(1, total_beats):
        beat_out = out_path.replace(".mp4", f"_beat{beat}.mp4")
        ok = False
        last_err = None
        for attempt in range(3):
            try:
                _generate_one_segment(
                    shot, beat_duration, beat_out, setting_and_characters,
                    seed=_derive_seed(script_id, shot_index, variant=f"beat{beat}-{attempt}"),
                    beat_index=beat, shot_index=idx,
                )
                ok = True
                break
            except Exception as e:
                last_err = e
                if attempt < 2:
                    print(f"Beat {beat + 1} failed on attempt {attempt + 1}/3 ({e}) - retrying.")
                    time.sleep(6)
        if not ok:
            print(f"Beat {beat + 1} failed after retries ({last_err}) - freeze-holding the remainder of this shot.")
            break
        beat_paths.append(beat_out)

    clips = [VideoFileClip(p) for p in beat_paths]
    combined = concatenate_videoclips(clips, method="compose")

    if target_duration - combined.duration > 0.05:
        combined = fit_clip_to_duration(combined, target_duration)

    tmp_path = out_path.replace(".mp4", "_extended.mp4")
    combined.write_videofile(tmp_path, fps=FRAME_RATE, codec="libx264", audio=False, threads=2, logger=None)
    for c in clips:
        c.close()
    for p in beat_paths[1:]:
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
