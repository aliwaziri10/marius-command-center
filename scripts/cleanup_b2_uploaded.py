"""
Marius Command Center - One-off Backblaze B2 cleanup (2026-10-09)
Run manually via workflow_dispatch (cleanup_b2_uploaded.yml).

WHY: B2 bucket hit 75% of its free quota. Final videos are already deleted
right after YouTube upload (youtube_upload.py), but per-shot clips,
narration, images and thumbnails for finished episodes were never removed.

DELETES: every object in the bucket whose key contains the UUID of a script
whose status = 'uploaded' (already live on YouTube - pure duplicates).

NEVER TOUCHES: objects belonging to any script that is not 'uploaded'
(unfinished work), and objects matching no script at all (reported only,
unless DELETE_ORPHANS=true).
"""

import os
import sys
import requests
import storage_b2

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SECRET_KEY"]
HEADERS = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}

DRY_RUN = os.environ.get("DRY_RUN", "false").strip().lower() == "true"
DELETE_ORPHANS = os.environ.get("DELETE_ORPHANS", "false").strip().lower() == "true"


def fetch_script_ids():
    uploaded, other = set(), set()
    offset = 0
    while True:
        r = requests.get(
            f"{SUPABASE_URL}/rest/v1/scripts?select=id,status&order=created_at.asc"
            f"&limit=1000&offset={offset}",
            headers=HEADERS, timeout=60,
        )
        r.raise_for_status()
        rows = r.json()
        for row in rows:
            (uploaded if row["status"] == "uploaded" else other).add(row["id"])
        if len(rows) < 1000:
            break
        offset += 1000
    return uploaded, other


def list_bucket():
    client = storage_b2._get_client()
    paginator = client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=storage_b2.B2_BUCKET_NAME):
        for obj in page.get("Contents", []):
            yield obj["Key"], obj["Size"]


def gb(n):
    return f"{n / (1024 ** 3):.2f} GB"


def main():
    uploaded_ids, other_ids = fetch_script_ids()
    print(f"Scripts: {len(uploaded_ids)} uploaded, {len(other_ids)} not uploaded (protected).")

    total_files = total_bytes = 0
    to_delete, del_bytes = [], 0
    kept_files = kept_bytes = orphan_files = orphan_bytes = 0

    for key, size in list_bucket():
        total_files += 1
        total_bytes += size
        if any(i in key for i in other_ids):
            kept_files += 1
            kept_bytes += size
        elif any(i in key for i in uploaded_ids):
            to_delete.append(key)
            del_bytes += size
        else:
            orphan_files += 1
            orphan_bytes += size
            if DELETE_ORPHANS:
                to_delete.append(key)
                del_bytes += size

    print(f"Bucket now: {total_files} files, {gb(total_bytes)}")
    print(f"Protected (unfinished scripts): {kept_files} files, {gb(kept_bytes)}")
    print(f"Orphans (match no script): {orphan_files} files, {gb(orphan_bytes)} "
          f"- {'DELETING' if DELETE_ORPHANS else 'left alone'}")
    print(f"To delete: {len(to_delete)} files, {gb(del_bytes)}")

    if DRY_RUN:
        print(f"[DRY RUN] nothing deleted. Examples: {to_delete[:5]}")
        return

    client = storage_b2._get_client()
    deleted = 0
    for i in range(0, len(to_delete), 1000):
        batch = to_delete[i:i + 1000]
        resp = client.delete_objects(
            Bucket=storage_b2.B2_BUCKET_NAME,
            Delete={"Objects": [{"Key": k} for k in batch], "Quiet": True},
        )
        errs = resp.get("Errors", [])
        deleted += len(batch) - len(errs)
        for e in errs[:5]:
            print(f"Delete error: {e}")
        print(f"Deleted batch {i // 1000 + 1}: {len(batch) - len(errs)}/{len(batch)}")

    print("\n=== SUMMARY ===")
    print(f"Files deleted: {deleted}")
    print(f"Space freed: about {gb(del_bytes)}")
    print(f"Bucket should now hold about {gb(total_bytes - del_bytes)}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
