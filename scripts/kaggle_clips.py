"""
Marius Command Center - Kaggle clip generation (2026-11-10, rev 2).

Replaces Agnes / stock footage with real AI-generated clips made on Kaggle's free GPU.
Runs in GitHub Actions every 30 minutes (workflow: kaggle_clips.yml). Each run does ONE of:
  - kernel running/queued on Kaggle  -> nothing (wait for the next run)
  - kernel finished                  -> download the clips, scale them to 1280x704, upload to B2,
                                        save progress to Supabase (video_urls / video_next_index)
  - no kernel yet / nothing running  -> push the next batch of shots of the most-advanced script
When every shot of a script is saved, the existing assembly in video_generation.process_script
(narration + SFX + music mix + upload prep) runs with shot_limit=0, so no clip is ever asked
of Agnes or stock footage.

REV 2 FIXES (after run #1 failed in 32 s):
  - Kaggle answers "Cannot access kernel ... Permission 'kernels.get' was denied" for a notebook
    that does not exist yet. That is now read as "no notebook yet" and the first batch is pushed.
    If the status still cannot be read after our own push, the run reports it and waits 6 h
    instead of pushing again every 30 minutes.
  - The Agnes prompt is a 2,500+ character wall of guard text and the model reads only the first
    ~256 tokens, so the shot's own description would have been cut off. This file now builds a
    short prompt with the shot description FIRST.

REV 2.1 (2026-11-11): when scale_clip fails, ffmpeg's own error text and an ffprobe of the
downloaded clip are now saved into scripts.last_error (they were thrown away before).

REV 2.2 (2026-11-11): the run log showed "ffmpeg: not found" on the GitHub runner, which is why
no clip was ever saved. ensure_ffmpeg() now installs ffmpeg at the start of every run if missing.

REV 2.3 (2026-11-11): (a) a script that has all its clips but failed assembly in the last 6 h is
skipped instead of being retried (and re-failing the whole run) every 30 minutes; (b) pushing a
batch to Kaggle now counts as progress, so a healthy run no longer exits red and opens a failure issue.

REV 2.4 (2026-11-11): the September backlog scripts (for example cb18b7c2 and 17fc73b3) have a
narration_url whose mp3 file no longer exists in Supabase storage (the download answers 400), so
their clips could never be assembled and Kaggle GPU hours were being spent on them. get_candidates()
now checks that the narration file really downloads (HTTP 200) and only keeps scripts that pass.

REV 2.5 (2026-11-11): a notebook run that a person cancelled on Kaggle is now its own state
("cancelled"): the runner sends a fresh batch straight away instead of treating the missing output
as a crash and waiting 6 hours.

State lives in Kaggle's kernel (slug marius-clips) and in Supabase scripts.video_urls, so every
run is safe to repeat. Needs env: SUPABASE_URL, SUPABASE_SECRET_KEY, B2_*, GEMINI_API_KEY,
KAGGLE_USERNAME (required, no fallback) and KAGGLE_API_TOKEN or KAGGLE_KEY.
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
from prompt_builder import LIGHTING_PROMPT_MAP, DEFAULT_LIGHTING_KEY
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
UNREADABLE_MARK = "KAGGLE_STATUS_UNREADABLE"
CANDIDATE_SCAN = 80   # scripts looked at before the narration check
CANDIDATE_KEEP = 10   # scripts kept after the narration check

SUMMARY = []
FAULTS = []
PROGRESS = {"shots": 0, "pushed": 0}
LAST_FFMPEG = {"text": ""}


def say(text):
    print(text)
    SUMMARY.append(str(text))


def sh(cmd):
    p = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    out = (p.stdout or "") + (p.stderr or "")
    print(f"$ {cmd}\n{out.strip()[-3000:]}\n")
    return p.returncode, out


def ensure_ffmpeg():
    """The GitHub runner image no longer ships ffmpeg (run log: 'ffmpeg: not found'). Install it."""
    if shutil.which("ffmpeg"):
        return True
    say("ffmpeg is missing on this runner; installing it.")
    sh("sudo apt-get update -qq && sudo apt-get install -y -qq ffmpeg")
    if shutil.which("ffmpeg"):
        say("ffmpeg installed.")
        return True
    # fallback: the static ffmpeg that ships inside the imageio-ffmpeg pip package
    sh("pip install -q imageio-ffmpeg")
    try:
        import imageio_ffmpeg
        exe = imageio_ffmpeg.get_ffmpeg_exe()
        sh(f'sudo ln -sf "{exe}" /usr/local/bin/ffmpeg')
    except Exception as e:
        print(f"imageio-ffmpeg fallback failed: {e}")
    ok = bool(shutil.which("ffmpeg"))
    say("ffmpeg installed (fallback)." if ok else "ffmpeg could NOT be installed.")
    return ok


def kaggle_user():
    user = os.environ.get("KAGGLE_USERNAME", "").strip()
    if not user:
        raise RuntimeError("KAGGLE_USERNAME is missing. Add it as a repository secret.")
    return user


def parse_shot_list(script):
    sl = script.get("shot_list")
    if isinstance(sl, str):
        sl = json.loads(sl)
    return sl or []


def narration_ok(url):
    """True only if the narration file really downloads (HTTP 200). Old September scripts point to
    mp3 files that were deleted from storage (download answers 400), so they can never be assembled."""
    if not url:
        return False
    try:
        r = requests.get(url, stream=True, timeout=20)
        ok = r.status_code == 200
        r.close()
        return ok
    except Exception:
        return False


def get_candidates():
    resp = retryable_request(
        "GET",
        f"{SUPABASE_URL}/rest/v1/scripts?status=eq.images_generated&narration_url=not.is.null"
        f"&order=video_next_index.desc.nullslast,created_at.asc&limit={CANDIDATE_SCAN}",
        headers=HEADERS,
        timeout=30,
    )
    good = []
    dead = 0
    for s in resp.json():
        if narration_ok(s.get("narration_url")):
            good.append(s)
        else:
            dead += 1
    if dead:
        say(f"Skipped {dead} script(s) whose narration file no longer exists (cannot be assembled).")
    return good[:CANDIDATE_KEEP]


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


def short_anchor(text, limit=300):
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    cut = text[:limit]
    i = max(cut.rfind(". "), cut.rfind("; "))
    return cut[:i + 1] if i > 100 else cut


def ltx_prompt(shot, anchor, extra=""):
    """Short prompt for LTX (reads ~256 tokens): the shot description comes FIRST."""
    visual = (shot.get("visual_description") or "").strip()
    shot_type = (shot.get("shot_type") or "medium").replace("_", " ")
    cam = (shot.get("camera_movement") or "static").replace("_", " ")
    key = shot.get("lighting") or DEFAULT_LIGHTING_KEY
    lighting = LIGHTING_PROMPT_MAP.get(key, LIGHTING_PROMPT_MAP[DEFAULT_LIGHTING_KEY])
    parts = [f"{shot_type} shot. {visual}"]
    if extra:
        parts.append(extra[:200])
    a = short_anchor(anchor)
    if a:
        parts.append(a)
    parts.append(lighting)
    parts.append("photorealistic cinematic documentary footage, natural skin texture, "
                 "historically accurate, no modern objects")
    if cam != "static":
        parts.append(f"camera {cam}")
    parts.append("smooth continuous motion")
    text = ". ".join(p.strip().rstrip(".") for p in parts if p and p.strip())
    return text[:1100]


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
        base = ltx_prompt(shot, focused, extra)
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
                        p = ltx_prompt(apply_beat_to_shot(shot, beats[k]), focused, extra)
                    except Exception:
                        p = base
                prompts.append(p)
        seed = int(hashlib.md5(f"{script_id}:{i}".encode()).hexdigest()[:8], 16)
        jobs.append({"index": i, "duration": round(dur, 3), "prompts": prompts, "seed": seed})
    return {"script_id": script_id, "start_index": start, "budget_minutes": BUDGET_MIN, "jobs": jobs}


def kernel_status(ref):
    code, out = sh(f"kaggle kernels status {ref}")
    low = out.lower()
    # Kaggle says "Cannot access kernel ... Permission 'kernels.get' was denied" for a notebook
    # that does not exist yet (confirmed in run #1), so that text means "no notebook yet".
    if ("cannot access kernel" in low or "permission 'kernels.get'" in low
            or "404" in low or "not found" in low or "notfound" in low or "could not find" in low):
        return "none"
    if "complete" in low:
        return "complete"
    if "running" in low:
        return "running"
    if "queued" in low or "queue" in low:
        return "queued"
    if "cancel" in low:
        return "cancelled"
    if "error" in low or "failed" in low:
        return "error"
    if "has status" in low:
        return "running"  # a status word we do not know: be safe and wait
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
        FAULTS.append(f"Kaggle refused the push for script {script_id}: {out[-400:]}")
        return False
    PROGRESS["pushed"] += 1
    say(f"Pushed a Kaggle batch for script {script_id}: shots {start + 1} to {start + len(manifest['jobs'])}.")
    time.sleep(8)
    after = kernel_status(f"{user}/{SLUG}")
    say(f"Kaggle notebook status right after the push: {after}.")
    if after in ("none", "unknown"):
        record_error(script_id, f"{UNREADABLE_MARK}: pushed a batch but cannot read the notebook status "
                                f"afterwards (the Kaggle token may lack permission to read notebooks).")
        FAULTS.append("Pushed to Kaggle but cannot read the notebook status afterwards. "
                      "No more pushes for 6 hours; check the Kaggle token permissions.")
    return True


def scale_clip(src, dst):
    vf = f"scale=w={OUT_W}:h=-2:flags=lanczos,crop={OUT_W}:{OUT_H},fps=24,format=yuv420p"
    code, out = sh(f'ffmpeg -y -v error -i "{src}" -vf "{vf}" -an -c:v libx264 -crf 20 -preset veryfast "{dst}"')
    ok = code == 0 and os.path.exists(dst)
    if not ok:
        size = os.path.getsize(src) if os.path.exists(src) else -1
        _, probe = sh(f'ffprobe -v error -show_entries stream=codec_name,width,height,nb_frames '
                      f'-of default=nw=1 "{src}"')
        LAST_FFMPEG["text"] = (f"exit={code}; src_bytes={size}; ffmpeg said: {out.strip()[-700:]} "
                               f"| ffprobe said: {probe.strip()[-300:]}")
    return ok


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
            return saved, f"ffmpeg could not scale shot {idx + 1}: {LAST_FFMPEG['text']}"
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
            after = fetch_script(script_id) or {}
            if after.get("status") == "video_generated":
                say(f"Script {script_id} is assembled (status video_generated). YouTube Upload picks it up next.")
            else:
                last = (after.get("last_error") or "")[-600:]
                FAULTS.append(f"Script {script_id} was not assembled. Last error: {last or 'none recorded'}")
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
    if not ensure_ffmpeg():
        FAULTS.append("ffmpeg is not available and could not be installed; clips cannot be resized.")
        return
    try:
        candidates = get_candidates()
    except Exception as e:
        say(f"Supabase did not answer ({e}); nothing done, next run retries.")
        return
    if not candidates:
        say("No script is ready for video (needs status images_generated and a narration file that downloads).")
        return

    # 1) scripts whose clips are all saved just need assembling (skipped for 6 h after a failed assembly)
    for s in candidates:
        total = len(parse_shot_list(s))
        if total and (s.get("video_next_index") or 0) >= total:
            if recently_errored(s):
                say(f"Script {s['id']} has all its clips but failed assembly in the last "
                    f"{RETRY_COOLDOWN_HOURS} h; skipping it for now (error is saved on the script).")
                continue
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
        FAULTS.append("Could not read the Kaggle notebook status (unexpected answer, see the log). Nothing pushed.")
        return
    if state == "cancelled":
        say("The last Kaggle run was cancelled; sending a fresh batch.")
    if (state == "none" and (target.get("last_error") or "").startswith(UNREADABLE_MARK)
            and recently_errored(target)):
        say(f"A batch was pushed earlier but its status cannot be read; waiting up to {RETRY_COOLDOWN_HOURS} h "
            f"instead of pushing again.")
        return

    failed_collect = False
    if state in ("complete", "error"):
        saved, why = collect(target, ref)
        if saved:
            target = fetch_script(target["id"]) or target
        elif why != "stale":
            failed_collect = True
            record_error(target["id"], f"Kaggle batch gave no clips: {why}")
            FAULTS.append(f"Kaggle batch for script {target['id']} produced no clips: {why[:1000]}")

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
    if FAULTS and PROGRESS["shots"] == 0 and PROGRESS["pushed"] == 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
