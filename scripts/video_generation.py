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

def generate_one_clip(client, supabase, script_id, image_urls, shot_list, video_urls, next_index):
    image_url = image_urls[next_index]
    prompt = get_shot_prompt(shot_list, next_index)

    print(f"Script id={script_id}, generating clip {next_index + 1}/{len(image_urls)}")
    print(f"Prompt: {prompt}")
    print(f"Source image: {image_url}")

    result = client.predict(
        prompt=prompt,
        negative_prompt="worst quality, inconsistent motion, blurry, jittery, distorted",
        input_image_filepath=handle_file(image_url),
        input_video_filepath=None,
        height_ui=512,
        width_ui=704,
        mode="image-to-video",
        duration_ui=2,
        ui_frames_to_use=9,
        seed_ui=42,
        randomize_seed=True,
        ui_guidance_scale=1,
        improve_texture_flag=True,
        api_name="/image_to_video",
    )

    video_path = None
    if isinstance(result, str):
        video_path = result
    elif isinstance(result, dict):
        video_path = result.get("video") or result.get("path") or result.get("name")
    elif isinstance(result, (list, tuple)) and len(result) > 0:
        first = result[0]
        video_path = first.get("video") if isinstance(first, dict) else first

    if not video_path or not os.path.exists(video_path):
        raise RuntimeError(f"Could not locate a valid output video file. Raw result: {result}")

    filename = f"{script_id}_clip_{next_index + 1}.mp4"
    with open(video_path, "rb") as f:
        supabase.storage.from_("video_clips").upload(
            filename,
            f,
            {"content-type": "video/mp4", "upsert": "true"}
        )

    public_url = supabase.storage.from_("video_clips").get_public_url(filename)
    return public_url


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

    client = Client(SPACE_NAME)

    failures = 0
    while next_index < len(image_urls):
        try:
            public_url = generate_one_clip(client, supabase, script_id, image_urls, shot_list, video_urls, next_index)
        except Exception as e:
            failures += 1
            print(f"Clip {next_index + 1}/{len(image_urls)} FAILED: {e}")
            if failures >= 3:
                print("3 consecutive-ish failures reached this run — stopping early, progress saved so far.")
                break
            next_index += 1  # skip this shot for now rather than getting stuck forever; revisit later if needed
            continue

        video_urls.append(public_url)
        next_index += 1

        # Save progress after EVERY clip — same safety pattern as the Nova/Silk Road fix
        update_data = {
            "video_urls": video_urls,
            "video_next_index": next_index,
            "status": "videos_generated" if next_index >= len(image_urls) else "video_in_progress"
        }
        supabase.table("scripts").update(update_data).eq("id", script_id).execute()
        print(f"Uploaded clip {next_index}/{len(image_urls)}: {public_url}")

    print(f"Run finished. {next_index}/{len(image_urls)} clips done overall. Failures this run: {failures}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
