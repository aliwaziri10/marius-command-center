# Marius / Erased — Continuation Notes (2026-09-19 PART 2, LIVE HANDOFF — read this section FIRST)

**Claude picking this up: this section is a live handoff from a session
that ended at ~90% context. Everything below "CURRENT STATE" is exactly
where things stood. Do NOT re-diagnose from scratch — verify these
specific facts first, then act.**

## CURRENT STATE (as of handoff)

- `storage_b2.py`'s stale-connection fix (commit `4a989ea`, forces a
  brand-new boto3 client on every upload retry attempt instead of
  reusing a dead pooled connection) is **CONFIRMED live on `main`** —
  verified by reading the file directly off `refs/heads/main` this
  session, not just trusting the commit log.
- A **Video Generation** run was in progress, observed live via a
  workflow-run log screenshot Ali pasted, running **53+ minutes** (job
  `timeout-minutes: 60`, so it was about to be force-killed by GitHub
  any minute at handoff time).
- That pasted log was from an OLDER run (no "with a fresh connection"
  text in its retry messages = pre-`4a989ea` code) showing the B2
  SSLEOFError hitting shot `40698016-.../shot_000.mp4` AND all three of
  its chain-extension reference frames (`chain_shot_000_chain1/2/3.mp4`)
  — every single attempt, 4/4, across multiple distinct object keys in
  one run. Then it moved on to script `e4b92178-...` and started
  generating ITS shot 1, which also needs 3 chained sub-clips (16.3s
  shot vs ~7s per-generation cap) before it can even attempt its first
  real upload.
- Last query before handoff (Supabase, `iwgocbiqjjhlvkygmcir`, table
  `scripts`): **zero progress saved anywhere** — `video_next_index = 0`
  and `clips_done = 0` for all three oldest `images_generated` scripts
  (`e086c4f2`, `40698016`, `e4b92178`). No `last_error_at` newer than
  `2026-09-18 21:11:26+00`.
- Ruled OUT this session, don't re-check these:
  - **GitHub Actions minutes quota** — confirmed via Ali's own billing
    screenshot: `0 min used / 2,000 min included`. The $18.96/$15.88/
    $3.96 "usage by repository" figures on the billing page are gross
    costs fully offset by the public-repo discount (net $0 billable) —
    NOT evidence of a quota block. Do not re-raise this theory.
  - `CLIP_BATCH_LIMIT` has never been changed in any commit ever (full
    86-commit history checked) — see PART 1 below for detail. Not
    touched this session, deliberately.
  - Agnes poll-timeout crash — already fixed 2026-09-18, confirmed live
    in `agnes_client.py`, not the cause of anything this session.

## WHY this matters — the live open question at handoff

Nearly 24 hours of **zero Supabase activity** from ANY Marius workflow
(not just Video Generation) between `2026-09-18 21:11` and whenever the
53-minute run above actually started, is not yet explained. Two
live hypotheses, NEITHER confirmed:
1. Each `Video Generation` run is genuinely just slow because of chain-
   extension (multiple full Agnes generate+poll cycles per shot before
   the first `save_progress` call) — not stuck, just legitimately taking
   close to the full 60 minutes per attempt, and `concurrency: group:
   video-generation, cancel-in-progress: false` means only one run goes
   at a time, so a near-60-min run naturally creates long gaps between
   any visible DB activity.
2. Something is actually hanging (network call with no bound, a stuck
   moviepy/ffmpeg step, etc.) — not yet identified. If so, the run gets
   killed at the 60-min job timeout, `if: failure()` may not fire on a
   *timeout-kill* the same way it does on a real exception (worth
   checking — this was NOT verified this session), which would explain
   why no new "workflow failed" issue has appeared since #1001 despite
   apparent problems.

## EXACT NEXT STEPS for whoever picks this up

1. Query Supabase (`project_id: iwgocbiqjjhlvkygmcir`) for the same
   three scripts above (`e086c4f2`, `40698016`, `e4b92178`) — check
   `video_next_index`, `video_urls` array length, `last_error_at`. If
   any of them now show `video_next_index >= 1`, the fix is working and
   it really was just slow (hypothesis 1) — tell Ali the good news
   plainly, don't over-explain.
2. If still zero progress everywhere, check whether a NEWER run has
   started since the 53-minute one got killed (Ali can screenshot the
   Actions run list — `https://github.com/aliwaziri10/marius-command-
   center/actions/workflows/video_generation.yml` — showing timestamps
   and status). If a new run started and is ALSO stuck near 60 minutes
   on the same script/shot, that's real evidence for hypothesis 2 — pull
   that run's live log (ask Ali to paste it) to see exactly where it's
   spending the time (Agnes poll? ffmpeg? a bare `requests` call with no
   timeout at all?).
3. Do not re-do the CLIP_BATCH_LIMIT/quota/Agnes-poll investigations —
   see "Ruled OUT" above.
4. If genuinely stuck (hypothesis 2 confirmed), the fix is almost
   certainly adding a bound to whatever step is hanging — the pattern
   already used everywhere else in this codebase (explicit retry loop
   with a max attempt count + `time.sleep`, e.g. exactly what
   `storage_b2.upload_bytes` and `agnes_client.poll_agnes_task` already
   do) — find the one remaining unbounded call and apply the same
   pattern, per `DEBUGGING_METHODOLOGY.md`.

---

# Marius / Erased — Continuation Notes (2026-09-19 PART 1, THROUGHPUT + AGNES-REPLACEMENT SESSION)

**Read this entire file before touching any code.**

Status markers: CONFIRMED = proven against real code/data this session.
HYPOTHESIS = reasoned, not proven by execution. Per
DEBUGGING_METHODOLOGY.md, do not upgrade a HYPOTHESIS to fact without
verifying it first.

---

## 2026-09-19 session — B2/Agnes fixes landed, throughput math checked, Agnes-replacement researched

### What's CONFIRMED this session

- **Root cause of "no video in over a month" was two real bugs, not the
  CLIP_BATCH_LIMIT/CANDIDATE_POOL_SIZE pacing.** Both now fixed and live:
  1. `storage_b2.py`: `upload_bytes`'s retry loop (added 2026-09-18) was
     reusing the same cached boto3 client/connection on every retry, so a
     dead pooled TLS connection reproduced the identical
     `SSLEOFError`/`SSLError` 4/4 times instead of getting a fresh
     connection. Fixed (commit `4a989ea`, 2026-09-18): every retry
     attempt after the first now builds a brand-new client
     (`_new_client()`), forcing a fresh TCP+TLS connection.
  2. `agnes_client.py`'s poll-timeout crash (Agnes `ReadTimeoutError`
     killing the whole script run) was **already fixed same-day
     2026-09-18**, before this session started — confirmed by reading
     the live file, no further action needed there.
- **Checked whether raising `CLIP_BATCH_LIMIT` (currently 8) had ever
  been tried before, per Ali's request.** Went through the full commit
  history of `scripts/video_generation.py` (86 commits, back to file
  creation 2026-07-08). `CLIP_BATCH_LIMIT` itself has **never** been
  changed in any commit. The only related constant ever touched was
  `CANDIDATE_POOL_SIZE` (5 → 15, 2026-07-25) — a different setting (how
  many stuck scripts get considered per run, not how many shots get
  generated). So raising `CLIP_BATCH_LIMIT` is a genuinely untried idea,
  not a dead end.
- **Re-checked the throughput math with the two bugs actually fixed**:
  the 8-shot budget is spent sequentially by the oldest queued script,
  not split evenly across 15 candidates — one script can burn a full
  ~25-shot episode in about 4 runs (~2.7 hours) once it's succeeding.
  The "one shot of progress per script per run" symptom Ali/Claude
  observed before this session was almost certainly the two bugs above
  (failing candidates burning a run's attention with `shots_used = 0`
  and no real budget spent), not an inherent pacing ceiling. **No
  `CLIP_BATCH_LIMIT` change made this session** — recommend watching a
  few scheduled runs first to confirm `video_urls` is actually advancing
  on the oldest queued script before touching this constant at all.

### Agnes-replacement research (requested by Ali — "generate video on a
laptop/CPU instead of paying for Agnes")

Researched this in depth. Honest finding: **there is no real CPU-only or
laptop-only equivalent to what Agnes actually does for Marius** (prompt
→ realistic AI-generated scene video). The rumor Ali saw is very likely
about a different category of pipeline — CPU-only "faceless shorts"
generators (e.g. `NanoBotAgent/video-generator-ytshorts`, built to run
on free GitHub Actions CPU runners) that produce a TTS voiceover over a
static/animated **gradient background** rendered with plain FFmpeg, not
a real generated scene. That's a fundamentally different, much simpler
visual style than Marius's documentary-style AI shots and would be a
content/format change, not a drop-in Agnes replacement.

Real open-source text-to-video models that could genuinely replace
Agnes on quality (Wan2.2, HunyuanVideo, LTX-2) all still need a real GPU
with meaningful VRAM (8GB+ even with GGUF quantization) — none run
usably on CPU; a CPU render of even a few seconds of real video-diffusion
output takes on the order of hours, not viable for a daily pipeline.
GitHub-hosted Actions runners are CPU-only for all non-Enterprise plans
(confirmed no GPU option). The closest realistic paths to a genuinely
cheaper/free Agnes alternative, if this is worth pursuing later:
- A GPU-backed self-hosted runner (rent a cheap cloud GPU, e.g. a single
  T4, and point a GitHub Actions job at it) — real infra cost, not free.
- Offloading generation to a free-tier GPU-backed Hugging Face Space
  (ZeroGPU) running an open model like Wan2.2 — free but rate-limited
  and would need real integration work to swap in for the Agnes API
  calls in `agnes_client.py`.
- Staying on Agnes and treating today's two fixes as the actual
  unblock — likely the highest-leverage move right now given no CPU/free
  option matches Agnes's output quality or throughput.

**No code changed for this thread this session** — flagging the
research honestly rather than pushing a fake "laptop GPU-free" fix, since
what's actually available wouldn't produce Marius's current visual style
or throughput.

---

*Prior session history (2026-08-22 chunk-stitch/YouTube-upload session
and earlier) trimmed from this file to keep it usable — see
`git log -- CONTINUATION.md` for full detail. That work is a SEPARATE
thread from this session's throughput/Agnes-replacement work.*
