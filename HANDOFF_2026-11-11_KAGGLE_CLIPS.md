# HANDOFF 2026-11-11 (Marius only): Kaggle clips, where it stands

Re-verify live before trusting this file (Supabase `scripts`, Actions runs). Read this after `HANDOFF_2026-11-10_KAGGLE_CLIPS.md`.

## What works (proven)
- Kaggle test run produced good 4 s AI clips (Zia watched the video). LTX-Video 2B on Kaggle free GPU, about 135 s GPU per 4 s clip. Clips are SILENT (sound is added later by assembly).

## What fails (live data, 2026-11-11)
- Production run does NOT save clips. Script `17fc73b3`: 30 shots, `video_next_index` 0, 0 clips saved.
- `scripts.last_error` (03:15 UTC): "Kaggle batch gave no clips: ffmpeg could not scale shot 1".
- Failing step: `scale_clip()` in `scripts/kaggle_clips.py` (ffmpeg scale/crop to 1280x704, fps 24, libx264) on the clip downloaded from Kaggle. The ffmpeg error text was discarded, so the cause is UNKNOWN.
- Other scripts (`8e7186bd`, `93d0f57b`, `e7265c60`, `709bff70`) show old tracebacks from the deleted `video_generation.yml` path (2026-11-10). Not the Kaggle path.

## State of repo (verified by direct read)
- `.github/workflows/kaggle_clips.yml` live: cron every 30 min, uses `secrets.KAGGLE_USERNAME` with no fallback.
- `video_generation.yml` was deleted on 2026-11-10.
- Workflow files cannot be written by the GitHub connector (403): Zia must paste them.

## Fix in progress (this session)
1. Log ffmpeg's real error and an ffprobe of the downloaded clip into `scripts.last_error` (change to `scripts/kaggle_clips.py` only; generation untouched).
2. After the next run (cron or manual "Run workflow"), read `last_error` in Supabase: `select left(last_error,1500) from scripts where id::text like '17fc73b3%';`
3. Fix the real cause, then confirm `video_next_index` rises and clips appear in B2.

## Still open
- Script Writing workflow failures (#551 to #554) and 48 h stall alerts.
- Kaggle token was pasted in chat on 2026-10-25: Zia should regenerate it and replace the secret.
- Kaggle clips are silent: assembly (`video_generation.process_script`) adds SFX and music once all shots are saved. Not yet run on this path.
- Phone verification of the Kaggle account (needed for GPU and internet) not confirmed.

## Rules
Zia is a non-coder: full files, each URL/path in its own code block, max 3 to 4 steps, never mix Marius with Nova, work only through `aliwaziri10` repos.
