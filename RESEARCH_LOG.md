# RESEARCH LOG (fallback-chain branch)

Every claim is VERIFIED (with the Actions run link and a raw excerpt) or UNVERIFIED.
RESULTS.md is overwritten on every push, so the excerpts that matter are copied here.
No key or secret is ever written in this file.

## Loop 1, 2026-10-18: do the free sources work from a real Actions run?

Hypothesis: Pixabay (with Zia's key), NASA, Internet Archive and Wikimedia Commons can each be searched and a file reached from a GitHub Actions runner, and Agnes can be checked quickly.

Run: https://github.com/aliwaziri10/marius-command-center/actions/runs/39128247942 (commit f0183833e6b44ffd0b0f8caa10a7da42d1b07a41, 2026-10-18 12:40 UTC)

### VERIFIED

1. Pixabay video search works with the PIXABAY_API_KEY secret. Both a short query and a 100 character prompt-like query returned HTTP 200 with 3 hits.
   Raw: `rate-limit headers {'X-RateLimit-Limit': '100', 'X-RateLimit-Remaining': '99', 'X-RateLimit-Reset': '60'}` and `totalHits=500, returned=3`.
2. A Pixabay clip file is reachable. Raw: `file check HTTP 200, content-type video/mp4, first bytes read 1024`.
3. For the first Pixabay hit, the `small` rendition was 960x540 (not 1280x720). Raw: `first hit id=283533 duration=40s small=960x540`. The `large` rendition of that hit is listed as 1920x1080.
4. NASA Image and Video Library works with no key: search and asset lookup returned HTTP 200, and mp4 variants were `orig, large, medium, mobile, preview, small`. Raw: `file check HTTP 206, content-type video/mp4, first bytes read 1024`.
5. Internet Archive works with no key. The top Prelinger item had `licenseurl=http://creativecommons.org/licenses/publicdomain/` and an h.264 mp4 of 68512128 bytes. Raw: `file check HTTP 206, content-type video/mp4`.
6. Wikimedia Commons works with no key when a descriptive User-Agent is sent. The first video was a 1920x1080 webm, licence CC BY 4.0, attribution required: true. Raw: `file check HTTP 206, content-type video/webm`.
7. Agnes answers a full queue fast. From the Actions runner, POST /v1/videos returned HTTP 503 `video_queue_full` in 0.32 seconds. Raw: `{"code":"video_queue_full","message":"video queue is full, please retry later ..."}`. So a quick check with a circuit breaker is the right design, and the current 8 x 120 s wait (about 16 minutes per shot) is not needed to learn that Agnes is full.
8. At 12:40 UTC on 2026-10-18 Agnes Flash was full. This is one sample, not a pattern.

### UNVERIFIED

- Whether the Pixabay `medium` rendition is 1920x1080 as the docs say (only `small` was measured).
- Whether search results are relevant to a real shot. Hit counts were measured, relevance was not.
- Rate limits for NASA, Internet Archive and Wikimedia (not measured, only 2 to 3 calls each were made).
- NASA licence per item (the NASA guidelines page is cited, each item must still be checked).
- Pexels (no PEXELS_API_KEY in the run, skipped).
- Whether the HF_TOKEN secret is used for any call. It is read in scripts/assembly_stage.py (`os.environ.get`). The repo PLAYBOOK says it is unused. Not yet confirmed from the rest of that file. It will not be used.
- Agnes Flash clip size (the handoff says 1280x704, not measured by us).

### Next hypothesis

A stock clip can be fitted to 1280x720 and the exact shot duration, with no black frames or frozen stretches, using moviepy and ffmpeg inside an Actions run. Test next: build scripts/stock_fallback.py, then a standalone test of about 25 minutes made only from stock clips plus Edge TTS narration, run in Actions.
