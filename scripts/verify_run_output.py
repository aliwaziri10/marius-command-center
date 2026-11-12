"""
Marius Command Center - Post-Run Output Verifier (Loop Skill 1)

Checks what's ACTUALLY sitting in Supabase/storage after a stage runs,
instead of trusting the stage script's own "exit 0". Run as the last step
of a workflow, after the stage script itself.

This pipeline has no local file artifact that survives a run (video files
are uploaded to storage and deleted from /tmp immediately), so
"file-based" here means: this script's own logic and output are simple and
self-contained (one file, stdlib + requests + storage_b2, prints JSON, no
new infra) - but what it checks is the real state in Supabase/B2, since
that's what "worked" actually means for this pipeline. A verifier that
only checked local files would verify nothing real.

Usage:
    python scripts/verify_run_output.py --stage script_writing
    python scripts/verify_run_output.py --stage video_generation

Exits non-zero (and prints failures to stderr) if anything checked doesn't
hold up - this is what makes the run fail loud. Each workflow already has
an "Open issue on failure" step gated on `if: failure()`, which fires off
of ANY failed step in the job, so no change is needed there: this script
failing is enough to trigger it.

STORAGE MIGRATION FIX (2026-09-02): verify_video_generated_script()
previously called check_url_alive() (a plain requests.head()) on
scripts.video_url, which worked when video_url was a real Supabase
Storage https:// URL. Since the B2 migration, video_url is a bare B2
object key (e.g. "abc123.mp4") - an HTTP HEAD on that raises
requests.exceptions.MissingSchema immediately, which would have marked
every single freshly-migrated video as "not verified" on every run,
failing this step and opening a false failure issue even when everything
actually worked. Fixed by checking B2 keys via storage_b2.object_size()
(a real B2 API head_object call) instead of an HTTP request.
video_chunk_urls is untouched - those are always real https:// Supabase
Storage URLs from before the migration (no script created after the
migration will ever have chunk_urls populated - see video_generation.py),
so check_url_alive() remains correct for that field specifically.

LAZY IMPORT FIX (2026-09-10): storage_b2 used to be imported at module
level, which reads B2_ENDPOINT_URL/B2_KEY_ID/B2_APPLICATION_KEY from the
environment at import time (see storage_b2.py). The script_writing stage's
code path never touches storage_b2 at all - only the video_generation
stage does, via check_b2_key_alive(). But because the import was
unconditional and eager, running `--stage script_writing` in a workflow
step whose env block only sets SUPABASE_URL/SUPABASE_SECRET_KEY (and not
the B2 vars) crashed with a KeyError on B2_ENDPOINT_URL before a single
line of this script's actual logic ran. Fixed by moving the import inside
check_b2_key_alive(), so it's only loaded - and only requires B2 env vars
- when the video_generation stage actually calls it.

SHOT-COUNT RANGE FIX (2026-11-12): the planner (shot_breakdown_stage.py)
now writes about one shot per 5 seconds of narration (about 200 shots for a
17 minute script) instead of 25-35 shots in total. MAX_SHOTS raised from 35
to 450 so correct new plans are not reported as broken. Old scripts with
25-35 shots still pass.

DOCUMENTARY-QUALITY CHECKS (2026-11-12): the planner rewrite (commit
c183001, 2026-11-12T04:23:40Z) made these rules hard limits at write time,
but nothing re-checked them afterwards, so a hand edit or a planner bug
could ship a plan that looks nothing like a real documentary (one woman on
screen for 17 minutes, 34 s shots, faces morphing). verify_planner_rewrite_rules()
now re-checks, on every script created at/after PLANNER_REWRITE_AT:
protagonist named in at most 30% of shots, average shot length 3-7 s, no
shot over 12 s of narration, at least 1 in 4 shots wide/establishing, at
most ~1/3 zoom-family shots or extreme close-ups, no camera move repeated
more than twice in a row, no face close-ups, and shot excerpts covering at
least 80% of the narration. Older scripts are skipped because they were
planned under the old 25-35 shot rules and would fail these for no real
reason.
"""
import argparse
import json
import os
import re
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
MAX_SHOTS = 450

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

# ADDED (2026-11-12): planner rewrite commit c183001 landed at this time.
# Scripts created at/after it are held to the documentary-quality rules
# below; earlier scripts were planned under the old rules and are skipped.
PLANNER_REWRITE_AT = datetime.fromisoformat("2026-11-12T04:23:40+00:00")

# Duplicated from shot_breakdown_stage.py on purpose (contract, not
# implementation - see MIN_SHOTS above).
WORDS_PER_SECOND = 2.5
MIN_AVG_SHOT_SECONDS = 3.0
MAX_AVG_SHOT_SECONDS = 7.0
HARD_MAX_SHOT_SECONDS = 12.0
MIN_COVERAGE = 0.80
PROTAGONIST_MAX_RATIO = 0.30
MIN_WIDE_RATIO = 0.25
MAX_ZOOM_SHOT_RATIO = 0.32
MAX_CONSECUTIVE_SAME_MOVEMENT = 2
ZOOM_FAMILY_MOVEMENTS = {"push_in", "crash_zoom", "zoom_in", "snap_zoom", "dolly_in"}
FACE_WORDS = ("face", "faces", "eye", "eyes", "gaze", "stare", "staring", "portrait", "expression")

# Same name detection as prompt_focus.py (copied, not imported).
_NAME_RE = re.compile(
    r"recurring (?:protagonist|character)(?:,?\s+(?:is|named|called))?\s+(?:named\s+|called\s+)?([A-Z][^\s,.;:]+)"
)
_INTRO_RE = re.compile(
    r"\b([A-Z][^\s,.;:]+)(?:\s+[A-Z][^\s,.;:]+)?\s+is\s+an?\s+[\w-]*year[\w-]*old"
)
_PEOPLE_RE = re.compile(
    r"\b(man|men|woman|women|person|persons|people|child|children|girl|boy|clerk|clerks|"
    r"worker|workers|soldier|soldiers|officer|officers|guard|guards|figure|figures|crowd|"
    r"crowds|villager|villagers|family|families|couple|silhouette|silhouettes|"
    r"he|she|they|his|her|their|him|them|staff|passengers|residents|neighbors|"
    r"neighbours|onlookers|bystanders|pedestrians|mother|father|son|daughter|doctor|nurse|"
    r"priest|farmer|farmers|prisoner|prisoners|inmates|refugees|civilians|youth|elder|"
    r"elders|boys|girls|students|teacher|teachers|merchant|merchants)\b",
    re.IGNORECASE,
)


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
    that nothing has verified since it was written. Only used for real
    https:// URLs (legacy video_chunk_urls) - see check_b2_key_alive for
    video_url, which is a bare B2 object key, not a URL."""
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


def check_b2_key_alive(object_key, min_bytes=None):
    """ADDED (2026-09-02): the B2-key equivalent of check_url_alive, for
    scripts.video_url now that it holds a bare object key instead of a
    URL. Uses storage_b2.object_size() (a real B2 head_object call) rather
    than an HTTP request.

    LAZY IMPORT (2026-09-10): storage_b2 is imported here, not at module
    level, so the script_writing stage (which never calls this function)
    doesn't need B2_ENDPOINT_URL/B2_KEY_ID/B2_APPLICATION_KEY set."""
    import storage_b2
    size = storage_b2.object_size(object_key)
    if size is None:
        return False, "object not found in B2 (or could not be checked)"
    if min_bytes is not None and size < min_bytes:
        return False, f"only {size} bytes (min {min_bytes})"
    return True, None


def _parse_created_at(script):
    raw = script.get("created_at")
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def _protagonist_name(anchor):
    match = _NAME_RE.search(anchor or "") or _INTRO_RE.search(anchor or "")
    return match.group(1).strip() if match else None


def _names_protagonist(shot, name):
    text = " ".join([shot.get("visual_description") or "", shot.get("primary_subject") or ""]).lower()
    if name and re.search(r"\b" + re.escape(name.lower()) + r"\b", text):
        return True
    return "protagonist" in text or "main character" in text


def verify_planner_rewrite_rules(script, shot_list):
    """ADDED (2026-11-12): re-checks the documentary-quality rules the new
    planner enforces at write time. Only applies to scripts created
    at/after PLANNER_REWRITE_AT; older scripts return no problems."""
    problems = []
    created_at = _parse_created_at(script)
    if created_at is None or created_at < PLANNER_REWRITE_AT:
        return problems

    shots = [s for s in shot_list if isinstance(s, dict)]
    n = len(shots)
    if n == 0:
        return problems

    # 1. Protagonist named in at most 30% of shots (same cap formula as planner).
    name = _protagonist_name(script.get("setting_and_characters"))
    hits = [i for i, s in enumerate(shots) if _names_protagonist(s, name)]
    cap = max(1, int(n * PROTAGONIST_MAX_RATIO))
    if hits and len(hits) > cap:
        problems.append(
            f"protagonist{' ' + name if name else ''} named in {len(hits)}/{n} shots "
            f"({len(hits) / n:.0%}), max {PROTAGONIST_MAX_RATIO:.0%}"
        )

    # 2. Average shot length, from narration word count.
    narration = (script.get("narration_text") or "").strip()
    if narration:
        total_seconds = len(narration.split()) / WORDS_PER_SECOND
        avg = total_seconds / n
        if not (MIN_AVG_SHOT_SECONDS <= avg <= MAX_AVG_SHOT_SECONDS):
            problems.append(
                f"average shot is {avg:.1f} s of narration, outside "
                f"{MIN_AVG_SHOT_SECONDS:.0f}-{MAX_AVG_SHOT_SECONDS:.0f} s"
            )
        covered = sum(len((s.get("narration_excerpt") or "").split()) for s in shots)
        narration_words = len(narration.split())
        if narration_words and covered < MIN_COVERAGE * narration_words:
            problems.append(
                f"shot excerpts cover only {covered} of {narration_words} narration words "
                f"({covered / narration_words:.0%}), min {MIN_COVERAGE:.0%} - picture and voice drifted apart"
            )

    # 3. No single shot over 12 s of narration.
    too_long = [
        i for i, s in enumerate(shots)
        if len((s.get("narration_excerpt") or "").split()) / WORDS_PER_SECOND > HARD_MAX_SHOT_SECONDS
    ]
    if too_long:
        problems.append(
            f"{len(too_long)} shot(s) cover more than {HARD_MAX_SHOT_SECONDS:.0f} s of narration "
            f"(first at index {too_long[0]})"
        )

    # 4. Shot variety: wide/establishing share.
    wide = sum(1 for s in shots if s.get("shot_type") in ("wide", "establishing"))
    if wide / n < MIN_WIDE_RATIO:
        problems.append(f"only {wide}/{n} shots ({wide / n:.0%}) are wide/establishing, min {MIN_WIDE_RATIO:.0%}")

    # 5. Zoom discipline.
    zoomy = sum(
        1 for s in shots
        if s.get("camera_movement") in ZOOM_FAMILY_MOVEMENTS or s.get("shot_type") == "extreme_close_up"
    )
    if zoomy > int(n * MAX_ZOOM_SHOT_RATIO):
        problems.append(f"{zoomy}/{n} shots ({zoomy / n:.0%}) are zooms/extreme close-ups, max {MAX_ZOOM_SHOT_RATIO:.0%}")

    # 6. Same camera move repeated too many times in a row.
    run, prev = 0, None
    for i, s in enumerate(shots):
        move = s.get("camera_movement")
        run = run + 1 if move and move == prev else 1
        prev = move
        if move and run > MAX_CONSECUTIVE_SAME_MOVEMENT:
            problems.append(f"camera move {move!r} repeated {run} times in a row (at shot index {i})")
            break

    # 7. Face close-ups (the video model draws faces badly).
    face_closeups = [
        i for i, s in enumerate(shots)
        if s.get("shot_type") in ("close_up", "extreme_close_up")
        and _PEOPLE_RE.search(s.get("visual_description") or "")
        and any(re.search(r"\b" + w + r"\b", (s.get("visual_description") or "").lower()) for w in FACE_WORDS)
    ]
    if face_closeups:
        problems.append(f"{len(face_closeups)} face close-up(s) (first at index {face_closeups[0]})")

    return problems


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
        problems.extend(verify_planner_rewrite_rules(script, shot_list))

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
    live and non-trivial - not just a string in a column that nothing has
    verified since it was written, and not just an upload call that
    returned success without the bytes actually being real.

    STORAGE MIGRATION FIX (2026-09-02): video_url is now a bare B2 object
    key (checked via check_b2_key_alive/storage_b2), not an https:// URL.
    video_chunk_urls is untouched - it's always a real Supabase Storage
    URL list from before the migration (checked via the original
    check_url_alive), since no script created after the migration will
    ever have this field populated.
    """
    problems = []
    video_url = script.get("video_url")
    chunk_urls = script.get("video_chunk_urls")

    if not video_url and not chunk_urls:
        problems.append("status is video_generated but both video_url and video_chunk_urls are empty")
        return problems

    if video_url:
        ok, reason = check_b2_key_alive(video_url, min_bytes=MIN_VIDEO_BYTES)
        if not ok:
            problems.append(f"video_url (B2 key) not verified: {reason}")

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
