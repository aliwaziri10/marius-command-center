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
                "Authorization": f"Bearer
