# HANDOFF 2026-11-12 - Marius quality fix plan (and Lawn Tales next)

START HERE next session: read the LIVE state first (repo `aliwaziri10/marius-command-center`, Supabase project `iwgocbiqjjhlvkygmcir`). Do not trust this file blindly.
Owner's rules: full copy-paste files only (never diffs), tell him what you are about to do BEFORE doing it, one step per message, every URL/code in its own copy box, no money talk, GitHub username always written in full as aliwaziri10, act proactively but verify live first.
Dictated terms: "long tails" = Lawn Tales. Garbled dictation is a mishearing on Claude's side, never his error.

## CURRENT STATE (as told by him, 2026-11-12 - GitHub could not confirm; its API rate-limited this session)
- Kaggle Video Generation workflow: DISABLED by him on purpose, so no more GPU hours are spent on the old too-long shot plan. Nothing makes new clips until it is re-enabled.
- YouTube Upload workflow: DISABLED by him, so nothing can go public unreviewed. It publishes the oldest video_generated script as PUBLIC every 30 min with no review.
- Old "Video Generation" (Agnes + stock fallback) workflow: deleted. Also deleted: kaggle_test.yml, cleanup_dead_storage.yml, silent_videos.yml. Kept cleanup_b2_uploaded.yml.
- Agnes probe (agnes_probe.yml, every 2 h): still on. Last seen result 2026-11-10 03:50 UTC: QUEUE_FULL. It opens a GitHub issue "Agnes is generating videos again" only when Agnes finishes a test clip.
- narrator_voice_test.yml (manual only) is still in the repo; he picked Christopher from it.
- Script 17fc73b3: status uploaded, YouTube id KQYCt4yIMAU, he set it to PRIVATE. Next in queue: cb18b7c2 (narrated, 0 clips, same too-long plan style - do NOT generate it until the planner is fixed).

## Decisions he stated (2026-11-12)
- NO stock footage at all. Clips must be AI-generated and match the narration.
- Kaggle GPU makes the clips. Agnes stays watched by the probe (all earlier YouTube videos used Agnes).
- Narrator: en-US-ChristopherNeural.
- Protagonist on screen only ~30% of the video. Every other shot must match script + narration. Every action must be given an explicit command.
- Order: fix Marius quality FIRST, then Lawn Tales with the same Kaggle approach.
- First Kaggle video judged unacceptable: one woman on screen throughout, AI morphing, objects appearing from nowhere, crossed-looking eyes, low clarity. He wants every shot's on-screen description written out (done: docs/17fc73b3_shot_review.md).

## Done and verified
- Kaggle path has NO Agnes call and NO stock code. Stock came only from the old workflow (stock_fallback.py, switched on by PIXABAY_API_KEY).
- ffmpeg missing on the runner fixed (commit d95c60b, other session); script 17fc73b3 then completed all 30 clips and was assembled and uploaded.
- scripts/narration.py: voice = Christopher (commit a6d04f0). Another session added closest-to-done-first ordering to it.
- scripts/prompt_focus.py fixed (commit 0f9d032): it only recognised "recurring protagonist <Name>", so "Greta Müller is a 38-year-old woman..." was never detected and Greta was sent with ALL 30 shots. Now also matches "<Name> is a <N>-year-old". Tested on the real anchor: shots 1 and 8 get no Greta + a no-people clause; shot 16 keeps her; old wording and the fail-safe still work.
- scripts/agnes_probe.py (commit 9258cb0) + workflow (commit 0c837aa). Tested with 9 fake Agnes answers.
- Docs: docs/17fc73b3_shot_review.md (all 30 shots vs narration).

## Root causes of the bad video (measured)
1. Protagonist detection bug - FIXED.
2. Planner share limit is blind - NOT FIXED: shot_breakdown_stage.py enforces MAX_SUBJECT_SHOT_RATIO (0.20) only over shots with a non-empty primary_subject tag; the tags are empty, so it counts nothing. Real share in 17fc73b3: Greta named in 13/30 = 43%.
3. Shots far too long - NOT FIXED: 30 shots for 1,020 s of narration = 34 s per shot (max 72.7 s, 18 shots > 28 s). kaggle_clips.py chains 4 s pieces (SEG_SECONDS=4, MAX_SEGMENTS=7), each continuing from the previous last frame, so long shots drift and morph. This is the biggest cause. A documentary cuts every 4-8 s.
4. Model limits: LTX-Video 2B distilled, 704x480, 8 steps (kaggle_clips_kernel.py line 25), scaled up to 1280x704. Soft picture, faces can look wrong. The Kaggle prompt (ltx_prompt in kaggle_clips.py) has NO negative prompt. The kernel only asks for "a GPU" (enable_gpu true, no accelerator named) and uses a single GPU; which GPU Kaggle gave is unknown. He does not have the T4 x2 option.

## TODO, in this order
A. Planner (scripts/shot_breakdown_stage.py, large file ~700+ lines, read ALL of it first, especially SHOT_RULES_BLOCK, the Gemini call and the validators around lines 590-700): produce about one shot per 4-6 s of narration (about 170-250 shots for a 17-min script), each shot ONE concrete visible action + subject + camera that matches its narration line; count the protagonist BY NAME (prompt_focus.protagonist_name) and enforce <= 30%. GPU cost stays about the same (total video seconds are fixed) but chain drift disappears. Push as a full file via the GitHub connector (scripts/ writes work; .github/workflows/ writes return 403, so workflow files must be pasted by him).
B. kaggle_clips.py / kernel: add a negative prompt (cross-eyed, deformed eyes, extra limbs, morphing, melting), avoid chaining for shots with faces, prefer wide/medium over face close-ups, print the GPU name in the run summary.
C. youtube_upload.py: make the default privacy "private" until he approves a Kaggle video, THEN he can re-enable the workflow. Do not re-enable YouTube Upload before this.
D. Re-enable Kaggle Video Generation (he clicks Enable workflow) only after A and B are live; then retire/regenerate 17fc73b3 and run cb18b7c2 with the new plan.
E. Ask him whether the sound (Christopher narration + ACE music + Freesound SFX) was acceptable in the finished video; he only judged the picture.
F. When Agnes recovers (probe issue appears), build "check Agnes first, one engine per video" routing.

## Lawn Tales (after Marius)
Repo is adrian001234/upgraded-journey (wordless single-character snail comedy, Mimsi, channel Tiny Lawn Tales / The Lawn Tales). aliwaziri10 reportedly has write access to a forked copy; run GitHub get_me and check the live repo FIRST (owner trap). Plan: port the Kaggle clip generator (kaggle_clips.py, kaggle_clips_kernel.py, beat_director/prompt helpers). Cartoon/animal content hides AI-face problems far better. Not started; nothing about that repo was verified today.
