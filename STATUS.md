# Marius Status
Updated: 2026-08-07 (session handoff)

Topics: 204 pending, 45 scripted
Scripts by status: archived=18, uploaded=18, images_generated=5, content_flagged=0
TTS engine: edge-tts (en-US-GuyNeural) — Chatterbox-TTS fully reverted 2026-08-06 (was too slow/heavy on GitHub-hosted CPU runners, caused workflow stalls ~25min then runner kill)
Content-flag fix: live on main (fallback strips ethnicity/atrocity terms from Agnes anchor before retry) — 3 previously-flagged scripts reset to images_generated, not yet re-tested under load
Open issue: script_writing.py has crashed 3x (Aug 6), zero new scripts since Aug 6 00:23 — crash suspected in save_script()/mark_topic_scripted() (outside try/except), not yet confirmed (no Action log access)
GitHub write access: still 403 "Resource not accessible by integration" — confirmed again 2026-08-07
