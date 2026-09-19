# Marius / Erased — Chain Beats Handoff (2026-09-19)

**Standing rule: re-verify everything below against live GitHub/Supabase. Do not trust this doc at face value. Read alongside `CONTINUATION.md` (PART 2 = B2/throughput state) and `PLAYBOOK.md`.**

## Verified live on `main`

- Scene-by-scene rewrite of `clip_generation.py` broke the `assembly_stage.py` import; reverted (`79ecfd2`). `scene_director.py` removed (`4f56b08`). Chain-variation patch (`daaa60c`) reverted (`15009a0`).
- NEW `scripts/beat_director.py` (`7105ba4`): one fail-soft Gemini call per shot that needs chaining. Returns N beats (`action`, `camera_movement`, `shot_type`) or `None` on ANY failure. Bounded: 2 attempts x 45s, own call (not `llm_client.call_llm` retry loops), key via `x-goog-api-key` header.
- `scripts/clip_generation.py` (`397da0d`): `generate_shot_clip` calls `author_chain_beats` once before the chain loop; each chain segment gets `apply_beat_to_shot(shot, beat)`. `None` = old repeated-prompt behavior. Signatures unchanged.
- `.github/workflows/video_generation.yml`: `GEMINI_API_KEY` added to the "Run video generation" env (committed by Zia, verified by re-fetch). Secret exists at repo level (listed in `PLAYBOOK.md`, used by `script_writing.py`).
- Connector write: 403 on `.github/workflows/*` (Zia must commit those); OK on `scripts/*` and docs.

## Tests actually run (sandbox, mocked Agnes/moviepy)

- Both live files pass `py_compile`.
- 20s shot, beats present: segments get `ORIG/static`, `B1/orbit`, `B2/tilt_up` (durations 7/7/6).
- 20s shot, `beat_director` returns `None`: all three segments get `ORIG/static` = identical to pre-change behavior.
- `beat_director` validation: bad enum coerced, consecutive same camera changed, wrong count/modern-object word -> `None`, missing key -> `None`.

## NOT verified

- No live Video Generation run since these changes. Next run: look for `[beat_director] authored N chain beat(s)` vs `falling back` in the log; confirm chained shots visibly differ.
- Premise is a HYPOTHESIS: that identical repeated prompts are why long shots look like a looped moment. Not proven from real output. Judge by the next real clip.
- Beats are LLM-authored and not checked against `narration_excerpt`; a beat could drift from the narration.
- Supabase: use project `iwgocbiqjjhlvkygmcir` (live, newest script/topic rows dated 2026-09-19). `PLAYBOOK.md` previously listed `swnjzzejsuupecdgbzzf`, which this connector cannot access; treat as stale unless proven otherwise.
- Supabase at 2026-09-19: `acf67e3b` and `41fd7031` at `video_next_index = 1`; other recent scripts at 0.
