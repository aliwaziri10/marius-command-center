# Marius / Erased — Continuation Notes (2026-09-19, THROUGHPUT + AGNES-REPLACEMENT SESSION)

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

### NEXT STEP for next session (or later this one)

1. Let a few scheduled `Video Generation` runs fire now that both B2 and
   Agnes-poll fixes are live; confirm via Supabase that `video_urls` is
   actually advancing on the oldest `images_generated` script.
2. Only if throughput is still clearly bottlenecked after that (not just
   "slower than we'd like"), revisit `CLIP_BATCH_LIMIT` as a real,
   never-before-tried lever.
3. Agnes-replacement is parked as a real option, not abandoned — if
   Ali wants to pursue it, the ZeroGPU/self-hosted-runner paths above are
   the realistic next step, not a mythical CPU-only equivalent.

---

*Prior session history (2026-08-22 chunk-stitch/YouTube-upload session
and earlier) trimmed from this file to keep it usable — see
`git log -- CONTINUATION.md` for full detail. That work is a SEPARATE
thread from this session's throughput/Agnes-replacement work.*
