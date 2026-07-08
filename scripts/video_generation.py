import os
import sys
import json
import requests
from supabase import create_client
from gradio_client import Client, handle_file

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_SECRET_KEY = os.environ["SUPABASE_SECRET_KEY"]

SPACE_NAME = "Lightricks/ltx-video-distilled"

def get_shot_prompt(shot_list, index):
    if not isinstance(shot_list, list) or index >= len(shot_list):
        return "cinematic, gentle camera movement, documentary style"
    shot = shot_list[index]
    if isinstance(shot, dict):
        base = shot.get("visual_description") or shot.get("description") or ""
    elif isinstance(shot, str):
        base = shot
    else:
        base = ""
    return f"{base}. Cinematic, gentle camera movement, documentary film style."

def main():
    supabase = create_client(SUPABASE_URL, SUPABASE_SECRET_KEY)

    result = supabase.table("scripts").select("*").in_("status", ["images_generated", "video_in_progress"]).limit(1).execute()
    if not result.data:
        print("No scripts ready for video generation. Exiting.")
        return

    script = result.data[0]
    script_id = script["id"]
    image_urls = script.get("image_urls") or []
    shot_list = script.get("shot_list") or []
    video_urls = script.get("video_urls") or []
    next_index = script.get("video_next_index") or 0

    if next_index >= len(image_urls):
        supabase.table("scripts").update({"status": "videos_generated"}).eq("id", script_id).execute()
        print(f"All {len(image_urls)} clips already generated for script {script_id}. Status updated.")
        return

    image_url = image_urls[next_index]
    prompt = get_shot_prompt(shot_list, next_index)

    print(f"Script id={script_id}, generating clip {next_index + 1}/{len(image_urls)}")
    print(f"Prompt: {prompt}")
    print(f"Source image: {image_url}")

    client = Client(SPACE_NAME)

    try:
        result = client.predict(
            handle_file(image_url),
            prompt,
            "",  # negative_prompt
            api_name="/predict"
        )
    except Exception as e:
        print(f"First attempt failed: {e}")
        print("Printing full API schema for this Space so we can fix parameter names:")
        try:
            client.view_api()
        except Exception as inner_e:
            print(f"Could not fetch API schema either: {inner_e}")
        sys.exit(1)

    # result is typically a filepath or dict containing a filepath, depending on the Space's output component
    video_path = None
    if isinstance(result, str):
        video_path = result
    elif isinstance(result, dict):
        video_path = result.get("video") or result.get("path") or result.get("name")
    elif isinstance(result, (list, tuple)) and len(result) > 0:
        first = result[0]
        video_path = first.get("video") if isinstance(first, dict) else first

    if not video_path or not os.path.exists(video_path):
        print(f"Could not locate a valid output video file. Raw result: {result}")
        sys.exit(1)

    filename = f"{script_id}_clip_{next_index + 1}.mp4"
    with open(video_path, "rb") as f:
        supabase.storage.from_("video_clips").upload(
            filename,
            f,
            {"content-type": "video/mp4", "upsert": "true"}
        )

    public_url = supabase.storage.from_("video_clips").get_public_url(filename)
    video_urls.append(public_url)
    new_index = next_index + 1

    update_data = {
        "video_urls": video_urls,
        "video_next_index": new_index,
        "status": "videos_generated" if new_index >= len(image_urls) else "video_in_progress"
    }
    supabase.table("scripts").update(update_data).eq("id", script_id).execute()

    print(f"Uploaded clip {new_index}/{len(image_urls)}: {public_url}")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
