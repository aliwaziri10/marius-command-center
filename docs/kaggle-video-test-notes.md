# Kaggle free-GPU video test: decision notes

Date: 2026-10-21 (written during the Agnes queue-full backup search)

## Decision
- Backup video generation will use the open-source Wan 2.2 and LTX-Video models.
- Everything runs on Kaggle's free GPU. Zia has no GPU and nothing runs on his laptop.
- Free only. No paid, credit-based, daily-credit or trial tools, ever.
- GitHub Actions starts the Kaggle notebook; no manual clicking per clip.

## Where things are
- Workflow: `.github/workflows/kaggle_test.yml` (manual run, "Kaggle Video Test")
- Runner script: `scripts/kaggle_video_test/run_test.py` (pushes the notebook, waits, downloads results into `kaggle_out/`)
- Notebook that runs on Kaggle: `scripts/kaggle_video_test/kernel.py` (tries Wan 2.2 5B first, then LTX-Video, writes `report.json` + test clips)
- Repo secrets: `KAGGLE_USERNAME`, `KAGGLE_API_TOKEN` (values are never stored in the repo)
- Kaggle account username: `ziawaziri`

## Requirements and open points
- Kaggle account must be phone-verified for GPU and internet inside notebooks (not done as of 2026-10-21).
- Model files are downloaded free and without an account by the notebook at run time.
- Not yet verified: clip quality on Kaggle's GPU, seconds of video per free GPU hour, and uploading clips from inside the notebook to our storage.
- Nothing in the Marius pipeline has been changed by this test.

## Next steps
1. Read the first run's `report.json` and clips.
2. If it works, add the Kaggle path as a fallback in `scripts/clip_generation.py` when Agnes raises `AgnesOverloadedError`.
3. Measure real seconds of video per free GPU hour before relying on it.
