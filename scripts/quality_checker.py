"""
Marius Command Center - Quality Checker (Loop Skill 2: writer/checker split)

A second, independent LLM call that grades the writer's own output against
the channel's house rules, using a FRESH call_llm() invocation with no
memory of having written it - the fresh-context/self-grading separation is
the same discipline behind "LLM-as-judge" evaluation and behind Anthropic's
own Claude Code guidance to have "a fresh model try to refute the result,
so the agent doing the work isn't the one grading it." (Every call_llm()
call is already stateless/fresh per-request - there's no shared
conversation state to leak between the writer and checker calls here, so
the separation this file adds is entirely about WHAT is graded, not about
manufacturing statelessness that already exists.)

Design choices, deliberately kept close to established practice rather than
invented from scratch:
- Force reasoning before the verdict (the JSON schema puts "reasoning"
  before "passed") - grading a claim before writing the reasoning for it is
  a known bias (verdict-first, rationalize-after) in LLM-as-judge setups.
- One pointwise pass/fail grade per artifact, not a numeric score - this
  pipeline needs a gate, not a leaderboard, so pass/fail plus a reason is
  the right shape.
- The checker grades against the SAME house rules already given to the
  writer (hook structure, CTA quality, documentary shot independence,
  etc.), not a separate invented rubric - the point is to catch cases that
  slip past the writer's own deterministic keyword/structural checks
  (narration_stage.py / shot_breakdown_stage.py) while still violating the
  spirit of those rules, not to add new requirements never given to the
  writer.
- Fails OPEN on infra failure (grader call itself times out / hits a
  quota wall after retries): logs a warning and lets the writer's output
  through rather than blocking the whole episode indefinitely on the
  checker being unavailable. The deterministic checks already gate the
  hard requirements; this is an added semantic layer, not the only line
  of defense.
- Slots into the EXISTING content-retry loop in each stage (a checker
  rejection is treated exactly like any other content-validation failure,
  same wait/retry/attempt-count logic) - no new retry infrastructure.
"""

from llm_client import call_llm, extract_json, DailyQuotaExhausted


def _run_grader(prompt, context_label):
    """Shared grading-call wrapper. Returns (passed: bool, reason: str).
    Fails OPEN (passed=True, reason notes the infra failure) if the grader
    call itself can't be completed - see module docstring."""
    try:
        raw = call_llm(prompt)
    except DailyQuotaExhausted:
        raise
    except RuntimeError as e:
        print(f"[checker] {context_label}: grader call failed ({e}) - failing OPEN, "
              f"accepting writer's output unchecked this attempt.")
        return True, f"checker unavailable ({e}) - not evaluated"

    try:
        parsed = extract_json(raw)
    except ValueError as e:
        print(f"[checker] {context_label}: grader response unparseable ({e}) - failing OPEN.")
        return True, f"checker response unparseable ({e}) - not evaluated"

    passed = bool(parsed.get("passed"))
    reasoning = (parsed.get("reasoning") or "").strip()
    issues = parsed.get("issues") or []
    if not passed:
        issue_text = "; ".join(str(i) for i in issues) if issues else "no specific issues listed"
        return False, f"{reasoning} | issues: {issue_text}"
    return True, reasoning


NARRATION_GRADER_RUBRIC = """You are the quality-control editor for "Erased,"
a YouTube documentary channel. You did NOT write the narration below - a
different writer did. Your only job is to grade it against this channel's
house rules, honestly and skeptically. Do not be lenient because it's
"good enough" - if a rule is violated, fail it.

Grade against these specific rules:

1. OPENING HOOK: the first 1-2 sentences must state the single most
   dramatic, concrete fact of the story immediately - a real number, name,
   or consequence. It must NOT open with "today we'll look at," "this is
   the story of," a channel introduction, or vague scene-setting.
2. CURIOSITY GAP: within the first few sentences, a specific question must
   be posed that the rest of the episode answers.
3. NO REPEATED "GASPING": reactions to shock/fear/surprise should be
   varied (held breath, stiffened posture, dropped object, trembling
   hands, etc.) - a script that leans on "gasped"/"gasping" more than
   once or twice, or uses it as the default reaction every time, fails.
4. CALL TO ACTION: there must be one natural, in-voice sentence (after the
   emotional climax, before the closing line) that clearly asks the viewer
   to like/subscribe/comment - it must NOT read as a generic, copy-pasted
   "smash that like button" line disconnected from the story's own
   imagery and voice.
5. NARRATIVE COMPLETENESS: the script must read as a complete arc (setup,
   rising complications, dramatic turn, emotional climax, reflective
   closing) - not a truncated or summarized ending, and not padded with
   repetitive filler to hit a word count.

Episode topic: {title}
Angle: {angle}

NARRATION TO GRADE:
---
{narration_text}
---

Return ONLY valid JSON, no other text, no markdown fences, in this exact
format (reasoning MUST come before the verdict - think it through before
you decide):

{{
  "reasoning": "Walk through each of the 5 rules above against the actual text, citing what you found for each one.",
  "issues": ["Short specific issue 1", "Short specific issue 2"],
  "passed": true
}}

Set "passed" to false if ANY of the 5 rules are violated. "issues" should
be empty if passed is true."""


def grade_narration(title, angle, narration_text):
    prompt = NARRATION_GRADER_RUBRIC.format(title=title, angle=angle, narration_text=narration_text)
    return _run_grader(prompt, "narration")


SHOT_BREAKDOWN_GRADER_RUBRIC = """You are the quality-control shot-list
editor for "Erased," a YouTube documentary channel. You did NOT write the
shot list below - a different director did. Your only job is to grade it
against this channel's house rules, honestly and skeptically. The shot
list has already passed mechanical/keyword checks (shot count, required
fields, banned-phrase scans) - your job is to catch violations that slip
past keyword matching because they're PARAPHRASED, not to re-check things
a keyword scan already covers well.

Grade against these specific rules, reading the shots as a sequence:

1. DOCUMENTARY SHOT INDEPENDENCE: every shot must show an action already
   complete/stable, not an action in progress that depends on the next
   shot to finish it - even when this is phrased in a way that dodges
   obvious continuation words like "continues" or "then."
2. PURPOSEFUL STILLNESS: every shot with a person in frame must show them
   doing something specific and concrete - not standing/waiting/sitting
   with an implied task rather than a stated one.
3. VISUAL CONSISTENCY: every shot must stay consistent with the given
   setting_and_characters anchor (same location/era/ethnicity, consistent
   recurring-character appearance) - flag any shot that seems to drift
   from it.
4. NATURAL PACING: shots should vary in type/movement - flag it if, reading
   the sequence as a whole, it feels monotonous or mechanically repetitive
   in a way the numeric checks (zoom ratio, consecutive-subject count)
   might not have caught.

Episode topic: {title}
Angle: {angle}

SETTING AND CHARACTERS (fixed anchor):
---
{setting_and_characters}
---

COLOR PALETTE (fixed anchor):
---
{color_palette}
---

SHOT LIST TO GRADE ({shot_count} shots):
---
{shot_list_text}
---

Return ONLY valid JSON, no other text, no markdown fences, in this exact
format (reasoning MUST come before the verdict - think it through before
you decide):

{{
  "reasoning": "Walk through each of the 4 rules above against the actual shots, citing shot numbers for anything you found.",
  "issues": ["Short specific issue naming a shot number, if any"],
  "passed": true
}}

Set "passed" to false if there's a clear, citable violation of any of the
4 rules above - not for minor stylistic preference. "issues" should be
empty if passed is true."""


def grade_shot_breakdown(title, angle, setting_and_characters, color_palette, shot_list):
    shot_list_text = "\n".join(
        f"{i + 1}. [{s.get('shot_type')}, {s.get('camera_movement')}] "
        f"{s.get('visual_description', '')} "
        f"(subject: {s.get('primary_subject') or 'none'}, location: {s.get('location_tag') or 'none'})"
        for i, s in enumerate(shot_list)
    )
    prompt = SHOT_BREAKDOWN_GRADER_RUBRIC.format(
        title=title, angle=angle,
        setting_and_characters=setting_and_characters,
        color_palette=color_palette,
        shot_count=len(shot_list),
        shot_list_text=shot_list_text,
    )
    return _run_grader(prompt, "shot_breakdown")
