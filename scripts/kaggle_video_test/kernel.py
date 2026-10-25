"""
Runs ON KAGGLE (free GPU). TEST 4 (2026-10-25): Mimsi the snail, LTX-Video 2B 0.9.8-DISTILLED.
- Fixes the picture-to-video crash from test 3 (generator must live on cuda when an image is given).
- Starts clips from Mimsi's real reference picture (public link from SHOW_BIBLE.md).
- Adds sound (music + effects made by ffmpeg, same recipe as upgraded-journey assembly/sound.py)
  on top of each clip, because the model makes silent video only.
Nothing here touches Marius, Supabase or Backblaze.
"""
import os
import gc
import json
import time
import inspect
import traceback
import subprocess
import urllib.request

OUT = "/kaggle/working"
REPORT = {"started": time.strftime("%Y-%m-%d %H:%M:%S"), "test": "mimsi-ltx-2b-0.9.8-distilled-test4", "steps": []}

CKPT = "https://huggingface.co/Lightricks/LTX-Video/ltxv-2b-0.9.8-distilled.safetensors"
BASE_REPO = "Lightricks/LTX-Video"
W, H, FRAMES, STEPS, FPS = 704, 480, 97, 8, 24

MIMSI_URL = "https://dbdtwhzlmzhyidpmeymn.supabase.co/storage/v1/object/public/video_clips/refs/mimsi.png"
MIMSI = ("Mimsi the snail, a small cute garden snail with a friendly happy face. Soft pale tan-yellow body, "
         "two short eyestalks, each with one big round shiny eye with a brown iris, a small smiling mouth, "
         "and a smooth bright orange spiral shell with one cream-colored swirl line.")
STYLE = ("photoreal 3D animated macro-world, sunny green lawn, bright natural daylight, "
         "soft shallow depth of field, vivid saturated color, cinematic")

# (name, prompt, sound words, uses Mimsi picture)
SHOTS = [
    ("mimsi_eyes_pop", MIMSI + " Her eyestalks pop up tall and her eyes go wide with surprise as she stares at "
     "something off camera, then a small happy bounce. " + STYLE + ", camera static", "gasp, pop", True),
    ("mimsi_crawl", MIMSI + " She slowly crawls forward across the grass, her shell gently wobbling, "
     "eyestalks swaying and looking around. " + STYLE + ", slow camera follow", "squeak, boing", True),
    ("mimsi_hide", MIMSI + " She pulls her head into her shell and the bright orange shell spins like a top "
     "on the grass. " + STYLE + ", camera static", "whoosh, boing", True),
    ("sparrow_no_reference", "A small sparrow with a round fluffy body, streaky brown and cream feathers, a short pale "
     "cone-shaped beak and one big curious round black eye hops across a sunny green lawn and pecks the ground. "
     + STYLE + ", camera static", "chirp, tick", False),
]
CHAIN_PROMPT = (MIMSI + " She keeps crawling forward, her eyestalks drooping tiredly, shell wobbling. "
                + STYLE + ", slow camera follow")
CHAIN_SOUND = "sigh, squeak"


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
r = run("pip install -q -U diffusers transformers accelerate ftfy imageio imageio-ffmpeg sentencepiece protobuf pillow")
REPORT["pip_returncode"] = r.returncode
run("pip uninstall -y torchao")
REPORT["versions"] = run("pip list 2>/dev/null | grep -iE '^(torch|diffusers|transformers|accelerate) '").stdout.strip()
save()

import torch  # noqa: E402
import imageio_ffmpeg  # noqa: E402
from PIL import Image  # noqa: E402
from diffusers import LTXPipeline, LTXImageToVideoPipeline  # noqa: E402
from diffusers.utils import export_to_video  # noqa: E402

FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
SR = 44100

# ---------- sound (same recipe as upgraded-journey assembly/sound.py) ----------
NOISE = "anoisesrc=d={d}:c={c}:a={a}:r=44100"
EFFECTS = {
    "boing": "aevalsrc='0.7*sin(2*PI*(260+240*sin(2*PI*5*t))*t)*exp(-4*t)':d=0.7",
    "pop": "aevalsrc='0.8*sin(2*PI*(700+900*exp(-20*t))*t)*exp(-18*t)':d=0.2",
    "squeak": "aevalsrc='0.5*sin(2*PI*(1400+500*sin(2*PI*14*t))*t)*exp(-6*t)':d=0.35",
    "tick": "aevalsrc='0.7*sin(2*PI*1800*t)*exp(-70*t)':d=0.12",
    "chirp": "aevalsrc='0.5*sin(2*PI*(2600+900*sin(2*PI*9*t))*t)*exp(-9*t)':d=0.3",
    "whoosh": NOISE.format(d=0.9, c="pink", a=0.6) + ",bandpass=f=900:t=h:w=700,afade=t=in:d=0.45,afade=t=out:st=0.45:d=0.45",
    "gasp": NOISE.format(d=0.5, c="white", a=0.5) + ",bandpass=f=1800:t=h:w=1200,afade=t=in:d=0.2,afade=t=out:st=0.25:d=0.25",
    "sigh": NOISE.format(d=1.0, c="pink", a=0.35) + ",bandpass=f=600:t=h:w=500,afade=t=in:d=0.3,afade=t=out:st=0.4:d=0.6",
}
GAIN_DB = {"whoosh": 12, "sigh": 14, "gasp": 6}
NOTES = [262, 330, 392, 330, 440, 392, 330, 294, 262, 330, 392, 523, 440, 392, 330, 294]
STEP = 0.5


def ff(args):
    subprocess.run([FFMPEG, "-y", "-v", "error"] + args, check=True)


def make_effect(name):
    out = os.path.join("/tmp", f"sfx_{name}.wav")
    if not os.path.exists(out):
        ff(["-f", "lavfi", "-i", EFFECTS[name], "-af", f"volume={GAIN_DB.get(name, 0)}dB",
            "-ar", str(SR), "-ac", "1", out])
    return out


def make_music(duration):
    out = "/tmp/music_bed.wav"
    fade = f"afade=t=in:d=1,afade=t=out:st={max(duration - 2, 0):.2f}:d=2"
    freq = "0"
    for i in reversed(range(len(NOTES))):
        freq = f"if(eq(mod(floor(t/{STEP}),{len(NOTES)}),{i}),{NOTES[i]},{freq})"
    expr = (f"0.45*(sin(2*PI*({freq})*t)+0.3*sin(4*PI*({freq})*t))*exp(-5*mod(t,{STEP}))"
            f"+0.25*sin(2*PI*131*t)*exp(-1.2*mod(t,2))")
    ff(["-f", "lavfi", "-i", f"aevalsrc='{expr}':d={duration:.2f}:s={SR}", "-af", fade, "-ac", "1", out])
    return out


def add_sound(video_path, sound_words, duration):
    """Mux music + effects onto a silent clip. Returns the new file path."""
    names = [w.strip() for w in sound_words.split(",") if w.strip() in EFFECTS]
    music = make_music(duration)
    fx = [make_effect(n) for n in names]
    inputs = ["-i", video_path, "-i", music]
    for f in fx:
        inputs += ["-i", f]
    parts = ["[1:a]volume=0.35[m]"]
    labels = ["[m]"]
    for i in range(len(fx)):
        delay = int((0.6 + i * 1.4) * 1000)
        parts.append(f"[{i + 2}:a]adelay={delay}|{delay}[s{i}]")
        labels.append(f"[s{i}]")
    parts.append("".join(labels) + f"amix=inputs={len(labels)}:normalize=0,alimiter=limit=0.95[a]")
    out = video_path.replace(".mp4", "_sound.mp4")
    ff(inputs + ["-filter_complex", ";".join(parts), "-map", "0:v", "-map", "[a]",
                 "-c:v", "copy", "-c:a", "aac", "-shortest", out])
    return out


def has_audio(path):
    p = subprocess.run([FFMPEG, "-i", path], capture_output=True, text=True)
    return "Audio:" in (p.stderr or "")


# ---------- model ----------
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


def load_mimsi():
    """Download Mimsi's reference picture and crop it to the video shape."""
    path = os.path.join(OUT, "mimsi_reference.png")
    urllib.request.urlretrieve(MIMSI_URL, path)
    img = Image.open(path).convert("RGB")
    scale = max(W / img.width, H / img.height)
    img = img.resize((round(img.width * scale), round(img.height * scale)), Image.LANCZOS)
    left, top = (img.width - W) // 2, (img.height - H) // 2
    img = img.crop((left, top, left + W, top + H))
    img.save(os.path.join(OUT, "mimsi_reference_cropped.png"))
    return img


def call(pipe, prompt, seed, image=None):
    # the picture-to-video pipeline draws its noise on the GPU, so its generator must be on cuda
    gen = torch.Generator("cuda").manual_seed(seed) if image is not None else torch.Generator().manual_seed(seed)
    kw = dict(prompt=prompt, width=W, height=H, num_frames=FRAMES, num_inference_steps=STEPS,
              guidance_scale=1.0, decode_timestep=0.05, decode_noise_scale=0.025, generator=gen)
    if image is not None:
        kw["image"] = image
        kw["image_cond_noise_scale"] = 0.025
    allowed = set(inspect.signature(pipe.__call__).parameters)
    dropped = [k for k in kw if k not in allowed]
    kw = {k: v for k, v in kw.items() if k in allowed}
    return pipe(**kw).frames[0], dropped


def timed(name, pipe, prompt, seed, sound_words, image=None):
    step = {"step": name, "ok": False, "used_picture": image is not None}
    torch.cuda.reset_peak_memory_stats()
    t = time.time()
    try:
        frames, dropped = call(pipe, prompt, seed, image)
        step["generate_seconds"] = round(time.time() - t, 1)
        path = os.path.join(OUT, f"mimsi4_{name}.mp4")
        export_to_video(frames, path, fps=FPS)
        step["file"] = path
        step["clip_seconds"] = round(len(frames) / FPS, 2)
        step["dropped_args"] = dropped
        step["peak_vram_gb"] = round(torch.cuda.max_memory_allocated() / 1e9, 2)
        step["ok"] = True
        try:
            with_sound = add_sound(path, sound_words, step["clip_seconds"])
            step["sound_file"] = with_sound
            step["sound_has_audio_track"] = has_audio(with_sound)
        except Exception as e:
            step["sound_error"] = (type(e).__name__ + ": " + str(e))[:300]
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
    try:
        mimsi_img = load_mimsi()
        log({"step": "mimsi_picture", "ok": True, "size": list(mimsi_img.size)})
    except Exception as e:
        mimsi_img = None
        log({"step": "mimsi_picture", "ok": False, "error": (type(e).__name__ + ": " + str(e))[:400]})

    i2v = None
    try:
        i2v = LTXImageToVideoPipeline(**pipe.components)
    except Exception as e:
        log({"step": "i2v_setup", "ok": False, "error": (type(e).__name__ + ": " + str(e))[:400],
             "trace": traceback.format_exc()[-800:]})

    crawl = None
    for i, (name, prompt, sound_words, use_pic) in enumerate(SHOTS, start=1):
        if use_pic:
            if i2v is None or mimsi_img is None:
                log({"step": name, "ok": False, "error": "no picture or no i2v pipeline"})
                continue
            frames = timed(name, i2v, prompt, i, sound_words, image=mimsi_img)
        else:
            frames = timed(name, pipe, prompt, i, sound_words)
        if name == "mimsi_crawl":
            crawl = frames

    if crawl is not None and i2v is not None:
        timed("chain_from_crawl", i2v, CHAIN_PROMPT, 9, CHAIN_SOUND, image=crawl[-1])

REPORT["finished"] = time.strftime("%Y-%m-%d %H:%M:%S")
save()
print("DONE")
