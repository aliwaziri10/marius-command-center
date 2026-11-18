# Marius / Erased - Continuation Notes (2026-11-18 PART 7, FIRST KAGGLE VIDEO REJECTED, FIXES MADE, TWO WORKFLOWS PAUSED, read this section FIRST)

Times are UTC. Zia is in India (UTC+5:30). Re-verify against live GitHub and Supabase before acting. Supabase project: `iwgocbiqjjhlvkygmcir`.
Before creating or editing ANYTHING read `REPO_ACCESS_RULE.md` and `DEBUGGING_STANDARDS.md`. A session on 2026-11-12 skipped them and created extra dated files; that is the mistake behind this rewrite. Lawn Tales lives in `aliwaziri10/upgraded-journey` ONLY. Never use `adrian001234/upgraded-journey`.

## NEXT PROFILE START HERE
1. Ask Zia which workflows are enabled. He says he DISABLED `kaggle_clips.yml` (Kaggle Video Generation) and `youtube_upload.yml` (YouTube Upload) on 2026-11-12. The GitHub API refuses the sandbox (rate limit), so this is NOT confirmed from here.
2. Do the TODO list below in order. Item A comes first.
3. Zia wants Marius fixed first, then Lawn Tales. One project per session.

## What happened 2026-11-10 to 2026-11-12 (verified live unless marked)
- The first Kaggle video, script `17fc73b3`, was assembled and reached `uploaded` (YouTube id `KQYCt4yIMAU`). `youtube_upload.py` publishes the oldest `video_generated` script as PUBLIC every 30 minutes with no review, so it went public by itself. Zia judged the picture unacceptable (one woman on screen for 17 minutes, AI morphing, objects appearing from nowhere, eyes that look crossed, soft picture) and set it to PRIVATE. He has not yet judged the sound (Christopher narration, ACE music, Freesound effects).
- The old Video Generation workflow (Agnes, with the stock-footage fallback switched on by `PIXABAY_API_KEY`) was disabled by Zia and then deleted. That was the only source of stock footage; the Kaggle path has no Agnes call and no stock code. Also deleted: `kaggle_test.yml`, `cleanup_dead_storage.yml`, `silent_videos.yml` (nothing referenced them; the scripts stay). Kept: `cleanup_b2_uploaded.yml`. `b2_preflight.py` and `verify_run_output.py` are still referenced by workflows (`kaggle_clips.yml`, `script_writing.yml`): do not delete.
- Added `scripts/agnes_probe.py` (`9258cb0`) and `.github/workflows/agnes_probe.yml` (`0c837aa`): every 2 hours it asks Agnes for one 4 second test clip and opens a GitHub issue "Agnes is generating videos again" only if a finished clip comes back. Last seen result 2026-11-10 03:50: QUEUE_FULL (HTTP 503). Tested with 9 fake Agnes answers; the first real run was the 03:50 one.
- Added `.github/workflows/narrator_voice_test.yml` (manual only). Zia picked `en-US-ChristopherNeural`; `scripts/narration.py` uses it (`a6d04f0`).
- `scripts/prompt_focus.py` (`0f9d032`): the code only recognised "recurring protagonist <Name>". The anchor for `17fc73b3` says "Greta Müller is a 38-year-old woman...", so no protagonist was found and her description was sent with ALL 30 shots, including the Stasi building and the Berlin Wall. It now also matches "<Name> is a <N>-year-old". Tested on the real anchor: shots 1 and 8 lose Greta and get a "no people" clause; shot 16 keeps her.
- `scripts/kaggle_clips_kernel.py` rev 3 (`d782503`): CUT MODE is the default. Each piece of a shot (about 4 s) is its own text-to-video clip from its own beat prompt instead of a picture-to-video chain from the previous last frame. Setting `cut_mode` to false in the manifest restores the chain. NOT yet run on a GPU. The notebook already records the GPU name in `manifest_out.json` (key `gpu`); nothing prints it in the run summary.
- `docs/17fc73b3_shot_review.md` lists all 30 shots of that script next to their narration.

## Why the first video was bad (measured on the live data)
1. Protagonist detection bug: FIXED (above).
2. The planner's share limit is blind: `shot_breakdown_stage.py` applies `MAX_SUBJECT_SHOT_RATIO` (0.20) only over shots that carry a non-empty `primary_subject`. The tags are empty, so it counts nothing. Real share in `17fc73b3`: Greta named in 13 of 30 shots (43%). Zia wants 30% at most. NOT FIXED.
3. Shots are far too long: 30 shots for 1020 s of narration is 34 s per shot (longest 72.7 s, 18 shots over 28 s). The kernel builds a shot from up to 7 pieces of about 4 s, so long shots drift. A documentary cuts every 4 to 8 s. Cut mode removes the cumulative drift but the plan itself is still too coarse. NOT FIXED.
4. Model limits: LTX-Video 2B distilled, 704x480, 8 steps, scaled to 1280x704. A negative prompt would do nothing, because the call uses `guidance_scale=1.0` (distilled model, no CFG). Do not add one.

## Decisions Zia stated (2026-11-12)
- No stock footage at all. Every clip AI-generated and matching the narration. Kaggle GPU makes the clips.
- Agnes stays monitored (the probe), because all his earlier YouTube videos used Agnes.
- Protagonist on screen in about 30% of the video at most. Every other shot must match the script and narration. Every action needs an explicit command.
- Fix Marius first, then Lawn Tales with the same Kaggle approach ("long tails" in his dictation means Lawn Tales).

## TODO, in this order
A. `scripts/shot_breakdown_stage.py` (1232 lines, read ALL of it first, especially `SHOT_RULES_BLOCK`, the Gemini calls and the validators near lines 590 to 700): one shot per 4 to 6 s of narration, each with ONE concrete visible action, subject and camera matching its narration line, and the protagonist counted BY NAME (`prompt_focus.protagonist_name`) with a hard 30% cap.
B. GPU cost: PART 6 decision 1 (cap pieces per shot) still waits for Zia. With cut mode, each extra piece is a new angle, so a lower cap changes pacing, not drift.
C. `scripts/youtube_upload.py`: default privacy to private until Zia approves a Kaggle video. NOT done. Do not re-enable YouTube Upload before this.
D. Re-enable Kaggle Video Generation (Zia clicks Enable workflow) only after A is live. Then redo `17fc73b3` and run `cb18b7c2`.
E. Ask Zia whether the sound was acceptable.
F. When the Agnes probe opens its issue, build "check Agnes first, one engine per video".
G. Lawn Tales: `HANDOFF_2026-10-25_TLT_KAGGLE.md` has the plan (3D snail Mimsi). Repo is `aliwaziri10/upgraded-journey`; secrets must be set on THAT repo. Not started.
Backlog (STATUS.md 2026-11-18 03:32): uploaded 21, images_generated 124, newest script has 0 clips. At about 7.5 GPU hours per video the queue only grows (PART 6 arithmetic).

---

# Marius / Erased - Continuation Notes (2026-11-11 PART 6, NARRATION ORDER + NARRATION STORAGE + THROUGHPUT)

(PART 7 above is newer. Answer to this part's step 1: `17fc73b3` reached `uploaded` on 2026-11-12, so the Kaggle assembly path worked once; sound and picture were not judged as good.)

Times are UTC. Zia is in India (UTC+5:30), so his "Nov 12" is the evening of 2026-11-11 UTC. Re-verify against live GitHub/Supabase before acting. Supabase project: `iwgocbiqjjhlvkygmcir`.

## What changed in PART 6
- `c8094f7`: `scripts/narration.py` now picks the pending script with the most clips saved first (`video_next_index` desc, nulls last, then `created_at`). Reviewed: the query is inside the existing try/except, so a bad query exits green with "nothing done", never red.
- `9854cd0`: cosmetic ellipsis spelling in `narration.py`, no behavior change.
- Database: scripts `17fc73b3` and `cb18b7c2` were set to `pending` so narration rebuilt their lost mp3 files. No clips or other rows touched.

## Confirmed live (2026-11-11, about 21:10)
- `17fc73b3`: a manual Narration run at about 21:08 made `narration_17fc73b3-834f-4ba4-8a8c-fd7a1044d2de.mp3` (15.6 MB, voice ChristopherNeural, 142 sentences). 30 of 30 clips saved, 30 `shot_durations` totalling 1020 s (old total 971 s, +5%).
- `cb18b7c2`: `pending`, 0 clips, 31 shots, 1295 s, no narration file.
- `narration.yml` says cron `0 * * * *`, but the Actions list (runs #823 to #829) showed runs 4 to 9 hours apart. GitHub is not running it hourly. Each run narrates 1 script (`MAX_SCRIPTS_PER_RUN = 1`).
- Narration storage (20:35): 51 files, 634 MB, bucket has no `file_size_limit`. Of 112 `images_generated` scripts, 70 have no narration file and 42 have one. No code that deletes them was found. Cause unknown.

## Why videos come out about once a week (arithmetic, NOT measured on Kaggle)
- Average script: 817 s of narration, about 187 four-second pieces (cap 7 per shot), from `shot_durations`.
- About 135 s of GPU per piece (one test run, see `HANDOFF_2026-11-10_KAGGLE_CLIPS.md`). That is about 7 h of GPU per video.
- Kaggle GPU quota is commonly reported as about 30 h/week, but Kaggle's docs give no number. Ceiling is about 4 videos a week. The runner stops each Kaggle run at 7 h (`KAGGLE_BUDGET_MINUTES=420`).
- Script Writing adds about 3 scripts a day, so the queue only grows.
- Measured 2026-11-11: 27 shots took the full 7 hour budget (about 15 minutes per shot) on the first batch.

## NOT verified (PART 6)
- Assembly with narration 5% longer than the clips: it stretches or holds short clips. Not checked visually.
- Actions logs: the GitHub connector cannot read them and `web_fetch` refuses run URLs. Use Supabase (`last_error`, `storage.objects`, `query_logs`), failure issues, or ask Zia to paste the log.
- `narration.py` only prints failures to the run log. It does not save them to `scripts.last_error`. If you add it, clear that error on success: `kaggle_clips.py` `recently_errored()` skips a fully-clipped script for 6 h after any `last_error_at`.
- Script Writing fails about every 8 h (issues #1684 to #1693). Not investigated.

## Do not
- Do not set the 70 narration-less scripts to `pending` (about 870 MB of new files, and the Kaggle queue cannot reach them for weeks).
- Do not let narration run further ahead of GPU capacity without a cap.

## Decisions waiting for Zia (free options only)
1. Cut GPU cost: cap pieces per shot (`MAX_SEGMENTS` 7 to 3, hold the rest) or keep full length and accept about 4 videos a week at best.
2. Throttle narration while many narrated scripts wait, and delete a script's mp3 after its video uploads.
3. Test a stronger model: 3 shots each on Wan 2.2 5B and HunyuanVideo 1.5 on Kaggle, time each clip, Zia judges quality.
4. Test both T4 GPUs at once, one job per card. Zia says the T4 x2 option is not offered on his account; the GPU name is in `manifest_out.json`.

## How Zia works
Non-coder, voice dictation. Full files, every URL, path and secret name in its own code block, one step at a time, one project per session (Marius only, never mix Nova). He gets angry at hedging: read the repo, Supabase and issues yourself first, say what is proven, say plainly what you cannot see. Tell him what you are about to do before you do it. No em dashes in anything written for him. Never create or change anything before reading the files involved.

---

# Older history (2026-09-19 to 2026-09-21, compressed 2026-11-18; full text is in `git log -- CONTINUATION.md`)
Standing facts that are still true:
- `scripts/b2_preflight.py` and `scripts/verify_run_output.py` are run by workflows. Do NOT delete them.
- `narration.py` (the audio stage, run by `narration.yml`) and `narration_stage.py` (a text helper imported by `script_writing.py`) are different files with confusingly similar names. Both are live. Do not rename.
- `beat_director.py` is a fail-soft Gemini call that writes beats (`action`, `camera_movement`, `shot_type`) for long shots; any failure returns `None` and the old repeated-prompt behavior is used. In the 2026-11-10 Kaggle log many shots fell back because of HTTP errors or invalid answers.
- `code_health_check.yml` only runs `py_compile`; it would not catch a broken cross-file import.
- The connector gets 403 on `.github/workflows/*` (Zia must commit those) and writes fine to `scripts/*` and docs.
- The live Supabase project is `iwgocbiqjjhlvkygmcir`. The old id in `PLAYBOOK.md` (`swnjzzejsuupecdgbzzf`) is stale.
- Deleted as unused on 2026-09-19: `health_agent.py`, `image_generation.py`, `test_narration_edgetts.py`, `test_narration_freellm.py`.
- Open research, unbuilt: a free-LLM fallback chain for `llm_client.py` (Gemini Flash-Lite models first, then Groq, Mistral, NVIDIA NIM). Needs keys as GitHub secrets.
- Agnes: a POST that times out on the read side may already have created a task (possible duplicate clip credit). Not measured.
