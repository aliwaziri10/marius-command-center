# Kaggle free-GPU video test: decision notes

Date: 2026-10-21 (written during the Agnes queue-full backup search). Updated 2026-10-25.

## Decision
- Backup video generation will use the open-source Wan 2.2 and LTX-Video models.
- Everything runs on Kaggle's free GPU. Zia has no GPU and nothing runs on his laptop.
- Free only. No paid, credit-based, daily-credit or trial tools, ever. Model files are public downloads (no account, no key, no payment).
- GitHub Actions starts the Kaggle notebook; no manual clicking per clip.

## Where things are
- Workflow: `.github/workflows/kaggle_test.yml` (manual run, "Kaggle Video Test")
- Runner script: `scripts/kaggle_video_test/run_test.py` (pushes the notebook, waits, downloads results into `kaggle_out/`; prints REPORT and CLIPS in the run log)
- Notebook that runs on Kaggle: `scripts/kaggle_video_test/kernel.py`
- Repo secrets: `KAGGLE_USERNAME`, `KAGGLE_API_TOKEN` (values are never stored in the repo)
- Kaggle account username: `ziawaziri`

## Results
- 2026-10-24 test 3 (LTX 2B 0.9.8 distilled, Kaggle T4): 5 text-to-video clips OK, 704x480, 4.04 s each, ~135 s GPU per clip, 182 s one-time load, 12 GB peak. Realistic scenes and faces clean; motion gentle.
- Picture-to-video chain crashed (generator on cpu, needs cuda). Fixed in test 4.
- Clips have NO audio track (model is video-only). Sound is added after: upgraded-journey `assembly/sound.py` (ffmpeg music + effects) verified 2026-10-25 on these clips, audio present.
- 2026-10-25 test 4 pushed (a0c3a32): Mimsi from her reference picture (3 clips + 1 chained), 1 sparrow clip with no picture, sound added to every clip. NOT RUN YET: press "Run workflow" on Kaggle Video Test, then read FINAL STATUS / REPORT / CLIPS in the step "Run Kaggle video test".

## Requirements and open points
- Kaggle account must be phone-verified for GPU and internet inside notebooks (unconfirmed as of 2026-10-25).
- Claude's GitHub connector cannot edit workflow files (403 "without workflows permission"); the run button must be pressed by Zia.
- Licence of the LTX 2B 0.9.8 weights not yet read. Not yet verified: whether Mimsi stays the same snail, seconds of video per free GPU hour over a week, uploading clips from the notebook to storage.
- Nothing in the Marius pipeline has been changed by this test.

## Next steps
1. Run test 4, read report.json (used_picture, generate_seconds, sound_has_audio_track) and look at the clips.
2. If Mimsi holds, add the Kaggle path as a fallback (Marius: `scripts/clip_generation.py` on `AgnesOverloadedError`; Tiny Lawn: `video/generate_video.py`).
3. Measure real seconds of video per free GPU hour before relying on it.
