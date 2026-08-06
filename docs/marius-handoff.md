# Marius Command Center — Handoff Sheet
Written: 2026-07-20, updated 2026-07-25, 2026-08-06, by Claude, verified live against Supabase and GitHub at time of writing.

## ⚠️⚠️ POST-MORTEM — READ BEFORE TOUCHING cron/timeout/concurrency/batch settings (2026-08-06)

A Claude session touched `narration.yml`/`narration.py` cron, timeout, and
batch settings across MULTIPLE separate edits, each one reactive instead of
reasoned, on a pipeline that was already running successfully. Do not repeat
this. Before changing ANY of {cron interval, timeout-minutes, concurrency,
MAX_SCRIPTS_PER_RUN / CLIP_BATCH_LIMIT / similar batch constants} in this
repo, do ALL of the following FIRST, in this order, before writing a single
line:

1. **Pull real Actions run logs** (not just docs/memory) for the workflow
   you're about to touch. Get actual run duration, not an assumption.
2. **Query Supabase directly** for the real distribution of what the
   workflow processes (e.g. `char_length(narration_text)`, shot counts,
   percentiles) — not a single sample, not a guess.
3. **Check `private` vs `public` repo status** via `GitHub:search_repositories`
   (`"private": false/true` in the result) before reasoning about any
   GitHub Actions minutes budget. Public repos = unlimited free minutes.
   This repo (`aliwaziri10/marius-command-center`) is PUBLIC — confirmed
   2026-08-06. Re-verify if it's ever made private.
4. **Do the arithmetic explicitly**: (real per-run duration) × (real
   throughput/week or /month) — and only then decide cron/timeout/batch
   numbers. Do not set a timeout shorter than the known worst-case runtime.
   Do not tighten a cron interval without checking whether the underlying
   job is actually the bottleneck (it may not be — cron gap and per-run
   duration are two separate problems; fixing one does not fix the other).
5. **Check sibling workflow files in the same repo for an existing pattern**
   (e.g. `video_generation.yml` already had `concurrency` + no missing
   timeout guard) before writing a new workflow file that's missing a
   safeguard a neighboring file already solved.
6. **State the reasoning and the numbers used, in the commit/handoff note,
   not just the resulting values** — so the next session (or next fool) can
   audit the logic, not just trust the output.

Concretely, what went wrong this session: cron was tightened from 2x/day to
every 30 min based on doc claims alone, without pulling a real run log first
— the actual bottleneck (Chatterbox CPU sampling speed, ~1 sentence/min,
confirmed via a live run log) was never the cron gap. A `timeout-minutes: 25`
was then set on a job whose own just-read log showed a 64-minute real
runtime — self-contradictory, would have killed every real run. Batch size
(`MAX_SCRIPTS_PER_RUN`) was raised to 3 then walked back to 1 based on an
assumed GitHub Actions 2,000 min/month budget that was NEVER CHECKED — the
repo is public, so that budget doesn't exist and the whole worry (and the
walk-back) was unnecessary churn caused by not verifying a checkable fact.

**Current live settings as of 2026-08-06 (verify freshly before trusting):**
- `narration.yml`: cron `*/30 * * * *`, `concurrency: group: narration,
  cancel-in-progress: false`, `timeout-minutes: 180` (pending Ali's commit).
- `narration.py`: `MAX_SCRIPTS_PER_RUN = 2` (pending Ali's commit).
- Real narration runtime data (2026-08-06, live Supabase query): avg
  narration_text 5,429 chars, p90 8,389 chars, max 9,882 chars, across
  scripts with avg 60 / p90 72 / max 85 shots. One confirmed live run:
  8,235 chars / 60 sentences took 1h4m11s (old single-script code path).
  Scale worst case (~9,882 chars) to roughly 75-80 min for one script.

## STANDING RULE — READ THIS SECOND
**Do not trust this document at face value.** Before acting on ANY claim below, re-verify it against live Supabase data (project `swnjzzejsuupecdgbzzf`) and/or the live GitHub repo (
