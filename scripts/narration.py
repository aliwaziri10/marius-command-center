"""
Marius Command Center - Narration Agent
Takes the oldest pending script and generates a narrated audio file using
gTTS (free, no API key needed), then uploads it to Supabase Storage.
"""

import os
import requests
from gtts import gTTS

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SECRET_KEY"]

HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
}

BUCKET_NAME = "narration"


def get_next_pending_script():
    resp = requests.get(
        f"{SUPABASE_URL}/rest/v1/scripts?status=eq.pending&order=created_at.asc&limit=1",
        headers=HEADERS,
        timeout=30,
    )
    resp.raise_for_status()
    rows = resp.json()
    return rows[0] if rows else None


def generate_audio(text, output_path):
    tts = gTTS(text=text, lang="en", tld="co.uk", slow=False)
    tts.save(output_path)


def upload_audio(script_id, file_path):
    file_name = f"{script_id}.mp3"
    with open(file_path, "rb") as f:
        file_bytes = f.read()

    resp = requests.put(
        f"{SUPABASE_URL}/storage/v1/object/{BUCKET_NAME}/{file_name}",
        headers={
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
            "Content-Type": "audio/mpeg",
        },
        data=file_bytes,
        timeout=60,
    )
    if resp.status_code >= 400:
        print(f"Upload failed - status {resp.status_code}: {resp.text}")
    resp.raise_for_status()
    return f"{SUPABASE_URL}/storage/v1/object/public/{BUCKET_NAME}/{file_name}"


def update_video_record(script_id, narration_url):
    resp = requests.post(
        f"{SUPABASE_URL}/rest/v1/videos",
        headers={**HEADERS, "Prefer": "return=representation"},
        json={
            "script_id": script_id,
            "narration_url": narration_url,
            "status": "narrated",
        },
        timeout=30,
    )
    resp.raise_for_status()


def mark_script_narrated(script_id):
    resp = requests.patch(
        f"{SUPABASE_URL}/rest/v1/scripts?id=eq.{script_id}",
        headers=HEADERS,
        json={"status": "narrated"},
        timeout=30,
    )
    resp.raise_for_status()


def main():
    script = get_next_pending_script()
    if not script:
        print("No pending scripts found. Nothing to do.")
        return

    print(f"Generating narration for script {script['id']}")
    output_path = "/tmp/narration.mp3"
    generate_audio(script["narration_text"], output_path)

    narration_url = upload_audio(script["id"], output_path)
    print(f"Uploaded: {narration_url}")

    update_video_record(script["id"], narration_url)
    mark_script_narrated(script["id"])
    print("Done.")


if __name__ == "__main__":
    main()
