# Marius Command Center — Handoff Sheet
Written: 2026-07-12 (later same day), by Claude, verified live against Supabase and GitHub at time of writing.

## ⚠️ STANDING RULE — READ THIS FIRST
**Do not trust this document at face value.** Before acting on ANY claim below, re-verify it against live Supabase data (project `swnjzzejsuupecdgbzzf`) and/or the live GitHub repo (`aliwaziri10/marius-command-center`). This has caught real false claims in prior handoffs — trust the database and the actual repo files, never a previous session's notes, including this one.

## User workflow preferences (apply every time, no exceptions)
- Every path/URL goes in its own fenced code block (so the copy button appears).
- Every script/code change: give the path first, then paste the FULL file content directly in a fenced code block in the chat message itself — never as a downloadable file. User selects-all-deletes-pastes into GitHub and commits.
- Zia is a non-coder: no diffs, full-file replacement only. Max 3-4 steps per message.
- Do not ask for permission/confirmation on routine execution steps once a plan is clear — only check in when a decision genuinely needs Zia's input. Just proceed and report what was done.
- After every meaningful change, update this handoff doc (`docs/marius-handoff.md` in the repo — always commit it here, never a local/sandbox path) with exact verified values so the next session doesn't have to re-derive anything.
- **GitHub write access**: Claude's GitHub connector is currently read-only (confirmed via a 403 "Resource not accessible by integration" error when attempting `create_or_update_file`). All code/workflow changes must still go through Zia pasting into the GitHub UI. Zia has been told how to upgrade this (GitHub → Settings → Applications → Installed GitHub Apps → set Contents to Read and write) but has NOT done so as of this writing — re-check by attempting a small write before assuming this has changed.

## Reusable references
- Supabase project ID: `swnjzzejsuupecdgbzzf`
- GitHub repo: `https://github.com/aliwaziri10/marius-command-center`
- GitHub Actions: `https://github.com/aliwaziri10/marius-command-center/actions`
- Storage buckets (all public): `narration`, `images`, `video_clips`, `videos`, `thumbnails`
- `CLIP_BATCH_LIMIT = 8` in `video_generation.py` — each run only generates up to 8 new clips (Agnes free-tier quota), resumes next run.
- `image_generation.py` has NO batch limit — one run processes the entire script's shot list in one continuous execution.
- Claude's tools cannot fetch/render images from `swnjzzejsuupecdgbzzf.supabase.co` — visual checks of thumbnails must be done by Zia directly.
- Claude DOES have a working GitHub connector for reads (`GitHub:get_file_contents`, etc.) — use this instead of `raw.githubusercontent.com` fetches where convenient, it's authenticated and not rate-limited the same way.

## Full pipeline map (all 8 workflows, verified live 2026-07-12)
| Workflow | Schedule | Does |
|---|---|---|
| Topic Research | every 6h | generates new topics |
| Script Writing | 03:00, 15:00 | writes script + `hook_text` from oldest pending topic |
| Narration | 05:00, 17:00 | narrates oldest pending script, writes `shot_durations` |
| Image Generation | every 6h | ALL shots in one run (no batch limit) |
| Video Generation | every 20 min | 8 clips/run, auto-assembles once all clips done |
| Thumbnail Generation | every 10 min | picks oldest script missing a thumbnail; also pushes directly to YouTube if script already `uploaded` (see Code changes below) |
| YouTube Upload | every 30 min | uploads oldest `video_generated` script, sets thumbnail if one exists yet |
| Update Status | on completion of the above | keeps `STATUS.md` current |

All cron schedules and concurrency groups confirmed correct — no structural pipeline issues found in this audit.

## Verified script pipeline state (queried directly, 2026-07-12, RE-VERIFY before trusting)

| Script ID | Status | Images | Clips | Notes |
|---|---|---|---|---|
| `8688e753-a000-419c-8250-a1294cb12a75` | `pending` | 0 | 0 | **New, generated this session by the live pipeline** — hook_text is `"400 PAGES. ONE CHEST."`, confirming the `script_writing.py` hook_text fix works end-to-end on a real new script. |
| `1cb89fbe-d7aa-41ab-90d8-0d1cd1fbfd62` | `images_generated` | 55/55 | 0 | Has real `shot_durations` (new sync fix). Ready for Video Generation, will pick up automatically. |
| `a2e22bd4-f418-4d53-8d5e-40bee1203760` | `video_generated` | 43 | 43/43 | Old narration (no `shot_durations`). Fully assembled, waiting for Thumbnail Generation + YouTube Upload to pick it up on their next scheduled ticks — good real-world test of the new thumbnail-push code path once it goes through. |
| `ae2507cb-e06f-4884-954e-ea7870707636` | `uploaded` | 38 | 38/38 | Live YouTube ID `ZzoWqHRgb80`. hook_text `"VERDUN: THE FORGOTTEN ARMY"`. Thumbnail exists in Supabase. **Zia manually uploaded a custom thumbnail via YouTube Studio for this video already** (had no thumbnail because it was uploaded before the thumbnail pipeline existed). |
| `8c626aa5-672b-4fda-82aa-c9ef2bbe82d6` | `uploaded` | 42 | 42/42 | Live YouTube ID `FUykoQjdyg8`. hook_text is now `"SECRET LEDGER"` (changed by an external/unknown process after Claude set it to `"312 DIARIES..."` earlier — unexplained, not investigated). **Zia manually uploaded a custom thumbnail via YouTube Studio for this video too**, same reason as above. |
| `d615192e-8707-4c1d-8f62-8f6b84e3d51e` | `archived` | 23 | 0 | Still untouched, still not discussed with Zia. Ask her directly. |

## Code changes made 2026-07-12 (all confirmed live in repo)
1. **`scripts/thumbnail_generation.py`** — multiple rounds this session, final confirmed state (333 lines, syntax-checked):
   - Auto-shrinking font (`fit_text_to_frame`, 88px down to 40px floor) so hook text can never overflow/get cut off at the edges.
   - Stroke-aware bounding box math (`_line_bbox` includes `stroke_width`) for accurate centering.
   - Yellow text `(255, 214, 0)` instead of white.
   - Vivid/saturated background image prompt instead of "moody, film grain" (better YouTube CTR).
   - `resize_to_canvas()` cover-crop — added by a **different session** working on the same repo in parallel (confirmed compatible, not a conflict) — force-fits Pollinations.ai output to the exact 1280x720 canvas before text layout, since Pollinations doesn't always honor requested dimensions.
   - **NEW this round**: `push_thumbnail_to_youtube()` — when this script generates/regenerates a thumbnail for a script that's already `status = 'uploaded'` (has a `youtube_video_id`), it now pushes the thumbnail directly to the live YouTube video via `thumbnails.set`, not just to Supabase. This closes a real gap: previously, any post-upload thumbnail regeneration sat unused in Supabase forever since `youtube_upload.py` only calls `thumbnails.set` once, at original upload time. Requires `YOUTUBE_CLIENT_ID`/`YOUTUBE_CLIENT_SECRET`/`YOUTUBE_REFRESH_TOKEN` env vars (added to the workflow, see below) — if missing, the push step just logs and skips, doesn't fail the run.
2. **`.github/workflows/thumbnail_generation.yml`** — updated to pass `YOUTUBE_CLIENT_ID`, `YOUTUBE_CLIENT_SECRET`, `YOUTUBE_REFRESH_TOKEN` as env vars (same secrets `youtube_upload.yml` already uses), required for the push above to work.
3. **`scripts/script_writing.py`** — adds a real `hook_text` field to the generation prompt/schema (`normalize_hook_text()`), confirmed working on a real new script (`8688e753`, see table above).
4. **Database**: `8c626aa5` had `hook_text` set (later changed externally, see table) and `thumbnail_url` reset to null earlier this session to force a regen with the fixed code.

**NOT YET TESTED end-to-end**: the `push_thumbnail_to_youtube` path has not yet fired for real, since no script has both (a) been freshly uploaded AND (b) had its thumbnail regenerated *after* upload since this code went live. The next natural test is if `a2e22bd4` or `1cb89fbe` get uploaded and something later triggers a thumbnail regen on them — or a manual test by nulling `thumbnail_url` on `ae2507cb` or `8c626aa5` and watching the next Thumbnail Generation run's logs.

## Open items / next steps (in order) — RE-VERIFY EACH BEFORE ACTING
1. Watch `a2e22bd4` go through Thumbnail Generation + YouTube Upload on its own (should happen automatically within the hour) — first real end-to-end test of the fixed thumbnail pipeline on a brand-new upload.
2. Trigger or wait for Video Generation on `1cb89fbe` (55 shots, needs ~7 runs at 8 clips/run).
3. Ask Zia about `d615192e` — still unresolved.
4. Consider testing `push_thumbnail_to_youtube` deliberately (null out `thumbnail_url` for an already-`uploaded` script, watch the next Thumbnail Generation run push it live) to confirm the new capability actually works before relying on it.
5. GitHub secrets page not independently re-checked — only investigate if a run logs "not set" again.
6. Optional: ask Zia if she wants to grant Claude's GitHub connector write access (Contents: Read and write) to skip the copy-paste step for future code changes — she was informed but hadn't decided as of this writing.
