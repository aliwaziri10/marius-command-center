"""
Marius Command Center - Thumbnail Generation Agent
Picks the oldest script that has a finished video but no thumbnail yet,
generates a vibrant, high-contrast background image (same Pollinations.ai
source used by image_generation.py, for consistency), overlays bold hook
text via Pillow (text is composited locally, not AI-rendered, since AI
image models render text unreliably), and uploads the result to the
'thumbnails' bucket.

HOOK TEXT SOURCE: uses the script's own hook_text column if present.
Falls back to shot 1's narration_excerpt (the "STAKE" fact - see the
OPENING HOOK structure in script_writing.py's prompt) trimmed to a legible
thumbnail length, for older scripts written before hook_text existed.
"""

import os
import sys
import json
import urllib.parse
import requests
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont
from supabase import create_client

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_SECRET_KEY = os.environ["SUPABASE_SECRET_KEY"]

POLLINATIONS_BASE = "https://image.pollinations.ai/prompt"
IMAGE_WIDTH = 1280
IMAGE_HEIGHT = 720

FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
MAX_HOOK_CHARS = 60  # keeps overlay text legible at thumbnail size

MAX_FONT_SIZE = 88
MIN_FONT_SIZE = 40
FONT_SIZE_STEP = 4
TEXT_MARGIN = 48
LINE_SPACING = 12
STROKE_WIDTH = 6
TEXT_COLOR = (255, 214, 0)       # high-visibility yellow, reads well on any bg
STROKE_COLOR = (0, 0, 0)
MAX_TEXT_BLOCK_HEIGHT = int(IMAGE_HEIGHT * 0.42)  # cap how much vertical space text can take


def generate_background_image(prompt, seed=0):
    """Same Pollinations.ai call pattern as image_generation.py, with a
    thumbnail-specific style boost tuned for high click-through: vivid,
    saturated color rather than a desaturated/moody grade, since
    high-contrast color thumbnails consistently outperform grayscale or
    muted ones on YouTube."""
    styled_prompt = (
        f"{prompt}, cinematic YouTube thumbnail, vivid saturated colors, "
        f"bold dramatic lighting, high contrast, punchy color grade, sharp focus"
    )
    encoded_prompt = urllib.parse.quote(styled_prompt)
    url = f"{POLLINATIONS_BASE}/{encoded_prompt}"
    params = {
        "width": IMAGE_WIDTH,
        "height": IMAGE_HEIGHT,
        "seed": seed,
        "nologo": "true",
    }
    r = requests.get(url, params=params, timeout=60)
    r.raise_for_status()
    return r.content


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


def _line_bbox(draw, text, font):
    """Bounding box that includes the stroke outline, so width/height
    measurements match what actually gets rendered."""
    return draw.textbbox((0, 0), text, font=font, stroke_width=STROKE_WIDTH)


def wrap_text(text, font, draw, max_width):
    """Greedy word wrap. If a single word is still wider than max_width
    on its own, it's kept on its own line rather than silently overflowing
    - the caller is responsible for shrinking the font until it fits."""
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
    total_height = 0
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
    """Try progressively smaller font sizes until the wrapped text fits
    entirely within the available width/height, so text can never be cut
    off at the edges. Falls back to the smallest size (still wrapped) if
    nothing fits perfectly, rather than overflowing."""
    text = hook_text.upper()
    size = MAX_FONT_SIZE
    while size >= MIN_FONT_SIZE:
        font = ImageFont.truetype(FONT_PATH, size)
        lines = wrap_text(text, font, draw, max_width)
        if fits(lines, font, draw, max_width, max_height):
            return font, lines
        size -= FONT_SIZE_STEP

    font = ImageFont.truetype(FONT_PATH, MIN_FONT_SIZE)
    lines = wrap_text(text, font, draw, max_width)
    return font, lines


def overlay_hook_text(image_bytes, hook_text):
    if not hook_text:
        return image_bytes

    img = Image.open(BytesIO(image_bytes)).convert("RGB")
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

    if not shot_list:
        print("No shot_list found. Cannot generate thumbnail. Exiting.")
        return

    background_prompt = shot_list[0].get("visual_description", "").strip()
    if not background_prompt:
        print("Shot 1 has no visual_description. Cannot generate thumbnail. Exiting.")
        return

    hook_text = derive_hook_text(script, shot_list)
    print(f"Hook text: {hook_text!r}")

    image_bytes = generate_background_image(background_prompt, seed=0)
    final_bytes = overlay_hook_text(image_bytes, hook_text)

    filename = f"{script_id}.jpg"
    supabase.storage.from_("thumbnails").upload(
        filename,
        final_bytes,
        {"content-type": "image/jpeg", "upsert": "true"}
    )
    public_url = supabase.storage.from_("thumbnails").get_public_url(filename)
    print(f"Uploaded thumbnail: {public_url}")

    supabase.table("scripts").update({"thumbnail_url": public_url}).eq("id", script_id).execute()
    print("Done.")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
