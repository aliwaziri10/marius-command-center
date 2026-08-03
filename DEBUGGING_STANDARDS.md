# Debugging Standards — Read Before Diagnosing Any Bug

Applies to any AI assistant or person debugging Nova, Marius, or TechPulse.

Before presenting any root cause or diagnosis as fact:

1. Trace the actual failure end-to-end in the real code — open and read the exact file/function involved. Never infer a cause from a filename, a comment, or a plausible-sounding theory.

2. Cross-check every claim against live data (Supabase/GitHub/actual product output) — never conclude from a single data point.

3. Actively look for contradicting evidence before settling on an explanation. If the theory is "X is broken," check the real-world output (e.g. the actual YouTube channel, actual storage bucket) — not just an internal status flag, since status/flags can be stale or manually edited and not reflect reality.

4. Explicitly rule out at least one alternative explanation before presenting a conclusion.

5. If a theory doesn't fully explain every observed symptom, say so out loud and keep investigating instead of presenting a partial explanation as the root cause.

6. Do not state a root cause with confidence until it has been verified from at least two independent angles (e.g. code logic + live data, or DB state + real-world output).

7. If full verification isn't possible with available tools, say exactly what remains unverified — do not present a guess as confirmed.

## Log of past mistakes (add to this, don't delete)

- 2026-08-04 (Marius): Diagnosed Video Generation "finishing in 2 minutes" as an Agnes API account block, based only on a Cloudflare page shown once. Zia proved this wrong by showing 19 real YouTube uploads through Aug 1. Real picture: two separate issues existed — (a) Agnes genuinely failing on the newest stuck script, and (b) 19 old `archived` scripts sitting in the DB, wrongly assumed to be "already uploaded duplicates" until checked title-by-title against the real YouTube upload list — only 1 of 19 was actually a duplicate.
## Account ownership — check this BEFORE assuming any API account is "blocked"

The Agnes AI account that owns the real working API keys (`marius`, `Nova Command Center`) was created and is logged into via **aliwaziri10.2@gmail.com** — NOT any zia-owned email/profile. If a dashboard login shows "you have been blocked" or looks empty/wrong, check which email you're logged in as FIRST. Logging into the wrong email will look identical to an account being blocked, but it isn't — it's just the wrong account. This applies to every AI assistant profile/session working on this project going forward.
