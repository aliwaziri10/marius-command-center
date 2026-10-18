"""
Fallback-chain experiments (branch: fallback-chain).

PURPOSE: measure, in a real GitHub Actions run, which free video sources work
for Marius and what they actually return. Nothing here changes the pipeline.
Nothing here is assumed: every result below is written to
experiments/RESULTS.md with a raw excerpt, and every call is written to
experiments/CALL_LOG.md.

RULES THIS FILE FOLLOWS
- Free sources only. No paid, credit-based or trial API is called.
- Keys come from environment variables only and are never printed or written.
  Everything written to disk passes through redact() first.
- Few requests (about 2 to 4 per source per run), only a 1 KB range download
  per source. No mass downloads. Pixabay responses would be cached 24h in the
  real code; this test makes only two Pixabay searches.
- A source with no key is SKIPPED, not failed.
- The Agnes probe runs ONLY when the file experiments/PROBE_AGNES exists on
  the branch, so pushes do not poke Agnes by accident.
"""

import os
import re
import sys
import time
import datetime

import requests

OUT_DIR = "experiments"
RESULTS_PATH = os.path.join(OUT_DIR, "RESULTS.md")
CALLLOG_PATH = os.path.join(OUT_DIR, "CALL_LOG.md")
PROBE_FLAG = os.path.join(OUT_DIR, "PROBE_AGNES")

UA = "marius-command-center-fallback-test/0.1 (+https://github.com/aliwaziri10/marius-command-center)"
TIMEOUT = 25
SECRET_NAMES = ("PIXABAY_API_KEY", "PEXELS_API_KEY", "AGNES_API_KEY")
CALLS = []


def _secret_values():
    return [os.environ[n] for n in SECRET_NAMES if os.environ.get(n)]


def redact(text):
    text = str(text)
    for v in _secret_values():
        text = text.replace(v, "***")
    return text


def call(source, method, url, params=None, headers=None, json_body=None, stream=False):
    """One HTTP call. Returns (response_or_None, error_text_or_None). Logs the
    call without any key (key-like params are dropped from the log)."""
    public = {k: v for k, v in (params or {}).items() if k.lower() not in ("key", "api_key")}
    h = {"User-Agent": UA}
    h.update(headers or {})
    started = time.time()
    resp, err = None, None
    try:
        resp = requests.request(method, url, params=params, headers=h, json=json_body,
                                timeout=TIMEOUT, stream=stream)
    except Exception as e:  # any network failure is a result, not a crash
        err = redact(f"{e.__class__.__name__}: {e}")
    took = round(time.time() - started, 2)
    CALLS.append({
        "time": datetime.datetime.now(datetime.timezone.utc).strftime("%H:%M:%S"),
        "source": source,
        "method": method,
        "url": redact(url),
        "params": redact(public),
        "status": resp.status_code if resp is not None else "-",
        "seconds": took,
        "error": err or "",
    })
    return resp, err


def jsonof(resp):
    try:
        return resp.json()
    except Exception:
        return None


def excerpt(resp, n=350):
    try:
        text = resp.text
    except Exception:
        text = "<no text>"
    return redact(re.sub(r"\s+", " ", text)[:n])


def result(name, status, lines, raw=""):
    return {"name": name, "status": status, "lines": [redact(x) for x in lines], "raw": redact(raw)}


def range_check(source, url):
    """Download only the first 1 KB to prove the file URL is reachable."""
    resp, err = call(source + "-file", "GET", url, headers={"Range": "bytes=0-1023"}, stream=True)
    if err or resp is None:
        return False, f"file check error: {err}"
    try:
        got = len(resp.raw.read(1024))
    except Exception:
        got = -1
    ctype = resp.headers.get("Content-Type")
    resp.close()
    ok = resp.status_code in (200, 206) and got > 0
    return ok, f"file check HTTP {resp.status_code}, content-type {ctype}, first bytes read {got}"


def strip_tags(s):
    return re.sub(r"<[^>]+>", "", s or "").strip()


# ---------------------------------------------------------------- Pixabay
def test_pixabay():
    key = os.environ.get("PIXABAY_API_KEY")
    if not key:
        return result("Pixabay video", "SKIPPED", ["no PIXABAY_API_KEY in this run"])
    lines, status, raw, first = [], "PASS", "", None
    queries = [
        ("short keywords", "ocean waves"),
        ("long prompt-like", ("Wide cinematic shot of ancient stone ruins at golden hour, slow drone push in, "
                              "dust in the air, no people")[:100]),
    ]
    for label, q in queries:
        resp, err = call("pixabay", "GET", "https://pixabay.com/api/videos/",
                         params={"key": key, "q": q, "per_page": 3, "safesearch": "true"})
        if err or resp is None:
            lines.append(f"{label}: request error: {err}")
            status = "FAIL"
            continue
        rl = {k: resp.headers.get(k) for k in ("X-RateLimit-Limit", "X-RateLimit-Remaining", "X-RateLimit-Reset")}
        if resp.status_code != 200:
            lines.append(f"{label}: HTTP {resp.status_code}, body: {excerpt(resp)}, rate-limit headers {rl}")
            status = "FAIL"
            continue
        data = jsonof(resp) or {}
        hits = data.get("hits", [])
        lines.append(f"{label}: q='{q}' HTTP 200, totalHits={data.get('totalHits')}, returned={len(hits)}, rate-limit headers {rl}")
        if hits and first is None:
            first, raw = hits[0], excerpt(resp)
    if first:
        small = (first.get("videos") or {}).get("small") or {}
        lines.append(f"first hit id={first.get('id')} duration={first.get('duration')}s small={small.get('width')}x{small.get('height')}")
        lines.append(f"CREDIT: Video by {first.get('user')} on Pixabay, {first.get('pageURL')} "
                     "(Pixabay Content Licence, https://pixabay.com/service/license-summary/)")
        if small.get("url"):
            ok, msg = range_check("pixabay", small["url"])
            lines.append(msg)
            if not ok:
                status = "FAIL"
    elif status == "PASS":
        status = "FAIL"
        lines.append("no hits returned for either query")
    return result("Pixabay video", status, lines, raw)


# ---------------------------------------------------------------- Pexels (optional)
def test_pexels():
    key = os.environ.get("PEXELS_API_KEY")
    if not key:
        return result("Pexels video (optional)", "SKIPPED", ["no PEXELS_API_KEY in this run"])
    lines, status, raw = [], "PASS", ""
    resp, err = call("pexels", "GET", "https://api.pexels.com/videos/search",
                     params={"query": "ocean waves", "per_page": 3, "orientation": "landscape"},
                     headers={"Authorization": key})
    if err or resp is None:
        return result("Pexels video (optional)", "FAIL", [f"request error: {err}"])
    rl = {k: resp.headers.get(k) for k in ("X-Ratelimit-Limit", "X-Ratelimit-Remaining", "X-Ratelimit-Reset")}
    if resp.status_code != 200:
        return result("Pexels video (optional)", "FAIL", [f"HTTP {resp.status_code}, body: {excerpt(resp)}, headers {rl}"])
    data = jsonof(resp) or {}
    vids = data.get("videos", [])
    lines.append(f"HTTP 200, returned={len(vids)}, rate-limit headers {rl}")
    raw = excerpt(resp)
    if vids:
        v = vids[0]
        files = v.get("video_files", [])
        pick = next((f for f in files if f.get("width") == 1280), files[0] if files else {})
        lines.append(f"first hit id={v.get('id')} duration={v.get('duration')}s picked={pick.get('width')}x{pick.get('height')}")
        lines.append(f"CREDIT: Video by {(v.get('user') or {}).get('name')} on Pexels, {v.get('url')} (Pexels licence)")
        if pick.get("link"):
            ok, msg = range_check("pexels", pick["link"])
            lines.append(msg)
            if not ok:
                status = "FAIL"
    else:
        status = "FAIL"
    return result("Pexels video (optional)", status, lines, raw)


# ---------------------------------------------------------------- NASA
def test_nasa():
    lines, status, raw = [], "PASS", ""
    resp, err = call("nasa", "GET", "https://images-api.nasa.gov/search",
                     params={"q": "moon surface", "media_type": "video", "page_size": 3})
    if err or resp is None:
        return result("NASA Image and Video Library", "FAIL", [f"request error: {err}"])
    if resp.status_code != 200:
        return result("NASA Image and Video Library", "FAIL", [f"HTTP {resp.status_code}, body: {excerpt(resp)}"])
    data = jsonof(resp) or {}
    items = ((data.get("collection") or {}).get("items")) or []
    lines.append(f"search HTTP 200, returned={len(items)}")
    raw = excerpt(resp)
    if not items:
        return result("NASA Image and Video Library", "FAIL", lines + ["no items returned"], raw)
    meta = (items[0].get("data") or [{}])[0]
    nid = meta.get("nasa_id")
    lines.append(f"first item nasa_id={nid} title={meta.get('title')!r} center={meta.get('center')}")
    resp2, err2 = call("nasa", "GET", f"https://images-api.nasa.gov/asset/{nid}")
    if err2 or resp2 is None or resp2.status_code != 200:
        return result("NASA Image and Video Library", "FAIL",
                      lines + [f"asset lookup failed: {err2 or resp2.status_code}"], raw)
    hrefs = [i.get("href", "") for i in (((jsonof(resp2) or {}).get("collection") or {}).get("items") or [])]
    mp4s = [h.replace("http://", "https://") for h in hrefs if h.lower().endswith(".mp4")]
    lines.append(f"mp4 variants found: {[m.rsplit('~', 1)[-1] if '~' in m else m.rsplit('/', 1)[-1] for m in mp4s]}")
    lines.append(f"CREDIT: NASA, {meta.get('title')} (nasa_id {nid}). NASA media usage guidelines: "
                 "https://www.nasa.gov/nasa-brand-center/images-and-media/ . Licence per item UNVERIFIED.")
    pick = next((m for m in mp4s if "~medium" in m), mp4s[0] if mp4s else None)
    if pick:
        ok, msg = range_check("nasa", pick)
        lines.append(msg)
        if not ok:
            status = "FAIL"
    else:
        status = "FAIL"
        lines.append("no mp4 file in the asset list")
    return result("NASA Image and Video Library", status, lines, raw)


# ---------------------------------------------------------------- Internet Archive
def test_archive():
    lines, status, raw = [], "PASS", ""
    resp, err = call("archive", "GET", "https://archive.org/advancedsearch.php",
                     params={"q": "collection:prelinger AND mediatype:movies",
                             "fl[]": ["identifier", "title", "licenseurl"],
                             "rows": 3, "sort[]": "downloads desc", "output": "json"})
    if err or resp is None:
        return result("Internet Archive", "FAIL", [f"request error: {err}"])
    if resp.status_code != 200:
        return result("Internet Archive", "FAIL", [f"HTTP {resp.status_code}, body: {excerpt(resp)}"])
    docs = (((jsonof(resp) or {}).get("response")) or {}).get("docs") or []
    lines.append(f"search HTTP 200, returned={len(docs)}")
    raw = excerpt(resp)
    if not docs:
        return result("Internet Archive", "FAIL", lines + ["no docs returned"], raw)
    ident = docs[0].get("identifier")
    resp2, err2 = call("archive", "GET", f"https://archive.org/metadata/{ident}")
    if err2 or resp2 is None or resp2.status_code != 200:
        return result("Internet Archive", "FAIL", lines + [f"metadata failed: {err2 or resp2.status_code}"], raw)
    md = jsonof(resp2) or {}
    files = md.get("files") or []
    mp4 = next((f for f in files if str(f.get("name", "")).lower().endswith(".mp4")), None)
    meta = md.get("metadata") or {}
    lines.append(f"identifier={ident} title={meta.get('title')!r} licenseurl={meta.get('licenseurl')} rights={meta.get('rights')}")
    lines.append(f"CREDIT: Internet Archive, {meta.get('title')}, https://archive.org/details/{ident} "
                 f"(licence: {meta.get('licenseurl') or 'not stated in metadata, UNVERIFIED'})")
    if mp4:
        lines.append(f"mp4 file {mp4.get('name')} size={mp4.get('size')} format={mp4.get('format')}")
        ok, msg = range_check("archive", f"https://archive.org/download/{ident}/{mp4.get('name')}")
        lines.append(msg)
        if not ok:
            status = "FAIL"
    else:
        status = "FAIL"
        lines.append("no mp4 file listed for this item")
    return result("Internet Archive", status, lines, raw)


# ---------------------------------------------------------------- Wikimedia Commons
def test_wikimedia():
    lines, status, raw = [], "PASS", ""
    resp, err = call("wikimedia", "GET", "https://commons.wikimedia.org/w/api.php",
                     params={"action": "query", "generator": "search", "gsrsearch": "volcano filetype:video",
                             "gsrnamespace": 6, "gsrlimit": 3, "prop": "imageinfo",
                             "iiprop": "url|size|mime|extmetadata", "format": "json", "formatversion": 2})
    if err or resp is None:
        return result("Wikimedia Commons", "FAIL", [f"request error: {err}"])
    if resp.status_code != 200:
        return result("Wikimedia Commons", "FAIL", [f"HTTP {resp.status_code}, body: {excerpt(resp)}"])
    pages = (((jsonof(resp) or {}).get("query")) or {}).get("pages") or []
    lines.append(f"search HTTP 200, returned={len(pages)}")
    raw = excerpt(resp)
    pick = None
    for p in pages:
        info = (p.get("imageinfo") or [{}])[0]
        if str(info.get("mime", "")).startswith("video/"):
            pick = (p, info)
            break
    if not pick:
        return result("Wikimedia Commons", "FAIL", lines + ["no video file in the results"], raw)
    p, info = pick
    ext = info.get("extmetadata") or {}
    lic = (ext.get("LicenseShortName") or {}).get("value")
    artist = strip_tags((ext.get("Artist") or {}).get("value"))
    attrib = (ext.get("AttributionRequired") or {}).get("value")
    lines.append(f"title={p.get('title')!r} mime={info.get('mime')} size={info.get('width')}x{info.get('height')}")
    lines.append(f"CREDIT: {p.get('title')} by {artist or 'unknown'}, licence {lic}, attribution required: {attrib}, "
                 f"{info.get('descriptionurl')}")
    ok, msg = range_check("wikimedia", info.get("url", ""))
    lines.append(msg)
    if not ok:
        status = "FAIL"
    return result("Wikimedia Commons", status, lines, raw)


# ---------------------------------------------------------------- Agnes probe
def test_agnes():
    if not os.path.exists(PROBE_FLAG):
        return result("Agnes quick check", "SKIPPED", ["experiments/PROBE_AGNES not present, no probe sent"])
    key = os.environ.get("AGNES_API_KEY")
    if not key:
        return result("Agnes quick check", "SKIPPED", ["no AGNES_API_KEY in this run"])
    payload = {"model": "agnes-video-2.5-flash",
               "prompt": "A calm ocean wave rolling onto a sandy beach, static camera",
               "mode": "text", "seconds": "4", "size": "720P", "aspect_ratio": "16:9", "n": 1}
    resp, err = call("agnes", "POST", "https://apihub.agnes-ai.com/v1/videos",
                     headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                     json_body=payload)
    if err or resp is None:
        return result("Agnes quick check", "FAIL", [f"request error: {err}"])
    took = CALLS[-1]["seconds"]
    queue_full = resp.status_code == 503 and "video_queue_full" in resp.text
    lines = [f"POST /v1/videos answered HTTP {resp.status_code} in {took}s, queue_full={queue_full}",
             "no polling was done (this is only a latency and availability check)"]
    return result("Agnes quick check", "PASS" if (resp.status_code == 200 or queue_full) else "FAIL",
                  lines, excerpt(resp))


def write_outputs(results):
    os.makedirs(OUT_DIR, exist_ok=True)
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    server = os.environ.get("GITHUB_SERVER_URL", "")
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    run_id = os.environ.get("GITHUB_RUN_ID", "")
    run_link = f"{server}/{repo}/actions/runs/{run_id}" if run_id else "not running in Actions (local run, proves nothing)"
    out = ["# Fallback-chain experiment results", "",
           f"- Run: {run_link}", f"- Commit: {os.environ.get('GITHUB_SHA', 'n/a')}", f"- Time: {now}", "",
           "| Source | Result |", "|---|---|"]
    out += [f"| {r['name']} | {r['status']} |" for r in results]
    for r in results:
        out += ["", f"## {r['name']}: {r['status']}", ""]
        out += [f"- {x}" for x in r["lines"]]
        if r["raw"]:
            out += ["", "Raw excerpt:", "```", r["raw"], "```"]
    log = ["# Call log (no keys are ever written here)", "",
           "| Time | Source | Method | URL | Params | HTTP | Seconds | Error |", "|---|---|---|---|---|---|---|---|"]
    for c in CALLS:
        log.append(f"| {c['time']} | {c['source']} | {c['method']} | {c['url']} | {c['params']} | "
                   f"{c['status']} | {c['seconds']} | {c['error']} |")
    for path, body in ((RESULTS_PATH, "\n".join(out) + "\n"), (CALLLOG_PATH, "\n".join(log) + "\n")):
        body = redact(body)
        for v in _secret_values():
            assert v not in body, "a secret value would have been written, refusing"
        with open(path, "w", encoding="utf-8") as f:
            f.write(body)


def main():
    results = []
    for fn in (test_pixabay, test_pexels, test_nasa, test_archive, test_wikimedia, test_agnes):
        try:
            results.append(fn())
        except Exception as e:  # a bug in one test must not hide the others
            results.append(result(fn.__name__, "FAIL", [f"test crashed: {e.__class__.__name__}: {e}"]))
    write_outputs(results)
    print("done:", ", ".join(f"{r['name']}={r['status']}" for r in results))
    return 0


if __name__ == "__main__":
    sys.exit(main())
