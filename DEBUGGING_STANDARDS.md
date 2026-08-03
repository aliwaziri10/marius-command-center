# Marius Command Center — Handoff Sheet
Written: 2026-08-04, by Claude. Verified live against Supabase (`swnjzzejsuupecdgbzzf`) at time of writing.

## ⚠️ STANDING RULE — READ THIS FIRST
Do not trust this document at face value. Re-verify every claim against live Supabase/GitHub before acting. See also `DEBUGGING_STANDARDS.md` in this repo — read it before diagnosing any bug.

## Account ownership (resolved 2026-08-04, was a real source of confusion)
The Agnes AI account holding the real working API keys (`marius`, `Nova Command Center`) is owned by **aliwaziri10.2@gmail.com**, not any Zia-owned login. A "you have been blocked" Cloudflare page on the Agnes dashboard was caused by being logged into the WRONG email — the actual account and its keys are fine. Check which email you're logged in as before assuming an account/key problem.

## Live script status counts (2026-08-04)
| Status | Count |
|---|---|
| `archived` | 18 |
| `content_flagged` | 3 |
| `pending` | 1 |
| `uploaded` | 16 |

## Script `92dec2f9` — resolved diagnosis (2026-08-04)
Was assumed stuck due to an Agnes account block — WRONG, see above. Real cause, verified live: `character_reference_url` populated successfully (Agnes account/key working fine), but shot generation was rejected on content-policy grounds (likely the WWII/Nazi flag imagery in the prompt), retried once with fallback, failed again, auto-flagged `content_flagged` by the pipeline's own designed behavior. To resume: reword the flagged shot's `visual_description` in `shot_list`, then reset status to `images_generated`.

## Deleted 2026-08-04
Script `97becca1-0b6b-4bbc-b955-ffe644df54b1` ("The Librarian of Red Emma, Detroit") — deleted. Confirmed duplicate: this exact title was already live on YouTube (uploaded 2026-07-31 under a different script). This was an old abandoned attempt at the same topic, only 16/60 clips done, safe to remove.

## 18 archived scripts — NOT deleted, contain real unfinished work
Checked every one of the (formerly 19, now 18) `archived` scripts' topic title against the actual YouTube channel upload list (not just DB status, which can be stale/wrong). Only 1 was a real duplicate (deleted above). The other 18 are unique topics never published, with real Agnes-generated progress already paid for:
- 4 scripts are 45–73% done (`The Scavenger of the Great Stink` 38/70, `The Mail Battalion's Last Witness` 51/70, `The San Francisco Resident...` 42/85, `The Courier of the Siege of Sarajevo` 37/82)
- 14 others range 0–18 clips done
None have been reset yet — still sitting at `archived`, not in the active queue. Resume by setting status back to `images_generated` (pipeline is resume-safe, will continue from `video_next_index`).

## Reusable references
- Supabase project ID: `swnjzzejsuupecdgbzzf`
- GitHub repo: `https://github.com/aliwaziri10/marius-command-center`
- GitHub Actions: `https://github.com/aliwaziri10/marius-command-center/actions`
- YouTube channel: "Erased From History" (`@erased.fromhistory`, channel ID `UC2VOrDdsqMEc33kvK3u4JXA`)
- GitHub `create_or_update_file` API write returns 403 — all code/doc changes go through Zia pasting into GitHub web editor.
- `CLIP_BATCH_LIMIT = 8` in `video_generation.py` — max 8 new clips per scheduled run, resumes automatically. `AgnesOverloadedError` exits quietly (exit 0, no GitHub issue) on transient overload by design — check `video_next_index` in Supabase directly to see real progress, don't rely on issue count alone.
