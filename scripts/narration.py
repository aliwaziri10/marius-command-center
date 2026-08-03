import os
import re
import sys
import json
import subprocess
from supabase import create_client
import torchaudio
from chatterbox.tts import ChatterboxTTS
from pydub import AudioSegment
from pydub.effects import normalize as pydub_normalize

# --- Config from GitHub Actions secrets ---
SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_SECRET_KEY = os.environ["SUPABASE_SECRET_KEY"]

# Chatterbox - replaces Edge TTS. Switched after a side-by-side comparison
# found Chatterbox has noticeably more natural prosody/"feel". Same switch
# already made on TechPulse.
SLOWDOWN_FACTOR = "0.95"  # ~5% slower, pitch preserved (was RATE="-5%" under Edge TTS)

# Pause after EVERY sentence, per Zia's explicit instruction - not just
# paragraph breaks. 1-2s per pause.
PAUSE_SECONDS_MIN = 1.0
PAUSE_SECONDS_MAX = 2.0

# STUTTER/DUPLICATE GUARD: carried over from the Edge TTS version. Sanity-
# checks a synthesized sentence's duration against a rough expected speaking
# pace for its word count, and retries if the clip looks glitched
# (duplicated/restarted audio). Generic safety net, not backend-specific.
MIN_PLAUSIBLE_WORDS_PER_SECOND = 1.6
DURATION_SLACK_SECONDS = 1.0
MAX_SENTENCE_TTS_ATTEMPTS = 3

_tts_model = None


def get_tts_model():
    global _tts_model
    if _tts_model is None:
        _tts_model = ChatterboxTTS.from_pretrained(device="cpu")
    return _tts_model


def split_into_segments(narration_text):
    """Splits narration into one segment per SENTENCE, so a pause gets
    inserted after every sentence (not just at paragraph/blank-line
    breaks, which most scripts don't have). Sentence boundary = ./!/?
    followed by whitespace. Falls back to the whole text as a single
    segment if no sentence-ending punctuation is found at all."""
    raw_segments = re.split(r"(?<=[.!?])\s+", narration_text.strip())
    segments = [seg.strip() for seg in raw_segments if seg.strip()]
    return segments if segments else [narration_text.strip()]


def _max_plausible_duration(text):
    word_count = max(len(text.split()), 1)
    return (word_count / MIN_PLAUSIBLE_WORDS_PER_SECOND) + DURATION_SLACK_SECONDS


def synthesize_sentence(text, tts, tmp_path):
    """One real Chatterbox TTS call per full sentence - correct prosody/
    intonation, no mid-sentence resets. Returns a pydub AudioSegment.

    STUTTER/DUPLICATE GUARD: validates the synthesized clip's duration
    against a rough expected-speaking-pace ceiling for that sentence's word
    count, retrying if the clip looks glitched (duplicated/restarted audio)
    instead of trusting it blindly.
    """
    max_plausible = _max_plausible_duration(text)
    last_duration = None
    clip = None

    for attempt in range(MAX_SENTENCE_TTS_ATTEMPTS):
        wav = tts.generate(text)
        torchaudio.save(tmp_path, wav, tts.sr)
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


def synthesize_with_pauses(narration_text, tts):
    """Synthesizes narration sentence-by-sentence and concatenates them
    with a real silence gap (1-2s) after every sentence. Used only when
    no shot_list is available yet (fallback path)."""
    segments = split_into_segments(narration_text)
    print(f"Narration split into {len(segments)} sentence(s) for pause insertion.")

    combined = AudioSegment.silent(duration=0)
    for i, segment in enumerate(segments):
        clip = synthesize_sentence(segment, tts, f"/tmp/sent_{i}.wav")
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


def synthesize_per_sentence_with_shot_durations(narration_text, shot_list, tts):
    """Synthesizes narration one real SENTENCE at a time via Chatterbox.
    Each full sentence gets ONE natural TTS call (correct prosody/
    intonation, no mid-sentence resets), with a real 1-2s pause only at
    real sentence boundaries.

    Per-shot video-sync timing still works: each sentence's single real
    measured audio duration is distributed across the shots that fall
    inside it, proportional to word count.
    """
    sentences = split_into_segments(narration_text)
    print(f"Narration split into {len(sentences)} real sentence(s) for natural TTS.")

    combined = AudioSegment.silent(duration=0)
    sentence_durations = []

    for i, sentence in enumerate(sentences):
        clip = synthesize_sentence(sentence, tts, f"/tmp/sent_{i}.wav")
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

    tts = get_tts_model()

    # 2. Generate narration audio via Chatterbox, one real sentence at a
    # time (natural prosody, no mid-sentence fragment resets). If
    # shot_list is available, each sentence's real measured duration is
    # distributed across the shots inside it for accurate video-sync
    # timing. Falls back to the whole-text sentence-split method (no
    # shot durations) if shot_list isn't available yet.
    shot_durations = None
    if shot_list:
        combined_audio, shot_durations = synthesize_per_sentence_with_shot_durations(
            narration_text, shot_list, tts
        )
    else:
        combined_audio = synthesize_with_pauses(narration_text, tts)

    # 2b. Normalize loudness to a consistent, normal level.
    combined_audio = pydub_normalize(combined_audio)

    raw_filename = f"narration_{script_id}_raw.wav"
    output_filename = f"narration_{script_id}.wav"
    combined_audio.export(raw_filename, format="wav")

    # 2c. Slow down slightly for pacing (pitch preserved via ffmpeg atempo),
    # matching the -5% rate used under Edge TTS.
    subprocess.run(
        ["ffmpeg", "-y", "-i", raw_filename, "-filter:a", f"atempo={SLOWDOWN_FACTOR}", output_filename],
        check=True, capture_output=True,
    )
    os.remove(raw_filename)
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
    update_payload = {
        "status": "images_generated",
        "narration_url": public_url
    }
    if shot_durations is not None:
        # Shot durations were measured BEFORE the final atempo slowdown -
        # scale them by the same factor so they still match the exported,
        # slowed-down audio.
        slowdown = float(SLOWDOWN_FACTOR)
        update_payload["shot_durations"] = [d / slowdown for d in shot_durations]
    supabase.table("scripts").update(update_payload).eq("id", script_id).execute()
    print("Script status updated to 'images_generated'. Done.")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
