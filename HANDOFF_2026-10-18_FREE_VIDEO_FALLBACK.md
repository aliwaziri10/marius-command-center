# HANDOFF 2026-10-18: Free backup video generator (Agnes queue full)

## Read this first (how to work with Zia)
- State out loud which GitHub account you are connected to before any GitHub work (this session: aliwaziri10).
- Zia is not technical. Plain words, click-by-click, ONE step at a time, then wait for him to come back.
- Every link or copy/paste item goes inside a code block.
- Be proactive on straightforward work. Push each file to the repo right after creating it.
- FREE ONLY. No credit-based, daily-credit, trial or paid tools. He has rejected, repeatedly: Seedance, Google Flow, PixVerse, Vidu, Renderforest, Pollinations (credit system now), Pixabay as a video generator. Do not suggest them again.
- His laptop is a basic Dell Inspiron 15: nothing that runs AI models locally (LTX Desktop needs a 16GB NVIDIA GPU, no).
- Workflow files (.github/workflows/*.yml) return 403 for the connector. Zia must commit those by hand (copy-paste into the GitHub web editor).
- Verify commits live on GitHub; do not trust older handoff notes.

## The problem
Agnes video generation (used by Marius, Nova and upgraded-journey / Tiny Lawn Tales) has returned 503 `video_queue_full` since about 2026-10-10. All video pipelines are stalled. Zia wants a free backup that keeps videos moving (target: 30 min to 1 hour long-form, with script, narration, SFX, video, like Agnes did).

## What was learned this session
- Marius pipeline: topic research -> script -> shot breakdown -> Edge TTS narration -> one Agnes clip per shot (4 to 12 s, longer shots chained from several clips) -> assembly. A long video is hundreds of short clips stitched, never one generation.
- scripts/agnes_client.py: uses model agnes-video-2.5-flash (switched 2026-10-18; the old v2.0 was retired 2026-09-25). On 503 video_queue_full it waits 120 s, up to 8 tries (~16 min), then raises AgnesOverloadedError.
- scripts/clip_generation.py: `_generate_one_segment_raw` calls create_agnes_task/poll_agnes_task and downloads the clip; this is the natural place to add a fallback. `fit_clip_to_duration` already exists for freeze-hold fits. Content-policy fallbacks (3 tiers) already exist there.
- Nova uses the same design (not read this session).

## Research findings (searches only, limits not tested by us)
- No free site generates unlimited AI video clips like Agnes. Hugging Face Spaces (LTX/Wan demos) are free but limited to ~2 to 8 s clips and a small daily GPU quota (shared anonymous quota, queues). Kaggle gives ~30 free GPU hours/week but needs a technical notebook setup. CogVideoX-Flash is listed as free in Zhipu docs (limits unverified).
- GitHub long-form tools found (Dima911-png/longform-video-generator, free-ai-video-generator, Auto_LongForm_VideoEngine, OpenMontage, MoneyPrinterTurbo) make narrated slideshows / stock-footage videos, not moving AI clips, and have no SFX. longform-video-generator's workflow is untested by its author and Google image quota may need billing.
- No free sound-effects generator was found.

## Chosen plan
Add a fallback to Marius's clip generation: when Agnes raises AgnesOverloadedError (queue full), fetch a matching real stock video clip for that shot from the Pexels API (free key) instead of stalling. Fits the documentary channels (Erased = Marius, Alternate Earth = Nova). It does NOT fit Tiny Lawn Tales (wordless snail cartoon), which needs Agnes. Pexels limits not yet checked.
- Must be fail-soft: if PEXELS_API_KEY is missing or Pexels fails, behave exactly as before.

## Status / next steps
1. DONE: Step 1 sent to Zia: get a free Pexels API key at https://www.pexels.com/api/ (do not paste it in chat). Waiting for him to confirm he has it.
2. NEXT (Zia, hand-edit): add the key as a GitHub Actions secret named PEXELS_API_KEY in the repo, and add it to the `env:` of the video-generation workflow (workflow yml must be edited by him; give copy-paste).
3. NEXT (Claude): write scripts/stock_fallback.py (Pexels search by shot description, download best landscape clip, trim/fit to duration) and hook it into clip_generation.py around the AgnesOverloadedError path. Push each file right after creating it, verify live.
4. THEN: check Pexels rate limits and licence terms, then port the same fallback to Nova.
5. Still open: free SFX source; whether Zia still wants a second AI-clip backup (Hugging Face / Kaggle) after the stock fallback works.
