# HANDOFF 2026-10-25: Kaggle video fallback for Tiny Lawn Tales (repo adrian001234/upgraded-journey)

Stored here because Claude's GitHub connector got 403 "Resource not accessible by integration" writing to `adrian001234/upgraded-journey` on 2026-10-25. Move this file there when write works. NOT BUILT YET. Re-verify everything live.

## Decision (Zia, 2026-10-25)
Use free Kaggle GPU video generation (as Marius already does) for Tiny Lawn Tales (3D snail Mimsi), because Agnes has answered `video_queue_full` since about 2026-10-10. Zia says Kaggle is set up and Marius has already run 3 to 4 Kaggle workflows that produced videos (Zia's claim; clip quality not checked by Claude).

## Verified live on 2026-10-25
- `adrian001234/upgraded-journey`: last commit is 2026-10-11 ("Update HANDOFF.md"). Nothing newer. No Kaggle files exist there.
- The connected Supabase project is only `marius` (`iwgocbiqjjhlvkygmcir`). Its `tpd_scripts` table is EMPTY. Tiny Lawn Tales data is not visible from the connected tools, so whether Tiny Lawn Tales produced a video is NOT confirmed. Check `https://github.com/adrian001234/upgraded-journey/actions` and the repo HANDOFF.md.
- Marius reference (read live): `.github/workflows/kaggle_test.yml`, `scripts/kaggle_video_test/run_test.py` (push kernel, poll status every 60 s, download output), `scripts/kaggle_video_test/kernel.py` (LTX-Video 2B 0.9.8 distilled, diffusers, 704x480, 97 frames at 24 fps, 8 steps, includes image-to-video test).
- The 2026-10-18 Marius video run log: Agnes queue full, both scripts went STOCK-ONLY, ACE Music and HF MusicGen failed on DNS, 4 of 28 sound-effect cues matched, outro fell back to a freeze frame. Report said "No faults this run".

## Plan
1. Kaggle notebook renders Mimsi shots with LTX image-to-video from the reference picture; the GitHub run downloads clips and uploads them to storage, so no storage keys go on Kaggle.
2. Reuse Marius's runner pattern; keep Agnes as the primary path in `video/generate_video.py`, Kaggle as fallback.
3. Open: LTX quality on a 3D snail, Mimsi consistency, free GPU quota (about 30 h a week, unverified), time per clip.

## Secrets
Zia says he saved the Kaggle API token as a secret in `adrian001234/upgraded-journey` (belief: `KAGGLE_API_TOKEN`; Claude cannot read secrets; NOT verified). The token was pasted in chat on 2026-10-25: regenerate it on Kaggle and replace the secret after the first successful render. Marius's workflow falls back to username `Diawazi` for `KAGGLE_USERNAME`.

## Next steps (one at a time)
1. Check the secret names at `https://github.com/adrian001234/upgraded-journey/settings/secrets/actions`.
2. Fix write access to `adrian001234/upgraded-journey` (collaborator access for `aliwaziri10`, or Zia pastes files).
3. Write the Kaggle runner and kernel for Tiny Lawn Tales, push, verify live, run one 4-shot test, judge the clips.
