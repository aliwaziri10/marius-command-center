"""
Marius Command Center - Thumbnail Generation Agent
Picks the oldest script that has a finished video but no thumbnail yet,
generates a dramatic background image (same Pollinations.ai source used by
image_generation.py, for consistency), overlays bold hook text via Pillow
(text is composited locally, not AI-rendered, since AI image models render
text unreliably), and uploads the result to the 'thumbnails' bucket.

HOOK TEXT SOURCE: uses the script's own hook_text column if present.
Falls back to shot 1's narration_excerpt (the "STAKE" fact - see the
OPENING HOOK structure in script_writing.py's prompt) since no current
code populates hook_text yet. Long fallback text is trimmed to a legible
thumbnail length.
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
FONT_SIZE = 88
TEXT_MARGIN = 48
LINE_SPACING = 12
STROKE_WIDTH = 6


def generate_background_image(prompt, seed=0):
    """Same Pollinations.ai call pattern as image_generation.py, with a
    thumbnail-specific style boost for higher visual impact."""
    styled_prompt = f"{prompt}, cinematic YouTube thumbnail, dramatic high-contrast lighting, moody, film grain"
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
    narration_excerpt (the STAKE fact) trimmed to a legible length, since
    no script-writing code currently populates hook_text."""
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


def wrap_text(text, font, draw, max_width):
    words = text.split()
    lines = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        bbox = draw.textbbox((0, 0), candidate, font=font)
        if bbox[2] - bbox[0] <= max_width or not current:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def overlay_hook_text(image_bytes, hook_text):
    if not hook_text:
        return image_bytes

    img = Image.open(BytesIO(image_bytes)).convert("RGB")
    draw = ImageDraw.Draw(img)
    font = ImageFont.truetype(FONT_PATH, FONT_SIZE)

    max_text_width = IMAGE_WIDTH - (TEXT_MARGIN * 2)
    lines = wrap_text(hook_text.upper(), font, draw, max_text_width)

    line_heights = []
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        line_heights.append(bbox[3] - bbox[1])
    total_text_height = sum(line_heights) + LINE_SPACING * (len(lines) - 1)

    y = IMAGE_HEIGHT - TEXT_MARGIN - total_text_height
    for i, line in enumerate(lines):
        bbox = draw.textbbox((0, 0), line, font=font)
        line_width = bbox[2] - bbox[0]
        x = (IMAGE_WIDTH - line_width) / 2
        draw.text(
            (x, y),
            line,
            font=font,
            fill=(255, 255, 255),
            stroke_width=STROKE_WIDTH,
            stroke_fill=(0, 0, 0),
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
