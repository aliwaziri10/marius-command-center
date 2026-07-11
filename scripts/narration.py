import os
import re
import sys
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
            # Alternate between min/max within range for a touch of natural
            # variation rather than an identical mechanical gap every time.
            pause_len = PAUSE_SECONDS_MIN if i % 2 == 0 else PAUSE_SECONDS_MAX
            silence = np.zeros(int(pause_len * sample_rate), dtype=audio_chunks[-1].dtype)
            audio_chunks.append(silence)

    return np.concatenate(audio_chunks), sample_rate


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
    print(f"Narrating script id={script_id}, length={len(narration_text)} chars")

    # 2. Download Kokoro model files if not cached
    download_if_missing(MODEL_URL, MODEL_PATH)
    download_if_missing(VOICES_URL, VOICES_PATH)

    # 3. Generate narration audio, with real pauses after every sentence
    kokoro = Kokoro(MODEL_PATH, VOICES_PATH)
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

    # 5. Update script status and store narration URL
    supabase.table("scripts").update({
        "status": "narrated",
        "narration_url": public_url
    }).eq("id", script_id).execute()
    print("Script status updated to 'narrated'. Done.")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
