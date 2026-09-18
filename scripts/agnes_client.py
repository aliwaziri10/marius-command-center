"""
Marius Command Center - Agnes API client (split from video_generation.py,
2026-09-06, same pattern as the 2026-08-18 script_writing.py split).

Holds everything that talks directly to the Agnes video-generation API:
task creation, polling, video-URL extraction, frame-count rounding, and
the exception types the rest of the pipeline catches to decide what kind
of failure just happened (content-policy rejection vs transient overload
vs a genuine bad-request bug). No Supabase/B2/moviepy logic lives here -
this file only knows about Agnes's HTTP contract.

POLL-TIMEOUT CRASH FIX (2026-09-18): poll_agnes_task's per-request
requests.get() had a bare timeout=30 with no try/except around it. Agnes
routinely takes longer than 30s to answer a single poll request while a
video is still rendering - that's normal load, not a failure - but a
ReadTimeoutError/ConnectionError from requests is not one of
ContentPolicyRejection/AgnesOverloadedError/AgnesBadRequestError, so it
was never caught by process_script's per-shot handling in
video_generation.py. It fell straight through to main()'s generic
per-script catch-all, which logs it and moves to the next script -
silently killing that script's progress for the run instead of just
waiting and polling again. Confirmed live: scripts 4d32a7b4 and
b8a63d7f both stuck at 1/N clips for days with this exact traceback in
last_error. Fixed by catching requests.exceptions.RequestException
inside the poll loop and treating it as a transient miss (log, sleep the
normal interval, try again) instead of letting it propagate - the
existing max_wait budget still bounds total time spent polling.
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

# RESOLUTION UPGRADE (2026-08-28): raised from 1280x720 to 1920x1080 -
# Agnes video v2.0 supports up to 1080p natively (confirmed in their own
# docs), this pipeline was requesting the 720p tier for every single clip
# with no technical reason to. Zero cost, zero infra change - pure
# quality gain at the same API call.
WIDTH, HEIGHT = 1920, 1080
FRAME_RATE = 24
MIN_FRAMES = 49
MAX_FRAMES = 169
MAX_CLIP_SECONDS = MAX_FRAMES / FRAME_RATE

AGNES_RETRYABLE_CODES = {429, 500, 502, 503, 504}
AGNES_MAX_RETRIES = 4
AGNES_IMAGE_MAX_RETRIES = 3

# POLL-TIMEOUT CRASH FIX (2026-09-18): a single dropped/slow poll request
# no longer ends the whole poll loop - it's retried up to this many times
# (each still bounded by the per-request timeout below) before giving up
# and surfacing as AgnesOverloadedError, same as a real max_wait timeout.
POLL_REQUEST_TIMEOUT = 30
POLL_MAX_CONSECUTIVE_NETWORK_ERRORS = 5


class ContentPolicyRejection(Exception):
    pass


class AgnesOverloadedError(Exception):
    pass


class AgnesBadRequestError(Exception):
    """
    STALL FIX (2026-09-02): a 400 from Agnes that is NOT a content-policy
    rejection (i.e. resp.text doesn't contain "content_policy_violation")
    used to fall straight through to resp.raise_for_status() as a bare
    requests.HTTPError with no response body captured. That plain
    HTTPError isn't one of the two types process_script's per-shot loop
    catches (ContentPolicyRejection, AgnesOverloadedError), so it was only
    ever caught by main()'s outer per-script catch-all - which logs it and
    moves on, but never changes the script's status. Since
    get_ready_scripts only filters on status=images_generated, the exact
    same script came back as the oldest candidate on the next run and
    retried the exact same failing shot with the exact same payload,
    forever, with no body text ever persisted anywhere. Found live on
    script 8fb7e5f9, stuck at shot 11/32 since 2026-08-24, silently
    re-failing every hourly run for 9 days straight.

    This exception carries the real resp.text so the actual reason is
    finally visible, and is caught specifically in process_script (see
    mark_video_stalled) so a stuck shot gets a terminal status instead of
    an infinite identical retry.
    """
    pass


def round_to_valid_frames(num_frames):
    # FREEZE-FRAME FIX (2026-08-03): was using round() to the nearest valid
    # frame count, which rounds DOWN roughly half the time - producing a
    # clip up to ~0.3s shorter than the target duration, which then had to
    # be covered by a frozen final frame. Using ceiling instead guarantees
    # the generated clip is always >= target duration, so there's nothing
    # left to freeze except sub-frame remainders (a few milliseconds).
    n = math.ceil((num_frames - 1) / 8)
    n = max(0, n)
    return 8 * n + 1


def create_agnes_task(prompt, num_frames, image_url=None, negative_prompt=None, seed=None):
    """
    NEGATIVE_PROMPT SUPPORT (2026-09-08): Agnes's own docs confirm a
    negative_prompt field on this endpoint that this pipeline never sent -
    every anti-waxy/anti-plastic-skin instruction was previously carried
    only inside the positive prompt (QUALITY_GUARD in prompt_builder.py).
    Positive "not waxy, not plastic" phrasing is known-unreliable on video
    models (the model can attend to the nouns "waxy"/"plastic" without
    reliably applying the negation). Passing the same guard text through
    the API's real negative_prompt channel as well gives the constraint a
    second, structurally stronger path to actually suppress the effect,
    on top of (not instead of) the existing positive QUALITY_GUARD text.
    Optional and backward compatible - omitted entirely from the payload
    when the caller doesn't pass one, so this never breaks the character-
    reference image call path or any other caller that doesn't use it.

    SEED SUPPORT (2026-09-10): Agnes's own docs confirm a seed field on
    this endpoint that this pipeline never sent. Optional and backward
    compatible - omitted entirely from the payload when the caller
    doesn't pass one. Deterministic seeds let a shot regenerate with the
    same visual result on a resumed/retried run instead of a fresh random
    roll every time; clip_generation.py derives one per shot from
    (script_id, shot_index) so re-running an interrupted run doesn't
    produce visually inconsistent reruns of shots that already looked
    right, while a genuine content-policy/chain retry deliberately uses a
    different seed so it isn't just repeating the same failure.
    """
    last_error_text = None

    for attempt in range(AGNES_MAX_RETRIES):
        payload = {
            "model": "agnes-video-v2.0",
            "prompt": prompt,
            "height": HEIGHT,
            "width": WIDTH,
            "num_frames": num_frames,
            "frame_rate": FRAME_RATE,
        }
        if image_url:
            payload["image"] = image_url
        if negative_prompt:
            payload["negative_prompt"] = negative_prompt
        if seed is not None:
            payload["seed"] = seed

        resp = requests.post(
            f"{AGNES_BASE}/videos",
            headers=AGNES_HEADERS,
            json=payload,
            timeout=60,
        )

        if resp.status_code == 400 and "content_policy_violation" in resp.text:
            raise ContentPolicyRejection(resp.text)

        if resp.status_code in AGNES_RETRYABLE_CODES:
            last_error_text = resp.text
            wait = 20 * (attempt + 1)
            print(f"AGNES transient error {resp.status_code} (attempt {attempt + 1}/{AGNES_MAX_RETRIES}): {resp.text}")
            print(f"Retrying in {wait}s...")
            time.sleep(wait)
            continue

        if resp.status_code == 400:
            # STALL FIX (2026-09-02): any other 400 (not content-policy,
            # not one of the retryable transient codes above) is a
            # permanent, non-retryable failure - raise it with the real
            # body captured instead of letting it fall through to a bare
            # raise_for_status() with no text attached.
            print(f"AGNES 400 (non-content-policy): {resp.text}")
            raise AgnesBadRequestError(resp.text)

        if resp.status_code >= 400:
            print(f"AGNES ERROR {resp.status_code}: {resp.text}")
        resp.raise_for_status()
        data = resp.json()
        return data.get("video_id") or data.get("id") or data.get("task_id")

    raise AgnesOverloadedError(f"Agnes still failing after {AGNES_MAX_RETRIES} attempts: {last_error_text}")


def extract_video_url(data):
    for key in ("video_url", "url", "remixed_from_video_id"):
        val = data.get(key)
        if isinstance(val, str) and val.startswith("http"):
            return val
    for val in data.values():
        if isinstance(val, str) and val.startswith("http") and val.endswith(".mp4"):
            return val
    return None


def poll_agnes_task(video_id, max_wait=300, interval=10):
    waited = 0
    consecutive_network_errors = 0
    while waited < max_wait:
        try:
            resp = requests.get(
                AGNES_POLL_URL,
                params={"video_id": video_id, "model_name": "agnes-video-v2.0"},
                headers=AGNES_HEADERS,
                timeout=POLL_REQUEST_TIMEOUT,
            )
        except requests.exceptions.RequestException as e:
            # POLL-TIMEOUT CRASH FIX (2026-09-18): a slow/dropped poll
            # request used to propagate straight up and kill this whole
            # script's run (see module docstring). Treat it exactly like a
            # not-ready-yet poll instead - wait the normal interval and
            # try again, bounded by the same max_wait budget, but bail
            # out with AgnesOverloadedError if the network itself looks
            # broken rather than Agnes just being slow.
            consecutive_network_errors += 1
            print(f"AGNES POLL network error ({consecutive_network_errors}/{POLL_MAX_CONSECUTIVE_NETWORK_ERRORS}): {e}")
            if consecutive_network_errors >= POLL_MAX_CONSECUTIVE_NETWORK_ERRORS:
                raise AgnesOverloadedError(f"Agnes poll network errors {consecutive_network_errors}x in a row for video_id {video_id}: {e}")
            time.sleep(interval)
            waited += interval
            continue

        consecutive_network_errors = 0

        if resp.status_code == 400 and "content_policy_violation" in resp.text:
            raise ContentPolicyRejection(resp.text)
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
