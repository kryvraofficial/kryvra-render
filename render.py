#!/usr/bin/env python3
"""Portable renderer for CI (GitHub Actions) and local use.

Renders the glassmorphic ledgers scene to MP4 with Pillow + ffmpeg.
No Node, no Chromium, no API calls.

Usage:
    python render.py --out out/video.mp4 --seconds 3 --fps 30
    python render.py --out out/video.mp4 --width 1080 --height 1920 --seconds 6
"""
import argparse
import math
import os
import shutil
import subprocess

from PIL import Image, ImageDraw, ImageFilter, ImageFont

BG = (20, 20, 19)
TERRA = (217, 119, 87)
CREAM = (244, 243, 238)
MUTED = (154, 151, 145)
BLUE = (96, 165, 250)

FONT_CANDIDATES = {
    True: [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    ],
    False: [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    ],
}


def ffmpeg_bin():
    for cand in (
        os.environ.get("FFMPEG_BIN"),
        "/root/.hermes/tools/ffmpeg-9.0.1-linux-x64/bin/ffmpeg",
        shutil.which("ffmpeg"),
    ):
        if cand and os.path.exists(cand):
            return cand
    raise SystemExit("ffmpeg not found (set FFMPEG_BIN)")


def font(bold, size):
    for path in FONT_CANDIDATES[bold]:
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def clamp01(x):
    return max(0.0, min(1.0, x))


def spring_curve(frames, fps, damping=11.0, stiffness=180.0, mass=0.7):
    dt = 1.0 / fps
    x, v = 0.0, 0.0
    out = []
    for _ in range(frames):
        a = (-stiffness * (x - 1.0) - damping * v) / mass
        v += a * dt
        x += v * dt
        out.append(x)
    return out


def ease_out_progress(frames, start, dur):
    out = []
    for i in range(frames):
        p = clamp01((i - start) / max(1, dur))
        out.append(1 - (1 - p) ** 3)
    return out


def radial_orb(size, color, peak=185):
    s = 96
    small = Image.new("L", (s, s), 0)
    px = small.load()
    c = s / 2
    for y in range(s):
        for x in range(s):
            d = min(1.0, math.hypot(x - c, y - c) / c)
            px[x, y] = int(peak * (1 - d) ** 2.2)
    return Image.new("RGB", (size, size), color), small.resize((size, size), Image.BICUBIC)


def draw_glass_card(base, bbox, radius=40, blur=26, tint=(255, 255, 255, 44),
                    rim=(255, 255, 255, 70)):
    W, H = base.size
    x1, y1, x2, y2 = [int(v) for v in bbox]
    cw, ch = x2 - x1, y2 - y1
    if cw <= 2 or ch <= 2:
        return base

    crop = base.crop((max(0, x1), max(0, y1), min(W, x2), min(H, y2))).convert("RGB")
    crop = crop.resize((max(1, cw // 4), max(1, ch // 4)), Image.BILINEAR)
    crop = crop.filter(ImageFilter.GaussianBlur(max(1, blur // 4)))
    crop = crop.resize((cw, ch), Image.BICUBIC)

    frost = Image.alpha_composite(crop.convert("RGBA"), Image.new("RGBA", (cw, ch), tint))
    mask = Image.new("L", (cw, ch), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, cw - 1, ch - 1), radius=radius, fill=255)
    base.paste(frost.convert("RGB"), (x1, max(0, y1)), mask)

    rim_layer = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
    ImageDraw.Draw(rim_layer).rounded_rectangle(
        (0, 0, cw - 1, ch - 1), radius=radius, outline=rim, width=2
    )
    fade = Image.new("L", (cw, ch), 0)
    fd = ImageDraw.Draw(fade)
    for y in range(ch):
        fd.line([(0, y), (cw, y)], fill=int(255 * max(0.0, 1 - y / (ch * 0.9))))
    rim_layer.putalpha(Image.composite(rim_layer.getchannel("A"), Image.new("L", (cw, ch), 0), fade))
    base.paste(rim_layer.convert("RGB"), (x1, max(0, y1)), rim_layer.getchannel("A"))
    return base


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="out/video.mp4")
    ap.add_argument("--seconds", type=float, default=3.0)
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--width", type=int, default=720)
    ap.add_argument("--height", type=int, default=1280)
    ap.add_argument("--crf", type=int, default=18)
    a = ap.parse_args()

    W, H, FPS = a.width, a.height, a.fps
    total = int(FPS * a.seconds)
    k = W / 720.0  # scale typography with canvas width

    spring = spring_curve(total + 30, FPS)
    counter = ease_out_progress(total + 30, start=int(0.55 * FPS), dur=int(0.9 * FPS))
    orb_t, orb_m = radial_orb(int(580 * k), TERRA, 185)
    orb_b, orb_m2 = radial_orb(int(480 * k), BLUE, 120)

    os.makedirs(os.path.dirname(os.path.abspath(a.out)) or ".", exist_ok=True)

    cmd = [
        ffmpeg_bin(), "-y",
        "-f", "rawvideo", "-vcodec", "rawvideo", "-s", f"{W}x{H}",
        "-pix_fmt", "rgb24", "-r", str(FPS), "-i", "-",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", str(a.crf),
        "-preset", "medium", "-movflags", "+faststart", a.out,
    ]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    for i in range(total):
        t = i / FPS
        spr = spring[min(i, len(spring) - 1)]
        val_p = counter[min(i, len(counter) - 1)]

        zoom = 1.0 + 0.06 * (i / max(1, total - 1))
        img = Image.new("RGB", (W, H), BG)

        ang = t / max(0.001, a.seconds) * math.tau
        ox = 0.46 * W + math.sin(ang) * 70 * k
        oy = 0.40 * H + math.cos(ang) * 60 * k
        lay = Image.new("RGB", (W, H), (0, 0, 0))
        lay.paste(orb_t, (int(ox) - orb_t.width // 2, int(oy) - orb_t.height // 2), orb_m)
        lay.paste(orb_b, (int(W * 0.78) - orb_b.width // 2, int(H * 0.72) - orb_b.height // 2), orb_m2)
        img = Image.blend(img, lay, 0.85)

        if zoom != 1.0:
            nw, nh = int(W * zoom), int(H * zoom)
            img = img.resize((nw, nh), Image.BICUBIC)
            left, top = (nw - W) // 2, (nh - H) // 2
            img = img.crop((left, top, left + W, top + H))

        lift = int(90 * k * (1 - spr)) if spr < 1 else 0
        scale = max(0.6, min(1.12, spr))
        cw, ch = int(560 * k * scale), int(420 * k * scale)
        cx, cy = W // 2, int(H * 0.55) + lift
        bbox = (cx - cw // 2, cy - ch // 2, cx + cw // 2, cy + ch // 2)
        img = draw_glass_card(img, bbox, radius=max(8, int(40 * scale)))

        d = ImageDraw.Draw(img, "RGBA")
        f_kick = font(False, max(10, int(16 * k * scale)))
        f_val = font(True, max(20, int(66 * k * scale)))
        f_sub = font(False, max(10, int(17 * k * scale)))
        f_pill = font(False, max(9, int(13 * k * scale)))

        x0 = cx - cw // 2 + int(40 * k * scale)
        d.text((x0, cy - ch // 2 + int(42 * k * scale)), "SMART LEDGER", font=f_kick, fill=MUTED + (255,))
        d.text((x0, cy - ch // 2 + int(88 * k * scale)),
               f"${int(18420 * val_p):,}", font=f_val, fill=CREAM + (255,))
        d.text((x0, cy - ch // 2 + int(178 * k * scale)), "this month",
               font=f_sub, fill=(140, 137, 132, 255))

        px = x0
        py = cy + ch // 2 - int(78 * k * scale)
        for label in ("CATEGORISED", "RECONCILED"):
            bb = d.textbbox((0, 0), label, font=f_pill)
            pw = (bb[2] - bb[0]) + int(34 * k * scale)
            ph = int(34 * k * scale)
            d.rounded_rectangle([px, py, px + pw, py + ph], radius=ph // 2,
                                fill=(255, 255, 255, 26), outline=(255, 255, 255, 48), width=1)
            d.text((px + int(17 * k * scale), py + int(9 * k * scale)),
                   label, font=f_pill, fill=(226, 224, 219, 255))
            px += pw + int(12 * k * scale)

        proc.stdin.write(img.tobytes())

    proc.stdin.close()
    proc.wait()
    print(f"OK {a.out} {os.path.getsize(a.out)} bytes {total} frames {W}x{H}@{FPS}")


if __name__ == "__main__":
    main()
