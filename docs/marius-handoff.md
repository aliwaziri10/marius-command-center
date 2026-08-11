# Marius Command Center — Handoff Doc
Last updated: 2026-08-12

## Pipeline
topic_research → script_writing → narration → images_generated →
video_generation (resumable, CLIP_BATCH_LIMIT=8 shots/run) →
video_generated → uploaded. Channel: @erased.fromhistory (Erased From History).

## What was broken (as of 2026-08-12)
1. **Videos too short (1.5–4 min instead of 10–12 min)**: old videos
   (Aug 2–5) were made before MIN_NARRATION_WORDS=1500 validation existed
   in script_writing.py. Current code already enforces 1500+ words
   (aims 1700–2000). Fix is live in code — NOT yet confirmed on a real
   produced video, since nothing shipped between Aug 6 and this fix.

2. **Nothing shipped since Aug 6**: script_writing.py silently stalled.
   Root cause confirmed via aistudio.google.com/rate-limit: Marius's
   Gemini key hit 44/20 daily request cap (RPD) on gemini-3.5-flash.
   Every call 429'd; script_writing.py's InfraFailure path deliberately
   exits clean (no crash, no GitHub issue) on pure infra failure, so this
   produced total silence for days — looked like nothing was happening
   because nothing was, but with no error trail.

   Why quota blew out: script_writing.py had MAX_GENERATION_ATTEMPTS=10,
   each attempt making up to MAX_RETRIES=4 Gemini calls internally —
   worst case 240 calls/run against a 20/day cap, on a 4-hour cron (6
   runs/day). topic_research.py similarly had MAX_RETRIES=4 on its own
   6-hour cron.

## Fix applied 2026-08-12 (via GitHub web editor, confirmed landed)
- `scripts/script_writing.py`: MAX_RETRIES 4→2, MAX_GENERATION_ATTEMPTS 10→3
- `scripts/topic_research.py`: MAX_RETRIES 4→2
- `.github/workflows/script_writing.yml`: cron 4h → 12h
  (`"0 */12 * * *"` — note: first edit had a typo, `"0 *12 * * *"`,
  which is invalid cron syntax; caught and fixed same session)

New worst-case daily Gemini budget: ~20 calls/day total (topic_research
~8 + script_writing ~12), down from 240+. Should stay under the free-tier
20 RPD ceiling going forward.

## Still unverified — check first next session
- Has script_writing actually produced a new script since this fix?
  Check: `select count(*) from scripts where created_at > '2026-08-12'`
  on Supabase project `swnjzzejsuupecdgbzzf`.
- Has a new script made it all the way to `uploaded` status, and is its
  narration_text actually 1500+ words this time?
- Is the 20 RPD daily budget actually holding, or still getting hit?
  Check aistudio.google.com/rate-limit (project marius-command-center,
  key "...7kUA") for Gemini 3.5 Flash RPD.
- Two scripts still stuck `content_flagged` (from before this session):
  - `92dec2f9-05e6-4d32-8fa3-6c5e76f97c9b` "The Bakery That Hid 25" —
    flagged shot: WWII/Nazi imagery
  - `716623f1-583b-4f6f-a8b8-9dfefe29fcf2` "The Hutu Who Hid Tutsi
    Families in Rwanda's 1994 Genocide" — flagged shot index 30/72
  Both need their flagged shot's visual_description reworded, then
  status reset to `images_generated` to resume.

## Standing gotchas (see also memory /areas/marius-command-center.md)
- GitHub write API (create_or_update_file, push_files) returns 403 on
  this repo — always use the web editor.
- `youtube_video_id` column has silently failed to write back since
  ~July 20 even on successful uploads — read real progress from
  `video_next_index` + `jsonb_array_length(video_urls)` instead.
- `AgnesOverloadedError` and Gemini `InfraFailure` both exit quietly
  (no crash, no issue) by design — absence of a GitHub issue does NOT
  mean things are working. Always check live Supabase state.
