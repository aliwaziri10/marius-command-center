"""
Marius Command Center - Topic Research Agent
Generates new "Forgotten Names" episode topics: real, documented stories of
ordinary people caught in extraordinary historical moments.

Duplicate-checking is built in from the start (unlike Nova's early bug):
it fetches every existing topic title before generating new ones, and asks
the AI to avoid them, then double-checks the results itself.

PROVIDER SWITCH (2026-08-07): OpenRouter removed entirely, same as
script_writing.py. Zia's standing decision - OpenRouter caused repeated
free-tier model churn/outages across the pipeline, so it's dropped
everywhere, not just where it broke first. Gemini (same free
GEMINI_API_KEY already used by script_writing.py) is now the sole
provider - also a stronger, more consistent writer for this kind of
creative/narrative generation task than whatever model OpenRouter's
auto-router happens to route to.

MODEL FIX (2026-09-10): GEMINI_MODEL was still "gemini-3.5-flash" here,
the same deprecated name that broke script_writing.py on 2026-08-07
("no longer available to new users"). script_writing.py (via
llm_client.py) was switched to "gemini-3.5-flash-lite" at the time, but
this file was never updated - every topic_research run since has almost
certainly been failing on the same dead model name. Fixed by switching to
the shared llm_client.py entirely (see next note) instead of keeping a
second copy of the model name to drift out of sync again.

SHARED CLIENT + RELEVANCE CHECKER (2026-09-13): this file had its own
copy-pasted call_gemini() with no relation to llm_client.py's call_llm() -
half the retry budget (MAX_RETRIES=2 vs 4), no daily-quota detection, and
critically, no extract_json() repair pipeline at all: a single malformed-
JSON response here (the exact kind of thing shot_breakdown_stage.py has
hit repeatedly) would just crash this script outright with an unhandled
json.loads() error. Switched to the shared call_llm/extract_json from
llm_client.py, and added response_schema so Gemini's output is
structurally constrained here too - see llm_client.py's SCHEMA-CONSTRAINED
GENERATION note.

Separately: Zia reported the topics being generated had drifted toward
quaint, low-stakes daily-life vignettes (a baker, a flower vendor) with no
real peril or urgency - fine as a job description, but not why anyone
stops scrolling on a true-crime/history channel. Nothing in the old prompt
ever asked for STAKES, only "ordinary person, extraordinary moment," which
an LLM can satisfy with a technically-true but flat story just as easily
as a gripping one. Two changes: (1) the generation prompt now explicitly
requires real danger, moral urgency, or a hidden injustice - an occupation
is fine as the entry point (this channel's best-performing episodes are
built exactly that way: a radio operator, an ice-cream vendor), but the
tension has to come from the crisis around them, not the job itself; (2)
added a second independent grading call (grade_topic_candidates, same
writer/checker split already used for narration and shot breakdowns) that
scores each candidate on stakes/relevance before anything is saved.

GRADING MATCHED BY INDEX, NOT TITLE TEXT (2026-09-13, caught in review
before this was ever sent/committed): the first draft of
grade_topic_candidates matched each grade back to its candidate by
comparing title strings - fragile, since the grading call could plausibly
retype a title with slightly different punctuation/whitespace and a
genuinely good topic would then be silently discarded as "not graded" for
no real reason. Fixed to match by the candidate's 1-based position in the
list handed to the grader instead, which can't drift.

CANDIDATE COUNT LOOSENED (2026-09-13, same review): the response schema
originally forced Gemini to return EXACTLY NUM_CANDIDATE_TOPICS every
attempt (minItems == maxItems). On a later retry, once the exclude-list
has grown long, forcing an exact count risks the model padding with a
weak idea just to hit the number. Loosened to a range instead.
"""

import os
import requests

from llm_client import call_llm, extract_json

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SECRET_KEY"]

HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
}

NUM_NEW_TOPICS = 3
# RELEVANCE CHECKER (2026-09-13): oversample candidates since the grading
# pass below is expected to reject some of them - without this, a run
# that rejects even one candidate would fall short of NUM_NEW_TOPICS.
NUM_CANDIDATE_TOPICS_MIN = 4
NUM_CANDIDATE_TOPICS_MAX = 6
MAX_GENERATION_ATTEMPTS = 3

TOPIC_RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "topics": {
            "type": "ARRAY",
            "minItems": NUM_CANDIDATE_TOPICS_MIN,
            "maxItems": NUM_CANDIDATE_TOPICS_MAX,
            "items": {
                "type": "OBJECT",
                "properties": {
                    "title": {"type": "STRING"},
                    "angle": {"type": "STRING"},
                },
                "required": ["title", "angle"],
            },
        },
    },
    "required": ["topics"],
}

GRADE_RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "grades": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "index": {"type": "INTEGER"},
                    "passed": {"type": "BOOLEAN"},
                    "reason": {"type": "STRING"},
                },
                "required": ["index", "passed", "reason"],
            },
        },
    },
    "required": ["grades"],
}


def get_existing_titles():
    resp = requests.get(
        f"{SUPABASE_URL}/rest/v1/topics?select=title",
        headers=HEADERS,
        timeout=30,
    )
    resp.raise_for_status()
    return [row["title"] for row in resp.json()]


def generate_topic_candidates(exclude_titles):
    exclude_list = "\n".join(f"- {t}" for t in exclude_titles) or "(none yet)"

    prompt = f"""You are a research assistant for a YouTube documentary channel
called "Forgotten Names." Each episode tells a real, historically documented
true story about an ordinary person caught in an extraordinary historical
moment. Not famous leaders - overlooked, real individuals.

Do NOT suggest any of these already-used topics:
{exclude_list}

STAKES ARE MANDATORY (this is what makes someone stop scrolling and watch):
every topic must involve real danger, a life-or-death choice, a hidden
injustice, or a moral crisis the person faced - not just an interesting job
during an interesting time. An occupation (baker, vendor, switchman,
telegraph operator, nurse) is a perfectly good ENTRY POINT into a story,
but only if the surrounding crisis - a war, a genocide, a disaster, a
cover-up, a resistance movement - puts that person at real risk or forces
them into a real moral choice. Reject any idea in your own head first if
the honest one-sentence summary would be "a person did their ordinary job
during a historical period" with nothing more at stake than that - a
pleasant, low-stakes slice-of-life (a quiet bakery, a peaceful flower
garden, a calm daily routine) is exactly what this channel does NOT want,
no matter how historically interesting the setting is.

Generate between {NUM_CANDIDATE_TOPICS_MIN} and {NUM_CANDIDATE_TOPICS_MAX}
brand new episode topic ideas. For each one, the "angle" must make the
real stakes explicit: what was actually at risk, and what real choice or
danger the person faced. Return ONLY valid JSON, no other text, in this
exact format:

{{
  "topics": [
    {{"title": "Short episode title", "angle": "2-3 sentences: the real story, and explicitly what was at stake or what danger/choice the person faced"}}
  ]
}}"""

    raw = call_llm(prompt, response_schema=TOPIC_RESPONSE_SCHEMA)
    parsed = extract_json(raw)
    return parsed.get("topics") or []


def grade_topic_candidates(candidates):
    """WRITER/CHECKER SPLIT (2026-09-13): same pattern already proven for
    narration (quality_checker.py) and shot breakdowns
    (quality_checker.grade_shot_breakdown) - a fresh, independent LLM call
    grades the writer's own output against the house rule (real stakes,
    not a flat slice-of-life), instead of trusting the generation prompt
    alone to have been followed.

    Matched back to each candidate by its 1-based position in the listing
    handed to the grader, not by re-matching title text (see module
    docstring) - returns {0-based index: (passed, reason)}."""
    if not candidates:
        return {}

    listing = "\n".join(
        f'{i + 1}. "{c.get("title", "")}" - {c.get("angle", "")}'
        for i, c in enumerate(candidates)
    )

    prompt = f"""You are a strict editor for a YouTube documentary channel called
"Forgotten Names." Grade each candidate episode topic below against ONE rule:

PASS only if the topic involves real danger, a life-or-death choice, a
hidden injustice, or a moral crisis the person faced - something with real
stakes that would make a modern viewer stop scrolling and watch.

FAIL if the topic is a pleasant or merely "historically interesting"
slice-of-life with no real peril or moral weight - an ordinary job during
an interesting period, but nothing genuinely at stake (e.g. a quiet
bakery, a peaceful flower garden, a calm daily routine, a simple trade
with no danger attached).

Candidates:
{listing}

Return ONLY valid JSON, no other text, in this exact format, using the
NUMBER shown before each candidate above as "index" - do not retype the
title:

{{
  "grades": [
    {{"index": 1, "passed": true, "reason": "one short sentence"}}
  ]
}}"""

    raw = call_llm(prompt, response_schema=GRADE_RESPONSE_SCHEMA)
    parsed = extract_json(raw)
    grades = parsed.get("grades") or []
    result = {}
    for g in grades:
        idx = g.get("index")
        if isinstance(idx, int) and 1 <= idx <= len(candidates):
            result[idx - 1] = (g.get("passed", False), g.get("reason", ""))
    return result


def collect_approved_topics(existing_titles):
    """Loops up to MAX_GENERATION_ATTEMPTS times, oversampling candidates
    and grading them, until NUM_NEW_TOPICS approved topics are collected
    or the attempt budget runs out (in which case whatever passed so far
    is still returned - a partial batch of good topics beats blocking the
    whole run over one weak idea)."""
    approved = []
    seen_titles = set(t.lower() for t in existing_titles)

    for attempt in range(1, MAX_GENERATION_ATTEMPTS + 1):
        if len(approved) >= NUM_NEW_TOPICS:
            break

        exclude_titles = list(existing_titles) + [a["title"] for a in approved]
        candidates = generate_topic_candidates(exclude_titles)

        fresh_candidates = []
        for c in candidates:
            title = (c.get("title") or "").strip()
            angle = (c.get("angle") or "").strip()
            if not title or not angle:
                continue
            if title.lower() in seen_titles:
                print(f"[topics] Skipped duplicate candidate: {title}")
                continue
            fresh_candidates.append({"title": title, "angle": angle})

        if not fresh_candidates:
            print(f"[topics] Attempt {attempt}/{MAX_GENERATION_ATTEMPTS}: no fresh candidates returned.")
            continue

        grades = grade_topic_candidates(fresh_candidates)
        for i, c in enumerate(fresh_candidates):
            passed, reason = grades.get(i, (False, "not graded (missing from checker response)"))
            if passed:
                print(f"[topics] Approved: \"{c['title']}\" - {reason}")
                approved.append(c)
                seen_titles.add(c["title"].lower())
            else:
                print(f"[topics] Rejected (low stakes): \"{c['title']}\" - {reason}")

        if len(approved) < NUM_NEW_TOPICS and attempt < MAX_GENERATION_ATTEMPTS:
            print(f"[topics] Only {len(approved)}/{NUM_NEW_TOPICS} approved so far - generating more candidates...")

    return approved[:NUM_NEW_TOPICS]


def save_topic(title, angle):
    resp = requests.post(
        f"{SUPABASE_URL}/rest/v1/topics",
        headers={**HEADERS, "Prefer": "return=representation"},
        json={"title": title, "angle": angle, "status": "pending"},
        timeout=30,
    )
    resp.raise_for_status()
    print(f"Saved topic: {title}")


def main():
    existing = get_existing_titles()
    print(f"Found {len(existing)} existing topics.")

    approved_topics = collect_approved_topics(existing)
    if not approved_topics:
        print("No topics passed the stakes/relevance check this run - nothing saved.")
        return

    for topic in approved_topics:
        save_topic(topic["title"], topic["angle"])


if __name__ == "__main__":
    main()
