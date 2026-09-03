"""
Marius Command Center - One-off Supabase Storage Cleanup
Run manually via workflow_dispatch. Not part of the regular pipeline.

WHY THIS EXISTS (2026-09-04): the 2026-09-02 B2 migration moved all NEW
video storage to Backblaze B2, but ~10.3 GB of OLD files from before the
migration were still sitting in Supabase Storage, pushing the project over
its free-tier quota (exceed_storage_size_quota / exceed_egress_quota),
which was blocking every workflow that touches the database (Update
Status, Script Writing, Narration all failed with 402 Payment Required).

WHAT COUNTS AS SAFE TO DELETE:
  - Files belonging to a script whose status = 'uploaded' (the video is
    already live on YouTube - the Supabase copy is a pure duplicate).
  - Files that don't match ANY script id currently in the database at all
    (orphaned - the parent record was deleted or reworked at some point,
    so nothing in the pipeline could ever reference these again).

WHAT IS EXPLICITLY PROTECTED (never touched by this script):
  - Files belonging to any script whose status is NOT 'uploaded' - i.e.
    'archived' or 'images_generated' or any future non-uploaded status.
    These represent generated-but-not-yet-finished work (video clips,
    narration, images) that hasn't been turned into a finished video yet.
    Deleting these would destroy real, unused production work.

HOW MATCHING WORKS: every filename/path in every bucket contains the
script's UUID somewhere in it (e.g. "8c626aa5....mp4",
"narration_8c626aa5....wav", "8c626aa5..../part_003.mp4",
"8c626aa5..../shot_012.mp4"). So a file is protected if its path contains
the UUID of any non-uploaded script, and is a deletion candidate
otherwise.
"""

import os
import sys
from supabase import create_client

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_SECRET_KEY = os.environ["SUPABASE_SECRET_KEY"]

BUCKETS = ["video_clips", "videos", "narration", "images", "thumbnails"]

# Safety valve: set DRY_RUN=false in the workflow env to actually delete.
# Defaults to true (list-only) so a run with a typo'd env can't nuke anything.
DRY_RUN = os.environ.get("DRY_RUN", "true").strip().lower() != "false"


def list_all_objects(supabase, bucket):
    """Recursively lists every object in a bucket, including inside
    subfolders (e.g. video_clips/<script_id>/shot_001.mp4). The Storage
    API's list() only returns one level at a time and mixes files and
    folders together in the same response, so this walks folders it finds."""
    all_paths = []
    stack = [""]
    while stack:
        prefix = stack.pop()
        offset = 0
        while True:
            entries = supabase.storage.from_(bucket).list(
                path=prefix,
                options={"limit": 1000, "offset": offset},
            )
            if not entries:
                break
            for entry in entries:
                full_path = f"{prefix}/{entry['name']}" if prefix else entry["name"]
                # Supabase Storage folders are represented as entries with
                # id == None and no metadata.
                if entry.get("id") is None and entry.get("metadata") is None:
                    stack.append(full_path)
                else:
                    all_paths.append((full_path, (entry.get("metadata") or {}).get("size", 0)))
            if len(entries) < 1000:
                break
            offset += 1000
    return all_paths


def main():
    supabase = create_client(SUPABASE_URL, SUPABASE_SECRET_KEY)

    print("Fetching protected (non-uploaded) script ids...")
    protected = (
        supabase.table("scripts")
        .select("id")
        .neq("status", "uploaded")
        .execute()
    )
    protected_ids = [row["id"] for row in protected.data]
    print(f"Protected script ids (never deleted): {len(protected_ids)}")

    total_deleted_files = 0
    total_deleted_bytes = 0
    total_protected_files = 0

    for bucket in BUCKETS:
        print(f"\n--- Bucket: {bucket} ---")
        objects = list_all_objects(supabase, bucket)
        print(f"Found {len(objects)} files.")

        to_delete = []
        for path, size in objects:
            if any(pid in path for pid in protected_ids):
                total_protected_files += 1
                continue
            to_delete.append(path)
            total_deleted_bytes += size or 0

        print(f"Safe to delete in this bucket: {len(to_delete)}")

        if not to_delete:
            continue

        if DRY_RUN:
            print(f"[DRY RUN] Would delete {len(to_delete)} files from '{bucket}'. "
                  f"Example: {to_delete[:3]}")
            total_deleted_files += len(to_delete)
            continue

        # Delete in batches of 100 (Storage API limit per call).
        for i in range(0, len(to_delete), 100):
            batch = to_delete[i:i + 100]
            supabase.storage.from_(bucket).remove(batch)
            total_deleted_files += len(batch)
            print(f"Deleted batch {i // 100 + 1} ({len(batch)} files) from '{bucket}'.")

    print("\n=== SUMMARY ===")
    print(f"Mode: {'DRY RUN - nothing actually deleted' if DRY_RUN else 'LIVE DELETE'}")
    print(f"Files deleted: {total_deleted_files}")
    print(f"Space freed: {total_deleted_bytes / (1024**3):.2f} GB")
    print(f"Files protected/skipped (unfinished work): {total_protected_files}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
