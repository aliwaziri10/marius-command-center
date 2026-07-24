# Marius Command Center — Handoff Sheet
Written: 2026-07-20, updated 2026-07-25, by Claude, verified live against Supabase and GitHub at time of writing.

## ⚠️ STANDING RULE — READ THIS FIRST
**Do not trust this document at face value.** Before acting on ANY claim below, re-verify it against live Supabase data (project `swnjzzejsuupecdgbzzf`) and/or the live GitHub repo (`aliwaziri10/marius-command-center`). Prior handoffs have gone stale within days — trust the database and the actual repo files, never a previous session's notes, including this one.

## User workflow preferences (apply every time, no exceptions)
- Every path/URL goes in its own fenced code block (copy button).
- Every script/code change: give the path first, then the FULL file content in a separate fenced code block in chat. Zia selects-all, deletes, pastes, commits. Never diffs, never "find this line."
- Zia is a non-coder, works via browser only (GitHub web editor, Supabase dashboard, Render/Google Cloud Console), no terminal.
- One step at a time for multi-step instructions.
- Terse, action-only replies — no preamble/rationale unless safety-critical.
- After meaningful changes, update this doc with exact live-verified values.
- GitHub `create_or_update_file` returns 403 every session — Claude's write access is read-only in practice. All code changes go through Zia pasting into the GitHub web UI.
- Branch protection on `main`: no direct commits — but Zia has been committing directly via the web editor successfully this session, so protection may not be active or applies only to the API path. Re-verify if a future commit is rejected.

## Reusable references
- Supabase project ID: `swnjzzejsuupecdgbzzf`
- GitHub repo: `https://github.com/aliwaziri10/marius-command-center`
- GitHub Actions: `https://github.com/aliwaziri10/marius-command-center/actions`
- Storage buckets: `narration`, `video_clips`, `videos`, `thumbnails` (`images` bucket now unused — see pipeline change below)
- Secret naming for Marius (distinct from Nova's `YT_*` convention): `YOUTUBE_CLIENT_ID`, `YOUTUBE_CLIENT_SECRET`, `YOUTUBE_REFRESH_TOKEN`
- `CLIP_BATCH_LIMIT = 8` in `video_generation.py` — max 8 new clips per scheduled run (Agnes free-tier quota), resumes automatically next run. A 45-shot script takes ~6 runs to fully clip.
- `AgnesOverloadedError` in `video_generation.py` exits quietly (exit 0, no GitHub issue) on transient Agnes overload — by design, so normal overload doesn't spam issues. Means a stalled script won't always show up as a failed run; check `video_next_index` in Supabase directly to confirm real progress vs. silent stall.

## Narration engine change — 2026-07-25 (Kokoro → Edge TTS) — ⚠️ NOT YET CONFIRMED LIVE
**Status as of writing: full-file replacements have been GIVEN to Zia for manual paste+commit. Re-check the actual repo files and a fresh workflow run before assuming any of this is live.**

### Why
Kokoro narration (voice `am_adam`) was flagged as sounding less natural/expressive than desired. Separately (and unrelated to voice quality), an older bug where narration was synthesized per-shot instead of per-sentence — causing audio to pause mid-sentence at every scene cut — was already fixed in a prior session (see `synthesize_per_sentence_with_shot_durations` in `narration.py`, which synthesizes one full sentence per TTS call and proportionally distributes that sentence's real duration across the shots inside it). That per-sentence fix is preserved as-is in the Edge TTS version below — it was never a Kokoro-specific fix.

### What changed
Three files, all given to Zia as full-file replacements on 2026-07-25:
1. **`scripts/narration.py`** — Kokoro (`kokoro_onnx`, local ONNX model, voice `am_adam`) replaced with Edge TTS (`edge-tts` package, voice `en-US-GuyNeural`, male, rate `-5%`). Same per-sentence-call + proportional-shot-duration architecture kept unchanged; only the actual TTS call and audio-handling library changed (numpy/soundfile → pydub, since edge-tts outputs mp3 and pydub handles concatenation/silence-padding/export-to-wav/loudness-normalization more directly for that format).
2. **`requirements.txt`** — removed `kokoro-onnx`, added `edge-tts` and `pydub`. Kept `soundfile`/`numpy` in case other scripts in the repo still import them (not exhaustively checked).
3. **`.github/workflows/narration.yml`** — added a `sudo apt-get install -y ffmpeg` step before `pip install -r requirements.txt`, since pydub needs ffmpeg on the runner (mirrors what `.github/workflows/test-narration-edge.yml` already did for the test version).

### Voice choice rationale
Chose male (`en-US-GuyNeural`) over female based on quick research: general explainer-video studies favor female voices for trust/friendliness, but niche guidance for documentary/history-storytelling content specifically favors an authoritative male voice for trust and watch-time in narration-heavy content. Not a rigorous A/B test — if retention data later suggests otherwise, revisit.

### Testing history that led here (all via `scripts/test_narration_edgetts.py`, `.github/workflows/test-narration-edge.yml` — test-only, never touched the live engine)
- v1 (450ms fixed pause between sentences): narration finished 4-5s ahead of (shorter than) the video.
- v2 (650ms fixed pause): closed the total gap, but a fixed pause can't fix drift that isn't uniform — one specific sentence ("Elsa the seamstress") was found 9s out of sync mid-script, because Edge TTS doesn't take the same time per sentence Kokoro did when the video's shots were originally cut.
- v3 (current test approach, not yet ported to live narration.py's fallback path): per-sentence silence padding, where each sentence's audio is padded with silence up to the sum of the shot durations assigned to it (video's `shot_durations` split into N equal-ish chunks for N sentences). This locks sync at every sentence boundary. **Note:** this v3 padding-to-existing-video-durations approach only matters when muxing new audio onto an *already-rendered* video (which is what the test script does, reusing a published video). It is NOT the same problem as the live pipeline, where narration.py generates shot_durations first and video_generation.py cuts new clips to match — so the live `narration.py` given above does not need the v3 padding logic, only the per-sentence-call fix it already had.

### Before trusting this is live, verify:
1. Open `https://github.com/aliwaziri10/marius-command-center/blob/main/scripts/narration.py` and confirm it imports `edge_tts` and `pydub`, not `kokoro_onnx`.
2. Open `requirements.txt` and confirm `edge-tts`/`pydub` are listed, `kokoro-onnx` is not.
3. Open `.github/workflows/narration.yml` and confirm the ffmpeg install step is present.
4. Run the Narration workflow manually once (`workflow_dispatch`) and check the run log for errors, then check Supabase `scripts` table for a new row with a fresh `narration_url` and confirm it's a normal-length `.wav`.
5. Listen to the actual output before assuming voice quality/pacing is resolved — it was not verified live before this doc entry was written.

## Pipeline structure change — 2026-07-20 (dead code removed)
`image_generation.py` and its workflow (`image_generation.yml`) generated a still image per shot via Pollinations and wrote `image_urls` + status `images_generated` — but `video_generation.py` never read `image_urls`; it always generated video clips directly from `shot_list` text via Agnes. This was confirmed dead code (the repo's own `PLAYBOOK.md` already called `image_urls` "legacy/unused for new scripts").

**Removed:**
- `scripts/image_generation.py` — deleted.
- `.github/workflows/image_generation.yml` — content replaced with a retirement comment (left in place, disabled).

**Changed:**
- `scripts/narration.py` — final status changed from `"narrated"` to `"images_generated"` directly, so `video_generation.py` (which queries on that exact status string) picks it up with no gap. Log message updated to match.

**New pipeline flow:** `topic_research` → `script_writing` → `narration` (now sets `images_generated` directly) → `video_generation` → `thumbnail_generation` / `youtube_upload`.

The `images_generated` status name is now historical/misleading (no images involved) but left as-is since every downstream script (`video_generation.py`, `youtube_upload.py`, dashboards) keys off that exact string — renaming it would require touching every query, not worth the risk for a cosmetic fix.

## Fixes made 2026-07-20 (all confirmed live)

### 1. YouTube OAuth `invalid_grant` — FIXED
Root cause: refresh token had expired (Google OAuth consent screen constraint). Fixed by:
- Generating a new Client Secret in Google Cloud Console (old one couldn't be retrieved — Google no longer allows viewing existing secrets).
- Regenerating the refresh token via OAuth Playground with the new credentials.
- Updated GitHub secrets: `YOUTUBE_CLIENT_ID`, `YOUTUBE_CLIENT_SECRET`, `YOUTUBE_REFRESH_TOKEN`.
- Confirmed fixed: manual `youtube_upload.yml` run completed cleanly (no `invalid_grant`), correctly reported "No videos ready" since nothing was at `video_generated` status yet at the time.
- Publishing status checked: consent screen is in **Production** (not Testing), so this should not require re-doing every 7 days going forward.

### 2. Oversized burned-in captions — FIXED
Captions were rendering at font size 42 across 86% of frame width, wrapping into a block covering nearly half the screen on longer narration excerpts. In `scripts/video_generation.py`:
- `CAPTION_FONT_SIZE`: 42 → 28
- `CAPTION_MAX_WIDTH_RATIO`: 0.86 → 0.70
This is a constant change, applies to all future videos, not a one-off patch.

### 3. Original clip audio being discarded — FIXED
`assemble_final_video` was concatenating shot clips (which already carried usable ambience/music baked in by Agnes) via `concatenate_videoclips`, then calling `.with_audio(final_audio)` — which **replaces** a clip's audio track rather than layering onto it. The original per-clip audio was being silently thrown away every time, regardless of whether the generated music/SFX mix succeeded.
- Added `extract_original_clip_audio()` — pulls each shot's original audio track, volume-matched via new constant `ORIGINAL_CLIP_AUDIO_VOLUME = 0.30`.
- `build_audio_mix()` now takes this as an optional 4th layer alongside narration/music/SFX.
- Audio mix is now: narration + original clip ambience + background score + SFX, all through the existing safety limiter (`LIMITER_CEILING = 0.98`) so this can't cause clipping.

## Verified live pipeline state (queried directly, 2026-07-20 — RE-VERIFY before trusting)

| Status | Count |
|---|---|
| `archived` | 1 |
| `images_generated` | 9 |
| `uploaded` | 10 |

Topics in queue: 93.

### Scripts at `images_generated` (waiting on Video Generation), oldest first:
| Script ID | Clips done | Created |
|---|---|---|
| `e6de21d1-36f1-4723-880f-c8900b3522b4` | 32/45 | 2026-07-15 |
| `f86cea49-f741-40b2-8712-ea8aaed13442` | 0 | 2026-07-16 |
|
