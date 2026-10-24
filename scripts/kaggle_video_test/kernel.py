"""
Runs ON KAGGLE (free GPU). TEST 2 (2026-10-24): LTX-Video 2B 0.9.6-DISTILLED.
Goal: measure real speed/quality of the fast distilled model (8 steps, no guidance) and test
image-to-video chaining (continue a clip from its last frame). Writes clips + report.json.
Nothing here touches Marius, Supabase or Backblaze.
"""
import os
import gc
import json
import time
import traceback
import subprocess

OUT = "/kaggle/working"
REPORT = {"started": time.strftime("%Y-%m-%d %H:%M:%S"), "test": "ltx-2b-0.9.6-distilled", "steps": []}

CKPT = "https://huggingface.co/Lightricks/LTX-Video/ltxv-2b-0.9.6-distilled-04-25.safetensors"
BASE_REPO = "Lightricks/LTX-Video"
W, H, FRAMES, STEPS, FPS = 704, 480, 97, 8, 24

PROMPTS = [
    ("harbour", "A small wooden pilot boat moving slowly through calm harbour water at dawn, light fog over the stone quay, "
                "vivid saturated color, warm golden light, cinematic, sharp detail, slow camera push-in"),
    ("market", "Medieval market square at midday, merchants and townspeople walking and trading between stalls, "
               "rich saturated colors, natural sunlight, shallow depth of field, cinematic, camera follows slowly"),
    ("craftsman", "Close-up of an old craftsman's hands carving a wooden figure in a workshop, warm lamplight, "
                  "wood shavings falling, vivid saturated color, shallow depth of field, cinematic"),
]
CHAIN_PROMPT = ("The pilot boat keeps gliding forward as the fog slowly lifts, same harbour, "
                "vivid saturated color, warm golden light, cinematic")


def save():
    with open(os.path.join(OUT, "report.json"), "w") as f:
        json.dump(REPORT, f, indent=2)


def run(cmd):
    return subprocess.run(cmd, shell=True, capture_output=True, text=True)


def log(step):
    REPORT["steps"].append(step)
    save()
    print(json.dumps(step, indent=2))


REPORT["gpu"] = run("nvidia-smi --query-gpu=name,memory.total --format=csv,noheader").stdout.strip()
r = run("pip install -q -U diffusers transformers accelerate ftfy imageio imageio-ffmpeg sentencepiece protobuf")
REPORT["pip_returncode"] = r.returncode
run("pip uninstall -y torchao")
REPORT["versions"] = run("pip list 2>/dev/null | grep -iE '^(torch|diffusers|transformers|accelerate) '").stdout.strip()
save()

import torch  # noqa: E402
from diffusers import LTXPipeline, LTXImageToVideoPipeline  # noqa: E402
from diffusers.utils import export_to_video  # noqa: E402


def free():
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()


def load(mode):
    """Two loading routes (A: full single file, B: transformer+vae from single file, rest from base repo)."""
    t = time.time()
    pipe, how, errs = None, None, []
    try:
        pipe = LTXPipeline.from_single_file(CKPT, torch_dtype=torch.bfloat16)
        how = "A: LTXPipeline.from_single_file"
    except Exception as e:
        errs.append("A failed: " + (type(e).__name__ + ": " + str(e))[:400])
        try:
            from diffusers import LTXVideoTransformer3DModel, AutoencoderKLLTXVideo
            tr = LTXVideoTransformer3DModel.from_single_file(CKPT, torch_dtype=torch.bfloat16)
            vae = AutoencoderKLLTXVideo.from_single_file(CKPT, torch_dtype=torch.bfloat16)
            pipe = LTXPipeline.from_pretrained(BASE_REPO, transformer=tr, vae=vae, torch_dtype=torch.bfloat16)
            how = "B: transformer+vae single file, rest from base repo"
        except Exception as e2:
            errs.append("B failed: " + (type(e2).__name__ + ": " + str(e2))[:400])
            errs.append(traceback.format_exc()[-800:])
    if pipe is None:
        log({"step": "load", "mode": mode, "ok": False, "errors": errs})
        return None
    try:
        pipe.vae.enable_tiling()
    except Exception:
        pass
    if mode == "model":
        pipe.enable_model_cpu_offload()
    else:
        pipe.enable_sequential_cpu_offload()
    log({"step": "load", "mode": mode, "ok": True, "how": how, "seconds": round(time.time() - t, 1), "errors": errs})
    return pipe


def gen(pipe, prompt, seed, image=None):
    kw = dict(prompt=prompt, width=W, height=H, num_frames=FRAMES, num_inference_steps=STEPS,
              guidance_scale=1.0, generator=torch.Generator().manual_seed(seed))
    if image is not None:
        kw["image"] = image
        kw["image_cond_noise_scale"] = 0.025
    try:
        return pipe(decode_timestep=0.05, decode_noise_scale=0.025, **kw).frames[0]
    except TypeError:
        return pipe(**kw).frames[0]


def timed(name, pipe, prompt, seed, image=None):
    step = {"step": name, "ok": False}
    torch.cuda.reset_peak_memory_stats()
    t = time.time()
    try:
        frames = gen(pipe, prompt, seed, image)
        step["generate_seconds"] = round(time.time() - t, 1)
        path = os.path.join(OUT, f"ltxd_{name}.mp4")
        export_to_video(frames, path, fps=FPS)
        step["file"] = path
        step["clip_seconds"] = round(len(frames) / FPS, 2)
        step["ok"] = True
        step["peak_vram_gb"] = round(torch.cuda.max_memory_allocated() / 1e9, 2)
        log(step)
        return frames
    except Exception as e:
        step["error"] = (type(e).__name__ + ": " + str(e))[:400]
        step["trace"] = traceback.format_exc()[-800:]
        log(step)
        free()
        return None


pipe, first_frames = None, None
for mode in ("model", "sequential"):
    pipe = load(mode)
    if pipe is None:
        break
    first_frames = timed(f"{PROMPTS[0][0]}_{mode}", pipe, PROMPTS[0][1], 1)
    if first_frames is not None:
        break
    del pipe
    pipe = None
    free()

if pipe is not None and first_frames is not None:
    for i, (name, prompt) in enumerate(PROMPTS[1:], start=2):
        timed(name, pipe, prompt, i)
    try:
        i2v = LTXImageToVideoPipeline(**pipe.components)
        timed("chain_from_harbour", i2v, CHAIN_PROMPT, 9, image=first_frames[-1])
    except Exception as e:
        log({"step": "chain_setup", "ok": False, "error": (type(e).__name__ + ": " + str(e))[:400],
             "trace": traceback.format_exc()[-800:]})

REPORT["finished"] = time.strftime("%Y-%m-%d %H:%M:%S")
save()
print("DONE")
