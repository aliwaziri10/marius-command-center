"""
Marius Command Center - Script Writing Agent
Takes the oldest pending topic and turns it into a full narration script
plus a shot-by-shot visual production plan for "Forgotten Names."
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

MAX_RETRIES = 4


def get_next_pending_topic():
    resp = requests.get(
        f"{SUPABASE_URL}/rest/v1/topics?status=eq.pending&order=created_at.asc&limit=1",
        headers=HEADERS,
        timeout=30,
    )
    resp.raise_for_status()
    rows = resp.json()
    return rows[0] if rows else None


def call_openrouter(prompt):
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
            timeout=90,
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


def generate_script(title, angle):
    prompt = f"""You are the head writer for "Forgotten Names," a YouTube documentary
channel telling real, historically documented true stories of ordinary people
caught in extraordinary historical moments.

Episode topic: {title}
Angle: {angle}

Write a complete 8-10 minute narration script (roughly 1200-1500 words) with a
strong hook in the first 15 seconds, a clear narrative arc, and a reflective
closing line. Also break the episode into shots for visual generation.

Return ONLY valid JSON, no other text, in this exact format:

{{
  "narration_text": "The full narration script as one string, written to be read aloud.",
  "shot_list": [
    {{"shot_number": 1, "visual_description": "Detailed description for AI image/video generation", "narration_excerpt": "The exact portion of narration this shot covers"}}
  ]
}}

Include 15-25 shots covering the full narration."""

    content = call_openrouter(prompt).strip()
    if content.startswith("```"):
        content = content.split("```")[1]
        if content.startswith("json"):
            content = content[4:]
    return json.loads(content.strip())


def save_script(topic_id, narration_text, shot_list):
    resp = requests.post(
        f"{SUPABASE_URL}/rest/v1/scripts",
        headers={**HEADERS, "Prefer": "return=representation"},
        json={
            "topic_id": topic_id,
            "narration_text": narration_text,
            "shot_list": shot_list,
            "status": "pending",
        },
        timeout=30,
    )
    resp.raise_for_status()
    print("Script saved.")


def mark_topic_scripted(topic_id):
    resp = requests.patch(
        f"{SUPABASE_URL}/rest/v1/topics?id=eq.{topic_id}",
        headers=HEADERS,
        json={"status": "scripted"},
        timeout=30,
    )
    resp.raise_for_status()


def main():
    topic = get_next_pending_topic()
    if not topic:
        print("No pending topics found. Nothing to do.")
        return

    print(f"Writing script for: {topic['title']}")
    result = generate_script(topic["title"], topic["angle"])
    save_script(topic["id"], result["narration_text"], result["shot_list"])
    mark_topic_scripted(topic["id"])
    print("Done.")


if __name__ == "__main__":
    main()
