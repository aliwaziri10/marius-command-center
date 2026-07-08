# Marius Command Center — Continuation Log
**Last updated:** July 9, 2026 (v2 — paste this into a new chat to resume instantly)

## Project
YouTube channel **"Forgotten Names"** — real documented stories of ordinary people in extraordinary historical moments. Long-form (8-15 min), English first, Hindi dubbing later. Fully separate from Nova Command Center — no shared code/credentials.

## Architecture
- **No Railway.** GitHub Actions (free, 7GB RAM) does all processing on schedules. Supabase (free) = database + file storage.
- Repo: `https://github.com/aliwaziri10/marius-command-center` (owner: aliwaziri10)
- Supabase project: `marius`, region Mumbai (ap-south-1)
- Supabase URL: `https://swnjzzejsuupecdgbzzf.supabase.co`
- Supabase Publishable key: `sb_publishable_lTcvuqEcDMN4OHlJg2yOFw_hkj9uz_9`
- Supabase Secret key: `[REDACTED — stored in GitHub Actions secret SUPABASE_SECRET_KEY]`
- DB password: `[REDACTED — see Supabase dashboard > Project Settings > Database if needed again]`
- OpenRouter key: `[REDACTED — stored in GitHub Actions secret OPENROUTER_API_KEY]`
- All 3 keys already saved as GitHub Actions secrets: `SUPABASE_URL`, `SUPABASE_SECRET_KEY`, `OPENROUTER_API_KEY`

## Database tables (created, in Supabase)
`topics` (id, title, angle, status, created_at)
`scripts` (id, topic_id, narration_text, shot_list jsonb, status, created_at)
`videos` (id, script_id, narration_url, video_url, youtube_video_id, status, created_at)

## Pipeline status
1. **Topic Research** (`scripts/topic_research.py` + `.github/workflows/topic_research.yml`) — ✅ WORKING. Uses OpenRouter `openrouter/free` auto-router with retry/backoff (fixes 429 rate-limit issue). Runs every 6 hours. 3 topics generated so far, incl. "The Librarian Who Saved Baghdad."
2. **Script Writing** (`scripts/script_writing.py` + `.github/workflows/script_writing.yml`) — ✅ WORKING. Same OpenRouter approach. Runs twice daily. 1 script generated so far.
3. **Narration** (`scripts/narration.py` + `.github/workflows/narration.yml`) — ⚠️ IN PROGRESS. Storage bucket `narration` exists (public, 50MB limit). Pipeline works end-to-end (confirmed green tick) BUT voice quality rejected twice:
   - gTTS female voice → rejected, too robotic.
   - Microsoft edge-tts male voice → untested/inconclusive, user unsure.
   - **Currently switching to Kokoro TTS "Adam" voice** (same voice user liked on Nova — voice choice only, no Nova code reused). Requires `kokoro-onnx` + `soundfile` in requirements.txt, downloads model files from GitHub releases at runtime (works fine in GitHub Actions' 7GB RAM, unlike Railway).
   - **STATUS AT CUTOFF: mid-edit.** User was pasting the Kokoro version of `narration.py` and updated `requirements.txt` (3 lines: requests, kokoro-onnx, soundfile) into GitHub's web editor, but got confused by leftover old text in the edit box. Unclear if commit was completed.

## IMMEDIATE NEXT STEPS (resume here)
1. Confirm `requirements.txt` contains exactly:
   ```
   requests
   kokoro-onnx
   soundfile
   ```
2. Confirm `scripts/narration.py` contains the Kokoro/Adam version (uses `kokoro_onnx.Kokoro`, voice=`am_adam`, downloads model from `thewh1teagle/kokoro-onnx` GitHub releases). If either file looks wrong or still has old gTTS/edge-tts code mixed in, wipe the box completely (Ctrl+A, Delete) and paste fresh — never edit around old content.
3. Reset the one already-narrated script so it reruns:
   ```sql
   update scripts set status = 'pending' where status = 'narrated';
   ```
   Run in Supabase SQL Editor.
4. Run the Narration workflow manually (Actions → Narration → Run workflow). First run will be slow (60-90s) — downloads the voice model.
5. Check result in Supabase Storage → `narration` bucket → preview the audio. If Adam voice confirmed good, move to next untouched stage: **image/video generation** (not started), then **assembly** (not started), then **YouTube upload** (not started, needs `containsSyntheticMedia` disclosure field).

## Standing rules for this project
- Velorique is a complete non-coder. Every instruction: exact clicks, exact copy-paste boxes, full file content every time (never "see above").
- Max 3 steps per message, wait for confirmation.
- No Railway. No Nova Command Center code/IDs/credentials reused — ever.
- When editing an existing GitHub file: always select-all + delete first, then paste fresh content. Never edit around existing lines.
- If a GitHub Actions run fails: get the real error from inside the black log box under the failed step (e.g. "Run narration"), not the Annotations summary — the summary only ever says "Process completed with exit code 1" and hides the real reason.
