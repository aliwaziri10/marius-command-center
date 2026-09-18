"""
Marius Command Center - Trend Research Agent

Pulls real, currently-high-interest article titles into the trend_signals
table, so topic_research.py can ground new episode ideas in what real
audiences are actually curious about right now - instead of drifting
toward flat, low-stakes ideas (a bakery, a flower garden) with no real
audience pull.

SOURCE SWAP (2026-09-19) - CONFIRMED root cause: this file originally
pulled from Reddit's public, unauthenticated JSON endpoints
(r/todayilearned/top.json etc). trend_signals had ZERO rows, ever, since
the table's creation on 2026-09-13 - this ran daily via cron for days and
silently produced nothing every single time. Root cause: Reddit blocks
essentially all unauthenticated API traffic from cloud/datacenter IP
ranges (AWS/GCP/Azure) with a 403, a platform-wide policy since 2023 -
GitHub Actions runners are Azure-hosted, so this was never going to work
regardless of User-Agent string or retry count. Compounding this: every
failure path in the old fetch_top_posts()/save_signal() caught its own
exception, printed a message, and returned/continued - meaning this
script always exited 0 and NEVER opened a single "workflow failed" issue
in weeks of running, even though it did nothing every single time. Nobody
could tell it was broken from the Actions UI.

Replaced Reddit with Wikipedia's official Pageviews API
(wikimedia.org/api/rest_v1/metrics/pageviews/top/...) - a public,
unauthenticated, well-documented endpoint that does not block
cloud/datacenter IPs (Wikimedia's own docs list programmatic/bot access
as an intended use case, unlike Reddit's). Pulls the prior day's most-
viewed English Wikipedia articles as a general real-interest signal.
This is a broader signal than "history specifically" (it's whatever the
whole internet is reading about that day, which includes current events,
entertainment, etc, not just history) - topic_research.py already treats
trend_signals as optional inspiration, never a requirement, so a title
about something unrelated to this channel's history focus is simply
never picked, exactly like a Reddit post that didn't fit wouldn't have
been either. The goal here is a working, real signal instead of a dead,
silent one - not a perfect topical match on every row.

FAIL LOUD (2026-09-19): unlike the old version, a totally failed run now
raises instead of printing and returning 0 - so if this ever breaks again
(a Wikimedia API change, a network block, etc), the existing
"Open issue on failure" step in trend_research.yml actually fires and
Zia finds out, instead of this silently doing nothing for weeks again.
A partial failure (one day's data unavailable, still saved a partial
batch) is still tolerated and logged, matching the spirit of the original
script's per-item resilience.

trend_signals table (created 2026-09-13, schema unchanged):
    id uuid primary key
    subreddit text            -- now holds a source label, e.g. "wikipedia_top_en"
    post_title text           -- now holds a Wikipedia article title
    post_score int            -- now holds that day's pageview count
    fetched_at timestamptz
    used_in_topic_id uuid (nullable, set later by topic_research.py once a
        topic is actually generated from this signal - not touched here)
"""

import os
import time
from datetime import datetime, timedelta, timezone

import requests

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SECRET_KEY"]

HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
}

# Wikimedia's own docs ask for a descriptive, identifying User-Agent with
# contact info - unlike Reddit, this is the ENCOURAGED way to access this
# endpoint, not something that gets penalized.
WIKI_USER_AGENT = "marius-command-center-trend-research/1.0 (github.com/aliwaziri10/marius-command-center)"
WIKI_TOP_URL_TEMPLATE = (
    "https://wikimedia.org/api/rest_v1/metrics/pageviews/top/en.wikipedia.org/all-access/{year}/{month}/{day}"
)

# Pageview data typically isn't available for "today" yet - go back this
# many days to a date that's reliably already published.
DAYS_AGO = 2
ARTICLES_TO_SAVE = 60
SOURCE_LABEL = "wikipedia_top_en"
MAX_RETRIES = 3

# Junk/non-article entries that always show up in this feed and carry no
# real topical signal.
SKIP_TITLES_PREFIXES = ("Special:", "Main_Page", "Wikipedia:", "Portal:", "File:", "Talk:")


def fetch_top_articles():
    target_date = datetime.now(timezone.utc) - timedelta(days=DAYS_AGO)
    url = WIKI_TOP_URL_TEMPLATE.format(
        year=target_date.strftime("%Y"),
        month=target_date.strftime("%m"),
        day=target_date.strftime("%d"),
    )
    last_error = None
    for attempt in range(MAX_RETRIES):
        try:
            resp = requests.get(url, headers={"User-Agent": WIKI_USER_AGENT}, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            articles = data.get("items", [{}])[0].get("articles", [])
            return articles
        except (requests.exceptions.RequestException, KeyError, IndexError, ValueError) as e:
            last_error = e
            wait = (attempt + 1) * 10
            print(f"Wikipedia pageviews request failed (attempt {attempt + 1}/{MAX_RETRIES}): {e}")
            if attempt < MAX_RETRIES - 1:
                print(f"Retrying in {wait}s...")
                time.sleep(wait)

    raise RuntimeError(f"Could not fetch Wikipedia top pageviews after {MAX_RETRIES} attempts: {last_error}")


def save_signal(title, score):
    resp = requests.post(
        f"{SUPABASE_URL}/rest/v1/trend_signals",
        headers={**HEADERS, "Prefer": "return=representation"},
        json={"subreddit": SOURCE_LABEL, "post_title": title, "post_score": score},
        timeout=30,
    )
    resp.raise_for_status()


def main():
    articles = fetch_top_articles()
    print(f"Fetched {len(articles)} raw entries from Wikipedia pageviews.")

    total_saved = 0
    total_skipped_save_errors = 0
    for entry in articles:
        raw_title = entry.get("article", "")
        if not raw_title or raw_title.startswith(SKIP_TITLES_PREFIXES):
            continue

        title = raw_title.replace("_", " ").strip()
        views = entry.get("views", 0)

        try:
            save_signal(title, views)
            total_saved += 1
        except requests.exceptions.RequestException as e:
            total_skipped_save_errors += 1
            print(f"Failed to save signal for {title!r}: {e}")

        if total_saved >= ARTICLES_TO_SAVE:
            break

    print(f"Done. Saved {total_saved} trend signals from {SOURCE_LABEL} "
          f"({total_skipped_save_errors} save error(s)).")

    # FAIL LOUD (2026-09-19): if the fetch itself succeeded but literally
    # nothing was saved (e.g. every single insert failed, or the filtered
    # article list was empty), that's still worth a real failure - a run
    # that "succeeds" while saving 0 rows is exactly the silent-failure
    # pattern this rewrite exists to end.
    if total_saved == 0:
        raise RuntimeError(
            f"Fetched {len(articles)} raw entries but saved 0 trend signals - "
            f"treating this as a failure so it surfaces instead of running silently forever."
        )


if __name__ == "__main__":
    main()
