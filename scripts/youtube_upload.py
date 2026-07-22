"""
Marius Command Center - YouTube Upload Agent
Takes the oldest script with status 'video_generated' and uploads its
final video to YouTube via the YouTube Data API v3, using a stored OAuth
refresh token (no browser interaction needed at runtime).

Uploads are set to 'public' - videos are fully live and discoverable
immediately on upload.

Sets status.containsSyntheticMedia = True on every upload, per YouTube's
Altered/Synthetic content disclosure requirement (API field added
2024-10-30) - required since every video here is AI-generated.

Also sets a custom thumbnail via thumbnails.set, using thumbnail_url from
the scripts row if video_generation.py produced one. Missing thumbnail
never blocks the upload itself - it's a best-effort step.
"""

import os
import requests

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SECRET_KEY"]
YOUTUBE_CLIENT_ID = os.environ["YOUTUBE_CLIENT_ID"]
YOUTUBE_CLIENT_SECRET = os.environ["YOUTUBE_CLIENT_SECRET"]
YOUTUBE_REFRESH_TOKEN = os.environ["YOUTUBE_REFRESH_TOKEN"]

HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
}

TOKEN_URL = "https://oauth2.googleapis.com/token"
UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos"
THUMBNAIL_SET_URL = "https://www.googleapis.com/upload/youtube/v3/thumbnails/set"


def get_access_token():
    resp = requests.post(
        TOKEN_URL,
        data={
            "client_id": YOUTUBE_CLIENT_ID,
            "client_secret": YOUTUBE_CLIENT_SECRET,
            "refresh_token": YOUTUBE_REFRESH_TOKEN,
            "grant_type": "refresh_token",
        },
        timeout=30,
    )
    if resp.status_code >= 400:
        print(f"TOKEN REFRESH ERROR {resp.status_code}: {resp.text}")
    resp.raise_for_status()
    return resp.json()["access_token"]


def get_next_ready_script():
    resp = requests.get(
        f"{SUPABASE_URL}/rest/v1/scripts?status=eq.video_generated&order=created_at.asc&limit=1",
        headers=HEADERS,
        timeout=30,
    )
    resp.raise_for_status()
    rows = resp.json()
    return rows[0] if rows else None


def get_topic_title(topic_id):
    resp = requests.get(
        f"{SUPABASE_URL}/rest/v1/topics?id=eq.{topic_id}&select=title",
        headers=HEADERS,
        timeout=30,
    )
    resp.raise_for_status()
    rows = resp.json()
    return rows[0]["title"] if rows else "Erased"


def download_file(url, out_path):
    r = requests.get(url, timeout=300)
    r.raise_for_status()
    with open(out_path, "wb") as f:
        f.write(r.content)
    return out_path


def build_description(narration_text):
    text = (narration_text or "").strip()
    limit = 1500
    if len(text) > limit:
        snippet = text[:limit]
        last_boundary = max(
            snippet.rfind(". "),
            snippet.rfind(".\n"),
            snippet.rfind("! "),
            snippet.rfind("? "),
        )
        if last_boundary > 0:
            snippet = snippet[: last_boundary + 1]
        else:
            last_space = snippet.rfind(" ")
            snippet = (snippet[:last_space] if last_space > 0 else snippet) + "..."
    else:
        snippet = text
    return (
        f"{snippet}\n\n"
        f"If this story moved you, subscribe - every episode of Erased "
        f"brings back a name history tried to bury.\n\n"
        f"#erased #history #documentary"
    )


def upload_to_youtube(access_token, video_path, title, description):
    metadata = {
        "snippet": {
            "title": title[:100],
            "description": description,
            "categoryId": "27",
        },
        "status": {
            "privacyStatus": "public",
            "selfDeclaredMadeForKids": False,
            # Required disclosure for AI-generated/altered realistic content.
            # Field added to the YouTube Data API v3 on 2024-10-30.
            "containsSyntheticMedia": True,
        },
    }

    file_size = os.path.getsize(video_path)

    init_resp = requests.post(
        f"{UPLOAD_URL}?uploadType=resumable&part=snippet,status",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json; charset=UTF-8",
            "X-Upload-Content-Type": "video/mp4",
            "X-Upload-Content-Length": str(file_size),
        },
        json=metadata,
        timeout=60,
    )
    if init_resp.status_code >= 400:
        print(f"UPLOAD INIT ERROR {init_resp.status_code}: {init_resp.text}")
    init_resp.raise_for_status()
    upload_url = init_resp.headers["Location"]

    with open(video_path, "rb") as f:
        file_bytes = f.read()

    put_resp = requests.put(
        upload_url,
        headers={
            "Content-Type": "video/mp4",
            "Content-Length": str(file_size),
        },
        data=file_bytes,
        timeout=600,
    )
    if put_resp.status_code >= 400:
        print(f"UPLOAD PUT ERROR {put_resp.status_code}: {put_resp.text}")
    put_resp.raise_for_status()
    return put_resp.json()["id"]


def set_thumbnail(access_token, youtube_id, thumbnail_path):
    """Best-effort: a thumbnail failure should never fail the whole upload,
    since the video itself already succeeded by the time this runs."""
    file_size = os.path.getsize(thumbnail_path)
    with open(thumbnail_path, "rb") as f:
        file_bytes = f.read()

    resp = requests.post(
        f"{THUMBNAIL_SET_URL}?videoId={youtube_id}",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "image/jpeg",
            "Content-Length": str(file_size),
        },
        data=file_bytes,
        timeout=60,
    )
    if resp.status_code >= 400:
        print(f"THUMBNAIL SET ERROR {resp.status_code}: {resp.text}")
        return False
    print("Custom thumbnail set.")
    return True


def mark_uploaded(script_id, youtube_id):
    resp = requests.patch(
        f"{SUPABASE_URL}/rest/v1/scripts?id=eq.{script_id}",
        headers=HEADERS,
        json={"status": "uploaded", "youtube_video_id": youtube_id},
        timeout=30,
    )
    resp.raise_for_status()


def main():
    script = get_next_ready_script()
    if not script:
        print("No videos ready for YouTube upload. Nothing to do.")
        return

    script_id = script["id"]
    print(f"Working on script {script_id}")

    if not script.get("video_url"):
        print("Script has no video_url yet. Skipping.")
        return

    title = get_topic_title(script["topic_id"])
    description = build_description(script.get("narration_text", ""))

    video_path = "/tmp/upload_video.mp4"
    download_file(script["video_url"], video_path)

    access_token = get_access_token()
    youtube_id = upload_to_youtube(access_token, video_path, title, description)
    print(f"Uploaded to YouTube (PUBLIC): https://youtube.com/watch?v={youtube_id}")

    thumbnail_url = script.get("thumbnail_url")
    if thumbnail_url:
        try:
            thumb_path = "/tmp/upload_thumbnail.jpg"
            download_file(thumbnail_url, thumb_path)
            set_thumbnail(access_token, youtube_id, thumb_path)
        except Exception as e:
            print(f"Thumbnail upload failed, video is still live without a custom thumbnail: {e}")
    else:
        print("No thumbnail_url on this script - skipping custom thumbnail.")

    mark_uploaded(script_id, youtube_id)
    print("Done.")


if __name__ == "__main__":
    main()
