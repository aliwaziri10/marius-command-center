# Marius Playbook (rarely changes — read alongside STATUS.md)

Repo: https://github.com/aliwaziri10/marius-command-center
Supabase: https://supabase.com/dashboard/project/swnjzzejsuupecdgbzzf
Zia is non-coder. Never ask her to explain the schema/structure - it's all below. Just tell her what to click.

## Pipeline order
Topic Research -> Script Writing -> Narration -> Image Generation -> Video Generation -> Assembly -> YouTube Upload.
Check STATUS.md for which stage the latest script is on, then help with the NEXT stage only.

## Database (Supabase table "scripts")
Columns: id, topic_id, narration_text, shot_list (jsonb - each shot has a "visual_description" field, NOT "description"/"visual"/"text"), status, narration_url, image_urls (jsonb array), video_urls (jsonb array), video_next_index (int), created_at.
Status values in order: pending -> narrated -> images_generated -> video_in_progress -> videos_generated.

## Storage buckets (all public)
narration (.wav files), images (.jpg, named <script_id>_shot_<n>.jpg), video_clips (.mp4, named <script_id>_clip_<n>.mp4), final_videos (not yet used).

## GitHub Actions secrets already set
SUPABASE_URL, SUPABASE_SECRET_KEY, OPENROUTER_API_KEY, AGNES_API_KEY, HF_TOKEN (currently unused - video gen uses Agnes, not Hugging Face - HF_TOKEN can be ignored/removed).

## Known gotchas already solved - do not rediscover these
- shot_list field is "visual_description" not "description".
- Kokoro voices file must be voices.bin (not voices.json) from the "model-files" release tag (not "model-files-v1.0").
- Kokoro raw audio is too quiet - must normalize_volume() before saving.
- Voice = am_adam (American), NOT bm_george (British) - Zarah explicitly chose Adam.
- Video generation uses Agnes AI (agnes-ai.com) - Zarah knowingly chose this over Hugging Face/LTX despite it being a newer, less established company, because free HF ZeroGPU quota (2-5 min/day) is too small for a 20-clip episode. Do not silently switch this back - ask first if considering a change.
- A green tick on a workflow does NOT mean it did real work - always verify counts in the database or files in the bucket.

## Remaining stages to build
Assembly (ffmpeg): stitch narration + video clips (or images with Ken Burns pan/zoom as fallback) into one file per script, upload to final_videos bucket.
YouTube Upload: needs Google Cloud OAuth setup first (not started), then title/description/thumbnail + containsSyntheticMedia disclosure field.

## Standing communication rules
Always give exact URLs in copy boxes, combined with what to click, in the same step. Always spell out Ctrl+A then Delete before any paste-replace. Max 3-4 steps per message, wait for confirmation. Never write real secrets into any file - GitHub secrets only. Do not add third-party AI services without asking first.
