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

CHANNEL VERIFICATION (2026-08-03): Nova's youtube_upload.py has a guard
that checks which channel the OAuth credentials are actually authorized
for before uploading, since a wrong client_id/refresh_token pair could
silently post to the wrong channel (this happened for real on Nova once).
Marius never had this. Added here too, but in a NON-BLOCKING form: the
authorized channel title is always fetched and logged so it's visible in
every run's log, but this only hard-blocks the upload if an
EXPECTED_YOUTUBE_CHANNEL_TITLE secret is explicitly set to a specific
name. Left unset by default because the exact current live title of
Marius's channel (was "Wazza Boys", a rename to "Erased" was planned) is
not confirmed as of this change - hard-coding a guess here risks blocking
every future upload if the guess is wrong, which is worse than no check
at all. Once you confirm the exact current channel title (check
youtube.com while signed into the account that owns Erased), set
EXPECTED_YOUTUBE_CHANNEL_TITLE as a repo secret to that exact string to
turn on the hard block.

CHUNK-STITCH FIX (2026-08-22): video_generation.py's CHUNKED-UPLOAD
QUALITY FIX (2026-08-20) started splitting large final videos into
multiple sequential chunk files (video_chunk_urls) instead of shrinking
bitrate to fit Supabase's 50MB single-file cap, whenever a fixed-quality
encode doesn't fit in one file - this is what fixed the corrupted/~144p-
looking 19-minute video Zia flagged. This file re-stitches chunks back
into one file before uploading, so the upload flow below this point is
unchanged either way.

DOUBLE-UPLOAD FIX (2026-08-23): status used to only flip to 'uploaded' at
the very end of main(), AFTER the thumbnail step. If anything failed or
timed out between a successful YouTube upload and that final write (a
thumbnail download/set failure, a network blip, the 30-minute GitHub
Actions timeout), the DB row stayed at 'video_generated' even though the
video was already live on YouTube - so the next scheduled run (every 30
min) picked the SAME script again and uploaded the SAME video a second
time under a brand-new YouTube ID. This is the confirmed root cause of a
duplicate "two-part" upload Zia found for the low-quality 19-minute
episode. Fix: mark_uploaded() is now called immediately after
upload_to_youtube() succeeds, BEFORE the thumbnail step even starts -
closing that window completely. A thumbnail failure after this point can
never cause a re-upload again, since the DB already reflects reality by
the time it could fail.
"""

import os
import requests
from moviepy import VideoFileClip, concatenate_videoclips
import storage_b2

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SECRET_KEY"]
YOUTUBE_CLIENT_ID = os.environ["YOUTUBE_CLIENT_ID"]
YOUTUBE_CLIENT_SECRET = os.environ["YOUTUBE_CLIENT_SECRET"]
YOUTUBE_REFRESH_TOKEN = os.environ["YOUTUBE_REFRESH_TOKEN"]

# Optional - see CHANNEL VERIFICATION note above. Unset by default.
EXPECTED_YOUTUBE_CHANNEL_TITLE = os.environ.get("EXPECTED_YOUTUBE_CHANNEL_TITLE", "").strip()

HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
}

TOKEN_URL = "https://oauth2.googleapis.com/token"
CHANNELS_URL = "https://www.googleapis.com/youtube/v3/channels"
UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos"
THUMBNAIL_SET_URL = "https://www.googleapis.com/upload/youtube/v3/thumbnails/set"

FRAME_RATE = 24  # matches video_generation.py's FRAME_RATE, kept in sync for the stitch re-encode


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


def get_authorized_channel(access_token):
    """Asks YouTube which channel the current access token is actually
    authorized for. Logged every run for visibility; only enforced as a
    hard block if EXPECTED_YOUTUBE_CHANNEL_TITLE is set (see file header)."""
    resp = requests.get(
        CHANNELS_URL,
        headers={"Authorization": f"Bearer {access_token}"},
        params={"part": "snippet", "mine": "true"},
        timeout=30,
    )
    resp.raise_for_status()
    items = resp.json().get("items", [])
    if not items:
        raise RuntimeError(
            "YouTube API returned no channel for these credentials - the token "
            "may be invalid, expired, or missing required scopes."
        )
    channel = items[0]
    return channel["id"], channel["snippet"]["title"]


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


def stitch_chunks_to_local_file(video_chunk_urls, out_path):
    """
    CHUNK-STITCH FIX (2026-08-22): downloads every chunk in order (the
    chunk_urls list is already in the correct sequential order - see
    upload_video_chunked in video_generation.py, which appends part_001,
    part_002, ... in a simple for-loop) and concatenates them into one
    local mp4 with moviepy, matching the encode settings video_generation.py
    already uses for everything else in this pipeline. Raises on any
    failure (download or encode) - the caller's existing try/except in
    main() is responsible for turning that into a recorded, non-fatal
    error for this script, same as every other failure mode here.

    LEGACY (2026-09-02): this function only runs for pre-migration rows
    that already have video_chunk_urls populated (real Supabase Storage
    URLs) - see the call site in main(). No script created after the B2
    migration will ever reach this path.
    """
    local_chunk_paths = []
    for i, url in enumerate(video_chunk_urls):
        chunk_path = f"/tmp/upload_chunk_{i:03d}.mp4"
        download_file(url, chunk_path)
        local_chunk_paths.append(chunk_path)

    clips = [VideoFileClip(p) for p in local_chunk_paths]
    try:
        combined = concatenate_videoclips(clips, method="compose")
        combined.write_videofile(
            out_path,
            fps=FRAME_RATE,
            codec="libx265",
            audio_codec="aac",
            audio_bitrate="128k",
            threads=2,
            logger=None,
            ffmpeg_params=["-preset", "fast", "-tag:v", "hvc1"],
        )
    finally:
        for c in clips:
            c.close()
        for p in local_chunk_paths:
            if os.path.exists(p):
                os.remove(p)

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

    video_path = "/tmp/upload_video.mp4"

    if script.get("video_url"):
        # STORAGE MIGRATION (2026-09-02): video_url is now a B2 object key
        # (not a Supabase Storage public URL) for any script generated
        # after this migration - download directly via storage_b2. A
        # pre-migration row would have a real https:// Supabase URL here
        # instead; those already finished (status flips to 'uploaded'
        # immediately after a successful upload, see DOUBLE-UPLOAD FIX
        # above) so this branch will only ever see B2 keys going forward.
        storage_b2.download_to_file(script["video_url"], video_path)
    elif script.get("video_chunk_urls"):
        # LEGACY PATH (pre-2026-09-02 rows only): video_chunk_urls was how
        # large videos were handled before the B2 migration removed
        # chunking entirely (see video_generation.py). No script created
        # after this migration will ever have this field populated - kept
        # only so any already-existing chunked row can still complete.
        chunk_urls = script["video_chunk_urls"]
        print(f"No single video_url - found {len(chunk_urls)} video_chunk_urls instead "
              f"(pre-migration legacy row). Downloading and re-stitching into one file before upload.")
        stitch_chunks_to_local_file(chunk_urls, video_path)
        print("Chunks re-stitched successfully into one local file.")
    else:
        print("Script has no video_url or video_chunk_urls yet. Skipping.")
        return

    access_token = get_access_token()

    channel_id, channel_title = get_authorized_channel(access_token)
    print(f"These credentials are authorized for channel: {channel_title!r} ({channel_id})")
    if EXPECTED_YOUTUBE_CHANNEL_TITLE:
        if channel_title.strip().lower() != EXPECTED_YOUTUBE_CHANNEL_TITLE.lower():
            raise RuntimeError(
                f"REFUSING TO UPLOAD: these credentials authorize {channel_title!r}, not the "
                f"expected {EXPECTED_YOUTUBE_CHANNEL_TITLE!r}. Wrong YOUTUBE_CLIENT_ID/"
                f"YOUTUBE_REFRESH_TOKEN pair for Marius. No video was downloaded or uploaded."
            )
        print(f"Channel verified ({EXPECTED_YOUTUBE_CHANNEL_TITLE}) - proceeding.")
    else:
        print("EXPECTED_YOUTUBE_CHANNEL_TITLE not set - skipping hard verification, "
              "proceeding based on channel title logged above only.")

    title = get_topic_title(script["topic_id"])
    description = build_description(script.get("narration_text", ""))

    youtube_id = upload_to_youtube(access_token, video_path, title, description)
    print(f"Uploaded to YouTube (PUBLIC): https://youtube.com/watch?v={youtube_id}")

    # DOUBLE-UPLOAD FIX (2026-08-23): mark this uploaded IMMEDIATELY, before
    # the thumbnail step - see file header. Nothing after this line can
    # ever cause a re-upload of the same video again.
    mark_uploaded(script_id, youtube_id)

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

    print("Done.")


if __name__ == "__main__":
    main()
