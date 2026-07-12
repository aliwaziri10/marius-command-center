"""
Marius Command Center - Thumbnail Generation Agent
Picks the oldest script that has a finished video but no thumbnail yet,
pulls a real frame directly out of that finished video as the background
(the same idea YouTube Studio's own auto-suggested thumbnails use - an
actual frame from the footage, not an unrelated AI-generated image),
overlays bold hook text via Pillow (text is composited locally, not
AI-rendered, since AI image models render text unreliably), and uploads
the result to the 'thumbnails' bucket.

HOOK TEXT SOURCE: uses the script's own hook_text column if present.
Falls back to shot 1's narration_excerpt (the "STAKE" fact - see the
OPENING HOOK structure in script_writing.py's prompt) trimmed to a legible
thumbnail length, for older scripts written before hook_text existed.

PHRASE-PER-LINE: hook_text is written as short punctuation-separated
fragments (e.g. "312 DIARIES. ONE BOMB. GONE IN SECONDS."). Each fragment
gets its own line rather than being greedily word-wrapped across lines,
so the layout reads the way it was written.

CANVAS-SAFE: the extracted video frame is force-fit to the exact target
canvas (cover-crop resize: scale to fill, then center-crop, no
stretching) before any text layout happens, so the overlay math is
always working against the real image dimensions.

LIVE-VIDEO PUSH: if the script this runs on is already 'uploaded' (has a
youtube_video_id), the freshly generated thumbnail is also pushed directly
to the live YouTube video via thumbnails.set, not just saved to Supabase -
see push_thumbnail_to_youtube().
"""

import os
import re
import sys
import json
import requests
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont
from moviepy import VideoFileClip
from supabase import create_client

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_SECRET_KEY = os.environ["SUPABASE_SECRET_KEY"]

# Only needed to push a regenerated thumbnail to an already-uploaded YouTube
# video (see push_thumbnail_to_youtube below). Optional: if these aren't set,
# that step is skipped and everything else still works normally.
YOUTUBE_CLIENT_ID = os.environ.get("YOUTUBE_CLIENT_ID")
YOUTUBE_CLIENT_SECRET = os.environ.get("YOUTUBE_CLIENT_SECRET")
YOUTUBE_REFRESH_TOKEN = os.environ.get("YOUTUBE_REFRESH_TOKEN")

YOUTUBE_TOKEN_URL = "https://oauth2.googleapis.com/token"
YOUTUBE_THUMBNAIL_SET_URL = "https://www.googleapis.com/upload/youtube/v3/thumbnails/set"

IMAGE_WIDTH = 1280
IMAGE_HEIGHT = 720
FRAME_FRACTION = 0.2  # pull the background frame from 20% into the episode -
                       # past the cold-open beat, before it settles into
                       # slower narrative shots

FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
MAX_HOOK_CHARS = 60  # keeps overlay text legible at thumbnail size

MAX_FONT_SIZE = 44   # was 88 - cut 50% per feedback, text was overwhelming the frame
MIN_FONT_SIZE = 20   # was 40 - cut 50%
FONT_SIZE_STEP = 2
TEXT_MARGIN = 48
LINE_SPACING = 10
STROKE_WIDTH = 3     # was 6 - scaled down with the smaller font
TEXT_COLOR = (255, 214, 0)       # high-visibility yellow, reads well on any bg
STROKE_COLOR = (0, 0, 0)
MAX_TEXT_BLOCK_HEIGHT = int(IMAGE_HEIGHT * 0.20)  # was 0.42 - text now takes
                                                   # a fifth of the frame, not
                                                   # nearly half


def download_video_frame(video_url, fraction=FRAME_FRACTION):
    """Downloads the finished episode video and grabs a real frame from it
    to use as the thumbnail background - the same approach YouTube
    Studio's auto-suggested thumbnails use. Looks far more coherent than a
    separately AI-generated background with no relation to the actual
    footage."""
    tmp_path = "/tmp/thumb_source.mp4"
    r = requests.get(video_url, timeout=120)
    r.raise_for_status()
    with open(tmp_path, "wb") as f:
        f.write(r.content)

    clip = VideoFileClip(tmp_path)
    t = max(0.0, min(clip.duration * fraction, clip.duration - 0.1))
    frame = clip.get_frame(t)
    clip.close()
    os.remove(tmp_path)
    return Image.fromarray(frame).convert("RGB")


def resize_to_canvas(img, target_w, target_h):
    """Force-fits img to exactly (target_w, target_h) via a cover-crop:
    scale up/down so the image fully covers the target box, then crop
    the center - no stretching or distortion."""
    src_w, src_h = img.size
    if (src_w, src_h) == (target_w, target_h):
        return img
    scale = max(target_w / src_w, target_h / src_h)
    new_w, new_h = int(src_w * scale + 0.5), int(src_h * scale + 0.5)
    img = img.resize((new_w, new_h), Image.LANCZOS)
    left = (new_w - target_w) // 2
    top = (new_h - target_h) // 2
    return img.crop((left, top, left + target_w, top + target_h))


def derive_hook_text(script, shot_list):
    """Prefers a real hook_text column value. Falls back to shot 1's
    narration_excerpt (the STAKE fact) trimmed to a legible length, for
    scripts written before hook_text existed."""
    hook_text = (script.get("hook_text") or "").strip()
    if hook_text:
        return hook_text[:MAX_HOOK_CHARS].rstrip()

    if shot_list:
        first_excerpt = (shot_list[0].get("narration_excerpt") or "").strip()
        if first_excerpt:
            if len(first_excerpt) <= MAX_HOOK_CHARS:
                return first_excerpt
            return first_excerpt[:MAX_HOOK_CHARS].rsplit(" ", 1)[0] + "..."

    return ""


def split_into_phrase_lines(text):
    """Splits hook text on sentence-ending punctuation so each written
    fragment ("312 DIARIES." / "ONE BOMB." / "GONE IN SECONDS.") becomes
    its own line, instead of letting greedy word-wrap recombine them
    however the width happens to allow."""
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return [p.strip() for p in parts if p.strip()]


def _line_bbox(draw, text, font):
    """Bounding box that includes the stroke outline, so width/height
    measurements match what actually gets rendered."""
    return draw.textbbox((0, 0), text, font=font, stroke_width=STROKE_WIDTH)


def wrap_text(text, font, draw, max_width):
    """Greedy word wrap, used as a fallback within a single phrase if
    that phrase alone is still too wide for the frame."""
    words = text.split()
    lines = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        bbox = _line_bbox(draw, candidate, font)
        if bbox[2] - bbox[0] <= max_width or not current:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def fits(lines, font, draw, max_width, max_height):
    max_line_width = 0
    line_heights = []
    for line in lines:
        bbox = _line_bbox(draw, line, font)
        w = bbox[2] - bbox[0]
        h = bbox[3] - bbox[1]
        max_line_width = max(max_line_width, w)
        line_heights.append(h)
    total_height = sum(line_heights) + LINE_SPACING * max(0, len(lines) - 1)
    return max_line_width <= max_width and total_height <= max_height


def fit_text_to_frame(hook_text, draw, max_width, max_height):
    """Try progressively smaller font sizes until the phrase-per-line
    text fits entirely within the available width/height. Each written
    phrase is kept on its own line; a phrase only gets word-wrapped
    further if it's still too wide on its own at the current size."""
    text = hook_text.upper()
    phrases = split_into_phrase_lines(text) or [text]
    size = MAX_FONT_SIZE
    while size >= MIN_FONT_SIZE:
        font = ImageFont.truetype(FONT_PATH, size)
        lines = []
        for phrase in phrases:
            lines.extend(wrap_text(phrase, font, draw, max_width))
        if fits(lines, font, draw, max_width, max_height):
            return font, lines
        size -= FONT_SIZE_STEP

    font = ImageFont.truetype(FONT_PATH, MIN_FONT_SIZE)
    lines = []
    for phrase in phrases:
        lines.extend(wrap_text(phrase, font, draw, max_width))
    return font, lines


def overlay_hook_text(img, hook_text):
    img = resize_to_canvas(img, IMAGE_WIDTH, IMAGE_HEIGHT)

    if not hook_text:
        out = BytesIO()
        img.save(out, format="JPEG", quality=92)
        return out.getvalue()

    draw = ImageDraw.Draw(img)

    max_text_width = IMAGE_WIDTH - (TEXT_MARGIN * 2)
    font, lines = fit_text_to_frame(hook_text, draw, max_text_width, MAX_TEXT_BLOCK_HEIGHT)

    line_heights = []
    for line in lines:
        bbox = _line_bbox(draw, line, font)
        line_heights.append(bbox[3] - bbox[1])
    total_text_height = sum(line_heights) + LINE_SPACING * (len(lines) - 1)

    y = IMAGE_HEIGHT - TEXT_MARGIN - total_text_height
    for i, line in enumerate(lines):
        bbox = _line_bbox(draw, line, font)
        line_width = bbox[2] - bbox[0]
        x = (IMAGE_WIDTH - line_width) / 2 - bbox[0]
        draw.text(
            (x, y),
            line,
            font=font,
            fill=TEXT_COLOR,
            stroke_width=STROKE_WIDTH,
            stroke_fill=STROKE_COLOR,
        )
        y += line_heights[i] + LINE_SPACING

    out = BytesIO()
    img.save(out, format="JPEG", quality=92)
    return out.getvalue()


def push_thumbnail_to_youtube(youtube_video_id, image_bytes):
    """Pushes a thumbnail directly to an already-live YouTube video.
    youtube_upload.py only sets a thumbnail at the moment of upload - once
    a script's status is 'uploaded', nothing else ever calls thumbnails.set
    again. Without this, any thumbnail regenerated after upload (bug fixes,
    quality improvements, a backfilled hook_text, etc.) sits unused in
    Supabase forever while the live video keeps its original thumbnail.
    Best-effort: failures here are logged but never raised, since the
    thumbnail row in Supabase has already been updated successfully by the
    time this runs, and a failed push shouldn't be treated as a fatal error."""
    if not (YOUTUBE_CLIENT_ID and YOUTUBE_CLIENT_SECRET and YOUTUBE_REFRESH_TOKEN):
        print("YouTube credentials not configured - skipping push to live video.")
        return False

    try:
        token_resp = requests.post(
            YOUTUBE_TOKEN_URL,
            data={
                "client_id": YOUTUBE_CLIENT_ID,
                "client_secret": YOUTUBE_CLIENT_SECRET,
                "refresh_token": YOUTUBE_REFRESH_TOKEN,
                "grant_type": "refresh_token",
            },
            timeout=30,
        )
        token_resp.raise_for_status()
        access_token = token_resp.json()["access_token"]

        set_resp = requests.post(
            f"{YOUTUBE_THUMBNAIL_SET_URL}?videoId={youtube_video_id}",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "image/jpeg",
                "Content-Length": str(len(image_bytes)),
            },
            data=image_bytes,
            timeout=60,
        )
        if set_resp.status_code >= 400:
            print(f"YouTube thumbnail push failed ({set_resp.status_code}): {set_resp.text}")
            return False

        print(f"Pushed thumbnail directly to live YouTube video {youtube_video_id}.")
        return True
    except Exception as e:
        print(f"YouTube thumbnail push failed: {e}")
        return False


def main():
    supabase = create_client(SUPABASE_URL, SUPABASE_SECRET_KEY)

    result = (
        supabase.table("scripts")
        .select("*")
        .in_("status", ["video_generated", "uploaded"])
        .is_("thumbnail_url", "null")
        .order("created_at", desc=False)
        .limit(1)
        .execute()
    )
    if not result.data:
        print("No scripts need a thumbnail. Exiting.")
        return

    script = result.data[0]
    script_id = script["id"]
    shot_list = script.get("shot_list")
    if isinstance(shot_list, str):
        shot_list = json.loads(shot_list)

    print(f"Generating thumbnail for script id={script_id}")

    video_url = script.get("video_url")
    if not video_url:
        print("Script has no finished video yet. Cannot pull a thumbnail frame. Exiting.")
        return

    hook_text = derive_hook_text(script, shot_list or [])
    print(f"Hook text: {hook_text!r}")

    background_img = download_video_frame(video_url)
    final_bytes = overlay_hook_text(background_img, hook_text)

    filename = f"{script_id}.jpg"
    supabase.storage.from_("thumbnails").upload(
        filename,
        final_bytes,
        {"content-type": "image/jpeg", "upsert": "true"}
    )
    public_url = supabase.storage.from_("thumbnails").get_public_url(filename)
    print(f"Uploaded thumbnail: {public_url}")

    supabase.table("scripts").update({"thumbnail_url": public_url}).eq("id", script_id).execute()

    youtube_video_id = script.get("youtube_video_id")
    if script.get("status") == "uploaded" and youtube_video_id:
        push_thumbnail_to_youtube(youtube_video_id, final_bytes)

    print("Done.")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
