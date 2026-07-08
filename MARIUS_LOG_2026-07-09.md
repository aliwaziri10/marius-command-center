# Marius Command Center — Progress Log
**Last updated:** July 9, 2026

## What Marius Is
Automated YouTube documentary channel: **"Forgotten Names"** — real, documented stories of ordinary people caught in extraordinary historical moments. Long-form (8–15 min) to start. English first, dub into Hindi and other languages once the format is proven and monetized.

Fully separate system from Nova Command Center — no shared code, no shared credentials, no shared channel.

## Why This Niche/Format
- YouTube's 2026 "inauthentic content" policy demonetizes mass-produced, templated, whatever's-trending content — evaluated at the whole-channel level, not just per video.
- Safe path: one consistent named identity, one clear angle, real research per video, not a trend-chasing multi-niche factory.
- Reuses the production pattern already proven on Nova (script → narration → visuals → assembly), just with new code, new content, new channel.

## Architecture Decision
- **No Railway, no always-on server** (this is what broke Nova via free-tier memory limits).
- **GitHub Actions** — free, 7GB RAM runners, does all heavy processing on a schedule.
- **Supabase** — free Postgres database + file storage, replaces Railway entirely.

## Accounts & Project Setup — DONE
- GitHub account: `aliwaziri10`
- Repo: https://github.com/aliwaziri10/marius-command-center (Public)
- Supabase org: Marius (Personal, Free plan)
- Supabase project: `marius`, region **South Asia (Mumbai) ap-south-1**
- Supabase Project URL: `https://swnjzzejsuupecdgbzzf.supabase.co`
- Database password: generated, saved (starts `r4dt...`, stored in this session's history)
- Supabase Publishable key: saved (starts `sb_publishable_lTcv...`)
- Supabase Secret key: saved (starts `sb_secret_Kfhs5...`)
- Both keys stored as **GitHub Actions repository secrets**: `SUPABASE_URL`, `SUPABASE_SECRET_KEY` — confirmed added.

## Next Steps (not started yet)
1. Create database tables in Supabase (topics, scripts, videos tracking) via SQL Editor.
2. Build topic research script (GitHub Actions) — no duplicate-topic bug this time, unlike Nova's.
3. Build script-writing agent.
4. Build narration (TTS) agent.
5. Build image/video generation agent.
6. Build assembly agent.
7. Build YouTube upload script with proper AI-disclosure metadata (`containsSyntheticMedia` field).
8. Wire full automation via GitHub Actions schedule — zero manual clicking.

## Standing Rules For This Project
- Velorique is a non-coder — every instruction must be exact, copy-paste boxes for anything typed, plain click/select instructions for everything else.
- Max 3 steps per message, then wait for confirmation.
- No Nova Command Center code, IDs, or infrastructure reused.
