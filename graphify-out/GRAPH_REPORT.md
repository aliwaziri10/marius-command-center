# Graph Report - marius-command-center  (2026-11-12)

## Corpus Check
- 52 files · ~78,395 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 678 nodes · 1511 edges · 27 communities (25 shown, 2 thin omitted)
- Extraction: 97% EXTRACTED · 3% INFERRED · 0% AMBIGUOUS · INFERRED: 42 edges (avg confidence: 0.94)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `d250fd1b`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- llm_client.py
- time
- kaggle_clips.py
- kernel.py
- shot_breakdown_stage.py
- stock_fallback.py
- HANDOFF 2026-11-12 - Marius quality fix plan (and Lawn Tales next)
- os
- re
- requests
- 17fc73b3_shot_review.md
- HANDOFF 2026-10-18: Free backup video generator (Agnes queue full)
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
- verify_run_output.py
- generate_codemap.py
- assembly_stage.py
- HANDOFF 2026-11-11 (Marius only): Kaggle clips, where it stands

## God Nodes (most connected - your core abstractions)
1. `process_script()` - 27 edges
2. `retryable_request()` - 23 edges
3. `generate_shot_clip()` - 21 edges
4. `validate_and_normalize_shot_response()` - 21 edges
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

## Communities (27 total, 2 thin omitted)

### Community 0 - "llm_client.py"
Cohesion: 0.07
Nodes (30): call_llm(), DailyQuotaExhausted, extract_json(), InfraFailure, _quote_unquoted_keys(), sanitize_json_control_chars(), _strip_trailing_commas(), build_narration_continuation_prompt() (+22 more)

### Community 1 - "time"
Cohesion: 0.08
Nodes (44): What was found and fixed (2026-09-21), What was learned this session, AgnesBadRequestError, AgnesOverloadedError, ContentPolicyRejection, create_agnes_task(), extract_video_url(), poll_agnes_task() (+36 more)

### Community 2 - "kaggle_clips.py"
Cohesion: 0.08
Nodes (35): NOT verified, Files (all on main, compile-checked), HANDOFF 2026-11-10 (end of session): Kaggle AI clips for Marius, History this session, Next steps, in order, NOT verified (check first, live), Secrets (names only, Claude cannot read them), apply_beat_to_shot() (+27 more)

### Community 3 - "kernel.py"
Cohesion: 0.11
Nodes (19): call(), free(), load(), make_shot(), run(), save(), seg_frames(), add_sound() (+11 more)

### Community 4 - "shot_breakdown_stage.py"
Cohesion: 0.07
Nodes (40): anchor_declares_no_protagonist(), anchor_problem(), auto_repair_ambience(), auto_repair_dominant_subject(), auto_repair_excessive_consecutive_subject(), auto_repair_face_closeups(), auto_repair_location_change_without_establishing(), auto_repair_missing_onscreen_text() (+32 more)

### Community 5 - "stock_fallback.py"
Cohesion: 0.12
Nodes (20): _concat(), configure_agnes_wait(), _download(), _ffmpeg(), _generic_queries(), is_enabled(), _keywords(), _loop_fill() (+12 more)

### Community 6 - "HANDOFF 2026-11-12 - Marius quality fix plan (and Lawn Tales next)"
Cohesion: 0.25
Nodes (7): CURRENT STATE (as told by him, 2026-11-12 - GitHub could not confirm; its API rate-limited this session), Decisions he stated (2026-11-12), Done and verified, HANDOFF 2026-11-12 - Marius quality fix plan (and Lawn Tales next), Lawn Tales (after Marius), Root causes of the bad video (measured), TODO, in this order

### Community 7 - "os"
Cohesion: 0.11
Nodes (17): extract_url(), finish(), run(), list_all_objects(), main(), check_generation_failed_backlog(), check_stale_scripts(), check_stuck_scripts() (+9 more)

### Community 8 - "re"
Cohesion: 0.06
Nodes (29): 1. Done today (verified by commit), 2. Problems Zia reported on 2026-10-08 (all still OPEN), 3. Evidence gathered (Marius only), 4.1 Plan check: protagonist cap (planning stage), 4.2 Prompt fix: only describe the protagonist when the shot is about them, 4.3 Clip check: morphing and waxy-face detector (after each clip, before upload to B2), 4.4 Measure, 4. Build list (in this order) (+21 more)

### Community 9 - "requests"
Cohesion: 0.14
Nodes (18): _fetch_script_ids(), _gb(), sweep(), fetch_top_articles(), main(), save_signal(), build_description(), delete_source_from_storage() (+10 more)

### Community 11 - "HANDOFF 2026-10-18: Free backup video generator (Agnes queue full)"
Cohesion: 0.29
Nodes (6): Chosen plan, HANDOFF 2026-10-18: Free backup video generator (Agnes queue full), Read this first (how to work with Zia), Research findings (searches only, limits not tested by us), Status / next steps, The problem

### Community 12 - "thumbnail_generation.py"
Cohesion: 0.08
Nodes (22): check_clip(), enabled(), _extract_frames_b64(), _max_calls(), max_redo(), shot_needs_check(), focus_anchor(), no_people_clause() (+14 more)

### Community 13 - "storage_b2.py"
Cohesion: 0.06
Nodes (26): 2026-09-19 session — B2/Agnes fixes landed, throughput math checked, Agnes-replacement researched, Agnes-replacement research (requested by Ali — "generate video on a, Marius / Erased — Continuation Notes (2026-09-19 PART 1, THROUGHPUT + AGNES-REPLACEMENT SESSION), What's CONFIRMED this session, main(), probe(), fetch_script_ids(), gb() (+18 more)

### Community 14 - "Marius / Erased - Continuation Notes (2026-11-11 PART 6, NARRATION ORDER + NARRATION STORAGE + THROUGHPUT, read this section FIRST)"
Cohesion: 0.07
Nodes (26): Confirmed live (2026-11-11, about 21:10), Correction to PART 4 (important — do NOT delete these files), CURRENT STATE (as of handoff), Decisions waiting for Zia (free options only), Declutter done (2026-09-19, verified before deleting), Do not, EXACT NEXT STEPS, EXACT NEXT STEPS for whoever picks this up (+18 more)

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

### Community 23 - "verify_run_output.py"
Cohesion: 0.16
Nodes (12): check_b2_key_alive(), check_stalled_scripts(), check_url_alive(), fetch_scripts(), main(), _names_protagonist(), _parse_created_at(), _protagonist_name() (+4 more)

### Community 24 - "generate_codemap.py"
Cohesion: 0.24
Nodes (8): build_codemap(), CallCollector, extract_env_vars(), extract_tables(), find_py_files(), get_docstring_first_line(), main(), process_file()

### Community 26 - "assembly_stage.py"
Cohesion: 0.12
Nodes (18): apply_safety_limiter(), assemble_final_video(), build_audio_mix(), build_caption_clip(), build_caption_clips(), compute_shot_start_times(), compute_target_bitrate(), download_file() (+10 more)

### Community 28 - "HANDOFF 2026-11-11 (Marius only): Kaggle clips, where it stands"
Cohesion: 0.25
Nodes (7): Fix in progress (this session), HANDOFF 2026-11-11 (Marius only): Kaggle clips, where it stands, Rules, State of repo (verified by direct read), Still open, What fails (live data, 2026-11-11), What works (proven)

## Knowledge Gaps
- **82 isolated node(s):** `NEXT PROFILE START HERE`, `What changed this session`, `Confirmed live (2026-11-11, about 21:10)`, `Why videos come out about once a week (arithmetic, NOT measured on Kaggle)`, `Do not` (+77 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 259 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **2 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `process_script()` connect `time` to `kaggle_clips.py`, `os`, `storage_b2.py`, `assembly_stage.py`, `HANDOFF 2026-11-11 (Marius only): Kaggle clips, where it stands`?**
  _High betweenness centrality (0.045) - this node is a cross-community bridge._
- **What connects `NEXT PROFILE START HERE`, `What changed this session`, `Confirmed live (2026-11-11, about 21:10)` to the rest of the system?**
  _82 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `llm_client.py` be split into smaller, more focused modules?**
  _Cohesion score 0.06604324956165984 - nodes in this community are weakly interconnected._
- **Why does `build_agnes_prompt()` connect `re` to `time`, `kaggle_clips.py`?**
  _High betweenness centrality (0.034) - this node is a cross-community bridge._
- **Should `time` be split into smaller, more focused modules?**
  _Cohesion score 0.07785547785547786 - nodes in this community are weakly interconnected._
- **Why does `poll_agnes_task()` connect `time` to `requests`, `Marius / Erased - Continuation Notes (2026-11-11 PART 6, NARRATION ORDER + NARRATION STORAGE + THROUGHPUT, read this section FIRST)`, `Marius Command Center — Handoff Doc`?**
  _High betweenness centrality (0.032) - this node is a cross-community bridge._
- **Should `kaggle_clips.py` be split into smaller, more focused modules?**
  _Cohesion score 0.08326530612244898 - nodes in this community are weakly interconnected._