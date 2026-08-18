"""
Marius Command Center - Script Writing Agent
Takes the oldest pending topic(s) and turns each into a full narration
script plus a shot-by-shot visual production plan for "Erased."

SPLIT (2026-08-18): this file previously held everything - the LLM client,
narration generation, and shot-breakdown generation - in one long file with
an extensive docstring documenting the provider-switch history (OpenRouter
-> Gemini -> Groq -> back to Gemini) and every bug fixed along the way.
That history is preserved below for context. The actual client/narration/
shot-breakdown logic has been moved out into three modules with NO behavior
change:
  - llm_client.py: call_llm(), retryable_request(), InfraFailure,
    DailyQuotaExhausted, extract_json()/sanitize_json_control_chars()
  - narration_stage.py: generate_narration() and its prompts
  - shot_breakdown_stage.py: generate_shot_breakdown(), all shot
    validation functions, and chunking logic
This file now only orchestrates: fetch pending topics, call the two stages
in order, save the result, and update topic/script status in Supabase.

=== FULL PROVIDER-SWITCH HISTORY (preserved for context) ===

PROVIDER SWITCH (2026-08-06): OpenRouter's free-tier request cap was being
exhausted, causing sustained 429s. Removed OpenRouter entirely, Gemini
became the only provider.

CONTENT-RETRY BACKOFF FIX (2026-08-15): added a real sleep between content
attempts to stop self-inflicted 429 bursts.

PROVIDER SWITCH (2026-08-15): Gemini removed, Groq became the only
provider (higher free-tier RPM/TPM ceiling, 128K context).

TWO-STAGE GENERATION (2026-08-15): split one call into generate_narration()
+ generate_shot_breakdown() - asking one call to write 1700+ words of prose
AND decompose it into a large structured shot list was cutting narration
short.

CHUNKED SHOT BREAKDOWN (2026-08-15): even split from narration, the
shot-breakdown call alone was too big for Groq's free tier. Split into
NUM_SHOT_CHUNKS per-chunk calls, stitched and renumbered afterward.

SUSPECTED-DAILY-QUOTA-EXHAUSTION EARLY ABORT (2026-08-15, later): detected
Groq's undocumented daily token cap (TPD, invisible in headers) via a
"high remaining but still 429" signature, and aborted the run early rather
than retrying uselessly.

TOKEN-BUDGET TRIM (2026-08-17): cut MIN_SHOTS/MAX_SHOTS and narration
target words further to reduce worst-case tokens per script.

FALSE-POSITIVE DAILY-QUOTA ABORT FIX (2026-08-17, later): the Aug 15
heuristic misclassified an ordinary per-minute TPM window as a daily
exhaustion. Fixed to parse Groq's actual reset-window headers.

PROVIDER SWITCH BACK TO GEMINI (2026-08-17, latest): abandoned Groq
entirely - proved its 429s can show fully replenished per-minute headers
while still permanently 429ing every call, meaning Groq's real constraint
(the undocumented TPD cap) is structurally invisible to this script. All
Groq-specific code/constants were dead history at that point and have
since been removed as part of this split (they added no value once Gemini
was restored - see git history on this file's pre-split version if the
exact Groq tuning constants are ever needed again).

MILLISECOND RESET FORMAT + INVERTED FAIL-SAFE FIX (2026-08-17, even later):
fixed two compounding bugs in the (now-removed) Groq quota-guessing logic
before Groq was abandoned outright.

TRUNCATED-JSON + REPETITIVE-REACTION FIX (2026-08-18): added explicit
maxOutputTokens to the Gemini call (large shot-breakdown chunks were
truncating mid-JSON) and added anti-gasping guidance to both the narration
and shot-breakdown prompts, since characters gasping was the default
reaction beat in nearly every episode.
"""

from llm_client import retryable_request, SUPABASE_URL, HEADERS, InfraFailure, DailyQuotaExhausted
from narration_stage import generate_narration
from shot_breakdown_stage import generate_shot_breakdown


def get_pending_topics(limit=5):
    """HEAD-OF-LINE FIX (2026-08-14): previously fetched only the single
    oldest pending topic. If that topic hit InfraFailure, main() returned
    cleanly (exit 0, no GitHub issue) and left it 'pending' for the next
    run to retry - which then hit the exact same topic again. Confirmed
    live: 'The Manzanar Teacher Who Taught in Secret' (created 2026-07-17)
    sat retried on every 12h run for over a week while 240+ newer pending
    topics never got a turn. Mirrors the same fix already proven in
    video_generation.py's get_ready_scripts()."""
    resp = retryable_request(
        "GET",
        f"{SUPABASE_URL}/rest/v1/topics?status=eq.pending&order=created_at.asc&limit={limit}",
        headers=HEADERS,
        timeout=30,
    )
    return resp.json()


def generate_script(title, angle):
    """Orchestrates the two stages. If the narration stage hits InfraFailure,
    that propagates up untouched (topic stays pending). If the shot-breakdown
    stage fails after narration already succeeded, that's still surfaced as
    a real failure - but note the narration itself was proven fine, so a
    generation_failed topic reset for this reason should retry fast."""
    narration_text = generate_narration(title, angle)
    return generate_shot_breakdown(title, angle, narration_text)


def save_script(topic_id, narration_text, shot_list, music_mood, hook_text, setting_and_characters):
    retryable_request(
        "POST",
        f"{SUPABASE_URL}/rest/v1/scripts",
        headers={**HEADERS, "Prefer": "return=representation"},
        json={
            "topic_id": topic_id,
            "narration_text": narration_text,
            "shot_list": shot_list,
            "music_mood": music_mood,
            "hook_text": hook_text,
            "setting_and_characters": setting_and_characters,
            "status": "pending",
        },
        timeout=30,
    )
    print("Script saved.")


def mark_topic_scripted(topic_id):
    retryable_request(
        "PATCH",
        f"{SUPABASE_URL}/rest/v1/topics?id=eq.{topic_id}",
        headers=HEADERS,
        json={"status": "scripted"},
        timeout=30,
    )


def mark_topic_generation_failed(topic_id, reason):
    retryable_request(
        "PATCH",
        f"{SUPABASE_URL}/rest/v1/topics?id=eq.{topic_id}",
        headers=HEADERS,
        json={"status": "generation_failed", "last_failure_reason": str(reason)[:2000]},
        timeout=30,
    )
    print(f"Topic {topic_id} marked generation_failed - will be skipped by future runs until manually "
          f"reset. Last reason: {reason}")
    print(f"FIX: review/reword the topic's title or angle in the topics table for {topic_id}, then "
          f"reset status back to 'pending' to retry it.")


def main():
    topics = get_pending_topics(limit=5)
    if not topics:
        print("No pending topics found. Nothing to do.")
        return

    for topic in topics:
        print(f"Writing script for: {topic['title']}")
        try:
            result = generate_script(topic["title"], topic["angle"])
        except DailyQuotaExhausted as e:
            # Every remaining topic in this batch would hit the exact same
            # wall - stop the whole run immediately instead of burning
            # more time on doomed retries. Topic stays 'pending', same as
            # InfraFailure, since this is not the topic's fault either.
            print(
                f"ABORTING RUN - Gemini daily quota exhausted on topic "
                f"{topic['id']} ({topic['title']}): {e}"
            )
            print("This will not clear until Google's daily reset - not retrying "
                  "further topics this run. Next scheduled run will retry from the top.")
            return
        except InfraFailure as e:
            print(f"Gemini infra failure on topic {topic['id']} ({topic['title']}) - not the "
                  f"topic's fault, leaving it pending and trying the next-oldest candidate "
                  f"this run instead of exiting: {e}")
            continue
        except RuntimeError as e:
            mark_topic_generation_failed(topic["id"], str(e))
            continue

        save_script(
            topic["id"],
            result["narration_text"],
            result["shot_list"],
            result["music_mood"],
            result["hook_text"],
            result["setting_and_characters"],
        )
        mark_topic_scripted(topic["id"])
        print("Done.")
        return

    print("No candidate in this batch produced a script this run (all hit infra failures or "
          "were marked generation_failed) - next scheduled run will re-fetch and retry.")


if __name__ == "__main__":
    main()
