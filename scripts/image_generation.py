import os
import sys
import time
import json
import urllib.parse
import requests
from supabase import create_client

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_SECRET_KEY = os.environ["SUPABASE_SECRET_KEY"]

POLLINATIONS_BASE = "https://image.pollinations.ai/prompt"
IMAGE_WIDTH = 1280
IMAGE_HEIGHT = 720
DELAY_BETWEEN_CALLS_SECONDS = 16  # stay above the 15s anonymous rate limit

def generate_image(prompt, seed):
    encoded_prompt = urllib.parse.quote(prompt)
    url = f"{POLLINATIONS_BASE}/{encoded_prompt}"
    params = {
        "width": IMAGE_WIDTH,
        "height": IMAGE_HEIGHT,
        "seed": seed,
        "nologo": "true"
    }
    r = requests.get(url, params=params, timeout=60)
    r.raise_for_status()
    return r.content

def extract_shot_descriptions(shot_list):
    descriptions = []
    if isinstance(shot_list, list):
        for shot in shot_list:
            if isinstance(shot, dict):
                text = shot.get("description") or shot.get("visual") or shot.get("shot") or shot.get("text")
                if text:
                    descriptions.append(text)
            elif isinstance(shot, str):
                descriptions.append(shot)
    return descriptions

def main():
    supabase = create_client(SUPABASE_URL, SUPABASE_SECRET_KEY)

    result = supabase.table("scripts").select("*").eq("status", "narrated").limit(1).execute()
    if not result.data:
        print("No narrated scripts found. Exiting.")
        return

    script = result.data[0]
    script_id = script["id"]
    shot_list = script.get("shot_list")
    print(f"Generating images for script id={script_id}")

    descriptions = extract_shot_descriptions(shot_list)
    if not descriptions:
        print("No shot descriptions found in shot_list. Exiting.")
        return

    print(f"Found {len(descriptions)} shots to illustrate.")

    image_urls = []
    for i, desc in enumerate(descriptions):
        print(f"[{i+1}/{len(descriptions)}] Generating: {desc[:80]}")
        try:
            image_bytes = generate_image(desc, seed=i)
        except Exception as e:
            print(f"  Failed to generate image {i+1}: {e}")
            continue

        filename = f"{script_id}_shot_{i+1}.jpg"
        supabase.storage.from_("images").upload(
            filename,
            image_bytes,
            {"content-type": "image/jpeg", "upsert": "true"}
        )
        public_url = supabase.storage.from_("images").get_public_url(filename)
        image_urls.append(public_url)
        print(f"  Uploaded: {public_url}")

        if i < len(descriptions) - 1:
            time.sleep(DELAY_BETWEEN_CALLS_SECONDS)

    if not image_urls:
        print("No images were successfully generated. Not updating status.")
        return

    supabase.table("scripts").update({
        "status": "images_generated",
        "image_urls": image_urls
    }).eq("id", script_id).execute()

    print(f"Done. {len(image_urls)} images generated and script status updated.")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
