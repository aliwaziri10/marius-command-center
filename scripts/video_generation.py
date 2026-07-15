"""
Marius Command Center - Video Generation Agent
Takes the oldest script with images generated and generates one real AI
video clip per shot using Agnes AI, sized to match narration timing, then
assembles the final video with a 3-layer audio mix: narration, background
score, and SFX.

RESUME-SAFE: generated clips are uploaded to storage and recorded in
video_urls/video_next_index after every single shot, so a run that gets
cut off (timeout, crash, manual stop) picks up exactly where it left off
on the next run instead of regenerating finished shots.

QUOTA-SAFE: Agnes's free tier appears to silently repeat/stale past a
per-run quota ceiling, so each run generates at most CLIP_BATCH_LIMIT new
clips then stops cleanly. The resume logic above picks up the rest on the
next scheduled run.

RETRY-SAFE: create_agnes_task retries transient backend errors (429 rate
limit, 500/502/503/504 server-side issues) with backoff before giving up,
so a single flaky Agnes response doesn't kill the whole run. Clip
verification (HEAD checks on already-generated shots) also retries before
concluding a shot is genuinely broken, so a single transient network
blip doesn't discard already-finished work.

CONTENT-POLICY-RESILIENT: if Agnes rejects a shot's prompt on content-
policy grounds, this now auto-retries ONCE with a generic, stripped-down
fallback prompt (shot_type/camera fields only, no freeform visual_description
text) before giving up on the shot. If the fallback is ALSO rejected, the
script is marked status='content_flagged' (not left at 'images_generated')
and the run moves on to the next-oldest eligible script instead of crash-
looping on the same one forever. A flagged script is invisible to future
runs until its status is manually changed back - review shot_list in the
scripts table, reword the offending shot, and reset status to
'images_generated' to resume it.

ACE-MUSIC-RESILIENT: ACE Music's free hosted API has had reported
reliability issues (endpoint 404s/502s). generate_background_music now
tries every host in ACE_MUSIC_BASES in order and only skips background
music entirely if all of them fail, instead of giving up on the first
error.
"""

import os
import json
import time
import base64
import requests
import numpy as np
from moviepy import (
    VideoFileClip,
    AudioFileClip,
    CompositeAudioClip,
    concatenate_videoclips,
    concatenate_audioclips,
)
from moviepy.video.fx import FadeIn, FadeOut
from moviepy.audio.fx import AudioFadeIn, AudioFadeOut

FADE_IN_SECONDS = 0.75
FADE_OUT_SECONDS = 1.5
TRAIL_SECONDS = 3.0  # extra hold at the very end so ambient/music keeps
                      # breathing and fades out naturally instead of
                      # cutting hard the instant narration ends

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SECRET_KEY"]
AGNES_API_KEY = os.environ["AGNES_API_KEY"]
FREESOUND_API_KEY = os.environ.get("FREESOUND_API_KEY")
ACE_MUSIC_API_KEY = os.environ.get("ACE_MUSIC_API_KEY")

HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
}

AGNES_BASE = "https://apihub.agnes-ai.com/v1"
AGNES_POLL_URL = "https://apihub.agnes-ai.com/agnesapi"
AGNES_HEADERS = {
    "Authorization": f"Bearer {AGNES_API_KEY}",
    "Content-Type": "application/json",
}

# Try both known ACE Music hosts in order; only give up on background
# music if every host in this list fails.
ACE_MUSIC_BASES = ["https://api.acemusic.ai", "https://ai.acemusic.ai"]
ACE_MUSIC_HEADERS = {
    "Authorization": f"Bearer {ACE_MUSIC_API_KEY}",
    "Content-Type": "application/json",
}

VIDEO_BUCKET = "videos"
CLIP_BUCKET = "video_clips"  # individual shot clips, kept until final assembly
WIDTH, HEIGHT = 1152, 768
FRAME_RATE = 24
MIN_FRAMES = 49   # 8*6+1, ~2s - Agnes requires num_frames = 8*n+1
MAX_FRAMES = 169  # 8*21+1, ~7s

CLIP_BATCH_LIMIT = 8  # max new clips generated per run - stay under Agnes's free-tier quota

MUSIC_VOLUME = 0.34   # was 0.238 (+20% from 0.198 per Zarah's request) - bumped
                       # further per Zia's "louder ambient/music" request. Safe to
                       # push higher: apply_safety_limiter below auto-scales the
                       # WHOLE mix down if the true peak would exceed LIMITER_CEILING,
                       # so this cannot cause clipping even at this level.
SFX_VOLUME = 1.0      # capped at source loudness - 0.935+20% would exceed 1.0 and risk clipping/distortion
LIMITER_CEILING = 0.98  # safety cap on the fully mixed audio (narration + music + SFX
                         # combined) - individual layer volumes staying under 1.0 doesn't
                         # guarantee the mix does when loud moments overlap, so this checks
                         # the actual mixed peak and scales down only if it would clip

AGNES_RETRYABLE_CODES = {429, 500, 502, 503, 504}
AGNES_MAX_RETRIES = 4

CLIP_VERIFY_RETRIES = 3
CLIP_VERIFY_RETRY_WAIT = 5


class ContentPolicyRejection(Exception):
    """Raised when Agnes rejects a shot's prompt on content-policy
    grounds, so the caller can print a clear, actionable message instead
    of letting a raw HTTPError/traceback be the only signal."""
    pass


def round_to_valid_frames(num_frames):
    n = round((num_frames - 1) / 8)
    n = max(0, n)
    return 8 * n + 1


def get_next_ready_script():
    resp = requests.get(
        f"{SUPABASE_URL}/rest/v1/scripts?status=eq.images_generated&order=created_at.asc&limit=1",
        headers=HEADERS,
        timeout=30,
    )
    resp.raise_for_status()
    rows = resp.json()
    return rows[0] if rows else None


def download_file(url, out_path):
    r = requests.get(url, timeout=120)
    r.raise_for_status()
    with open(out_path, "wb") as f:
        f.write(r.content)
    return out_path


def build_agnes_prompt(shot, use_fallback=False):
    """Fold the Cinematic Director's shot_type/camera_movement/lens_effect
    into the Agnes prompt so the generated clip actually reflects the
    intended camera work, not just the raw visual description.

    use_fallback=True builds a generic, content-safe prompt with NO
    freeform visual_description text at all - used as a one-time retry
    when the real prompt gets rejected on content-policy grounds, since
    we can't know in advance which word/phrase triggered the rejection."""
    shot_type = (shot.get("shot_type") or "medium").replace("_", " ")
    camera_movement = (shot.get("camera_movement") or "static").replace("_", " ")
    lens_effect = shot.get("lens_effect") or "none"

    if use_fallback:
        parts = [f"{shot_type} cinematic documentary shot"]
    else:
        visual = shot.get("visual_description", "").strip()
        parts = [visual, f"{shot_type} shot"]

    if camera_movement != "static":
        parts.append(f"camera {camera_movement}")
    if lens_effect != "none":
        parts.append(lens_effect.replace("_", " "))

    return ", ".join(p for p in parts if p)


def create_agnes_task(prompt, num_frames):
    """Retries on transient Agnes/backend errors (429 rate limit, 500/502/
    503/504 server-side issues) with backoff before raising - one flaky
    response from Agnes should not kill the whole run and force a manual
    re-trigger. Raises ContentPolicyRejection distinctly (not retryable)
    if Agnes rejects the prompt on content grounds."""
    last_error_text = None

    for attempt in range(AGNES_MAX_RETRIES):
        resp = requests.post(
            f"{AGNES_BASE}/videos",
            headers=AGNES_HEADERS,
            json={
                "model": "agnes-video-v2.0",
                "prompt": prompt,
                "height": HEIGHT,
                "width": WIDTH,
                "num_frames": num_frames,
                "frame_rate": FRAME_RATE,
            },
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

    raise RuntimeError(f"Agnes still failing after {AGNES_MAX_RETRIES} attempts: {last_error_text}")


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
    raise RuntimeError(f"Agnes generation timed out after {max_wait}s for video_id {video_id}")


def generate_shot_clip(shot, target_duration, out_path):
    """Generates one shot's clip. On content-policy rejection, retries
    ONCE with a generic fallback prompt (no freeform text) before giving
    up - this recovers most false-positive rejections automatically
    without ever touching the story/shot data."""
    raw_frames = int(target_duration * FRAME_RATE)
    raw_frames = max(MIN_FRAMES, min(MAX_FRAMES, raw_frames))
    num_frames = round_to_valid_frames(raw_frames)
    num_frames = max(MIN_FRAMES, min(MAX_FRAMES, num_frames))

    prompt = build_agnes_prompt(shot, use_fallback=False)
    try:
        video_id = create_agnes_task(prompt, num_frames)
    except ContentPolicyRejection:
        print("Content policy rejection on primary prompt - retrying once with a generic fallback prompt...")
        fallback_prompt = build_agnes_prompt(shot, use_fallback=True)
        video_id = create_agnes_task(fallback_prompt, num_frames)  # let this one raise if it also fails

    video_url = poll_agnes_task(video_id)
    download_file(video_url, out_path)
    return out_path


def fit_clip_to_duration(clip, target):
    """Fits a generated clip to its target duration. If the clip is
    already long enough, trims it. If it's shorter, extends it by
    freezing the last frame and holding it for the remaining time -
    NOT by looping/repeating the clip from the start, which reads as an
    obvious, jarring restart. A held final frame is invisible to the
    viewer."""
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
    """Marks a script content_flagged instead of leaving it at
    images_generated, so get_next_ready_script skips it on all future
    runs and moves on to the next-oldest eligible script instead of
    crash-looping on the same blocked script forever. Zia (or Claude)
    reviews shot_list, rewords the offending shot, then manually resets
    status back to 'images_generated' to resume it."""
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


def compute_shot_start_times(shot_durations):
    starts = []
    t = 0.0
    for d in shot_durations:
        starts.append(t)
        t += d
    return starts


def compute_target_bitrate(duration_seconds, target_mb=42, audio_kbps=128):
    """Pick a video bitrate so the final file lands under the 50MB
    Supabase free-tier cap, leaving 8MB headroom, regardless of length."""
    target_bits = target_mb * 8 * 1024 * 1024
    audio_bits = audio_kbps * 1000 * duration_seconds
    video_bits = max(target_bits - audio_bits, 300_000 * duration_seconds)
    return f"{int(video_bits / duration_seconds / 1000)}k"


# ---------------------------------------------------------------------------
# Sound Designer: background score (ACE Music) + SFX (Freesound)
# ---------------------------------------------------------------------------

def poll_ace_music_task(task_id, out_path, base_url=None, max_wait=180, interval=8):
    """Polls ACE Music task status via POST /query_result, per the real
    ACE-Step API (a task created by POST /release_task returns a task_id,
    queried via POST task_id_list - not GET /v1/jobs/{job_id}).

    base_url must be the same host that /release_task was called on -
    passed in explicitly since generate_background_music now tries
    multiple hosts and must poll/download from whichever one accepted
    the task."""
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


def generate_background_music(prompt, duration, out_path):
    """Generates the episode's background score via POST /release_task,
    polled via POST /query_result. Tries every host in ACE_MUSIC_BASES in
    order and only gives up (returns None, skipping music for this
    episode) if every host fails - ACE Music's free hosted API has had
    reported reliability issues on individual hosts, so a single 404/502
    on one host should not silently kill background music forever."""
    if not ACE_MUSIC_API_KEY:
        print("No ACE_MUSIC_API_KEY set - skipping background music.")
        return None

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
                print(f"ACE MUSIC ERROR ({base}) {resp.status_code}: {resp.text}")
                continue
            task_id = resp.json().get("data", {}).get("task_id")
            if not task_id:
                print(f"ACE Music response had no task_id ({base}): {resp.json()}")
                continue
            result = poll_ace_music_task(task_id, out_path, base_url=base)
            if result:
                return result
        except Exception as e:
            print(f"ACE Music generation raised an exception on {base}, trying next host
