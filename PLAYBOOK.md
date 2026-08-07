# Marius Playbook (rarely changes — read alongside STATUS.md)

Repo: https://github.com/aliwaziri10/marius-command-center
Supabase: https://supabase.com/dashboard/project/swnjzzejsuupecdgbzzf
Zia is non-coder. Never ask him to explain the schema/structure - it's all below. Just tell him what to click.

## Pipeline order
Topic Research -> Script Writing -> Narration -> Video Generation -> YouTube Upload.
Narration generates the audio AND advances the script straight to `images_generated` - there is no separate Image Generation stage in the live pipeline. `scripts/image_generation.py` still exists as a file/workflow in the repo but is dead code - do not run it for new scripts.
Video Generation includes clip generation AND final assembly in one script (video_generation.py) - no separate Assembly stage.
Check STATUS.md for which stage the latest script is on, then help with the NEXT stage only.

## Database (Supabase table "scripts")
Columns: id, topic_id, narration_text, shot_list (jsonb - each shot has a "visual_description" field, NOT "description"/"visual"/"text"), status, narration_url, image_urls (jsonb array, legacy/unused for new scripts), video_urls (jsonb array - per-shot clip URLs), video_next_index (int - how many shots are done), video_url (text - final assembled video), created_at.
Status values in order: pending -> images_generated -> video_generated -> uploaded. (`narrated` is not a real status - narration jumps straight to `images_generated`.) `content_flagged` is a side-branch status: Agnes rejected a shot on content-policy grounds even after a fallback retry; needs a manual fix (reword the shot or replace it with a neutral filler) and a reset to `images_generated` to resume.
"video_generated" means the final assembled video (narration + all clips) is done and sitting in the videos bucket.

## Database (Supabase table "topics")
Columns: id, title, angle, status. Status values: pending -> scripted (becomes a row in `scripts`). `generation_failed` is a side-branch: Script Writing's LLM call or validation failed repeatedly; the topic is skipped by future runs until manually reworded and reset to `pending`.

## Storage buckets (all public)
narration (.wav/.mp3 files), images (.jpg, legacy/unused for new scripts), video_clips (.mp4, per-shot clips named <script_id>/shot_<n>.mp4, used as working storage during generation, also holds /refs/ subfolder with last-frame continuity images), videos (.mp4, final assembled video per script, named <script_id>.mp4).

## GitHub Actions secrets currently set
SUPABASE_URL, SUPABASE_SECRET_KEY, GEMINI_API_KEY, AGNES_API_KEY, ACE_MUSIC_API_KEY, FREESOUND_API_KEY, HF_TOKEN (currently unused - video gen uses Agnes, not Hugging Face - can be ignored/removed), YOUTUBE_CLIENT_ID, YOUTUBE_CLIENT_SECRET, YOUTUBE_REFRESH_TOKEN, EXPECTED_YOUTUBE_CHANNEL_TITLE.
**OPENROUTER_API_KEY was removed entirely on 2026-08-06.** Script Writing and Topic Research are now Gemini-only (`gemini-3.5-flash`), no fallback provider. Don't reference OpenRouter in future diagnosis - it's gone by design, not missing by accident.

## Known gotchas already solved - do not rediscover these
- shot_list field is "visual_description" not "description".
- Narration voice: edge-tts, `en-US-GuyNeural`. (Kokoro was tried and reverted - too slow/heavy on GitHub-hosted runners, caused ~25min stalls then runner kills. Chatterbox was also tried for a time and reverted for the same reason.)
- Video generation uses Agnes AI (agnes-ai.com) - Zia knowingly chose this over Hugging Face/LTX despite it being a newer, less established company, because free HF ZeroGPU quota (2-5 min/day) is too small for a full episode. Do not silently switch this back - ask first if considering a change.
- video_generation.py is resume-safe: it checks video_next_index and video_urls on the script row before generating anything, uploads each shot's clip individually to video_clips as soon as it's made, and saves progress after every single shot. Re-running it after a partial/interrupted run continues from where it stopped instead of regenerating finished shots. Do not remove this without a strong reason.
- A green tick on a workflow does NOT mean it did real work - always verify counts in the database or files in the bucket. A scheduled cron trigger can also be silently delayed by GitHub itself for hours - check actual run timestamps in the Actions tab before assuming the pipeline code is broken.
- Content-policy rejections (`content_flagged`) can be triggered by the anchor text (`setting_and_characters`, sent with every shot prompt) OR by the visual content of a specific shot itself, independent of any text fix. If a text-level fix (stripping sensitive words from the anchor) doesn't clear a stuck shot after a real retry, don't keep re-diagnosing the text - replace that one shot's `visual_description` with something generic and neutral (e.g. a static empty-room shot) and move on. Pipeline flow matters more than that one shot's fidelity.
- This repo is PUBLIC - GitHub Actions minutes are uncapped (the free-tier 2,000 min/month cap only applies to private repos). Don't hold back a scheduling/frequency change over an Actions-minutes budget that doesn't apply here.
- The AI assistant's GitHub connector is permanently read-only by design (not a setting Zia can change) - all code pushes go through Zia pasting into the GitHub web editor. Data-only fixes (status resets, shot_list rewording) don't need this - do those directly via Supabase.

## Remaining stages to build
YouTube Upload: done and live (see `scripts/youtube_upload.py`) - this section is historical, kept for context on what used to be outstanding.

## Standing communication rules
Always give exact URLs in copy boxes, combined with what to click, in the same step. Always spell out Ctrl+A then Delete before any paste-replace. Max 3-4 steps per message, wait for confirmation. Never write real secrets into any file - GitHub secrets only. Do not add third-party AI services without asking first. Minimize Zia's involvement - act on routine fixes without asking permission first; only ask when a decision is genuinely his to make.
