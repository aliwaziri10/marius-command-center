"""
Marius Command Center - Video Generation (orchestration only)

Split 2026-09-06 (same pattern as the 2026-08-18 script_writing.py split)
into 4 modules + this orchestration layer:
  - agnes_client.py    - Agnes API HTTP contract, exceptions, constants
  - prompt_builder.py  - all prompt-building logic and guard constants
  - clip_generation.py - per-shot clip generation, chain-extension
  - assembly_stage.py  - audio mix, captions, final encode/upload

This file now only does: pick the next scripts to work on, run each shot
through clip_generation, save progress, and once all shots are done, run
assembly_stage and mark the script complete. No prompt-building, no Agnes
HTTP details, no ffmpeg/moviepy mixing logic live here anymore - see the
relevant module for those.
"""

import os
import json
import time
import traceback
import requests
from moviepy import AudioFileClip

import storage_b2
from agnes_client import ContentPolicyRejection, AgnesOverloadedError, AgnesBadRequestError
from clip_generation import generate_shot_clip
from assembly_stage import assemble_final_video, upload_video

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SECRET_KEY"]

HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
}

TRAIL_SECONDS = 3.0

CLIP_BATCH_LIMIT = 8          # total shots generated per run, across ALL candidates combined
CANDIDATE_POOL_SIZE = 15      # raised from 5 (2026-07-25) so every currently-stuck script is in rotation

CLIP_VERIFY_RETRIES = 3
CLIP_VERIFY_RETRY_WAIT = 5


def get_ready_scripts(limit=CANDIDATE_POOL_SIZE):
    resp = requests.get(
        f"{SUPABASE_URL}/rest/v1/scripts?status=eq.images_generated&order=created_at.asc&limit={limit}",
        headers=HEADERS,
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def download_file(url, out_path):
    r = requests.get(url, timeout=120)
    r.raise_for_status()
    with open(out_path, "wb") as f:
        f.write(r.content)
    return out_path


def record_error(script_id, error_text):
    """
    VERIFIER-GATE FIX (2026-08-22): persists the real exception (full
    traceback) for a script to scripts.last_error/last_error_at, instead of
    letting it disappear into an Actions log that's hard to get to. This is
    what makes a failure diagnosable from Supabase alone. Best-effort only -
    if even this write fails, we print and move on rather than compounding
    the original failure.
    """
    try:
        resp = requests.patch(
            f"{SUPABASE_URL}/rest/v1/scripts?id=eq.{script_id}",
            headers=HEADERS,
            json={
                "last_error": error_text[-8000:],
                "last_error_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            },
            timeout=30,
        )
        resp.raise_for_status()
    except Exception as e:
        print(f"Could not record last_error for script {script_id} (secondary failure, non-fatal): {e}")


def clear_error(script_id):
    """Clears a previously recorded last_error once a script succeeds, so
    Supabase never shows a stale failure for a script that's now fine."""
    try:
        resp = requests.patch(
            f"{SUPABASE_URL}/rest/v1/scripts?id=eq.{script_id}",
            headers=HEADERS,
            json={"last_error": None},
            timeout=30,
        )
        resp.raise_for_status()
    except Exception as e:
        print(f"Could not clear last_error for script {script_id} (non-fatal): {e}")


def compute_shot_durations(shot_list, total_duration):
    weights = [max(len(s.get("narration_excerpt", "")), 20) for s in shot_list]
    total_weight = sum(weights)
    return [(weight / total_weight) * total_duration for weight in weights]


def get_shot_durations(script, shot_list, audio_clip):
    stored = script.get("shot_durations")
    if (
        isinstance(stored, list)
        and len(stored) == len(shot_list)
        and all(isinstance(d, (int, float)) and d >= 0 for d in stored)
    ):
        print("Using real per-shot narration durations from shot_durations column.")
        return list(stored)
    print("shot_durations column missing/invalid for this script - falling back to text-length estimate.")
    return compute_shot_durations(shot_list, audio_clip.duration)


def upload_clip(script_id, index, file_path):
    """Returns the B2 object KEY (not a URL) - see storage_b2.py
    docstring. This is what gets stored in scripts.video_urls now."""
    file_name = f"{script_id}/shot_{index:03d}.mp4"
    return storage_b2.upload_file(file_name, file_path, content_type="video/mp4")


def save_progress(script_id, video_urls, next_index):
    resp = requests.patch(
        f"{SUPABASE_URL}/rest/v1/scripts?id=eq.{script_id}",
        headers=HEADERS,
        json={"video_urls": video_urls, "video_next_index": next_index},
        timeout=30,
    )
    resp.raise_for_status()


def mark_content_flagged(script_id, shot_index, reason):
    resp = requests.patch(
        f"{SUPABASE_URL}/rest/v1/scripts?id=eq.{script_id}",
        headers=HEADERS,
        json={"status": "content_flagged"},
        timeout=30,
    )
    resp.raise_for_status()
    print(f"Script {script_id} marked content_flagged (shot {shot_index + 1}) - will be skipped by future runs until manually reset. Reason: {reason}")


def mark_video_stalled(script_id, shot_index, reason):
    """
    STALL FIX (2026-09-02): companion to mark_content_flagged, but for a
    non-content-policy 400 (AgnesBadRequestError) - a genuine request-format
    or upstream bug, not a policy rejection, so it gets its own status
    rather than being mislabeled content_flagged. Sets status to
    'video_stalled', which get_ready_scripts does NOT select (it only
    queries status=images_generated), so the same broken shot stops being
    retried identically every run. The real Agnes response body is
    persisted to last_error via record_error so the actual cause is
    visible directly in Supabase - reset status back to 'images_generated'
    manually once the underlying issue (bad prompt field, payload bug,
    etc.) is understood/fixed, same workflow as content_flagged.
    """
    record_error(script_id, f"AgnesBadRequestError on shot {shot_index + 1}: {reason}")
    resp = requests.patch(
        f"{SUPABASE_URL}/rest/v1/scripts?id=eq.{script_id}",
        headers=HEADERS,
        json={"status": "video_stalled"},
        timeout=30,
    )
    resp.raise_for_status()
    print(f"Script {script_id} marked video_stalled (shot {shot_index + 1}) - will be skipped by future runs until manually reset. Reason: {reason}")


def mark_video_generated(script_id, video_url=None, video_chunk_urls=None, audio_stats=None):
    update = {"status": "video_generated"}
    if video_url is not None:
        update["video_url"] = video_url
    if video_chunk_urls is not None:
        update["video_chunk_urls"] = video_chunk_urls
    if audio_stats is not None:
        update["music_generated"] = audio_stats.get("music_generated", False)
        update["sfx_applied_count"] = audio_stats.get("sfx_applied_count", 0)
        # AUDIO-DEBUG FIX (2026-08-23): persists the real failure reason(s)
        # collected in build_audio_mix to scripts.audio_debug, queryable
        # directly from Supabase - no GitHub Actions log access needed to
        # diagnose why music/SFX didn't apply on a given episode.
        update["audio_debug"] = audio_stats.get("audio_debug")
    resp = requests.patch(
        f"{SUPABASE_URL}/rest/v1/scripts?id=eq.{script_id}",
        headers=HEADERS,
        json=update,
        timeout=30,
    )
    resp.raise_for_status()


def process_script(script, shot_limit=CLIP_BATCH_LIMIT):
    script_id = script["id"]
    if not script.get("narration_url"):
        print(f"Script {script_id} has no narration_url yet. Skipping.")
        return 0

    print(f"Working on script {script_id}")

    shot_list = script["shot_list"]
    if isinstance(shot_list, str):
        shot_list = json.loads(shot_list)
    total_shots = len(shot_list)
    music_mood = script.get("music_mood") or ""
    setting_and_characters = script.get("setting_and_characters", "")

    video_urls = script.get("video_urls") or []
    next_index = script.get("video_next_index") or 0

    # STORAGE MIGRATION (2026-09-02): video_urls entries are B2 object keys
    # now, not URLs - verification uses storage_b2.object_exists (a real
    # B2 head_object check) instead of an HTTP HEAD on a stored URL. This
    # has no expiry dependency regardless of how long a script has been
    # sitting resumable across runs, unlike a presigned-URL-based check
    # would (see storage_b2.py docstring for the full reasoning).
    verified_urls = []
    for i, key in enumerate(video_urls):
        verified = False
        last_error = None
        for attempt in range(CLIP_VERIFY_RETRIES):
            try:
                if storage_b2.object_exists(key):
                    verified = True
                    break
                last_error = "object not found in B2"
            except Exception as e:
                last_error = str(e)
            if attempt < CLIP_VERIFY_RETRIES - 1:
                time.sleep(CLIP_VERIFY_RETRY_WAIT)
        if verified:
            verified_urls.append(key)
        else:
            print(f"Clip {i} failed verification after {CLIP_VERIFY_RETRIES} attempts ({last_error}), will regenerate: {key}")
            break

    if len(verified_urls) != len(video_urls):
        video_urls = verified_urls
        next_index = len(verified_urls)
        save_progress(script_id, video_urls, next_index)
        print(f"Corrected progress after verification: {next_index}/{total_shots} shots actually confirmed done")

    shots_used = 0

    if next_index >= total_shots:
        print(f"All {total_shots} shots already generated, video_urls has {len(video_urls)} entries. Skipping to assembly check.")
    elif shot_limit <= 0:
        print(f"No shot budget remaining this run for script {script_id} - will get a turn on the next scheduled run.")
        return 0
    else:
        audio_path = "/tmp/narration_audio"
        audio_path += ".mp3" if script["narration_url"].endswith(".mp3") else ".wav"
        download_file(script["narration_url"], audio_path)
        audio_clip = AudioFileClip(audio_path)
        shot_durations = get_shot_durations(script, shot_list, audio_clip)

        batch_end = min(next_index + shot_limit, total_shots)
        print(f"Resuming from shot {next_index + 1}/{total_shots} ({len(video_urls)} already done) - generating up to shot {batch_end} this run (budget this call: {shot_limit})")

        anchor_image_url = None

        for i in range(next_index, batch_end):
            shot = shot_list[i]
            raw_path = f"/tmp/shot_{i:03d}.mp4"
            print(f"Generating shot {i+1}/{total_shots} (~{shot_durations[i]:.1f}s)...")
            try:
                generate_shot_clip(shot, shot_durations[i], raw_path, setting_and_characters, anchor_image_url=anchor_image_url, script_id=script_id)
            except ContentPolicyRejection as e:
                mark_content_flagged(script_id, i, str(e))
                print(f"Rejected visual_description: {shot.get('visual_description', '')!r}")
                print(f"FIX: reword shot_list[{i}].visual_description for script {script_id} in the "
                      f"scripts table, then reset status to 'images_generated' to resume from exactly "
                      f"this shot. Moving on to the next-oldest eligible candidate for now.")
                return shots_used
            except AgnesBadRequestError as e:
                mark_video_stalled(script_id, i, str(e))
                print(f"Non-content-policy 400 on shot {i+1}/{total_shots} - not a transient/overload "
                      f"error, so it will not resolve itself on retry. FIX: inspect scripts.last_error "
                      f"for the real Agnes response body, fix the underlying request/payload issue, then "
                      f"reset status to 'images_generated' to resume from exactly this shot. Moving on to "
                      f"the next-oldest eligible candidate for now.")
                return shots_used
            except AgnesOverloadedError as e:
                print(f"Agnes appears overloaded (upstream load saturated) on shot {i+1}/{total_shots} after all retries: {e}")
                if shots_used:
                    print(f"Progress already saved through shot {i}/{total_shots} ({len(video_urls)} clips done) "
                          f"this run - stopping here instead of crashing; next scheduled run resumes from here.")
                else:
                    print(f"Zero progress made on this script this run - moving on to the next-oldest "
                          f"eligible candidate instead of ending the run. This script's own turn will "
                          f"come back around once Agnes's load eases.")
                return shots_used

            clip_url = upload_clip(script_id, i, raw_path)
            video_urls.append(clip_url)
            save_progress(script_id, video_urls, i + 1)
            shots_used += 1
            print(f"Saved progress: {i + 1}/{total_shots} shots done")

            os.remove(raw_path)
            time.sleep(4)

        if batch_end < total_shots:
            print(f"Shot budget for this candidate used up this run ({shots_used} shots). {total_shots - batch_end} shots remain - resuming on a future run.")
            return shots_used

    if len(video_urls) >= total_shots:
        print("All shots done. Assembling final video...")
        try:
            audio_path = "/tmp/narration_audio_final"
            audio_path += ".mp3" if script["narration_url"].endswith(".mp3") else ".wav"
            download_file(script["narration_url"], audio_path)
            audio_clip = AudioFileClip(audio_path)
            shot_durations = get_shot_durations(script, shot_list, audio_clip)
            shot_durations[-1] += TRAIL_SECONDS

            output_path = "/tmp/final_video.mp4"
            output_path, audio_stats = assemble_final_video(script_id, video_urls, audio_path, music_mood, shot_list, shot_durations, output_path, setting_and_characters=setting_and_characters)

            video_url = upload_video(script_id, output_path)
            print(f"Uploaded to B2 as a single object (key: {video_url}).")

            mark_video_generated(script_id, video_url=video_url, audio_stats=audio_stats)
            clear_error(script_id)
            print("Done.")
        except Exception as e:
            # VERIFIER-GATE FIX (2026-08-22): assembly used to be
            # unprotected - any exception here (bad clip download, ffmpeg
            # failure, upload timeout, a shot duration far exceeding what
            # chaining can cover, etc.) propagated all the way up through
            # process_script and main(), crashing the ENTIRE run before any
            # other candidate script got a turn. This is the confirmed
            # cause of 177 straight failed Video Generation runs even
            # though per-shot clip generation itself was working fine. The
            # real exception is now recorded to scripts.last_error /
            # last_error_at so the actual cause is visible directly in
            # Supabase, the run keeps going, and this script just retries
            # assembly again next run instead of blocking every other
            # script in the queue.
            error_text = traceback.format_exc()
            print(f"Assembly FAILED for script {script_id} - recording error and moving on: {e}")
            record_error(script_id, error_text)

    return shots_used


def main():
    candidates = get_ready_scripts(CANDIDATE_POOL_SIZE)
    if not candidates:
        print("No scripts with images ready for video generation. Nothing to do.")
        return

    remaining_budget = CLIP_BATCH_LIMIT
    any_progress = False

    for script in candidates:
        if remaining_budget <= 0:
            print(f"Per-run shot budget ({CLIP_BATCH_LIMIT}) fully used - stopping here to respect Agnes's "
                  f"quota ceiling. Remaining candidates get their turn on the next scheduled run.")
            break

        try:
            shots_used = process_script(script, shot_limit=remaining_budget)
        except Exception as e:
            # VERIFIER-GATE FIX (2026-08-22): a crash ANYWHERE inside
            # process_script (not just assembly) used to kill this whole
            # run, leaving every other queued script untouched until the
            # next cron tick. Catching here means one broken script can
            # never block the rest of the batch again - the real exception
            # is still recorded to last_error for diagnosis.
            error_text = traceback.format_exc()
            print(f"Unexpected error processing script {script['id']} - recording error and moving to next candidate: {e}")
            record_error(script['id'], error_text)
            shots_used = 0

        if shots_used > 0:
            any_progress = True
            remaining_budget -= shots_used
            print(f"Script {script['id']} used {shots_used} shot(s) this run - {remaining_budget} left in this run's shared budget.")
        else:
            print(f"No progress on script {script['id']} this run (overloaded, content-flagged, or already "
                  f"fully assembled) - trying the next candidate with the same remaining budget.")

    if not any_progress:
        print(f"No progress possible on any of the {len(candidates)} candidate scripts this run "
              f"(all stalled or not ready) - next scheduled run will retry.")


if __name__ == "__main__":
    main()
