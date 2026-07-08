"""
Marius Command Center - Topic Research Agent
Generates new "Forgotten Names" episode topics: real, documented stories of
ordinary people caught in extraordinary historical moments.

Duplicate-checking is built in from the start (unlike Nova's early bug):
it fetches every existing topic title before generating new ones, and asks
the AI to avoid them, then double-checks the results itself.

Uses OpenRouter's auto-router (openrouter/free) with retries, so a busy
individual free model doesn't fail the whole run.
"""

import os
import json
import time
import requests

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SECRET_KEY"]
OPENROUTER_KEY = os.environ["OPENROUTER_API_KEY"]

HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
}

NUM_NEW_TOPICS = 3
MAX_RETRIES = 4


def get_existing_titles():
    resp = requests.get(
        f"{SUPABASE_URL}/rest/v1/topics?select=title",
        headers=HEADERS,
        timeout=30,
    )
    resp.raise_for_status()
    return [row["title"] for row in resp.json()]


def call_openrouter(prompt):
    """Call OpenRouter's free auto-router, retrying with backoff on 429s."""
    last_error = None
    for attempt in range(MAX_RETRIES):
        resp = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENROUTER_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": "openrouter/free",
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=60,
        )
        if resp.status_code == 429:
            wait = (attempt + 1) * 15
            print(f"Rate limited, waiting {wait}s before retry...")
            time.sleep(wait)
            last_error = resp
            continue
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]

    raise RuntimeError(f"OpenRouter still rate-limited after {MAX_RETRIES} attempts: {last_error.text if last_error else 'unknown'}")


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

    content = call_openrouter(prompt).strip()
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
