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
"""

import os
import json
import time
import requests

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SECRET_KEY"]
GEMINI_KEY = os.environ["GEMINI_API_KEY"]

HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
}

NUM_NEW_TOPICS = 3
MAX_RETRIES = 4

GEMINI_MODEL = "gemini-3.5-flash-lite"
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GEMINI_KEY}"


def get_existing_titles():
    resp = requests.get(
        f"{SUPABASE_URL}/rest/v1/topics?select=title",
        headers=HEADERS,
        timeout=30,
    )
    resp.raise_for_status()
    return [row["title"] for row in resp.json()]


def call_gemini(prompt):
    """Sole provider - OpenRouter removed. Retries with backoff on 429s
    and transient errors, same pattern as script_writing.py's call_llm."""
    body = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
    }).encode()
    last_error = None
    for attempt in range(MAX_RETRIES):
        try:
            resp = requests.post(
                GEMINI_URL,
                data=body,
                headers={"Content-Type": "application/json"},
                timeout=90,
            )
        except (requests.exceptions.ChunkedEncodingError,
                requests.exceptions.ConnectionError,
                requests.exceptions.Timeout) as e:
            wait = (attempt + 1) * 15
            print(f"Gemini network error ({e.__class__.__name__}: {e}), waiting {wait}s before retry...")
            last_error = e
            time.sleep(wait)
            continue

        if resp.status_code == 429:
            wait = (attempt + 1) * 15
            print(f"Gemini rate limited, waiting {wait}s before retry...")
            last_error = resp
            time.sleep(wait)
            continue

        try:
            resp.raise_for_status()
        except requests.exceptions.HTTPError as e:
            wait = (attempt + 1) * 15
            print(f"Gemini HTTP error {resp.status_code} ({e}): {resp.text[:300]}, waiting {wait}s before retry...")
            last_error = resp
            time.sleep(wait)
            continue

        try:
            return resp.json()["candidates"][0]["content"]["parts"][0]["text"]
        except (requests.exceptions.JSONDecodeError, KeyError, IndexError) as e:
            wait = (attempt + 1) * 15
            print(f"Gemini response envelope malformed/unparseable ({e}), waiting {wait}s before retry...")
            last_error = e
            time.sleep(wait)
            continue

    raise RuntimeError(f"Gemini still failing after {MAX_RETRIES} attempts: {last_error}")


def generate_topics(existing_titles):
    exclude_list = "\n".join(f"- {t}" for t in existing_titles) or "(none yet)"

    prompt = f"""You are a research assistant for a YouTube documentary channel
called "Forgotten Names." Each episode tells a real, historically documented
true story about an ordinary person caught in an extraordinary historical
moment. Not famous leaders - overlooked, real individuals.

Do NOT suggest any of these already-used topics:
{exclude_list}

Generate {NUM_NEW_TOPICS} brand new episode topic ideas. Return ONLY valid JSON,
no other text, in this exact format:

[
  {{"title": "Short episode title", "angle": "2-3 sentence description of the real story and why it matters"}}
]"""

    content = call_gemini(prompt).strip()
    if content.startswith("```"):
        content = content.split("```")[1]
        if content.startswith("json"):
            content = content[4:]
    return json.loads(content.strip())


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

    new_topics = generate_topics(existing)

    existing_lower = [t.lower() for t in existing]
    for topic in new_topics:
        title = topic.get("title", "").strip()
        angle = topic.get("angle", "").strip()
        if not title:
            continue
        if title.lower() in existing_lower:
            print(f"Skipped duplicate: {title}")
            continue
        save_topic(title, angle)


if __name__ == "__main__":
    main()
