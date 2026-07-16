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
import math
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
MAX_CLIP_SECONDS = MAX_FRAMES / FRAME_RATE  # ~7.04s - hard cap per single Agnes generation

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


def _generate_one_segment(shot, segment_duration, out_path):
    """Generates a single Agnes clip no longer than MAX_CLIP_SECONDS. On
    content-policy rejection, retries ONCE with a generic fallback prompt
    before giving up."""
    raw_frames = int(segment_duration * FRAME_RATE)
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


def generate_shot_clip(shot, target_duration, out_path):
    """Generates a shot's full clip. Agnes hard-caps any single generation
    at ~MAX_CLIP_SECONDS. Shots needing MORE than that are now split into
    multiple back-to-back Agnes generations and stitched together with
    concatenate_videoclips, instead of generating one short clip and
    freezing the last frame to pad out the remaining time - eliminates
    the multi-second freeze-frame stretches that were showing up on any
    shot with longer narration."""
    n_segments = max(1, math.ceil(target_duration / MAX_CLIP_SECONDS))
    segment_duration = target_duration / n_segments

    if n_segments == 1:
        return _generate_one_segment(shot, segment_duration, out_path)

    print(f"Shot needs {target_duration:.1f}s (over the ~{MAX_CLIP_SECONDS:.1f}s per-generation cap) - "
          f"generating {n_segments} clips of ~{segment_duration:.1f}s each and stitching, instead of freezing.")

    segment_paths = []
    for seg in range(n_segments):
        seg_path = out_path.replace(".mp4", f"_seg{seg}.mp4")
        _generate_one_segment(shot, segment_duration, seg_path)
        segment_paths.append(seg_path)
        if seg < n_segments - 1:
            time.sleep(4)  # brief pause between back-to-back submissions for the same shot

    clips = [VideoFileClip(p) for p in segment_paths]
    stitched = concatenate_videoclips(clips, method="compose")
    stitched.write_videofile(out_path, fps=FRAME_RATE, codec="libx264", audio=False, threads=2, logger=None)
    for c in clips:
        c.close()
    for p in segment_paths:
        os.remove(p)

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


def get_shot_durations(script, shot_list, audio_clip):
    """Prefers the REAL per-shot durations already computed and saved by
    narration.py in the shot_durations DB column (accurate to the actual
    narration audio, so clip cuts land on sentence ends). Only falls back
    to the old text-length-weighted estimate if shot_durations is missing
    or doesn't match the current shot_list (e.g. older scripts generated
    before this column existed)."""
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
            print(f"ACE Music generation raised an exception on {base}, trying next host: {e}")

    print("Continuing without background music - every ACE Music host failed this run.")
    return None


def search_freesound_sfx(query, out_path):
    """Finds and downloads a short SFX clip matching the cue. Returns None
    (and logs) on any failure so a bad SFX cue never breaks the whole run."""
    if not FREESOUND_API_KEY:
        print("No FREESOUND_API_KEY set - skipping SFX for this cue.")
        return None
    try:
        resp = requests.get(
            "https://freesound.org/apiv2/search/text/",
            params={
                "query": query,
                "token": FREESOUND_API_KEY,
                "fields": "id,previews",
                "filter": "duration:[0.1 TO 8]",
                "sort": "score",
                "page_size": 1,
            },
            timeout=30,
        )
        if resp.status_code >= 400:
            print(f"FREESOUND ERROR {resp.status_code}: {resp.text}")
            return None
        results = resp.json().get("results", [])
        if not results:
            print(f"No Freesound results for cue: {query}")
            return None
        previews = results[0].get("previews", {})
        preview_url = previews.get("preview-hq-mp3") or previews.get("preview-lq-mp3")
        if not preview_url:
            return None
        download_file(preview_url, out_path)
        return out_path
    except Exception as e:
        print(f"Freesound lookup failed for cue '{query}', skipping this SFX: {e}")
        return None


def apply_safety_limiter(audio_clip, ceiling=LIMITER_CEILING):
    """Checks the TRUE peak of the fully mixed audio (narration + music +
    SFX layers all summed together, as they'll actually play back) and
    scales the whole mix down only if that peak would exceed `ceiling`.

    Individual layer volumes staying under 1.0 does not guarantee the
    combined mix does - if narration, music, and an SFX cue all happen to
    peak at the same instant, their amplitudes add together and can exceed
    1.0 even though no single layer does on its own. That overshoot is
    exactly what causes audible clipping/distortion. This checks the real
    rendered peak instead of trusting the individual volume constants, and
    only scales down (never up) so quiet mixes are left untouched.

    Uses fps=44100 (CD-quality) for the peak scan - accurate enough to
    catch true peaks without being so high-resolution it meaningfully
    slows down the run."""
    samples = audio_clip.to_soundarray(fps=44100)
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


def build_audio_mix(narration_path, music_mood, shot_list, shot_durations, shot_starts, total_duration):
    """Composites 3 audio layers: narration (full volume), looped background
    score (ducked), and per-shot SFX placed at their exact timestamps."""
    layers = [AudioFileClip(narration_path)]

    if music_mood:
        music_path = "/tmp/background_music.mp3"
        if generate_background_music(music_mood, total_duration, music_path):
            music_clip = AudioFileClip(music_path)
            music_clip = fit_audio_to_duration(music_clip, total_duration)
            music_clip = music_clip.with_volume_scaled(MUSIC_VOLUME)
            layers.append(music_clip)

    for i, shot in enumerate(shot_list):
        cue = (shot.get("sfx_cue") or "").strip()
        if not cue:
            continue
        sfx_path = f"/tmp/sfx_{i:03d}.mp3"
        if search_freesound_sfx(cue, sfx_path):
            sfx_clip = AudioFileClip(sfx_path)
            max_len = shot_durations[i]
            if sfx_clip.duration > max_len:
                sfx_clip = sfx_clip.subclipped(0, max_len)
            sfx_clip = sfx_clip.with_volume_scaled(SFX_VOLUME).with_start(shot_starts[i])
            layers.append(sfx_clip)

    mixed = CompositeAudioClip(layers)
    return apply_safety_limiter(mixed)


def assemble_final_video(script_id, video_urls, narration_path, music_mood, shot_list, shot_durations, output_path):
    clips = []
    for i, url in enumerate(video_urls):
        raw_path = f"/tmp/final_shot_{i:03d}.mp4"
        download_file(url, raw_path)
        clip = VideoFileClip(raw_path)
        clip = clip.resized(new_size=(WIDTH, HEIGHT))
        clip = fit_clip_to_duration(clip, shot_durations[i])
        clips.append(clip)

    total_duration = sum(shot_durations)
    shot_starts = compute_shot_start_times(shot_durations)
    final_audio = build_audio_mix(
        narration_path, music_mood, shot_list, shot_durations, shot_starts, total_duration
    )

    final_audio = final_audio.with_effects(
        [AudioFadeIn(FADE_IN_SECONDS), AudioFadeOut(FADE_OUT_SECONDS)]
    )

    final = concatenate_videoclips(clips, method="compose")
    final = final.with_effects([FadeIn(FADE_IN_SECONDS), FadeOut(FADE_OUT_SECONDS)])
    final = final.with_audio(final_audio)
    target_bitrate = compute_target_bitrate(total_duration)
    print(f"Target video bitrate: {target_bitrate} (duration {total_duration:.1f}s)")
    final.write_videofile(
        output_path,
        fps=FRAME_RATE,
        codec="libx264",
        audio_codec="aac",
        audio_bitrate="128k",
        bitrate=target_bitrate,
        threads=2,
        logger=None,
    )
    return output_path


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
        },
        data=file_bytes,
        timeout=300,
    )
    if resp.status_code >= 400:
        print(f"Upload failed - status {resp.status_code}: {resp.text}")
    resp.raise_for_status()
    return f"{SUPABASE_URL}/storage/v1/object/public/{VIDEO_BUCKET}/{file_name}"


def mark_video_generated(script_id, video_url):
    resp = requests.patch(
        f"{SUPABASE_URL}/rest/v1/scripts?id=eq.{script_id}",
        headers=HEADERS,
        json={"status": "video_generated", "video_url": video_url},
        timeout=30,
    )
    resp.raise_for_status()


def main():
    script = get_next_ready_script()
    if not script:
        print("No scripts with images ready for video generation. Nothing to do.")
        return
    if not script.get("narration_url"):
        print("Script has no narration_url yet. Skipping.")
        return

    script_id = script["id"]
    print(f"Working on script {script_id}")

    shot_list = script["shot_list"]
    if isinstance(shot_list, str):
        shot_list = json.loads(shot_list)
    total_shots = len(shot_list)
    music_mood = script.get("music_mood") or ""

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

    if next_index >= total_shots:
        print(f"All {total_shots} shots already generated, video_urls has {len(video_urls)} entries. Skipping to assembly check.")
    else:
        audio_path = "/tmp/narration_audio"
        audio_path += ".mp3" if script["narration_url"].endswith(".mp3") else ".wav"
        download_file(script["narration_url"], audio_path)
        audio_clip = AudioFileClip(audio_path)
        shot_durations = get_shot_durations(script, shot_list, audio_clip)

        batch_end = min(next_index + CLIP_BATCH_LIMIT, total_shots)
        print(f"Resuming from shot {next_index + 1}/{total_shots} ({len(video_urls)} already done) - generating up to shot {batch_end} this run")

        for i in range(next_index, batch_end):
            shot = shot_list[i]
            raw_path = f"/tmp/shot_{i:03d}.mp4"
            print(f"Generating shot {i+1}/{total_shots} (~{shot_durations[i]:.1f}s)...")
            try:
                generate_shot_clip(shot, shot_durations[i], raw_path)
            except ContentPolicyRejection as e:
                mark_content_flagged(script_id, i, str(e))
                print(f"Rejected visual_description: {shot.get('visual_description', '')!r}")
                print(f"FIX: reword shot_list[{i}].visual_description for script {script_id} in the "
                      f"scripts table, then reset status to 'images_generated' to resume from exactly "
                      f"this shot. Moving on to the next-oldest eligible script for now.")
                return

            clip_url = upload_clip(script_id, i, raw_path)
            video_urls.append(clip_url)
            save_progress(script_id, video_urls, i + 1)
            print(f"Saved progress: {i + 1}/{total_shots} shots done")

            os.remove(raw_path)
            time.sleep(4)

        if batch_end < total_shots:
            print(f"Batch limit reached ({CLIP_BATCH_LIMIT} clips this run). {total_shots - batch_end} shots remain - resuming on the next scheduled run.")
            return

    if len(video_urls) >= total_shots:
        print("All shots done. Assembling final video...")
        audio_path = "/tmp/narration_audio_final"
        audio_path += ".mp3" if script["narration_url"].endswith(".mp3") else ".wav"
        download_file(script["narration_url"], audio_path)
        audio_clip = AudioFileClip(audio_path)
        shot_durations = get_shot_durations(script, shot_list, audio_clip)
        shot_durations[-1] += TRAIL_SECONDS  # hold the final shot a bit longer so
                                              # the music/ambient bed fades out
                                              # naturally instead of cutting off

        output_path = "/tmp/final_video.mp4"
        assemble_final_video(script_id, video_urls, audio_path, music_mood, shot_list, shot_durations, output_path)

        video_url = upload_video(script_id, output_path)
        print(f"Uploaded: {video_url}")

        mark_video_generated(script_id, video_url)
        print("Done.")


if __name__ == "__main__":
    main()
