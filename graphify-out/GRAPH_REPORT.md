# Graph Report - marius-command-center  (2026-10-20)

## Corpus Check
- 41 files · ~67,212 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 528 nodes · 1138 edges · 23 communities (22 shown, 1 thin omitted)
- Extraction: 97% EXTRACTED · 3% INFERRED · 0% AMBIGUOUS · INFERRED: 36 edges (avg confidence: 0.94)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `52ff10e0`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- llm_client.py
- clip_generation.py
- assembly_stage.py
- json
- shot_breakdown_stage.py
- os
- video_generation.py
- re
- narration.py
- requests
- thumbnail_generation.py
- generate_codemap.py
- storage_b2.py
- _get_client
- Marius / Erased — Continuation Notes (2026-09-21 PART 5, AGNES CREATE-TIMEOUT FIX + PART 4 CORRECTION, read this section FIRST)
- Marius Command Center — Handoff Doc
- Marius Playbook (rarely changes — read alongside STATUS.md)
- upload_bytes
- b2_preflight.py
- Debugging Methodology — Mandatory for Every AI Agent Working on Atlas Frame Pipelines
- Marius Command Center — AI Operating Standards
- Marius / Erased — Continuation Notes (2026-09-19 PART 2, LIVE HANDOFF)
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
- `2026-09-21 — Agnes create-task ReadTimeout crash fixed; declutter` --references--> `create_agnes_task()`  [INFERRED]
  docs/marius-handoff.md → scripts/agnes_client.py
- `What happened this session` --references--> `generate_narration()`  [INFERRED]
  CONTINUATION.md → scripts/narration_stage.py
- `Next steps` --references--> `AgnesOverloadedError`  [INFERRED]
  docs/kaggle-video-test-notes.md → scripts/agnes_client.py
- `EXACT NEXT STEPS for whoever picks this up` --references--> `poll_agnes_task()`  [INFERRED]
  CONTINUATION.md → scripts/agnes_client.py
- `2026-09-18/19 — Video generation stall, three independent root causes` --references--> `poll_agnes_task()`  [INFERRED]
  docs/marius-handoff.md → scripts/agnes_client.py

## Import Cycles
- None detected.

## Communities (23 total, 1 thin omitted)

### Community 0 - "llm_client.py"
Cohesion: 0.07
Nodes (28): call_llm(), DailyQuotaExhausted, extract_json(), InfraFailure, _quote_unquoted_keys(), sanitize_json_control_chars(), _strip_trailing_commas(), build_narration_continuation_prompt() (+20 more)

### Community 1 - "clip_generation.py"
Cohesion: 0.07
Nodes (38): Marius / Erased — Continuation Notes (2026-09-19 PART 3, CHAIN BEATS — read this section FIRST), NOT verified, Tests run (sandbox, mocked Agnes/moviepy), Verified live on `main` (2026-09-19), What was found and fixed (2026-09-21), Decision, Kaggle free-GPU video test: decision notes, Next steps (+30 more)

### Community 2 - "assembly_stage.py"
Cohesion: 0.07
Nodes (29): apply_safety_limiter(), assemble_final_video(), build_audio_mix(), build_caption_clip(), build_caption_clips(), compute_shot_start_times(), compute_target_bitrate(), download_file() (+21 more)

### Community 3 - "json"
Cohesion: 0.08
Nodes (23): check_generation_failed_backlog(), check_stale_scripts(), check_stuck_scripts(), hours_since(), main(), supabase_get(), attempt(), free() (+15 more)

### Community 4 - "shot_breakdown_stage.py"
Cohesion: 0.08
Nodes (23): auto_repair_dominant_subject(), auto_repair_excessive_consecutive_subject(), auto_repair_location_change_without_establishing(), auto_repair_missing_onscreen_text(), build_shot_breakdown_chunk_prompt(), build_shot_breakdown_response_schema(), find_anachronistic_object_shots(), find_continuation_language_shots() (+15 more)

### Community 5 - "os"
Cohesion: 0.12
Nodes (20): _concat(), configure_agnes_wait(), _download(), _ffmpeg(), _generic_queries(), is_enabled(), _keywords(), _loop_fill() (+12 more)

### Community 6 - "video_generation.py"
Cohesion: 0.13
Nodes (24): upload_video(), extract_last_frame_url(), generate_character_reference(), get_continuity_anchor(), retryable_request(), upload_file(), clear_error(), compute_shot_durations() (+16 more)

### Community 7 - "re"
Cohesion: 0.09
Nodes (20): 1. Done today (verified by commit), 2. Problems Zia reported on 2026-10-08 (all still OPEN), 3. Evidence gathered (Marius only), 4.1 Plan check: protagonist cap (planning stage), 4.2 Prompt fix: only describe the protagonist when the shot is about them, 4.3 Clip check: morphing and waxy-face detector (after each clip, before upload to B2), 4.4 Measure, 4. Build list (in this order) (+12 more)

### Community 8 - "narration.py"
Cohesion: 0.11
Nodes (12): list_all_objects(), main(), _assign_shots_to_sentences(), main(), _max_plausible_duration(), _merge_short_segments(), narrate_one_script(), split_into_segments() (+4 more)

### Community 9 - "requests"
Cohesion: 0.17
Nodes (15): fetch_top_articles(), main(), save_signal(), build_description(), delete_source_from_storage(), download_file(), get_access_token(), get_authorized_channel() (+7 more)

### Community 10 - "thumbnail_generation.py"
Cohesion: 0.15
Nodes (11): derive_hook_text(), download_video_frame(), fit_text_to_frame(), fits(), _line_bbox(), main(), overlay_hook_text(), push_thumbnail_to_youtube() (+3 more)

### Community 11 - "generate_codemap.py"
Cohesion: 0.24
Nodes (8): build_codemap(), CallCollector, extract_env_vars(), extract_tables(), find_py_files(), get_docstring_first_line(), main(), process_file()

### Community 12 - "storage_b2.py"
Cohesion: 0.21
Nodes (5): _presign_clients(), _presign_config(), presigned_url(), _region_from_endpoint(), _url_is_fetchable()

### Community 13 - "_get_client"
Cohesion: 0.21
Nodes (8): fetch_script_ids(), gb(), list_bucket(), main(), download_to_file(), _get_client(), object_exists(), object_size()

### Community 14 - "Marius / Erased — Continuation Notes (2026-09-21 PART 5, AGNES CREATE-TIMEOUT FIX + PART 4 CORRECTION, read this section FIRST)"
Cohesion: 0.17
Nodes (11): Correction to PART 4 (important — do NOT delete these files), Declutter done (2026-09-19, verified before deleting), EXACT NEXT STEPS, EXACT NEXT STEPS for whoever picks this up, Marius / Erased — Continuation Notes (2026-09-19 PART 1, THROUGHPUT + AGNES-REPLACEMENT SESSION), Marius / Erased — Continuation Notes (2026-09-19 PART 4, SKILLS + DECLUTTER, read this section FIRST), Marius / Erased — Continuation Notes (2026-09-21 PART 5, AGNES CREATE-TIMEOUT FIX + PART 4 CORRECTION, read this section FIRST), NOT verified (+3 more)

### Community 15 - "Marius Command Center — Handoff Doc"
Cohesion: 0.17
Nodes (11): 2026-09-18/19 — Video generation stall, three independent root causes, 2026-09-19 — Trend grounding was completely dead since creation, 2026-09-21 — Agnes create-task ReadTimeout crash fixed; declutter, Current `scripts/` files (2026-09-21, confirmed live via a clone of `main`), Marius Command Center — Handoff Doc, Older history (pre-2026-09-18, unverified against current live state —, Pipeline, Session log (most recent first — keep this section, don't delete old (+3 more)

### Community 16 - "Marius Playbook (rarely changes — read alongside STATUS.md)"
Cohesion: 0.20
Nodes (9): Database (Supabase table "scripts"), Database (Supabase table "topics"), GitHub Actions secrets currently set, Known gotchas already solved - do not rediscover these, Marius Playbook (rarely changes — read alongside STATUS.md), Pipeline order, Remaining stages to build, Standing communication rules (+1 more)

### Community 17 - "upload_bytes"
Cohesion: 0.25
Nodes (6): 2026-09-19 session — B2/Agnes fixes landed, throughput math checked, Agnes-replacement researched, Agnes-replacement research (requested by Ali — "generate video on a, What's CONFIRMED this session, _client_config(), _new_client(), upload_bytes()

### Community 18 - "b2_preflight.py"
Cohesion: 0.29
Nodes (3): main(), probe(), delete_object()

### Community 19 - "Debugging Methodology — Mandatory for Every AI Agent Working on Atlas Frame Pipelines"
Cohesion: 0.33
Nodes (5): Debugging Methodology — Mandatory for Every AI Agent Working on Atlas Frame Pipelines, Standing priority, The process, in order, every time, The rule, stated plainly, What this looked like in practice (2026-08-18 Nova case study)

### Community 20 - "Marius Command Center — AI Operating Standards"
Cohesion: 0.40
Nodes (4): Before ending any session, Marius Command Center — AI Operating Standards, Standing behavioral rules, The three living docs in this repo — know the difference

### Community 21 - "Marius / Erased — Continuation Notes (2026-09-19 PART 2, LIVE HANDOFF)"
Cohesion: 0.50
Nodes (4): CURRENT STATE (as of handoff), EXACT NEXT STEPS for whoever picks this up, Marius / Erased — Continuation Notes (2026-09-19 PART 2, LIVE HANDOFF), WHY this matters — the live open question at handoff

## Knowledge Gaps
- **49 isolated node(s):** `Standing role (from Zia, 2026-09-21)`, `Correction to PART 4 (important — do NOT delete these files)`, `Declutter done (2026-09-19, verified before deleting)`, `NOT verified`, `EXACT NEXT STEPS` (+44 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 202 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **1 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `build_agnes_prompt()` connect `re` to `clip_generation.py`?**
  _High betweenness centrality (0.041) - this node is a cross-community bridge._
- **Are the 3 inferred relationships involving `process_script()` (e.g. with `AgnesBadRequestError` and `AgnesOverloadedError`) actually correct?**
  _`process_script()` has 3 INFERRED edges - model-reasoned connections that need verification._
- **What connects `Standing role (from Zia, 2026-09-21)`, `Correction to PART 4 (important — do NOT delete these files)`, `Declutter done (2026-09-19, verified before deleting)` to the rest of the system?**
  _49 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `llm_client.py` be split into smaller, more focused modules?**
  _Cohesion score 0.07272727272727272 - nodes in this community are weakly interconnected._
- **Why does `call_llm()` connect `llm_client.py` to `clip_generation.py`, `json`, `shot_breakdown_stage.py`, `video_generation.py`, `requests`?**
  _High betweenness centrality (0.040) - this node is a cross-community bridge._
- **Should `clip_generation.py` be split into smaller, more focused modules?**
  _Cohesion score 0.06748911465892599 - nodes in this community are weakly interconnected._
- **Why does `poll_agnes_task()` connect `clip_generation.py` to `requests`, `Marius / Erased — Continuation Notes (2026-09-19 PART 2, LIVE HANDOFF)`, `video_generation.py`, `Marius Command Center — Handoff Doc`?**
  _High betweenness centrality (0.039) - this node is a cross-community bridge._