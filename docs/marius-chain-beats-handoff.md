# Marius / Erased — Continuation Notes (2026-09-19 PART 3, CHAIN BEATS — read this section FIRST)

**Standing rule: re-verify everything below against live GitHub/Supabase. Do not trust this doc at face value.**

## Verified live on `main` (2026-09-19)

- Scene-by-scene rewrite of `clip_generation.py` broke the `assembly_stage.py` import; reverted (commit `79ecfd2`). `scene_director.py` removed (`4f56b08`). Chain-variation patch (`daaa60c`) reverted (`15009a0`). `clip_generation.py` was clean pre-change.
- NEW `scripts/beat_director.py` (commit `7105ba4`): one fail-soft Gemini call per shot that needs chaining. Returns N beats (`action`, `camera_movement`, `shot_type`) or `None` on ANY failure. Bounded: 2 attempts x 45s, uses its own call (not `llm_client.call_llm` retry loops), key sent via `x-goog-api-key` header.
- `scripts/clip_generation.py` (commit `397da0d`): `generate_shot_clip` calls `author_chain_beats` once before the chain loop and passes `apply_beat_to_shot(shot, beat)` to each chain segment. `None` = old repeated-prompt behavior. Function signatures unchanged (`assembly_stage.py` untouched).
- `.github/workflows/video_generation.yml`: `GEMINI_API_KEY: ${{ secrets.GEMINI_API_KEY }}` added to the "Run video generation" env (committed by Zia, verified by re-fetch). Repo-level secret existence proven earlier via `script_writing.py`'s workflow.
- GitHub write via connector: 403 on `.github/workflows/*` (needs Zia to commit); OK on `scripts/*` and docs.

## NOT yet verified

- No live Video Generation run has happened since these changes. Next run: look for `[beat_director] authored N chain beat(s)` vs `falling back` in the log, and confirm chained shots visibly differ.
- Supabase (`iwgocbiqjjhlvkygmcir`) at 2026-09-19: only `acf67e3b` and `41fd7031` show `video_next_index = 1`; the other recent scripts are at 0.

---

