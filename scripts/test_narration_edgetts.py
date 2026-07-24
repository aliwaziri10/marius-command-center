"""
Marius Command Center - Narration Engine TEST #2: edge-tts (standalone, non-destructive)

Purpose: test whether Microsoft Edge's free TTS engine (via the edge-tts
library - no API key, no signup, no rate limit) sounds more expressive
than the current local Kokoro engine, using a real 5-7 minute Erased
narration as the test text.

UPDATE (2026-07-24): first test run confirmed edge-tts sounds "much, much
better" and "more expressive" than Kokoro. Rate -15% was tried next and
came back too slow. Trying -5% now as a smaller adjustment from the
original (too-fast) default pace.

SAFETY GUARANTEES (same as the FreeLLMAPI test):
- Only ever SELECTs from the scripts table - never UPDATEs or INSERTs.
- Only reads a script that is ALREADY status='uploaded' (fully published,
  long finished) - zero chance of interfering with anything mid-pipeline.
- Uploads the test audio to Supabase storage under a "TEST_EDGE_" filename
  prefix - completely separate from any real narration_url. No script row
  is ever pointed at this file.
- Does not touch, call, or modify narration.py, video_generation.py, or
  any other pipeline stage. Kokoro remains the only live narration engine
  no matter what this test shows.
- No API key needed - edge-tts is free, unauthenticated, and unlimited.
"""

import os
import sys
import time
import asyncio
import requests
import edge_tts

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SECRET_KEY"]

HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
}

# A calm, expressive male documentary-narrator voice. Full list available
# via `edge-tts --list-voices` if a different tone is wanted later.
VOICE = "en-US-GuyNeural"

# Second test run (2026-07-24) at -15% came back too slow. Trying a
# smaller adjustment. Adjust this single value to re-tune further.
RATE = "-5%"


def get_sample_script():
    """Pulls ONE already-published script (status='uploaded') to use as
    realistic test narration text. Read-only - SELECT only."""
    resp = requests.get(
        f"{SUPABASE_URL}/rest/v1/scripts?status=eq.uploaded&order=created_at.desc&limit=1&select=id,narration_text",
        headers=HEADERS,
        timeout=30,
    )
    resp.raise_for_status()
    rows = resp.json()
    if not rows:
        raise RuntimeError("No already-uploaded scripts found to use as test text.")
    return rows[0]


async def synthesize(text, out_path):
    communicate = edge_tts.Communicate(text, VOICE, rate=RATE)
    await communicate.save(out_path)


def upload_test_audio(script_id, local_path):
    filename = f"TEST_EDGE_5PCT_{script_id}.mp3"
    with open(local_path, "rb") as f:
        audio_bytes = f.read()
    resp = requests.post(
        f"{SUPABASE_URL}/storage/v1/object/narration/{filename}",
        headers={
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
            "Content-Type": "audio/mpeg",
            "x-upsert": "true",
        },
        data=audio_bytes,
        timeout=120,
    )
    if resp.status_code >= 400:
        print(f"Test audio upload failed - status {resp.status_code}: {resp.text}")
        return None
    resp.raise_for_status()
    return f"{SUPABASE_URL}/storage/v1/object/public/narration/{filename}"


def main():
    script = get_sample_script()
    script_id = script["id"]
    narration_text = script["narration_text"]

    print(f"Using script id={script_id} as test text ({len(narration_text)} chars, {len(narration_text.split())} words).")
    print(f"Rate adjustment: {RATE}")
    print("This script is already published and live on YouTube - reading its text changes nothing about it.\n")

    local_path = "/tmp/test_edge_narration_5pct.mp3"
    start = time.time()
    try:
        asyncio.run(synthesize(narration_text, local_path))
    except Exception as e:
        print(f"\n=== TEST RESULT: FAILED ===")
        print(f"edge-tts could not produce audio for this length of narration: {e}")
        print("Current Kokoro-based narration.py is UNCHANGED and remains the active engine.")
        sys.exit(0)
    elapsed = time.time() - start

    size_bytes = os.path.getsize(local_path)
    print(f"SUCCESS in {elapsed:.1f}s. Produced {size_bytes} bytes of audio.")

    public_url = upload_test_audio(script_id, local_path)

    print("\n=== TEST RESULT: SUCCESS ===")
    print(f"Time taken: {elapsed:.1f} seconds")
    print(f"Voice used: {VOICE}, rate: {RATE}")
    if public_url:
        print(f"Listen to the test audio here: {public_url}")
    print("\nCurrent Kokoro-based narration.py is UNCHANGED and remains the active engine.")
    print("This was a test only - nothing in the live pipeline was modified.")


if __name__ == "__main__":
    main()
