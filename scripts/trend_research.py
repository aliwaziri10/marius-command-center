"""
Marius Command Center - Trend Research Agent
Pulls real, currently-popular post titles from a curated list of history-
themed subreddits and saves them into the trend_signals table, so
topic_research.py can ground new episode ideas in what real audiences are
actually engaging with right now - instead of drifting toward flat,
low-stakes ideas (a bakery, a flower garden) with no real audience pull.

Uses Reddit's public, unauthenticated JSON endpoints (no API key/account
needed) - e.g. https://www.reddit.com/r/todayilearned/top.json - which
only requires a real User-Agent header to avoid a 429.

trend_signals table (created 2026-09-13):
    id uuid primary key
    subreddit text
    post_title text
    post_score int
    fetched_at timestamptz
    used_in_topic_id uuid (nullable, set later by topic_research.py once a
        topic is actually generated from this signal - not touched here)
"""

import os
import time
import requests

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SECRET_KEY"]

HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
}

# Edit this list any time to change which subreddits feed the trend signal -
# no other code needs to change.
SUBREDDITS = [
    "todayilearned",
    "HistoryPorn",
    "UnresolvedMysteries",
    "AskHistorians",
    "HistoryAnecdotes",
]

POSTS_PER_SUBREDDIT = 15
REDDIT_TIMEFRAME = "week"  # top posts of the past week
REQUEST_HEADERS = {"User-Agent": "marius-trend-research/1.0 (by /u/marius-bot)"}
MAX_RETRIES = 3


def fetch_top_posts(subreddit):
    url = f"https://www.reddit.com/r/{subreddit}/top.json?limit={POSTS_PER_SUBREDDIT}&t={REDDIT_TIMEFRAME}"
    last_error = None
    for attempt in range(MAX_RETRIES):
        try:
            resp = requests.get(url, headers=REQUEST_HEADERS, timeout=30)
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
            wait = (attempt + 1) * 10
            print(f"Reddit network error on r/{subreddit} ({e.__class__.__name__}), waiting {wait}s: {e}")
            last_error = e
            time.sleep(wait)
            continue

        if resp.status_code == 429:
            wait = (attempt + 1) * 15
            print(f"Reddit rate limited on r/{subreddit}, waiting {wait}s before retry...")
            last_error = resp
            time.sleep(wait)
            continue

        try:
            resp.raise_for_status()
        except requests.exceptions.HTTPError as e:
            print(f"Reddit HTTP error on r/{subreddit} ({resp.status_code}): {e} - skipping this subreddit.")
            return []

        posts = []
        for child in resp.json().get("data", {}).get("children", []):
            post = child.get("data", {})
            title = post.get("title", "").strip()
            score = post.get("score", 0)
            if title:
                posts.append((title, score))
        return posts

    print(f"Giving up on r/{subreddit} after {MAX_RETRIES} attempts: {last_error}")
    return []


def save_signal(subreddit, title, score):
    resp = requests.post(
        f"{SUPABASE_URL}/rest/v1/trend_signals",
        headers={**HEADERS, "Prefer": "return=representation"},
        json={"subreddit": subreddit, "post_title": title, "post_score": score},
        timeout=30,
    )
    resp.raise_for_status()


def main():
    total_saved = 0
    for subreddit in SUBREDDITS:
        posts = fetch_top_posts(subreddit)
        print(f"r/{subreddit}: fetched {len(posts)} posts.")
        for title, score in posts:
            try:
                save_signal(subreddit, title, score)
                total_saved += 1
            except requests.exceptions.RequestException as e:
                print(f"Failed to save signal from r/{subreddit} ('{title[:60]}...'): {e}")
        # Be polite to Reddit's public endpoint between subreddits.
        time.sleep(2)

    print(f"Done. Saved {total_saved} trend signals across {len(SUBREDDITS)} subreddits.")


if __name__ == "__main__":
    main()
