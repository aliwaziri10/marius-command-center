# Marius Playbook (rarely changes — read alongside STATUS.md)

Repo: https://github.com/aliwaziri10/marius-command-center
Supabase: https://supabase.com/dashboard/project/swnjzzejsuupecdgbzzf
Google Cloud project: marius-command-center (owned by ziawaziri@gmail.com, the YouTube channel account)
Zarah is non-coder. Never ask her to explain the schema/structure - it's all below. Just tell her what to click.

## Pipeline order (CURRENT - do not use an older order)
Topic Research -> Script Writing -> Narration -> Video Generation -> YouTube Upload.
There is NO separate Image Generation stage and NO separate Assembly stage. video_generation.py does both: generates a video clip per shot directly from text via Agnes AI, sizes each to match narration timing, stitches with narration audio, uploads ONE final file. Ignore any old image_generation.py/workflow if still present - abandoned.

## Database (Supabase table "scripts")
Columns: id, topic_id, narration_text, shot_list (jsonb - "visual_description" for visual, "narration_excerpt" for matching narration), status, narration_url, video_url (singular).
Status values: pending -> narrated -> video_generated.
image_urls/video_urls/video_next_index columns still exist but are unused leftovers - ignore.

## Storage buckets (all public)
narration (.wav), videos (final .mp4 per script).

## GitHub Actions secrets currently set
SUPABASE_URL, SUPABASE_SECRET_KEY, OPENROUTER_API_KEY, AGNES_API_KEY, YOUTUBE_CLIENT_ID, YOUTUBE_CLIENT_SECRET, YOUTUBE_REFRESH_TOKEN. (HF_TOKEN also exists but is unused, safe to remove.)

## YouTube OAuth status (as of this writing)
Google Cloud project "marius-command-center" created under ziawaziri@gmail.com. YouTube Data API v3 enabled. TWO OAuth clients exist: "marius-uploader" (Desktop type, UNUSED, do not use) and "marius-uploader-web" (Web application type, THIS IS THE ONE IN USE - client ID starts with 264653492219-8orr0...). YOUTUBE_CLIENT_ID/SECRET/REFRESH_TOKEN in GitHub all correctly match the Web app client as of now.
IMPORTANT UNRESOLVED ISSUE: the app is still in "Testing" publish status on the OAuth consent screen, which caps refresh tokens at 7 days (not indefinite). This WILL break uploads after 7 days from token creation unless fixed. Fix = publish the OAuth consent screen to "Production" (Google Cloud Console -> APIs & Services -> OAuth consent screen -> Publish App). This does NOT require Google's full verification review for apps only requesting the youtube.upload scope in this way, but confirm before relying on it. This was not yet done as of this writing - do it before the 7-day window expires, or the refresh token will need to be regenerated via the whole OAuth Playground flow again.
The upload step in video_generation.py (or a separate youtube_upload.py) has NOT been written yet - only the OAuth credentials exist so far.

## Known gotchas already solved - do not rediscover these
- Kokoro voices file must be voices.bin from the "model-files" release tag. Voice = am_adam.
- Agnes num_frames must equal 8*n+1 (e.g. 49, 169) - already handled via round_to_valid_frames().
- Agnes video result polling uses GET https://apihub.agnes-ai.com/agnesapi?video_id=... (not /v1/videos/{id}) - already fixed.
- Video generation uses Agnes AI (agnes-ai.com), chosen knowingly over Hugging Face/LTX due to HF's tiny free quota (2-5 min/day). Do not silently switch back - ask first.
- A green tick on a workflow does NOT mean it did real work - always verify counts/files in the actual database or bucket.
- Zarah's "done"/"." confirmations have repeatedly NOT meant a GitHub commit actually landed, AND fetch tools (raw.githubusercontent.com and api.github.com) have both been unreliable in other Claude sessions (silent empty results, rate limits, one session fabricated file contents entirely without noticing). Always verify file contents independently before trusting either a human confirmation or a fetch result - re-fetch if anything seems inconsistent, and say so if a fetch tool seems broken rather than guessing.
- Google OAuth Playground's "use your own OAuth credentials" setting is unreliable/gets silently wiped on redirect. If a token exchange fails with "unauthorized_client" and the request body shows client_id=407408718192... (Google's own default test client), the custom credentials reverted - re-enter them and use the Playground's own "Authorize APIs" button (not a manually typed auth URL) without closing the settings popup in between, then check the gear icon again immediately upon return before clicking anything else.
- OAuth client type matters: "Desktop app" type does NOT support custom redirect URIs needed for OAuth Playground - must use "Web application" type with redirect URI https://developers.google.com/oauthplayground added.
- video_generation.py has NO checkpoint/resume - if it fails partway through a 20-shot run, it must restart from shot 1. A single run can take 60-100+ minutes; this is normal, not stuck.

## Remaining work
1. Fix YouTube OAuth 7-day token expiry (publish app to Production - see above).
2. Write the actual YouTube upload code (title/description generation from script data, thumbnail, containsSyntheticMedia disclosure field, using the saved OAuth credentials to upload the video from the "videos" bucket).
3. Confirm video_generation.py itself completes a full successful run end to end (was in progress as of this writing, for script e7a4dea1-a29f-47e5-a0e4-9944f4bc9b35).

## Standing communication rules
Always give exact URLs in copy boxes, combined with what to click, in the same step. Always spell out Ctrl+A then Delete before any paste-replace. Max 3-4 steps per message, wait for confirmation. Never write real secrets into any file - GitHub secrets only. Do not add third-party AI services without asking first. ALWAYS give full file contents when editing code, never partial snippets. Act proactively rather than asking permission for obvious next steps like updating this file.
