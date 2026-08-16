# Marius Command Center — Handoff Doc
Last updated: 2026-08-17
Re-verify against live data — don't trust this doc at face value.

## Pipeline
topic_research → script_writing → narration → images_generated →
video_generation (resumable, CLIP_BATCH_LIMIT=8 shots/run) →
video_generated → uploaded. Channel: @erased.fromhistory (Erased From History).

## Current LLM provider
Groq, `llama-3.3-70b-versatile`, free tier: 30 RPM, 12,000 TPM, AND an
undocumented daily token cap (TPD) not exposed in any response header
(~100K tokens/day, per Groq docs/community — not officially confirmed).
Gemini and OpenRouter were both removed as providers earlier (Aug 6/15).

## What was broken (confirmed live, 2026-08-17)
Nothing shipped since **2026-08-06**. Verified via Supabase
`swnjzzejsuupecdgbzzf`:
```sql
select id, status, created_at from scripts order by created_at desc limit 5;
```
Latest row: `82eb9746...` created `2026-08-06 00:23:27`. Nothing since.

GitHub Actions shows 5 `script_writing.yml` runs Aug 15-16, ALL
`conclusion: success` — but zero scripts saved in that window. This is
NOT a contradiction: `main()` in `script_writing.py` deliberately
`return`s with exit code 0 when it catches `SuspectedDailyQuotaExhausted`,
so a run that hit Groq's daily cap on the first topic shows green in
GitHub Actions while doing nothing. Confirmed from two angles: (1) code
read directly — the `except SuspectedDailyQuotaExhausted: ... return` in
`main()`, (2) live Supabase data — zero new rows across all 5 "successful"
runs.

The 2026-08-15 chunked-shot-breakdown fix (splitting one 60-85 shot
request into 3 Groq calls to stay under the 12,000 TPM per-minute cap)
was necessary but not sufficient — it fixed the *per-minute* ceiling but
not the *per-day* one, since the daily cap is on total tokens across ALL
calls in a day, not just the size of any one call.

## Fix applied 2026-08-17 (this session)
`scripts/script_writing.py`:
- `MIN_SHOTS` 60→**25**, `MAX_SHOTS` 85→**35**
- `NUM_SHOT_CHUNKS` 3→**2**

Rationale: cannot monitor or raise Groq's daily cap (invisible, free tier,
no-spend rule forbids paid tier) — only lever is reducing total tokens
spent per script. Fewer shots = smaller output per chunk call. Fewer
chunks = the full narration text (repeated in full as input on every
chunk call — the dominant cost) gets sent 2x instead of 3x per script.

Verified: file compiles (`python -m py_compile`), constants confirmed via
`findstr` after edit.

**NOT yet verified**: whether this actually gets a script under the daily
cap. Groq's TPD is invisible — the only way to confirm is watching the
next real run(s) land a new row in `scripts`.

## Still unverified — check first next session
- Did a new script actually save after this fix? Check:
  `select count(*) from scripts where created_at > '2026-08-17';`
- If still zero after 2+ scheduled runs: the shot-count cut wasn't enough.
  Next lever: reduce `NARRATION_MAX_CONTINUATIONS` (currently 3) or
  `NARRATION_TARGET_WORDS` (currently 1800) — narration continuation calls
  also re-send prior narration text as input each time, same repeated-input
  cost pattern as chunking.
- Two scripts still stuck `content_flagged` (long-standing, unrelated to
  this fix):
  - `92dec2f9-05e6-4d32-8fa3-6c5e76f97c9b` "The Bakery That Hid 25" —
    flagged shot: WWII/Nazi imagery
  - `716623f1-583b-4f6f-a8b8-9dfefe29fcf2` "The Hutu Who Hid Tutsi
    Families in Rwanda's 1994 Genocide" — flagged shot index 30/72
- Secondary known bug, not yet fixed: mid-continuation 429s can call
  `mark_topic_generation_failed()`, permanently blacklisting a topic whose
  real failure was rate-limiting, not bad content. Currently low-impact —
  264 topics sit `pending`, only 4 total `generation_failed` (all from
  July) — but worth revisiting if `generation_failed` count climbs.

## Standing gotchas
- GitHub App connector ("Claude for GitHub") is permanently **read-only**
  (admin/code/metadata read access only) — cannot be changed from GitHub
  settings or Claude's connector UI. Confirmed 2026-08-17.
- Working write path (as of 2026-08-17): Zia has this repo cloned locally
  on Windows, with a PAT (repo+workflow scopes) embedded in
  `git remote set-url origin` — pushes directly from CMD via `git push`,
  no connector needed. Token was set locally only, never shared in chat.
- `youtube_video_id` column has silently failed to write back since
  ~July 20 even on successful uploads — read real progress from
  `video_next_index` + `jsonb_array_length(video_urls)` instead.
- `InfraFailure` and `SuspectedDailyQuotaExhausted` both exit quietly (no
  crash, no GitHub issue, exit code 0/"success") by design — a green run
  in GitHub Actions does NOT mean anything was produced. Always check live
  Supabase state (`scripts` table `created_at`), never trust run status
  alone.