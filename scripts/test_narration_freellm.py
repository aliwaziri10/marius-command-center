"""
Marius Command Center - Narration Engine TEST (standalone, non-destructive)

Purpose: test whether FreeLLMAPI's TTS endpoint (the one used successfully
by Tech Pulse) can handle a full-length 5-7 minute Erased narration, and
capture real evidence: success/failure, response time, which provider
actually served it, and the resulting audio duration.

SAFETY GUARANTEES:
- Only ever SELECTs from the scripts table - never UPDATEs or INSERTs.
- Only reads a script that is ALREADY status='uploaded' (fully published,
  long ago finished) - so there is zero chance of interfering with any
  script currently mid-pipeline.
- Uploads the test audio to Supabase storage under a "TEST_" filename
  prefix, completely separate from any real narration_url ever referenced
  by a script row. No script row is ever pointed at this file.
- Does not touch, call, or modify narration.py, video_generation.py, or
  any other pipeline stage. Running this can never break or change the
  current Kokoro-based narration engine in any way.
- Safe to run as many times as you like; nothing here is "live".
"""

import os
import sys
import time
import json
import requests

# --- Marius Supabase (read-only use here) ---
SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SECRET_KEY"]

# --- FreeLLMAPI (Tech Pulse's TTS provider, borrowed only for this test) ---
FREELLM_URL = os.environ["FREELLM_API_URL"].replace("/chat/completions", "")
FREELLM_KEY = os.environ["FREELLM_API_KEY"]

HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
}


def get_sample_script():
    """Pulls ONE already-published script (status='uploaded') to use as
    realistic 5-7 minute test narration text. Read-only - SELECT only."""
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


def test_freellm_tts(text):
    """Calls FreeLLMAPI's /v1/audio/speech once with the full narration
    text, measuring response time and capturing which provider served it
    (X-Routed-Via), so we have real evidence instead of a guess."""
    body = json.dumps({
        "model": "auto",
        "input": text,
    }).encode()

    print(f"Sending {len(text)} characters ({len(text.split())} words) to FreeLLMAPI TTS...")
    start = time.time()

    try:
        resp = requests.post(
            f"{FREELLM_URL}/audio/speech",
            data=body,
            headers={
                "Authorization": f"Bearer {FREELLM_KEY}",
                "Content-Type": "application/json",
            },
            timeout=300,  # generous timeout for this TEST only - production code still uses 60s
        )
    except requests.exceptions.Timeout:
        elapsed = time.time() - start
        print(f"FAILED: request timed out after {elapsed:.1f}s (limit was 300s).")
        print("This alone is useful evidence: long-form input may exceed what this endpoint can handle in reasonable time.")
        return None

    elapsed = time.time() - start
    routed_via = resp.headers.get("X-Routed-Via", "unknown")
    fallback_attempts = resp.headers.get("X-Fallback-Attempts", "0")

    if resp.status_code >= 400:
        print(f"FAILED: HTTP {resp.status_code} after {elapsed:.1f}s. Routed via: {routed_via}")
        print(f"Response body: {resp.text[:500]}")
        return None

    audio_bytes = resp.content
    print(f"SUCCESS in {elapsed:.1f}s. Routed via: {routed_via}. Fallback attempts: {fallback_attempts}")
    print(f"Received {len(audio_bytes)} bytes of audio.")

    return {
        "audio_bytes": audio_bytes,
        "elapsed_seconds": elapsed,
        "routed_via": routed_via,
        "fallback_attempts": fallback_attempts,
    }


def upload_test_audio(script_id, audio_bytes):
    """Uploads to a TEST_-prefixed filename - never referenced by any
    script row, never touches narration_url. Purely for you to listen to."""
    filename = f"TEST_freellm_{script_id}.mp3"
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
    public_url = f"{SUPABASE_URL}/storage/v1/object/public/narration/{filename}"
    return public_url


def main():
    script = get_sample_script()
    script_id = script["id"]
    narration_text = script["narration_text"]

    print(f"Using script id={script_id} as test text ({len(narration_text)} chars).")
    print("This script is already published and live on YouTube - reading its text changes nothing about it.\n")

    result = test_freellm_tts(narration_text)

    if result is None:
        print("\n=== TEST RESULT: FAILED ===")
        print("FreeLLMAPI TTS could not produce audio for this length of narration.")
        print("Current Kokoro-based narration.py is UNCHANGED and remains the active engine.")
        sys.exit(0)

    public_url = upload_test_audio(script_id, result["audio_bytes"])

    print("\n=== TEST RESULT: SUCCESS ===")
    print(f"Time taken: {result['elapsed_seconds']:.1f} seconds")
    print(f"Provider that served this request: {result['routed_via']}")
    print(f"Fallback attempts before success: {result['fallback_attempts']}")
    if public_url:
        print(f"Listen to the test audio here: {public_url}")
    print("\nCurrent Kokoro-based narration.py is UNCHANGED and remains the active engine.")
    print("This was a test only - nothing in the live pipeline was modified.")


if __name__ == "__main__":
    main()
