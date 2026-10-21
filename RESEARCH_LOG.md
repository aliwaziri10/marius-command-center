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

## Loop 2, 2026-10-22: is there a better free AI-clip fallback than Kaggle?

Hypothesis: a free hosted video API would give more footage per day than Kaggle's free GPU.

Kaggle measurement (VERIFIED, from the run log Zia pasted, run https://github.com/aliwaziri10/marius-command-center/actions/runs/39632032160): 2 x Tesla T4. Wan2.2-TI2V-5B made 49 frames at 832x480 in 1542.7 s (load 250.5 s). LTX-Video made 97 frames at 704x480 in 702.2 s (load 253.3 s). Whole run about 48 minutes. Both clips downloaded. Clip quality NOT viewed by Claude. At LTX speed that is about 20 s of footage per GPU hour if 24 fps (fps not confirmed), so Kaggle cannot carry a daily 25 minute video. The 30 free GPU hours per week figure is UNVERIFIED.

Candidate: CogVideoX-Flash on the China platform bigmodel.cn.
- Primary source, official model overview https://docs.bigmodel.cn/cn/guide/start/model-overview lists CogVideoX-Flash as a free model (text and image input, AI sound effects, up to 10 s, up to 4K, 60 fps). This is the docs saying so, NOT an executed test: UNVERIFIED in practice.
- Secondary only (leads): the free tier is exposed only on the China platform and z.ai sells only paid models (dev.to article); free requests are queued at lower priority and rate limited at peak (dev.to, a third party MCP readme); clips are short and lower fidelity than top paid models (dev.to).
- UNVERIFIED and possibly a blocker: whether an account and key can be made without Chinese real-name verification (a third party readme says real-name verification is done 'as the platform requires'; the official Batch API FAQ says real-name verification is required for the Batch API). The brief says to discard anything needing an identity check Zia cannot pass.
- UNVERIFIED: commercial use terms of the free tier (a reference site says 'conditional').
- Rejected: third party gateways that resell the free tier with their own 'free key' (unknown terms, key trust). Also rejected by the brief: Hugging Face and every credit or trial based video tool.

Result: CogVideoX-Flash is the best candidate found, but nothing is proven. Only Zia can test sign up (identity check question). Plan stays: Agnes, then CogVideoX-Flash only if a key can be obtained, then stock footage, then still image zoom. Kaggle stays a rare extra for a few special shots, not a daily source.
