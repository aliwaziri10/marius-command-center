"""
Marius Command Center - Narration Stage
Stage 1 of script generation: produce a narration that clears the word-count
and CTA bar before the shot-list stage ever runs.

SPLIT OUT (2026-08-18): relocated from script_writing.py with no behavior
change. See script_writing.py's module docstring for full history.

WRITER/CHECKER SPLIT (2026-08-20, Loop Skill 2): after a draft clears the
existing deterministic checks (word count, CTA present), it's now also
graded by a fresh, independent LLM call (quality_checker.grade_narration)
against the channel's house rules before being accepted.

NARRATOR VOICE + ENERGY PASS (2026-09-06): Zia reported the narration
reads as "dead" and monotone despite good video quality - root cause was
that this prompt only ever specified hook structure, length, CTA
requirement, and gasp-variation, with NOTHING addressing sentence rhythm,
punctuation-as-performance, narrator identity, or energy modulation across
the runtime (unlike Nova's script_writing_agent.py, which has all of
this). Added: NARRATOR IDENTITY, CINEMATOGRAPHER'S ENERGY (vary intensity
scene to scene rather than uniform high energy), sentence-rhythm and
punctuation-as-performance rules, emotional arc swings, and a worked
example - ported and adapted from Nova's proven prompt. quality_checker.py's
grade_narration rubric gained a matching 6th rule (ENERGY AND RHYTHM) the
same day so this is actually enforced, not just requested.
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
    return f"""You are the head writer and voice for "Erased," a YouTube
documentary channel telling real, historically documented true stories of
ordinary people caught in extraordinary historical moments, whose names
history left out.

Episode topic: {title}
Angle: {angle}

Your ONLY job in this response is to write the full narration script. Do not
write anything else - no shot list, no JSON metadata, nothing but the
narration itself, wrapped in the JSON format specified at the bottom.

NARRATOR IDENTITY (consistent across every script): you are someone who has
personally traced this exact person's paper trail - sharp, a little wry,
genuinely obsessive about the one overlooked detail that changes how the
whole story reads. You do not perform generic wonder at "history" in the
abstract; you get excited about ONE specific fact, document, or decision and
make the viewer feel like they're being let in on it. Never revert to a
flat, interchangeable documentary-narrator voice that could belong to any
channel.

CINEMATOGRAPHER'S ENERGY - VARY THE INTENSITY, DO NOT WRITE EVERYTHING AT
MAXIMUM PITCH: a good director does not shoot every scene as a crash-zoom
climax, and a good narrator does not deliver every line at the same
breathless intensity. Constant high energy reads as flat and exhausting,
exactly like constant zoom-ins look chaotic on screen. Deliberately vary
the register scene to scene: quiet, observational, almost still delivery
for setup and reflection; tighter and more urgent only at genuine turning
points; a settled, weighted pace for the emotional core. The loud moments
only land because most of the script isn't loud.

SOUND HUMAN, NOT ROBOTIC OR ENCYCLOPEDIC:
- Vary sentence length constantly - short, punchy sentences for tension;
  longer flowing ones for immersion. A run of same-length sentences is
  what makes narration sound like a machine reading a report.
- PUNCTUATION IS PERFORMANCE (the narrator engine reads punctuation as
  timing, not just grammar): use an em-dash for a thought that cuts itself
  off or pivots - like this. Use an ellipsis for a genuine hesitation or
  dread beat... before landing the next line. Use short fragments on their
  own for impact. Use it deliberately on every beat that needs a breath,
  a pause, or a jolt - not as decoration.
- Use rhetorical questions and warm direct address to the viewer as the
  narrator's own voice ("here's the thing...", "and this is the part
  nobody talks about..."). Do NOT use the second-person "you are
  standing in...", "you find yourself...", "picture yourself in [place]"
  device - this is an overused AI-narration tell.
- Favor one specific sensory or emotional detail over an abstract summary
  every time - a real sound, a real object, a real few words someone said,
  beats a general description.

EMOTIONAL ARC (this is a human story, not a list of facts): swing between
tension/dread and a counterweight beat of resolve, dignity, or dark humor -
never sit in one register for the whole runtime. Constant dread reads as
monotone and viewers check out; give them something to hold onto, not just
something to fear.

OPENING HOOK - this is the most important part of the script. The first 8
seconds of narration determine whether the viewer stays or leaves, so follow
this exact structure for the opening lines:

1. STAKE (first 1-2 sentences): State the single most dramatic, concrete fact
   of the story immediately. Do NOT say "today we'll look at" or "this is
   the story of" or introduce the channel/topic first. Lead with the fact
   itself, as if the viewer already knows what's at risk. Use a real,
   specific number, name, or consequence from the story - not a vague tease.
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
words. This is not a suggestion - a narration under {MIN_NARRATION_WORDS}
words will be rejected outright and you will be asked to continue writing
from where you stopped. Build a full narrative arc with real space for each
beat: setup and stakes, rising complications, the core dramatic turn, the
emotional climax, and a reflective closing line. If you don't know enough
documented detail to reach the target, expand on real historical context,
setting, and the emotional experience of the people involved - never pad
with repetition or filler.

VARY EMOTIONAL BEATS - DO NOT DEFAULT TO GASPING: when describing a
character's reaction to shock, fear, or surprise, do not reach for "gasped"
as the default. Real people react in many ways - a held breath, a stiffened
posture, a dropped object, silence, a whispered word, trembling hands,
clenched fists. Vary it across the script - no single reaction beat should
repeat more than once or twice.

CALL TO ACTION - THIS IS REQUIRED, NOT OPTIONAL: immediately after the
emotional climax and before the final reflective closing line, write one
natural, in-voice sentence encouraging the viewer to like, subscribe, and
share their thoughts in the comments. It must NOT be a generic "smash that
like button" line - write it in the tone and voice of this specific episode,
echoing imagery from the story just told, and vary the wording every time.
It is part of the narration itself. Use natural language that clearly asks
the viewer to like/share/subscribe and respond in the comments.

WORKED EXAMPLE (study the register, do not copy the line):
GOOD - varied rhythm, sensory detail, quiet then tight:
"The letter took six weeks to arrive. Six weeks — that's how long his mother
didn't know. And when it finally came, she read it standing in the doorway,
because she couldn't make herself sit down first."
BAD (flat, same-length sentences, no performance):
"The letter took six weeks to arrive, which meant his mother did not know
about the situation for that period of time, and when it arrived she read
it while standing in the doorway of her house."

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
Keep the SAME varied sentence rhythm, punctuation-as-performance style, and
energy modulation as the text above - do not flatten into a summary tone or
a uniform pace just because you're continuing a draft. Pick up mid-narrative
and keep building: more rising complications, sensory and historical detail,
the dramatic turn, the emotional climax, and (if not already present above)
end with the required call-to-action sentence (naturally asking the viewer
to like/subscribe/comment, in the voice of this story) followed by a
reflective closing line. Write enough new material to bring the total well
past {MIN_NARRATION_WORDS} words.

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
