"""
Marius Command Center - Agnes API client.

MODEL SWITCH (2026-10-18): Agnes retired agnes-video-v2.0 on 2026-09-25.
This file now talks to agnes-video-2.5-flash, using the same request shape
the working Tiny Lawn Tales pipeline (upgraded-journey) already uses:
  POST /v1/videos  with  model, prompt, mode ("text" or "reference"),
                         seconds ("4".."12"), size ("720P"), aspect_ratio,
                         n, and images=[url] in reference mode
  GET  /agnesapi?video_id=...&model_name=agnes-video-2.5-flash
Flash supports 720P only and 4 to 12 seconds per clip.

Every name other Marius files import from here (create_agnes_task,
poll_agnes_task, round_to_valid_frames, WIDTH, HEIGHT, FRAME_RATE,
MIN_FRAMES, MAX_FRAMES, MAX_CLIP_SECONDS, the exception classes, ...) is
kept with the same signature, so clip_generation.py needs no changes. The
callers still think in frames; create_agnes_task converts frames to whole
seconds (rounded UP, so a clip is never shorter than the shot needs).

negative_prompt and seed are still accepted but are NOT sent: the Flash
request shape used by the working pipeline does not include them.

QUEUE FULL (503 video_queue_full): Agnes answers this when its free queue
is saturated. It is not a bug in this code. We wait and try again
(AGNES_QUEUE_FULL_WAIT_SECONDS between tries, up to
AGNES_QUEUE_FULL_MAX_ATTEMPTS), then raise AgnesOverloadedError, which the
rest of the pipeline already knows how to handle.

Earlier crash fixes (poll timeouts, poll 429s, create timeouts) are kept.
"""

import os
import math
import time
import requests

AGNES_API_KEY = os.environ["AGNES_API_KEY"]

AGNES_BASE = "https://apihub.agnes-ai.com/v1"
AGNES_POLL_URL = "https://apihub.agnes-ai.com/agnesapi"
AGNES_IMAGE_URL = f"{AGNES_BASE}/images/generations"
AGNES_HEADERS = {
    "Authorization": f"Bearer {AGNES_API_KEY}",
    "Content-Type": "application/json",
}

AGNES_VIDEO_MODEL = "agnes-video-2.5-flash"
VIDEO_SIZE = "720P"  # Flash supports only 720P
ASPECT_RATIO = "16:9"
MIN_CLIP_SECONDS = 4
MAX_CLIP_SECONDS_API = 12

# WIDTH/HEIGHT are still used by other files (image generation size, assembly).
WIDTH, HEIGHT = 1920, 1080
FRAME_RATE = 24
MIN_FRAMES = MIN_CLIP_SECONDS * FRAME_RATE + 1      # 97  (4 s)
MAX_FRAMES = MAX_CLIP_SECONDS_API * FRAME_RATE + 1  # 289 (12 s)
MAX_CLIP_SECONDS = MAX_CLIP_SECONDS_API

AGNES_RETRYABLE_CODES = {429, 500, 502, 503, 504}
AGNES_MAX_RETRIES = 4
AGNES_IMAGE_MAX_RETRIES = 3

AGNES_QUEUE_FULL_WAIT_SECONDS = 120
AGNES_QUEUE_FULL_MAX_ATTEMPTS = 8

POLL_REQUEST_TIMEOUT = 30
POLL_MAX_CONSECUTIVE_TRANSIENT_ERRORS = 5


class ContentPolicyRejection(Exception):
    pass


class AgnesOverloadedError(Exception):
    pass


class AgnesBadRequestError(Exception):
    """A 400 from Agnes that is not a content-policy rejection. Carries the
    real response text so the actual reason is visible (see 2026-09-02 stall
    fix: this used to be a bare HTTPError with no body)."""
    pass


def round_to_valid_frames(num_frames):
    # Kept for compatibility with clip_generation.py (ceiling, never shorter).
    n = math.ceil((num_frames - 1) / 8)
    n = max(0, n)
    return 8 * n + 1


def seconds_for_frames(num_frames):
    """Frames -> whole seconds for Flash, rounded up, clamped to 4..12."""
    secs = math.ceil((num_frames - 1) / FRAME_RATE)
    return str(min(max(secs, MIN_CLIP_SECONDS), MAX_CLIP_SECONDS_API))


def create_agnes_task(prompt, num_frames, image_url=None, negative_prompt=None, seed=None):
    """Create a Flash video task and return its video_id.
    image_url, when given, switches to reference mode with that picture."""
    payload = {
        "model": AGNES_VIDEO_MODEL,
        "prompt": prompt,
        "mode": "text",
        "seconds": seconds_for_frames(num_frames),
        "size": VIDEO_SIZE,
        "aspect_ratio": ASPECT_RATIO,
        "n": 1,
    }
    if image_url:
        payload["mode"] = "reference"
        payload["images"] = [image_url]
        payload["prompt"] = (
            "Use the picture in <Picture 1> as the visual reference for the "
            "subject, setting and look, keeping it consistent. " + prompt
        )

    last_error_text = None
    attempt = 0
    queue_full_count = 0

    while attempt < AGNES_MAX_RETRIES:
        try:
            resp = requests.post(
                f"{AGNES_BASE}/videos",
                headers=AGNES_HEADERS,
                json=payload,
                timeout=60,
            )
        except requests.exceptions.RequestException as e:
            attempt += 1
            last_error_text = f"{e.__class__.__name__}: {e}"
            wait = 20 * attempt
            print(f"AGNES create network error (attempt {attempt}/{AGNES_MAX_RETRIES}): {last_error_text}")
            print(f"Retrying in {wait}s...")
            time.sleep(wait)
            continue

        if resp.status_code == 400 and "content_policy_violation" in resp.text:
            raise ContentPolicyRejection(resp.text)

        if resp.status_code == 503 and "video_queue_full" in resp.text:
            queue_full_count += 1
            last_error_text = resp.text
            if queue_full_count >= AGNES_QUEUE_FULL_MAX_ATTEMPTS:
                raise AgnesOverloadedError(
                    f"Agnes video queue still full after {AGNES_QUEUE_FULL_MAX_ATTEMPTS} tries: {resp.text}"
                )
            print(f"AGNES video queue is full (try {queue_full_count}/{AGNES_QUEUE_FULL_MAX_ATTEMPTS}). "
                  f"Waiting {AGNES_QUEUE_FULL_WAIT_SECONDS}s before trying again...")
            time.sleep(AGNES_QUEUE_FULL_WAIT_SECONDS)
            continue

        if resp.status_code in AGNES_RETRYABLE_CODES:
            attempt += 1
            last_error_text = resp.text
            wait = 20 * attempt
            print(f"AGNES transient error {resp.status_code} (attempt {attempt}/{AGNES_MAX_RETRIES}): {resp.text}")
            print(f"Retrying in {wait}s...")
            time.sleep(wait)
            continue

        if resp.status_code == 400:
            print(f"AGNES 400 (non-content-policy): {resp.text}")
            raise AgnesBadRequestError(resp.text)

        if resp.status_code >= 400:
            print(f"AGNES ERROR {resp.status_code}: {resp.text}")
        resp.raise_for_status()
        data = resp.json()
        video_id = data.get("video_id") or data.get("id") or data.get("task_id")
        if not video_id:
            raise RuntimeError(f"Agnes submit response had no video_id: {data}")
        return video_id

    raise AgnesOverloadedError(f"Agnes still failing after {AGNES_MAX_RETRIES} attempts: {last_error_text}")


def extract_video_url(data):
    for key in ("url", "video_url", "remixed_from_video_id"):
        val = data.get(key)
        if isinstance(val, str) and val.startswith("http"):
            return val
    for val in data.values():
        if isinstance(val, str) and val.startswith("http") and val.endswith(".mp4"):
            return val
    return None


def poll_agnes_task(video_id, max_wait=900, interval=10):
    waited = 0
    consecutive_transient_errors = 0
    while waited < max_wait:
        try:
            resp = requests.get(
                AGNES_POLL_URL,
                params={"video_id": video_id, "model_name": AGNES_VIDEO_MODEL},
                headers=AGNES_HEADERS,
                timeout=POLL_REQUEST_TIMEOUT,
            )
        except requests.exceptions.RequestException as e:
            consecutive_transient_errors += 1
            print(f"AGNES POLL network error ({consecutive_transient_errors}/{POLL_MAX_CONSECUTIVE_TRANSIENT_ERRORS}): {e}")
            if consecutive_transient_errors >= POLL_MAX_CONSECUTIVE_TRANSIENT_ERRORS:
                raise AgnesOverloadedError(f"Agnes poll network errors {consecutive_transient_errors}x in a row for video_id {video_id}: {e}")
            wait = interval * consecutive_transient_errors
            time.sleep(wait)
            waited += wait
            continue

        if resp.status_code == 400 and "content_policy_violation" in resp.text:
            raise ContentPolicyRejection(resp.text)

        if resp.status_code in AGNES_RETRYABLE_CODES:
            consecutive_transient_errors += 1
            print(f"AGNES POLL transient error {resp.status_code} ({consecutive_transient_errors}/{POLL_MAX_CONSECUTIVE_TRANSIENT_ERRORS}): {resp.text}")
            if consecutive_transient_errors >= POLL_MAX_CONSECUTIVE_TRANSIENT_ERRORS:
                raise AgnesOverloadedError(f"Agnes poll kept returning {resp.status_code} {consecutive_transient_errors}x in a row for video_id {video_id}: {resp.text}")
            wait = interval * consecutive_transient_errors
            time.sleep(wait)
            waited += wait
            continue

        consecutive_transient_errors = 0

        if resp.status_code >= 400:
            print(f"AGNES POLL ERROR {resp.status_code}: {resp.text}")
        resp.raise_for_status()
        data = resp.json()
        status = data.get("status")
        if status == "completed":
            url = extract_video_url(data)
            if url:
                return url
            raise RuntimeError(f"Completed but no video URL found: {data}")
        if status == "failed":
            raise RuntimeError(f"Agnes generation failed: {data}")
        time.sleep(interval)
        waited += interval
    raise AgnesOverloadedError(f"Agnes generation timed out after {max_wait}s for video_id {video_id}")
