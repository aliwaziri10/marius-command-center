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

SILENT-PATCH-NOOP FIX (2026-09-12): confirmed live - a PATCH to Supabase's
PostgREST endpoint returns 200 OK even when the filter matches zero rows,
with an empty [] body if Prefer: return=representation is set, or no body
at all otherwise. Neither retryable_request() nor the old versions of
mark_topic_scripted()/mark_topic_generation_failed() checked this, so a
topic whose id had already changed, been deleted, or never matched the
filter for any reason would silently fail to update while the calling code
believed it had succeeded. This is the confirmed explanation for topics
found stuck as status='scripted' with no corresponding row in the scripts
table at all. Both functions below now request return=representation and
raise immediately if the response body is empty, instead of returning
normally.

UNCAUGHT-INFRA-CRASH FIX (2026-09-13): confirmed live via Supabase
postgrest_logs - the project's free-tier Postgres has been throwing
frequent "Warp server error: Thread killed by timeout manager" errors all
day (resource contention under load from the multiple scheduled
workflows hitting it). get_pending_topics() below was the one Supabase
call in this file called OUTSIDE of main()'s try/except, so when a
timeout caused retryable_request to exhaust its retries and raise
RuntimeError, the exception propagated uncaught and crashed the entire
script - reported as a hard workflow failure - instead of being treated
as an ordinary transient infra failure like every other Supabase/Gemini
call in this pipeline. This was believed at the time to be the confirmed
root cause of every "Script Writing workflow failed" issue since
2026-09-06.

UNCAUGHT-INFRA-CRASH FIX WAS INCOMPLETE (2026-09-19) - CONFIRMED live via
GitHub issues #1130 through #1152: Script Writing kept failing on every
run from 2026-09-15 through 2026-09-18, well after the 2026-09-13 fix
above was committed - meaning that fix did not actually stop the crashes,
it only moved the exposed window earlier in the run. Root cause: the same
class of uncaught-RuntimeError-from-retryable_request bug also existed in
save_script() and mark_topic_scripted(), both called AFTER the per-topic
try/except block in the loop below (which only wraps generate_script()).
A transient Supabase timeout during the save-script POST or the
mark-scripted PATCH - the exact same free-tier "Warp server error"
condition named in the 2026-09-13 fix - still crashed the whole run
uncaught, just one or two calls later than the case that was actually
fixed. Fixed by widening the try/except to cover the entire per-topic
body (generate, save, and mark) as one unit: any RuntimeError from any
Supabase/Gemini call anywhere in a topic's processing is now treated as
an ordinary infra failure - logged, and the run moves on cleanly - instead
of only failures during generation being caught.

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
    """SILENT-PATCH-NOOP FIX (2026-09-12): see module docstring. Previously
    this fired the PATCH and returned without checking whether any row was
    actually updated - a topic_id that didn't match (already changed,
    wrong type, deleted, anything) would silently do nothing while the
    caller believed the topic was now marked scripted. Now demands
    return=representation and raises if the response body is empty, so a
    no-op surfaces immediately as a loud failure instead of a topic quietly
    staying in whatever state it was already in."""
    resp = retryable_request(
        "PATCH",
        f"{SUPABASE_URL}/rest/v1/topics?id=eq.{topic_id}",
        headers={**HEADERS, "Prefer": "return=representation"},
        json={"status": "scripted"},
        timeout=30,
    )
    updated = resp.json()
    if not updated:
        raise RuntimeError(
            f"mark_topic_scripted PATCH silently no-op'd for topic_id={topic_id} - "
            f"0 rows matched. The script itself was already saved to the scripts "
            f"table, so this topic is now in an inconsistent state (script exists, "
            f"topic status was never advanced from its previous value) and needs "
            f"manual review, not a silent continue."
        )


def mark_topic_generation_failed(topic_id, reason):
    """SILENT-PATCH-NOOP FIX (2026-09-12): see module docstring and
    mark_topic_scripted() above - identical fix, same reasoning."""
    resp = retryable_request(
        "PATCH",
        f"{SUPABASE_URL}/rest/v1/topics?id=eq.{topic_id}",
        headers={**HEADERS, "Prefer": "return=representation"},
        json={"status": "generation_failed", "last_failure_reason": str(reason)[:2000]},
        timeout=30,
    )
    updated = resp.json()
    if not updated:
        raise RuntimeError(
            f"mark_topic_generation_failed PATCH silently no-op'd for topic_id={topic_id} - "
            f"0 rows matched. Original failure reason was: {reason}"
        )
    print(f"Topic {topic_id} marked generation_failed - will be skipped by future runs until manually "
          f"reset. Last reason: {reason}")
    print(f"FIX: review/reword the topic's title or angle in the topics table for {topic_id}, then "
          f"reset status back to 'pending' to retry it.")


def main():
    # UNCAUGHT-INFRA-CRASH FIX (2026-09-13): see module docstring. This
    # call previously sat outside any try/except - a Supabase timeout here
    # (confirmed live, happening frequently on this project) crashed the
    # entire script before a single topic was ever attempted. Now treated
    # like any other infra failure: log and exit cleanly so the workflow
    # isn't reported as failed and the next scheduled run retries.
    try:
        topics = get_pending_topics(limit=5)
    except RuntimeError as e:
        print(f"Supabase infra failure fetching pending topics - not the topics' fault, "
              f"exiting cleanly so the next scheduled run retries: {e}")
        return

    if not topics:
        print("No pending topics found. Nothing to do.")
        return

    for topic in topics:
        print(f"Writing script for: {topic['title']}")

        # UNCAUGHT-INFRA-CRASH FIX WAS INCOMPLETE (2026-09-19): see module
        # docstring. This try/except now wraps generation AND save AND
        # mark-scripted as one unit - previously only generate_script() was
        # covered, so a transient Supabase failure during save_script() or
        # mark_topic_scripted() still crashed the whole run uncaught,
        # exactly the bug the 2026-09-13 fix was supposed to have already
        # eliminated, confirmed still happening on every run 2026-09-15
        # through 2026-09-18 (issues #1130-#1152).
        try:
            result = generate_script(topic["title"], topic["angle"])
            save_script(
                topic["id"],
                result["narration_text"],
                result["shot_list"],
                result["music_mood"],
                result["hook_text"],
                result["setting_and_characters"],
            )
            mark_topic_scripted(topic["id"])
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
            # Covers: a genuine content/shot-breakdown failure from
            # generate_script (existing behavior), AND now also a Supabase
            # infra failure during save_script/mark_topic_scripted (new).
            # These two cases are handled the same way here deliberately:
            # if the script was never saved, marking generation_failed is
            # correct and safe. If save_script DID succeed but
            # mark_topic_scripted then hit an infra RuntimeError (not its
            # own "0 rows matched" case, which already has a clear message),
            # this will mark the topic generation_failed even though a
            # scripts row exists for it - an inconsistent state, but one
            # that surfaces loudly with the real error message attached
            # instead of crashing the whole run silently. Prefer
            # investigating a generation_failed topic with an infra-looking
            # reason over resetting it blindly.
            mark_topic_generation_failed(topic["id"], str(e))
            continue

        print("Done.")
        return

    print("No candidate in this batch produced a script this run (all hit infra failures or "
          "were marked generation_failed) - next scheduled run will re-fetch and retry.")


if __name__ == "__main__":
    main()
