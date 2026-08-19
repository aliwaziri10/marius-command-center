# Marius / Erased — Continuation Notes (2026-08-19)

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
`STATUS.md` (auto-updated, reliable) shows 3 scripts currently stuck at
`images_generated` with 0 clips as of 2026-08-19 09:16 UTC. Separate from
the script-writing issues above - worth a look next session.

## NEXT STEP
1. Implement and push the blind-retry fix in `shot_breakdown_stage.py`
   (thread `last_reason` into the next content-attempt's prompt as
   corrective guidance) - scoped, not yet done.
2. Trigger a real run afterward and read the new `extract_json` diagnostic
   log output to confirm or refute the trailing-comma hypothesis before
   writing it up as a fixed root cause anywhere.
3. Separately: check the 3 scripts stuck at `images_generated`/0 clips.
