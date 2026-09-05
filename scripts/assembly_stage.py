"""
Marius Command Center - assembly stage (split from video_generation.py,
2026-09-06, same pattern as the 2026-08-18 script_writing.py split).

Everything that turns a finished set of shot clips + narration into the
final uploadable video: audio mixing (narration/music/SFX/original-clip-
audio + safety limiter), caption rendering, the trail-extension on the
final shot, final concatenation/encode, and the upload to B2. Imports
clip-generation internals it reuses for the trail extension from
clip_generation.py rather than duplicating them.

FIX 1 (waxy/plastic AI skin, 2026-09-06): adds a post-processing
grade->blur->grain ffmpeg filter chain to the final encode in
assemble_final_video's write_videofile call - order matters (grade,
then blur, then grain; no sharpening anywhere in this pipeline). This is
the post-processing half of Fix 1; the prompt-level QUALITY_GUARD half
already lives in prompt_builder.py and has been live since 2026-08-22.
"""

import os
import time
import numpy as np
import requests
from PIL import Image, ImageDraw, ImageFont
from moviepy import (
    VideoFileClip,
    AudioFileClip,
    ImageClip,
    CompositeAudioClip,
    concatenate_videoclips,
    concatenate_audioclips,
)
from moviepy.video.fx import FadeIn, FadeOut
from moviepy.audio.fx import AudioFadeIn, AudioFadeOut

import storage_b2
from agnes_client import WIDTH, HEIGHT, FRAME_RATE, MAX_CLIP_SECONDS
from clip_generation import (
    _extract_last_frame_local,
    _upload_local_image_for_anchor,
    _generate_one_segment,
    fit_clip_to_duration,
)

FREESOUND_API_KEY = os.environ.get("FREESOUND_API_KEY")
ACE_MUSIC_API_KEY = os.environ.get("ACE_MUSIC_API_KEY")
HF_TOKEN = os.environ.get("HF_TOKEN")

ACE_MUSIC_BASES = ["https://api.acemusic.ai", "https://ai.acemusic.ai"]
ACE_MUSIC_HEADERS = {
    "Authorization": f"Bearer {ACE_MUSIC_API_KEY}",
    "Content-Type": "application/json",
}

HF_MUSICGEN_URL = "https://api-inference.huggingface.co/models/facebook/musicgen-small"

FADE_IN_SECONDS = 0.75
FADE_OUT_SECONDS = 1.5

NARRATION_VOLUME = 1.0
MUSIC_VOLUME = 0.18
SFX_VOLUME = 0.85
ORIGINAL_CLIP_AUDIO_VOLUME = 0.30
LIMITER_CEILING = 0.98

# CHUNKED-UPLOAD QUALITY FIX (2026-08-20): originally kept every video
# under Supabase's 50MB free-tier cap by crushing bitrate - fixed by
# fixing bitrate at a real quality level and chunking the output instead
# whenever needed. QUALITY_VIDEO_BITRATE_KBPS itself stays (still the
# right, duration-independent quality target).
QUALITY_VIDEO_BITRATE_KBPS = 3000   # fixed, duration-independent - healthy 720p HEVC quality

CAPTION_FONT_PATHS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]
CAPTION_FONT_SIZE = 28
CAPTION_MAX_WIDTH_RATIO = 0.70
CAPTION_BOTTOM_MARGIN = 60
CAPTION_LINE_SPACING = 10
CAPTION_TEXT_COLOR = (255, 255, 255, 255)
CAPTION_STROKE_COLOR = (0, 0, 0, 255)
CAPTION_STROKE_WIDTH = 3
CAPTION_BG_COLOR = (0, 0, 0, 140)
CAPTION_BG_PADDING = 16

# FIX 1 - WAXY/PLASTIC AI SKIN, post-processing half (2026-09-06): applied
# as the LAST step of the final encode, after everything else. Order
# matters - grade (contrast/saturation) first, then blur, then grain, and
# never any sharpening anywhere in this pipeline (sharpening is what
# produces the over-sharp, texture-suppressed "waxy" look in the first
# place). gblur=sigma=0.3 is a very light softening, just enough to break
# up AI over-sharpness without visibly softening the whole frame; the
# noise filter re-adds fine grain so skin doesn't read as airbrushed-flat
# after the blur.
SKIN_REALISM_VF = "eq=contrast=1.05:saturation=1.03,gblur=sigma=0.3,noise=alls=6:allf=t+u"


def download_file(url, out_path):
    r = requests.get(url, timeout=120)
    r.raise_for_status()
    with open(out_path, "wb") as f:
        f.write(r.content)
    return out_path


def compute_shot_start_times(shot_durations):
    starts = []
    t = 0.0
    for d in shot_durations:
        starts.append(t)
        t += d
    return starts


def compute_target_bitrate(duration_seconds=None, audio_kbps=128):
    # CHUNKED-UPLOAD QUALITY FIX (2026-08-20): no longer takes duration or
    # target_mb into account at all - bitrate used to be squeezed down as
    # episodes got longer, which is exactly what produced the ~144p-looking
    # 19-minute upload Zia flagged. Video bitrate is now a FIXED quality
    # value (QUALITY_VIDEO_BITRATE_KBPS) regardless of how long the episode
    # is. duration_seconds/audio_kbps args kept for call-site compatibility
    # but no longer change the result.
    return f"{QUALITY_VIDEO_BITRATE_KBPS}k"


def estimate_output_size_mb(duration_seconds, video_kbps=QUALITY_VIDEO_BITRATE_KBPS, audio_kbps=128):
    total_kbps = video_kbps + audio_kbps
    total_bits = total_kbps * 1000 * duration_seconds
    return total_bits / 8 / 1024 / 1024


def fit_audio_to_duration(audio_clip, target):
    if audio_clip.duration >= target:
        return audio_clip.subclipped(0, target)
    reps = int(target // audio_clip.duration) + 1
    looped = concatenate_audioclips([audio_clip] * reps)
    return looped.subclipped(0, target)


def poll_ace_music_task(task_id, out_path, base_url=None, max_wait=180, interval=8):
    waited = 0
    while waited < max_wait:
        resp = requests.post(
            f"{base_url}/query_result",
            headers=ACE_MUSIC_HEADERS,
            json={"task_id_list": [task_id]},
            timeout=30,
        )
        if resp.status_code >= 400:
            print(f"ACE MUSIC POLL ERROR ({base_url}) {resp.status_code}: {resp.text}")
            return None
        entries = resp.json().get("data", [])
        if not entries:
            time.sleep(interval)
            waited += interval
            continue
        entry = entries[0]
        status = entry.get("status")
        if status == 1:
            import json as _json
            result_list = _json.loads(entry.get("result", "[]"))
            if not result_list or not result_list[0].get("file"):
                print(f"ACE Music task succeeded but no file in result: {result_list}")
                return None
            file_path = result_list[0]["file"]
            audio_resp = requests.get(f"{base_url}{file_path}", timeout=60)
            audio_resp.raise_for_status()
            with open(out_path, "wb") as f:
                f.write(audio_resp.content)
            return out_path
        if status == 2:
            print(f"ACE Music task failed: {entry}")
            return None
        time.sleep(interval)
        waited += interval
    print(f"ACE Music task {task_id} timed out after {max_wait}s")
    return None


def generate_background_music(prompt, duration, out_path, debug=None):
    """
    AUDIO-DEBUG FIX (2026-08-23): music_generated has been false on every
    single episode ever assembled, with no way to see why without GitHub
    Actions log access (which Zia does not have). `debug`, when passed a
    dict by the caller, gets the LAST real error string written to it
    under debug["music_error"] on total failure - this dict is threaded
    all the way up to mark_video_generated and persisted to the new
    scripts.audio_debug column, so the real cause becomes queryable
    directly from Supabase instead of requiring log access at all.
    Behavior/return value is otherwise unchanged.
    """
    if not ACE_MUSIC_API_KEY:
        msg = "No ACE_MUSIC_API_KEY set - skipping background music."
        print(msg)
        if debug is not None:
            debug["music_error"] = msg
        return None

    last_error = None
    for base in ACE_MUSIC_BASES:
        try:
            resp = requests.post(
                f"{base}/release_task",
                headers=ACE_MUSIC_HEADERS,
                json={
                    "prompt": prompt,
                    "audio_duration": max(10, min(int(duration) + 5, 600)),
                    "thinking": True,
                },
                timeout=60,
            )
            if resp.status_code >= 400:
                last_error = f"ACE MUSIC ERROR ({base}) {resp.status_code}: {resp.text[:500]}"
                print(last_error)
                continue
            task_id = resp.json().get("data", {}).get("task_id")
            if not task_id:
                last_error = f"ACE Music response had no task_id ({base}): {str(resp.json())[:500]}"
                print(last_error)
                continue
            result = poll_ace_music_task(task_id, out_path, base_url=base)
            if result:
                return result
            last_error = f"ACE Music task on {base} did not return a usable file (see poll log)."
        except Exception as e:
            last_error = f"ACE Music generation raised an exception on {base}: {e}"
            print(f"{last_error} - trying next host.")

    print("Every ACE Music host failed - trying free Hugging Face MusicGen fallback.")
    result = generate_background_music_musicgen(prompt, duration, out_path, debug=debug)
    if result is None and debug is not None and "music_error" not in debug:
        debug["music_error"] = last_error or "ACE Music failed on all hosts (no specific error captured)."
    return result


def generate_background_music_musicgen(prompt, duration, out_path, debug=None):
    if not HF_TOKEN:
        msg = "No HF_TOKEN set - skipping MusicGen fallback, continuing without background music."
        print(msg)
        if debug is not None:
            debug["music_error"] = msg
        return None
    try:
        resp = requests.post(
            HF_MUSICGEN_URL,
            headers={"Authorization": f"Bearer {HF_TOKEN}"},
            json={"inputs": prompt},
            timeout=120,
        )
        if resp.status_code == 503:
            wait_for = 20
            try:
                wait_for = min(int(resp.json().get("estimated_time", 20)) + 2, 60)
            except Exception:
                pass
            print(f"MusicGen is cold-loading on Hugging Face - waiting {wait_for}s and retrying once.")
            time.sleep(wait_for)
            resp = requests.post(
                HF_MUSICGEN_URL,
                headers={"Authorization": f"Bearer {HF_TOKEN}"},
                json={"inputs": prompt},
                timeout=120,
            )
        if resp.status_code >= 400:
            msg = f"MusicGen fallback failed ({resp.status_code}): {resp.text[:500]}"
            print(msg)
            if debug is not None:
                debug["music_error"] = msg
            return None
        content_type = resp.headers.get("content-type", "")
        if "audio" not in content_type:
            msg = f"MusicGen fallback returned unexpected content-type '{content_type}' (likely an HTML/JSON error page, not audio)."
            print(msg)
            if debug is not None:
                debug["music_error"] = msg
            return None
        with open(out_path, "wb") as f:
            f.write(resp.content)
        print(f"MusicGen fallback succeeded - background music generated via Hugging Face free tier.")
        return out_path
    except Exception as e:
        msg = f"MusicGen fallback raised an exception: {e}"
        print(f"{msg}, continuing without background music.")
        if debug is not None:
            debug["music_error"] = msg
        return None


def search_freesound_sfx(query, out_path, debug=None):
    """
    AUDIO-DEBUG FIX (2026-08-23): same rationale as generate_background_music.
    On failure, appends a short reason string to debug["sfx_errors"] (capped
    at 5 entries so a whole-episode SFX outage doesn't bloat the column)
    instead of only printing it.

    SFX QUERY SIMPLIFICATION (2026-08-24): sfx_cue text written by the
    shot-breakdown LLM is a full descriptive sentence (e.g. "Howling cold
    wind and distant creaking wooden pilings"), but Freesound's search is
    tag-based and matches short keyword-style queries far better -
    confirmed live via audio_debug on script 4fe33993 (Lighthouse Keeper),
    where all 5 SFX cues returned "No results" verbatim. Before hitting
    Freesound, the query is now trimmed to its first few significant words
    (stopwords and filler dropped) as a keyword-style fallback query if the
    full-sentence query returns nothing, instead of giving up after one
    literal-sentence search.
    """
    if not FREESOUND_API_KEY:
        if debug is not None and "sfx_errors" not in debug:
            debug.setdefault("sfx_errors", []).append("No FREESOUND_API_KEY set.")
        return None

    def _try_query(q):
        resp = requests.get(
            "https://freesound.org/apiv2/search/text/",
            params={
                "query": q,
                "token": FREESOUND_API_KEY,
                "fields": "id,previews",
                "filter": "duration:[0.1 TO 8]",
                "sort": "score",
                "page_size": 1,
            },
            timeout=30,
        )
        if resp.status_code >= 400:
            return None, f"FREESOUND ERROR {resp.status_code} for '{q}': {resp.text[:300]}"
        results = resp.json().get("results", [])
        if not results:
            return None, f"No results for cue: {q}"
        previews = results[0].get("previews", {})
        preview_url = previews.get("preview-hq-mp3") or previews.get("preview-lq-mp3")
        if not preview_url:
            return None, f"Result for '{q}' had no preview URL."
        return preview_url, None

    _STOPWORDS = {
        "a", "an", "the", "of", "in", "on", "at", "and", "or", "with",
        "distant", "background", "faint", "loud", "soft", "sudden", "slight",
        "some", "into", "from", "as", "is", "are", "being", "nearby",
    }

    def _keyword_fallback_query(q):
        words = [w.strip(".,!?;:'\"()").lower() for w in q.split()]
        meaningful = [w for w in words if w and w not in _STOPWORDS]
        return " ".join(meaningful[:3]) if meaningful else q

    try:
        preview_url, err = _try_query(query)

        if not preview_url:
            fallback_q = _keyword_fallback_query(query)
            if fallback_q and fallback_q.lower() != query.strip().lower():
                print(f"Freesound literal-sentence query failed ({err}) - retrying with "
                      f"keyword fallback query '{fallback_q}'.")
                preview_url, err2 = _try_query(fallback_q)
                if not preview_url:
                    err = f"{err} | keyword fallback '{fallback_q}' also failed: {err2}"

        if not preview_url:
            print(err)
            if debug is not None and len(debug.get("sfx_errors", [])) < 5:
                debug.setdefault("sfx_errors", []).append(err)
            return None

        download_file(preview_url, out_path)
        return out_path
    except Exception as e:
        msg = f"Freesound lookup raised an exception for cue '{query}': {e}"
        print(f"{msg}, skipping this SFX.")
        if debug is not None and len(debug.get("sfx_errors", [])) < 5:
            debug.setdefault("sfx_errors", []).append(msg)
        return None


def apply_safety_limiter(audio_clip, ceiling=LIMITER_CEILING):
    try:
        samples = audio_clip.to_soundarray(fps=44100)
    except Exception as e:
        print(f"Safety limiter: could not analyze mixed audio ({e}) - skipping peak check, using mix as-is.")
        return audio_clip
    peak = float(np.max(np.abs(samples))) if samples.size else 0.0

    if peak <= 0:
        print("Safety limiter: mixed audio is silent, nothing to scale.")
        return audio_clip
    if peak <= ceiling:
        print(f"Safety limiter: peak was {peak:.3f} (ceiling {ceiling}), no scaling needed.")
        return audio_clip

    scale = ceiling / peak
    print(f"Safety limiter: peak was {peak:.3f}, exceeds ceiling {ceiling} - scaling whole mix by {scale:.3f} to prevent clipping.")
    return audio_clip.with_volume_scaled(scale)


def extract_original_clip_audio(video_clips, shot_durations, shot_starts, total_duration):
    layers = []
    for i, clip in enumerate(video_clips):
        try:
            if clip.audio is None:
                continue
            seg_audio = clip.audio
            max_len = shot_durations[i]
            if seg_audio.duration and seg_audio.duration > max_len:
                seg_audio = seg_audio.subclipped(0, max_len)
            seg_audio = seg_audio.with_volume_scaled(ORIGINAL_CLIP_AUDIO_VOLUME).with_start(shot_starts[i])
            layers.append(seg_audio)
        except Exception as e:
            print(f"Could not extract original audio from shot {i}, skipping that layer: {e}")
    return layers


def build_audio_mix(narration_path, music_mood, shot_list, shot_durations, shot_starts, total_duration, original_clip_audio_layers=None):
    layers = [AudioFileClip(narration_path).with_volume_scaled(NARRATION_VOLUME)]
    stats = {"music_generated": False, "sfx_cues_total": 0, "sfx_applied_count": 0}
    # AUDIO-DEBUG FIX (2026-08-23): collects the real failure reasons from
    # generate_background_music/search_freesound_sfx so they can be
    # persisted to scripts.audio_debug (see mark_video_generated) and
    # queried directly from Supabase - no GitHub Actions log access needed.
    audio_debug = {}

    if original_clip_audio_layers:
        layers.extend(original_clip_audio_layers)

    if music_mood:
        music_path = "/tmp/background_music.mp3"
        if generate_background_music(music_mood, total_duration, music_path, debug=audio_debug):
            music_clip = AudioFileClip(music_path)
            music_clip = fit_audio_to_duration(music_clip, total_duration)
            music_clip = music_clip.with_volume_scaled(MUSIC_VOLUME)
            layers.append(music_clip)
            stats["music_generated"] = True
    else:
        audio_debug["music_error"] = "No music_mood set on this script - music generation never attempted."

    for i, shot in enumerate(shot_list):
        cue = (shot.get("sfx_cue") or "").strip()
        if not cue:
            continue
        stats["sfx_cues_total"] += 1
        sfx_path = f"/tmp/sfx_{i:03d}.mp3"
        if search_freesound_sfx(cue, sfx_path, debug=audio_debug):
            sfx_clip = AudioFileClip(sfx_path)
            max_len = shot_durations[i]
            if sfx_clip.duration > max_len:
                sfx_clip = sfx_clip.subclipped(0, max_len)
            sfx_clip = sfx_clip.with_volume_scaled(SFX_VOLUME).with_start(shot_starts[i])
            layers.append(sfx_clip)
            stats["sfx_applied_count"] += 1

    if audio_debug:
        stats["audio_debug"] = audio_debug

    mixed = CompositeAudioClip(layers)
    if mixed.duration and mixed.duration > total_duration:
        mixed = mixed.subclipped(0, total_duration)
    print(f"Audio mix stats: music_generated={stats['music_generated']}, "
          f"sfx_applied={stats['sfx_applied_count']}/{stats['sfx_cues_total']} cues, "
          f"original_clip_audio_layers={len(original_clip_audio_layers or [])}")
    return apply_safety_limiter(mixed), stats


def _load_caption_font(size=CAPTION_FONT_SIZE):
    for path in CAPTION_FONT_PATHS:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    print("Caption font not found at any known path - falling back to PIL's default font (captions will be smaller/plainer).")
    return ImageFont.load_default()


def _wrap_caption_text(text, font, max_width, draw):
    words = text.split()
    lines = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        bbox = draw.textbbox((0, 0), candidate, font=font)
        if bbox[2] - bbox[0] <= max_width or not current:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def render_caption_image(text, video_width=WIDTH, video_height=HEIGHT):
    text = (text or "").strip()
    if not text:
        return None

    font = _load_caption_font()
    img = Image.new("RGBA", (video_width, video_height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    max_text_width = int(video_width * CAPTION_MAX_WIDTH_RATIO)
    lines = _wrap_caption_text(text, font, max_text_width, draw)
    if not lines:
        return None

    line_heights = []
    line_widths = []
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        line_widths.append(bbox[2] - bbox[0])
        line_heights.append(bbox[3] - bbox[1])

    line_height = max(line_heights) if line_heights else CAPTION_FONT_SIZE
    block_height = len(lines) * line_height + (len(lines) - 1) * CAPTION_LINE_SPACING
    block_width = max(line_widths) if line_widths else 0

    block_bottom = video_height - CAPTION_BOTTOM_MARGIN
    block_top = block_bottom - block_height

    bg_left = (video_width - block_width) // 2 - CAPTION_BG_PADDING
    bg_right = (video_width + block_width) // 2 + CAPTION_BG_PADDING
    bg_top = block_top - CAPTION_BG_PADDING
    bg_bottom = block_bottom + CAPTION_BG_PADDING
    draw.rounded_rectangle([bg_left, bg_top, bg_right, bg_bottom], radius=14, fill=CAPTION_BG_COLOR)

    y = block_top
    for line, lw in zip(lines, line_widths):
        x = (video_width - lw) // 2
        draw.text(
            (x, y), line, font=font, fill=CAPTION_TEXT_COLOR,
            stroke_width=CAPTION_STROKE_WIDTH, stroke_fill=CAPTION_STROKE_COLOR,
        )
        y += line_height + CAPTION_LINE_SPACING

    return img


def build_caption_clip(text, start, duration, video_width=WIDTH, video_height=HEIGHT):
    try:
        img = render_caption_image(text, video_width, video_height)
        if img is None:
            return None
        frame = np.array(img)
        clip = ImageClip(frame, transparent=True, duration=duration)
        clip = clip.with_start(start)
        return clip
    except Exception as e:
        print(f"Caption render failed for text {text[:60]!r}, skipping this caption: {e}")
        return None


def build_caption_clips(shot_list, shot_durations, shot_starts, video_width=WIDTH, video_height=HEIGHT):
    caption_clips = []
    for i, shot in enumerate(shot_list):
        text = (shot.get("narration_excerpt") or "").strip()
        if not text:
            continue
        clip = build_caption_clip(text, shot_starts[i], shot_durations[i], video_width, video_height)
        if clip is not None:
            caption_clips.append(clip)
    print(f"Built {len(caption_clips)}/{len(shot_list)} caption overlays.")
    return caption_clips


def assemble_final_video(script_id, video_urls, narration_path, music_mood, shot_list, shot_durations, output_path, setting_and_characters=""):
    clips = []
    for i, url in enumerate(video_urls):
        # STORAGE MIGRATION (2026-09-02): video_urls entries are B2 object
        # keys now, not URLs - download directly via storage_b2 instead of
        # an HTTP GET on a stored URL.
        raw_path = f"/tmp/final_shot_{i:03d}.mp4"
        storage_b2.download_to_file(url, raw_path)

        if i == len(video_urls) - 1:
            clip = VideoFileClip(raw_path)
            clip = clip.resized(new_size=(WIDTH, HEIGHT))
            if clip.duration < shot_durations[i]:
                try:
                    local_frame_path = _extract_last_frame_local(raw_path)
                    chain_anchor_url = _upload_local_image_for_anchor(
                        script_id, f"trail_{os.path.basename(raw_path)}", local_frame_path
                    )
                    trail_out_path = raw_path.replace(".mp4", "_trail.mp4")
                    remaining = shot_durations[i] - clip.duration
                    _generate_one_segment(
                        shot_list[i], min(remaining, MAX_CLIP_SECONDS), trail_out_path,
                        setting_and_characters, anchor_image_url=chain_anchor_url,
                    )
                    trail_clip = VideoFileClip(trail_out_path).resized(new_size=(WIDTH, HEIGHT))
                    combined = concatenate_videoclips([clip, trail_clip], method="compose")
                    if combined.duration < shot_durations[i]:
                        combined = fit_clip_to_duration(combined, shot_durations[i])
                    clip = combined
                except Exception as e:
                    print(f"Trail chain-extension failed ({e}) - falling back to freeze-hold for the outro: {e}")
                    clip = fit_clip_to_duration(clip, shot_durations[i])
        else:
            clip = VideoFileClip(raw_path)
            clip = clip.resized(new_size=(WIDTH, HEIGHT))
            clip = fit_clip_to_duration(clip, shot_durations[i])

        clips.append(clip)

    total_duration = sum(shot_durations)
    shot_starts = compute_shot_start_times(shot_durations)

    original_clip_audio_layers = extract_original_clip_audio(clips, shot_durations, shot_starts, total_duration)

    final_audio, audio_stats = build_audio_mix(
        narration_path, music_mood, shot_list, shot_durations, shot_starts, total_duration,
        original_clip_audio_layers=original_clip_audio_layers,
    )

    final_audio = final_audio.with_effects(
        [AudioFadeIn(FADE_IN_SECONDS), AudioFadeOut(FADE_OUT_SECONDS)]
    )

    final = concatenate_videoclips(clips, method="compose")

    final = final.with_effects([FadeIn(FADE_IN_SECONDS), FadeOut(FADE_OUT_SECONDS)])
    final = final.with_audio(final_audio)
    # CHUNKED-UPLOAD QUALITY FIX (2026-08-20): bitrate is now fixed/quality-
    # driven (see compute_target_bitrate above) - duration no longer
    # affects it, so the encode below is always done at full quality.
    target_bitrate = compute_target_bitrate()
    print(f"Target video bitrate: {target_bitrate} (fixed, quality-driven - duration was {total_duration:.1f}s)")
    final.write_videofile(
        output_path,
        fps=FRAME_RATE,
        codec="libx265",
        audio_codec="aac",
        audio_bitrate="128k",
        bitrate=target_bitrate,
        threads=2,
        logger=None,
        # FIX 1 (2026-09-06): grade->blur->grain filter added here, after
        # everything else in the pipeline - see SKIN_REALISM_VF comment
        # above for why order matters and why no sharpening is added.
        ffmpeg_params=["-preset", "fast", "-tag:v", "hvc1", "-vf", SKIN_REALISM_VF],
    )
    return output_path, audio_stats


def upload_video(script_id, file_path):
    """Returns the B2 object KEY (not a URL) - stored in scripts.video_url.

    STORAGE MIGRATION (2026-09-02): replaces upload_video_chunked as the
    single upload path for the final assembled video. No chunking - B2
    has no practically-relevant size ceiling for anything this pipeline
    produces, so the entire chunk-split/re-stitch system is gone. Final
    videos always upload as one object.
    """
    file_name = f"{script_id}.mp4"
    file_size_mb = os.path.getsize(file_path) / (1024 * 1024)
    print(f"Final video size: {file_size_mb:.1f}MB - uploading to B2 as a single object.")
    return storage_b2.upload_file(file_name, file_path, content_type="video/mp4")
