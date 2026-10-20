"""
Runs ON KAGGLE (free GPU). One-time TEST: can an open-source video model make a clip here?
Tries Wan 2.2 (5B) first, then LTX-Video. Writes test clip(s) + report.json to /kaggle/working.
Nothing here touches Marius, Supabase or Backblaze.
"""
import os
import sys
import gc
import json
import time
import traceback
import subprocess

OUT = "/kaggle/working"
REPORT = {"started": time.strftime("%Y-%m-%d %H:%M:%S"), "gpu": None, "attempts": []}
PROMPT = ("A grey 1942 harbour at dawn, a small wooden pilot boat moving slowly through calm water, "
          "fog over the quay, period accurate, natural light, cinematic documentary look, no text")
NEGATIVE = "text, watermark, modern objects, cars, drones, blurry, distorted, extra limbs"


def save_report():
    with open(os.path.join(OUT, "report.json"), "w") as f:
        json.dump(REPORT, f, indent=2)


def run(cmd):
    return subprocess.run(cmd, shell=True, capture_output=True, text=True)


REPORT["gpu"] = run("nvidia-smi --query-gpu=name,memory.total --format=csv,noheader").stdout.strip()
print("GPU:", REPORT["gpu"])
save_report()

r = run("pip install -q -U diffusers transformers accelerate ftfy imageio imageio-ffmpeg sentencepiece protobuf")
REPORT["pip_returncode"] = r.returncode
if r.returncode != 0:
    REPORT["pip_error"] = r.stderr[-800:]
save_report()

import torch  # noqa: E402
from diffusers.utils import export_to_video  # noqa: E402


def free():
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()


def attempt(name, fn):
    t0 = time.time()
    entry = {"model": name, "ok": False}
    try:
        info = fn()
        entry.update(info)
        entry["ok"] = True
    except Exception as e:
        entry["error"] = (type(e).__name__ + ": " + str(e))[:500]
        entry["trace"] = traceback.format_exc()[-1200:]
    entry["seconds_total"] = round(time.time() - t0, 1)
    if torch.cuda.is_available():
        entry["peak_vram_gb"] = round(torch.cuda.max_memory_allocated() / 1e9, 2)
    REPORT["attempts"].append(entry)
    save_report()
    free()
    print(json.dumps(entry, indent=2))


def wan():
    from diffusers import AutoencoderKLWan, WanPipeline
    model = "Wan-AI/Wan2.2-TI2V-5B-Diffusers"
    t = time.time()
    vae = AutoencoderKLWan.from_pretrained(model, subfolder="vae", torch_dtype=torch.float32)
    pipe = WanPipeline.from_pretrained(model, vae=vae, torch_dtype=torch.bfloat16)
    pipe.enable_model_cpu_offload()
    load_s = round(time.time() - t, 1)
    t = time.time()
    frames = pipe(prompt=PROMPT, negative_prompt=NEGATIVE, height=480, width=832,
                  num_frames=49, guidance_scale=5.0, num_inference_steps=20).frames[0]
    gen_s = round(time.time() - t, 1)
    path = os.path.join(OUT, "test_wan22_5b.mp4")
    export_to_video(frames, path, fps=24)
    return {"file": path, "load_seconds": load_s, "generate_seconds": gen_s,
            "clip": "832x480, 49 frames (~2 s)"}


def ltx():
    from diffusers import LTXPipeline
    t = time.time()
    pipe = LTXPipeline.from_pretrained("Lightricks/LTX-Video", torch_dtype=torch.bfloat16)
    pipe.enable_model_cpu_offload()
    load_s = round(time.time() - t, 1)
    t = time.time()
    frames = pipe(prompt=PROMPT, negative_prompt=NEGATIVE, width=704, height=480,
                  num_frames=97, num_inference_steps=30).frames[0]
    gen_s = round(time.time() - t, 1)
    path = os.path.join(OUT, "test_ltx_video.mp4")
    export_to_video(frames, path, fps=24)
    return {"file": path, "load_seconds": load_s, "generate_seconds": gen_s,
            "clip": "704x480, 97 frames (~4 s)"}


attempt("Wan2.2-TI2V-5B", wan)
attempt("LTX-Video", ltx)

REPORT["finished"] = time.strftime("%Y-%m-%d %H:%M:%S")
save_report()
print("DONE")
