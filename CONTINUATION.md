# Marius / Erased — Continuation Notes (2026-08-06)

## Where things stand
- Narration (Chatterbox-TTS rewrite from Aug 3) is confirmed working live in Supabase.
- video_generation.py is currently the bottleneck: 2 scripts at 0 shots generated, 1 stuck at 38/70 shots — likely the known unfixed Agnes ~7s/169-frame freeze-loop cap. Not yet worked on.

## Root-caused bug: lighthouse video
Live video "The Lighthouse Keeper of Sable Island" (YouTube ID Tz2Q52A8YC8, script id 9e7857f0) plays as a ~2min frozen/repetitive loop.
Root cause: narration_text was only ~320 words (target 1200-1500), only 10 real shots existed, and script_writing.py's validator padded the required 60-shot minimum by repeating that same 10-shot block 6x verbatim. The old empty-shot check didn't catch it because duplicated shots aren't empty, just repeated.
Audited all 41 other scripts — this is the only one with severe duplication (2 others had one harmless single-shot repeat).
Decision: leave the live video up as-is rather than delete/replace it, until the fix below is deployed and proven.

## Fix — NOT YET PUSHED (blocked)
Add to scripts/script_writing.py, inside validate_and_normalize() (same reject-and-retry pattern as the existing CTA/hook checks):
- MIN_NARRATION_WORDS = 900 — hard-reject narration_text under 900 words
- find_duplicate_shots() — hard-reject any (visual_description, narration_excerpt) shot pair repeated more than 2 times
Also update the generation prompt text to explicitly forbid short narration and shot repetition.

BLOCKER: GitHub write access to aliwaziri10/marius-command-center is returning
403 "Resource not accessible by integration" on every write (create_or_update_file
and push_files both fail identically; even a trivial write-test.txt edit fails).
Reads work fine — this is a connector permission issue, not a code issue.

FIX FOR THE BLOCKER (Zia to do): grant "Contents: Read and write" to the GitHub
connector/App for this specific repo, then have the next session push the fix
above immediately — no further debugging needed.
