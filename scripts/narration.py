import os
import re
import sys
import json
import time
import asyncio
import subprocess
import edge_tts
from supabase import create_client
from pydub import AudioSegment
from pydub.effects import normalize as pydub_normalize

# --- Config from GitHub Actions secrets ---
SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_SECRET_KEY = os.environ["SUPABASE_SECRET_KEY"]

# EDGE TTS REVERT (2026-08-06): reverted off Chatterbox (local neural TTS,
# too slow/heavy on a GitHub-hosted CPU runner - real cause of workflow
# runs stalling ~25 minutes then getting killed by the runner) and off the
# earlier Kokoro engine before that. Back to edge-tts: a lightweight HTTPS
# call to Microsoft's Edge TTS service, no local model, no GPU/CPU cost.
VOICE = "en-US-GuyNeural"

# Speech rate passed directly to edge-tts per sentence. Edge TTS supports a
# native rate parameter, so no separate ffmpeg atempo pass is needed here
# (that was only required for Chatterbox, which has no rate control).
RATE = "-5%"

# Pause after EVERY sentence, per Zia's explicit instruction - not just
# paragraph breaks. 1-2s per pause.
PAUSE_SECONDS_MIN = 1.0
PAUSE_SECONDS_MAX = 2.0

# STUTTER/DUPLICATE GUARD: carried over from prior engines. Sanity-checks a
# synthesized sentence's duration against a rough expected speaking pace for
# its word count, and retries if the clip looks glitched. Kept as a generic
# safety net even though edge-tts is far less prone to this than Chatterbox.
MIN_PLAUSIBLE_WORDS_PER_SECOND = 1.6
DURATION_SLACK_SECONDS = 1.0
MAX_SENTENCE_TTS_ATTEMPTS = 3

# Max pending scripts to narrate in a single workflow run. Was hardcoded to
# 1 - with narration now running every 30 min (was 2x/day), pulling only one
# script per run wastes the tighter cron if more than one is pending.
MAX_SCRIPTS_PER_RUN = 1

# STORAGE 413 FIX (2026-08-18): confirmed live against a real failed run -
# "ba5d96c8" (31 shots, 15,606-char narration, 119 real sentences) synthesized
# successfully but failed on upload with a real Supabase Storage 413 Payload
# Too Large. Root cause: combined_audio was exported as uncompressed WAV
# (format="wav"), which for a full-length episode easily clears the
# project's storage size ceiling. video_generation.py already branches on
# file extension when downloading narration_url (.mp3 vs .wav), so switching
# the export to MP3 needs no downstream change - it only shrinks the
# uploaded file (roughly 8-10x smaller than the equivalent WAV) so it clears
# the limit. MP3 export requires libmp3lame, which ships with the ffmpeg apt
# package already installed by narration.yml's "Install ffmpeg" step.
NARRATION_EXPORT_FORMAT = "mp3"
NARRATION_FILE_EXTENSION = "mp3"
NARRATION_CONTENT_TYPE = "audio/mpeg"

# ABBREVIATION-SPLIT FIX (2026-08-29): split_into_segments below split on
# ANY ".", "!", or "?" followed by whitespace - which wrongly treats
# abbreviations and initials as full sentence ends. "Dr. Smith explained"
# was being split into "Dr." and "Smith explained" as if they were two
# separate sentences, each getting its own TTS call AND the full 1-2s
# inter-sentence pause inserted between them - audible as the narrator
# stopping mid-sentence before continuing (Zia's report: narration "does
# not complete a sentence in one go"). This list covers common
# abbreviations/titles/initials that precede a period without ending the
# sentence; if the word right before the period matches one of these (or
# is a single letter, i.e. an initial), the split is skipped and the
# sentence keeps building instead of being cut there.
_ABBREVIATIONS = {
    "mr", "mrs", "ms", "dr", "prof", "sr", "jr", "st", "no", "vs",
    "etc", "eg", "ie", "approx", "inc", "ltd", "corp", "co", "u.s",
    "u.k", "u.n", "u.s.a", "a.m", "p.m", "ph.d", "gov", "sen", "rep",
    "capt", "gen", "lt", "col", "maj", "ave", "blvd", "dept",
}


def split_into_segments(narration_text):
    """Splits narration into one segment per real SENTENCE, so a pause gets
    inserted only at genuine sentence boundaries - not after abbreviations,
    titles, or initials that happen to end in a period. Sentence boundary =
    ./!/? followed by whitespace, UNLESS the word immediately before that
    punctuation is a known abbreviation/title or a single letter (an
    initial like "J."), in which case the split is skipped and the
    sentence keeps accumulating. Falls back to the whole text as a single
    segment if no genuine sentence-ending punctuation is found at all."""
    raw_pieces = re.split(r"(?<=[.!?])\s+", narration_text.strip())
    segments = []
    buffer = ""
    for piece in raw_pieces:
        buffer = f"{buffer} {piece}".strip() if buffer else piece
        match = re.search(r"([A-Za-z]+)\.$", buffer)
        if match:
            word = match.group(1).lower()
            if word in _ABBREVIATIONS or len(word) <= 2:
                continue  # not a real sentence end - keep accumulating
        segments.append(buffer.strip())
        buffer = ""
    if buffer.strip():
        segments.append(buffer.strip())
    return [s for s in segments if s] or [narration_text.strip()]


def _max_plausible_duration(text):
    word_count = max(len(text.split()), 1)
    return (word_count / MIN_PLAUSIBLE_WORDS_PER_SECOND) + DURATION_SLACK_SECONDS


async def _synthesize_edge(text, out_path):
    communicate = edge_tts.Communicate(text, VOICE, rate=RATE)
    await communicate.save(out_path)


def synthesize_sentence(text, tmp_path):
    """One edge-tts call per full sentence - correct prosody/intonation, no
    mid-sentence resets. Returns a pydub AudioSegment.

    STUTTER/DUPLICATE GUARD: validates the synthesized clip's duration
    against a rough expected-speaking-pace ceiling for that sentence's word
    count, retrying if the clip looks glitched instead of trusting it
    blindly.
    """
    max_plausible = _max_plausible_duration(text)
    last_duration = None
    clip = None

    for attempt in range(MAX_SENTENCE_TTS_ATTEMPTS):
        asyncio.run(_synthesize_edge(text, tmp_path))
        clip = AudioSegment.from_file(tmp_path)
        duration_seconds = len(clip) / 1000.0
        last_duration = duration_seconds

        if duration_seconds <= max_plausible:
            return clip

        print(f"TTS output for sentence looks like a stutter/duplicate "
              f"({duration_seconds:.1f}s, expected under {max_plausible:.1f}s for "
              f"{len(text.split())} words) - attempt {attempt + 1}/{MAX_SENTENCE_TTS_ATTEMPTS}. "
              f"Sentence: {text[:80]!r}")

    print(f"Sentence still looks anomalous after {MAX_SENTENCE_TTS_ATTEMPTS} attempts "
          f"({last_duration:.1f}s) - using the last attempt anyway rather than blocking the whole run: "
          f"{text[:80]!r}")
    return clip


def synthesize_with_pauses(narration_text):
    """Synthesizes narration sentence-by-sentence and concatenates them
    with a real silence gap (1-2s) after every sentence. Used only when
    no shot_list is available yet (fallback path)."""
    segments = split_into_segments(narration_text)
    print(f"Narration split into {len(segments)} sentence(s) for pause insertion.")

    combined = AudioSegment.silent(duration=0)
    for i, segment in enumerate(segments):
        clip = synthesize_sentence(segment, f"/tmp/sent_{i}.mp3")
        combined += clip
        if i < len(segments) - 1:
            pause_len = PAUSE_SECONDS_MIN if i % 2 == 0 else PAUSE_SECONDS_MAX
            combined += AudioSegment.silent(duration=int(pause_len * 1000))

    return combined


def _assign_shots_to_sentences(sentences, shot_list):
    """Maps each shot's narration_excerpt onto the real sentence(s) it
    falls inside, using word-position overlap (not per-shot TTS).

    Shots are sub-sentence fragments by design (script_writing.py splits
    one sentence across 2-3 shots for fast-cut editing) - this function
    figures out, for each shot, which sentence(s) its words came from and
    how many words it contributed to each, so a sentence's single real
    audio duration can later be split proportionally across its shots.

    Returns (contributions, sentence_word_bounds) or None if no shot has
    usable narration_excerpt text at all.
    """
    sentence_word_counts = [max(len(s.split()), 1) for s in sentences]
    shot_word_counts = [
        len((shot.get("narration_excerpt") or "").split()) for shot in shot_list
    ]

    total_sentence_words = sum(sentence_word_counts)
    total_shot_words = sum(shot_word_counts)
    if total_shot_words == 0:
        return None

    scale = total_sentence_words / total_shot_words

    sentence_bounds = []
    running = 0
    for wc in sentence_word_counts:
        sentence_bounds.append((running, running + wc))
        running += wc

    contributions = []
    running_shot_pos = 0.0
    for wc in shot_word_counts:
        start = running_shot_pos * scale
        end = (running_shot_pos + wc) * scale
        running_shot_pos += wc

        shot_contribs = []
        for s_idx, (s_start, s_end) in enumerate(sentence_bounds):
            overlap = min(end, s_end) - max(start, s_start)
            if overlap > 0:
                shot_contribs.append((s_idx, overlap))
        contributions.append(shot_contribs)

    return contributions, sentence_bounds


def synthesize_per_sentence_with_shot_durations(narration_text, shot_list):
    """Synthesizes narration one real SENTENCE at a time via edge-tts. Each
    full sentence gets ONE natural TTS call (correct prosody/intonation, no
    mid-sentence resets), with a real 1-2s pause only at real sentence
    boundaries.

    Per-shot video-sync timing still works: each sentence's single real
    measured audio duration is distributed across the shots that fall
    inside it, proportional to word count.
    """
    sentences = split_into_segments(narration_text)
    print(f"Narration split into {len(sentences)} real sentence(s) for natural TTS.")

    combined = AudioSegment.silent(duration=0)
    sentence_durations = []

    for i, sentence in enumerate(sentences):
        clip = synthesize_sentence(sentence, f"/tmp/sent_{i}.mp3")
        combined += clip
        sentence_durations.append(len(clip) / 1000.0)

        if i < len(sentences) - 1:
            pause_len = PAUSE_SECONDS_MIN if i % 2 == 0 else PAUSE_SECONDS_MAX
            combined += AudioSegment.silent(duration=int(pause_len * 1000))
            # The pause belongs to the sentence right before it timing-wise.
            sentence_durations[-1] += pause_len

    shot_durations = [0.0] * len(shot_list)
    result = _assign_shots_to_sentences(sentences, shot_list)
    if result is None:
        even_share = sum(sentence_durations) / max(len(shot_list), 1)
        shot_durations = [even_share] * len(shot_list)
    else:
        contributions, sentence_bounds = result
        for shot_idx, shot_contribs in enumerate(contributions):
            for s_idx, words in shot_contribs:
                s_start, s_end = sentence_bounds[s_idx]
                sentence_word_span = max(s_end - s_start, 1)
                share = (words / sentence_word_span) * sentence_durations[s_idx]
                shot_durations[shot_idx] += share

    return combined, shot_durations


def narrate_one_script(supabase, script):
    """Runs the full narration pipeline for a single script row. Returns
    True on success, False on failure (logged, not raised, so one bad
    script in a batch doesn't stop the rest)."""
    script_id = script["id"]
    narration_text = script["narration_text"]
    shot_list = script.get("shot_list")
    if isinstance(shot_list, str):
        shot_list = json.loads(shot_list)
    print(f"Narrating script id={script_id}, length={len(narration_text)} chars, {len(shot_list or [])} shots")

    try:
        shot_durations = None
        if shot_list:
            combined_audio, shot_durations = synthesize_per_sentence_with_shot_durations(
                narration_text, shot_list
            )
        else:
            combined_audio = synthesize_with_pauses(narration_text)

        combined_audio = pydub_normalize(combined_audio)

        # STORAGE 413 FIX (2026-08-18): was format="wav" (uncompressed) -
        # confirmed via a real failed production run that this clears
        # Supabase Storage's size ceiling on any full-length episode.
        # MP3 export needs no downstream change: video_generation.py
        # already branches on narration_url's file extension.
        output_filename = f"narration_{script_id}.{NARRATION_FILE_EXTENSION}"
        combined_audio.export(output_filename, format=NARRATION_EXPORT_FORMAT, bitrate="128k")
        print(f"Audio written to {output_filename}")

        with open(output_filename, "rb") as f:
            supabase.storage.from_("narration").upload(
                output_filename,
                f,
                {"content-type": NARRATION_CONTENT_TYPE, "upsert": "true"}
            )
        public_url = supabase.storage.from_("narration").get_public_url(output_filename)
        print(f"Uploaded. Public URL: {public_url}")

        update_payload = {
            "status": "images_generated",
            "narration_url": public_url
        }
        if shot_durations is not None:
            update_payload["shot_durations"] = shot_durations
        supabase.table("scripts").update(update_payload).eq("id", script_id).execute()
        print(f"Script {script_id} status updated to 'images_generated'.")
        return True

    except Exception as e:
        print(f"ERROR narrating script {script_id}: {e}", file=sys.stderr)
        return False


def main():
    supabase = create_client(SUPABASE_URL, SUPABASE_SECRET_KEY)

    # 1. Get a batch of pending scripts (was limit(1) - narration now runs
    # every 30 min instead of 2x/day, so pulling only one per run would
    # waste the tighter cron whenever more than one script is pending).
    result = supabase.table("scripts").select("*").eq("status", "pending").limit(MAX_SCRIPTS_PER_RUN).execute()
    if not result.data:
        print("No pending scripts found. Exiting.")
        return

    print(f"Found {len(result.data)} pending script(s) to narrate this run.")

    success_count = 0
    for script in result.data:
        if narrate_one_script(supabase, script):
            success_count += 1

    print(f"Done. {success_count}/{len(result.data)} script(s) narrated successfully.")
    if success_count < len(result.data):
        sys.exit(1)


if __name__ == "__main__":
    main()
