# Graph Report - marius-command-center  (2026-10-25)

## Corpus Check
- 42 files · ~68,857 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 547 nodes · 1188 edges · 22 communities (21 shown, 1 thin omitted)
- Extraction: 97% EXTRACTED · 3% INFERRED · 0% AMBIGUOUS · INFERRED: 36 edges (avg confidence: 0.94)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `a0c3a323`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- llm_client.py
- clip_generation.py
- assembly_stage.py
- kernel.py
- shot_breakdown_stage.py
- stock_fallback.py
- video_generation.py
- os
- narration.py
- requests
- thumbnail_generation.py
- generate_codemap.py
- HANDOFF 2026-10-08: visual quality, narration pacing, YouTube Agent Skill ports
- storage_b2.py
- Marius / Erased — Continuation Notes (2026-09-21 PART 5, AGNES CREATE-TIMEOUT FIX + PART 4 CORRECTION, read this section FIRST)
- Marius Command Center — Handoff Doc
- Marius Playbook (rarely changes — read alongside STATUS.md)
- clip_qa.py
- Kaggle free-GPU video test: decision notes
- Debugging Methodology — Mandatory for Every AI Agent Working on Atlas Frame Pipelines
- Marius Command Center — AI Operating Standards
- STATUS.md

## God Nodes (most connected - your core abstractions)
1. `process_script()` - 25 edges
2. `validate_and_normalize_shot_response()` - 23 edges
3. `generate_shot_clip()` - 21 edges
4. `make_stock_clip()` - 19 edges
5. `retryable_request()` - 18 edges
6. `extract_json()` - 17 edges
7. `call_llm()` - 16 edges
8. `generate_narration()` - 14 edges
9. `main()` - 14 edges
10. `generate_shot_breakdown()` - 13 edges

## Surprising Connections (you probably didn't know these)
- `Next steps` --references--> `AgnesOverloadedError`  [INFERRED]
  docs/kaggle-video-test-notes.md → scripts/agnes_client.py
- `2026-09-21 — Agnes create-task ReadTimeout crash fixed; declutter` --references--> `create_agnes_task()`  [INFERRED]
  docs/marius-handoff.md → scripts/agnes_client.py
- `What happened this session` --references--> `generate_narration()`  [INFERRED]
  CONTINUATION.md → scripts/narration_stage.py
- `3. Evidence gathered (Marius only)` --references--> `build_agnes_prompt()`  [INFERRED]
  HANDOFF_2026-10-08_VISUAL_QUALITY_AND_YT_SKILLS.md → scripts/prompt_builder.py
- `EXACT NEXT STEPS for whoever picks this up` --references--> `poll_agnes_task()`  [INFERRED]
  CONTINUATION.md → scripts/agnes_client.py

## Import Cycles
- None detected.

## Communities (22 total, 1 thin omitted)

### Community 0 - "llm_client.py"
Cohesion: 0.07
Nodes (26): call_llm(), DailyQuotaExhausted, extract_json(), InfraFailure, _quote_unquoted_keys(), sanitize_json_control_chars(), _strip_trailing_commas(), build_narration_continuation_prompt() (+18 more)

### Community 1 - "clip_generation.py"
Cohesion: 0.09
Nodes (29): Marius / Erased — Continuation Notes (2026-09-19 PART 3, CHAIN BEATS — read this section FIRST), NOT verified, Tests run (sandbox, mocked Agnes/moviepy), Verified live on `main` (2026-09-19), What was found and fixed (2026-09-21), 4.2 Prompt fix: only describe the protagonist when the shot is about them, AgnesBadRequestError, AgnesOverloadedError (+21 more)

### Community 2 - "assembly_stage.py"
Cohesion: 0.08
Nodes (27): Chosen plan, HANDOFF 2026-10-18: Free backup video generator (Agnes queue full), Read this first (how to work with Zia), Research findings (searches only, limits not tested by us), Status / next steps, The problem, What was learned this session, apply_safety_limiter() (+19 more)

### Community 3 - "kernel.py"
Cohesion: 0.08
Nodes (20): add_sound(), call(), ff(), free(), has_audio(), load_mimsi(), log(), make_effect() (+12 more)

### Community 4 - "shot_breakdown_stage.py"
Cohesion: 0.07
Nodes (26): grade_shot_breakdown(), auto_repair_dominant_subject(), auto_repair_excessive_consecutive_subject(), auto_repair_location_change_without_establishing(), auto_repair_missing_onscreen_text(), build_shot_breakdown_chunk_prompt(), build_shot_breakdown_response_schema(), find_anachronistic_object_shots() (+18 more)

### Community 5 - "stock_fallback.py"
Cohesion: 0.12
Nodes (20): _concat(), configure_agnes_wait(), _download(), _ffmpeg(), _generic_queries(), is_enabled(), _keywords(), _loop_fill() (+12 more)

### Community 6 - "video_generation.py"
Cohesion: 0.12
Nodes (25): upload_video(), extract_last_frame_url(), get_continuity_anchor(), upload_reference_image(), load(), retryable_request(), upload_file(), clear_error() (+17 more)

### Community 7 - "os"
Cohesion: 0.13
Nodes (14): list_all_objects(), main(), check_generation_failed_backlog(), check_stale_scripts(), check_stuck_scripts(), hours_since(), main(), supabase_get() (+6 more)

### Community 8 - "narration.py"
Cohesion: 0.16
Nodes (10): _assign_shots_to_sentences(), main(), _max_plausible_duration(), _merge_short_segments(), narrate_one_script(), split_into_segments(), _synthesize_edge(), synthesize_per_sentence_with_shot_durations() (+2 more)

### Community 9 - "requests"
Cohesion: 0.13
Nodes (19): _ask_gemini_for_titles(), lint(), optimize_title(), _words(), fetch_top_articles(), main(), save_signal(), build_description() (+11 more)

### Community 10 - "thumbnail_generation.py"
Cohesion: 0.13
Nodes (11): derive_hook_text(), download_video_frame(), fit_text_to_frame(), fits(), _line_bbox(), main(), overlay_hook_text(), push_thumbnail_to_youtube() (+3 more)

### Community 11 - "generate_codemap.py"
Cohesion: 0.24
Nodes (8): build_codemap(), CallCollector, extract_env_vars(), extract_tables(), find_py_files(), get_docstring_first_line(), main(), process_file()

### Community 12 - "HANDOFF 2026-10-08: visual quality, narration pacing, YouTube Agent Skill ports"
Cohesion: 0.18
Nodes (10): 1. Done today (verified by commit), 2. Problems Zia reported on 2026-10-08 (all still OPEN), 3. Evidence gathered (Marius only), 4.1 Plan check: protagonist cap (planning stage), 4.3 Clip check: morphing and waxy-face detector (after each clip, before upload to B2), 4.4 Measure, 4. Build list (in this order), 5. YouTube Agent Skill: what to take (+2 more)

### Community 13 - "storage_b2.py"
Cohesion: 0.07
Nodes (25): 2026-09-19 session — B2/Agnes fixes landed, throughput math checked, Agnes-replacement researched, Agnes-replacement research (requested by Ali — "generate video on a, EXACT NEXT STEPS for whoever picks this up, Marius / Erased — Continuation Notes (2026-09-19 PART 1, THROUGHPUT + AGNES-REPLACEMENT SESSION), What's CONFIRMED this session, main(), probe(), fetch_script_ids() (+17 more)

### Community 14 - "Marius / Erased — Continuation Notes (2026-09-21 PART 5, AGNES CREATE-TIMEOUT FIX + PART 4 CORRECTION, read this section FIRST)"
Cohesion: 0.14
Nodes (13): Correction to PART 4 (important — do NOT delete these files), CURRENT STATE (as of handoff), Declutter done (2026-09-19, verified before deleting), EXACT NEXT STEPS, EXACT NEXT STEPS for whoever picks this up, Marius / Erased — Continuation Notes (2026-09-19 PART 2, LIVE HANDOFF), Marius / Erased — Continuation Notes (2026-09-19 PART 4, SKILLS + DECLUTTER, read this section FIRST), Marius / Erased — Continuation Notes (2026-09-21 PART 5, AGNES CREATE-TIMEOUT FIX + PART 4 CORRECTION, read this section FIRST) (+5 more)

### Community 15 - "Marius Command Center — Handoff Doc"
Cohesion: 0.17
Nodes (11): 2026-09-18/19 — Video generation stall, three independent root causes, 2026-09-19 — Trend grounding was completely dead since creation, 2026-09-21 — Agnes create-task ReadTimeout crash fixed; declutter, Current `scripts/` files (2026-09-21, confirmed live via a clone of `main`), Marius Command Center — Handoff Doc, Older history (pre-2026-09-18, unverified against current live state —, Pipeline, Session log (most recent first — keep this section, don't delete old (+3 more)

### Community 16 - "Marius Playbook (rarely changes — read alongside STATUS.md)"
Cohesion: 0.20
Nodes (9): Database (Supabase table "scripts"), Database (Supabase table "topics"), GitHub Actions secrets currently set, Known gotchas already solved - do not rediscover these, Marius Playbook (rarely changes — read alongside STATUS.md), Pipeline order, Remaining stages to build, Standing communication rules (+1 more)

### Community 17 - "clip_qa.py"
Cohesion: 0.17
Nodes (11): check_clip(), enabled(), _extract_frames_b64(), _max_calls(), max_redo(), shot_needs_check(), focus_anchor(), no_people_clause() (+3 more)

### Community 18 - "Kaggle free-GPU video test: decision notes"
Cohesion: 0.33
Nodes (5): Decision, Kaggle free-GPU video test: decision notes, Next steps, Requirements and open points, Where things are

### Community 19 - "Debugging Methodology — Mandatory for Every AI Agent Working on Atlas Frame Pipelines"
Cohesion: 0.33
Nodes (5): Debugging Methodology — Mandatory for Every AI Agent Working on Atlas Frame Pipelines, Standing priority, The process, in order, every time, The rule, stated plainly, What this looked like in practice (2026-08-18 Nova case study)

### Community 20 - "Marius Command Center — AI Operating Standards"
Cohesion: 0.40
Nodes (4): Before ending any session, Marius Command Center — AI Operating Standards, Standing behavioral rules, The three living docs in this repo — know the difference

## Knowledge Gaps
- **49 isolated node(s):** `Standing role (from Zia, 2026-09-21)`, `Correction to PART 4 (important — do NOT delete these files)`, `Declutter done (2026-09-19, verified before deleting)`, `NOT verified`, `EXACT NEXT STEPS` (+44 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 207 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **1 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `build_agnes_prompt()` connect `clip_generation.py` to `HANDOFF 2026-10-08: visual quality, narration pacing, YouTube Agent Skill ports`?**
  _High betweenness centrality (0.040) - this node is a cross-community bridge._
- **Are the 3 inferred relationships involving `process_script()` (e.g. with `AgnesBadRequestError` and `AgnesOverloadedError`) actually correct?**
  _`process_script()` has 3 INFERRED edges - model-reasoned connections that need verification._
- **What connects `Standing role (from Zia, 2026-09-21)`, `Correction to PART 4 (important — do NOT delete these files)`, `Declutter done (2026-09-19, verified before deleting)` to the rest of the system?**
  _49 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `llm_client.py` be split into smaller, more focused modules?**
  _Cohesion score 0.07402031930333818 - nodes in this community are weakly interconnected._
- **Why does `call_llm()` connect `llm_client.py` to `clip_generation.py`, `kernel.py`, `shot_breakdown_stage.py`, `video_generation.py`, `requests`?**
  _High betweenness centrality (0.039) - this node is a cross-community bridge._
- **Should `clip_generation.py` be split into smaller, more focused modules?**
  _Cohesion score 0.0851063829787234 - nodes in this community are weakly interconnected._
- **Why does `poll_agnes_task()` connect `clip_generation.py` to `requests`, `storage_b2.py`, `video_generation.py`, `Marius Command Center — Handoff Doc`?**
  _High betweenness centrality (0.038) - this node is a cross-community bridge._