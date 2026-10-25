#!/usr/bin/env python3
"""How money built globalization — 30s motion graphic with voiceover.

Pipeline:
  1. synthesize VO per line (edge-tts)
  2. measure each line's real duration -> scene lengths
  3. render scenes in parallel (multiprocessing; CI has 4 cores)
  4. concat video, build audio track with matching gaps, mux

No browser, no API keys, no stock footage.
"""
import argparse
import json
import math
import os
import shutil
import subprocess
import sys
from multiprocessing import Pool

from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H = 1080, 1920
FPS = 30
PAD = 0.45  # breath after each VO line

BG = (20, 20, 19)
INK = (244, 243, 238)
MUTED = (154, 151, 145)
TERRA = (217, 119, 87)
GOLD = (232, 178, 92)
BLUE = (96, 165, 250)
GLASS_TINT = (255, 255, 255, 46)

BOLD_PATHS = ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]
REG_PATHS = ["/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]

VOICE = "en-US-AriaNeural"

# ---- script: label, headline, narration
SCENES = [
    dict(
        label="BARTER",
        head="Before money",
        vo="For most of history, trade meant barter. You needed what I had, and I needed what you had.",
        cap="You needed what I had.",
    ),
    dict(
        label="ONE UNIT",
        head="A shared measure",
        vo="Money changed the deal. One unit, accepted by strangers, in any port.",
        cap="One unit strangers accept.",
    ),
    dict(
        label="DISTANCE",
        head="Ports and credit",
        vo="With a shared measure of value, distance stopped mattering.",
        cap="Distance stopped mattering.",
    ),
    dict(
        label="TRADE",
        head="It compounded",
        vo="Trade grew. Supply chains spread across continents.",
        cap="Supply chains crossed continents.",
    ),
    dict(
        label="TRUST",
        head="What actually spread",
        vo="Globalization was not built by politics. It was built on trust in one unit.",
        cap="Built on trust in one unit.",
    ),
]


def ffmpeg_bin():
    for c in (os.environ.get("FFMPEG_BIN"),
              "/root/.hermes/tools/ffmpeg-9.0.1-linux-x64/bin/ffmpeg",
              shutil.which("ffmpeg")):
        if c and os.path.exists(c):
            return c
    raise SystemExit("ffmpeg not found")


def ffprobe_dur(path):
    # NOTE: never string-replace "ffmpeg"->"ffprobe" in the full path — it also
    # rewrites the *directory* name (.../ffmpeg-9.0.1.../ffprobe-9.0.1...).
    ff = ffmpeg_bin()
    probe = os.path.join(os.path.dirname(ff), "ffprobe")
    if os.path.exists(probe):
        out = subprocess.run([probe, "-v", "error", "-show_entries", "format=duration",
                              "-of", "default=nw=1:nk=1", path],
                             capture_output=True, text=True)
        try:
            return float(out.stdout.strip())
        except ValueError:
            pass
    # fallback: parse ffmpeg stderr
    out = subprocess.run([ff, "-i", path], capture_output=True, text=True)
    for line in out.stderr.splitlines():
        if "Duration:" in line:
            t = line.split("Duration:")[1].split(",")[0].strip()
            h, m, s = t.split(":")
            return int(h) * 3600 + int(m) * 60 + float(s)
    return 0.0


def font(bold, size):
    for p in (BOLD_PATHS if bold else REG_PATHS):
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def clamp01(x):
    return max(0.0, min(1.0, x))


def ease_out(t):
    return 1 - (1 - t) ** 3


def ease_io(t):
    return t * t * (3 - 2 * t)


def seg(t, a, d):
    return clamp01((t - a) / d) if d > 0 else 1.0


# ---------------------------------------------------------------- backdrop
def backdrop():
    """Vertical gradient, warm-dark, built small then upscaled."""
    sw, sh = 54, 96
    small = Image.new("RGB", (sw, sh))
    px = small.load()
    for y in range(sh):
        f = y / (sh - 1)
        px_col = (
            int(20 + 8 * (1 - f)),
            int(20 + 6 * (1 - f)),
            int(19 + 4 * (1 - f)),
        )
        for x in range(sw):
            px[x, y] = px_col
    return small.resize((W, H), Image.BICUBIC)


def radial(size, peak=170, pw=2.2):
    s = 128
    small = Image.new("L", (s, s), 0)
    px = small.load()
    c = s / 2
    for y in range(s):
        for x in range(s):
            d = min(1.0, math.hypot(x - c, y - c) / c)
            px[x, y] = int(peak * (1 - d) ** pw)
    return small.resize((size, size), Image.BICUBIC)


BACK = backdrop()
ORB_TERRA = (Image.new("RGB", (900, 900), TERRA), radial(900, 190))
ORB_BLUE = (Image.new("RGB", (760, 760), BLUE), radial(760, 120))


def add_orb(img, orb, cx, cy, strength=0.8):
    base, mask = orb
    layer = Image.new("RGB", (W, H), (0, 0, 0))
    layer.paste(base, (int(cx) - base.width // 2, int(cy) - base.height // 2), mask)
    return Image.blend(img, layer, strength)


def glass_panel(img, bbox, radius=44, blur=30, tint=GLASS_TINT):
    x1, y1, x2, y2 = [int(v) for v in bbox]
    cw, ch = max(2, x2 - x1), max(2, y2 - y1)
    crop = img.crop((max(0, x1), max(0, y1), min(W, x2), min(H, y2))).convert("RGB")
    crop = crop.resize((max(1, cw // 4), max(1, ch // 4)), Image.BILINEAR)
    crop = crop.filter(ImageFilter.GaussianBlur(max(1, blur // 4)))
    crop = crop.resize((cw, ch), Image.BICUBIC)
    frost = Image.alpha_composite(crop.convert("RGBA"), Image.new("RGBA", (cw, ch), tint))
    mask = Image.new("L", (cw, ch), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, cw - 1, ch - 1), radius=radius, fill=255)
    img.paste(frost.convert("RGB"), (x1, max(0, y1)), mask)
    rim = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
    ImageDraw.Draw(rim).rounded_rectangle((0, 0, cw - 1, ch - 1), radius=radius,
                                          outline=(255, 255, 255, 60), width=2)
    fade = Image.new("L", (cw, ch), 0)
    fd = ImageDraw.Draw(fade)
    for y in range(ch):
        fd.line([(0, y), (cw, y)], fill=int(255 * max(0.0, 1 - y / (ch * 0.85))))
    rim.putalpha(Image.composite(rim.getchannel("A"), Image.new("L", (cw, ch), 0), fade))
    img.paste(rim.convert("RGB"), (x1, max(0, y1)), rim.getchannel("A"))
    return img


# ---------------------------------------------------------------- drawings
def draw_coin(d, cx, cy, r, p, t):
    if p <= 0:
        return
    rr = r * ease_out(p)
    d.ellipse([cx - rr, cy - rr, cx + rr, cy + rr], fill=(34, 30, 26), outline=GOLD, width=max(3, int(rr * 0.06)))
    d.ellipse([cx - rr * 0.74, cy - rr * 0.74, cx + rr * 0.74, cy + rr * 0.74], outline=(232, 178, 92, 120), width=2)
    f = font(True, int(rr * 0.92))
    txt = "$"
    bb = d.textbbox((0, 0), txt, font=f)
    d.text((cx - (bb[2] - bb[0]) / 2, cy - (bb[3] - bb[1]) / 2 - bb[1]), txt, font=f, fill=GOLD)


def draw_arrow(d, x0, y0, x1, y1, p, color, width=7, head=18):
    if p <= 0:
        return
    p = ease_out(p)
    xe, ye = x0 + (x1 - x0) * p, y0 + (y1 - y0) * p
    d.line([x0, y0, xe, ye], fill=color, width=width)
    if p > 0.8:
        ang = math.atan2(y1 - y0, x1 - x0)
        for s in (-0.5, 0.5):
            d.line([xe, ye, xe - head * math.cos(ang + s), ye - head * math.sin(ang + s)],
                   fill=color, width=width)


def scene_barter(t, dur, d, img):
    k = W / 1080
    left = (170 * k, 760 * k, 430 * k, 1020 * k)
    right = (650 * k, 760 * k, 910 * k, 1020 * k)
    p = seg(t, 0.1, 0.7)
    if p > 0:
        img = glass_panel(img, left)
        img = glass_panel(img, right)
        d = ImageDraw.Draw(img, "RGBA")
        d.rounded_rectangle([left[0] + 60 * k, left[1] + 70 * k, left[2] - 60 * k, left[3] - 70 * k],
                            radius=12, outline=MUTED, width=3)
        d.ellipse([right[0] + 60 * k, right[1] + 70 * k, right[2] - 60 * k, right[3] - 70 * k],
                  outline=MUTED, width=3)
    # the swap that fails: two arrows, one stops short
    draw_arrow(d, 460 * k, 830 * k, 640 * k, 830 * k, seg(t, 0.9, 0.7), TERRA)
    draw_arrow(d, 640 * k, 950 * k, 520 * k, 950 * k, seg(t, 1.5, 0.7), MUTED)
    if t > 2.3:
        d.line([470 * k, 900 * k, 620 * k, 900 * k], fill=(255, 107, 107), width=5)
    return img, d


def scene_unit(t, dur, d, img):
    k = W / 1080
    cx, cy = W / 2, 940 * k
    draw_coin(d, cx, cy, 110 * k, seg(t, 0.05, 0.6), t)
    nodes = [(cx + math.cos(a) * 330 * k, cy + math.sin(a) * 250 * k) for a in
             [math.radians(x) for x in (-150, -105, -60, 60, 105, 150)]]
    for i, (nx, ny) in enumerate(nodes):
        pp = seg(t, 0.55 + i * 0.12, 0.5)
        if pp <= 0:
            continue
        d.line([cx, cy, nx, ny], fill=(232, 178, 92, 110), width=3)
        rr = 26 * k * ease_out(pp)
        d.ellipse([nx - rr, ny - rr, nx + rr, ny + rr], fill=(255, 255, 255, 26), outline=(255, 255, 255, 70), width=2)
    return img, d


def scene_distance(t, dur, d, img):
    k = W / 1080
    # subtle grid
    for gx in range(0, W, int(90 * k)):
        d.line([gx, 640 * k, gx, 1180 * k], fill=(255, 255, 255, 12), width=1)
    for gy in range(int(640 * k), int(1180 * k), int(90 * k)):
        d.line([0, gy, W, gy], fill=(255, 255, 255, 12), width=1)

    ports = [(250 * k, 800 * k), (820 * k, 730 * k), (330 * k, 1090 * k),
             (760 * k, 1060 * k), (540 * k, 690 * k)]
    for i, (px, py) in enumerate(ports):
        pp = seg(t, 0.15 + i * 0.08, 0.4)
        if pp > 0:
            rr = 14 * k * ease_out(pp)
            d.ellipse([px - rr, py - rr, px + rr, py + rr], fill=BLUE)
    routes = [(0, 1), (0, 4), (4, 1), (0, 2), (2, 3), (3, 1)]
    for i, (a, b) in enumerate(routes):
        p = seg(t, 0.6 + i * 0.16, 0.6)
        if p <= 0:
            continue
        x0, y0 = ports[a]
        x1, y1 = ports[b]
        mx, my = (x0 + x1) / 2, (y0 + y1) / 2 - 90 * k
        steps = 26
        n = max(2, int(steps * ease_io(p)))
        pts = []
        for s in range(n + 1):
            u = s / steps
            bx = (1 - u) ** 2 * x0 + 2 * (1 - u) * u * mx + u * u * x1
            by = (1 - u) ** 2 * y0 + 2 * (1 - u) * u * my + u * u * y1
            pts.append((bx, by))
        if len(pts) > 1:
            d.line(pts, fill=(120, 180, 255, 215), width=5)
        if p > 0.95:
            ex, ey = pts[-1]
            d.ellipse([ex - 8, ey - 8, ex + 8, ey + 8], fill=(232, 178, 92))
    return img, d


def scene_growth(t, dur, d, img):
    k = W / 1080
    base_y = 1180 * k
    vals = [0.22, 0.34, 0.5, 0.72, 1.0]
    bw = 80 * k
    gap = 52 * k
    start_x = (W - (len(vals) * bw + (len(vals) - 1) * gap)) / 2
    for i, v in enumerate(vals):
        p = seg(t, 0.1 + i * 0.14, 0.55)
        if p <= 0:
            continue
        h = 470 * k * v * ease_out(p)
        x = start_x + i * (bw + gap)
        col = GOLD if i == len(vals) - 1 else (255, 255, 255, 40)
        d.rounded_rectangle([x, base_y - h, x + bw, base_y], radius=int(12 * k), fill=col)
    d.line([start_x - 30 * k, base_y, start_x + len(vals) * (bw + gap), base_y],
           fill=(255, 255, 255, 70), width=3)
    return img, d


def scene_trust(t, dur, d, img):
    k = W / 1080
    cx, cy = W / 2, 950 * k
    p = seg(t, 0.05, 0.8)
    draw_coin(d, cx, cy, 120 * k, p, t)
    for i in range(3):
        pp = seg(t, 0.3 + i * 0.22, 0.9)
        rr = (190 + i * 62) * k * ease_out(pp)
        if rr > 2:
            d.ellipse([cx - rr, cy - rr * 0.62, cx + rr, cy + rr * 0.62],
                      outline=(232, 178, 92, max(0, 90 - i * 22)), width=3)
    return img, d


SCENE_FN = [scene_barter, scene_unit, scene_distance, scene_growth, scene_trust]


def render_scene(args):
    idx, frames, path = args
    fn = SCENE_FN[idx]
    proc = subprocess.Popen(
        [ffmpeg_bin(), "-y", "-f", "rawvideo", "-vcodec", "rawvideo",
         "-s", f"{W}x{H}", "-pix_fmt", "rgb24", "-r", str(FPS), "-i", "-",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "20",
         "-preset", "veryfast", "-movflags", "+faststart", path],
        stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    dur = frames / FPS
    for f in range(frames):
        t = f / FPS
        img = BACK.copy()
        ang = t / max(0.001, dur) * math.tau
        img = add_orb(img, ORB_TERRA, W * 0.46 + math.sin(ang) * 90,
                      H * 0.42 + math.cos(ang) * 70, 0.75)
        img = add_orb(img, ORB_BLUE, W * 0.82, H * 0.74, 0.45)
        d = ImageDraw.Draw(img, "RGBA")

        img, d = fn(t, dur, d, img)

        # ---- header + caption (inside vertical safe zone)
        f_lab = font(True, int(26 * W / 1080))
        f_head = font(True, int(54 * W / 1080))
        f_cap = font(True, int(40 * W / 1080))
        k = W / 1080
        lab_p = ease_out(seg(t, 0.0, 0.4))
        d.text((90 * k, 300 * k + (1 - lab_p) * 24), SCENES[idx]["label"], font=f_lab, fill=TERRA)
        head_p = ease_out(seg(t, 0.12, 0.55))
        d.text((90 * k, 348 * k + (1 - head_p) * 30), SCENES[idx]["head"], font=f_head, fill=INK)

        cap_p = ease_out(seg(t, 0.25, 0.5))
        if cap_p > 0:
            cap = SCENES[idx]["cap"]
            bb = d.textbbox((0, 0), cap, font=f_cap)
            cw = bb[2] - bb[0]
            cx = (W - cw) / 2
            cy = H - 430 * k + (1 - cap_p) * 26
            d.rounded_rectangle([cx - 40, cy - 22, cx + cw + 40, cy + 74],
                                radius=22, fill=(255, 255, 255, 18))
            d.text((cx, cy), cap, font=f_cap, fill=INK)

        proc.stdin.write(img.tobytes())
    proc.stdin.close()
    proc.wait()
    return path


def synth_vo(outdir):
    os.makedirs(outdir, exist_ok=True)
    files = []
    for i, sc in enumerate(SCENES):
        p = os.path.join(outdir, f"vo{i}.mp3")
        if not (os.path.exists(p) and os.path.getsize(p) > 1000):
            r = subprocess.run(
                [sys.executable, "-m", "edge_tts", "--voice", VOICE,
                 "--text", sc["vo"], "--write-media", p],
                capture_output=True, text=True,
            )
            if not os.path.exists(p):
                raise SystemExit(f"VO failed for scene {i}: {r.stderr[:300]}")
        files.append(p)
    return files


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="out/globalization.mp4")
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 1)))
    ap.add_argument("--work", default="build")
    ap.add_argument("--skip-vo", action="store_true")
    a = ap.parse_args()

    os.makedirs(a.work, exist_ok=True)
    os.makedirs(os.path.dirname(os.path.abspath(a.out)) or ".", exist_ok=True)

    vo_files = synth_vo(os.path.join(a.work, "vo"))
    durs = [ffprobe_dur(p) for p in vo_files]
    frames = [max(int(FPS * 2.2), int(round((d + PAD) * FPS))) for d in durs]
    total = sum(frames)
    print("VO durations:", [round(d, 2) for d in durs])
    print(f"scenes frames={frames} total={total} ({total / FPS:.1f}s)")

    jobs = [(i, frames[i], os.path.join(a.work, f"scene{i}.mp4")) for i in range(len(SCENES))]
    if a.workers > 1:
        with Pool(min(a.workers, len(jobs))) as pool:
            for done in pool.imap_unordered(render_scene, jobs):
                print("rendered", done, flush=True)
    else:
        for j in jobs:
            print("rendered", render_scene(j), flush=True)

    # ---- concat video
    listfile = os.path.join(a.work, "concat.txt")
    with open(listfile, "w") as fh:
        for _, _, p in jobs:
            fh.write(f"file '{os.path.abspath(p)}'\n")
    silent = os.path.join(a.work, "silent.mp4")
    subprocess.run([ffmpeg_bin(), "-y", "-f", "concat", "-safe", "0", "-i", listfile,
                    "-c", "copy", silent], check=True, capture_output=True)

    # ---- build audio: vo_i followed by PAD silence, matching scene lengths
    pieces, filters, inputs = [], [], []
    t_cursor = 0.0
    for i, p in enumerate(vo_files):
        inputs += ["-i", p]
        filters.append(f"[{i}:a]adelay={int(t_cursor * 1000)}|{int(t_cursor * 1000)}[a{i}]")
        pieces.append(f"[a{i}]")
        t_cursor += frames[i] / FPS
    fc = ";".join(filters) + ";" + "".join(pieces) + f"amix=inputs={len(pieces)}:normalize=0[aout]"
    mixed = os.path.join(a.work, "voice.m4a")
    subprocess.run([ffmpeg_bin(), "-y", *inputs, "-filter_complex", fc,
                    "-map", "[aout]", "-t", f"{t_cursor:.2f}", "-c:a", "aac",
                    "-b:a", "160k", mixed], check=True, capture_output=True)

    subprocess.run([ffmpeg_bin(), "-y", "-i", silent, "-i", mixed,
                    "-c:v", "copy", "-c:a", "aac", "-b:a", "160k",
                    "-shortest", "-movflags", "+faststart", a.out],
                   check=True, capture_output=True)
    print("OK", a.out, os.path.getsize(a.out), "bytes", f"{t_cursor:.1f}s")


if __name__ == "__main__":
    main()
