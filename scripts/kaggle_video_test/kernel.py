"""
Runs ON KAGGLE (free GPU). One-time TEST: can an open-source video model make a clip here?
Tries Wan 2.2 (5B) first, then LTX-Video. Writes test clip(s) + report.json to /kaggle/working.
Each model is loaded once with sequential CPU offload (lowest VRAM), then tried at a ladder of
sizes: original size first, smaller size only if that runs out of memory.
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

# Newer diffusers imports torchao.quantization.FqnToConfig (needs torchao >= 0.15) whenever
# torchao is installed. We do no quantization, so remove torchao entirely.
REPORT["torchao_before"] = run("pip show torchao | grep -i '^version'").stdout.strip() or "not installed"
u = run("pip uninstall -y torchao")
REPORT["torchao_uninstall_returncode"] = u.returncode
REPORT["versions"] = run("pip list 2>/dev/null | grep -iE '^(torch|diffusers|transformers|accelerate) '").stdout.strip()
REPORT["cpu_ram"] = run("free -g | head -2").stdout.strip()
save_report()

import torch  # noqa: E402
from diffusers.utils import export_to_video  # noqa: E402


def free():
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()


def try_model(name, load_fn, call_fn, rungs, out_name):
    """Load once, then try each (width, height, frames) rung until one makes a clip."""
    entry = {"model": name, "ok": False, "rungs": []}
    t0 = time.time()
    try:
        t = time.time()
        pipe = load_fn()
        entry["load_seconds"] = round(time.time() - t, 1)
    except Exception as e:
        entry["error"] = (type(e).__name__ + ": " + str(e))[:500]
        entry["trace"] = traceback.format_exc()[-1200:]
        entry["seconds_total"] = round(time.time() - t0, 1)
        REPORT["attempts"].append(entry)
        save_report()
        free()
        print(json.dumps(entry, indent=2))
        return
    for (w, h, f) in rungs:
        rung = {"width": w, "height": h, "frames": f, "ok": False}
        torch.cuda.reset_peak_memory_stats()
        try:
            t = time.time()
            frames = call_fn(pipe, w, h, f)
            rung["generate_seconds"] = round(time.time() - t, 1)
            path = os.path.join(OUT, out_name)
            export_to_video(frames, path, fps=24)
            rung["file"] = path
            rung["ok"] = True
            entry["ok"] = True
        except Exception as e:
            rung["error"] = (type(e).__name__ + ": " + str(e))[:400]
            rung["trace"] = traceback.format_exc()[-800:]
        rung["peak_vram_gb"] = round(torch.cuda.max_memory_allocated() / 1e9, 2)
        entry["rungs"].append(rung)
        REPORT["attempts"] = [a for a in REPORT["attempts"] if a.get("model") != name] + [entry]
        save_report()
        free()
        if rung["ok"]:
            break
    entry["seconds_total"] = round(time.time() - t0, 1)
    REPORT["attempts"] = [a for a in REPORT["attempts"] if a.get("model") != name] + [entry]
    save_report()
    print(json.dumps(entry, indent=2))
    del pipe
    free()


def load_wan():
    from diffusers import AutoencoderKLWan, WanPipeline
    model = "Wan-AI/Wan2.2-TI2V-5B-Diffusers"
    vae = AutoencoderKLWan.from_pretrained(model, subfolder="vae", torch_dtype=torch.float32)
    pipe = WanPipeline.from_pretrained(model, vae=vae, torch_dtype=torch.bfloat16)
    try:
        pipe.vae.enable_tiling()
    except Exception as e:
        print("vae tiling not available:", e)
    pipe.enable_sequential_cpu_offload()  # do NOT move the pipe to cuda first
    return pipe


def call_wan(pipe, w, h, f):
    return pipe(prompt=PROMPT, negative_prompt=NEGATIVE, height=h, width=w,
                num_frames=f, guidance_scale=5.0, num_inference_steps=20).frames[0]


def load_ltx():
    from diffusers import LTXPipeline
    pipe = LTXPipeline.from_pretrained("Lightricks/LTX-Video", torch_dtype=torch.bfloat16)
    try:
        pipe.vae.enable_tiling()
    except Exception as e:
        print("vae tiling not available:", e)
    pipe.enable_sequential_cpu_offload()  # do NOT move the pipe to cuda first
    return pipe


def call_ltx(pipe, w, h, f):
    return pipe(prompt=PROMPT, negative_prompt=NEGATIVE, width=w, height=h,
                num_frames=f, num_inference_steps=30).frames[0]


# (width, height, frames): original size first, smaller fallback second
try_model("Wan2.2-TI2V-5B", load_wan, call_wan,
          [(832, 480, 49), (640, 352, 33)], "test_wan22_5b.mp4")
try_model("LTX-Video", load_ltx, call_ltx,
          [(704, 480, 97), (512, 320, 49)], "test_ltx_video.mp4")

REPORT["finished"] = time.strftime("%Y-%m-%d %H:%M:%S")
save_report()
print("DONE")
