"""
Marius Command Center - B2 preflight (2026-09-19)

WHY THIS EXISTS: Video Generation only touches B2 AFTER spending 15-20
minutes of Agnes generation per shot (more with chain-extension). When B2
uploads were failing with SSLEOFError 4/4, every run burned its whole
60-minute budget generating clips that were then thrown away at upload
time. This script probes B2 up front, in seconds, so a broken B2
connection is caught BEFORE any Agnes credits are spent.

Two probes, on purpose: a tiny payload and an ~8 MB payload (about the
size of a real clip). If the tiny one passes and the large one fails, the
problem is payload-size dependent (not just a dead connection) - that is
printed explicitly so the next diagnosis does not have to guess.

Uses storage_b2.upload_bytes, i.e. the exact same code path (including the
fresh-client-per-retry fix, commit 4a989ea) that real uploads use. Also
prints boto3/botocore versions, which matter for S3-compatible endpoints.

Exit code 1 on any failed probe. The workflow step is continue-on-error,
so this does NOT turn the run red or open a failure issue - it just skips
the generation step and leaves a ::error:: annotation on the run.
"""

import os
import sys
import time

import boto3
import botocore

import storage_b2

PROBE_KEY = "_preflight/b2_probe.bin"
PROBES = [
    ("small", 64 * 1024),
    ("large", 8 * 1024 * 1024),
]


def probe(label, n_bytes):
    payload = os.urandom(n_bytes)
    start = time.time()
    try:
        storage_b2.upload_bytes(PROBE_KEY, payload, content_type="application/octet-stream")
    except Exception as e:
        print(f"::error::B2 preflight FAILED ({label}, {n_bytes} bytes) after {time.time() - start:.1f}s: {e}")
        return False
    print(f"B2 preflight OK ({label}, {n_bytes} bytes) in {time.time() - start:.1f}s")
    return True


def main():
    print(f"B2 preflight: boto3 {boto3.__version__}, botocore {botocore.__version__}")
    results = {label: probe(label, n) for label, n in PROBES}
    storage_b2.delete_object(PROBE_KEY)  # idempotent; non-fatal on failure

    if all(results.values()):
        print("B2 preflight passed - safe to spend Agnes credits.")
        return

    if results["small"] and not results["large"]:
        print("::error::B2 preflight: small upload OK but large upload FAILED - failure is payload-size dependent, not just a stale connection.")
    elif not results["small"] and not results["large"]:
        print("::error::B2 preflight: ALL probes failed - endpoint/TLS/credentials level problem, not size related.")
    print("Skipping video generation this run so no Agnes credits are spent on clips that cannot be uploaded.")
    sys.exit(1)


if __name__ == "__main__":
    main()
