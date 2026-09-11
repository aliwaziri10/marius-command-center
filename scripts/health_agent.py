"""
Marius Command Center - Health Agent
Runs every 3 hours via .github/workflows/health_agent.yml (cron). Checks
the pipeline for stuck/failed work and reports a clear status - this
first version DIAGNOSES and SURFACES problems (topics stuck in
generation_failed, scripts with last_error set, no new scripts/videos in
an unexpectedly long window). It does not yet auto-write code fixes -
that requires an LLM-in-the-loop step (calling Gemini/Claude with the
failing file + error) which is the next planned addition once this base
diagnostic loop is confirmed running reliably on the 3-hour cron.

Exit code is always 0 (never fails the workflow run itself) - a health
problem found is reported in the log/status file, not treated as an
Actions failure, so the cron keeps running on schedule regardless of
what it finds.
"""

import os
import json
import time
import requests
from datetime import datetime, timezone

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SECRET_KEY"]
HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
}


def sb_get(path):
    resp = requests.get(f"{SUPABASE_URL}/rest/v1/{path}", headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return resp.json()


def check_stuck_topics():
    """Topics sitting in generation_failed - these will NEVER retry on their
    own (script_writing.py deliberately skips them), so they're the
    clearest signal of "the pipeline needs a human or an agent to look at
    something."""
    failed = sb_get("topics?status=eq.generation_failed&select=id,title,last_failure_reason&order=created_at.desc")
    return failed


def check_stuck_scripts():
    """Scripts with last_error set - something failed downstream of
    script_writing (video_generation, narration, etc.) and left a trail."""
    errored = sb_get("scripts?last_error=not.is.null&select=id,topic_id,last_error,last_error_at&order=last_error_at.desc&limit=20")
    return errored


def check_recent_output():
    """How long since the last script/video was actually produced -
    the single clearest "is this pipeline alive at all" signal."""
    scripts = sb_get("scripts?select=id,created_at&order=created_at.desc&limit=1")
    videos = sb_get("videos?select=id,created_at&order=created_at.desc&limit=1")
    return {
        "last_script_at": scripts[0]["created_at"] if scripts else None,
        "last_video_at": videos[0]["created_at"] if videos else None,
    }


def main():
    report = {
        "run_at": datetime.now(timezone.utc).isoformat(),
        "stuck_topics": check_stuck_topics(),
        "errored_scripts": check_stuck_scripts(),
        "recent_output": check_recent_output(),
    }

    print("=== Marius Health Agent Report ===")
    print(json.dumps(report, indent=2, default=str))

    if report["stuck_topics"]:
        print(f"\n[ALERT] {len(report['stuck_topics'])} topic(s) stuck in generation_failed:")
        for t in report["stuck_topics"]:
            print(f"  - {t['id']}: {t['title']} -- {t['last_failure_reason']}")
    else:
        print("\n[OK] No topics stuck in generation_failed.")

    if report["errored_scripts"]:
        print(f"\n[ALERT] {len(report['errored_scripts'])} script(s) with a recorded last_error:")
        for s in report["errored_scripts"]:
            print(f"  - {s['id']}: {s['last_error']} (at {s['last_error_at']})")
    else:
        print("\n[OK] No scripts with a recorded last_error.")

    print(f"\nLast script produced: {report['recent_output']['last_script_at']}")
    print(f"Last video produced: {report['recent_output']['last_video_at']}")

    # Always exit 0 - this is a diagnostic run, not a gate. A real problem
    # found here should be visible in the Actions log, not fail the run.
    print("\nHealth check complete.")


if __name__ == "__main__":
    main()
