#!/usr/bin/env python3
"""
Regenerate the mascot assets from pepe_cry.png.

Development-time only -- needs Pillow (`pip install pillow`). The app itself
stays stdlib-only and just loads the PNG/ICO files this script writes into
assets/.

    python tools/make_assets.py
"""

import os
import sys

from PIL import Image, ImageDraw

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCE = os.path.join(ROOT, "pepe_cry.png")
ASSETS = os.path.join(ROOT, "assets")

# Sizes the UI loads directly with tk.PhotoImage.
PNG_SIZES = (48, 96)
# Sizes embedded in the .ico for the window, taskbar, exe and installer.
ICO_SIZES = (16, 24, 32, 48, 64, 128, 256)
# How far a pixel may stray from pure white and still count as background.
FLOOD_TOLERANCE = 30


def cut_background(image: Image.Image) -> Image.Image:
    """Flood-fill the outer white away, leaving the frog on transparency.

    Filling from all four edges rather than thresholding every white pixel
    keeps the enclosed whites -- the eye highlights -- intact.
    """
    out = image.convert("RGBA")
    width, height = out.size
    edges = (
        [(x, 0) for x in range(width)]
        + [(x, height - 1) for x in range(width)]
        + [(0, y) for y in range(height)]
        + [(width - 1, y) for y in range(height)]
    )
    for seed in edges:
        if out.getpixel(seed)[3] == 0:
            continue                      # already cleared by an earlier seed
        ImageDraw.floodfill(out, seed, (0, 0, 0, 0), thresh=FLOOD_TOLERANCE)
    return out


def trim(image: Image.Image) -> Image.Image:
    """Crop to the visible pixels so the mascot fills its box."""
    bbox = image.split()[3].getbbox()
    return image.crop(bbox) if bbox else image


def square(image: Image.Image) -> Image.Image:
    """Pad to a square so every scaled copy keeps the aspect ratio."""
    width, height = image.size
    side = max(width, height)
    canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    canvas.paste(image, ((side - width) // 2, (side - height) // 2))
    return canvas


def main() -> int:
    if not os.path.exists(SOURCE):
        print(f"missing source image: {SOURCE}", file=sys.stderr)
        return 1

    os.makedirs(ASSETS, exist_ok=True)
    mascot = square(trim(cut_background(Image.open(SOURCE))))
    print(f"source {Image.open(SOURCE).size} -> trimmed square {mascot.size}")

    for size in PNG_SIZES:
        path = os.path.join(ASSETS, f"mascot_{size}.png")
        mascot.resize((size, size), Image.LANCZOS).save(path)
        print(f"wrote {os.path.relpath(path, ROOT)}")

    ico_path = os.path.join(ASSETS, "mascot.ico")
    mascot.save(ico_path, sizes=[(s, s) for s in ICO_SIZES])
    print(f"wrote {os.path.relpath(ico_path, ROOT)} ({len(ICO_SIZES)} sizes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
