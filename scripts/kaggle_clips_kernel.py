"""
Runs ON KAGGLE (free GPU). Marius shot-clip generator (2026-11-10, rev 2).

The GitHub runner (scripts/kaggle_clips.py) bakes the shot jobs into MANIFEST (base64).
This notebook makes each shot with LTX-Video 2B distilled: the first piece of a shot is
text-to-video, longer shots continue picture-to-video from the previous piece's last frame.
It writes shot_NNN.mp4 plus manifest_out.json into /kaggle/working.
Silent video only: narration, music and sound effects are added later by Marius's own assembly.
Model loading follows scripts/kaggle_video_test/kernel.py.
"""
import os
import gc
import json
import math
import time
import base64
import inspect
import traceback
import subprocess

OUT = "/kaggle/working"
MANIFEST = json.loads(base64.b64decode("__MANIFEST_B64__").decode("utf-8"))
T0 = time.time()
BUDGET_SEC = int(MANIFEST.get("budget_minutes", 420)) * 60
W, H, STEPS, FPS = 704, 480, 8, 24
MAX_SEG_FRAMES = 97
MAX_PROMPT_TOKENS = 256
CKPTS = [
    "https://huggingface.co/Lightricks/LTX-Video/ltxv-2b-0.9.8-distilled.safetensors",
    "https://huggingface.co/Lightricks/LTX-Video/blob/main/ltxv-2b-0.9.8-distilled.safetensors",
]
BASE_REPO = "Lightricks/LTX-Video"

RESULT = {
    "script_id": MANIFEST["script_id"],
    "start_index": MANIFEST["start_index"],
    "done": [],
    "clip_seconds": {},
    "errors": [],
    "started": time.strftime("%Y-%m-%d %H:%M:%S"),
    "finished": None,
    "stopped_because": None,
}


def save():
    with open(os.path.join(OUT, "manifest_out.json"), "w") as f:
        json.dump(RESULT, f, indent=2)


def run(cmd):
    return subprocess.run(cmd, shell=True, capture_output=True, text=True)


save()
RESULT["gpu"] = run("nvidia-smi --query-gpu=name,memory.total --format=csv,noheader").stdout.strip()
r = run("pip install -q -U diffusers transformers accelerate ftfy imageio imageio-ffmpeg sentencepiece protobuf pillow")
RESULT["pip_returncode"] = r.returncode
run("pip uninstall -y torchao")
save()

import torch  # noqa: E402
from diffusers import LTXPipeline, LTXImageToVideoPipeline  # noqa: E402
from diffusers import LTXVideoTransformer3DModel, AutoencoderKLLTXVideo  # noqa: E402
from diffusers.utils import export_to_video  # noqa: E402


def free():
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()


def load():
    for ckpt in CKPTS:
        try:
            tr = LTXVideoTransformer3DModel.from_single_file(ckpt, torch_dtype=torch.bfloat16)
            vae = AutoencoderKLLTXVideo.from_single_file(ckpt, torch_dtype=torch.bfloat16)
            pipe = LTXPipeline.from_pretrained(BASE_REPO, transformer=tr, vae=vae, torch_dtype=torch.bfloat16)
            try:
                pipe.vae.enable_tiling()
            except Exception:
                pass
            pipe.enable_sequential_cpu_offload()
            return pipe
        except Exception as e:
            RESULT["errors"].append("load failed (" + ckpt[-40:] + "): " + (type(e).__name__ + ": " + str(e))[:400])
            save()
            free()
    return None


def call(pipe, prompt, seed, frames, image=None):
    # the picture-to-video pipeline draws its noise on the GPU, so its generator must be on cuda
    if image is not None:
        gen = torch.Generator("cuda").manual_seed(seed)
    else:
        gen = torch.Generator().manual_seed(seed)
    kw = dict(prompt=prompt, width=W, height=H, num_frames=frames, num_inference_steps=STEPS,
              guidance_scale=1.0, decode_timestep=0.05, decode_noise_scale=0.025, generator=gen,
              max_sequence_length=MAX_PROMPT_TOKENS)
    if image is not None:
        kw["image"] = image
        kw["image_cond_noise_scale"] = 0.025
    allowed = set(inspect.signature(pipe.__call__).parameters)
    kw = {k: v for k, v in kw.items() if k in allowed}
    return pipe(**kw).frames[0]


def seg_frames(remaining):
    # LTX needs 8*k+1 frames
    n = 8 * math.ceil((max(remaining, 2) - 1) / 8) + 1
    return max(25, min(MAX_SEG_FRAMES, n))


def make_shot(pipe, i2v, job, attempt):
    need = max(25, int(round(job["duration"] * FPS)) + 1)
    frames = []
    for k, prompt in enumerate(job["prompts"]):
        have = len(frames)
        if have >= need:
            break
        remaining = need - have + (1 if k > 0 else 0)
        nf = seg_frames(remaining)
        seed = int(job["seed"]) + 101 * k + 7919 * attempt
        if k == 0:
            piece = call(pipe, prompt, seed, nf)
        else:
            if i2v is None:
                raise RuntimeError("picture-to-video pipeline not available for the continuation piece")
            piece = call(i2v, prompt, seed, nf, image=frames[-1])
            piece = piece[1:]
        frames.extend(piece)
        free()
    if not frames:
        raise RuntimeError("no frames produced")
    return frames[:need]


pipe = load()
if pipe is None:
    RESULT["stopped_because"] = "model load failed"
else:
    i2v = None
    try:
        i2v = LTXImageToVideoPipeline(**pipe.components)
    except Exception as e:
        RESULT["errors"].append("i2v setup failed: " + (type(e).__name__ + ": " + str(e))[:300])
    save()

    for job in MANIFEST["jobs"]:
        if time.time() - T0 > BUDGET_SEC:
            RESULT["stopped_because"] = "time budget reached"
            break
        idx = job["index"]
        ok = False
        for attempt in range(2):
            try:
                t = time.time()
                frames = make_shot(pipe, i2v, job, attempt)
                path = os.path.join(OUT, "shot_%03d.mp4" % idx)
                export_to_video(frames, path, fps=FPS)
                RESULT["done"].append(idx)
                RESULT["clip_seconds"][str(idx)] = round(len(frames) / FPS, 2)
                print("shot", idx, "done in", round(time.time() - t, 1), "s")
                ok = True
                save()
                break
            except Exception as e:
                RESULT["errors"].append("shot %s attempt %s: %s" % (idx, attempt + 1, (type(e).__name__ + ": " + str(e))[:300]))
                RESULT["errors"].append(traceback.format_exc()[-500:])
                free()
                save()
        if not ok:
            RESULT["stopped_because"] = "shot %s failed twice" % idx
            break
    if RESULT["stopped_because"] is None:
        RESULT["stopped_because"] = "batch finished"

RESULT["finished"] = time.strftime("%Y-%m-%d %H:%M:%S")
save()
print("DONE", RESULT["stopped_because"])
