"""
Marius Command Center - Script Writing Agent
Takes the oldest pending topic and turns it into a full narration script
plus a shot-by-shot visual production plan for "Erased."
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
MIN_SHOTS = 35
MAX_SHOTS = 55
MAX_GENERATION_ATTEMPTS = 3
MAX_HOOK_TEXT_CHARS = 40
MAX_HOOK_TEXT_WORDS = 5  # researched YouTube best practice: top-performing
                         # thumbnails consistently use 3-5 words - anything
                         # longer stops being readable in a mobile-feed glance

# The exact example hook text shown in the prompt below. If the model ever
# echoes this verbatim instead of writing a real one for the actual story,
# validate_and_normalize() rejects it and generate_script() retries - this
# is what caused a real video ("The Porter Who Carried Freedom") to get a
# completely unrelated thumbnail hook ("312 DIARIES. ONE BOMB. GONE IN
# SECONDS.") copied straight from the prompt's own example.
EXAMPLE_HOOK_TEXT = "312 DIARIES. ONE BOMB. GONE IN SECONDS."

VALID_SHOT_TYPES = {
    "wide", "medium", "close_up", "extreme_close_up", "establishing", "detail_insert"
}
VALID_CAMERA_MOVEMENTS = {
    "static", "pan_left", "pan_right", "tilt_up", "tilt_down", "zoom_in", "zoom_out",
    "push_in", "pull_out", "dolly_in", "dolly_out", "tracking", "crash_zoom",
    "whip_pan", "handheld_shake", "orbit", "drone_rise", "drone_descend",
    "parallax", "focus_pull", "dutch_angle", "snap_zoom", "speed_ramp",
}
VALID_LENS_EFFECTS = {
    "shallow_depth_of_field", "lens_flare", "film_grain", "none"
}


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


def extract_json(raw_text):
    """Pull a JSON object out of model output even if it's wrapped in
    markdown fences, extra commentary, or inconsistent formatting."""
    text = raw_text.strip()

    if "```" in text:
        parts = text.split("```")
        for part in parts:
            candidate = part.strip()
            if candidate.startswith("json"):
                candidate = candidate[4:].strip()
            if candidate.startswith("{"):
                text = candidate
                break

    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("No JSON object found in model output.")

    return json.loads(text[start:end + 1])


def normalize_shot(shot, index):
    """Fill in safe defaults for any missing/invalid fields so a flaky
    free-model response never breaks video_generation.py downstream."""
    shot_type = shot.get("shot_type")
    if shot_type not in VALID_SHOT_TYPES:
        shot_type = "medium"

    camera_movement = shot.get("camera_movement")
    if camera_movement not in VALID_CAMERA_MOVEMENTS:
        camera_movement = "static"

    lens_effect = shot.get("lens_effect")
    if lens_effect not in VALID_LENS_EFFECTS:
        lens_effect = "none"

    return {
        "shot_number": shot.get("shot_number", index + 1),
        "visual_description": shot.get("visual_description", ""),
        "narration_excerpt": shot.get("narration_excerpt", ""),
        "shot_type": shot_type,
        "camera_movement": camera_movement,
        "camera_reason": shot.get("camera_reason", ""),
        "lens_effect": lens_effect,
        "sfx_cue": shot.get("sfx_cue", ""),
    }


def normalize_hook_text(result):
    """hook_text is thumbnail copy, not narration - short, punchy, and
    written to be read in under a second at thumbnail size. Falls back to
    a trimmed version of the first shot's narration_excerpt if the model
    didn't provide one, so downstream thumbnail generation always has
    something usable."""
    hook_text = (result.get("hook_text") or "").strip()
    if hook_text:
        return hook_text[:MAX_HOOK_TEXT_CHARS].rstrip()

    shot_list = result.get("shot_list") or []
    if shot_list:
        fallback = (shot_list[0].get("narration_excerpt") or "").strip()
        if len(fallback) <= MAX_HOOK_TEXT_CHARS:
            return fallback
        if fallback:
            return fallback[:MAX_HOOK_TEXT_CHARS].rsplit(" ", 1)[0] + "..."

    return ""


def hook_text_matches_prompt_example(hook_text):
    """Catches the model copying the prompt's own 'Good' example verbatim
    instead of writing a real hook for this story. Compares loosely
    (lowercased, punctuation-insensitive) so minor formatting differences
    from the model don't let a copy slip through."""
    def _simplify(s):
        return "".join(ch.lower() for ch in s if ch.isalnum())

    return _simplify(hook_text) == _simplify(EXAMPLE_HOOK_TEXT)


def hook_text_too_long_to_glance(hook_text):
    """A thumbnail gets about 2 seconds of attention while someone scrolls.
    The character limit alone doesn't guarantee that - a dense 60-character
    sentence can still be too slow to read at a glance. This checks word
    count as a separate, stricter gate."""
    word_count = len(hook_text.split())
    return word_count > MAX_HOOK_TEXT_WORDS


def hook_text_matches_story(hook_text, narration_text):
    """Sanity check that the hook text is actually about this story, not a
    leftover/copied line from a different one: requires at least one
    meaningful (4+ letter) word from the hook to also appear in the
    narration. A hook built from the story's own facts will always pass
    this; a copied/hallucinated one almost never will."""
    if not hook_text or not narration_text:
        return False

    narration_lower = narration_text.lower()
    hook_words = [w.strip(".,!?\"'").lower() for w in hook_text.split()]
    meaningful_words = [w for w in hook_words if len(w) >= 4]

    if not meaningful_words:
        return True  # nothing meaningful to check, don't block on it

    return any(w in narration_lower for w in meaningful_words)


def validate_and_normalize(result):
    """Returns (is_valid, normalized_result_or_error_reason)."""
    if "narration_text" not in result or not result["narration_text"].strip():
        return False, "missing narration_text"

    shot_list = result.get("shot_list")
    if not isinstance(shot_list, list) or len(shot_list) == 0:
        return False, "missing or empty shot_list"

    if len(shot_list) < MIN_SHOTS or len(shot_list) > MAX_SHOTS:
        return False, f"shot count {len(shot_list)} outside {MIN_SHOTS}-{MAX_SHOTS} range"

    normalized_shots = [normalize_shot(s, i) for i, s in enumerate(shot_list)]

    result["shot_list"] = normalized_shots
    result["music_mood"] = result.get("music_mood", "").strip() or (
        "Tense cinematic thriller score, sparse low piano and rising strings "
        "at the start, driving percussion and brass stabs building through "
        "the middle, explosive full-orchestra climax at the reveal, "
        "tapering to a quiet resolution."
    )
    result["hook_text"] = normalize_hook_text(result)

    if hook_text_matches_prompt_example(result["hook_text"]):
        return False, "hook_text copied the prompt's example verbatim instead of writing a real one"

    if hook_text_too_long_to_glance(result["hook_text"]):
        return False, f"hook_text is {len(result['hook_text'].split())} words - too long to read in a 2-second glance (max {MAX_HOOK_TEXT_WORDS})"

    if not hook_text_matches_story(result["hook_text"], result["narration_text"]):
        return False, f"hook_text {result['hook_text']!r} doesn't appear related to this story's narration"

    return True, result


def generate_script(title, angle):
    prompt = f"""You are the head writer for "Erased," a YouTube documentary
channel telling real, historically documented true stories of ordinary people
caught in extraordinary historical moments, whose names history left out.

Episode topic: {title}
Angle: {angle}

OPENING HOOK - this is the most important part of the script. The first 8
seconds of narration determine whether the viewer stays or leaves, so follow
this exact structure for the opening lines:

1. STAKE (first 1-2 sentences): State the single most dramatic, concrete fact
   of the story immediately. Do NOT say "today we'll look at" or "this is the
   story of" or introduce the channel/topic first. Lead with the fact itself,
   as if the viewer already knows what's at risk. Use a real, specific number,
   name, or consequence from the story - not a vague tease.
   Bad: "Today we're going to talk about a forgotten hero of history."
   Good: "140,000 men dug the trenches of the Western Front - and history
   erased every one of their names."

2. VISUAL LOCK (next 1 sentence): A concrete, specific image or moment that
   proves the stake is real - not generic scene-setting.

3. CURIOSITY GAP (next 1-2 sentences): Pose the specific question the rest of
   the episode answers, so the viewer needs to keep watching to find out.

Only after these opening beats should the script settle into the normal
narrative arc. No channel intro, no "welcome back," no restating the title -
go straight into the stake.

Write a complete 8-10 minute narration script (roughly 1200-1500 words) with
this opening structure, a clear narrative arc through the rest of the story,
and a reflective closing line.

CALL TO ACTION: immediately after the emotional climax of the story and
before the final reflective closing line, write one natural, in-voice
sentence encouraging the viewer to like and subscribe so more of these
erased stories get told. This must NOT be a generic "smash that like
button" line - write it in the tone and voice of this specific episode,
using imagery or phrasing that echoes the story just told, and vary the
wording from episode to episode. It is part of the narration_text itself,
not a separate field.

THUMBNAIL HOOK TEXT - separate from the narration, also write a short,
punchy line of thumbnail cover text that would make someone scrolling
YouTube stop and click. This is NOT a narration sentence - it should read
like a headline: concrete, high-stakes, and built around the single most
shocking number, name, or fact in THIS SPECIFIC STORY (the one named in
"Episode topic" above) - never a different story.

THE 2-SECOND RULE: a thumbnail gets about 2 seconds of a scrolling viewer's
attention before they move on, and most viewers see it shrunk down on a
phone screen. The hook text must be absorbable in that window - which
means SHORT: {MAX_HOOK_TEXT_WORDS} words maximum, ideally 3-4, under
{MAX_HOOK_TEXT_CHARS} characters. This is not a summary of the story - the
video title already gives that context. This is the single emotional
spike: one number, one name, or one consequence. Use short punchy
fragments separated by periods, not one flowing sentence - fragments let
the eye grab each piece independently instead of having to read
start-to-finish.

The example below shows the STYLE only - a short fragment built from a real
number/name/consequence. It is NOT about this episode's topic. Do not reuse
it, copy it, or adapt it - write an entirely new line using facts that
actually appear in the narration you write for THIS episode.
   Bad (too long/sentence-like): "When a bomb hit the pub, 312 diaries were
   buried under the rubble."
   Style example only, from an unrelated story - never copy this line
   itself: "312 DIARIES. ONE BOMB. GONE IN SECONDS."

CINEMATIC DIRECTOR - shot list requirements:
Break the episode into EXACTLY between {MIN_SHOTS} and {MAX_SHOTS} shots -
this is a hard requirement, not a suggestion. This is a dense, sub-sentence
level breakdown - a single narration sentence should often span 2-3 separate
shots, not one. Do not write sparse, paragraph-level shots.

For each shot, provide:
- "shot_type": one of "wide", "medium", "close_up", "extreme_close_up",
  "establishing", "detail_insert"
- "camera_movement": one of "static", "pan_left", "pan_right", "tilt_up",
  "tilt_down", "zoom_in", "zoom_out", "push_in", "pull_out", "dolly_in",
  "dolly_out", "tracking", "crash_zoom", "whip_pan", "handheld_shake",
  "orbit", "drone_rise", "drone_descend", "parallax", "focus_pull",
  "dutch_angle", "snap_zoom", "speed_ramp"
- "camera_reason": one short sentence on why this movement was chosen for
  this specific narration beat
- "lens_effect": one of "shallow_depth_of_field", "lens_flare", "film_grain",
  "none" - use sparingly and only where it heightens the moment (e.g.
  shallow_depth_of_field on an emotional close-up, lens_flare on a
  triumphant reveal). Most shots should be "none".

PACING RHYTHM (Gen Z attention span - keep it moving):
- Default to quick shots (roughly 2-4 seconds of narration each). Avoid long
  static stretches.
- Only use a held/static shot deliberately, right before a big reveal or
  emotional gut-punch, to let it land. These held shots should be rare -
  most of the episode should feel fast-cut.
- Vary shot_type, camera_movement, and lens_effect constantly - never repeat
  the same camera_movement more than twice in a row. Favor the more dynamic
  movements (push_in, crash_zoom, whip_pan, orbit, drone_rise, speed_ramp)
  over plain static/pan shots to match the energy of premium AI video tools.

SOUND DESIGNER - audio requirements:
- At the top level, include "music_mood": a single descriptive prompt (for
  an AI music generator) describing the background score for the WHOLE
  episode. Score it like a THRILLER MOVIE, not a somber museum documentary:
  it should build tension progressively through the episode - start
  restrained and low-key, add layers/intensity as the story escalates, and
  peak into a dramatic, percussive climax at the episode's biggest reveal
  or emotional gut-punch, before resolving. Describe the specific arc
  explicitly in the prompt. Favor modern, high-energy scoring over
  classical/orchestral-documentary tropes - think trailer music and
  true-crime thriller scoring, not elevator-music strings.
- For each shot, include "sfx_cue": a short sound-effect prompt ONLY for
  shots that are loud or dramatic moments (explosions, gunfire, crashes,
  sudden reveals, door slams, crowd roars). For all other shots, set
  "sfx_cue" to an empty string. Do not invent SFX for quiet or ordinary
  shots - use this field sparingly.

  CALL TO ACTION: immediately after the emotional climax of the story and
before the final reflective closing line, write one natural, in-voice
sentence encouraging the viewer to like, subscribe, and share their own
thoughts in the comments so more of these erased stories get told. This
must NOT be a generic "smash that like button" line - write it in the
tone and voice of this specific episode, using imagery or phrasing that
echoes the story just told, and vary the wording from episode to episode.
It is part of the narration_text itself, not a separate field.

Return ONLY valid JSON, no other text, no markdown fences, in this exact
format:

{{
  "narration_text": "The full narration script as one string, written to be read aloud.",
  "hook_text": "Short punchy thumbnail cover line, max {MAX_HOOK_TEXT_WORDS} words and under {MAX_HOOK_TEXT_CHARS} characters, readable in a 2-second glance, written specifically for THIS episode's topic - never the style example above.",
  "music_mood": "Background score prompt for the whole episode, describing its build-up arc.",
  "shot_list": [
    {{
      "shot_number": 1,
      "visual_description": "Detailed description for AI image/video generation",
      "narration_excerpt": "The exact portion of narration this shot covers",
      "shot_type": "wide",
      "camera_movement": "push_in",
      "camera_reason": "Why this movement fits this beat",
      "lens_effect": "none",
      "sfx_cue": ""
    }}
  ]
}}

Include between {MIN_SHOTS} and {MAX_SHOTS} shots covering the full narration."""

    last_reason = None
    for attempt in range(MAX_GENERATION_ATTEMPTS):
        raw = call_openrouter(prompt)
        try:
            parsed = extract_json(raw)
        except (ValueError, json.JSONDecodeError) as e:
            last_reason = f"JSON parse failed: {e}"
            print(f"Attempt {attempt + 1}/{MAX_GENERATION_ATTEMPTS} failed - {last_reason}")
            continue

        is_valid, result = validate_and_normalize(parsed)
        if is_valid:
            return result

        last_reason = result
        print(f"Attempt {attempt + 1}/{MAX_GENERATION_ATTEMPTS} failed - {last_reason}")

    raise RuntimeError(f"Script generation failed after {MAX_GENERATION_ATTEMPTS} attempts. Last reason: {last_reason}")


def save_script(topic_id, narration_text, shot_list, music_mood, hook_text):
    resp = requests.post(
        f"{SUPABASE_URL}/rest/v1/scripts",
        headers={**HEADERS, "Prefer": "return=representation"},
        json={
            "topic_id": topic_id,
            "narration_text": narration_text,
            "shot_list": shot_list,
            "music_mood": music_mood,
            "hook_text": hook_text,
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
    save_script(
        topic["id"],
        result["narration_text"],
        result["shot_list"],
        result["music_mood"],
        result["hook_text"],
    )
    mark_topic_scripted(topic["id"])
    print("Done.")


if __name__ == "__main__":
    main()
