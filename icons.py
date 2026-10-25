#!/usr/bin/env python3
"""Lucide icon loader: fetch SVG once, rasterize to a tinted PNG, cache it.

Lucide is ISC-licensed (free for commercial use, attribution not required).

Why rasterize: Pillow cannot draw SVG. cairosvg converts the path data to a
bitmap; the result is cached by (name, size, colour) so a 900-frame render
downloads and converts each icon exactly once.
"""
import hashlib
import os
import subprocess

import cairosvg
from PIL import Image

BASE = "https://unpkg.com/lucide-static@latest/icons/{name}.svg"
CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icon_cache")

# icons used by the globalization piece (all present in lucide-static)
USED = [
    "handshake",   # barter / trust
    "wheat",       # goods
    "shirt",       # goods
    "coins",       # money
    "banknote",    # one unit
    "ship",        # sea trade
    "truck",       # land trade
    "anchor",      # port
    "package",     # cargo
    "factory",     # production
    "globe",       # globalization
    "trending-up", # growth
]


def _svg_path(name):
    os.makedirs(CACHE, exist_ok=True)
    p = os.path.join(CACHE, f"{name}.svg")
    if not (os.path.exists(p) and os.path.getsize(p) > 200):
        url = BASE.format(name=name)
        r = subprocess.run(["curl", "-sL", "--max-time", "30", "-o", p, url],
                           capture_output=True, text=True)
        if not (os.path.exists(p) and os.path.getsize(p) > 200):
            raise RuntimeError(f"icon download failed: {name} ({r.returncode})")
    return p


def icon(name, size=128, color=(244, 243, 238)):
    """Return an RGBA image of the icon, tinted, cached on disk."""
    hexcol = "#%02x%02x%02x" % color[:3]
    key = hashlib.sha1(f"{name}_{size}_{hexcol}_v1".encode()).hexdigest()[:16]
    png = os.path.join(CACHE, f"{name}_{key}.png")
    if os.path.exists(png) and os.path.getsize(png) > 200:
        return Image.open(png).convert("RGBA")

    svg = open(_svg_path(name), encoding="utf-8").read()
    # swap the stroke colour; lucide ships stroke="currentColor"
    svg = svg.replace('stroke="currentColor"', f'stroke="{hexcol}"')
    cairosvg.svg2png(bytestring=svg.encode("utf-8"), write_to=png,
                     output_width=size, output_height=size)
    return Image.open(png).convert("RGBA")


def paste_icon(img, name, cx, cy, size=128, color=(244, 243, 238), opacity=1.0):
    """Paste a centred icon onto an RGB image."""
    ic = icon(name, size, color)
    if opacity < 1.0:
        a = ic.getchannel("A").point(lambda v: int(v * opacity))
        ic.putalpha(a)
    img.paste(ic, (int(cx - size / 2), int(cy - size / 2)), ic)
    return img


def prefetch():
    for n in USED:
        try:
            icon(n, 128)
        except Exception as e:
            print("warn:", n, e)


if __name__ == "__main__":
    prefetch()
    print("cached in", CACHE)
