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
"""

import os
import json
import time
import base64
import requests
from moviepy import (
    VideoFileClip,
    AudioFileClip,
    CompositeAudioClip,
    concatenate_videoclips,
    concatenate_audioclips,
)

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

ACE_MUSIC_BASE = "https://api.acemusic.ai"
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

MUSIC_VOLUME = 0.18
SFX_VOLUME = 0.85


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


def build_agnes_prompt(shot):
    """Fold the Cinematic Director's shot_type/camera_movement/lens_effect
    into the Agnes prompt so the generated clip actually reflects the
    intended camera work, not just the raw visual description."""
    visual = shot.get("visual_description", "").strip()
    shot_type = (shot.get("shot_type") or "medium").replace("_", " ")
    camera_movement = (shot.get("camera_movement") or "static").replace("_", " ")
    lens_effect = shot.get("lens_effect") or "none"

    parts = [visual, f"{shot_type} shot"]
    if camera_movement != "static":
        parts.append(f"camera {camera_movement}")
    if lens_effect != "none":
        parts.append(lens_effect.replace("_", " "))

    return ", ".join(p for p in parts if p)


def create_agnes_task(prompt, num_frames):
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
    if resp.status_code >= 400:
        print(f"AGNES ERROR {resp.status_code}: {resp.text}")
    resp.raise_for_status()
    data = resp.json()
    return data.get("video_id") or data.get("id") or data.get("task_id")


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
    prompt = build_agnes_prompt(shot)
    raw_frames = int(target_duration * FRAME_RATE)
    raw_frames = max(MIN_FRAMES, min(MAX_FRAMES, raw_frames))
    num_frames = round_to_valid_frames(raw_frames)
    num_frames = max(MIN_FRAMES, min(MAX_FRAMES, num_frames))

    video_id = create_agnes_task(prompt, num_frames)
    video_url = poll_agnes_task(video_id)
    download_file(video_url, out_path)
    return out_path


def fit_clip_to_duration(clip, target):
    if clip.duration >= target:
        return clip.subclipped(0, target)
    reps = int(target // clip.duration) + 1
    looped = concatenate_videoclips([clip] * reps)
    return looped.subclipped(0, target)


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

def poll_ace_music_task(job_id, out_path, max_wait=180, interval=8):
    """Polls ACE Music job status via GET /v1/jobs/{job_id}, per the
    documented ACE-Step API (job created by POST /v1/music/generate
    returns a job_id, not a task_id)."""
    waited = 0
    while waited < max_wait:
        resp = requests.get(
            f"{ACE_MUSIC_BASE}/v1/jobs/{job_id}",
            headers=ACE_MUSIC_HEADERS,
            timeout=30,
        )
        if resp.status_code >= 400:
            print(f"ACE MUSIC POLL ERROR {resp.status_code}: {resp.text}")
            return None
        data = resp.json()
        status = data.get("status")
        if status in ("completed", "SUCCESS", "success", "succeeded", "SUCCEEDED"):
            url = data.get("audio_url") or data.get("url")
            if url:
                download_file(url, out_path)
                return out_path
            b64 = data.get("audio_base64") or data.get("audio")
            if b64:
                with open(out_path, "wb") as f:
                    f.write(base64.b64decode(b64))
                return out_path
            print(f"ACE Music task completed but no audio field found: {list(data.keys())}")
            return None
        if status in ("failed", "FAILED", "ERROR", "error"):
            print(f"ACE Music task failed: {data}")
            return None
        time.sleep(interval)
        waited += interval
    print(f"ACE Music job {job_id} timed out after {max_wait}s")
    return None


def generate_background_music(prompt, duration, out_path):
    """Generates the episode's background score via POST /v1/music/generate,
    which returns a job_id polled via GET /v1/jobs/{job_id}. Fails
    gracefully: returns None instead of crashing the whole video."""
    if not ACE_MUSIC_API_KEY:
        print("No ACE_MUSIC_API_KEY set - skipping background music.")
        return None
    try:
        resp = requests.post(
            f"{ACE_MUSIC_BASE}/v1/music/generate",
            headers=ACE_MUSIC_HEADERS,
            json={
                "prompt": prompt,
                "duration": min(int(duration) + 5, 600),
                "instrumental": True,
            },
            timeout=120,
        )
        if resp.status_code >= 400:
            print(f"ACE MUSIC ERROR {resp.status_code}: {resp.text}")
            print("Continuing without background music - check the error above and fix the endpoint/fields.")
            return None
        data = resp.json()

        audio_url = data.get("audio_url") or data.get("url")
        if audio_url:
            download_file(audio_url, out_path)
            return out_path

        b64 = data.get("audio_base64") or data.get("audio")
        if b64:
            with open(out_path, "wb") as f:
                f.write(base64.b64decode(b64))
            return out_path

        job_id = data.get("job_id") or data.get("task_id") or data.get("id") or data.get("request_id")
        if job_id:
            return poll_ace_music_task(job_id, out_path)

        print(f"ACE Music response had no recognizable audio field: {list(data.keys())}")
        return None
    except Exception as e:
        print(f"ACE Music generation raised an exception, continuing without background score: {e}")
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

    return CompositeAudioClip(layers)


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

    final = concatenate_videoclips(clips, method="compose")
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
        try:
            head = requests.head(url, timeout=30)
            if head.status_code == 200:
                verified_urls.append(url)
            else:
                print(f"Clip {i} failed verification (status {head.status_code}), will regenerate: {url}")
                break
        except requests.RequestException as e:
            print(f"Clip {i} failed verification ({e}), will regenerate: {url}")
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
        shot_durations = compute_shot_durations(shot_list, audio_clip.duration)

        batch_end = min(next_index + CLIP_BATCH_LIMIT, total_shots)
        print(f"Resuming from shot {next_index + 1}/{total_shots} ({len(video_urls)} already done) - generating up to shot {batch_end} this run")

        for i in range(next_index, batch_end):
            shot = shot_list[i]
            raw_path = f"/tmp/shot_{i:03d}.mp4"
            print(f"Generating shot {i+1}/{total_shots} (~{shot_durations[i]:.1f}s)...")
            generate_shot_clip(shot, shot_durations[i], raw_path)

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
        shot_durations = compute_shot_durations(shot_list, audio_clip.duration)

        output_path = "/tmp/final_video.mp4"
        assemble_final_video(script_id, video_urls, audio_path, music_mood, shot_list, shot_durations, output_path)

        video_url = upload_video(script_id, output_path)
        print(f"Uploaded: {video_url}")

        mark_video_generated(script_id, video_url)
        print("Done.")


if __name__ == "__main__":
    main()
