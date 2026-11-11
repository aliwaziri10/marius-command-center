# HANDOFF 2026-11-10 (end of session): Kaggle AI clips for Marius

Zia's decision: Marius clips are AI-generated on Kaggle's free GPU. NO stock footage, NO Agnes. Re-verify everything live before trusting this file.

## Files (all on main, compile-checked)
- `scripts/kaggle_clips.py` (runner, rev 2, commit 6ccaf6c). One action per run: wait if Kaggle running/queued, collect finished clips (ffmpeg scale+crop to 1280x704, upload to B2, save `video_urls` + `video_next_index`), or push the next 30 shots of the most-advanced `images_generated` script to the Kaggle notebook `<KAGGLE_USERNAME>/marius-clips`. When all shots are saved it calls `video_generation.process_script(script, shot_limit=0)` (existing assembly).
- `scripts/kaggle_clips_kernel.py` (runs on Kaggle, rev 2, commit 64159e5). LTX-Video 2B 0.9.8 distilled, 704x480, 24 fps, 256 prompt tokens. Piece 1 text-to-video, longer shots chained picture-to-video from the last frame using beat_director beats. Silent clips. Stops at first shot that fails twice or after 420 min.
- `.github/workflows/kaggle_clips.yml` (Zia pasted it; live, cron every 30 min, concurrency group `video-generation`, run name "Kaggle Video Generation").
- Old `Video Generation` workflow (`video_generation.yml`) must be DISABLED by Zia (Actions page, ⋯, Disable workflow). NOT confirmed done. Until it is disabled, Agnes/stock footage can still run.

## History this session
- Run #1 failed in 32 s: Kaggle answers "Cannot access kernel ... Permission 'kernels.get' was denied" for a notebook that does not exist yet; old code read it as a login error. Fixed (reads it as "none", pushes first batch).
- Found before any clip was made: `prompt_builder.build_agnes_prompt` is 2,500+ chars with the shot description AFTER the guard text; LTX reads ~256 tokens, so it would have dropped the description. Runner now uses its own `ltx_prompt()` (description first, anchor capped at 300 chars, lighting, short style cue).
- If status is unreadable after a push, run writes `KAGGLE_STATUS_UNREADABLE` to `scripts.last_error` and waits 6 h (no push loop).

## NOT verified (check first, live)
1. Run #2 of "Kaggle Video Generation" (Zia was told to start it by hand): did it push a batch? Read the run summary.
2. Whether Kaggle account is phone-verified (needed for GPU + internet), whether the token can push/read notebooks.
3. Whether `kaggle_test.yml` ever produced good clips; LTX 2B quality on documentary shots is unjudged; time per piece and Kaggle's ~30 h/week GPU quota unmeasured. A 30-shot video is roughly 100-150 pieces of 4 s.
4. bf16 on Kaggle's GPU (P100/T4) is untested by us.
5. Assembly of Kaggle clips (`process_script` with shot_limit=0) never ran on this path yet.
6. Continuity between shots is NOT used (each shot is text-to-video).

## Secrets (names only, Claude cannot read them)
KAGGLE_USERNAME (required, no fallback), KAGGLE_API_TOKEN or KAGGLE_KEY, SUPABASE_URL, SUPABASE_SECRET_KEY, B2_ENDPOINT_URL, B2_KEY_ID, B2_APPLICATION_KEY, GEMINI_API_KEY, AGNES_API_KEY (imports only), FREESOUND_API_KEY, ACE_MUSIC_API_KEY, HF_TOKEN. The Kaggle token was pasted in chat on 2026-10-25: ask Zia to regenerate it and replace the secret.

## Next steps, in order
1. Read the latest run of `https://github.com/aliwaziri10/marius-command-center/actions/workflows/kaggle_clips.yml`; fix only what the log shows.
2. Confirm `video_generation.yml` is disabled.
3. When the first batch comes back, check the clips with Zia before the cron runs unattended; if LTX 2B is too weak, swap the kernel model (Wan 2.2 was Zia's original ask), keeping the runner unchanged.
4. Rules: Zia is non-technical, full files + edit URLs, every path/URL/secret name in its own code block, workflow files must be pasted by him (403 for the connector), one project per session (Marius only), re-check live state before every claim.
