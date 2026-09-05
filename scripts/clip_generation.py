"""
Marius Command Center - clip generation (split from video_generation.py,
2026-09-06, same pattern as the 2026-08-18 script_writing.py split).

Everything that produces an actual shot clip: the character-reference
image (dormant continuity feature, kept for a possible future
single-protagonist format), the continuity-anchor lookup, single-segment
generation against Agnes (with the 3-tier content-policy fallback), the
chain-extension logic for shots longer than one Agnes generation can
produce, and the freeze-hold fit-to-duration fallback. Imports the Agnes
HTTP contract from agnes_client.py and the prompt-building logic from
prompt_builder.py rather than owning either.
"""

import os
import time
import requests
from PIL import Image
from moviepy import VideoFileClip, concatenate_videoclips

import storage_b2
from agnes_client import (
    AGNES_HEADERS,
    AGNES_IMAGE_URL,
    AGNES_RETRYABLE_CODES,
    AGNES_IMAGE_MAX_RETRIES,
    AGNES_MAX_RETRIES,
    WIDTH,
    HEIGHT,
    FRAME_RATE,
    MIN_FRAMES,
    MAX_FRAMES,
    MAX_CLIP_SECONDS,
    ContentPolicyRejection,
    AgnesOverloadedError,
    round_to_valid_frames,
    create_agnes_task,
    poll_agnes_task,
)
from prompt_builder import build_agnes_prompt, build_character_reference_prompt

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SECRET_KEY"]

HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
}

# SMOOTH-EXTENSION FIX (2026-08-01): when a shot (or the final trail) needs
# more duration than one Agnes generation can produce (MAX_CLIP_SECONDS),
# this used to freeze the last frame for the remainder - visible as a
# "stuck" still image, happening at every sentence-boundary pause across
# an episode plus every single video's outro. MAX_CHAIN_SEGMENTS caps how
# many additional REAL Agnes clips we'll chain (each anchored to the
# previous clip's own last frame, same mechanism as cross-shot continuity)
# to cover the overflow with real motion instead.
#
# CHAIN-BUDGET FIX (2026-08-23): 3 segments (~21s of overflow, ~28s total
# per shot) was sized for short pauses, but confirmed live on the Bosnia
# episode (script 40ffc83c, 33 shots / ~19min = ~35s per shot average) -
# almost every shot in a real full-length episode needs MORE than 28s
# total, so nearly every shot was hitting the chain-budget ceiling and
# silently freeze-holding the remainder, exactly matching Zia's report of
# "multiple freeze frames, narrator keeps speaking." Raised to 6 segments
# (~42s of overflow, ~49s total per shot) to comfortably cover this
# format's real average shot length with headroom, not just short pauses.
MAX_CHAIN_SEGMENTS = 6


def download_file(url, out_path):
    r = requests.get(url, timeout=120)
    r.raise_for_status()
    with open(out_path, "wb") as f:
        f.write(r.content)
    return out_path


def upload_reference_image(script_id, file_name, local_path):
    """Returns the B2 object KEY (not a URL) - see storage_b2.py docstring
    for why. Callers that need to hand this to Agnes (which requires a
    real fetchable URL) must call storage_b2.presigned_url() on the
    result themselves, right before the Agnes call."""
    dest = f"{script_id}/refs/{file_name}"
    try:
        return storage_b2.upload_file(dest, local_path, content_type="image/png")
    except Exception as e:
        print(f"Reference frame upload failed: {e}")
        return None


def generate_character_reference(script):
    """
    Generates ONE reference image per script (via agnes-image-2.1-flash),
    anchored to the episode's setting_and_characters text, so every shot's
    video call has a consistent character/setting to hold onto instead of
    starting blind. Persists the result to scripts.character_reference_url
    so this only ever runs once per script, even across resumed runs.
    Returns None (and skips silently) if there's no setting_and_characters
    text to anchor to, or if Agnes's image endpoint fails after retries -
    the pipeline still works without it, just without the consistency
    boost.

    DORMANT since 2026-08-18 (see CONTINUITY-CHAIN REMOVED in
    video_generation.py's original file header) - no longer called from
    process_script's per-shot loop. Left defined in case cross-shot
    chaining is wanted back for a future single-protagonist format.
    """
    script_id = script["id"]
    existing = script.get("character_reference_url")
    if existing:
        return existing

    anchor = (script.get("setting_and_characters") or "").strip()
    if not anchor:
        print("No setting_and_characters text on this script - skipping character reference image.")
        return None

    prompt = build_character_reference_prompt(anchor)
    last_error_text = None

    for attempt in range(AGNES_IMAGE_MAX_RETRIES):
        try:
            resp = requests.post(
                AGNES_IMAGE_URL,
                headers=AGNES_HEADERS,
                json={
                    "model": "agnes-image-2.1-flash",
                    "prompt": prompt,
                    "size": f"{WIDTH}x{HEIGHT}",
                    "extra_body": {"response_format": "url"},
                },
                timeout=60,
            )
        except requests.RequestException as e:
            last_error_text = str(e)
            print(f"Character reference image request raised an exception (attempt {attempt + 1}/{AGNES_IMAGE_MAX_RETRIES}): {e}")
            time.sleep(10 * (attempt + 1))
            continue

        if resp.status_code in AGNES_RETRYABLE_CODES:
            last_error_text = resp.text
            print(f"Character reference image transient error {resp.status_code} (attempt {attempt + 1}/{AGNES_IMAGE_MAX_RETRIES}): {resp.text}")
            time.sleep(10 * (attempt + 1))
            continue

        if resp.status_code >= 400:
            print(f"Character reference image generation failed permanently ({resp.status_code}): {resp.text} - continuing without a reference image.")
            return None

        data = resp.json()
        image_url = None
        for entry in data.get("data", []):
            if isinstance(entry, dict) and entry.get("url"):
                image_url = entry["url"]
                break
        if not image_url:
            image_url = data.get("url")

        if not image_url:
            print(f"Character reference image response had no usable URL: {data} - continuing without a reference image.")
            return None

        resp2 = requests.patch(
            f"{SUPABASE_URL}/rest/v1/scripts?id=eq.{script_id}",
            headers=HEADERS,
            json={"character_reference_url": image_url},
            timeout=30,
        )
        resp2.raise_for_status()
        print(f"Character reference image generated and saved for script {script_id}.")
        return image_url

    print(f"Character reference image generation exhausted all retries ({last_error_text}) - continuing without one.")
    return None


def extract_last_frame_url(script_id, shot_index, local_video_path):
    """
    Pulls the final frame of a just-generated (or already-downloaded) shot
    clip and uploads it as a small PNG, so it can be passed as the "image"
    anchor for the NEXT shot's Agnes call - this is what chains shots
    together visually instead of each one being generated blind. Fails
    soft (returns None) on any error, same fail-soft pattern as
    music/SFX/captions elsewhere in this pipeline - continuity is a
    quality improvement, not something that should ever crash a run.

    DORMANT since 2026-08-18 - no longer called from process_script's
    per-shot loop. Left defined in case cross-shot chaining is wanted
    back for a future single-protagonist format.
    """
    try:
        clip = VideoFileClip(local_video_path)
        frame = clip.get_frame(max(clip.duration - 1 / FRAME_RATE, 0))
        clip.close()
        img = Image.fromarray(frame)
        png_path = local_video_path.replace(".mp4", "_lastframe.png")
        img.save(png_path)
        url = upload_reference_image(script_id, f"shot_{shot_index:03d}_lastframe.png", png_path)
        os.remove(png_path)
        return url
    except Exception as e:
        print(f"Could not extract/upload last frame for shot {shot_index}, continuing without a continuity anchor for the next shot: {e}")
        return None


def get_continuity_anchor(script, video_urls):
    """
    Reconstructs the correct anchor image for the NEXT shot to generate:
    - if at least one shot is already done, downloads the most recently
      completed clip and extracts its last frame (this is what makes
      continuity survive across resumed runs, not just within one run)
    - otherwise falls back to the script's character reference image
      (generating it if it doesn't exist yet)

    DORMANT since 2026-08-18 - no longer called from process_script's
    per-shot loop. Left defined in case cross-shot chaining is wanted
    back for a future single-protagonist format.

    STORAGE MIGRATION (2026-09-02): video_urls entries are now B2 object
    keys, not URLs (see storage_b2.py) - uses storage_b2.download_to_file
    directly rather than an HTTP download of a stored URL.
    """
    if video_urls:
        try:
            tmp_path = "/tmp/_anchor_source.mp4"
            storage_b2.download_to_file(video_urls[-1], tmp_path)
            url = extract_last_frame_url(script["id"], len(video_urls) - 1, tmp_path)
            os.remove(tmp_path)
            if url:
                return url
        except Exception as e:
            print(f"Could not rebuild continuity anchor from the last completed clip, falling back to character reference: {e}")

    return generate_character_reference(script)


def _generate_one_segment(shot, segment_duration, out_path, setting_and_characters="", anchor_image_url=None):
    raw_frames = int(segment_duration * FRAME_RATE)
    raw_frames = max(MIN_FRAMES, min(MAX_FRAMES, raw_frames))
    num_frames = round_to_valid_frames(raw_frames)
    num_frames = max(MIN_FRAMES, min(MAX_FRAMES, num_frames))

    prompt = build_agnes_prompt(shot, setting_and_characters, fallback_level=0)
    try:
        video_id = create_agnes_task(prompt, num_frames, image_url=anchor_image_url)
    except ContentPolicyRejection:
        print("Content policy rejection on primary prompt - retrying with sanitized-anchor fallback "
              "(tier 1, image anchor also dropped this attempt)...")
        try:
            fallback_prompt = build_agnes_prompt(shot, setting_and_characters, fallback_level=1)
            video_id = create_agnes_task(fallback_prompt, num_frames, image_url=None)
        except ContentPolicyRejection:
            print("Sanitized-anchor fallback ALSO rejected - retrying once more with a fully generic, "
                  "anchor-free prompt AND no image anchor (tier 2, last resort before giving up on this shot)...")
            ultra_prompt = build_agnes_prompt(shot, setting_and_characters, fallback_level=2)
            video_id = create_agnes_task(ultra_prompt, num_frames, image_url=None)

    video_url = poll_agnes_task(video_id)
    download_file(video_url, out_path)
    return out_path


def _extract_last_frame_local(video_path):
    """Extracts the last frame of a local clip file and uploads it nowhere -
    returns a local PNG path for immediate reuse as the next Agnes anchor
    within the same shot's chain-extension. Separate from
    extract_last_frame_url (which uploads to storage) because chain
    segments are purely intra-shot and never need to survive a resumed run."""
    clip = VideoFileClip(video_path)
    frame = clip.get_frame(max(clip.duration - 1 / FRAME_RATE, 0))
    clip.close()
    png_path = video_path.replace(".mp4", "_lastframe.png")
    Image.fromarray(frame).save(png_path)
    return png_path


def _upload_local_image_for_anchor(script_id, tag, png_path):
    """Chain-extension anchors must be passed to Agnes as a real fetchable
    URL, not a bare B2 key - this is the one place upload_reference_image's
    key gets immediately presigned, since the result is used right away in
    the same run and never persisted to the database (ephemeral use only,
    so the 1-hour presigned URL default is more than enough)."""
    key = upload_reference_image(script_id, tag, png_path)
    os.remove(png_path)
    if not key:
        return None
    return storage_b2.presigned_url(key)


def generate_shot_clip(shot, target_duration, out_path, setting_and_characters="", anchor_image_url=None, script_id=None):
    capped_duration = min(target_duration, MAX_CLIP_SECONDS)
    _generate_one_segment(shot, capped_duration, out_path, setting_and_characters, anchor_image_url=anchor_image_url)

    if target_duration <= MAX_CLIP_SECONDS:
        return out_path

    remaining = target_duration - capped_duration
    segment_paths = [out_path]
    current_anchor_path = out_path
    chain_used = 0

    print(f"Shot needs {target_duration:.1f}s (over the ~{MAX_CLIP_SECONDS:.1f}s per-generation cap) - "
          f"chaining real continuation clips for the remaining {remaining:.1f}s instead of freezing.")

    while remaining > 0.05 and chain_used < MAX_CHAIN_SEGMENTS:
        seg_duration = min(remaining, MAX_CLIP_SECONDS)
        seg_out_path = out_path.replace(".mp4", f"_chain{chain_used + 1}.mp4")

        # CHAIN-RETRY FIX (2026-08-23): a single transient Agnes hiccup
        # (momentary overload/rate-limit) used to immediately give up on
        # the ENTIRE remaining chain and freeze-hold the rest of the shot -
        # even though AgnesOverloadedError is, by definition, a transient
        # condition create_agnes_task already retried AGNES_MAX_RETRIES
        # times internally. One extra attempt at the chain-segment level
        # (separate from that internal retry) catches the case where the
        # segment simply landed during a bad moment, without extending
        # runtime much - a genuine/permanent failure still falls through
        # to the freeze-hold exactly as before.
        # FREEZE-FRAME REDUCTION FIX (2026-08-25): raised from 2 attempts to
        # 3, with a shorter backoff between them (10s -> 6s), directly per
        # Zia's report that freeze-holds still show up on a minority of
        # shots. A single retry was giving up too early on transient Agnes
        # hiccups; a third attempt (with a faster retry cadence so it
        # doesn't meaningfully slow down a run) lets more segments recover
        # instead of falling through to the freeze-hold fallback below.
        segment_ok = False
        last_chain_error = None
        for chain_attempt in range(3):
            try:
                local_frame_path = _extract_last_frame_local(current_anchor_path)
                chain_anchor_url = _upload_local_image_for_anchor(
                    script_id or "unknown", f"chain_{os.path.basename(seg_out_path)}", local_frame_path
                )
                _generate_one_segment(shot, seg_duration, seg_out_path, setting_and_characters, anchor_image_url=chain_anchor_url)
                segment_ok = True
                break
            except (ContentPolicyRejection, AgnesOverloadedError, Exception) as e:
                last_chain_error = e
                if chain_attempt < 2:
                    print(f"Chain-extension segment {chain_used + 1} failed on attempt "
                          f"{chain_attempt + 1}/3 ({e}) - retrying before falling back to a freeze-hold.")
                    time.sleep(6)

        if not segment_ok:
            print(f"Chain-extension segment {chain_used + 1} failed after retry ({last_chain_error}) - "
                  f"falling back to a freeze-hold for the remaining {remaining:.1f}s instead of losing the whole shot.")
            break

        segment_paths.append(seg_out_path)
        current_anchor_path = seg_out_path
        remaining -= seg_duration
        chain_used += 1

    clips = [VideoFileClip(p) for p in segment_paths]
    combined = concatenate_videoclips(clips, method="compose")

    if remaining > 0.05:
        combined = fit_clip_to_duration(combined, combined.duration + remaining)

    tmp_path = out_path.replace(".mp4", "_extended.mp4")
    combined.write_videofile(tmp_path, fps=FRAME_RATE, codec="libx264", audio=False, threads=2, logger=None)
    for c in clips:
        c.close()
    for p in segment_paths[1:]:
        if os.path.exists(p):
            os.remove(p)
    os.replace(tmp_path, out_path)

    return out_path


def fit_clip_to_duration(clip, target):
    if clip.duration >= target:
        return clip.subclipped(0, target)

    extra = target - clip.duration
    freeze_frame = clip.to_ImageClip(t=max(clip.duration - 1 / FRAME_RATE, 0))
    freeze_frame = freeze_frame.with_duration(extra).with_fps(FRAME_RATE)
    return concatenate_videoclips([clip, freeze_frame])
