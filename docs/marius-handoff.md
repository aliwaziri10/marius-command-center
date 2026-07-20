# Marius Command Center — Handoff Sheet
Written: 2026-07-20, by Claude, verified live against Supabase and GitHub at time of writing.

## ⚠️ STANDING RULE — READ THIS FIRST
**Do not trust this document at face value.** Before acting on ANY claim below, re-verify it against live Supabase data (project `swnjzzejsuupecdgbzzf`) and/or the live GitHub repo (`aliwaziri10/marius-command-center`). Prior handoffs have gone stale within days — trust the database and the actual repo files, never a previous session's notes, including this one.

## User workflow preferences (apply every time, no exceptions)
- Every path/URL goes in its own fenced code block (copy button).
- Every script/code change: give the path first, then the FULL file content in a separate fenced code block in chat. Zia selects-all, deletes, pastes, commits. Never diffs, never "find this line."
- Zia is a non-coder, works via browser only (GitHub web editor, Supabase dashboard, Render/Google Cloud Console), no terminal.
- One step at a time for multi-step instructions.
- Terse, action-only replies — no preamble/rationale unless safety-critical.
- After meaningful changes, update this doc with exact live-verified values.
- GitHub `create_or_update_file` returns 403 every session — Claude's write access is read-only in practice. All code changes go through Zia pasting into the GitHub web UI.
- Branch protection on `main`: no direct commits — but Zia has been committing directly via the web editor successfully this session, so protection may not be active or applies only to the API path. Re-verify if a future commit is rejected.

## Reusable references
- Supabase project ID: `swnjzzejsuupecdgbzzf`
- GitHub repo: `https://github.com/aliwaziri10/marius-command-center`
- GitHub Actions: `https://github.com/aliwaziri10/marius-command-center/actions`
- Storage buckets: `narration`, `video_clips`, `videos`, `thumbnails` (`images` bucket now unused — see pipeline change below)
- Secret naming for Marius (distinct from Nova's `YT_*` convention): `YOUTUBE_CLIENT_ID`, `YOUTUBE_CLIENT_SECRET`, `YOUTUBE_REFRESH_TOKEN`
- `CLIP_BATCH_LIMIT = 8` in `video_generation.py` — max 8 new clips per scheduled run (Agnes free-tier quota), resumes automatically next run. A 45-shot script takes ~6 runs to fully clip.
- `AgnesOverloadedError` in `video_generation.py` exits quietly (exit 0, no GitHub issue) on transient Agnes overload — by design, so normal overload doesn't spam issues. Means a stalled script won't always show up as a failed run; check `video_next_index` in Supabase directly to confirm real progress vs. silent stall.

## Pipeline structure change — 2026-07-20 (dead code removed)
`image_generation.py` and its workflow (`image_generation.yml`) generated a still image per shot via Pollinations and wrote `image_urls` + status `images_generated` — but `video_generation.py` never read `image_urls`; it always generated video clips directly from `shot_list` text via Agnes. This was confirmed dead code (the repo's own `PLAYBOOK.md` already called `image_urls` "legacy/unused for new scripts").

**Removed:**
- `scripts/image_generation.py` — deleted.
- `.github/workflows/image_generation.yml` — content replaced with a retirement comment (left in place, disabled).

**Changed:**
- `scripts/narration.py` — final status changed from `"narrated"` to `"images_generated"` directly, so `video_generation.py` (which queries on that exact status string) picks it up with no gap. Log message updated to match.

**New pipeline flow:** `topic_research` → `script_writing` → `narration` (now sets `images_generated` directly) → `video_generation` → `thumbnail_generation` / `youtube_upload`.

The `images_generated` status name is now historical/misleading (no images involved) but left as-is since every downstream script (`video_generation.py`, `youtube_upload.py`, dashboards) keys off that exact string — renaming it would require touching every query, not worth the risk for a cosmetic fix.

## Fixes made 2026-07-20 (all confirmed live)

### 1. YouTube OAuth `invalid_grant` — FIXED
Root cause: refresh token had expired (Google OAuth consent screen constraint). Fixed by:
- Generating a new Client Secret in Google Cloud Console (old one couldn't be retrieved — Google no longer allows viewing existing secrets).
- Regenerating the refresh token via OAuth Playground with the new credentials.
- Updated GitHub secrets: `YOUTUBE_CLIENT_ID`, `YOUTUBE_CLIENT_SECRET`, `YOUTUBE_REFRESH_TOKEN`.
- Confirmed fixed: manual `youtube_upload.yml` run completed cleanly (no `invalid_grant`), correctly reported "No videos ready" since nothing was at `video_generated` status yet at the time.
- Publishing status checked: consent screen is in **Production** (not Testing), so this should not require re-doing every 7 days going forward.

### 2. Oversized burned-in captions — FIXED
Captions were rendering at font size 42 across 86% of frame width, wrapping into a block covering nearly half the screen on longer narration excerpts. In `scripts/video_generation.py`:
- `CAPTION_FONT_SIZE`: 42 → 28
- `CAPTION_MAX_WIDTH_RATIO`: 0.86 → 0.70
This is a constant change, applies to all future videos, not a one-off patch.

### 3. Original clip audio being discarded — FIXED
`assemble_final_video` was concatenating shot clips (which already carried usable ambience/music baked in by Agnes) via `concatenate_videoclips`, then calling `.with_audio(final_audio)` — which **replaces** a clip's audio track rather than layering onto it. The original per-clip audio was being silently thrown away every time, regardless of whether the generated music/SFX mix succeeded.
- Added `extract_original_clip_audio()` — pulls each shot's original audio track, volume-matched via new constant `ORIGINAL_CLIP_AUDIO_VOLUME = 0.30`.
- `build_audio_mix()` now takes this as an optional 4th layer alongside narration/music/SFX.
- Audio mix is now: narration + original clip ambience + background score + SFX, all through the existing safety limiter (`LIMITER_CEILING = 0.98`) so this can't cause clipping.

## Verified live pipeline state (queried directly, 2026-07-20 — RE-VERIFY before trusting)

| Status | Count |
|---|---|
| `archived` | 1 |
| `images_generated` | 9 |
| `uploaded` | 10 |

Topics in queue: 93.

### Scripts at `images_generated` (waiting on Video Generation), oldest first:
| Script ID | Clips done | Created |
|---|---|---|
| `e6de21d1-36f1-4723-880f-c8900b3522b4` | 32/45 | 2026-07-15 |
| `f86cea49-f741-40b2-8712-ea8aaed13442` | 0 | 2026-07-16 |
| `58f75bf2-e7ea-47fa-b34b-8705af1e49c2` | 0 | 2026-07-16 |
| `f53f3cc0-be59-41d5-8cc1-4d93bb257f0a` | 0 | 2026-07-16 |
| `78011fa8-7ce7-49f4-8443-2998afdc1fce` | 0 | 2026-07-17 |
| `d4015715-a3bd-4231-a1e7-0d405b6bedbf` | 0 | 2026-07-18 |
| `c34406d6-5123-41f9-807c-5758d9d83ad2` | 0 | 2026-07-18 |
| `c6d245b1-49a9-4a19-8c89-8f4a80c6d389` | 0 | 2026-07-19 |
| `3ad85abb-1719-4e4b-9480-7fae986209d3` | 0 | 2026-07-19 |

Video Generation only works the single oldest script at a time (8 clips/run); the rest queue behind it in order — this is normal, not stalled. `e6de21d1` (45 shots) has ~2 runs left before it moves to assembly/upload, then `f86cea49` starts.

## Open items / next steps — RE-VERIFY EACH BEFORE ACTING
1. Let `e6de21d1` finish clipping (13 shots left as of this writing) — should auto-assemble and flow to Thumbnail Generation + YouTube Upload once done.
2. Confirm the OAuth fix holds past the next natural token cycle — if `invalid_grant` recurs, check Production/Testing status first (already confirmed Production as of today, but re-verify).
3. Structural cleanup not yet done: `video_generation.py` is 1,100+ lines doing generation, audio mixing, captioning, and assembly all in one file — candidate for splitting into separate modules if Zia wants to revisit "code structure" further.
4. `d615192e-8707-4c1d-8f62-8f6b84e3d51e` (`archived` status) — still unresolved from a prior session, never discussed with Zia. Ask her directly if it matters.
