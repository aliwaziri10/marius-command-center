"""
Marius Command Center - free stock-footage fallback (2026-10-18).

WHY: Agnes has returned 503 video_queue_full since about 2026-10-10, which
stalls every video. When Agnes cannot take a shot, this module fetches a real
stock video clip from Pixabay (free API key) that matches the shot, fits it to
the exact duration the shot needs, and writes it to the same out_path the
Agnes clip would have used. The rest of the pipeline (upload, assembly,
narration timing, SFX) does not know or care where the clip came from.

FAIL-SOFT: if PIXABAY_API_KEY is missing, or anything here fails, every public
function returns False / does nothing and the pipeline behaves exactly as it
did before this file existed.

Stock footage is a backup, not an equal: it will not match each shot as
precisely as an AI clip.

Pixabay API: https://pixabay.com/api/docs/  (about 100 requests per 60 s).
"""

import os
import re
import time
import hashlib
import shutil
import subprocess
import requests

PIXABAY_VIDEO_API = "https://pixabay.com/api/videos/"
OUT_W, OUT_H, OUT_FPS = 1920, 1080, 24
MAX_CLIPS_PER_SHOT = 10
MIN_USEFUL_CLIP_SECONDS = 3

# Used only when a shot's own words find nothing. Picked to suit a
# real-history documentary look (Erased). Override with STOCK_GENERIC_QUERIES
# (comma separated) in the workflow env if a channel needs a different feel.
DEFAULT_GENERIC_QUERIES = [
    "old city street", "ancient ruins", "historic building", "stone wall",
    "forest mist", "dark clouds", "candle flame", "old book pages",
    "sea waves", "desert dunes", "mountain valley", "river flowing",
]

STOPWORDS = set("""
a an the and or of in on at to for with from by as is are was were be been being
this that these those it its into over under through across while during
his her their they them he she we you i our your my not no but if then than
very more most some any each every one two three four five several
shot camera close up wide medium low high angle view scene frame showing shows
visible person people man men woman women figure figures
""".split())

_used_ids = set()
_stock_scripts = set()


class StockOnlyError(Exception):
    """Raised when a video that is already in stock mode cannot get a stock clip."""


def is_enabled():
    return bool(os.environ.get("PIXABAY_API_KEY", "").strip())


def configure_agnes_wait():
    """When the fallback is enabled there is no point waiting ~16 minutes per
    shot for Agnes' queue. Try twice with ONE 60 s wait in between (about one
    minute total), then let the fallback take over. Tunable with
    STOCK_FALLBACK_AGNES_TRIES (1 = no wait at all) and
    STOCK_FALLBACK_AGNES_WAIT_SECONDS. Does nothing if the fallback is off."""
    if not is_enabled():
        return
    try:
        import agnes_client
        tries = int(os.environ.get("STOCK_FALLBACK_AGNES_TRIES", "2"))
        wait = int(os.environ.get("STOCK_FALLBACK_AGNES_WAIT_SECONDS", "60"))
        agnes_client.AGNES_QUEUE_FULL_MAX_ATTEMPTS = max(1, tries)
        agnes_client.AGNES_QUEUE_FULL_WAIT_SECONDS = max(1, wait)
    except Exception as e:
        print(f"[stock_fallback] could not shorten Agnes queue wait: {e}")


def _sb():
    url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_SECRET_KEY", "")
    if not url or not key:
        return None, None
    return url, {"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json"}


def script_is_stock(script_id):
    """True once this video has started using stock footage. Stays True across
    runs (saved in scripts.clip_source), so one video is never a mix of
    Agnes clips and stock clips from that point on."""
    if not script_id:
        return False
    if script_id in _stock_scripts:
        return True
    try:
        url, headers = _sb()
        if not url:
            return False
        r = requests.get(f"{url}/rest/v1/scripts?id=eq.{script_id}&select=clip_source",
                         headers=headers, timeout=20)
        if r.status_code == 200:
            rows = r.json()
            if rows and rows[0].get("clip_source") == "stock":
                _stock_scripts.add(script_id)
                return True
    except Exception as e:
        print(f"[stock_fallback] could not read stock mode for script {script_id}: {e}")
    return False


def mark_script_stock(script_id):
    if not script_id:
        return
    if script_id not in _stock_scripts:
        print(f"[stock_fallback] script {script_id} is now STOCK-ONLY: every remaining shot of this "
              f"video uses stock footage and Agnes is not used again for it.")
    _stock_scripts.add(script_id)
    try:
        url, headers = _sb()
        if not url:
            return
        r = requests.patch(f"{url}/rest/v1/scripts?id=eq.{script_id}", headers=headers,
                           json={"clip_source": "stock"}, timeout=20)
        if r.status_code >= 300:
            print(f"[stock_fallback] could not save stock mode ({r.status_code}): {r.text[:150]}")
    except Exception as e:
        print(f"[stock_fallback] could not save stock mode for script {script_id}: {e}")


def _ffmpeg():
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return shutil.which("ffmpeg") or "ffmpeg"


def _keywords(shot):
    text = (shot.get("visual_description") or "")
    words = re.findall(r"[A-Za-z]+", text.lower())
    seen, out = set(), []
    for w in words:
        if len(w) < 4 or w in STOPWORDS or w in seen:
            continue
        seen.add(w)
        out.append(w)
    return out


def _generic_queries():
    raw = os.environ.get("STOCK_GENERIC_QUERIES", "").strip()
    if raw:
        items = [x.strip() for x in raw.split(",") if x.strip()]
        if items:
            return items
    return DEFAULT_GENERIC_QUERIES


def _query_ladder(shot, script_id, shot_index):
    kws = _keywords(shot)
    ladder = []
    for n in (3, 2, 1):
        if len(kws) >= n:
            q = " ".join(kws[:n])
            if q not in ladder:
                ladder.append(q)
    generics = _generic_queries()
    h = int(hashlib.md5(f"{script_id}:{shot_index}".encode()).hexdigest()[:8], 16)
    ladder.append(generics[h % len(generics)])
    ladder.append(generics[(h + 1) % len(generics)])
    return ladder


def _search(query):
    key = os.environ["PIXABAY_API_KEY"].strip()
    for attempt in range(3):
        try:
            r = requests.get(
                PIXABAY_VIDEO_API,
                params={"key": key, "q": query, "video_type": "film",
                        "per_page": 30, "safesearch": "true"},
                timeout=30,
            )
        except requests.RequestException as e:
            print(f"[stock_fallback] Pixabay search error for '{query}': {e}")
            time.sleep(5 * (attempt + 1))
            continue
        if r.status_code == 429:
            print("[stock_fallback] Pixabay rate limit hit - waiting 30 s")
            time.sleep(30)
            continue
        if r.status_code != 200:
            print(f"[stock_fallback] Pixabay search HTTP {r.status_code} for '{query}': {r.text[:200]}")
            return []
        try:
            return r.json().get("hits", []) or []
        except ValueError:
            return []
    return []


def _pick_file(hit):
    vids = hit.get("videos") or {}
    candidates = []
    for name in ("large", "medium", "small"):
        v = vids.get(name) or {}
        if v.get("url"):
            candidates.append(v)
    for v in candidates:
        w = v.get("width") or 0
        if 1280 <= w <= 2560:
            return v["url"]
    return candidates[0]["url"] if candidates else None


def _download(url, path):
    with requests.get(url, stream=True, timeout=120) as r:
        r.raise_for_status()
        with open(path, "wb") as f:
            for chunk in r.iter_content(chunk_size=1 << 20):
                if chunk:
                    f.write(chunk)
    return path


def _normalize(src, dst, seconds):
    """Scale and crop to 1920x1080 at 24 fps, no audio, exactly `seconds` long."""
    vf = (f"scale={OUT_W}:{OUT_H}:force_original_aspect_ratio=increase,"
          f"crop={OUT_W}:{OUT_H},fps={OUT_FPS},setsar=1")
    cmd = [_ffmpeg(), "-y", "-loglevel", "error", "-i", src, "-vf", vf, "-an",
           "-t", f"{seconds:.3f}", "-c:v", "libx264", "-preset", "veryfast",
           "-crf", "23", "-pix_fmt", "yuv420p", dst]
    subprocess.run(cmd, check=True, timeout=600)


def _concat(parts, dst):
    list_path = dst + ".txt"
    with open(list_path, "w") as f:
        for p in parts:
            f.write(f"file '{os.path.abspath(p)}'\n")
    cmd = [_ffmpeg(), "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
           "-i", list_path, "-c", "copy", dst]
    subprocess.run(cmd, check=True, timeout=600)
    os.remove(list_path)


def _probe_duration(path):
    """Real length of a video file in seconds (None if it cannot be read)."""
    try:
        p = subprocess.run([_ffmpeg(), "-i", path], capture_output=True, text=True, timeout=60)
        m = re.search(r"Duration: (\d+):(\d+):(\d+(?:\.\d+)?)", p.stderr)
        if not m:
            return None
        h, mi, sec = m.groups()
        return int(h) * 3600 + int(mi) * 60 + float(sec)
    except Exception:
        return None


def _pad_to(path, target, actual):
    """Hold the last frame so the file is exactly `target` seconds long."""
    tmp = path + ".pad.mp4"
    extra = max(target - actual, 0.0) + 0.05
    cmd = [_ffmpeg(), "-y", "-loglevel", "error", "-i", path,
           "-vf", f"tpad=stop_mode=clone:stop_duration={extra:.3f}", "-an",
           "-t", f"{target:.3f}", "-c:v", "libx264", "-preset", "veryfast",
           "-crf", "23", "-pix_fmt", "yuv420p", tmp]
    subprocess.run(cmd, check=True, timeout=600)
    os.replace(tmp, path)


def require_stock_clip(shot, target_duration, out_path, script_id=None, shot_index=None):
    """For a video already in stock mode: make the stock clip or raise. Never Agnes."""
    if make_stock_clip(shot, target_duration, out_path, script_id, shot_index):
        return out_path
    raise StockOnlyError(f"stock footage could not be fetched for shot {shot_index} of a stock-only video "
                         f"(Pixabay unreachable or nothing found) - Agnes is not used mid-video; will retry next run")


def make_stock_clip(shot, target_duration, out_path, script_id=None, shot_index=None):
    """Write a stock clip of exactly target_duration seconds to out_path.
    Returns True on success, False on any problem (caller then behaves as before)."""
    if not is_enabled():
        return False
    work = []
    try:
        remaining = float(target_duration)
        parts = []
        piece_no = 0
        ladder = _query_ladder(shot, script_id, shot_index)
        ladder += [g for g in _generic_queries() if g not in ladder]
        for query in ladder:
            if remaining <= 0.05 or piece_no >= MAX_CLIPS_PER_SHOT:
                break
            hits = [h for h in _search(query)
                    if h.get("id") not in _used_ids and (h.get("duration") or 0) >= MIN_USEFUL_CLIP_SECONDS]
            if not hits:
                time.sleep(0.8)
                continue
            start = int(hashlib.md5(f"{script_id}:{shot_index}:{query}".encode()).hexdigest()[:8], 16) % len(hits)
            ordered = hits[start:] + hits[:start]
            for hit in ordered:
                if remaining <= 0.05 or piece_no >= MAX_CLIPS_PER_SHOT:
                    break
                url = _pick_file(hit)
                if not url:
                    continue
                raw = out_path.replace(".mp4", f"_stock_raw{piece_no}.mp4")
                norm = out_path.replace(".mp4", f"_stock_norm{piece_no}.mp4")
                work.extend([raw, norm])
                try:
                    _download(url, raw)
                    use = min(remaining, float(hit.get("duration") or remaining))
                    _normalize(raw, norm, use)
                except Exception as e:
                    print(f"[stock_fallback] clip {hit.get('id')} failed, trying another: {e}")
                    continue
                _used_ids.add(hit.get("id"))
                parts.append(norm)
                remaining -= use
                piece_no += 1
            time.sleep(0.8)

        if not parts:
            print(f"[stock_fallback] found no stock footage at all for shot {shot_index}.")
            return False

        if len(parts) == 1:
            shutil.copyfile(parts[0], out_path)
        else:
            _concat(parts, out_path)
        # Safety net: trust the real file length, not Pixabay's stated length.
        actual = _probe_duration(out_path)
        if actual is not None and actual < float(target_duration) - 0.3:
            print(f"[stock_fallback] shot {shot_index}: clip was only {actual:.1f}s for a {target_duration:.1f}s shot "
                  f"- holding the last frame for the remaining {float(target_duration) - actual:.1f}s.")
            _pad_to(out_path, float(target_duration), actual)
            actual = _probe_duration(out_path)
        print(f"[stock_fallback] shot {shot_index}: stock footage used ({len(parts)} clip(s), "
              f"{target_duration:.1f}s wanted, {actual if actual is not None else 0:.1f}s real).")
        return True
    except Exception as e:
        print(f"[stock_fallback] failed for shot {shot_index}: {e}")
        return False
    finally:
        for p in work:
            try:
                if os.path.exists(p):
                    os.remove(p)
            except OSError:
                pass
