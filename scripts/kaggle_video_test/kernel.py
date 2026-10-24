"""
Runs ON KAGGLE (free GPU). TEST 3 (2026-10-24): LTX-Video 2B 0.9.8-DISTILLED (newer than 0.9.6).
Same prompts style as test 2 plus a face close-up and a no-people landscape, sequential offload
(model offload ran out of memory last time). Also fixes the image-to-video chain test.
Nothing here touches Marius, Supabase or Backblaze.
"""
import os
import gc
import json
import time
import inspect
import traceback
import subprocess

OUT = "/kaggle/working"
REPORT = {"started": time.strftime("%Y-%m-%d %H:%M:%S"), "test": "ltx-2b-0.9.8-distilled", "steps": []}

CKPT = "https://huggingface.co/Lightricks/LTX-Video/ltxv-2b-0.9.8-distilled.safetensors"
BASE_REPO = "Lightricks/LTX-Video"
W, H, FRAMES, STEPS, FPS = 704, 480, 97, 8, 24

PROMPTS = [
    ("craftsman", "Close-up of an old craftsman's hands carving a wooden figure in a workshop, warm lamplight, "
                  "wood shavings falling, vivid saturated color, shallow depth of field, cinematic"),
    ("market", "Medieval market square at midday, merchants and townspeople walking and trading between stalls, "
               "rich saturated colors, natural sunlight, shallow depth of field, cinematic, camera follows slowly"),
    ("fisherman_face", "Close-up portrait of a weathered elderly fisherman with a grey beard, wind in his hair, "
                       "looking out to sea, clear detailed face, natural daylight, vivid saturated color, cinematic"),
    ("harbour", "A small wooden pilot boat moving slowly through calm harbour water at dawn, light fog over the stone quay, "
                "vivid saturated color, warm golden light, cinematic, sharp detail, slow camera push-in"),
    ("valley", "Wide aerial shot of a green mountain valley at sunrise, a river winding through it, light mist, "
               "vivid saturated color, golden light, cinematic, slow camera drift forward"),
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


def load():
    t = time.time()
    try:
        from diffusers import LTXVideoTransformer3DModel, AutoencoderKLLTXVideo
        tr = LTXVideoTransformer3DModel.from_single_file(CKPT, torch_dtype=torch.bfloat16)
        vae = AutoencoderKLLTXVideo.from_single_file(CKPT, torch_dtype=torch.bfloat16)
        pipe = LTXPipeline.from_pretrained(BASE_REPO, transformer=tr, vae=vae, torch_dtype=torch.bfloat16)
        try:
            pipe.vae.enable_tiling()
        except Exception:
            pass
        pipe.enable_sequential_cpu_offload()
        log({"step": "load", "ok": True, "seconds": round(time.time() - t, 1)})
        return pipe
    except Exception as e:
        log({"step": "load", "ok": False, "error": (type(e).__name__ + ": " + str(e))[:500],
             "trace": traceback.format_exc()[-900:]})
        return None


def call(pipe, prompt, seed, image=None):
    kw = dict(prompt=prompt, width=W, height=H, num_frames=FRAMES, num_inference_steps=STEPS,
              guidance_scale=1.0, decode_timestep=0.05, decode_noise_scale=0.025,
              generator=torch.Generator().manual_seed(seed))
    if image is not None:
        kw["image"] = image
        kw["image_cond_noise_scale"] = 0.025
    allowed = set(inspect.signature(pipe.__call__).parameters)
    dropped = [k for k in kw if k not in allowed]
    kw = {k: v for k, v in kw.items() if k in allowed}
    return pipe(**kw).frames[0], dropped


def timed(name, pipe, prompt, seed, image=None):
    step = {"step": name, "ok": False}
    torch.cuda.reset_peak_memory_stats()
    t = time.time()
    try:
        frames, dropped = call(pipe, prompt, seed, image)
        step["generate_seconds"] = round(time.time() - t, 1)
        path = os.path.join(OUT, f"ltx098_{name}.mp4")
        export_to_video(frames, path, fps=FPS)
        step["file"] = path
        step["clip_seconds"] = round(len(frames) / FPS, 2)
        step["ok"] = True
        step["dropped_args"] = dropped
        step["peak_vram_gb"] = round(torch.cuda.max_memory_allocated() / 1e9, 2)
        log(step)
        return frames
    except Exception as e:
        step["error"] = (type(e).__name__ + ": " + str(e))[:400]
        step["trace"] = traceback.format_exc()[-800:]
        log(step)
        free()
        return None


pipe = load()
if pipe is not None:
    harbour = None
    for i, (name, prompt) in enumerate(PROMPTS, start=1):
        frames = timed(name, pipe, prompt, i)
        if name == "harbour":
            harbour = frames
    if harbour is not None:
        try:
            i2v = LTXImageToVideoPipeline(**pipe.components)
            timed("chain_from_harbour", i2v, CHAIN_PROMPT, 9, image=harbour[-1])
        except Exception as e:
            log({"step": "chain_setup", "ok": False, "error": (type(e).__name__ + ": " + str(e))[:400],
                 "trace": traceback.format_exc()[-800:]})

REPORT["finished"] = time.strftime("%Y-%m-%d %H:%M:%S")
save()
print("DONE")
