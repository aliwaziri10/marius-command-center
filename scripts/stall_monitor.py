import os
import sys
from datetime import datetime, timedelta, timezone
from supabase import create_client

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_SECRET_KEY = os.environ["SUPABASE_SECRET_KEY"]

# A script sitting in images_generated for longer than this with clips still
# incomplete gets flagged as stalled. 48h is generous - a healthy run
# advances every ~40 min via video_generation.yml, so a script genuinely
# still short of its shot count after 48h has stopped making progress, not
# just queued behind other work.
STALL_THRESHOLD_HOURS = 48


def main():
    supabase = create_client(SUPABASE_URL, SUPABASE_SECRET_KEY)
    result = supabase.table("scripts").select(
        "id, status, created_at, video_urls, shot_list"
    ).eq("status", "images_generated").execute()

    if not result.data:
        print("No images_generated scripts found. Nothing to check.")
        return

    now = datetime.now(timezone.utc)
    stalled = []

    for row in result.data:
        created_at = datetime.fromisoformat(row["created_at"].replace("Z", "+00:00"))
        age_hours = (now - created_at).total_seconds() / 3600
        clips_done = len(row.get("video_urls") or [])
        total_shots = len(row.get("shot_list") or [])

        if age_hours >= STALL_THRESHOLD_HOURS and clips_done < total_shots:
            stalled.append({
                "id": row["id"],
                "age_hours": round(age_hours, 1),
                "clips_done": clips_done,
                "total_shots": total_shots,
            })
            print(f"STALLED: {row['id']} - {clips_done}/{total_shots} clips, "
                  f"{age_hours:.1f}h old (threshold {STALL_THRESHOLD_HOURS}h)")

    if not stalled:
        print("No stalled scripts found. All images_generated rows are within threshold or complete.")
        return

    print(f"Found {len(stalled)} stalled script(s).")
    sys.exit(1)


if __name__ == "__main__":
    main()
