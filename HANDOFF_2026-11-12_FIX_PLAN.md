# HANDOFF 2026-11-12 - Marius quality fix plan (and Lawn Tales next)

Read the live state first (do not trust this file blindly): repo `aliwaziri10/marius-command-center`, Supabase project `iwgocbiqjjhlvkygmcir`.
Owner's rules: full copy-paste files only, tell him what you are about to do BEFORE doing it, every URL/code in its own copy box, no money talk, never name him by anything but what he uses.

## Decisions he stated (2026-11-12)
- NO stock footage at all. Clips must be AI-generated and match the narration.
- Kaggle GPU generates the clips. Agnes should still be watched (probe) because all earlier YouTube videos used Agnes.
- Narrator: en-US-ChristopherNeural (chosen from a 7-voice sample test).
- Protagonist on screen in only ~30% of the video. Every other shot must match script + narration. Every action must be given an explicit command.
- Order: fix Marius quality FIRST, then bring the same Kaggle generation to Lawn Tales. ("long tails" in his dictation = Lawn Tales.)
- The first Kaggle video (script 17fc73b3, YouTube id KQYCt4yIMAU) was judged unacceptable. He set it to PRIVATE.

## Done and verified this session
- Old "Video Generation" workflow (Agnes + stock fallback) disabled by him, then deleted. Also deleted: kaggle_test.yml, cleanup_dead_storage.yml, silent_videos.yml. Kept cleanup_b2_uploaded.yml.
- Kaggle path has NO Agnes call and NO stock code (read kaggle_clips.py, kaggle_clips_kernel.py, helpers).
- ffmpeg missing on the runner was fixed by another session (commit d95c60b); a manual run then saved clips and the script finished.
- Agnes probe added: scripts/agnes_probe.py (commit 9258cb0) + .github/workflows/agnes_probe.yml (commit 0c837aa), every 2 h. First real run 2026-11-10 03:50 UTC: QUEUE_FULL (HTTP 503).
- Narrator switched to Christopher in scripts/narration.py (commit a6d04f0). Another session later added closest-to-done-first ordering to the same file.
- prompt_focus.py fixed (commit 0f9d032): the old code only recognised "recurring protagonist <Name>", so Greta ("Greta Müller is a 38-year-old woman...") was sent with ALL 30 shots. Tested on the real anchor: shots 1 and 8 now get no Greta and a "no people" clause; shot 16 keeps her.

## Root causes of the bad first video (measured)
1. Protagonist detection bug (fixed, above).
2. Planner share limit is blind: shot_breakdown_stage.py counts MAX_SUBJECT_SHOT_RATIO (0.20) only over shots with a non-empty primary_subject tag; the tags are empty, so it counts nothing. Real share in 17fc73b3: Greta named in 13/30 = 43%.
3. Shots are far too long: 30 shots for 1,020 s of narration = 34 s per shot (max 72.7 s, 18 shots > 28 s). The clip builder chains 4 s pieces (SEG_SECONDS=4, MAX_SEGMENTS=7), each continuing from the last frame, so long shots drift/morph and the person "gestures" for ages. A documentary cuts every 4-8 s.
4. Model limits: LTX-Video 2B distilled, 704x480, 8 steps, scaled up to 1280x704 - soft, and faces can look wrong (cross-eyed). The Kaggle prompt has NO negative prompt (not verified in the notebook call; kw list shows none). GPU model not recorded in any log seen.
See docs/17fc73b3_shot_review.md for all 30 shots.

## TODO, in this order
A. Planner (shot_breakdown_stage.py): produce roughly one shot per 4-6 s of narration (about 170-250 shots for a 17-min script), each shot ONE concrete visible action, subject and camera, matching its narration line; count the protagonist BY NAME (use prompt_focus.protagonist_name) and enforce <= 30% of shots. GPU cost is about the same as now (total video seconds are fixed) but chain drift disappears.
B. Kaggle clips: lower MAX_SEGMENTS pressure, no chaining for shots with faces, add a negative prompt (cross-eyed, deformed eyes, extra limbs, morphing), prefer wide/medium over face close-ups.
C. Safety: youtube_upload.py publishes the oldest video_generated script as PUBLIC every 30 min with no review. Make the default privacy "private" (or keep the workflow disabled) until he approves a Kaggle video. NOT done. Whether he disabled YouTube Upload is NOT confirmed.
D. Retire/regenerate 17fc73b3 and rerun with the fixed planner. cb18b7c2 is next in line (0 clips, narrated).
E. Assembly check: this was the first run of narration+SFX+music mix on the Kaggle path; he judged the picture, not yet the sound. Ask him.

## Lawn Tales (after Marius)
- Repo is adrian001234/upgraded-journey (wordless single-character snail comedy, Mimsi, channel Tiny Lawn Tales / The Lawn Tales, Minuscule style). aliwaziri10 reportedly has write access to a forked copy; run get_me and check the live repo FIRST (owner trap).
- Plan: port the Kaggle clip generator (scripts/kaggle_clips.py + kaggle_clips_kernel.py + the beat/prompt helpers) once Marius quality is fixed. Cartoon/animal content hides the AI faces problem better. Not started. Nothing verified about that repo today.
