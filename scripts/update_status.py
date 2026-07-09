import os
from datetime import datetime, timezone
from supabase import create_client

supabase = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SECRET_KEY"])

topics = supabase.table("topics").select("id", count="exact").execute()
scripts = supabase.table("scripts").select("id,status,video_urls,video_next_index").execute().data

counts = {}
for s in scripts:
    counts[s["status"]] = counts.get(s["status"], 0) + 1

latest = scripts[-1] if scripts else None
now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

lines = [f"# Marius Status", f"Updated: {now}", "", f"Topics: {topics.count}"]
lines.append("Scripts by status: " + ", ".join(f"{k}={v}" for k, v in counts.items()) if counts else "Scripts: none yet")
if latest:
    clips = len(latest.get("video_urls") or [])
    lines.append(f"Latest script: {latest['id'][:8]} — {latest['status']} ({clips} clips)")

with open("STATUS.md", "w") as f:
    f.write("\n".join(lines) + "\n")

print("STATUS.md written.")
