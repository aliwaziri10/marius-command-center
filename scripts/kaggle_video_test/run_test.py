"""
Runs in GitHub Actions. Pushes scripts/kaggle_video_test/kernel.py to Kaggle as a private
GPU notebook, waits for it, downloads the result (test clips + report.json) into ./kaggle_out.
Needs env KAGGLE_USERNAME and (KAGGLE_KEY or KAGGLE_API_TOKEN). Test only: nothing in the
Marius pipeline is touched.
"""
import os
import sys
import json
import time
import shutil
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
SLUG = "marius-video-test"
MAX_WAIT_MIN = int(os.environ.get("KAGGLE_TEST_MAX_MINUTES", "120"))


def sh(cmd, check=False):
    p = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    out = (p.stdout or "") + (p.stderr or "")
    print(f"$ {cmd}\n{out.strip()}\n")
    if check and p.returncode != 0:
        sys.exit(f"command failed: {cmd}")
    return p.returncode, out


def main():
    user = os.environ.get("KAGGLE_USERNAME", "").strip()
    if not user:
        sys.exit("KAGGLE_USERNAME is missing. Add it as a repository secret.")
    if not (os.environ.get("KAGGLE_KEY") or os.environ.get("KAGGLE_API_TOKEN")):
        sys.exit("Neither KAGGLE_KEY nor KAGGLE_API_TOKEN is set. Add the Kaggle key as a repository secret.")

    work = os.path.join(HERE, "_push")
    shutil.rmtree(work, ignore_errors=True)
    os.makedirs(work)
    shutil.copy(os.path.join(HERE, "kernel.py"), os.path.join(work, "kernel.py"))
    meta = {
        "id": f"{user}/{SLUG}",
        "title": SLUG,
        "code_file": "kernel.py",
        "language": "python",
        "kernel_type": "script",
        "is_private": "true",
        "enable_gpu": "true",
        "enable_internet": "true",
        "dataset_sources": [],
        "competition_sources": [],
        "kernel_sources": [],
    }
    with open(os.path.join(work, "kernel-metadata.json"), "w") as f:
        json.dump(meta, f, indent=2)

    sh("kaggle --version")
    code, out = sh(f"kaggle kernels push -p {work}")
    if code != 0 or "error" in out.lower():
        sys.exit("Kaggle refused the push (see output above). Common causes: wrong username, bad key, "
                 "or the Kaggle account is not phone-verified (needed for GPU + internet).")

    ref = f"{user}/{SLUG}"
    deadline = time.time() + MAX_WAIT_MIN * 60
    status = ""
    while time.time() < deadline:
        time.sleep(60)
        _, out = sh(f"kaggle kernels status {ref}")
        low = out.lower()
        if "complete" in low:
            status = "complete"
            break
        if "error" in low or "cancel" in low or "failed" in low:
            status = "error"
            break
    print("FINAL STATUS:", status or "timeout")

    out_dir = os.path.join(os.getcwd(), "kaggle_out")
    shutil.rmtree(out_dir, ignore_errors=True)
    os.makedirs(out_dir)
    sh(f"kaggle kernels output {ref} -p {out_dir}")
    rp = os.path.join(out_dir, "report.json")
    if os.path.exists(rp):
        print("REPORT:\n" + open(rp).read())
    clips = [x for x in os.listdir(out_dir) if x.endswith(".mp4")]
    print("CLIPS:", clips or "none")
    if not clips:
        sys.exit("No test clip came back. Read the report/log above.")


if __name__ == "__main__":
    main()
