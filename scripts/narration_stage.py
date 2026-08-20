"""
Marius Command Center - Narration Stage
Stage 1 of script generation: produce a narration that clears the word-count
and CTA bar before the shot-list stage ever runs.

SPLIT OUT (2026-08-18): relocated from script_writing.py with no behavior
change. See script_writing.py's module docstring for full history.

WRITER/CHECKER SPLIT (2026-08-20, Loop Skill 2): after a draft clears the
existing deterministic checks (word count, CTA present), it's now also
graded by a fresh, independent LLM call (quality_checker.grade_narration)
against the channel's house rules before being accepted - catches quality
issues (weak hook, repetitive "gasping", generic CTA, truncated arc) that
pass the mechanical checks but violate the spirit of the rules the writer
was given. A checker rejection is treated exactly like any other content
failure below - same retry/wait/attempt-count loop, no new infra.
"""

import time

from llm_client import call_llm, extract_json, DailyQuotaExhausted, InfraFailure
from quality_checker import grade_narration

MIN_NARRATION_WORDS = 1500
NARRATION_MAX_ATTEMPTS = 3
NARRATION_MAX_CONTINUATIONS = 2
NARRATION_TARGET_WORDS = 1600
CONTENT_RETRY_WAIT_SECONDS = 25
MAX_INFRA_ATTEMPTS = 4

# BURST-RISK FIX (2026-08-15 evening, still applies under Gemini): every
# other retry path in this file waits between calls except the narration
# continuation loop, which fired back-to-back with zero delay.
CONTINUATION_CALL_DELAY_SECONDS = 10

CTA_KEYWORDS = (
    "comment", "comments", "subscribe", "share this", "share it",
    "like this", "like and", "tell us", "let us know", "hit follow",
    "hit that", "follow along", "leave a", "drop a",
)
CTA_SEARCH_WINDOW_CHARS = 700


def narration_has_engagement_cta(narration_text):
    if not narration_text:
        return False
    window = narration_text[-CTA_SEARCH_WINDOW_CHARS:].lower()
    return any(keyword in window for keyword in CTA_KEYWORDS)


def build_narration_prompt(title, angle):
    return f"""You are the head writer for "Erased," a YouTube documentary
channel telling real, historically documented true stories of ordinary people
caught in extraordinary historical moments, whose names history left out.

Episode topic: {title}
Angle: {angle}

Your ONLY job in this response is to write the full narration script. Do not
write anything else - no shot list, no JSON metadata, nothing but the
narration itself, wrapped in the JSON format specified at the bottom.

OPENING HOOK - this is the most important part of the script. The first 8
seconds of narration determine whether the viewer stays or leaves, so follow
this exact structure for the opening lines:

1. STAKE (first 1-2 sentences): State the single most dramatic, concrete fact
   of the story immediately. Do NOT say "today we'll look at" or "this is
   the story of" or introduce the channel/topic first. Lead with the fact itself,
   as if the viewer already knows what's at risk. Use a real, specific number,
   name, or consequence from the story - not a vague tease.
   Bad: "Today we're going to talk about a forgotten hero of history."
   Good: "140,000 men dug the trenches of the Western Front - and history
   erased every one of their names."

2. VISUAL LOCK (next 1 sentence): A concrete, specific image or moment that
   proves the stake is real - not generic scene-setting.

3. CURIOSITY GAP (next 1-2 sentences): Pose the specific question the rest of
   the episode answers, so the viewer needs to keep watching to find out.

Only after these opening beats should the script settle into the normal
narrative arc. No channel intro, no "welcome back," no restating the title -
go straight into the stake.

LENGTH IS A HARD REQUIREMENT: write a complete 10-12 minute narration script
of AT LEAST {MIN_NARRATION_WORDS} words - target {NARRATION_TARGET_WORDS}
words. This is not a suggestion or a rough guide - a narration under
{MIN_NARRATION_WORDS} words will be rejected outright and you will be asked
to continue writing from where you stopped. Do not stop early. Do not
summarize the rest of the story to wrap up quickly. Build a full narrative
arc: setup and stakes, rising complications, the core dramatic turn, the
emotional climax, and a reflective closing line - give each of these real
space, not a sentence or two each. If you don't know enough documented detail
about this specific story to reach the target, expand on the real historical
context, setting, sensory detail, and the emotional experience of the people
involved - do not pad with repetition or filler, and do not write a short
script assuming it will be extended later.

VARY EMOTIONAL BEATS - DO NOT DEFAULT TO GASPING: when describing a
character's reaction to shock, fear, or surprise, do not reach for "gasped"
or "gasping" as the default reaction verb. Real people react to tension in
many different physical and emotional ways - a held breath, a stiffened
posture, a dropped object, silence, a whispered word, trembling hands, a
racing pulse, frozen stillness, a sharp intake through the nose, clenched
fists. Choose the reaction that fits this specific moment and this specific
person, and vary it across the script - the same reaction beat should not
repeat more than once or twice in a single episode.

CALL TO ACTION - THIS IS REQUIRED, NOT OPTIONAL: immediately after the
emotional climax of the story and before the final reflective closing line,
you MUST write one natural, in-voice sentence encouraging the viewer to
like, subscribe, and share their own thoughts in the comments so more of
these erased stories get told. Every single script must include this - a
script with no call to action will be rejected and regenerated. It must
NOT be a generic "smash that like button" line - write it in the tone and
voice of this specific episode, using imagery or phrasing that echoes the
story just told, and vary the wording from episode to episode. It is part
of the narration itself, not a separate field. Use natural language that
clearly asks the viewer to like/share/subscribe and to respond in the
comments (for example, weaving in words like "comment," "share," or
"subscribe" naturally) so the ask is unambiguous, not just implied.

Return ONLY valid JSON, no other text, no markdown fences, in this exact
format:

{{
  "narration_text": "The full narration script as one string, written to be read aloud, at least {MIN_NARRATION_WORDS} words."
}}"""


def build_narration_continuation_prompt(title, angle, so_far, words_so_far):
    return f"""You are continuing a narration script for "Erased," a YouTube
documentary channel, that you started writing but stopped too early.

Episode topic: {title}
Angle: {angle}

Here is everything you have written so far ({words_so_far} words - the
target is at least {MIN_NARRATION_WORDS}, ideally {NARRATION_TARGET_WORDS}):

---
{so_far}
---

Continue writing EXACTLY where this leaves off. Do not repeat or rephrase
anything already written above. Do not restart the story or re-introduce it.
Pick up mid-narrative and keep building: more rising complications, sensory
and historical detail, the dramatic turn, the emotional climax, and (if not
already present above) end with the required call-to-action sentence
(naturally asking the viewer to like/subscribe/comment, in the voice of this
story) followed by a reflective closing line. Write enough new material to
bring the total well past {MIN_NARRATION_WORDS} words.

Return ONLY valid JSON, no other text, no markdown fences, in this exact
format:

{{
  "continuation_text": "Only the NEW text that continues on from where the narration above left off - do not repeat any of the text already given to you."
}}"""


def generate_narration(title, angle):
    """Stage 1: produce a narration that already clears the word-count and
    CTA bar before the (expensive, easy-to-fail) shot-list stage ever runs.
    A short first draft is extended via continuation calls rather than
    thrown away - continuation is far more reliable than a fresh retry for
    hitting a hard word floor, since the model is extending known-good text
    instead of trying to nail the whole length in one shot."""
    infra_attempt = 0
    content_attempt = 0
    last_reason = None
    ever_reached_content = False

    while content_attempt < NARRATION_MAX_ATTEMPTS:
        try:
            raw = call_llm(build_narration_prompt(title, angle))
        except DailyQuotaExhausted:
            # FIX (2026-08-15, later): must NOT be swallowed by the generic
            # RuntimeError/infra-retry handling below - propagate straight
            # up so main() can abort the whole run instead of retrying.
            raise
        except RuntimeError as e:
            infra_attempt += 1
            last_reason = f"Gemini call failed: {e}"
            print(f"[narration] Infra retry {infra_attempt}/{MAX_INFRA_ATTEMPTS} failed - {last_reason}")
            if infra_attempt >= MAX_INFRA_ATTEMPTS:
                break
            time.sleep(infra_attempt * 20)
            continue

        ever_reached_content = True
        content_attempt += 1
        try:
            parsed = extract_json(raw)
            narration = (parsed.get("narration_text") or "").strip()
        except ValueError as e:
            last_reason = f"JSON parse failed: {e}"
            print(f"[narration] Attempt {content_attempt}/{NARRATION_MAX_ATTEMPTS} failed - {last_reason}")
            if content_attempt < NARRATION_MAX_ATTEMPTS:
                time.sleep(CONTENT_RETRY_WAIT_SECONDS)
            continue

        if not narration:
            last_reason = "narration_text missing/empty"
            print(f"[narration] Attempt {content_attempt}/{NARRATION_MAX_ATTEMPTS} failed - {last_reason}")
            if content_attempt < NARRATION_MAX_ATTEMPTS:
                time.sleep(CONTENT_RETRY_WAIT_SECONDS)
            continue

        # Continuation loop: extend a short draft instead of discarding it.
        continuation_rounds = 0
        while (
            len(narration.split()) < MIN_NARRATION_WORDS
            and continuation_rounds < NARRATION_MAX_CONTINUATIONS
        ):
            continuation_rounds += 1
            words_so_far = len(narration.split())
            print(f"[narration] Draft is {words_so_far} words, below {MIN_NARRATION_WORDS} - "
                  f"continuation round {continuation_rounds}/{NARRATION_MAX_CONTINUATIONS}")
            time.sleep(CONTINUATION_CALL_DELAY_SECONDS)
            try:
                raw_cont = call_llm(build_narration_continuation_prompt(title, angle, narration, words_so_far))
                parsed_cont = extract_json(raw_cont)
                cont_text = (parsed_cont.get("continuation_text") or "").strip()
            except DailyQuotaExhausted:
                raise
            except (RuntimeError, ValueError) as e:
                print(f"[narration] Continuation round {continuation_rounds} failed ({e}), stopping continuation "
                      f"for this draft")
                break
            if cont_text:
                narration = narration.rstrip() + "\n\n" + cont_text.strip()

        word_count = len(narration.split())
        if word_count < MIN_NARRATION_WORDS:
            last_reason = f"narration still only {word_count} words after {continuation_rounds} continuation round(s)"
            print(f"[narration] Attempt {content_attempt}/{NARRATION_MAX_ATTEMPTS} failed - {last_reason}")
            if content_attempt < NARRATION_MAX_ATTEMPTS:
                time.sleep(CONTENT_RETRY_WAIT_SECONDS)
            continue

        if not narration_has_engagement_cta(narration):
            last_reason = "narration is missing the required like/subscribe/comment call-to-action near the end"
            print(f"[narration] Attempt {content_attempt}/{NARRATION_MAX_ATTEMPTS} failed - {last_reason}")
            if content_attempt < NARRATION_MAX_ATTEMPTS:
                time.sleep(CONTENT_RETRY_WAIT_SECONDS)
            continue

        # WRITER/CHECKER SPLIT (2026-08-20, Loop Skill 2): fresh independent
        # grading call against the house rules above, before acceptance.
        passed, grade_reason = grade_narration(title, angle, narration)
        if not passed:
            last_reason = f"checker rejected narration - {grade_reason}"
            print(f"[narration] Attempt {content_attempt}/{NARRATION_MAX_ATTEMPTS} failed - {last_reason}")
            if content_attempt < NARRATION_MAX_ATTEMPTS:
                time.sleep(CONTENT_RETRY_WAIT_SECONDS)
            continue

        print(f"[narration] Confirmed at {word_count} words - checker passed ({grade_reason}).")
        return narration

    if not ever_reached_content:
        raise InfraFailure(
            f"Gemini never returned a usable response after {infra_attempt} infra retries during "
            f"narration stage. Last reason: {last_reason}"
        )
    raise RuntimeError(f"Narration generation failed after {content_attempt} content attempts. Last reason: {last_reason}")
