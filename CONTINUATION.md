# Marius / Erased — Continuation Notes (2026-08-20, FULL HANDOFF)

**Read this entire file before touching any code. This session ran out of
context mid-fix — nothing below has been pushed except this doc and the
bitrate fix noted in section 0. Everything in "PROPOSED FIXES" is scoped
but NOT implemented. Follow the order in "EXECUTION ORDER" exactly.**

Status markers: CONFIRMED = proven against real code/data this session.
HYPOTHESIS = reasoned, not proven by execution. Per
DEBUGGING_METHODOLOGY.md, do not upgrade a HYPOTHESIS to fact without
verifying it first.

---

## 0. What's actually fixed and live right now — CONFIRMED

`compute_target_bitrate()`'s floor lowered 300kbps→80kbps, target_mb
42→44 (commit `5982fc3`, already on `main`). This fixed the Supabase
50MB-per-file upload cap crash. Script `ba5d96c8` ("40,000 THIRSTY. ONE
LOOM.", 31 shots, ~1152s/~19min) ran to completion this session:
assembled, uploaded to Supabase Storage, uploaded to YouTube.
`status = 'uploaded'`. **The upload-failure bug is genuinely resolved.**

But Zia watched the actual video and it's bad. Five distinct problems
found this session, all below. **None of the fixes for these are pushed
yet.**

---

## 1. Freeze-frames throughout the video — CONFIRMED root cause

Real `shot_durations` for `ba5d96c8` (31 shots, seconds): 31.8, 28.8,
45.4, 27.2, 20.4, 43.0, 57.0, 37.8, 36.6, 33.4, 24.3, 76.9, 33.5, 52.5,
35.5, 34.2, 34.6, 86.4, 25.7, 41.3, 23.5, 31.6, 35.0, 27.3, 41.7, 37.8,
18.9, 22.5, 20.3, 36.4, 47.9.

Agnes generates ~7.04s per call max (`MAX_FRAMES/FRAME_RATE = 169/24`).
Chain-extension adds at most 3 more ~7s segments (`MAX_CHAIN_SEGMENTS=3`)
→ ~21s of real generated footage is the hard ceiling per shot. Every
shot above needs 19–86s. Most shots get 15–65+ seconds of frozen
padding. This is a pacing problem: 31 shots is far too few for a
19-minute video given the per-shot generation ceiling.

**PROPOSED FIX:** raise `MIN_SHOTS`/`MAX_SHOTS` in `script_writing.py`
(currently 25/35 — cut from 60/85 on 2026-08-17 specifically to
conserve Groq's daily token budget). That constraint is gone — Marius
switched to Gemini the same day, and Gemini doesn't have Groq's
invisible daily cap. Re-raising shot count is now safe and directly
reduces per-shot overflow.
**File to edit:** `scripts/script_writing.py`
**Suggested values:** restore toward the original 60/85, or something
in between (e.g. 50/70) — exact numbers need Zia's input on desired
video length vs. shot density trade-off. This interacts with item 6
below (video length itself may need to come down).

---

## 2. Named character appears in nearly every shot — CONFIRMED root cause

`setting_and_characters` for `ba5d96c8` describes one named recurring
character (Bintou Bala) in full physical detail. `build_agnes_prompt`
(fallback_level 0, in `video_generation.py`) includes this full anchor
text in every shot's prompt by default, and only strips it
(`_strip_named_characters_for_group_shot`) for shots whose
`visual_description` matches `CROWD_OR_GROUP_KEYWORDS`. Any non-crowd
shot (establishing shots, objects, scenery, other people) still gets her
full description, so she visually appears in shots she has no reason to
be in. **Zia's explicit instruction: the hero/heroine must not appear in
every scene — not optional, not a style preference.**

**PROPOSED FIX:** invert the default in `build_agnes_prompt` — strip the
named-character clause from the anchor UNLESS the shot's own
`visual_description` text actually references the character (by name,
or an unambiguous pronoun/role reference). Setting/era/location context
stays in the anchor either way; only the character-specific physical
description becomes conditional.
**File to edit:** `scripts/video_generation.py`, function
`build_agnes_prompt` (and possibly `_strip_named_characters_for_group_shot`,
which may need a companion function or an inverted condition rather than
a rename).

---

## 3. Character changed gender mid-video — HYPOTHESIS, code-consistent, NOT proven by execution

Zia observed the same "hero" character rendered as a man in 2 scenes
mid-video. Cross-shot continuity chaining (image-to-image anchoring
between consecutive shots) was fully disabled 2026-08-18 (see
`video_generation.py` header: "CONTINUITY-CHAIN REMOVED") because it
caused a different bug: visible morphing/deforming during scene
transitions (Agnes "unfreezing" from a static last-frame anchor). Since
then, every shot generates from TEXT ONLY, zero visual anchor — nothing
enforces consistent likeness shot-to-shot, only the text description.
This is a fully plausible explanation for identity drift including
gender, but has NOT been proven against this specific video's actual
shots/generations — do not treat as confirmed.

**PROPOSED FIX (needs Zia's explicit sign-off before implementing — this
is a new design, not a revert, and continuity chaining has already
caused two different regressions: added 2026-07-31, removed 2026-08-18
for the morphing bug):**
Re-enable `generate_character_reference()` (currently dormant, defined
but unused in `video_generation.py`) and pass the SAME single static
reference image as the anchor for every shot that features the named
character — NOT chained shot-to-shot last-frame anchoring (that's what
caused the 2026-08-18 morphing problem specifically). A single fixed
reference portrait gives identity consistency without inheriting the
previous shot's ending motion/frame, so it should not reintroduce the
transition-morph artifact — but this exact approach has never been
tried and is unverified. Test on one script before wide rollout.
**File to edit:** `scripts/video_generation.py` — re-wire
`generate_character_reference()` and pass its URL as `anchor_image_url`
in `process_script()`'s per-shot loop, but ONLY for shots identified as
featuring the named character (same detection logic as item 2's fix —
these two fixes should share one "does this shot feature the named
character" check).

---

## 4. Video is much lower quality than videos from ~2-3 days ago — CONFIRMED root cause, NEW problem, introduced by THIS session's own bitrate fix

Zia flagged picture quality as looking like ~144p or worse, despite the
video actually being encoded at 1280x720. Math, run and confirmed this
session:

```
target_mb = 44, audio_kbps = 128, duration = 1152.3s
target_bits = 44 * 8 * 1024 * 1024 = 369,098,752
audio_bits = 128000 * 1152.3 = 147,494,400
video_bits = target_bits - audio_bits = 221,604,352
video bitrate = video_bits / duration / 1000 ≈ 192.3 kbps
```

**192kbps at 1280x720/24fps is roughly 15-20x lower than a normal decent
720p bitrate (~2500-4000kbps).** This is a direct, mechanical consequence
of THIS session's own fix (item 0 above) — squeezing a ~19-minute 720p
video under Supabase's 50MB free-tier cap forces the bitrate down to
near-nothing. The upload-failure bug is fixed, but only by making the
video look terrible. **This is a real trade-off, not a bug with a clean
fix** — the 50MB cap and a ~19-minute 720p video are fundamentally
incompatible at watchable quality.

Videos from ~2-3 days ago (better quality, per Zia) were very likely
produced BEFORE the 25-run crash streak started (see
`video_generation.py` header, "TRAIL-EXTENSION CRASH FIX" — that
streak is GitHub issues #138-#162, and covered a long stretch where NO
video could complete assembly at all) — meaning those earlier good
videos used the OLD `compute_target_bitrate` (300kbps floor, target_mb
42) and were shorter and/or produced before other changes, giving a
higher effective bitrate. This is a HYPOTHESIS for why they looked
better — not proven, but consistent with the timeline.

**PROPOSED FIXES — this needs a real decision, not just a code change.
Options, none implemented, no cost implications (all stay within
$0 no-spend rule):**

- **Option A — reduce resolution.** Drop `WIDTH, HEIGHT` (currently
  1280, 720) to something like 854x480. Same 44MB budget spread over
  fewer pixels = meaningfully better perceived quality per byte, at the
  cost of not being "true" 720p. Simple, low-risk, one-constant change.
- **Option B — shorter videos.** Reduce target episode length (fewer/
  shorter shots — ties into item 1's shot-count fix) so the same 44MB
  budget covers fewer seconds, raising effective bitrate. Directly
  trades episode length for quality.
- **Option C — better codec efficiency.** Switch encode from H.264
  (`libx264`) to H.265/HEVC (`libx265`), which is meaningfully more
  efficient at the same bitrate (roughly 40-50% better in practice).
  Needs verifying `libx265` is available in the GitHub Actions Ubuntu
  runner's ffmpeg build (NOT yet checked this session), and that
  YouTube's upload pipeline handles an HEVC-encoded source file cleanly
  end-to-end (also NOT yet checked).
- **Option D — remove the 50MB constraint at its source (potentially
  the best long-term fix, NOT yet investigated).** The pipeline currently
  uploads the final assembled video to Supabase Storage
  (`upload_video()` in `video_generation.py`) BEFORE a separate
  `youtube_upload.yml` workflow presumably reads it back out to push to
  YouTube. If the final video never actually needs to live in Supabase
  Storage — e.g. if it could upload directly to YouTube from the same
  runner that assembles it, or hand off via a differently-capped
  intermediate store — the 50MB cap might be avoidable entirely rather
  than traded against quality. **Needs investigation into
  `youtube_upload.yml` and how it currently sources the video file
  before deciding if this is viable.**

**This needs Zia's input on which trade-off he wants (or investigating
Option D properly) before any of A/B/C get implemented — do not pick one
unilaterally.**

---

## 5. Music/SFX — Zia's explicit direction this session

- **Music: opt out entirely.** Stop calling `generate_background_music`
  altogether — not "let it keep failing silently," actually remove the
  call. Currently `music_generated: false` on `ba5d96c8` because ACE
  Music/MusicGen both failed anyway, but the code should stop trying.
- **SFX: keep, must actually work.** `sfx_applied_count: 0` on
  `ba5d96c8` — every SFX cue silently failed this run. Zia confirmed
  `FREESOUND_API_KEY` (and every other secret) is genuinely present and
  correctly set — a missing/empty key is RULED OUT. Real root cause NOT
  YET INVESTIGATED. Per DEBUGGING_METHODOLOGY.md: next session needs to
  pull the real `shot_list` `sfx_cue` text for `ba5d96c8` from Supabase
  and either run `search_freesound_sfx()` against those exact real
  queries (if network access allows reaching freesound.org) or add
  temporary diagnostic logging to a real run to capture the actual
  Freesound API response/status code per cue. Don't guess at a cause
  without that.

**File to edit:** `scripts/video_generation.py` — remove the
`generate_background_music` call path in `build_audio_mix`, then
separately debug `search_freesound_sfx`.

---

## 6. Narration tone — NOT YET INVESTIGATED AT ALL

Zia: narration doesn't read as documentary/emotionally-emotive, feels
"horrible." Zero code investigation done this session. Next step: pull
the actual narration-generation prompt from `narration_stage.py`,
review its tone instructions, and rewrite toward a more documentary/
emotive style. No hypothesis yet on why current output reads poorly —
could be prompt wording, could be a Gemini-vs-prior-provider style
difference (narration moved from Groq back to Gemini on 2026-08-17),
could be something else. Needs a fresh read of the actual prompt before
proposing anything.

**File to check:** `scripts/narration_stage.py`

---

## EXECUTION ORDER for next session

1. **Confirm both in-flight workflow runs (Marius `video_generation.yml`,
   Nova `generate_videos.yml`) are finished.** Never push/edit a file
   while its pipeline might be mid-run.
2. Get Zia's decision on item 4 (quality/bitrate trade-off — A/B/C/D)
   before writing any bitrate/resolution code — this is the most
   consequential open decision in this doc.
3. Get Zia's explicit sign-off on item 3's static-reference-image
   approach before implementing — continuity chaining has caused two
   prior regressions (added 2026-07-31, removed 2026-08-18), so this
   needs deliberate confirmation, not silent action.
4. Push fixes ONE FILE AT A TIME, verifying each individually:
   a. `scripts/script_writing.py` — raise `MIN_SHOTS`/`MAX_SHOTS` (item 1)
   b. `scripts/video_generation.py` — anchor-suppression-by-default for
      named character (item 2)
   c. `scripts/video_generation.py` — resolution/bitrate change per
      Zia's item-4 decision
   d. `scripts/video_generation.py` — static reference image anchoring,
      IF Zia signs off (item 3)
   e. `scripts/video_generation.py` — remove music call entirely (item 5)
   f. `scripts/video_generation.py` — investigate + fix SFX silent
      failure with real query/response data (item 5)
   g. `scripts/narration_stage.py` — investigate + fix narration tone
      (item 6)
5. After ALL fixes above are pushed and independently verified (not just
   assumed), reset `ba5d96c8` (clear `video_urls`, set
   `video_next_index=0`, status back to `images_generated`) to fully
   regenerate under the fixed pipeline. **Do not reset it before the
   fixes land** — would just reproduce the same bad output and waste
   Agnes quota.
6. Zia is deciding separately whether to delete the current live
   `ba5d96c8` YouTube upload — not Claude's call, no action taken on
   YouTube this session or planned in this doc.
7. Update this file again at the end of that session, in place, per
   `DEBUGGING_STANDARDS.md`.

---

*Prior session history (2026-08-19 and earlier) trimmed from this file
to keep it usable — see git commit history on this file
(`git log -- CONTINUATION.md`) for full detail if needed. Summary: that
session fixed the 2026-08-17 shot-writing token-budget crisis (Groq→
Gemini switch) and found two shot-breakdown JSON/onscreen-text bugs in
`shot_breakdown_stage.py`, one fixed (trailing-comma repair), one scoped
but not pushed (blind-retry-without-context fix) — worth revisiting
separately from everything in this doc.*
