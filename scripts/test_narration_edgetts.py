"""
Marius Command Center - Narration Engine TEST #4: edge-tts, per-sentence
synthesis with inserted pauses, muxed into the real video

UPDATE (2026-07-24): Global rate slowdown (-5%, -10%) still left narration
running ahead of video-locked shot timing. Switching approach: synthesize
each sentence separately, then concatenate with a fixed silence gap
between sentences, so pacing comes from pauses (matching how Kokoro's
paragraph-break pauses already work in the live pipeline) rather than
from slowing down speech itself.

SAFETY GUARANTEES (same as prior tests):
- Only ever SELECTs from the scripts table - never UPDATEs or INSERTs.
- Only reads a script that is ALREADY status='uploaded' (fully published,
  long finished) - zero chance of interfering with anything mid-pipeline.
- Downloads that script's already-public, already-live video_url purely
  to mux a NEW test audio track onto a COPY of it - the original file in
  Supabase Storage and the original YouTube upload are never touched or
  overwritten.
- Uploads combined test videos under a "TEST_EDGE_MIXED_" filename
  prefix - completely separate from any real video_url. No script row
  is ever pointed at these files.
- Does not touch, call, or modify narration.py, video_generation.py, or
  any other pipeline stage. Kokoro remains the only live narration engine
  no matter what this test shows.
- No API key needed - edge-tts is free, unauthenticated, and unlimited.
"""

import os
import re
import time
import asyncio
import subprocess
import requests
import edge_tts
from pydub import AudioSegment

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SECRET_KEY"]

HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
}

VOICES = [
    {"label": "male", "voice": "en-US-GuyNeural"},
    {"label": "female", "voice": "en-US-AriaNeural"},
]

# Speech rate per sentence - kept near-natural since pacing is now
# controlled by SENTENCE_PAUSE_MS between sentences, not by slowing
# down the words themselves.
RATE = "-5%"

# Silence inserted between sentences, in milliseconds. Adjust this up
# or down between test runs to dial in sync with the video.
SENTENCE_PAUSE_MS = 450


def get_sample_script():
    """Pulls ONE already-published script (status='uploaded') to use as
    realistic test narration text, plus its already-live video_url so
    the new narration can be muxed onto a copy of the real video.
    Read-only - SELECT only."""
    resp = requests.get(
        f"{SUPABASE_URL}/rest/v1/scripts"
        f"?status=eq.uploaded&order=created_at.desc&limit=1"
        f"&select=id,narration_text,video_url",
        headers=HEADERS,
        timeout=30,
    )
    resp.raise_for_status()
    rows = resp.json()
    if not rows:
        raise RuntimeError("No already-uploaded scripts found to use as test text.")
    row = rows[0]
    if not row.get("video_url"):
        raise RuntimeError(f"Script {row['id']} has no video_url - can't mux a preview.")
    return row


def download_video(video_url, out_path):
    resp = requests.get(video_url, stream=True, timeout=180)
    resp.raise_for_status()
    with open(out_path, "wb") as f:
        for chunk in resp.iter_content(chunk_size=1 << 20):
            f.write(chunk)


def split_sentences(text):
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    return [s.strip() for s in sentences if s.strip()]


async def synthesize(text, voice, rate, out_path):
    communicate = edge_tts.Communicate(text, voice, rate=rate)
    await communicate.save(out_path)


def build_paced_narration(text, voice, rate, out_path, tmp_dir, label):
    """Synthesizes each sentence separately, then concatenates them with
    a fixed silence gap between sentences."""
    sentences = split_sentences(text)
    silence = AudioSegment.silent(duration=SENTENCE_PAUSE_MS)
    combined = AudioSegment.silent(duration=0)

    for i, sentence in enumerate(sentences):
        clip_path = f"{tmp_dir}/sent_{label}_{i}.mp3"
        asyncio.run(synthesize(sentence, voice, rate, clip_path))
        combined += AudioSegment.from_file(clip_path)
        if i != len(sentences) - 1:
            combined += silence

    combined.export(out_path, format="mp3")
    return len(sentences)


def mux_audio_onto_video(video_path, audio_path, out_path):
    """Replaces the video's audio track with the new narration track.
    Video stream is copied untouched (fast, no re-encode). Output length
    follows the SHORTER of video/audio so nothing hangs on a black frame
    or a silent tail - this is a preview, not a final render."""
    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-i", audio_path,
        "-map", "0:v:0",
        "-map", "1:a:0",
        "-c:v", "copy",
        "-c:a", "aac",
        "-shortest",
        out_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg mux failed: {result.stderr[-2000:]}")


def upload_test_file(local_path, filename, bucket, content_type):
    with open(local_path, "rb") as f:
        data = f.read()
    resp = requests.post(
        f"{SUPABASE_URL}/storage/v1/object/{bucket}/{filename}",
        headers={
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
            "Content-Type": content_type,
            "x-upsert": "true",
        },
        data=data,
        timeout=300,
    )
    if resp.status_code >= 400:
        print(f"Upload failed for {filename} - status {resp.status_code}: {resp.text}")
        return None
    resp.raise_for_status()
    return f"{SUPABASE_URL}/storage/v1/object/public/{bucket}/{filename}"


def main():
    script = get_sample_script()
    script_id = script["id"]
    narration_text = script["narration_text"]
    video_url = script["video_url"]

    print(f"Using script id={script_id} as test text ({len(narration_text)} chars, {len(narration_text.split())} words).")
    print(f"Rate: {RATE} | Sentence pause: {SENTENCE_PAUSE_MS}ms")
    print(f"Source video (copy will be made, original untouched): {video_url}")
    print("This script is already published and live on YouTube - reading its text changes nothing about it.\n")

    local_video_path = "/tmp/source_video.mp4"
    print("Downloading source video...")
    download_video(video_url, local_video_path)
    print("Downloaded.\n")

    results = []

    for entry in VOICES:
        label = entry["label"]
        voice = entry["voice"]
        print(f"--- Voice: {label} ({voice}) ---")

        audio_path = f"/tmp/test_edge_paced_{label}.mp3"
        start = time.time()
        try:
            n_sentences = build_paced_narration(narration_text, voice, RATE, audio_path, "/tmp", label)
        except Exception as e:
            print(f"FAILED to synthesize {label} voice: {e}")
            continue
        elapsed = time.time() - start
        print(f"Synthesized {n_sentences} sentences in {elapsed:.1f}s.")

        mixed_path = f"/tmp/test_edge_mixed_{label}.mp4"
        try:
            mux_audio_onto_video(local_video_path, audio_path, mixed_path)
        except Exception as e:
            print(f"FAILED to mux {label} voice onto video: {e}")
            continue
        print("Muxed onto video.")

        mixed_filename = f"TEST_EDGE_MIXED_{label}_{script_id}.mp4"
        public_url = upload_test_file(mixed_path, mixed_filename, "videos", "video/mp4")
        if public_url:
            print(f"Watch+listen preview ({label} voice): {public_url}")
            results.append((label, public_url))
        print()

    print("=== TEST RESULT ===")
    if results:
        for label, url in results:
            print(f"{label}: {url}")
    else:
        print("No previews were produced - see errors above.")
    print("\nCurrent Kokoro-based narration.py is UNCHANGED and remains the active engine.")
    print("This was a test only - nothing in the live pipeline was modified.")


if __name__ == "__main__":
    main()
