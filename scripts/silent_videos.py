"""
Marius Command Center - Silent video export (2026-10-25)
Manual one-off. For every script that has generated shot clips in B2
(scripts.video_urls), downloads those clips in order, joins them into one
silent video (no narration, no music) and writes it to ./silent_out/<id>.mp4.
The workflow silent_videos.yml then offers that folder as a downloadable
GitHub Actions artifact. Changes nothing in Supabase and deletes nothing in B2.
"""

import os
import sys
import requests
from moviepy import VideoFileClip, concatenate_videoclips
import storage_b2

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SECRET_KEY"]
HEADERS = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}
OUT_DIR = "silent_out"
FPS = 24
SIZE = (1280, 704)


def get_scripts():
    r = requests.get(
        f"{SUPABASE_URL}/rest/v1/scripts?select=id,status,video_urls,video_next_index"
        f"&video_next_index=gt.0&order=video_next_index.desc",
        headers=HEADERS, timeout=60,
    )
    r.raise_for_status()
    return [s for s in r.json() if s.get("video_urls") and s["status"] != "uploaded"]


def build(script):
    sid = script["id"]
    keys = script["video_urls"]
    paths = []
    for i, key in enumerate(keys):
        p = f"/tmp/silent_{sid}_{i:03d}.mp4"
        storage_b2.download_to_file(key, p)
        paths.append(p)
    clips = []
    for p in paths:
        c = VideoFileClip(p)
        if c.size != list(SIZE) and tuple(c.size) != SIZE:
            c = c.resized(SIZE)
        clips.append(c)
    final = concatenate_videoclips(clips, method="compose")
    out = os.path.join(OUT_DIR, f"{sid}_{len(keys)}clips_silent.mp4")
    final.write_videofile(out, fps=FPS, codec="libx264", audio=False, threads=2, logger=None)
    for c in clips:
        c.close()
    for p in paths:
        os.remove(p)
    print(f"Built {out} from {len(keys)} clips.")


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    scripts = get_scripts()
    print(f"{len(scripts)} script(s) with generated clips.")
    failures = 0
    for s in scripts:
        try:
            build(s)
        except Exception as e:
            failures += 1
            print(f"FAILED for script {s['id']}: {e}")
    if failures and failures == len(scripts):
        sys.exit(1)


if __name__ == "__main__":
    main()
