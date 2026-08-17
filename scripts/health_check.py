"""
Marius Command Center - Health Check
Read-only monitor. Runs on its own schedule via GitHub Actions, independent
of every other workflow in this repo. Its only job is to detect the specific
silent-failure signatures already documented in project memory - it does
NOT diagnose root cause and does NOT touch/patch any pipeline code. When it
finds a problem it opens/updates a single GitHub issue; a human or a future
session runs the actual diagnostic skills (verify-live-state,
diagnose-content-policy-flag, audit-provider-fallback) from there.

Why this exists: the real cost on this pipeline hasn't been finding fixes -
once found, they've usually landed same-day. The cost has been NOTICING
something was wrong at all (e.g. zero new scripts for 9 days, Aug 6-15,
went unnoticed because main() exits code 0 even when every topic fails,
so no workflow-failure issue ever fired). This script exists purely to
close that noticing gap.

CHECKS (each independent, each can fire its own issue):
1. No new row in `scripts` table in STALE_HOURS_SCRIPTS hours.
2. Any `pending` script with incomplete video generation (video_urls
   shorter than shot_list) past STUCK_HOURS since creation - the
   documented Agnes freeze-loop / quota-exhaustion pattern.
3. `generation_failed` topic count - informational only, not itself a
   failure state (topic_research is currently permanently stopped per
   standing instruction, so this is just visibility on the existing
   backlog, not something new accumulating).

Note: topics-table staleness isn't checked, since topic_research is
deliberately, permanently stopped - a stale `topics` table is expected,
not a fault.
"""

import os
import sys
from datetime import datetime, timezone

import requests

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SECRET_KEY"]

HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
}

STALE_HOURS_SCRIPTS = 18   # script_writing runs every 12h; alert past one missed cycle
STUCK_HOURS = 48           # a 'pending' script (still generating shots) sitting idle this long is stuck, not slow

# Confirmed live via Supabase schema check (2026-08-18): status is a coarse
# text field (archived/content_flagged/pending/uploaded), NOT a granular
# per-stage enum. Per-shot generation progress lives in the video_urls
# jsonb array vs shot_list length, not in a status string - so "stuck" is
# measured as "status=pending AND video_urls hasn't grown in STUCK_HOURS",
# not by a status name.


def supabase_get(path):
    resp = requests.get(f"{SUPABASE_URL}/rest/v1/{path}", headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return resp.json()


def hours_since(iso_timestamp):
    ts = datetime.fromisoformat(iso_timestamp.replace("Z", "+00:00"))
    return (datetime.now(timezone.utc) - ts).total_seconds() / 3600.0


def check_stale_scripts():
    rows = supabase_get("scripts?select=id,created_at&order=created_at.desc&limit=1")
    if not rows:
        return "ALERT: `scripts` table is completely empty - no script has ever been saved."
    age = hours_since(rows[0]["created_at"])
    if age > STALE_HOURS_SCRIPTS:
        return (
            f"ALERT: no new row in `scripts` since {rows[0]['created_at']} "
            f"({age:.1f}h ago, threshold {STALE_HOURS_SCRIPTS}h). "
            f"script_writing.yml runs every 12h - this means at least one full cycle "
            f"produced nothing. Run [[verify-live-state]] then [[audit-provider-fallback]]."
        )
    return None


def check_stuck_scripts():
    """No updated_at column exists on `scripts`, so 'stuck' is approximated
    as: still status=pending, older than STUCK_HOURS since creation, AND
    video generation is incomplete (video_urls shorter than shot_list).
    This can't distinguish 'just started' from 'frozen partway' as precisely
    as a true last-progress timestamp would - flagged as a known limitation,
    not a perfect signal. It still catches the documented pattern (e.g. a
    script stuck at 38/70 shots for days)."""
    rows = supabase_get(
        "scripts?select=id,created_at,shot_list,video_urls&status=eq.pending&order=created_at.asc"
    )
    stuck = []
    for r in rows:
        if hours_since(r["created_at"]) <= STUCK_HOURS:
            continue
        shot_count = len(r.get("shot_list") or [])
        video_count = len(r.get("video_urls") or [])
        if shot_count and video_count < shot_count:
            stuck.append((r["id"], video_count, shot_count, hours_since(r["created_at"])))
    if stuck:
        lines = "\n".join(
            f"- id={sid} {vc}/{sc} shots video-generated, age={age:.1f}h"
            for sid, vc, sc, age in stuck
        )
        return (
            f"ALERT: {len(stuck)} script(s) pending >{STUCK_HOURS}h with incomplete "
            f"video generation (matches the documented Agnes freeze-loop pattern):\n{lines}"
        )
    return None


def check_generation_failed_backlog():
    rows = supabase_get("topics?select=id&status=eq.generation_failed")
    count = len(rows)
    if count > 0:
        return (
            f"INFO (not an alert): {count} topic(s) currently sitting in "
            f"generation_failed. Not actionable on its own - just visibility. "
            f"Review with [[audit-provider-fallback]] if the count is climbing "
            f"run over run."
        )
    return None


def main():
    findings = []
    check_fns = [check_stale_scripts, check_stuck_scripts, check_generation_failed_backlog]

    for check in check_fns:
        try:
            result = check()
        except Exception as e:
            findings.append(f"CHECK ERROR in {check.__name__}: {e}")
            continue
        if result:
            findings.append(result)

    alerts = [f for f in findings if f.startswith("ALERT")]
    info = [f for f in findings if not f.startswith("ALERT")]

    print(f"Health check run at {datetime.now(timezone.utc).isoformat()}")
    for f in findings:
        print(f)

    if alerts:
        body_lines = ["## Alerts\n"] + [f"- {a}" for a in alerts]
        if info:
            body_lines += ["\n## Info\n"] + [f"- {i}" for i in info]
        print("\n---ISSUE_BODY_START---")
        print("\n".join(body_lines))
        print("---ISSUE_BODY_END---")
        sys.exit(1)  # non-zero triggers the "open/update issue" step in the workflow

    print("No alerts. Pipeline state looks healthy against all checked signatures.")
    sys.exit(0)


if __name__ == "__main__":
    main()
