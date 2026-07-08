import os
import sys
import requests
from supabase import create_client
from kokoro_onnx import Kokoro
import soundfile as sf

# --- Config from GitHub Actions secrets ---
SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_SECRET_KEY = os.environ["SUPABASE_SECRET_KEY"]

MODEL_URL = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v0_19.onnx"
VOICES_URL = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices.json"
MODEL_PATH = "kokoro-v0_19.onnx"
VOICES_PATH = "voices.json"
VOICE_NAME = "bm_george"
LANG = "en-gb"

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

    # 3. Generate narration audio
    kokoro = Kokoro(MODEL_PATH, VOICES_PATH)
    samples, sample_rate = kokoro.create(narration_text, voice=VOICE_NAME, speed=1.0, lang=LANG)

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
