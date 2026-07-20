import os
import re
import sys
import json
import requests
import numpy as np
from supabase import create_client
from kokoro_onnx import Kokoro
import soundfile as sf

# --- Config from GitHub Actions secrets ---
SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_SECRET_KEY = os.environ["SUPABASE_SECRET_KEY"]

MODEL_URL = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files/kokoro-v0_19.onnx"
VOICES_URL = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files/voices.bin"
MODEL_PATH = "kokoro-v0_19.onnx"
VOICES_PATH = "voices.bin"
VOICE_NAME = "am_adam"
LANG = "en-us"

# Pause after EVERY sentence, per Zia's explicit instruction - not just
# paragraph breaks. 1-2s per pause (reduced from an earlier 4-5s, which
# would have added ~3 extra minutes of silence across a 40+ sentence script).
PAUSE_SECONDS_MIN = 1.0
PAUSE_SECONDS_MAX = 2.0


def download_if_missing(url, path):
    if not os.path.exists(path):
        print(f"Downloading {path} ...")
        r = requests.get(url, timeout=120)
        r.raise_for_status()
        with open(path, "wb") as f:
            f.write(r.content)
        print(f"Saved {path}")
    else:
        print(f"{path} already present, skipping download")


def normalize_volume(samples, target_peak=0.95):
    peak = np.max(np.abs(samples))
    if peak == 0:
        return samples
    return samples * (target_peak / peak)


def split_into_segments(narration_text):
    """Splits narration into one segment per SENTENCE, so a pause gets
    inserted after every sentence (not just at paragraph/blank-line
    breaks, which most scripts don't have). Sentence boundary = ./!/?
    followed by whitespace. Falls back to the whole text as a single
    segment if no sentence-ending punctuation is found at all."""
    raw_segments = re.split(r"(?<=[.!?])\s+", narration_text.strip())
    segments = [seg.strip() for seg in raw_segments if seg.strip()]
    return segments if segments else [narration_text.strip()]


def synthesize_with_pauses(kokoro, narration_text, voice, lang, sample_rate_hint=24000):
    """Synthesizes narration sentence-by-sentence and concatenates them
    with a real silence gap (1-2s) after every sentence, instead of one
    continuous kokoro.create() call with no pauses at all."""
    segments = split_into_segments(narration_text)
    print(f"Narration split into {len(segments)} sentence(s) for pause insertion.")

    audio_chunks = []
    sample_rate = sample_rate_hint

    for i, segment in enumerate(segments):
        samples, sample_rate = kokoro.create(segment, voice=voice, speed=1.0, lang=lang)
        audio_chunks.append(samples)

        if i < len(segments) - 1:
            pause_len = PAUSE_SECONDS_MIN if i % 2 == 0 else PAUSE_SECONDS_MAX
            silence = np.zeros(int(pause_len * sample_rate), dtype=audio_chunks[-1].dtype)
            audio_chunks.append(silence)

    return np.concatenate(audio_chunks), sample_rate


def synthesize_per_shot(kokoro, shot_list, voice, lang, sample_rate_hint=24000):
    """Synthesizes narration one shot at a time using each shot's own
    narration_excerpt (guaranteed 1:1 with shot_list, unlike a separate
    regex re-split of the full narration_text). Records each shot's real
    audio duration - INCLUDING its trailing pause - so video generation
    can size clips to true narration timing instead of estimating from
    character count, which ignores the 1-2s silence gap inserted after
    every sentence and drifts further out of sync as the script goes on."""
    audio_chunks = []
    shot_durations = []
    sample_rate = sample_rate_hint

    for i, shot in enumerate(shot_list):
        text = (shot.get("narration_excerpt") or "").strip()
        if not text:
            shot_durations.append(0.0)
            continue

        samples, sample_rate = kokoro.create(text, voice=voice, speed=1.0, lang=lang)
        audio_chunks.append(samples)
        shot_seconds = len(samples) / sample_rate

        if i < len(shot_list) - 1:
            pause_len = PAUSE_SECONDS_MIN if i % 2 == 0 else PAUSE_SECONDS_MAX
            silence = np.zeros(int(pause_len * sample_rate), dtype=samples.dtype)
            audio_chunks.append(silence)
            shot_seconds += pause_len

        shot_durations.append(shot_seconds)

    return np.concatenate(audio_chunks), sample_rate, shot_durations


def main():
    supabase = create_client(SUPABASE_URL, SUPABASE_SECRET_KEY)

    # 1. Get one pending script
    result = supabase.table("scripts").select("*").eq("status", "pending").limit(1).execute()
    if not result.data:
        print("No pending scripts found. Exiting.")
        return

    script = result.data[0]
    script_id = script["id"]
    narration_text = script["narration_text"]
    shot_list = script.get("shot_list")
    if isinstance(shot_list, str):
        shot_list = json.loads(shot_list)
    print(f"Narrating script id={script_id}, length={len(narration_text)} chars, {len(shot_list or [])} shots")

    # 2. Download Kokoro model files if not cached
    download_if_missing(MODEL_URL, MODEL_PATH)
    download_if_missing(VOICES_URL, VOICES_PATH)

    # 3. Generate narration audio. If shot_list is available, synthesize
    # per-shot so each shot's real spoken duration (plus its trailing
    # pause) is known exactly - this is what video generation uses for
    # true narration-synced timing. Falls back to the old whole-text
    # sentence-split method if shot_list isn't available yet.
    kokoro = Kokoro(MODEL_PATH, VOICES_PATH)
    shot_durations = None
    if shot_list:
        samples, sample_rate, shot_durations = synthesize_per_shot(kokoro, shot_list, VOICE_NAME, LANG)
    else:
        samples, sample_rate = synthesize_with_pauses(kokoro, narration_text, VOICE_NAME, LANG)

    # 3b. Boost volume to a normal loudness
    samples = normalize_volume(samples, target_peak=0.95)

    output_filename = f"narration_{script_id}.wav"
    sf.write(output_filename, samples, sample_rate)
    print(f"Audio written to {output_filename}")

    # 4. Upload to Supabase storage bucket 'narration'
    with open(output_filename, "rb") as f:
        supabase.storage.from_("narration").upload(
            output_filename,
            f,
            {"content-type": "audio/wav", "upsert": "true"}
        )
    public_url = supabase.storage.from_("narration").get_public_url(output_filename)
    print(f"Uploaded. Public URL: {public_url}")

    # 5. Update script status, narration URL, and real per-shot timing.
    # Status goes straight to 'images_generated' (skipping the old,
    # now-removed image_generation.py stage - Agnes generates video
    # directly from shot_list text, it never used the still images).
    update_payload = {
        "status": "images_generated",
        "narration_url": public_url
    }
    if shot_durations is not None:
        update_payload["shot_durations"] = shot_durations
    supabase.table("scripts").update(update_payload).eq("id", script_id).execute()
    print("Script status updated to 'images_generated'. Done.")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
