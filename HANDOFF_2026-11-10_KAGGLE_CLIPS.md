# HANDOFF 2026-11-10: Kaggle AI clips for Marius (replaces Agnes AND stock footage)

Zia's decision: Marius videos must be AI-generated on Kaggle's free GPU, not stock footage. NOT YET RUN. Re-verify everything live.

## What was built (pushed to main this session)
- `scripts/kaggle_clips.py`: GitHub-side runner, one action per run: wait / collect finished clips (ffmpeg scale+crop to 1280x704, upload to B2, save `video_urls` + `video_next_index`) / push next batch (30 shots) of the most-advanced `images_generated` script. When all shots are saved it calls `video_generation.process_script(script, shot_limit=0)` so the existing assembly runs; no Agnes or stock call is ever made.
- `scripts/kaggle_clips_kernel.py`: runs on Kaggle, LTX-Video 2B 0.9.8 distilled, 704x480, 24 fps. Piece 1 text-to-video, longer shots continue picture-to-video from the last frame (beats from beat_director). Silent clips, 420 min time budget, stops at the first shot that fails twice. Loader copied from `scripts/kaggle_video_test/kernel.py`.
- Workflow `.github/workflows/kaggle_video.yml` must be pasted by Zia (403 for the connector). It shares the concurrency group `video-generation` with the old workflow. The old `Video Generation` workflow must be DISABLED so stock footage / Agnes are never used.

## Not verified
- Whether `kaggle_test.yml` ever produced good clips (Actions logs not readable by the connector). LTX 2B quality on documentary shots is unjudged.
- Speed per clip on Kaggle's GPU and the weekly free GPU quota (about 30 h, unverified). A 30-shot video is roughly 100 to 150 pieces of 4 s.
- Continuity between shots is NOT used (each shot is text-to-video); only pieces within one shot are chained.
- `PIXABAY_API_KEY` secret may still exist; harmless once the old workflow is disabled.

## Secrets (names only)
KAGGLE_USERNAME (falls back to Diawazi), KAGGLE_API_TOKEN or KAGGLE_KEY, SUPABASE_URL, SUPABASE_SECRET_KEY, B2_ENDPOINT_URL, B2_KEY_ID, B2_APPLICATION_KEY, GEMINI_API_KEY, AGNES_API_KEY (only so imports work), FREESOUND_API_KEY, ACE_MUSIC_API_KEY, HF_TOKEN. The Kaggle token was pasted in chat on 2026-10-25: regenerate it on Kaggle and replace the secret.

## Next
1. Zia pastes the workflow and disables the old one. 2. Run it once by hand, read the run summary. 3. First finished Kaggle batch: look at the clips before letting the cron run unattended.
