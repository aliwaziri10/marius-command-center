"""
Marius Command Center - Narration Engine TEST #4: edge-tts, per-sentence
synthesis with inserted pauses, muxed into the real video

UPDATE (2026-07-24): Global rate slowdown (-5%, -10%) still left narration
running ahead of video-locked shot timing. Switching approach: synthesize
each sentence separately, then concatenate with a fixed silence gap
between sentences, so pacing comes from pauses (matching how Kokoro's
paragraph-break pauses already work in the live pipeline) rather than
from slowing down speech itself.

UPDATE (2026-07-25, first pass): Narration still finished 4-5s ahead of
video with a 450ms sentence pause. Raised pause to 650ms to add ~4.6s
across a typical 23-gap/24-sentence script.

UPDATE (2026-07-25, second pass): A flat pause only fixes the TOTAL
length - it drifted badly mid-script (9s off partway through), because
Edge TTS doesn't take the same time per sentence that Kokoro did when
the video's shots were originally cut. Replaced the fixed pause with
per-sentence padding: shot_durations for this video are split into
equal chunks (one chunk per sentence), and each sentence's audio is
padded with silence up to the sum of its chunk's shot durations. This
locks sync at every sentence boundary instead of only at the end.

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

# Speech rate per sentence - pacing now comes from per-sentence silence
# padding against the video's own shot_durations, not from this rate.
RATE = "-5%"

# Minimum silence gap enforced between sentences even when a sentence's
# own shots leave no slack (so words never run together).
MIN_GAP_MS = 150


def get_sample_script():
    """Pulls ONE already-published script (status='uploaded') to use as
    realistic test narration text, plus its already-live video_url and
    shot_durations so the new narration can be paced to match the real
    video's cut points. Read-only - SELECT only."""
    resp = requests.get(
        f"{SUPABASE_URL}/rest/v1/scripts"
        f"?status=eq.uploaded&order=created_at.desc&limit=1"
        f"&select=id,narration_text,video_url,shot_durations",
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
    if not row.get("shot_durations"):
        raise RuntimeError(f"Script {row['id']} has no shot_durations - can't pace against video.")
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


def chunk_shot_durations(shot_durations, n_sentences):
    """Splits the video's per-shot durations into n_sentences groups, in
    order, distributing any remainder shots across the first groups.
    Returns a list of target durations in ms, one per sentence."""
    n_shots = len(shot_durations)
    base = n_shots // n_sentences
    remainder = n_shots % n_sentences

    targets_ms = []
    idx = 0
    for i in range(n_sentences):
        take = base + (1 if i < remainder else 0)
        chunk = shot_durations[idx:idx + take]
        idx += take
        targets_ms.append(sum(chunk) * 1000)
    return targets_ms


async def synthesize(text, voice, rate, out_path):
    communicate = edge_tts.Communicate(text, voice, rate=rate)
    await communicate.save(out_path)


def build_paced_narration(text, voice, rate, shot_durations, out_path, tmp_dir, label):
    """Synthesizes each sentence separately, then pads each one with
    silence up to that sentence's share of the video's actual shot
    durations - so audio and video stay locked at every sentence
    boundary, not just at the very end."""
    sentences = split_sentences(text)
    targets_ms = chunk_shot_durations(shot_durations, len(sentences))
    combined = AudioSegment.silent(duration=0)

    for i, sentence in enumerate(sentences):
        clip_path = f"{tmp_dir}/sent_{label}_{i}.mp3"
        asyncio.run(synthesize(sentence, voice, rate, clip_path))
        speech = AudioSegment.from_file(clip_path)

        target_ms = targets_ms[i]
        pad_ms = target_ms - len(speech)
        if pad_ms < MIN_GAP_MS:
            print(f"  [sentence {i}] speech {len(speech)}ms >= target {target_ms:.0f}ms "
                  f"- overran its shots by {abs(pad_ms):.0f}ms, using minimum gap instead.")
            pad_ms = MIN_GAP_MS

        combined += speech
        if i != len(sentences) - 1:
            combined += AudioSegment.silent(duration=pad_ms)

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
    shot_durations = script["shot_durations"]

    print(f"Using script id={script_id} as test text ({len(narration_text)} chars, {len(narration_text.split())} words).")
    print(f"Rate: {RATE} | Pacing: per-sentence, matched to {len(shot_durations)} shot durations")
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
            n_sentences = build_paced_narration(narration_text, voice, RATE, shot_durations, audio_path, "/tmp", label)
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
