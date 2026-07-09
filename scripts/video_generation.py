"""
Marius Command Center - Video Generation Agent
Takes the oldest narrated script and generates one real AI video clip per
shot using Agnes AI, sized to match narration timing, then assembles the
final video with the narration audio track.
"""

import os
import json
import time
import requests
from moviepy import VideoFileClip, AudioFileClip, concatenate_videoclips

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SECRET_KEY"]
AGNES_API_KEY = os.environ["AGNES_API_KEY"]

HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
}

AGNES_BASE = "https://apihub.agnes-ai.com/v1"
AGNES_HEADERS = {
    "Authorization": f"Bearer {AGNES_API_KEY}",
    "Content-Type": "application/json",
}

VIDEO_BUCKET = "videos"
WIDTH, HEIGHT = 1152, 768
FRAME_RATE = 24
MIN_FRAMES = 49   # 8*6+1, ~2s - Agnes requires num_frames = 8*n+1
MAX_FRAMES = 169  # 8*21+1, ~7s


def round_to_valid_frames(num_frames):
    n = round((num_frames - 1) / 8)
    n = max(0, n)
    return 8 * n + 1


def get_next_ready_script():
    resp = requests.get(
        f"{SUPABASE_URL}/rest/v1/scripts?status=eq.narrated&order=created_at.asc&limit=1",
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
            f"https://apihub.agnes-ai.com/agnesapi",
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


def generate_shot_clip(prompt, target_duration, out_path):
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


def build_video(shot_list, audio_path, output_path):
    audio_clip = AudioFileClip(audio_path)
    total_duration = audio_clip.duration

    weights = [max(len(s.get("narration_excerpt", "")), 20) for s in shot_list]
    total_weight = sum(weights)

    clips = []
    for i, (shot, weight) in enumerate(zip(shot_list, weights)):
        target_duration = (weight / total_weight) * total_duration
        raw_path = f"/tmp/shot_{i:03d}.mp4"

        print(f"Generating shot {i+1}/{len(shot_list)} (~{target_duration:.1f}s)...")
        generate_shot_clip(shot["visual_description"], target_duration, raw_path)

        clip = VideoFileClip(raw_path)
        clip = clip.resized(new_size=(WIDTH, HEIGHT))
        clip = fit_clip_to_duration(clip, target_duration)
        clips.append(clip)

        time.sleep(4)

    final = concatenate_videoclips(clips, method="compose")
    final = final.with_audio(audio_clip)
    final.write_videofile(
        output_path,
        fps=FRAME_RATE,
        codec="libx264",
        audio_codec="aac",
        threads=2,
        logger=None,
    )
    return output_path


def upload_video(script_id, file_path):
    file_name = f"{script_id}.mp4"
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
        print("No narrated scripts ready for video generation. Nothing to do.")
        return
    if not script.get("narration_url"):
        print("Script has no narration_url yet. Skipping.")
        return

    print(f"Building video for script {script['id']}")

    audio_path = "/tmp/narration_audio"
    audio_path += ".mp3" if script["narration_url"].endswith(".mp3") else ".wav"
    download_file(script["narration_url"], audio_path)

    shot_list = script["shot_list"]
    if isinstance(shot_list, str):
        shot_list = json.loads(shot_list)

    output_path = "/tmp/final_video.mp4"
    build_video(shot_list, audio_path, output_path)

    video_url = upload_video(script["id"], output_path)
    print(f"Uploaded: {video_url}")

    mark_video_generated(script["id"], video_url)
    print("Done.")


if __name__ == "__main__":
    main()
