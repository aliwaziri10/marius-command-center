"""
Marius Command Center - Backblaze B2 storage (2026-09-02 migration)

Replaces Supabase Storage for all video/image assets (narration/scripts
stay on Supabase Postgres - only large-object storage moves). Marius's
Supabase org is confirmed on the Free plan (same as Nova's), which has a
real platform-level object size ceiling that no bucket/dashboard setting
can raise past - the exact issue that forced Nova's own B2 migration.
Rather than trust an unverified dashboard change, B2 removes the question
entirely: no practical per-object size limit for anything this pipeline
produces.

DESIGN DIFFERENCE FROM NOVA'S B2 MIGRATION - READ THIS FIRST:
Nova's version stores presigned URLs (6-day expiry) directly in the
database. That works for Nova's turnaround, but Marius's own history
shows a single resumable episode can take 19+ days across many scheduled
runs (confirmed: script 40ffc83c, Bosnia episode). A presigned URL with
any fixed expiry would silently break mid-episode - the per-run clip
re-verification step (HEAD-checking every already-uploaded shot) would
start failing on shots that are perfectly fine, forcing needless
regeneration. So this module NEVER stores a presigned URL anywhere.
Only the permanent, non-expiring B2 OBJECT KEY is ever persisted to
Supabase (in video_urls, video_chunk_urls, video_url,
character_reference_url). A presigned URL is generated fresh, on demand,
every single time something actually needs to fetch or hand a URL to an
external system (e.g. passing an anchor image to Agnes, which needs a
real fetchable URL, not a key) - see presigned_url() below. This makes
expiry a non-issue regardless of how long an episode takes.
"""

import os
import boto3
from botocore.client import Config

B2_ENDPOINT_URL = os.environ["B2_ENDPOINT_URL"]
B2_KEY_ID = os.environ["B2_KEY_ID"]
B2_APPLICATION_KEY = os.environ["B2_APPLICATION_KEY"]
B2_BUCKET_NAME = os.environ.get("B2_BUCKET_NAME", "marius-media-zia")

# Max presigned URL lifetime this module ever issues. Only relevant for
# the brief window between generating a presigned URL and something
# actually fetching it in the same run (e.g. Agnes downloading an anchor
# image, or this pipeline re-downloading a clip for chain-extension) -
# NOT relevant to how long a key can sit in the database, since keys
# never expire.
PRESIGNED_URL_EXPIRY_SECONDS = 3600  # 1 hour - generous for any single run's own use of a URL it just requested

_client = None


def _get_client():
    global _client
    if _client is None:
        _client = boto3.client(
            "s3",
            endpoint_url=f"https://{B2_ENDPOINT_URL}",
            aws_access_key_id=B2_KEY_ID,
            aws_secret_access_key=B2_APPLICATION_KEY,
            config=Config(signature_version="s3v4"),
        )
    return _client


def upload_bytes(object_key, file_bytes, content_type="application/octet-stream"):
    """Uploads bytes to B2 under object_key. Returns object_key unchanged
    (the caller persists this key to Supabase - never a URL)."""
    client = _get_client()
    client.put_object(
        Bucket=B2_BUCKET_NAME,
        Key=object_key,
        Body=file_bytes,
        ContentType=content_type,
    )
    return object_key


def upload_file(object_key, local_path, content_type="application/octet-stream"):
    with open(local_path, "rb") as f:
        return upload_bytes(object_key, f.read(), content_type=content_type)


def presigned_url(object_key, expires_in=PRESIGNED_URL_EXPIRY_SECONDS):
    """Generates a fresh, short-lived presigned GET URL for object_key.
    Call this immediately before the URL is actually needed (e.g. right
    before passing it to Agnes, or right before this run downloads the
    object itself) - never store the result anywhere persistent."""
    client = _get_client()
    return client.generate_presigned_url(
        "get_object",
        Params={"Bucket": B2_BUCKET_NAME, "Key": object_key},
        ExpiresIn=expires_in,
    )


def download_to_file(object_key, local_path):
    """Downloads object_key directly to local_path via the B2 API (no
    presigned URL needed for this - boto3 downloads authenticated
    directly)."""
    client = _get_client()
    client.download_file(B2_BUCKET_NAME, object_key, local_path)
    return local_path


def object_exists(object_key):
    """Used by process_script's per-run clip re-verification step, in
    place of the old requests.head(url) check - confirms a previously
    uploaded shot's object is actually still present in B2, with no
    dependency on any URL or expiry."""
    client = _get_client()
    try:
        client.head_object(Bucket=B2_BUCKET_NAME, Key=object_key)
        return True
    except Exception:
        return False


def object_size(object_key):
    """ADDED (2026-09-02): returns the real byte size of object_key in B2,
    or None if it doesn't exist / can't be checked. Added specifically for
    verify_run_output.py, whose verify_video_generated_script() previously
    called requests.head() on scripts.video_url expecting a real https://
    URL with a Content-Length header - but video_url is now a bare B2
    object key (e.g. "abc123.mp4"), not a URL, so a plain HTTP HEAD on it
    would raise requests.exceptions.MissingSchema immediately and mark
    every single freshly-migrated video as "not verified" on every run.
    This gives the verifier a real size figure via the B2 API itself
    (head_object's ContentLength), the direct equivalent of what the old
    Content-Length HTTP header check was trying to confirm."""
    client = _get_client()
    try:
        resp = client.head_object(Bucket=B2_BUCKET_NAME, Key=object_key)
        return resp.get("ContentLength")
    except Exception:
        return None
