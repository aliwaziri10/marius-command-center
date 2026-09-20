# Marius / Erased — Continuation Notes (2026-09-21 PART 5, AGNES CREATE-TIMEOUT FIX + PART 4 CORRECTION, read this section FIRST)

**Re-verify against live GitHub/Supabase before acting. Do not trust this doc at face value.**

## Standing role (from Zia, 2026-09-21)
On Marius the job is to keep the pipeline working and producing videos. Act autonomously end-to-end (diagnose, fix, push, verify, then report). Do not wait for permission on routine fixes. Pause only for a genuine blocker (workflow-file 403 that Zia must commit, or anything that spends money).

## Correction to PART 4 (important — do NOT delete these files)
PART 4 says `scripts/b2_preflight.py` and `scripts/verify_run_output.py` have no workflow. That is WRONG. Verified by grep of `.github/workflows/` on `main`: `video_generation.yml` runs `python scripts/b2_preflight.py` and `python scripts/verify_run_output.py --stage video_generation`; `script_writing.yml` runs `python scripts/verify_run_output.py --stage script_writing`. Deleting either breaks Video Generation. Both are live.

## What was found and fixed (2026-09-21)
- Supabase `iwgocbiqjjhlvkygmcir`: 12 oldest scripts all `images_generated`. `e086c4f2` is at 16/30 clips; the rest are at 0-2 of 30-34. Every `last_error` is timestamped 2026-09-19 19:16-22:13 UTC; none newer.
- Two independent crash causes were found in those tracebacks:
  1. Poll endpoint HTTP 429 raised out of `poll_agnes_task` (scripts `e086c4f2`, `4d32a7b4`). Already fixed by another profile on 2026-09-20 (POLL-429 RETRY FIX in `agnes_client.py`).
  2. `create_agnes_task`'s `requests.post` had no exception handling, so a `ReadTimeout` (read timeout=60) killed the script's run (script `3c7d572f`, traceback frames `clip_generation._generate_one_segment` -> `agnes_client.create_agnes_task`). FIXED in commit `3506266`: the POST is retried like 429/5xx (20s x attempt, 4 attempts), then `AgnesOverloadedError`, which callers already handle.
- Evidence for fix 2: (a) the traceback frames; (b) the live code had no try/except around the POST; (c) a mocked run reproduced the crash on the old code (one call, then `ReadTimeout`) and shows the new code returning after two timeouts and raising `AgnesOverloadedError` after four. Pushed file diffed identical to the tested copy.
- Known side effect: a POST that timed out on the read side may already have created a task on Agnes (possible duplicate clip credit). Not measured.

## Declutter done (2026-09-19, verified before deleting)
Deleted `scripts/health_agent.py` (`44a862f`), `scripts/image_generation.py` (`4b2818c`), `scripts/test_narration_edgetts.py` (`4b9cbbe`), `scripts/test_narration_freellm.py` (`d117475`). Each had zero references (Python imports, workflows, `requirements.txt`, docs other than lists). After deleting, all 23 remaining scripts compile and no import points at a removed file.

## NOT verified
- Whether runs after the 2026-09-20 poll fix are progressing. No Actions-log tool. Test: re-query `video_next_index`; if `e086c4f2` is above 16 or any script reaches `video_generated`, it is working.
- PART 3 chain beats still unverified in a real run (look for `[beat_director]` lines in the Video Generation log).
- Fixing the crashes does not fix pace: shots over ~7s still chain 2-3 Agnes generations each.

## EXACT NEXT STEPS
1. Re-query Supabase progress (above). If flat, get one fresh run log from Zia and read where it stops.
2. Optional, needs Zia's paste (workflow file): add an import-check step to `code_health_check.yml` (compile-only today).
3. Research, unbuilt: a free-LLM fallback chain for `llm_client.py`. Ranking found: Gemini 3.5 Flash-Lite, then Gemini 3.1 Flash-Lite, then Groq `openai/gpt-oss-120b` (daily token caps bind first: this is the invisible cap that stalled Marius in Aug), then Mistral Experiment (data-training opt-in), then NVIDIA NIM (free endpoints are for development/evaluation only). Cerebras is now a finite trial. Not built; needs keys as GitHub secrets.

---

# Marius / Erased — Continuation Notes (2026-09-19 PART 4, SKILLS + DECLUTTER, read this section FIRST)

**Claude picking this up: this section is newest. Re-verify against live GitHub/Supabase before acting — do not trust this doc at face value.**

## What happened this session
- Built 3 Atlas Frame custom skills (not repo files — Claude custom skills, uploaded per-profile in Claude.ai settings): `atlas-debug-protocol` (verify-live/reproduce-by-execution/two-angle debugging standard + known-bug catalog), `atlas-session-handoff` (this handoff format + cross-profile continuity), `atlas-code-delivery` (push policy, 403 fallback, Zia's exact paste-formatting rules). Handed to Zia as `.skill` files to upload to each profile individually (no org-wide sharing tier).
- Ran a declutter pass on `aliwaziri10/marius-command-center`. Findings:
  - `scripts/image_generation.py` — deleted 2026-09-19 (`4b2818c`). PLAYBOOK.md corrected 2026-09-21.
  - `scripts/b2_preflight.py` and `scripts/verify_run_output.py` — CORRECTED 2026-09-21: these ARE run by workflows (`video_generation.yml`, `script_writing.yml`). The original note here ("no matching workflow") was wrong. Do NOT delete them.
  - `scripts/narration.py` vs `scripts/narration_stage.py` — confusingly similar names but BOTH are live and different: `narration.py` is the actual TTS/audio-generation stage (run by `narration.yml`); `narration_stage.py` is a text-generation helper module (`generate_narration()`) imported by `script_writing.py`. Not clutter — just a naming collision worth flagging to Zia, not fixing (renaming risks breaking imports for no functional gain).
  - `code_health_check.yml` only runs `py_compile`, which would NOT have caught the 2026-09-19 scene-by-scene import break. A real fix (adding an import-check step) touches a workflow file → 403 → needs Zia's paste. NOT done this session — flagging as a real open item, not built.

## EXACT NEXT STEPS for whoever picks this up
1. Continue the chain-beats verification from PART 3 above (unchanged, still open) — this session did not touch that thread.
2. (Withdrawn 2026-09-21: `b2_preflight.py`/`verify_run_output.py` are live. Do not delete.)
3. (Done 2026-09-21: PLAYBOOK.md's stale `image_generation.py` reference corrected.)
4. Optional, needs Zia's paste (workflow file): add an import-check step to `code_health_check.yml` so a cross-file break like the 2026-09-19 incident gets caught automatically next time.

## Where the next profile should look
Every Atlas Frame profile: `CONTINUATION.md` top section on `main`, this pipeline's repo. Standing cross-pipeline rules are in each profile's own memory, not this file.

---

# Marius / Erased — Continuation Notes (2026-09-19 PART 3, CHAIN BEATS — read this section FIRST)

**Re-verify everything below against live GitHub/Supabase. Do not trust this doc at face value.**

## Verified live on `main` (2026-09-19)

- Scene-by-scene rewrite of `clip_generation.py` broke the `assembly_stage.py` import; reverted (`79ecfd2`). `scene_director.py` removed (`4f56b08`). Chain-variation patch (`daaa60c`) reverted (`15009a0`).
- NEW `scripts/beat_director.py` (`7105ba4`): one fail-soft Gemini call per shot that needs chaining. Returns N beats (`action`, `camera_movement`, `shot_type`) or `None` on ANY failure. Bounded: 2 attempts x 45s, own call (not `llm_client.call_llm` retry loops), key via `x-goog-api-key` header.
- `scripts/clip_generation.py` (`397da0d`): `generate_shot_clip` calls `author_chain_beats` once before the chain loop; each chain segment gets `apply_beat_to_shot(shot, beat)`. `None` = old repeated-prompt behavior. Signatures unchanged.
- `.github/workflows/video_generation.yml`: `GEMINI_API_KEY` added to the "Run video generation" env (committed by Zia, verified by re-fetch). Secret exists at repo level (listed in `PLAYBOOK.md`, used by `script_writing.py`).
- Connector write: 403 on `.github/workflows/*` (Zia must commit those); OK on `scripts/*` and docs.
- Live Supabase project is `iwgocbiqjjhlvkygmcir` (rows dated 2026-09-19). `PLAYBOOK.md`'s old `swnjzzejsuupecdgbzzf` is stale/inaccessible via the connector.
- `code_health_check.yml` only runs `py_compile` per file. It would NOT catch a broken cross-file import (the scene-by-scene incident).

## Tests run (sandbox, mocked Agnes/moviepy)

- Both live files pass `py_compile`.
- 20s shot, beats present: segments get `ORIG/static`, `B1/orbit`, `B2/tilt_up` (7/7/6s).
- 20s shot, `beat_director` returns `None`: all segments `ORIG/static` = pre-change behavior.
- `beat_director` validation: bad enum coerced, consecutive same camera changed, wrong count / modern-object word -> `None`, missing key -> `None`.

## NOT verified

- No live Video Generation run since these changes. Next run: look for `[beat_director] authored N chain beat(s)` vs `falling back` in the log; confirm chained shots visibly differ.
- Premise is a HYPOTHESIS: that identical repeated prompts are why long shots look like a looped moment. Not proven from real output.
- Beats are LLM-authored and not checked against `narration_excerpt`.
- Supabase 2026-09-19: `acf67e3b` and `41fd7031` at `video_next_index = 1`; other recent scripts at 0.

---

# Marius / Erased — Continuation Notes (2026-09-19 PART 2, LIVE HANDOFF)

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
53-minute run above actually started, is not yet explained. Two live
hypotheses, NEITHER confirmed:
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
