"""
Marius Command Center - Kaggle clip generation (2026-11-10).

Replaces Agnes / stock footage with real AI-generated clips made on Kaggle's free GPU.
Runs in GitHub Actions every 30 minutes (workflow: kaggle_video.yml). Each run does ONE of:
  - kernel running/queued on Kaggle  -> nothing (wait for the next run)
  - kernel finished                  -> download the clips, scale them to 1280x704, upload to B2,
                                        save progress to Supabase (video_urls / video_next_index)
  - nothing running                  -> push the next batch of shots of the most-advanced script
When every shot of a script is saved, the existing assembly in video_generation.process_script
(narration + SFX + music mix + upload prep) runs with shot_limit=0, so no clip is ever asked
of Agnes or stock footage.

State lives in Kaggle's kernel (slug marius-clips) and in Supabase scripts.video_urls, so every
run is safe to repeat. Needs env: SUPABASE_URL, SUPABASE_SECRET_KEY, B2_*, GEMINI_API_KEY,
KAGGLE_USERNAME (falls back to Diawazi) and KAGGLE_API_TOKEN or KAGGLE_KEY.
"""
import os
import sys
import json
import time
import math
import shutil
import base64
import calendar
import hashlib
import subprocess
import traceback

import requests

import storage_b2
from llm_client import retryable_request, SUPABASE_URL, HEADERS
from prompt_builder import build_agnes_prompt
from prompt_focus import focus_anchor, no_people_clause
from beat_director import author_chain_beats, apply_beat_to_shot

HERE = os.path.dirname(os.path.abspath(__file__))
KERNEL_SRC = os.path.join(HERE, "kaggle_clips_kernel.py")
SLUG = "marius-clips"
WORK = "/tmp/kaggle_clips_push"
OUT_DIR = "/tmp/kaggle_clips_out"

BATCH_SHOTS = int(os.environ.get("KAGGLE_BATCH_SHOTS", "30"))
BUDGET_MIN = int(os.environ.get("KAGGLE_BUDGET_MINUTES", "420"))
SEG_SECONDS = 4.0
MAX_SEGMENTS = 7
RETRY_COOLDOWN_HOURS = 6
OUT_W, OUT_H = 1280, 704

SUMMARY = []
FAULTS = []
PROGRESS = {"shots": 0}


def say(text):
    print(text)
    SUMMARY.append(str(text))


def sh(cmd):
    p = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    out = (p.stdout or "") + (p.stderr or "")
    print(f"$ {cmd}\n{out.strip()[-3000:]}\n")
    return p.returncode, out


def kaggle_user():
    return os.environ.get("KAGGLE_USERNAME", "").strip() or "Diawazi"


def parse_shot_list(script):
    sl = script.get("shot_list")
    if isinstance(sl, str):
        sl = json.loads(sl)
    return sl or []


def get_candidates():
    resp = retryable_request(
        "GET",
        f"{SUPABASE_URL}/rest/v1/scripts?status=eq.images_generated&narration_url=not.is.null"
        f"&order=video_next_index.desc.nullslast,created_at.asc&limit=10",
        headers=HEADERS,
        timeout=30,
    )
    return resp.json()


def fetch_script(script_id):
    resp = retryable_request(
        "GET",
        f"{SUPABASE_URL}/rest/v1/scripts?id=eq.{script_id}&limit=1",
        headers=HEADERS,
        timeout=30,
    )
    rows = resp.json()
    return rows[0] if rows else None


def record_error(script_id, text):
    try:
        retryable_request(
            "PATCH",
            f"{SUPABASE_URL}/rest/v1/scripts?id=eq.{script_id}",
            headers=HEADERS,
            json={"last_error": str(text)[-8000:],
                  "last_error_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())},
            timeout=30,
        )
    except Exception as e:
        print(f"Could not record last_error (non-fatal): {e}")


def save_progress(script_id, video_urls, next_index):
    retryable_request(
        "PATCH",
        f"{SUPABASE_URL}/rest/v1/scripts?id=eq.{script_id}",
        headers=HEADERS,
        json={"video_urls": video_urls, "video_next_index": next_index},
        timeout=30,
    )


def recently_errored(script):
    ts = script.get("last_error_at")
    if not ts:
        return False
    try:
        t = calendar.timegm(time.strptime(ts[:19], "%Y-%m-%dT%H:%M:%S"))
    except Exception:
        return False
    return (time.time() - t) < RETRY_COOLDOWN_HOURS * 3600


def get_durations(script, shot_list):
    stored = script.get("shot_durations")
    if (isinstance(stored, list) and len(stored) == len(shot_list)
            and all(isinstance(d, (int, float)) and d >= 0 for d in stored)):
        return [float(d) for d in stored]
    from moviepy import AudioFileClip
    ext = ".mp3" if script["narration_url"].endswith(".mp3") else ".wav"
    path = "/tmp/kc_narration" + ext
    r = requests.get(script["narration_url"], timeout=120)
    r.raise_for_status()
    with open(path, "wb") as f:
        f.write(r.content)
    total = AudioFileClip(path).duration
    weights = [max(len(s.get("narration_excerpt", "")), 20) for s in shot_list]
    tw = sum(weights)
    return [w / tw * total for w in weights]


def build_manifest(script, start):
    script_id = script["id"]
    shot_list = parse_shot_list(script)
    total = len(shot_list)
    durations = get_durations(script, shot_list)
    sac = script.get("setting_and_characters", "") or ""
    jobs = []
    for i in range(start, min(start + BATCH_SHOTS, total)):
        shot = shot_list[i]
        dur = max(float(durations[i]), 1.0)
        if i == total - 1:
            dur += 3.0  # the assembly adds a 3 s trail after the last shot
        segs = min(MAX_SEGMENTS, max(1, math.ceil(dur / SEG_SECONDS)))
        focused = focus_anchor(shot, sac)
        extra = no_people_clause(shot, sac)
        base = build_agnes_prompt(shot, focused, fallback_level=0)
        if extra:
            base = f"{base}, {extra}"
        prompts = [base]
        if segs > 1:
            beats = None
            try:
                beats = author_chain_beats(shot, sac, segs - 1)
            except Exception as e:
                print(f"beat_director failed for shot {i} (non-fatal, repeating the prompt): {e}")
            for k in range(segs - 1):
                p = base
                if beats and k < len(beats):
                    try:
                        cs = apply_beat_to_shot(shot, beats[k])
                        p = build_agnes_prompt(cs, focused, fallback_level=0)
                        if extra:
                            p = f"{p}, {extra}"
                    except Exception:
                        p = base
                prompts.append(p)
        prompts = [p[:1500] for p in prompts]
        seed = int(hashlib.md5(f"{script_id}:{i}".encode()).hexdigest()[:8], 16)
        jobs.append({"index": i, "duration": round(dur, 3), "prompts": prompts, "seed": seed})
    return {"script_id": script_id, "start_index": start, "budget_minutes": BUDGET_MIN, "jobs": jobs}


def kernel_status(ref):
    code, out = sh(f"kaggle kernels status {ref}")
    low = out.lower()
    if "complete" in low:
        return "complete"
    if "running" in low:
        return "running"
    if "queued" in low or "queue" in low:
        return "queued"
    if "error" in low or "cancel" in low or "failed" in low:
        if "404" in low or "not found" in low or "notfound" in low:
            return "none"
        return "error"
    if "404" in low or "not found" in low or "notfound" in low or "could not find" in low:
        return "none"
    return "unknown"


def push_batch(script, start):
    script_id = script["id"]
    manifest = build_manifest(script, start)
    if not manifest["jobs"]:
        say(f"Nothing to push for script {script_id} (no shots left).")
        return False
    b64 = base64.b64encode(json.dumps(manifest).encode("utf-8")).decode("ascii")
    src = open(KERNEL_SRC, encoding="utf-8").read()
    if "__MANIFEST_B64__" not in src:
        raise RuntimeError("kernel source has no __MANIFEST_B64__ placeholder")
    shutil.rmtree(WORK, ignore_errors=True)
    os.makedirs(WORK)
    with open(os.path.join(WORK, "kernel.py"), "w", encoding="utf-8") as f:
        f.write(src.replace("__MANIFEST_B64__", b64))
    user = kaggle_user()
    meta = {
        "id": f"{user}/{SLUG}",
        "title": SLUG,
        "code_file": "kernel.py",
        "language": "python",
        "kernel_type": "script",
        "is_private": "true",
        "enable_gpu": "true",
        "enable_internet": "true",
        "dataset_sources": [],
        "competition_sources": [],
        "kernel_sources": [],
    }
    with open(os.path.join(WORK, "kernel-metadata.json"), "w") as f:
        json.dump(meta, f, indent=2)
    code, out = sh(f"kaggle kernels push -p {WORK}")
    if code != 0 or "error" in out.lower():
        record_error(script_id, "Kaggle refused the push: " + out[-1500:])
        FAULTS.append(f"Kaggle refused the push for script {script_id}: {out[-300:]}")
        return False
    say(f"Pushed a Kaggle batch for script {script_id}: shots {start + 1} to {start + len(manifest['jobs'])}.")
    return True


def scale_clip(src, dst):
    vf = f"scale=w={OUT_W}:h=-2:flags=lanczos,crop={OUT_W}:{OUT_H},fps=24,format=yuv420p"
    code, out = sh(f'ffmpeg -y -v error -i "{src}" -vf "{vf}" -an -c:v libx264 -crf 20 -preset veryfast "{dst}"')
    return code == 0 and os.path.exists(dst)


def collect(script, ref):
    """Returns (saved_count, reason). reason is 'stale' when the kernel output belongs to an older batch."""
    script_id = script["id"]
    shutil.rmtree(OUT_DIR, ignore_errors=True)
    os.makedirs(OUT_DIR)
    sh(f"kaggle kernels output {ref} -p {OUT_DIR}")
    mpath = os.path.join(OUT_DIR, "manifest_out.json")
    if not os.path.exists(mpath):
        return 0, "Kaggle output had no manifest_out.json (the notebook probably crashed before it started)"
    m = json.load(open(mpath))
    next_index = script.get("video_next_index") or 0
    if m.get("script_id") != script_id or m.get("start_index") != next_index:
        return 0, "stale"
    video_urls = list(script.get("video_urls") or [])
    saved = 0
    for idx in sorted(m.get("done", [])):
        if idx != next_index:
            break
        src = os.path.join(OUT_DIR, f"shot_{idx:03d}.mp4")
        if not os.path.exists(src):
            break
        fixed = f"/tmp/kc_fixed_{idx:03d}.mp4"
        if not scale_clip(src, fixed):
            return saved, f"ffmpeg could not scale shot {idx + 1}"
        key = storage_b2.upload_file(f"{script_id}/shot_{idx:03d}.mp4", fixed, content_type="video/mp4")
        os.remove(fixed)
        video_urls.append(key)
        next_index += 1
        save_progress(script_id, video_urls, next_index)
        saved += 1
        PROGRESS["shots"] += 1
    why = "; ".join(str(e) for e in (m.get("errors") or [])[:2]) or str(m.get("stopped_because"))
    say(f"Saved {saved} Kaggle clip(s) for script {script_id}. Kaggle said: {m.get('stopped_because')}")
    return saved, why


def assemble_if_complete(script_id):
    script = fetch_script(script_id)
    if not script:
        return
    total = len(parse_shot_list(script))
    if total and (script.get("video_next_index") or 0) >= total:
        say(f"All {total} shots of script {script_id} are saved - assembling the final video.")
        try:
            import video_generation
            video_generation.process_script(script, shot_limit=0)
        except Exception as e:
            record_error(script_id, traceback.format_exc())
            FAULTS.append(f"Assembly failed for script {script_id}: {type(e).__name__}: {e}")


def write_summary():
    lines = ["## Marius - Kaggle Video Generation run report", ""]
    lines += [f"- {s}" for s in SUMMARY] or ["- Nothing to do this run."]
    if FAULTS:
        lines += ["", "### FAULTS (need attention)"] + [f"- {f}" for f in FAULTS]
    report = "\n".join(lines)
    print("\n" + report)
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        try:
            with open(path, "a") as f:
                f.write(report + "\n")
        except Exception as e:
            print(f"Could not write run summary (non-fatal): {e}")


def run():
    user = kaggle_user()
    ref = f"{user}/{SLUG}"
    try:
        candidates = get_candidates()
    except Exception as e:
        say(f"Supabase did not answer ({e}); nothing done, next run retries.")
        return
    if not candidates:
        say("No script is ready for video (needs status images_generated and a narration).")
        return

    # 1) scripts whose clips are all saved just need assembling
    for s in candidates:
        total = len(parse_shot_list(s))
        if total and (s.get("video_next_index") or 0) >= total:
            assemble_if_complete(s["id"])

    target = None
    for s in candidates:
        total = len(parse_shot_list(s))
        if total and (s.get("video_next_index") or 0) < total:
            target = s
            break
    if target is None:
        say("No script has shots left to generate.")
        return

    state = kernel_status(ref)
    say(f"Kaggle notebook {ref} status: {state}.")
    if state in ("running", "queued"):
        say("Kaggle is still working; the next run will collect the clips.")
        return
    if state == "unknown":
        FAULTS.append("Could not read the Kaggle notebook status (login problem?). Nothing pushed.")
        return

    failed_collect = False
    if state in ("complete", "error"):
        saved, why = collect(target, ref)
        if saved:
            target = fetch_script(target["id"]) or target
        elif why != "stale":
            failed_collect = True
            record_error(target["id"], f"Kaggle batch gave no clips: {why}")
            FAULTS.append(f"Kaggle batch for script {target['id']} produced no clips: {why[:400]}")

    target = fetch_script(target["id"]) or target
    total = len(parse_shot_list(target))
    nxt = target.get("video_next_index") or 0
    if nxt >= total:
        assemble_if_complete(target["id"])
        return
    if failed_collect and recently_errored(target):
        say(f"Last Kaggle batch failed; waiting up to {RETRY_COOLDOWN_HOURS} h before pushing again.")
        return
    push_batch(target, nxt)


def main():
    try:
        run()
    except Exception as e:
        FAULTS.append(f"Unexpected crash: {type(e).__name__}: {e}")
        traceback.print_exc()
    finally:
        write_summary()
    if FAULTS and PROGRESS["shots"] == 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
