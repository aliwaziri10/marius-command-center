"""
Marius Command Center - Post-Run Output Verifier (Loop Skill 1)

Checks what's ACTUALLY sitting in Supabase/storage after a stage runs,
instead of trusting the stage script's own "exit 0". Run as the last step
of a workflow, after the stage script itself.

This pipeline has no local file artifact that survives a run (video files
are uploaded to Supabase storage and deleted from /tmp immediately), so
"file-based" here means: this script's own logic and output are simple and
self-contained (one file, stdlib + requests, prints JSON, no new infra) -
but what it checks is the real state in Supabase, since that's what
"worked" actually means for this pipeline. A verifier that only checked
local files would verify nothing real.

Usage:
    python scripts/verify_run_output.py --stage script_writing
    python scripts/verify_run_output.py --stage video_generation

Exits non-zero (and prints failures to stderr) if anything checked doesn't
hold up - this is what makes the run fail loud. Each workflow already has
an "Open issue on failure" step gated on `if: failure()`, which fires off
of ANY failed step in the job, so no change is needed there: this script
failing is enough to trigger it.
"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone

import requests

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SECRET_KEY"]
HEADERS = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}

# Must match shot_breakdown_stage.py's MIN_SHOTS/MAX_SHOTS. Duplicated
# here deliberately rather than imported - this script checks the
# CONTRACT, not the implementation, and should keep working even if
# someone refactors shot_breakdown_stage.py's internals.
MIN_SHOTS = 25
MAX_SHOTS = 35

CHECK_SAMPLE_SIZE = 5        # most-recent N scripts per relevant status, each run
MIN_VIDEO_BYTES = 1_000_000  # 1MB floor - catches empty/near-empty/truncated uploads
HTTP_TIMEOUT = 30

# FIX (2026-08-20): color_palette was added to shot_breakdown_stage.py in
# commit 4b9c3fc (2026-08-20T01:48:19Z / 07:18:19+05:30 IST) as part of the
# director-features change. Scripts created before this timestamp legitimately
# have no color_palette - they predate the field, not a real regression.
# Checking for it on those older rows was producing false-positive failures
# on every run. Any script created at/after this cutoff still must have it.
COLOR_PALETTE_FIELD_ADDED_AT = datetime.fromisoformat("2026-08-20T01:48:19+00:00")


def fetch_scripts(status, limit=CHECK_SAMPLE_SIZE, order="created_at.desc"):
    resp = requests.get(
        f"{SUPABASE_URL}/rest/v1/scripts",
        headers=HEADERS,
        params={"status": f"eq.{status}", "order": order, "limit": limit},
        timeout=HTTP_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()


def check_url_alive(url, min_bytes=None):
    """HEAD request - confirms the URL is actually live and (optionally)
    non-trivially sized, not just a string sitting in a Supabase column
    that nothing has verified since it was written."""
    try:
        r = requests.head(url, timeout=HTTP_TIMEOUT, allow_redirects=True)
    except requests.RequestException as e:
        return False, f"request failed: {e}"
    if r.status_code != 200:
        return False, f"status {r.status_code}"
    if min_bytes is not None:
        size = r.headers.get("Content-Length")
        if size is None:
            return False, "no Content-Length header - cannot confirm size"
        if int(size) < min_bytes:
            return False, f"only {int(size)} bytes (min {min_bytes})"
    return True, None


def verify_shot_breakdown_script(script):
    """Any script that has passed shot breakdown (status images_generated
    or later) should have a shot_list obeying the same bounds/required
    fields shot_breakdown_stage.py is supposed to enforce at write time.
    This re-checks that post-hoc, catching drift, manual edits, or a bug
    in the write-time validation itself."""
    problems = []
    shot_list = script.get("shot_list")
    if isinstance(shot_list, str):
        try:
            shot_list = json.loads(shot_list)
        except (json.JSONDecodeError, TypeError):
            shot_list = None

    if not isinstance(shot_list, list) or len(shot_list) == 0:
        problems.append("shot_list missing or empty")
    else:
        if not (MIN_SHOTS <= len(shot_list) <= MAX_SHOTS):
            problems.append(f"shot_list has {len(shot_list)} shots, outside {MIN_SHOTS}-{MAX_SHOTS}")
        empty = [
            i for i, s in enumerate(shot_list)
            if not (s.get("visual_description") or "").strip()
            or not (s.get("narration_excerpt") or "").strip()
        ]
        if empty:
            problems.append(
                f"{len(empty)} shot(s) have empty visual_description/narration_excerpt "
                f"(first at index {empty[0]})"
            )

    if not (script.get("setting_and_characters") or "").strip():
        problems.append("setting_and_characters empty")

    # FIX (2026-08-20): only enforce color_palette on scripts created at/after
    # the field's introduction - see COLOR_PALETTE_FIELD_ADDED_AT above.
    created_at_raw = script.get("created_at")
    created_at = None
    if created_at_raw:
        try:
            created_at = datetime.fromisoformat(created_at_raw.replace("Z", "+00:00"))
        except ValueError:
            created_at = None

    if created_at is None or created_at >= COLOR_PALETTE_FIELD_ADDED_AT:
        if not (script.get("color_palette") or "").strip():
            problems.append("color_palette empty")

    if not (script.get("narration_url") or "").strip():
        problems.append("narration_url empty")

    return problems


def verify_video_generated_script(script):
    """A script marked video_generated must have a video that's actually
    live and non-trivial - not just a URL string a request happened to
    return 200 for once, and not just an upload call that returned 2xx
    without the bytes actually being real."""
    problems = []
    video_url = script.get("video_url")
    chunk_urls = script.get("video_chunk_urls")

    if not video_url and not chunk_urls:
        problems.append("status is video_generated but both video_url and video_chunk_urls are empty")
        return problems

    if video_url:
        ok, reason = check_url_alive(video_url, min_bytes=MIN_VIDEO_BYTES)
        if not ok:
            problems.append(f"video_url not verified: {reason}")

    if chunk_urls:
        if not isinstance(chunk_urls, list) or len(chunk_urls) == 0:
            problems.append("video_chunk_urls present but empty/malformed")
        else:
            for i, url in enumerate(chunk_urls):
                ok, reason = check_url_alive(url, min_bytes=MIN_VIDEO_BYTES)
                if not ok:
                    problems.append(f"video_chunk_urls[{i}] not verified: {reason}")

    return problems


def check_stalled_scripts():
    """Non-fatal early warning for the exact pattern STATUS.md is showing
    right now: a script sitting in images_generated with 0 clips generated
    and no forward progress. video_generation.py's own budget/retry loop is
    expected to eventually pick these back up, so this is a warning, not a
    failure - but it should show up somewhere instead of only being visible
    by manually reading STATUS.md."""
    warnings = []
    for s in fetch_scripts("images_generated", limit=CHECK_SAMPLE_SIZE):
        video_urls = s.get("video_urls") or []
        if len(video_urls) == 0:
            warnings.append(f"script {s.get('id')} is images_generated with 0 clips generated so far")
    return warnings


def run_verification(stage):
    result = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "stage": stage,
        "checked": [],
        "failures": [],
        "warnings": [],
    }

    if stage == "script_writing":
        for status in ("images_generated", "video_generated"):
            for s in fetch_scripts(status):
                problems = verify_shot_breakdown_script(s)
                result["checked"].append({"script_id": s.get("id"), "status": status, "problems": problems})
                result["failures"].extend(f"{s.get('id')}: {p}" for p in problems)

    elif stage == "video_generation":
        for s in fetch_scripts("video_generated"):
            problems = verify_video_generated_script(s)
            result["checked"].append({"script_id": s.get("id"), "status": "video_generated", "problems": problems})
            result["failures"].extend(f"{s.get('id')}: {p}" for p in problems)
        result["warnings"].extend(check_stalled_scripts())

    else:
        raise ValueError(f"Unknown --stage {stage!r}")

    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", required=True, choices=["script_writing", "video_generation"])
    args = parser.parse_args()

    result = run_verification(args.stage)
    print(json.dumps(result, indent=2))

    if result["failures"]:
        print(f"\nVERIFICATION FAILED: {len(result['failures'])} problem(s) found.", file=sys.stderr)
        sys.exit(1)

    if result["warnings"]:
        print(f"\nVerification passed with {len(result['warnings'])} warning(s).")

    print("\nVerification passed.")


if __name__ == "__main__":
    main()
