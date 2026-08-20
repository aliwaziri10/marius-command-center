# Marius Command Center — Handoff Doc
Last updated: 2026-08-20
Re-verify against live data — don't trust this doc at face value.

## READ BEFORE EDITING ANY FILE IN scripts/
Any session (any AI, any tool) must `view`/fetch the FULL current content
of a file from GitHub main immediately before editing it. Do not edit
from memory of an earlier version, a chat-log summary, or a cached
snippet — files here have been rewritten multiple times in the same week
by different sessions. Pasting an old version back overwrites newer fixes
with no error or warning.

Current `scripts/` files (2026-08-20):
`health_check.py`, `llm_client.py`, `narration.py`, `narration_stage.py`,
`quality_checker.py`, `script_writing.py`, `shot_breakdown_stage.py`,
`stall_monitor.py`, `thumbnail_generation.py`, `topic_research.py`,
`update_status.py`, `verify_run_output.py`, `video_generation.py`,
`youtube_upload.py`. (`image_generation.py`, `test_narration_edgetts.py`,
`test_narration_freellm.py` also present — legacy/test, not in the live
pipeline path; confirm before touching.)

## Pipeline
topic_research → script_writing (now split: llm_client.py +
narration_stage.py + shot_breakdown_stage.py, orchestrated by
script_writing.py) → narration → images_generated → video_generation
(resumable) → video_generated → uploaded. Channel: @erased.fromhistory
(Erased From History).

## Current LLM provider: Gemini (`gemini-3.5-flash-lite`)
Switched back from Groq 2026-08-17. Uses `GEMINI_API_KEY` secret
(confirmed present in repo). Groq abandoned because its 429s can show
FULLY replenished per-minute headers (1000/1000 requests, 12000/12000
tokens) while still permanently failing — the real constraint (likely
Groq's daily TPD cap) is structurally invisible in anything readable from
the response. Gemini's 429 body instead names the exact quota metric hit
(`quotaMetric`/`quotaId`) — an unambiguous signal Groq never gave.
`llm_client.py` now raises `DailyQuotaExhausted` only when the body
explicitly names a daily/free-tier metric, not from guessed headers.

**Do not switch providers again without a live test proving the new
provider's failure mode is actually diagnosable — Groq's silent-failure
behavior is exactly why it was replaced. See DailyQuotaExhausted class
docstring in llm_client.py for the full reasoning.**

## Confirmed working (2026-08-20)
```sql
select id, status, created_at from scripts order by created_at desc limit 5;
```
5 new scripts since 2026-08-19, most recent same-day. Status breakdown:
23 `uploaded`, 18 `archived`, 7 `images_generated` (normal queue depth).
Zero-output period (2026-08-06 to 2026-08-17) is resolved.

## File split (2026-08-18, separate session)
`script_writing.py` used to hold everything. Now:
- `llm_client.py`: `call_llm()`, `retryable_request()`, `InfraFailure`,
  `DailyQuotaExhausted`, JSON extraction/sanitization
- `narration_stage.py`: `generate_narration()` and its prompts
- `shot_breakdown_stage.py`: `generate_shot_breakdown()`, shot validation,
  chunking logic
- `script_writing.py`: orchestration only (fetch topic, call both
  stages, save, update status)
No behavior change from the split itself — same logic, moved.

## Video quality fix (2026-08-20, separate session)
19-minute upload ("The Gambian Weaver and Refugee Relief",
`ba5d96c8-5c00-4619-9d84-830291ed9aab`) came out visibly bad quality.
Root cause: video bitrate scaled down as episode duration increased.
Fixed in `video_generation.py` — bitrate now fixed at 3000 kbps
regardless of duration (`QUALITY_VIDEO_BITRATE_KBPS`). That script was
reset to `images_generated` with video fields cleared on 2026-08-20 to
regenerate at the corrected bitrate — **will create a NEW public YouTube
upload, does not overwrite the old one**. Old video
(`youtube.com/watch?v=g_dJrGizi9Q`) needs manual deletion by Zia once the
new one is confirmed live.

## Color/style — do not confuse with Nova
Marius `QUALITY_GUARD` (in `video_generation.py`) explicitly requires
**vivid saturated color**, explicitly bans desaturation/sepia/monochrome.
Marius has never had a monochrome guard. Full-motion black & white is
**Nova-only** (separate repo, separate pipeline). Confirmed live in code
2026-08-20 — do not carry Nova's B&W direction into Marius work.

## Standing gotchas
- GitHub App connector ("Claude for GitHub") is permanently **read-only**
  on this repo (admin/code/metadata read access only).
- Working write path: Zia has this repo cloned locally on Windows, PAT
  (repo+workflow scopes) embedded in `git remote set-url origin` — pushes
  via `git push` from CMD, no connector needed. Token never shared in
  chat.
- `InfraFailure` and `DailyQuotaExhausted` both exit quietly (exit code 0)
  by design when every topic in a batch is blocked — a green run in
  GitHub Actions does NOT mean a script was produced. Always check live
  Supabase `scripts.created_at`, never trust run status alone.
- Two scripts still stuck `content_flagged` (unrelated to any fix above):
  - `92dec2f9-05e6-4d32-8fa3-6c5e76f97c9b` "The Bakery That Hid 25" —
    WWII/Nazi imagery flagged
  - `716623f1-583b-4f6f-a8b8-9dfefe29fcf2` "The Hutu Who Hid Tutsi
    Families in Rwanda's 1994 Genocide" — shot index 30/72 flagged
