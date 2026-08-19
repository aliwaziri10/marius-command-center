# Marius / Erased — Continuation Notes (2026-08-20)

**Supersedes the 2026-08-19 version below (kept at the bottom for
history). Everything in this top section is current as of 2026-08-20 and
is marked CONFIRMED (verified live against real code/data) or HYPOTHESIS
(reasoned but not proven) per DEBUGGING_METHODOLOGY.md.**

## Bitrate fix (2026-08-20 session) — CONFIRMED WORKING
`compute_target_bitrate()`'s floor lowered 300kbps→80kbps, target_mb
42→44 (commit `5982fc3`). Script `ba5d96c8` ("40,000 THIRSTY. ONE LOOM.",
31 shots, 1152s/~19min) ran to completion: assembled, uploaded to
Supabase Storage, and uploaded to YouTube. `status` is now `uploaded`.
**This confirms the 50MB-cap upload failure is resolved.**

## NEW, more serious problem found this session: the uploaded video is low quality
Zia watched the actual upload and flagged four distinct issues. Root
causes below are a mix of CONFIRMED (verified against real
`shot_durations`/code) and HYPOTHESIS (hasn't been proven by execution
yet - do not treat as settled).

### 1. Heavy freeze-frames throughout, not just the outro — CONFIRMED root cause
Real `shot_durations` for `ba5d96c8` (31 shots): 31.8, 28.8, 45.4, 27.2,
20.4, 43.0, 57.0, 37.8, 36.6, 33.4, 24.3, 76.9, 33.5, 52.5, 35.5, 34.2,
34.6, 86.4, 25.7, 41.3, 23.5, 31.6, 35.0, 27.3, 41.7, 37.8, 18.9, 22.5,
20.3, 36.4, 47.9 (seconds). Agnes can only generate ~7.04s per call
(`MAX_FRAMES/FRAME_RATE = 169/24`); chain-extension covers at most 3
more ~7s segments (`MAX_CHAIN_SEGMENTS=3`), so ~21s of real footage is
the ceiling per shot. Every shot here needs 19–86s. Confirmed math: most
shots are 15–65+ seconds of frozen padding. Root cause is pacing, not a
video_generation.py bug: 31 shots is far too few for a ~19-minute video
at current per-shot generation limits.
**PROPOSED FIX (not yet pushed):** raise `MIN_SHOTS`/`MAX_SHOTS` in
`script_writing.py` (currently 25/35, cut 2026-08-17 to conserve Groq
daily-token budget) back up now that Gemini is the provider and that
constraint no longer applies. More, shorter shots = less per-shot
overflow = less freeze padding.

### 2. Named character (Bintou Bala) appears in nearly every shot — CONFIRMED root cause
`setting_and_characters` includes a full physical description of one
named recurring character. `build_agnes_prompt` (fallback_level 0)
includes this anchor text in every shot's prompt by default, and only
strips it (`_strip_named_characters_for_group_shot`) for shots whose
`visual_description` matches `CROWD_OR_GROUP_KEYWORDS`. Any non-crowd
shot (establishing shots, objects, scenery, other people) still gets her
full description fed to Agnes, causing her to visually appear in shots
she has no reason to be in. Zia's explicit instruction: the hero/heroine
must NOT appear in every scene - not optional.
**PROPOSED FIX (not yet pushed):** invert the default in
`build_agnes_prompt` - strip the named-character clause from the anchor
UNLESS the shot's own `visual_description` text actually references the
character (by name or a clear pronoun tied to prior context). Setting/
era/location context stays either way.

### 3. Character changed gender mid-video (same "hero" shown as a man in 2 scenes) — HYPOTHESIS, code-consistent
Cross-shot continuity chaining (image-to-image anchoring between
consecutive shots) was fully disabled 2026-08-18 (see
`video_generation.py` header, "CONTINUITY-CHAIN REMOVED") because it
caused a different problem: visible morphing/deforming during scene
transitions, since Agnes has to "unfreeze" from a static last-frame
anchor. Since that removal, every shot generates from TEXT ONLY with
zero visual anchor - nothing enforces consistent likeness between shots,
only the text description. This is a fully plausible, code-confirmed
explanation for identity drift (including gender) between shots, but has
not been proven by execution against this specific video's shots -
treat as HYPOTHESIS until verified.
**PROPOSED FIX (not yet pushed, design change, needs Zia sign-off):**
re-enable `generate_character_reference()` (currently dormant) and pass
the SAME single static reference image as the anchor for every shot
that features the named character - NOT chained shot-to-shot last-frame
anchoring (which is what caused the 2026-08-18 morphing problem). A
fixed reference portrait gives identity consistency without inheriting
the previous shot's ending motion/frame, so it shouldn't reintroduce the
morph-transition artifact. This is a genuinely new approach, not a
revert - has not been tested.

### 4. Music/SFX — Zia's explicit direction this session
- **Music: opt out entirely.** Stop calling `generate_background_music`
  altogether (not "let it fail silently" - actually skip it). Currently
  `music_generated: false` on `ba5d96c8` because ACE Music/MusicGen both
  failed silently anyway, but the code should stop trying at all.
- **SFX: keep, must actually work.** `sfx_applied_count: 0` on
  `ba5d96c8` - every SFX cue silently failed. Zia confirmed
  `FREESOUND_API_KEY` (and every other secret) is genuinely present and
  correctly set, so a missing/empty key is RULED OUT as the cause. Real
  root cause NOT YET INVESTIGATED - needs a live trace of
  `search_freesound_sfx()` against real `sfx_cue` text from this script's
  `shot_list` (per DEBUGGING_METHODOLOGY.md, don't guess - trace the
  actual query text and actual Freesound API response next session).

### 5. Narration tone — not yet investigated
Zia: narration doesn't read as documentary/emotionally-emotive, feels
"horrible." No code investigation done yet this session - next step is
pulling the actual narration prompt from `narration_stage.py` and
reviewing/rewriting its tone instructions. Nothing CONFIRMED or
HYPOTHESIZED yet on root cause - this is a fresh open item.

## Standing constraint this session
Two other pipeline runs (Marius `video_generation.yml`, Nova
`generate_videos.yml`) were live/in-progress while this investigation
happened. Per the "never push/edit a file while its pipeline might be
mid-run" rule, NONE of the proposed fixes above have been pushed yet.
Waiting for Zia to confirm both runs are finished before touching
`script_writing.py` or `video_generation.py`.

## NEXT STEPS, in order
1. Confirm both in-flight workflow runs (Marius, Nova) are finished.
2. Push fixes one file at a time: (a) `script_writing.py` MIN/MAX_SHOTS
   raise, (b) `video_generation.py` anchor-suppression-by-default logic
   for the named character, (c) `video_generation.py` remove music call
   entirely, (d) investigate + fix SFX silent failure with real query/
   response data, (e) investigate + fix narration tone prompt.
3. Get Zia's explicit sign-off on the static-reference-image approach
   (item 3 above) before implementing - it's a new design, not a proven
   fix, and past chaining attempts have caused regressions twice already
   (2026-07-31 added, 2026-08-18 removed for a different bug).
4. Once fixes are pushed and verified working on a fresh script, reset
   `ba5d96c8` (clear `video_urls`, set `video_next_index=0`, status back
   to `images_generated`) to fully regenerate under the fixed pipeline.
   Do NOT reset it before the fixes land - would just reproduce the same
   bad output.
5. Zia is deciding separately whether to delete the current live
   `ba5d96c8` YouTube upload - not Claude's call, no action taken on
   YouTube this session.

---

# Marius / Erased — Continuation Notes (2026-08-19) [SUPERSEDED, kept for history]

**This file had gone unmaintained since 2026-08-07 despite the standing
"update every session" rule in DEBUGGING_STANDARDS.md - it described a
crash investigation and architecture that predate three major changes
since (Groq detour, Gemini switch-back, the 2026-08-18 module split).
Everything below is current as of 2026-08-19 and is marked CONFIRMED
(verified live against real code/data/logs) or HYPOTHESIS (reasoned but
not yet proven by execution, per DEBUGGING_METHODOLOGY.md) - do not
upgrade a HYPOTHESIS line to fact without actually verifying it first.**

## Current architecture (CONFIRMED - read directly from live GitHub, 2026-08-19)
Script generation split 2026-08-18 into three modules, no behavior change
at split time: `llm_client.py` (Gemini call wrapper, Supabase retry
helper, JSON extraction), `narration_stage.py` (Stage 1: narration text),
`shot_breakdown_stage.py` (Stage 2: shot-by-shot breakdown, in
NUM_SHOT_CHUNKS=2 chunks). `script_writing.py` now only orchestrates:
fetch pending topics, run both stages, save, update status.

Provider is Gemini (`gemini-3.5-flash-lite`) - the pipeline briefly ran on
Groq 2026-08-15 through 2026-08-17 (abandoned: Groq's daily token cap is
structurally invisible in its response headers, so 429s could show fully
healthy per-minute headers while permanently blocked). `GEMINI_API_KEY`
is confirmed present as a repo secret and confirmed correctly wired into
`script_writing.yml`'s env block (a real bug where the workflow only
passed `GROQ_API_KEY` even after the code switched back to Gemini was
found and fixed 2026-08-17).

GitHub write access for this repo is CONFIRMED WORKING as of 2026-08-19
(multiple `create_or_update_file` commits landed and were read back
successfully this session, on both `scripts/*.py` and top-level docs) -
this reverses the old "403, read-only" note. See DEBUGGING_STANDARDS.md
point 4.

## Live run findings (2026-08-19) - CONFIRMED symptom, root causes are HYPOTHESIS
A real `python scripts/script_writing.py` run (pasted log, not summarized)
tried 5 topics, all 5 failed:
- Narration stage: no longer the bottleneck - confirmed at 2374-3122 words
  on every topic (one hit the CTA-missing retry once, recovered next
  attempt).
- Shot-breakdown stage: 2 dominant failure modes, both CONFIRMED as
  frequent from the real log, root cause of each is HYPOTHESIS only:
  1. `required_onscreen_text` left empty despite the HARD RULE in the
     prompt - hit on 4 of 5 topics, some more than once. **Structural gap
     identified in the code (this part IS confirmed, it's not a guess):
     every content-attempt retry in `generate_shot_breakdown()` rebuilds
     the exact same prompt from scratch with no information about why the
     previous attempt failed - retries are blind rerolls, not corrective.**
     NOT YET FIXED - a fix (thread the previous failure reason into the
     next attempt's prompt) was scoped but deliberately not pushed yet,
     pending confirmation this is the right next step.
  2. JSON parse failures ("Expecting property name enclosed in double
     quotes") at small character offsets (691-4484 chars) - too early to
     be maxOutputTokens truncation. HYPOTHESIS: genuine malformed JSON
     (trailing comma before a closing brace/bracket) from Gemini despite
     native JSON mode being on. NOT CONFIRMED - the actual raw failing
     text was never captured. Fix applied as a safety net either way
     (`_strip_trailing_commas()` added to `extract_json()`'s repair
     sequence, harmless no-op if wrong), PLUS diagnostic logging added so
     the next occurrence logs which repair (if any) fixed it, or the raw
     text if none did. **Check that log output before treating the
     trailing-comma theory as settled.**

## Other open item, NOT investigated this session
`STATUS.md` (auto-generated bot on every "update status" commit. **Never hand-edit this.**
 shows 3 scripts currently stuck at `images_generated` with 0 clips as of
2026-08-19 09:16 UTC. Separate from the script-writing issues above.

## NEXT STEP
1. Implement and push the blind-retry fix in `shot_breakdown_stage.py`
   (thread `last_reason` into the next content-attempt's prompt as
   corrective guidance) - scoped, not yet done.
2. Trigger a real run afterward and read the new `extract_json` diagnostic
   log output to confirm or refute the trailing-comma hypothesis before
   writing it up as a fixed root cause anywhere.
3. Separately: check the 3 scripts stuck at `images_generated`/0 clips.
