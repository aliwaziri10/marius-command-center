"""
Marius Command Center - automatic Backblaze B2 sweep (2026-11-03)

WHY: youtube_upload.py only ever deleted the final video file after a YouTube
upload. Per-shot clips, narration, images and thumbnails of finished episodes
were never removed, so the bucket kept filling (Backblaze 75% alerts).
Also, a plain delete on a B2 bucket only hides a file (the old version stays
and still counts toward storage), so this sweep removes EVERY version and
every delete-marker of each matching file.

WHAT IT DELETES: every object (all versions) whose key contains the UUID of a
script with status = 'uploaded' (already live on YouTube).
WHAT IT NEVER TOUCHES: any key containing the UUID of a script that is NOT
'uploaded' (unfinished work), and keys matching no script at all.

Safe by design: never raises, so it can never break an upload run.
Set B2_SWEEP_ENABLED=0 to turn it off.
"""

import os
import requests
import storage_b2


def _gb(n):
    return f"{n / (1024 ** 3):.2f} GB"


def _fetch_script_ids():
    url = os.environ["SUPABASE_URL"]
    key = os.environ["SUPABASE_SECRET_KEY"]
    headers = {"apikey": key, "Authorization": f"Bearer {key}"}
    uploaded, other = set(), set()
    offset = 0
    while True:
        r = requests.get(
            f"{url}/rest/v1/scripts?select=id,status&order=created_at.asc"
            f"&limit=1000&offset={offset}",
            headers=headers, timeout=60,
        )
        r.raise_for_status()
        rows = r.json()
        for row in rows:
            (uploaded if row["status"] == "uploaded" else other).add(row["id"])
        if len(rows) < 1000:
            break
        offset += 1000
    return uploaded, other


def sweep():
    if os.environ.get("B2_SWEEP_ENABLED", "1").strip() == "0":
        print("[b2_sweep] disabled by B2_SWEEP_ENABLED=0")
        return
    try:
        uploaded_ids, other_ids = _fetch_script_ids()
        client = storage_b2._new_client()
        bucket = storage_b2.B2_BUCKET_NAME

        targets = []  # (key, version_id, size)
        total_bytes = 0
        paginator = client.get_paginator("list_object_versions")
        for page in paginator.paginate(Bucket=bucket):
            for kind in ("Versions", "DeleteMarkers"):
                for obj in page.get(kind, []):
                    k = obj["Key"]
                    size = obj.get("Size", 0) or 0
                    total_bytes += size
                    if any(i in k for i in other_ids):
                        continue
                    if any(i in k for i in uploaded_ids):
                        targets.append((k, obj["VersionId"], size))

        freed = sum(t[2] for t in targets)
        print(f"[b2_sweep] bucket holds {_gb(total_bytes)} across all versions; "
              f"{len(targets)} versions belong to uploaded scripts ({_gb(freed)})")
        if not targets:
            return

        deleted = 0
        for i in range(0, len(targets), 1000):
            batch = targets[i:i + 1000]
            resp = client.delete_objects(
                Bucket=bucket,
                Delete={
                    "Objects": [{"Key": k, "VersionId": v} for k, v, _ in batch],
                    "Quiet": True,
                },
            )
            errs = resp.get("Errors", [])
            deleted += len(batch) - len(errs)
            for e in errs[:5]:
                print(f"[b2_sweep] delete error: {e}")
        print(f"[b2_sweep] deleted {deleted}/{len(targets)} versions, about {_gb(freed)} freed")
    except Exception as e:
        print(f"[b2_sweep] failed (non-fatal): {e}")


if __name__ == "__main__":
    sweep()
