# Graph Report - marius-command-center  (2026-11-10)

## Corpus Check
- 49 files · ~74,924 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 618 nodes · 1381 edges · 28 communities (26 shown, 2 thin omitted)
- Extraction: 97% EXTRACTED · 3% INFERRED · 0% AMBIGUOUS · INFERRED: 38 edges (avg confidence: 0.94)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `9258cb07`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- narration_stage.py
- clip_generation.py
- kaggle_clips.py
- json
- shot_breakdown_stage.py
- stock_fallback.py
- HANDOFF 2026-11-10 (end of session): Kaggle AI clips for Marius
- os
- narration.py
- requests
- thumbnail_generation.py
- time
- re
- storage_b2.py
- Marius / Erased — Continuation Notes (2026-09-21 PART 5, AGNES CREATE-TIMEOUT FIX + PART 4 CORRECTION, read this section FIRST)
- Marius Command Center — Handoff Doc
- Marius Playbook (rarely changes — read alongside STATUS.md)
- HANDOFF 2026-10-25: Kaggle video fallback for Tiny Lawn Tales (repo adrian001234/upgraded-journey)
- Kaggle free-GPU video test: decision notes
- Debugging Methodology — Mandatory for Every AI Agent Working on Atlas Frame Pipelines
- Marius Command Center — AI Operating Standards
- REPO ACCESS RULE (set by Zia, 2026-10-25). READ THIS BEFORE ANY GITHUB ACTION.
- STATUS.md
- call_llm
- script_writing.py
- llm_client.py
- HANDOFF 2026-10-18: Free backup video generator (Agnes queue full)
- build_shot_breakdown_response_schema

## God Nodes (most connected - your core abstractions)
1. `process_script()` - 26 edges
2. `retryable_request()` - 23 edges
3. `validate_and_normalize_shot_response()` - 23 edges
4. `generate_shot_clip()` - 21 edges
5. `make_stock_clip()` - 19 edges
6. `extract_json()` - 17 edges
7. `call_llm()` - 16 edges
8. `main()` - 15 edges
9. `generate_narration()` - 14 edges
10. `push_batch()` - 13 edges

## Surprising Connections (you probably didn't know these)
- `Next steps` --references--> `AgnesOverloadedError`  [INFERRED]
  docs/kaggle-video-test-notes.md → scripts/agnes_client.py
- `2026-09-21 — Agnes create-task ReadTimeout crash fixed; declutter` --references--> `create_agnes_task()`  [INFERRED]
  docs/marius-handoff.md → scripts/agnes_client.py
- `What happened this session` --references--> `generate_narration()`  [INFERRED]
  CONTINUATION.md → scripts/narration_stage.py
- `NOT verified (check first, live)` --references--> `process_script()`  [INFERRED]
  HANDOFF_2026-11-10_KAGGLE_CLIPS.md → scripts/video_generation.py
- `EXACT NEXT STEPS for whoever picks this up` --references--> `poll_agnes_task()`  [INFERRED]
  CONTINUATION.md → scripts/agnes_client.py

## Import Cycles
- None detected.

## Communities (28 total, 2 thin omitted)

### Community 0 - "narration_stage.py"
Cohesion: 0.24
Nodes (6): InfraFailure, build_narration_continuation_prompt(), build_narration_prompt(), generate_narration(), narration_has_engagement_cta(), grade_narration()

### Community 1 - "clip_generation.py"
Cohesion: 0.06
Nodes (41): What was found and fixed (2026-09-21), AgnesBadRequestError, AgnesOverloadedError, ContentPolicyRejection, create_agnes_task(), extract_video_url(), poll_agnes_task(), round_to_valid_frames() (+33 more)

### Community 2 - "kaggle_clips.py"
Cohesion: 0.07
Nodes (38): History this session, apply_beat_to_shot(), author_chain_beats(), _build_prompt(), _call_gemini_once(), _validate_beats(), check_clip(), enabled() (+30 more)

### Community 3 - "json"
Cohesion: 0.12
Nodes (18): call(), free(), load(), make_shot(), save(), seg_frames(), add_sound(), call() (+10 more)

### Community 4 - "shot_breakdown_stage.py"
Cohesion: 0.09
Nodes (21): auto_repair_dominant_subject(), auto_repair_excessive_consecutive_subject(), auto_repair_location_change_without_establishing(), auto_repair_missing_onscreen_text(), find_anachronistic_object_shots(), find_continuation_language_shots(), find_dominant_subject(), find_duplicate_character_shots() (+13 more)

### Community 5 - "stock_fallback.py"
Cohesion: 0.11
Nodes (21): run(), _concat(), configure_agnes_wait(), _download(), _ffmpeg(), _generic_queries(), is_enabled(), _keywords() (+13 more)

### Community 6 - "HANDOFF 2026-11-10 (end of session): Kaggle AI clips for Marius"
Cohesion: 0.33
Nodes (5): Files (all on main, compile-checked), HANDOFF 2026-11-10 (end of session): Kaggle AI clips for Marius, Next steps, in order, NOT verified (check first, live), Secrets (names only, Claude cannot read them)

### Community 7 - "os"
Cohesion: 0.07
Nodes (25): extract_url(), finish(), run(), list_all_objects(), main(), check_generation_failed_backlog(), check_stale_scripts(), check_stuck_scripts() (+17 more)

### Community 8 - "narration.py"
Cohesion: 0.16
Nodes (10): _assign_shots_to_sentences(), main(), _max_plausible_duration(), _merge_short_segments(), narrate_one_script(), split_into_segments(), _synthesize_edge(), synthesize_per_sentence_with_shot_durations() (+2 more)

### Community 9 - "requests"
Cohesion: 0.10
Nodes (25): _fetch_script_ids(), _gb(), sweep(), collect_approved_topics(), generate_topic_candidates(), get_existing_titles(), get_recent_trend_signals(), grade_topic_candidates() (+17 more)

### Community 10 - "thumbnail_generation.py"
Cohesion: 0.15
Nodes (11): derive_hook_text(), download_video_frame(), fit_text_to_frame(), fits(), _line_bbox(), main(), overlay_hook_text(), push_thumbnail_to_youtube() (+3 more)

### Community 11 - "time"
Cohesion: 0.13
Nodes (22): upload_video(), load(), retryable_request(), upload_file(), clear_error(), compute_shot_durations(), download_file(), get_ready_scripts() (+14 more)

### Community 12 - "re"
Cohesion: 0.07
Nodes (26): build_codemap(), CallCollector, extract_env_vars(), extract_tables(), find_py_files(), get_docstring_first_line(), main(), process_file() (+18 more)

### Community 13 - "storage_b2.py"
Cohesion: 0.06
Nodes (28): 2026-09-19 session — B2/Agnes fixes landed, throughput math checked, Agnes-replacement researched, Agnes-replacement research (requested by Ali — "generate video on a, CURRENT STATE (as of handoff), EXACT NEXT STEPS for whoever picks this up, Marius / Erased — Continuation Notes (2026-09-19 PART 1, THROUGHPUT + AGNES-REPLACEMENT SESSION), Marius / Erased — Continuation Notes (2026-09-19 PART 2, LIVE HANDOFF), What's CONFIRMED this session, WHY this matters — the live open question at handoff (+20 more)

### Community 14 - "Marius / Erased — Continuation Notes (2026-09-21 PART 5, AGNES CREATE-TIMEOUT FIX + PART 4 CORRECTION, read this section FIRST)"
Cohesion: 0.13
Nodes (14): Correction to PART 4 (important — do NOT delete these files), Declutter done (2026-09-19, verified before deleting), EXACT NEXT STEPS, EXACT NEXT STEPS for whoever picks this up, Marius / Erased — Continuation Notes (2026-09-19 PART 3, CHAIN BEATS — read this section FIRST), Marius / Erased — Continuation Notes (2026-09-19 PART 4, SKILLS + DECLUTTER, read this section FIRST), Marius / Erased — Continuation Notes (2026-09-21 PART 5, AGNES CREATE-TIMEOUT FIX + PART 4 CORRECTION, read this section FIRST), NOT verified (+6 more)

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

### Community 23 - "call_llm"
Cohesion: 0.19
Nodes (7): call_llm(), DailyQuotaExhausted, grade_shot_breakdown(), _run_grader(), build_shot_breakdown_chunk_prompt(), generate_shot_breakdown(), split_narration_into_chunks()

### Community 24 - "script_writing.py"
Cohesion: 0.24
Nodes (6): generate_script(), get_pending_topics(), main(), mark_topic_generation_failed(), mark_topic_scripted(), save_script()

### Community 25 - "llm_client.py"
Cohesion: 0.31
Nodes (4): extract_json(), _quote_unquoted_keys(), sanitize_json_control_chars(), _strip_trailing_commas()

### Community 26 - "HANDOFF 2026-10-18: Free backup video generator (Agnes queue full)"
Cohesion: 0.25
Nodes (7): Chosen plan, HANDOFF 2026-10-18: Free backup video generator (Agnes queue full), Read this first (how to work with Zia), Research findings (searches only, limits not tested by us), Status / next steps, The problem, What was learned this session

## Knowledge Gaps
- **64 isolated node(s):** `Standing role (from Zia, 2026-09-21)`, `Correction to PART 4 (important — do NOT delete these files)`, `Declutter done (2026-09-19, verified before deleting)`, `NOT verified`, `EXACT NEXT STEPS` (+59 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 230 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **2 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `build_agnes_prompt()` connect `re` to `clip_generation.py`, `kaggle_clips.py`?**
  _High betweenness centrality (0.039) - this node is a cross-community bridge._
- **Are the 4 inferred relationships involving `process_script()` (e.g. with `NOT verified (check first, live)` and `AgnesBadRequestError`) actually correct?**
  _`process_script()` has 4 INFERRED edges - model-reasoned connections that need verification._
- **What connects `Standing role (from Zia, 2026-09-21)`, `Correction to PART 4 (important — do NOT delete these files)`, `Declutter done (2026-09-19, verified before deleting)` to the rest of the system?**
  _64 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `clip_generation.py` be split into smaller, more focused modules?**
  _Cohesion score 0.06394230769230769 - nodes in this community are weakly interconnected._
- **Why does `poll_agnes_task()` connect `clip_generation.py` to `requests`, `time`, `storage_b2.py`, `Marius Command Center — Handoff Doc`?**
  _High betweenness centrality (0.036) - this node is a cross-community bridge._
- **Should `kaggle_clips.py` be split into smaller, more focused modules?**
  _Cohesion score 0.07259528130671507 - nodes in this community are weakly interconnected._
- **Why does `retryable_request()` connect `time` to `script_writing.py`, `llm_client.py`, `kaggle_clips.py`, `requests`?**
  _High betweenness centrality (0.033) - this node is a cross-community bridge._