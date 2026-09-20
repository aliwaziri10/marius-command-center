# Marius Command Center — Handoff Doc
Last updated: 2026-09-21 — scripts list and session log refreshed (full rewrite was 2026-09-19).
Re-verify against live data before trusting anything below — this doc lags reality
by definition. If something here contradicts live Supabase/GitHub state, live state wins.

---

## STANDING RULES (read this section first, every session, no exceptions)

These apply to any session — any AI, any tool, any profile — working on this repo.

1. **Never edit a file from memory.** `view`/fetch the FULL current content of a
   file from GitHub `main` immediately before editing it, every time, even if you
   edited it minutes ago in the same session. Files here get rewritten by
   different sessions in the same week. Pasting an old version back silently
   overwrites newer fixes with no error or warning from GitHub.

2. **Every fix gets a dated docstring/comment, in-file, at the point of the
   change** — not just in this handoff doc. Say what broke, the confirmed root
   cause (not a guess — cite the actual error/traceback/live data that proved
   it), and what the fix does. This file summarizes; the code is the permanent
   record. Follow the existing convention already used throughout every file in
   `scripts/` (e.g. `POLL-TIMEOUT CRASH FIX (2026-09-18)` in `agnes_client.py`).

3. **Update this handoff doc at the end of any session that changes root-cause-
   relevant state** — a real bug fixed, a schema change, a provider/credential
   swap, a new file added to the pipeline. Skipping this is what made the
   previous version of this doc stale for three weeks. A session that only
   answers questions or investigates without changing anything doesn't need to
   update this file.

4. **Confirm root cause from live data before fixing anything** — a Supabase
   query, a GitHub Actions issue body, an actual traceback. Never fix based on
   a guess or a pattern-match to "looks like the same bug as last time." Every
   fix committed to this repo should be traceable to a specific piece of
   evidence, not a hunch.

5. **One project per session where avoidable** — don't touch Marius and Nova in
   the same session/commit. They are separate Supabase orgs, separate repos,
   separate B2 buckets, separate everything except the underlying agent
   pattern. A fix confirmed on one is not automatically valid on the other —
   re-verify independently.

6. **Targeted fixes only, not full-file rewrites, unless the change genuinely
   touches most of the file.** Preserve every existing comment/docstring in a
   file you're editing — they're the fix history, not clutter. Only rewrite a
   whole file (as this handoff doc itself was, this session) when the doc/file
   is broadly stale, not for a single fix.

7. **Never assume a workflow that "exits 0" actually did anything.** This
   pipeline has a confirmed history (`trend_research.py`, fixed 2026-09-19) of
   a script silently swallowing every failure with `print()` + `continue` and
   exiting clean while doing nothing at all, for weeks, with zero GitHub issues
   ever opened. When investigating "why isn't X happening," check the real
   data the script was supposed to produce (a table's row count, a file's
   existence) — not just whether its workflow runs show green.

8. **Secrets can silently contain leading/trailing whitespace or newlines from
   how they were pasted in.** This has caused a full pipeline stall at least
   once (`B2_KEY_ID`, 2026-09-14/18 — see below). Every secret this pipeline
   reads should be `.strip()`'d at the point of use, defensively, regardless of
   whether the current value is known-clean.

---

## Pipeline

`topic_research` (grounded, since 2026-09-19, by real Wikipedia-pageviews
trend signals — see below) → `script_writing` (orchestrates `llm_client.py` +
`narration_stage.py` + `shot_breakdown_stage.py`) → `narration` → `images_generated`
→ `video_generation` (resumable, per-script shot budget shared across a run) →
`video_generated` → `youtube_upload` → `uploaded`. Channel: `@erased.fromhistory`
("Erased From History").

Housekeeping workflows: `health_check`, `stall_monitor`, `update_status`,
`cleanup_dead_storage`, `code_health_check`, `codemap`, `thumbnail_generation`.
(`dependency_graph` no longer exists as a workflow; removed from this list 2026-09-21.)

## Current `scripts/` files (2026-09-21, confirmed live via a clone of `main`)

All 23 are live: `agnes_client.py`, `assembly_stage.py`, `b2_preflight.py`
(run by `video_generation.yml`), `beat_director.py`, `clip_generation.py`,
`cleanup_dead_storage.py`, `health_check.py`, `llm_client.py`,
`narration.py`, `narration_stage.py`, `prompt_builder.py`,
`quality_checker.py`, `script_writing.py`, `shot_breakdown_stage.py`,
`stall_monitor.py`, `storage_b2.py`, `thumbnail_generation.py`,
`topic_research.py`, `trend_research.py`, `update_status.py`,
`verify_run_output.py` (run by `script_writing.yml` and
`video_generation.yml`), `video_generation.py`, `youtube_upload.py`.

Deleted 2026-09-19 after confirming zero references: `health_agent.py`,
`image_generation.py`, `test_narration_edgetts.py`,
`test_narration_freellm.py`.

## Storage: Backblaze B2 (migrated 2026-09-02, still current)

All video/image assets live in B2 (bucket `marius-media-zia`), not Supabase
Storage (Supabase org is Free tier — real per-object size ceiling). Only the
permanent, non-expiring B2 **object key** is ever persisted to Supabase
(`video_urls`, `video_url`, `video_chunk_urls`, `character_reference_url`) —
never a presigned URL. See `storage_b2.py` module docstring for the full
reasoning (a single resumable episode can span 19+ days across runs, so any
fixed-expiry URL would silently break mid-episode).

## Supabase project (re-verify at the start of every session — this has
changed twice before)

Project ID as of 2026-09-18: `iwgocbiqjjhlvkygmcir`, name `marius`, org
`pvckgioutauwsnbvhwfs`, region `ap-northeast-1`. Separate org from Nova's —
never assume shared quota or shared anything with Nova's Supabase project.

---

## Session log (most recent first — keep this section, don't delete old
entries; trim only once it gets unwieldy)

### 2026-09-21 — Agnes create-task ReadTimeout crash fixed; declutter
`create_agnes_task`'s `requests.post` had no exception handling, so a
`ReadTimeout` killed the script's run (confirmed in script `3c7d572f`'s
`last_error` traceback; commit `3506266`). Reproduced with a mock on the
old code, verified on the new. The poll-429 crash was fixed separately on
2026-09-20. All `last_error` values in Supabase date from 2026-09-19;
whether runs since then progress is NOT yet verified (see
`CONTINUATION.md` PART 5). Four unreferenced scripts were deleted (list
above).

### 2026-09-19 — Trend grounding was completely dead since creation
`trend_signals` table had **zero rows, ever**, since it was created
2026-09-13 — `trend_research.py` ran daily via cron and silently saved
nothing every single time. Confirmed root cause: the old version pulled
from Reddit's unauthenticated JSON API, which blocks essentially all
cloud/datacenter IP traffic (GitHub Actions runners are Azure) — no
User-Agent or retry-count fix gets around this. Compounding it: every
failure path caught its own exception, printed, and continued — the
workflow always exited 0 and never opened a single failure issue, so this
was invisible from the Actions UI. Rewrote `trend_research.py` to pull
from Wikipedia's official Pageviews API instead (public, unauthenticated,
does not block cloud IPs), and made a total-failure run raise instead of
silently succeeding at doing nothing. `topic_research.py` already treats
trend_signals as optional best-effort grounding (unchanged) — this fix
just makes sure that grounding is ever actually present.

Separately, 56 of 72 topics were sitting in `generation_failed` (content-
quality rejections in `shot_breakdown_stage.py` — modern-object mentions,
hook-text length, independent-shot-quality checker rejections — genuine
misses, not one repeating bug) leaving only 1 topic in the `pending`
queue. Requeued all 56 back to `pending` for a fresh generation attempt.
`MAX_GENERATION_ATTEMPTS = 3` in `shot_breakdown_stage.py` is thin against
how often these hard-rejections fire — worth revisiting if this recurs.

### 2026-09-18/19 — Video generation stall, three independent root causes
`video_generation` had been failing continuously since ~2026-09-06 (254+
open "workflow failed" issues, run #965 through #1001+), leaving every
`images_generated` script stuck at 0-1 clips generated. Three separate,
independently confirmed causes, fixed in this order:
1. `B2_KEY_ID` GitHub secret had a literal embedded newline, corrupting
   the AWS SigV4 Authorization header on every single upload
   (`ValueError: Invalid header value`) — fixed by Zia re-pasting the
   secret clean; `storage_b2.py` also defensively `.strip()`s all three
   B2 env vars now regardless.
2. `poll_agnes_task` in `agnes_client.py` had a bare 30s timeout with no
   try/except — a normal slow-but-not-actually-failed Agnes poll response
   crashed the entire script's run instead of just waiting and polling
   again. Fixed: catches `requests.exceptions.RequestException` inside
   the poll loop, retries up to `POLL_MAX_CONSECUTIVE_NETWORK_ERRORS`
   times before giving up.
3. `storage_b2.upload_bytes` had no retry around `put_object` — a dropped
   TLS connection mid-upload (`SSLEOFError`) killed the run even though
   boto3's own default retry (3 attempts) had already run and still
   surfaced it. Fixed: explicit retry loop, `UPLOAD_MAX_RETRIES = 4`.

Separately (same investigation): `color_palette` was added to
`shot_breakdown_stage.py`'s write-time validation on 2026-08-20, but the
matching Supabase column was **never created** — every write of it since
then silently failed against a schema PostgREST rejected, and
`verify_run_output.py`'s script_writing check has been failing on every
run since, for every script created after that date, with the real
`color_palette` text permanently lost (generated in-memory, never
persisted). Fixed: column added (`ALTER TABLE scripts ADD COLUMN
color_palette text`), the 15 affected existing rows backfilled with a
placeholder (their real palette text is unrecoverable — the shots/video
for those episodes were already generated before this was caught, so the
placeholder has no practical effect on those specific episodes).

**Not yet verified:** whether a full script now completes end-to-end
(images_generated → video_generated → uploaded) post-fix — check
`video_next_index` / clip counts against `total_shots` for the
in-progress candidates on the next session, and confirm at least one new
`uploaded` script appears.

---

## Older history (pre-2026-09-18, unverified against current live state —
kept for context only, do not trust without re-checking)

- LLM provider: Gemini, `gemini-3.5-flash-lite` model (switched back from
  Groq 2026-08-17 — Groq's 429 headers could show fully replenished quota
  while still permanently failing on an invisible daily cap; Gemini names
  the exact quota metric hit instead). Do not switch providers again
  without a live test proving the new provider's failure mode is
  diagnosable.
- `script_writing.py` was split (2026-08-18) into `llm_client.py` /
  `narration_stage.py` / `shot_breakdown_stage.py` + orchestration —
  no behavior change from the split itself.
- Video bitrate fixed at `QUALITY_VIDEO_BITRATE_KBPS` regardless of
  duration (2026-08-20) — previously scaled down on longer episodes,
  visibly hurting quality.
- Marius `QUALITY_GUARD` explicitly requires vivid saturated color, bans
  desaturation/sepia/monochrome. **Marius has never had a monochrome
  guard** — full-motion black & white is Nova-only. Do not carry Nova's
  B&W direction into Marius work.
- Narration sentence-splitting (`_ABBREVIATIONS` guard in `narration.py`)
  confirmed byte-for-byte identical to Nova's equivalent as of 2026-08-29
  — fixes the "narration cuts off mid-sentence on Dr./U.S./etc." bug at
  the code level. Whether this actually eliminates the audible pause on a
  real rendered episode was still unverified as of that date.
