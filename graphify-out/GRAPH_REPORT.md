# Graph Report - marius-command-center  (2026-10-25)

## Corpus Check
- 42 files · ~68,242 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 537 nodes · 1168 edges · 23 communities (22 shown, 1 thin omitted)
- Extraction: 97% EXTRACTED · 3% INFERRED · 0% AMBIGUOUS · INFERRED: 36 edges (avg confidence: 0.94)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `bcf3ba21`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- b2_preflight.py
- clip_generation.py
- assembly_stage.py
- time
- shot_breakdown_stage.py
- os
- video_generation.py
- json
- narration.py
- requests
- thumbnail_generation.py
- generate_codemap.py
- re
- storage_b2.py
- Marius / Erased — Continuation Notes (2026-09-21 PART 5, AGNES CREATE-TIMEOUT FIX + PART 4 CORRECTION, read this section FIRST)
- Marius Command Center — Handoff Doc
- Marius Playbook (rarely changes — read alongside STATUS.md)
- clip_qa.py
- upload_bytes
- Debugging Methodology — Mandatory for Every AI Agent Working on Atlas Frame Pipelines
- Marius Command Center — AI Operating Standards
- _get_client
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
- `What happened this session` --references--> `generate_narration()`  [INFERRED]
  CONTINUATION.md → scripts/narration_stage.py
- `Next steps` --references--> `AgnesOverloadedError`  [INFERRED]
  docs/kaggle-video-test-notes.md → scripts/agnes_client.py
- `2026-09-21 — Agnes create-task ReadTimeout crash fixed; declutter` --references--> `create_agnes_task()`  [INFERRED]
  docs/marius-handoff.md → scripts/agnes_client.py
- `EXACT NEXT STEPS for whoever picks this up` --references--> `poll_agnes_task()`  [INFERRED]
  CONTINUATION.md → scripts/agnes_client.py
- `What was learned this session` --references--> `_generate_one_segment_raw()`  [INFERRED]
  HANDOFF_2026-10-18_FREE_VIDEO_FALLBACK.md → scripts/clip_generation.py

## Import Cycles
- None detected.

## Communities (23 total, 1 thin omitted)

### Community 0 - "b2_preflight.py"
Cohesion: 0.25
Nodes (4): main(), probe(), delete_built(), delete_object()

### Community 1 - "clip_generation.py"
Cohesion: 0.10
Nodes (27): What was found and fixed (2026-09-21), Decision, Kaggle free-GPU video test: decision notes, Next steps, Requirements and open points, Where things are, 2026-09-18/19 — Video generation stall, three independent root causes, 2026-09-19 — Trend grounding was completely dead since creation (+19 more)

### Community 2 - "assembly_stage.py"
Cohesion: 0.08
Nodes (27): Chosen plan, HANDOFF 2026-10-18: Free backup video generator (Agnes queue full), Read this first (how to work with Zia), Research findings (searches only, limits not tested by us), Status / next steps, The problem, What was learned this session, apply_safety_limiter() (+19 more)

### Community 3 - "time"
Cohesion: 0.11
Nodes (16): Marius / Erased — Continuation Notes (2026-09-19 PART 3, CHAIN BEATS — read this section FIRST), NOT verified, Tests run (sandbox, mocked Agnes/moviepy), Verified live on `main` (2026-09-19), apply_beat_to_shot(), author_chain_beats(), _build_prompt(), _call_gemini_once() (+8 more)

### Community 4 - "shot_breakdown_stage.py"
Cohesion: 0.05
Nodes (39): call_llm(), DailyQuotaExhausted, extract_json(), InfraFailure, _quote_unquoted_keys(), sanitize_json_control_chars(), _strip_trailing_commas(), build_narration_continuation_prompt() (+31 more)

### Community 5 - "os"
Cohesion: 0.12
Nodes (22): _derive_seed(), generate_shot_clip(), _concat(), configure_agnes_wait(), _download(), _ffmpeg(), _generic_queries(), is_enabled() (+14 more)

### Community 6 - "video_generation.py"
Cohesion: 0.09
Nodes (28): WHY this matters — the live open question at handoff, upload_video(), retryable_request(), generate_script(), get_pending_topics(), main(), mark_topic_generation_failed(), mark_topic_scripted() (+20 more)

### Community 7 - "json"
Cohesion: 0.08
Nodes (22): list_all_objects(), main(), check_generation_failed_backlog(), check_stale_scripts(), check_stuck_scripts(), hours_since(), main(), supabase_get() (+14 more)

### Community 8 - "narration.py"
Cohesion: 0.16
Nodes (10): _assign_shots_to_sentences(), main(), _max_plausible_duration(), _merge_short_segments(), narrate_one_script(), split_into_segments(), _synthesize_edge(), synthesize_per_sentence_with_shot_durations() (+2 more)

### Community 9 - "requests"
Cohesion: 0.11
Nodes (22): collect_approved_topics(), generate_topic_candidates(), get_existing_titles(), get_recent_trend_signals(), grade_topic_candidates(), main(), save_topic(), fetch_top_articles() (+14 more)

### Community 10 - "thumbnail_generation.py"
Cohesion: 0.15
Nodes (11): derive_hook_text(), download_video_frame(), fit_text_to_frame(), fits(), _line_bbox(), main(), overlay_hook_text(), push_thumbnail_to_youtube() (+3 more)

### Community 11 - "generate_codemap.py"
Cohesion: 0.24
Nodes (8): build_codemap(), CallCollector, extract_env_vars(), extract_tables(), find_py_files(), get_docstring_first_line(), main(), process_file()

### Community 12 - "re"
Cohesion: 0.11
Nodes (18): 1. Done today (verified by commit), 2. Problems Zia reported on 2026-10-08 (all still OPEN), 3. Evidence gathered (Marius only), 4.1 Plan check: protagonist cap (planning stage), 4.2 Prompt fix: only describe the protagonist when the shot is about them, 4.3 Clip check: morphing and waxy-face detector (after each clip, before upload to B2), 4.4 Measure, 4. Build list (in this order) (+10 more)

### Community 13 - "storage_b2.py"
Cohesion: 0.15
Nodes (6): download_to_file(), object_size(), _presign_clients(), _presign_config(), _region_from_endpoint(), _url_is_fetchable()

### Community 14 - "Marius / Erased — Continuation Notes (2026-09-21 PART 5, AGNES CREATE-TIMEOUT FIX + PART 4 CORRECTION, read this section FIRST)"
Cohesion: 0.13
Nodes (14): Correction to PART 4 (important — do NOT delete these files), CURRENT STATE (as of handoff), Declutter done (2026-09-19, verified before deleting), EXACT NEXT STEPS, EXACT NEXT STEPS for whoever picks this up, EXACT NEXT STEPS for whoever picks this up, Marius / Erased — Continuation Notes (2026-09-19 PART 1, THROUGHPUT + AGNES-REPLACEMENT SESSION), Marius / Erased — Continuation Notes (2026-09-19 PART 2, LIVE HANDOFF) (+6 more)

### Community 15 - "Marius Command Center — Handoff Doc"
Cohesion: 0.25
Nodes (7): Current `scripts/` files (2026-09-21, confirmed live via a clone of `main`), Marius Command Center — Handoff Doc, Older history (pre-2026-09-18, unverified against current live state —, Pipeline, STANDING RULES (read this section first, every session, no exceptions), Storage: Backblaze B2 (migrated 2026-09-02, still current), Supabase project (re-verify at the start of every session — this has

### Community 16 - "Marius Playbook (rarely changes — read alongside STATUS.md)"
Cohesion: 0.20
Nodes (9): Database (Supabase table "scripts"), Database (Supabase table "topics"), GitHub Actions secrets currently set, Known gotchas already solved - do not rediscover these, Marius Playbook (rarely changes — read alongside STATUS.md), Pipeline order, Remaining stages to build, Standing communication rules (+1 more)

### Community 17 - "clip_qa.py"
Cohesion: 0.15
Nodes (11): check_clip(), enabled(), _extract_frames_b64(), _max_calls(), max_redo(), shot_needs_check(), focus_anchor(), no_people_clause() (+3 more)

### Community 18 - "upload_bytes"
Cohesion: 0.25
Nodes (6): 2026-09-19 session — B2/Agnes fixes landed, throughput math checked, Agnes-replacement researched, Agnes-replacement research (requested by Ali — "generate video on a, What's CONFIRMED this session, _client_config(), _new_client(), upload_bytes()

### Community 19 - "Debugging Methodology — Mandatory for Every AI Agent Working on Atlas Frame Pipelines"
Cohesion: 0.33
Nodes (5): Debugging Methodology — Mandatory for Every AI Agent Working on Atlas Frame Pipelines, Standing priority, The process, in order, every time, The rule, stated plainly, What this looked like in practice (2026-08-18 Nova case study)

### Community 20 - "Marius Command Center — AI Operating Standards"
Cohesion: 0.40
Nodes (4): Before ending any session, Marius Command Center — AI Operating Standards, Standing behavioral rules, The three living docs in this repo — know the difference

### Community 21 - "_get_client"
Cohesion: 0.33
Nodes (6): fetch_script_ids(), gb(), list_bucket(), main(), _get_client(), object_exists()

## Knowledge Gaps
- **49 isolated node(s):** `Standing role (from Zia, 2026-09-21)`, `Correction to PART 4 (important — do NOT delete these files)`, `Declutter done (2026-09-19, verified before deleting)`, `NOT verified`, `EXACT NEXT STEPS` (+44 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 203 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **1 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `build_agnes_prompt()` connect `re` to `clip_generation.py`?**
  _High betweenness centrality (0.041) - this node is a cross-community bridge._
- **Are the 3 inferred relationships involving `process_script()` (e.g. with `AgnesBadRequestError` and `AgnesOverloadedError`) actually correct?**
  _`process_script()` has 3 INFERRED edges - model-reasoned connections that need verification._
- **What connects `Standing role (from Zia, 2026-09-21)`, `Correction to PART 4 (important — do NOT delete these files)`, `Declutter done (2026-09-19, verified before deleting)` to the rest of the system?**
  _49 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `clip_generation.py` be split into smaller, more focused modules?**
  _Cohesion score 0.09672830725462304 - nodes in this community are weakly interconnected._
- **Why does `call_llm()` connect `shot_breakdown_stage.py` to `requests`, `time`, `json`?**
  _High betweenness centrality (0.040) - this node is a cross-community bridge._
- **Should `assembly_stage.py` be split into smaller, more focused modules?**
  _Cohesion score 0.07827260458839407 - nodes in this community are weakly interconnected._
- **Why does `poll_agnes_task()` connect `clip_generation.py` to `requests`, `time`, `Marius / Erased — Continuation Notes (2026-09-21 PART 5, AGNES CREATE-TIMEOUT FIX + PART 4 CORRECTION, read this section FIRST)`?**
  _High betweenness centrality (0.038) - this node is a cross-community bridge._