"""
Marius Command Center - clip QA (2026-10-09).

Zia's requirement: there must be a way to check whether the video
generator produced morphing / face-swapping / waxy faces, and redo the
shot if it did. After a clip is generated, 4 frames are pulled evenly
across it and sent to Gemini (vision) with one narrow question set:
did a person's face turn into a different person, did bodies/faces merge or
duplicate, does skin look waxy/plastic. A failed verdict makes the caller
regenerate that segment with a different seed (bounded - see
CLIP_QA_MAX_REDO, default 1, since every redo spends Agnes credits).

Design rules:
- Only clips whose shot actually contains people are checked (objects and
  places cannot swap faces) - saves Gemini calls and keeps the quota for
  the shots that matter.
- FAILS OPEN on every infrastructure problem (no key, quota, timeout,
  unparseable answer): the clip is accepted, a line is logged, and after a
  quota error QA switches itself off for the rest of the run. A broken
  checker must never block an episode.
- Set CLIP_QA_ENABLED=0 to turn it off without a code change.
"""

import os
import io
import json
import base64
import requests
from PIL import Image
from moviepy import VideoFileClip

from prompt_focus import visual_has_people, protagonist_name

GEMINI_MODEL = "gemini-3.5-flash-lite"  # same model llm_client.py already uses
FRAME_FRACTIONS = (0.05, 0.35, 0.65, 0.95)
FRAME_MAX_WIDTH = 448
REQUEST_TIMEOUT = 60

_calls_this_run = 0
_disabled_for_run = False


def enabled():
    return os.environ.get("CLIP_QA_ENABLED", "1").strip() != "0" and bool(os.environ.get("GEMINI_API_KEY"))


def max_redo():
    try:
        return max(int(os.environ.get("CLIP_QA_MAX_REDO", "1")), 0) if enabled() else 0
    except ValueError:
        return 1


def _max_calls():
    try:
        return int(os.environ.get("CLIP_QA_MAX_CALLS_PER_RUN", "120"))
    except ValueError:
        return 120


def shot_needs_check(shot, anchor=""):
    if visual_has_people(shot.get("visual_description") or "") or (shot.get("primary_subject") or "").strip():
        return True
    name = protagonist_name(anchor or "")
    return bool(name) and name.lower() in (shot.get("visual_description") or "").lower()


def _extract_frames_b64(video_path):
    frames = []
    clip = VideoFileClip(video_path)
    try:
        duration = max(clip.duration or 0, 0.1)
        for frac in FRAME_FRACTIONS:
            frame = clip.get_frame(min(duration * frac, max(duration - 0.05, 0)))
            img = Image.fromarray(frame).convert("RGB")
            if img.width > FRAME_MAX_WIDTH:
                ratio = FRAME_MAX_WIDTH / img.width
                img = img.resize((FRAME_MAX_WIDTH, int(img.height * ratio)))
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=70)
            frames.append(base64.b64encode(buf.getvalue()).decode())
    finally:
        clip.close()
    return frames


QA_PROMPT = (
    "These are 4 frames, in time order, from ONE short AI-generated video clip of a "
    "documentary scene. Judge ONLY these visual defects and answer with JSON:\n"
    '{"identity_change": bool, "deformation": bool, "waxy_skin": bool, "reason": "one short sentence"}\n'
    "identity_change = true if any person's face or body turns into a DIFFERENT person "
    "between frames, or two people swap faces, or a person is replaced by someone who looks different.\n"
    "deformation = true if faces, limbs or bodies melt, merge together, duplicate, grow extra "
    "limbs/fingers, or hands/faces are badly distorted.\n"
    "waxy_skin = true if skin looks like plastic, wax or an airbrushed doll rather than real skin.\n"
    "If no person is clearly visible, answer false for all three. Be strict but do not invent problems."
)


def check_clip(video_path, shot, anchor=""):
    """Returns {"ok": bool, "checked": bool, "reason": str}. Never raises."""
    global _calls_this_run, _disabled_for_run
    result = {"ok": True, "checked": False, "reason": ""}
    try:
        if _disabled_for_run or not enabled() or not shot_needs_check(shot, anchor):
            return result
        if _calls_this_run >= _max_calls():
            return result
        frames = _extract_frames_b64(video_path)
        parts = [{"text": QA_PROMPT}] + [
            {"inline_data": {"mime_type": "image/jpeg", "data": f}} for f in frames
        ]
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"
            f"?key={os.environ['GEMINI_API_KEY']}"
        )
        _calls_this_run += 1
        resp = requests.post(
            url,
            json={
                "contents": [{"parts": parts}],
                "generationConfig": {"temperature": 0, "maxOutputTokens": 300, "responseMimeType": "application/json"},
            },
            timeout=REQUEST_TIMEOUT,
        )
        if resp.status_code == 429:
            _disabled_for_run = True
            print("[clip_qa] Gemini quota hit - clip QA switched OFF for the rest of this run (failing open).")
            return result
        if resp.status_code >= 400:
            print(f"[clip_qa] Gemini error {resp.status_code} - accepting clip unchecked: {resp.text[:200]}")
            return result
        text = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
        verdict = json.loads(text.strip().strip("`").replace("json\n", "", 1))
        result["checked"] = True
        problems = [k for k in ("identity_change", "deformation", "waxy_skin") if verdict.get(k) is True]
        result["reason"] = f"{', '.join(problems) or 'clean'}: {str(verdict.get('reason', ''))[:160]}"
        result["ok"] = not problems
        print(f"[clip_qa] {'PASS' if result['ok'] else 'FAIL'} - {result['reason']}")
        return result
    except Exception as e:
        print(f"[clip_qa] check failed ({e}) - accepting clip unchecked (failing open).")
        return {"ok": True, "checked": False, "reason": f"error: {e}"}
