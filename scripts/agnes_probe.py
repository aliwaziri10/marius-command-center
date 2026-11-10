"""
Marius Command Center - Agnes probe (2026-11-10).

PURPOSE: Agnes's free video queue has been full (HTTP 503 video_queue_full)
since about 2026-10-10. This script asks one tiny question every couple of
hours: "is Agnes accepting video requests again, and does it finish one?"
It never touches Supabase, B2 or any script row. It only reports.

WHAT IT DOES: sends ONE 4-second 720P test request (the same request shape as
agnes_client.create_agnes_task). Then:
  QUEUE_FULL          503 video_queue_full -> nothing was created, nothing used.
  OPEN_AND_PRODUCING  accepted AND a finished video URL came back (the good one).
  ACCEPTED_BUT_FAILED / ACCEPTED_NO_RESULT  accepted, but no finished video.
  ERROR               any other answer or network problem (text is shown).
Writes the result to the Actions run summary and to /tmp/agnes_probe_result.txt
(the workflow opens a GitHub issue only when the result is OPEN_AND_PRODUCING).

Exit code: 0 for every normal outcome. 1 only when the key is rejected
(401/403) or missing, so a broken key shows as a red run.
"""
import os
import sys
import time
import requests

BASE = "https://apihub.agnes-ai.com/v1"
POLL_URL = "https://apihub.agnes-ai.com/agnesapi"
MODEL = "agnes-video-2.5-flash"
RESULT_FILE = "/tmp/agnes_probe_result.txt"
POLL_MAX_SECONDS = int(os.environ.get("PROBE_POLL_MAX_SECONDS", "720"))
POLL_INTERVAL = 15
PROMPT = ("Rain falling on a quiet cobblestone street at dusk, "
          "warm window light, slow camera push in, cinematic.")


def finish(outcome, detail, code=0):
    stamp = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())
    line = f"{outcome}: {detail}"
    print(f"[{stamp}] {line}")
    try:
        with open(RESULT_FILE, "w") as f:
            f.write(outcome)
    except Exception as e:
        print(f"Could not write result file (non-fatal): {e}")
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        try:
            with open(path, "a") as f:
                f.write(f"## Agnes probe\n\n- {stamp}\n- **{outcome}** - {detail}\n")
        except Exception as e:
            print(f"Could not write run summary (non-fatal): {e}")
    sys.exit(code)


def extract_url(data):
    for key in ("url", "video_url", "remixed_from_video_id"):
        val = data.get(key)
        if isinstance(val, str) and val.startswith("http"):
            return val
    for val in data.values():
        if isinstance(val, str) and val.startswith("http") and val.endswith(".mp4"):
            return val
    return None


def run():
    key = (os.environ.get("AGNES_API_KEY") or "").strip()
    if not key:
        finish("ERROR", "AGNES_API_KEY is not set for this workflow.", code=1)
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    payload = {"model": MODEL, "prompt": PROMPT, "mode": "text", "seconds": "4",
               "size": "720P", "aspect_ratio": "16:9", "n": 1}
    try:
        resp = requests.post(f"{BASE}/videos", headers=headers, json=payload, timeout=60)
    except requests.exceptions.RequestException as e:
        finish("ERROR", f"network problem reaching Agnes: {e.__class__.__name__}: {e}")

    if resp.status_code in (401, 403):
        finish("ERROR", f"Agnes rejected the key (HTTP {resp.status_code}): {resp.text[:300]}", code=1)
    if resp.status_code == 503 and "video_queue_full" in resp.text:
        finish("QUEUE_FULL", "Agnes video queue is still full (HTTP 503). Nothing was created.")
    if resp.status_code >= 400:
        finish("ERROR", f"HTTP {resp.status_code}: {resp.text[:300]}")

    try:
        data = resp.json()
    except Exception:
        finish("ERROR", f"Agnes answered 2xx but not JSON: {resp.text[:300]}")
    video_id = data.get("video_id") or data.get("id") or data.get("task_id")
    if not video_id:
        finish("ERROR", f"Agnes accepted the request but returned no video id: {str(data)[:300]}")

    print(f"Agnes accepted the test request (video id {video_id}). Waiting for the result...")
    waited = 0
    errors = 0
    while waited < POLL_MAX_SECONDS:
        time.sleep(POLL_INTERVAL)
        waited += POLL_INTERVAL
        try:
            r = requests.get(POLL_URL, params={"video_id": video_id, "model_name": MODEL},
                             headers=headers, timeout=30)
            if r.status_code >= 400:
                errors += 1
                if errors >= 5:
                    finish("ACCEPTED_NO_RESULT", f"accepted, but polling kept failing (last HTTP {r.status_code}).")
                continue
            d = r.json()
        except Exception as e:
            errors += 1
            if errors >= 5:
                finish("ACCEPTED_NO_RESULT", f"accepted, but polling kept failing ({e.__class__.__name__}).")
            continue
        errors = 0
        status = d.get("status")
        if status == "completed":
            url = extract_url(d)
            if url:
                finish("OPEN_AND_PRODUCING", f"Agnes accepted AND finished a test video in about {waited}s.")
            finish("ACCEPTED_BUT_FAILED", "status was completed but no video URL came back.")
        if status == "failed":
            finish("ACCEPTED_BUT_FAILED", f"Agnes accepted the request but generation failed: {str(d)[:300]}")
    finish("ACCEPTED_NO_RESULT", f"accepted, but no finished video within {POLL_MAX_SECONDS}s.")


if __name__ == "__main__":
    run()
