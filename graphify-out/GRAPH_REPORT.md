# Graph Report - marius-command-center  (2026-11-12)

## Corpus Check
- 50 files · ~77,615 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 639 nodes · 1412 edges · 27 communities (26 shown, 1 thin omitted)
- Extraction: 97% EXTRACTED · 3% INFERRED · 0% AMBIGUOUS · INFERRED: 42 edges (avg confidence: 0.94)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `0f9d0320`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- llm_client.py
- time
- kaggle_clips.py
- kernel.py
- shot_breakdown_stage.py
- stock_fallback.py
- build_agnes_prompt
- os
- narration.py
- requests
- clip_qa.py
- generate_codemap.py
- thumbnail_generation.py
- storage_b2.py
- Marius / Erased - Continuation Notes (2026-11-11 PART 6, NARRATION ORDER + NARRATION STORAGE + THROUGHPUT, read this section FIRST)
- Marius Command Center — Handoff Doc
- Marius Playbook (rarely changes — read alongside STATUS.md)
- HANDOFF 2026-10-25: Kaggle video fallback for Tiny Lawn Tales (repo adrian001234/upgraded-journey)
- Kaggle free-GPU video test: decision notes
- Debugging Methodology — Mandatory for Every AI Agent Working on Atlas Frame Pipelines
- Marius Command Center — AI Operating Standards
- REPO ACCESS RULE (set by Zia, 2026-10-25). READ THIS BEFORE ANY GITHUB ACTION.
- STATUS.md
- HANDOFF 2026-10-18: Free backup video generator (Agnes queue full)
- HANDOFF 2026-11-10 (end of session): Kaggle AI clips for Marius
- clip_generation.py
- HANDOFF 2026-11-11 (Marius only): Kaggle clips, where it stands

## God Nodes (most connected - your core abstractions)
1. `process_script()` - 27 edges
2. `retryable_request()` - 23 edges
3. `validate_and_normalize_shot_response()` - 23 edges
4. `generate_shot_clip()` - 21 edges
5. `make_stock_clip()` - 19 edges
6. `extract_json()` - 17 edges
7. `call_llm()` - 16 edges
8. `main()` - 15 edges
9. `run()` - 14 edges
10. `generate_narration()` - 14 edges

## Surprising Connections (you probably didn't know these)
- `Next steps` --references--> `AgnesOverloadedError`  [INFERRED]
  docs/kaggle-video-test-notes.md → scripts/agnes_client.py
- `2026-09-21 — Agnes create-task ReadTimeout crash fixed; declutter` --references--> `create_agnes_task()`  [INFERRED]
  docs/marius-handoff.md → scripts/agnes_client.py
- `What happened this session` --references--> `generate_narration()`  [INFERRED]
  CONTINUATION.md → scripts/narration_stage.py
- `NOT verified (check first, live)` --references--> `process_script()`  [INFERRED]
  HANDOFF_2026-11-10_KAGGLE_CLIPS.md → scripts/video_generation.py
- `Still open` --references--> `process_script()`  [INFERRED]
  HANDOFF_2026-11-11_KAGGLE_CLIPS.md → scripts/video_generation.py

## Import Cycles
- None detected.

## Communities (27 total, 1 thin omitted)

### Community 0 - "llm_client.py"
Cohesion: 0.07
Nodes (28): call_llm(), DailyQuotaExhausted, extract_json(), InfraFailure, _quote_unquoted_keys(), sanitize_json_control_chars(), _strip_trailing_commas(), build_narration_continuation_prompt() (+20 more)

### Community 1 - "time"
Cohesion: 0.11
Nodes (26): extract_url(), finish(), run(), upload_video(), extract_last_frame_url(), generate_character_reference(), get_continuity_anchor(), retryable_request() (+18 more)

### Community 2 - "kaggle_clips.py"
Cohesion: 0.10
Nodes (31): NOT verified, History this session, apply_beat_to_shot(), author_chain_beats(), _build_prompt(), _call_gemini_once(), _validate_beats(), assemble_if_complete() (+23 more)

### Community 3 - "kernel.py"
Cohesion: 0.11
Nodes (20): call(), free(), load(), make_shot(), run(), save(), seg_frames(), add_sound() (+12 more)

### Community 4 - "shot_breakdown_stage.py"
Cohesion: 0.07
Nodes (24): auto_repair_dominant_subject(), auto_repair_excessive_consecutive_subject(), auto_repair_location_change_without_establishing(), auto_repair_missing_onscreen_text(), build_shot_breakdown_chunk_prompt(), build_shot_breakdown_response_schema(), find_anachronistic_object_shots(), find_continuation_language_shots() (+16 more)

### Community 5 - "stock_fallback.py"
Cohesion: 0.12
Nodes (20): _concat(), configure_agnes_wait(), _download(), _ffmpeg(), _generic_queries(), is_enabled(), _keywords(), _loop_fill() (+12 more)

### Community 6 - "build_agnes_prompt"
Cohesion: 0.12
Nodes (15): 1. Done today (verified by commit), 2. Problems Zia reported on 2026-10-08 (all still OPEN), 3. Evidence gathered (Marius only), 4.1 Plan check: protagonist cap (planning stage), 4.2 Prompt fix: only describe the protagonist when the shot is about them, 4.3 Clip check: morphing and waxy-face detector (after each clip, before upload to B2), 4.4 Measure, 4. Build list (in this order) (+7 more)

### Community 7 - "os"
Cohesion: 0.09
Nodes (22): list_all_objects(), main(), check_generation_failed_backlog(), check_stale_scripts(), check_stuck_scripts(), hours_since(), main(), supabase_get() (+14 more)

### Community 8 - "narration.py"
Cohesion: 0.16
Nodes (10): _assign_shots_to_sentences(), main(), _max_plausible_duration(), _merge_short_segments(), narrate_one_script(), split_into_segments(), _synthesize_edge(), synthesize_per_sentence_with_shot_durations() (+2 more)

### Community 9 - "requests"
Cohesion: 0.11
Nodes (22): _fetch_script_ids(), _gb(), sweep(), _ask_gemini_for_titles(), lint(), optimize_title(), _words(), fetch_top_articles() (+14 more)

### Community 10 - "clip_qa.py"
Cohesion: 0.19
Nodes (10): check_clip(), enabled(), _extract_frames_b64(), _max_calls(), max_redo(), shot_needs_check(), focus_anchor(), protagonist_name() (+2 more)

### Community 11 - "generate_codemap.py"
Cohesion: 0.24
Nodes (8): build_codemap(), CallCollector, extract_env_vars(), extract_tables(), find_py_files(), get_docstring_first_line(), main(), process_file()

### Community 12 - "thumbnail_generation.py"
Cohesion: 0.15
Nodes (11): derive_hook_text(), download_video_frame(), fit_text_to_frame(), fits(), _line_bbox(), main(), overlay_hook_text(), push_thumbnail_to_youtube() (+3 more)

### Community 13 - "storage_b2.py"
Cohesion: 0.07
Nodes (24): What's CONFIRMED this session, main(), probe(), fetch_script_ids(), gb(), list_bucket(), main(), delete_built() (+16 more)

### Community 14 - "Marius / Erased - Continuation Notes (2026-11-11 PART 6, NARRATION ORDER + NARRATION STORAGE + THROUGHPUT, read this section FIRST)"
Cohesion: 0.07
Nodes (29): 2026-09-19 session — B2/Agnes fixes landed, throughput math checked, Agnes-replacement researched, Agnes-replacement research (requested by Ali — "generate video on a, Confirmed live (2026-11-11, about 21:10), Correction to PART 4 (important — do NOT delete these files), CURRENT STATE (as of handoff), Decisions waiting for Zia (free options only), Declutter done (2026-09-19, verified before deleting), Do not (+21 more)

### Community 15 - "Marius Command Center — Handoff Doc"
Cohesion: 0.17
Nodes (11): 2026-09-18/19 — Video generation stall, three independent root causes, 2026-09-19 — Trend grounding was completely dead since creation, 2026-09-21 — Agnes create-task ReadTimeout crash fixed; declutter, Current `scripts/` files (2026-09-21, confirmed live via a clone of `main`), Marius Command Center — Handoff Doc, Older history (pre-2026-09-18, unverified against current live state —, Pipeline, Session log (most recent first — keep this section, don't delete old (+3 more)

### Community 16 - "Marius Playbook (rarely changes — read alongside STATUS.md)"
Cohesion: 0.20
Nodes (9): Database (Supabase table "scripts"), Database (Supabase table "topics"), GitHub Actions secrets currently set, Known gotchas already solved - do not rediscover these, Marius Playbook (rarely changes — read alongside STATUS.md), Pipeline order, Remaining stages to build, Standing communication rules (+1 more)

### Community 17 - "HANDOFF 2026-10-25: Kaggle video fallback for Tiny Lawn Tales (repo adrian001234/upgraded-journey)"
Cohesion: 0.29
Nodes (6): Decision (Zia, 2026-10-25), HANDOFF 2026-10-25: Kaggle video fallback for Tiny Lawn Tales (repo adrian001234/upgraded-journey), Next steps (one at a time), Plan, Secrets, Verified live on 2026-10-25

### Community 18 - "Kaggle free-GPU video test: decision notes"
Cohesion: 0.29
Nodes (6): Decision, Kaggle free-GPU video test: decision notes, Next steps, Requirements and open points, Results, Where things are

### Community 19 - "Debugging Methodology — Mandatory for Every AI Agent Working on Atlas Frame Pipelines"
Cohesion: 0.33
Nodes (5): Debugging Methodology — Mandatory for Every AI Agent Working on Atlas Frame Pipelines, Standing priority, The process, in order, every time, The rule, stated plainly, What this looked like in practice (2026-08-18 Nova case study)

### Community 20 - "Marius Command Center — AI Operating Standards"
Cohesion: 0.40
Nodes (4): Before ending any session, Marius Command Center — AI Operating Standards, Standing behavioral rules, The three living docs in this repo — know the difference

### Community 21 - "REPO ACCESS RULE (set by Zia, 2026-10-25). READ THIS BEFORE ANY GITHUB ACTION."
Cohesion: 0.29
Nodes (6): Never touch these, for any reason, REPO ACCESS RULE (set by Zia, 2026-10-25). READ THIS BEFORE ANY GITHUB ACTION., Use only these repos, Voice-dictation garbles Zia uses, What this changes in practice, Why (verified against the GitHub API on 2026-10-25)

### Community 23 - "HANDOFF 2026-10-18: Free backup video generator (Agnes queue full)"
Cohesion: 0.29
Nodes (6): Chosen plan, HANDOFF 2026-10-18: Free backup video generator (Agnes queue full), Read this first (how to work with Zia), Research findings (searches only, limits not tested by us), Status / next steps, The problem

### Community 24 - "HANDOFF 2026-11-10 (end of session): Kaggle AI clips for Marius"
Cohesion: 0.33
Nodes (5): Files (all on main, compile-checked), HANDOFF 2026-11-10 (end of session): Kaggle AI clips for Marius, Next steps, in order, NOT verified (check first, live), Secrets (names only, Claude cannot read them)

### Community 26 - "clip_generation.py"
Cohesion: 0.07
Nodes (36): What was found and fixed (2026-09-21), What was learned this session, AgnesBadRequestError, AgnesOverloadedError, ContentPolicyRejection, create_agnes_task(), extract_video_url(), poll_agnes_task() (+28 more)

### Community 28 - "HANDOFF 2026-11-11 (Marius only): Kaggle clips, where it stands"
Cohesion: 0.25
Nodes (7): Fix in progress (this session), HANDOFF 2026-11-11 (Marius only): Kaggle clips, where it stands, Rules, State of repo (verified by direct read), Still open, What fails (live data, 2026-11-11), What works (proven)

## Knowledge Gaps
- **75 isolated node(s):** `NEXT PROFILE START HERE`, `What changed this session`, `Confirmed live (2026-11-11, about 21:10)`, `Why videos come out about once a week (arithmetic, NOT measured on Kaggle)`, `Do not` (+70 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 244 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **1 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `process_script()` connect `time` to `kernel.py`, `os`, `storage_b2.py`, `HANDOFF 2026-11-10 (end of session): Kaggle AI clips for Marius`, `clip_generation.py`, `HANDOFF 2026-11-11 (Marius only): Kaggle clips, where it stands`?**
  _High betweenness centrality (0.049) - this node is a cross-community bridge._
- **Are the 5 inferred relationships involving `process_script()` (e.g. with `NOT verified (check first, live)` and `Still open`) actually correct?**
  _`process_script()` has 5 INFERRED edges - model-reasoned connections that need verification._
- **What connects `NEXT PROFILE START HERE`, `What changed this session`, `Confirmed live (2026-11-11, about 21:10)` to the rest of the system?**
  _75 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `llm_client.py` be split into smaller, more focused modules?**
  _Cohesion score 0.07272727272727272 - nodes in this community are weakly interconnected._
- **Why does `build_agnes_prompt()` connect `build_agnes_prompt` to `kaggle_clips.py`, `clip_generation.py`?**
  _High betweenness centrality (0.038) - this node is a cross-community bridge._
- **Should `time` be split into smaller, more focused modules?**
  _Cohesion score 0.11336032388663968 - nodes in this community are weakly interconnected._
- **Why does `poll_agnes_task()` connect `clip_generation.py` to `requests`, `time`, `Marius / Erased - Continuation Notes (2026-11-11 PART 6, NARRATION ORDER + NARRATION STORAGE + THROUGHPUT, read this section FIRST)`, `Marius Command Center — Handoff Doc`?**
  _High betweenness centrality (0.034) - this node is a cross-community bridge._