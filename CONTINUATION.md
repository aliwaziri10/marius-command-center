# Marius / Erased — Continuation Notes (2026-08-07)

## Where things stand
- TTS: edge-tts (en-US-GuyNeural), NOT Chatterbox. Chatterbox reverted 2026-08-06 — too slow/heavy on GitHub-hosted runners, caused ~25min stalls then runner kills.
- CODEMAP.json (auto-generated on every push to main via codemap.yml, using Python's ast module) is a read-aid for AI-assistant sessions to query code structure fast — it is NOT consumed by any runtime pipeline script. No pipeline behavior depends on it.
- Content-flagged root cause fixed and live on main: fallback strips ethnicity/atrocity terms from the Agnes anchor before retrying (primary prompt untouched). 3 scripts (9404bc29, 716623f1, 92dec2f9) reset to images_generated. Not yet proven under load — none have hit a genuinely borderline shot again yet.
- video_generation.py bottleneck still open: scripts stall on the known unfixed Agnes ~7s/169-frame freeze-loop cap. Proposed fix (split long shots into multiple Agnes calls, concatenate) not yet built.

## Open issue: script_writing.py crashing (unresolved)
Crashed 3x on 2026-08-06 (05:57, 10:28, 12:24 UTC). Zero new scripts since Aug 6 00:23 (script 82eb9746). Zero topics have generation_failed status despite 3 crashes, meaning the crash happens AFTER successful LLM generation — most likely in save_script() or mark_topic_scripted(), both outside the try/except in main(). Not confirmed (no Action log access). Not urgent — 204 pending topics queued, no backlog risk.
NEXT STEP: manually trigger script_writing.yml (workflow_dispatch), have Zia paste the failing step's error text.

## Older fix — still NOT PUSHED (blocked)
scripts/script_writing.py needs MIN_NARRATION_WORDS=900 and find_duplicate_shots() added to validate_and_normalize(), same reject-and-retry pattern as existing CTA/hook checks. Root-caused the lighthouse video (Tz2Q52A8YC8) freeze: narration was ~320 words, script padded 10 real shots to 60 by repeating them 6x.

## Blocker (still open, reconfirmed 2026-08-07)
GitHub write access (create_or_update_file and push_files) still returns 403 "Resource not accessible by integration" on this repo. Reads work fine. Zia needs to grant Contents: Read & Write to the GitHub connector/App for this specific repo before any code fix can be pushed directly.
