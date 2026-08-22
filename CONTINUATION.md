# Marius / Erased — Continuation Notes (2026-08-22, CHUNK-STITCH SESSION)

**Read this entire file before touching any code.**

Status markers: CONFIRMED = proven against real code/data this session.
HYPOTHESIS = reasoned, not proven by execution. Per
DEBUGGING_METHODOLOGY.md, do not upgrade a HYPOTHESIS to fact without
verifying it first.

---

## 2026-08-22 session — YouTube uploads silently stalled since 08-17, fix in progress, NOT YET VERIFIED WORKING

### What's CONFIRMED this session

- Ali reported no YouTube uploads since the corrupted/144p 19-minute
  video was fixed. Traced via direct Supabase query: two real finished
  videos have been stuck at `status = video_generated` with ZERO upload
  attempts — `ba5d96c8` (10 chunks, `video_generated` since 08-17
  09:37 UTC) and `37993b31` (7 chunks, since 08-18 20:16 UTC). Both have
  `video_url: null`, only `video_chunk_urls` populated.
- Root cause, confirmed by reading the live `scripts/youtube_upload.py`:
  it only ever checks `script.get("video_url")`. It has no branch for
  `video_chunk_urls` at all — so every script that got chunked by the
  2026-08-20 CHUNKED-UPLOAD QUALITY FIX in `video_generation.py` (which
  splits output into `part_NNN.mp4` files instead of crushing bitrate,
  whenever a full-quality encode exceeds Supabase's 50MB single-file
  cap) has been silently skipped by every `youtube_upload.yml` run
  since, with no error logged anywhere — just "Script has no video_url
  yet. Skipping." forever.
- Separately, `scripts/video_generation.py` got a real fix this session
  too (commit `2cf8958`, pushed 08:05 UTC): `process_script()`'s
  assembly step and `main()`'s per-script loop were both unprotected —
  any exception crashed the entire run before other candidates got a
  turn. Now wrapped in try/except, real tracebacks recorded to the new
  `scripts.last_error`/`last_error_at` columns via `record_error()`.
  Confirmed via query: `last_error` is empty across all scripts (no
  crash has occurred to test it against yet, but the wrapping itself is
  confirmed live in the fetched file).

### Fix written this session — PROCESS FAILURE, logged for accountability

Wrote `stitch_chunks_to_local_file()` in `youtube_upload.py` (downloads
every chunk, concatenates via moviepy, uploads the result same as
before) and pushed it successfully via `create_or_update_file` — this
part worked. **But I did not check `youtube_upload.yml`'s dependency
install step before adding the moviepy import**, which is a direct
violation of DEBUGGING_METHODOLOGY.md step 2/3 (read the actual live
code/config the fix runs under, not just the target script). Ali ran the
workflow and it crashed immediately: `ModuleNotFoundError: No module
named 'moviepy'`. That workflow installs deps via a hardcoded
`pip install requests` line — it does NOT use `requirements.txt` (which
DOES list moviepy, confirmed) the way `video_generation.yml` and
`narration.yml` do. This should have been checked first and wasn't.

Also caught (after being called out, not before): moviepy's
`write_videofile()` needs the actual `ffmpeg` binary on the runner, not
just the pip package — `narration.yml` has a dedicated
`sudo apt-get install -y ffmpeg` step for this exact reason.
`youtube_upload.yml` has neither that step nor `requirements.txt`.

### CURRENT BLOCKER — needs Ali to paste manually

GitHub write access is confirmed working for regular files this session
(multiple successful pushes to `.py` and `.md` files), but **fails with
403 "Resource not accessible by integration" specifically on
`.github/workflows/*.yml` files** — this is very likely a missing
`workflow` OAuth scope on the connected token, distinct from repo
write access generally. This is a NEW finding, not previously
documented — worth remembering: workflow YAML edits need the manual
paste flow even when regular file pushes work fine.

**youtube_upload.yml fix, NOT yet applied — Ali needs to paste this
manually via the `.../edit/main/.github/workflows/youtube_upload.yml`
URL:** add an `Install ffmpeg` step (`sudo apt-get update && sudo
apt-get install -y ffmpeg`) before the existing install step, and
change `pip install requests` to `pip install requests moviepy`.

### NEXT STEP for next session (or later this one)

1. Confirm Ali has pasted the corrected `youtube_upload.yml`.
2. Manually trigger the `YouTube Upload` workflow (`workflow_dispatch`).
3. Watch the real run output — don't assume success from a green
   checkmark alone (per DEBUGGING_STANDARDS.md point 1). Confirm via
   direct Supabase query that `ba5d96c8` or `37993b31` actually flips to
   `status = uploaded` with a real `youtube_video_id` set.
4. Only after that live confirmation, treat the chunk-stitch fix as
   proven — not before.

---

*Prior session history (2026-08-20 and earlier — freeze-frames, named-
character-in-every-shot, gender-drift-on-continuity-removal, bitrate/
quality trade-off options, music/SFX, narration tone) trimmed from this
file to keep it usable — see `git log -- CONTINUATION.md` for full
detail. That work is a SEPARATE, STILL OPEN thread from this session's
chunk-stitch issue — do not assume either session's fixes touched the
other's problems.*
