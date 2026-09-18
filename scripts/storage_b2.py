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

CREDENTIAL WHITESPACE FIX (2026-09-14) - CONFIRMED live: a video_generation
run failed every single upload with botocore raising "Invalid header
value" on the Authorization header, showing a literal embedded newline
right after "Credential=" in the printed AWS4-HMAC-SHA256 string. HTTP
header values cannot contain a raw \n - this is not a code logic bug, it's
a trailing newline that ended up inside the B2_KEY_ID (or possibly
B2_APPLICATION_KEY/B2_ENDPOINT_URL) GitHub Actions secret itself, most
likely from how the value was originally pasted in when the secret was
created. All three env vars were being read completely raw with no
normalization at all. Since a secret's stored value can't be fixed from
here, and a stray trailing newline in a pasted credential is an extremely
common, easy-to-reintroduce mistake, defensively .strip()'d all three at
the point they're read - this is a permanent, safe fix regardless of
whether the underlying secret is ever cleaned up, and costs nothing if
the values were already clean.

UPLOAD SSL-DROP RETRY FIX (2026-09-18) - CONFIRMED live: with the header
bug above actually fixed (secret re-pasted clean), uploads started
failing instead with botocore.exceptions.SSLError /
ssl.SSLEOFError("EOF occurred in violation of protocol") mid-upload to
the B2 endpoint - a dropped connection, not a credential or logic
problem. boto3's own default retry handling (legacy mode, 3 attempts)
already ran and still surfaced this, so it's not simply under-retried at
the botocore layer for this particular exception type. upload_bytes now
wraps put_object in its own explicit retry loop (same pattern already
used elsewhere in this pipeline - see CLIP_VERIFY_RETRIES in
video_generation.py and the Agnes poll retry in agnes_client.py) so a
single dropped TLS connection during a large video upload no longer
kills the entire script's run.

STALE-CONNECTION RETRY FIX (2026-09-19) - CONFIRMED live: the retry loop
added above was still producing 4/4 identical SSLEOFErrors on the same
shot across multiple scripts. Root cause: the module-level `_client`
singleton was being reused across every retry attempt, so when the
underlying TLS connection itself had already died (not just one HTTP
request), every retry reused the same dead pooled connection out of
boto3/urllib3's connection pool and reproduced the exact same failure
every time - a well-known boto3/urllib3 pattern. A dead keep-alive
connection needs a brand-new client (fresh TCP+TLS connection), not just
a retried request on the same one. upload_bytes now forces a new client
on every retry attempt (attempt > 0) instead of reusing the cached
singleton, while normal (non-retry, non-upload) callers still get the
cheap cached client via _get_client().
"""

import time
import os
import boto3
from botocore.client import Config
from botocore.exceptions import BotoCoreError, ClientError

# CREDENTIAL WHITESPACE FIX (2026-09-14): see module docstring. .strip()
# defends against a stray leading/trailing newline or space in any of
# these three GitHub Actions secrets - a raw newline here breaks the AWS
# SigV4 Authorization header (HTTP headers cannot contain \n), causing
# every single upload/request to fail with an opaque
# "Invalid header value" error that has nothing to do with the actual
# credentials being wrong.
B2_ENDPOINT_URL = os.environ["B2_ENDPOINT_URL"].strip()
B2_KEY_ID = os.environ["B2_KEY_ID"].strip()
B2_APPLICATION_KEY = os.environ["B2_APPLICATION_KEY"].strip()
B2_BUCKET_NAME = os.environ.get("B2_BUCKET_NAME", "marius-media-zia").strip()

# Max presigned URL lifetime this module ever issues. Only relevant for
# the brief window between generating a presigned URL and something
# actually fetching it in the same run (e.g. Agnes downloading an anchor
# image, or this pipeline re-downloading a clip for chain-extension) -
# NOT relevant to how long a key can sit in the database, since keys
# never expire.
PRESIGNED_URL_EXPIRY_SECONDS = 3600  # 1 hour - generous for any single run's own use of a URL it just requested

# UPLOAD SSL-DROP RETRY FIX (2026-09-18): see module docstring.
UPLOAD_MAX_RETRIES = 4
UPLOAD_RETRY_WAIT_SECONDS = 8

_client = None


def _new_client():
    """Builds a brand-new boto3 S3 client (fresh TCP+TLS connection,
    fresh connection pool) rather than reusing any cached one. Used by
    upload_bytes on retry attempts - see STALE-CONNECTION RETRY FIX."""
    return boto3.client(
        "s3",
        endpoint_url=f"https://{B2_ENDPOINT_URL}",
        aws_access_key_id=B2_KEY_ID,
        aws_secret_access_key=B2_APPLICATION_KEY,
        config=Config(signature_version="s3v4"),
    )


def _get_client():
    global _client
    if _client is None:
        _client = _new_client()
    return _client


def upload_bytes(object_key, file_bytes, content_type="application/octet-stream"):
    """Uploads bytes to B2 under object_key. Returns object_key unchanged
    (the caller persists this key to Supabase - never a URL).

    UPLOAD SSL-DROP RETRY FIX (2026-09-18): retries on a dropped
    connection / SSL error during the upload itself, instead of letting a
    single bad connection kill the whole run (see module docstring).

    STALE-CONNECTION RETRY FIX (2026-09-19): every retry attempt after
    the first uses a brand-new client instead of the cached singleton,
    since a dead keep-alive TLS connection reproduces the identical
    SSLEOFError if it's simply reused (see module docstring)."""
    last_error = None
    for attempt in range(UPLOAD_MAX_RETRIES):
        client = _get_client() if attempt == 0 else _new_client()
        try:
            client.put_object(
                Bucket=B2_BUCKET_NAME,
                Key=object_key,
                Body=file_bytes,
                ContentType=content_type,
            )
            return object_key
        except (BotoCoreError, ClientError, OSError) as e:
            last_error = e
            wait = UPLOAD_RETRY_WAIT_SECONDS * (attempt + 1)
            print(f"B2 upload error for {object_key!r} (attempt {attempt + 1}/{UPLOAD_MAX_RETRIES}): {e}")
            if attempt < UPLOAD_MAX_RETRIES - 1:
                print(f"Retrying upload in {wait}s with a fresh connection...")
                time.sleep(wait)
    raise RuntimeError(f"B2 upload failed after {UPLOAD_MAX_RETRIES} attempts for {object_key!r}: {last_error}")


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


def delete_object(object_key):
    """ADDED (2026-09-10): deletes object_key from B2. Used for post-
    upload cleanup - once a video is confirmed live on YouTube, its
    source file no longer needs to sit in B2 storage. Safe to call on a
    key that's already gone (B2's delete_object is idempotent - no error
    on a missing key). Returns True if the call completed, False if it
    raised (logged, never fatal - a failed cleanup should never affect
    upload status, which is already recorded by the time this runs)."""
    client = _get_client()
    try:
        client.delete_object(Bucket=B2_BUCKET_NAME, Key=object_key)
        return True
    except Exception as e:
        print(f"B2 cleanup failed for {object_key!r} (non-fatal): {e}")
        return False
