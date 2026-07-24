import os
import re
import sys
import json
import asyncio
import requests
import numpy as np
from supabase import create_client
import edge_tts
from pydub import AudioSegment
from pydub.effects import normalize as pydub_normalize

# --- Config from GitHub Actions secrets ---
SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_SECRET_KEY = os.environ["SUPABASE_SECRET_KEY"]

# Edge TTS - replaces Kokoro. Chosen for more natural/expressive prosody.
# Male voice picked for this documentary/history-storytelling niche.
VOICE_NAME = "en-US-GuyNeural"
RATE = "-5%"

# Pause after EVERY sentence, per Zia's explicit instruction - not just
# paragraph breaks. 1-2s per pause (reduced from an earlier 4-5s, which
# would have added ~3 extra minutes of silence across a 40+ sentence script).
PAUSE_SECONDS_MIN = 1.0
PAUSE_SECONDS_MAX = 2.0


def split_into_segments(narration_text):
    """Splits narration into one segment per SENTENCE, so a pause gets
    inserted after every sentence (not just at paragraph/blank-line
    breaks, which most scripts don't have). Sentence boundary = ./!/?
    followed by whitespace. Falls back to the whole text as a single
    segment if no sentence-ending punctuation is found at all."""
    raw_segments = re.split(r"(?<=[.!?])\s+", narration_text.strip())
    segments = [seg.strip() for seg in raw_segments if seg.strip()]
    return segments if segments else [narration_text.strip()]


async def _synthesize_sentence(text, voice, rate, out_path):
    communicate = edge_tts.Communicate(text, voice, rate=rate)
    await communicate.save(out_path)


def synthesize_sentence(text, voice, rate, tmp_path):
    """One real TTS call per full sentence - correct prosody/intonation,
    no mid-sentence resets (this was the fix for the choppy,
    sub-sentence-fragment narration bug). Returns a pydub AudioSegment."""
    asyncio.run(_synthesize_sentence(text, voice, rate, tmp_path))
    return AudioSegment.from_file(tmp_path)


def synthesize_with_pauses(narration_text, voice, rate):
    """Synthesizes narration sentence-by-sentence and concatenates them
    with a real silence gap (1-2s) after every sentence. Used only when
    no shot_list is available yet (fallback path)."""
    segments = split_into_segments(narration_text)
    print(f"Narration split into {len(segments)} sentence(s) for pause insertion.")

    combined = AudioSegment.silent(duration=0)
    for i, segment in enumerate(segments):
        clip = synthesize_sentence(segment, voice, rate, f"/tmp/sent_{i}.mp3")
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

    # Shots rarely tile the narration_text with perfect word-for-word
    # coverage (minor rewording/punctuation differences from the model).
    # Scale shot-word-space onto sentence-word-space so the two line up
    # proportionally end-to-end rather than drifting apart.
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


def synthesize_per_sentence_with_shot_durations(narration_text, shot_list, voice, rate):
    """Synthesizes narration one real SENTENCE at a time via Edge TTS -
    this is the fix for the choppy, sub-sentence-fragment narration bug.
    Each full sentence gets ONE natural TTS call (correct prosody/
    intonation, no mid-sentence resets), with a real 1-2s pause only at
    real sentence boundaries.

    Per-shot video-sync timing still works: each sentence's single real
    measured audio duration is distributed across the shots that fall
    inside it, proportional to word count, instead of generating audio
    separately per shot fragment.
    """
    sentences = split_into_segments(narration_text)
    print(f"Narration split into {len(sentences)} real sentence(s) for natural TTS.")

    combined = AudioSegment.silent(duration=0)
    sentence_durations = []

    for i, sentence in enumerate(sentences):
        clip = synthesize_sentence(sentence, voice, rate, f"/tmp/sent_{i}.mp3")
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
        # No shot has usable narration_excerpt text - split total time evenly
        # across shots as a last-resort fallback.
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


def main():
    supabase = create_client(SUPABASE_URL, SUPABASE_SECRET_KEY)

    # 1. Get one pending script
    result = supabase.table("scripts").select("*").eq("status", "pending").limit(1).execute()
    if not result.data:
        print("No pending scripts found. Exiting.")
        return

    script = result.data[0]
    script_id = script["id"]
    narration_text = script["narration_text"]
    shot_list = script.get("shot_list")
    if isinstance(shot_list, str):
        shot_list = json.loads(shot_list)
    print(f"Narrating script id={script_id}, length={len(narration_text)} chars, {len(shot_list or [])} shots")

    # 2. Generate narration audio via Edge TTS, one real sentence at a
    # time (natural prosody, no mid-sentence fragment resets). If
    # shot_list is available, each sentence's real measured duration is
    # distributed across the shots inside it for accurate video-sync
    # timing. Falls back to the whole-text sentence-split method (no
    # shot durations) if shot_list isn't available yet.
    shot_durations = None
    if shot_list:
        combined_audio, shot_durations = synthesize_per_sentence_with_shot_durations(
            narration_text, shot_list, VOICE_NAME, RATE
        )
    else:
        combined_audio = synthesize_with_pauses(narration_text, VOICE_NAME, RATE)

    # 2b. Normalize loudness to a consistent, normal level.
    combined_audio = pydub_normalize(combined_audio)

    output_filename = f"narration_{script_id}.wav"
    combined_audio.export(output_filename, format="wav")
    print(f"Audio written to {output_filename}")

    # 3. Upload to Supabase storage bucket 'narration'
    with open(output_filename, "rb") as f:
        supabase.storage.from_("narration").upload(
            output_filename,
            f,
            {"content-type": "audio/wav", "upsert": "true"}
        )
    public_url = supabase.storage.from_("narration").get_public_url(output_filename)
    print(f"Uploaded. Public URL: {public_url}")

    # 4. Update script status, narration URL, and real per-shot timing.
    # Status goes straight to 'images_generated' (skipping the old,
    # now-removed image_generation.py stage - Agnes generates video
    # directly from shot_list text, it never used the still images).
    update_payload = {
        "status": "images_generated",
        "narration_url": public_url
    }
    if shot_durations is not None:
        update_payload["shot_durations"] = shot_durations
    supabase.table("scripts").update(update_payload).eq("id", script_id).execute()
    print("Script status updated to 'images_generated'. Done.")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
