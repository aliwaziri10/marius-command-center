# Marius Playbook (rarely changes — read alongside STATUS.md)

Repo: https://github.com/aliwaziri10/marius-command-center
Supabase: https://supabase.com/dashboard/project/swnjzzejsuupecdgbzzf
Zarah is non-coder. Never ask her to explain the schema/structure - it's all below. Just tell her what to click.

## Pipeline order (CURRENT - do not use an older order)
Topic Research -> Script Writing -> Narration -> Video Generation -> YouTube Upload.
There is NO separate Image Generation stage and NO separate Assembly stage anymore. video_generation.py does both: generates a video clip per shot directly from text via Agnes AI, sizes each to match narration timing, stitches them together with narration audio, uploads ONE final file. Do not build or run a separate image_generation.py workflow even if old files/workflows for it still exist in the repo - they are abandoned, ignore them.

## Database (Supabase table "scripts")
Columns: id, topic_id, narration_text, shot_list (jsonb - each shot has "visual_description" for the visual and "narration_excerpt" for its matching narration text), status, narration_url, video_url (singular).
Status values in order: pending -> narrated -> video_generated.
Columns image_urls/video_urls/video_next_index still exist but are LEFTOVER/unused - ignore them.

## Storage buckets (all public)
narration (.wav), videos (final .mp4 per script - the only bucket video_generation.py uses).

## GitHub Actions secrets already set
SUPABASE_URL, SUPABASE_SECRET_KEY, OPENROUTER_API_KEY, AGNES_API_KEY.

## Known gotchas already solved - do not rediscover these
- Kokoro voices file must be voices.bin from the "model-files" release tag. Voice = am_adam.
- Agnes num_frames must equal 8*n+1 (e.g. 49, 169) - video_generation.py already handles this via round_to_valid_frames().
- Agnes video result polling uses GET https://apihub.agnes-ai.com/agnesapi?video_id=... - NOT /v1/videos/{id}. Already fixed in current code.
- Video generation uses Agnes AI (agnes-ai.com), a newer/less established company, chosen knowingly over Hugging Face/LTX due to HF's tiny free quota. Do not silently switch this back - ask first.
- A green tick on a workflow does NOT mean it did real work - always verify counts/files in the actual database or bucket.
- IMPORTANT: file edits confirmed by Zarah as "done" have repeatedly NOT actually been committed on GitHub. Always verify via the GitHub API or by re-reading the file, don't just trust a confirmation.
- video_generation.py has NO checkpoint/resume - if it fails partway through a 20-shot run, it must restart from shot 1. A single run can take 60-100+ minutes; this is normal.

## Remaining stage to build
YouTube Upload: needs Google Cloud OAuth setup first (not started), then title/description/thumbnail + containsSyntheticMedia disclosure field.

## Standing communication rules
Always give exact URLs in copy boxes, combined with what to click, in the same step. Always spell out Ctrl+A then Delete before any paste-replace. Max 3-4 steps per message, wait for confirmation. Never write real secrets into any file - GitHub secrets only. Do not add third-party AI services without asking first. ALWAYS give full file contents when editing code, never partial snippets.
