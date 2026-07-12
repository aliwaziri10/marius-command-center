# Marius Command Center — Handoff Sheet
Written: 2026-07-12, by Claude, verified live against Supabase and GitHub at time of writing.

## ⚠️ STANDING RULE — READ THIS FIRST
**Do not trust this document at face value.** Before acting on ANY claim below, re-verify it against live Supabase data (project `swnjzzejsuupecdgbzzf`) and/or the live GitHub repo (`aliwaziri10/marius-command-center`). This has caught real false claims in prior handoffs — trust the database and the actual repo files, never a previous session's notes, including this one.

## User workflow preferences (apply every time, no exceptions)
- Every path/URL goes in its own fenced code block (so the copy button appears).
- Every script/code change: give the path first, then paste the FULL file content directly in a fenced code block in the chat message itself — never as a downloadable file. User selects-all-deletes-pastes into GitHub and commits.
- Zia is a non-coder: no diffs, full-file replacement only. Max 3-4 steps per message.
- Do not ask for permission/confirmation on routine execution steps once a plan is clear — only check in when a decision genuinely needs Zia's input. Just proceed and report what was done.
- After every meaningful change, update this handoff doc (commit it to `docs/marius-handoff.md` in the repo, not a local/sandbox path) with exact verified values so the next session doesn't have to re-derive anything.

## Reusable references
- Supabase project ID: `swnjzzejsuupecdgbzzf`
- GitHub repo: `https://github.com/aliwaziri10/marius-command-center`
- GitHub Actions: `https://github.com/aliwaziri10/marius-command-center/actions`
- Storage buckets (all public): `narration`, `images`, `video_clips`, `videos`, `thumbnails`
- `CLIP_BATCH_LIMIT = 8` in `video_generation.py` — each run only generates up to 8 new clips (Agnes free-tier quota), resumes next run.
- `image_generation.py` has NO batch limit — one run processes the entire script's shot list in one continuous execution.
- Claude has no ability to trigger GitHub Actions workflow runs or push commits directly in the normal case — Zia does the "Run workflow" / "paste and commit" steps. (Session note: later in this session Claude did push one commit directly via the GitHub API for a non-workflow file — see log below if that capability is confirmed repeatable.)
- Claude's tools cannot fetch/render images from `swnjzzejsuupecdgbzzf.supabase.co` — visual checks of thumbnails must be done by Zia directly.

## Verified script pipeline state (last queried 2026-07-12, RE-VERIFY before trusting)

| Script ID | Status | Images | Clips (of shot count) | Notes |
|---|---|---|---|---|
| `1cb89fbe-d7aa-41ab-90d8-0d1cd1fbfd62` | `narrated` (last check) | 0 (last check) | 0 (55 shots) | Has real `shot_durations`. Image Generation was manually triggered but not confirmed complete — re-check status/image count live. |
| `a2e22bd4-f418-4d53-8d5e-40bee1203760` | `images_generated` | 43 | 16 (of 43) | Old narration (no `shot_durations`), needs ~4 more Video Generation runs. |
| `ae2507cb-e06f-4884-954e-ea7870707636` | `images_generated` | 38 | 17 (of 38) | Old narration (no `shot_durations`), needs ~3 more Video Generation runs. |
| `8c626aa5-672b-4fda-82aa-c9ef2bbe82d6` | `uploaded` | 42 | 42/42 | Live YouTube ID `FUykoQjdyg8`. `hook_text` backfilled to `"312 DIARIES. ONE BOMB. GONE IN SECONDS."`. `thumbnail_url` reset to null to force regen with fixed code — RE-VERIFY whether it has regenerated yet and whether it looks right. |
| `d615192e-8707-4c1d-8f62-8f6b84e3d51e` | `archived` | 23 | 0 (23 shots) | Still untouched, still not discussed with Zia. |

## Code changes made 2026-07-12
1. **`scripts/thumbnail_generation.py`** — rewritten and confirmed committed (verified via raw.githubusercontent.com: `fit_text_to_frame`, `TEXT_COLOR = (255, 214, 0)` present). Auto-shrinking font so text can't overflow, stroke-aware centering, yellow text, vivid/saturated background prompt instead of "moody, film grain".
2. **`scripts/script_writing.py`** — rewritten and confirmed committed (verified: `normalize_hook_text`, `hook_text` in prompt schema present). Adds a real `hook_text` field generated per-script instead of always falling back to a narration sentence.
3. **Database**: `8c626aa5` had `hook_text` set and `thumbnail_url` reset to null via direct SQL.

## Open items / next steps (in order) — RE-VERIFY EACH BEFORE ACTING
1. Confirm `8c626aa5`'s thumbnail has regenerated with the new code and looks right (no cutoff, centered, yellow text, vivid background) — Zia must check the image directly.
2. Re-check `1cb89fbe` status/image count live — resume or re-trigger Image Generation if needed.
3. Resume `ae2507cb` and `a2e22bd4` with more Video Generation runs.
4. Ask Zia about `d615192e`.
5. GitHub secrets page not independently re-checked — only investigate if a run logs "not set" again.
