#!/usr/bin/env python3
"""Build the seer's idle loop (an animated WebP) from two stills, without a video model.

Usage: python tools/make_idle_loop.py MAIN_RAW.png BLINK_RAW.png OUT.webp [--size 240] [--fps 12] [--seconds 6]

MAIN_RAW is the main picture on flat #00FF00, BLINK_RAW the same picture with her eyes closed (an image
edit of MAIN_RAW). Both are keyed with tools/key_green.py. Only the eyes are taken from BLINK_RAW (where
the two differ around the face), so the rest of the picture never drifts between frames. On top come
effects drawn here: slow breathing, one blink, a glint sliding across the scrying lens, the moonstone
under it pulsing and a few motes of light rising from the staff. Every effect repeats with the loop, so
the last frame leads straight back into the first. Needs numpy and Pillow at build time only.
"""
import argparse
import math
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter

sys.path.insert(0, str(Path(__file__).resolve().parent))
from key_green import key_rgba  # noqa: E402

# Where the staff's lens and moonstone sit, as fractions of the square main picture (2026-11-26 render).
LENS = (0.379, 0.215, 0.086)       # centre x, centre y, radius
MOONSTONE = (0.368, 0.349, 0.018)
EYES_BOX = (0.26, 0.15, 0.72, 0.33)  # where the blink may differ: both eyes, the one in the lens too
WORK = 480                          # frames are drawn at twice the output size, then shrunk


def eye_mask(main: Image.Image, blink: Image.Image) -> Image.Image:
    """Where the closed eyes differ from the open ones, inside the eye box, feathered."""
    diff = ImageChops.difference(main.convert("RGB"), blink.convert("RGB")).convert("L")
    d = np.asarray(diff.filter(ImageFilter.GaussianBlur(2)), dtype=np.float32)
    w, h = main.size
    x0, y0, x1, y1 = (int(EYES_BOX[0] * w), int(EYES_BOX[1] * h), int(EYES_BOX[2] * w), int(EYES_BOX[3] * h))
    keep = np.zeros_like(d)
    keep[y0:y1, x0:x1] = (d[y0:y1, x0:x1] > 18).astype(np.float32) * 255
    mask = Image.fromarray(keep.astype(np.uint8)).filter(ImageFilter.MaxFilter(9)).filter(ImageFilter.GaussianBlur(4))
    return mask


def glow(size: int, color: tuple, radius: float) -> Image.Image:
    """A soft round glow, `radius` in pixels, on a transparent square."""
    yy, xx = np.mgrid[0:size, 0:size].astype(np.float32)
    c = (size - 1) / 2
    a = np.clip(1 - np.hypot(xx - c, yy - c) / radius, 0, 1) ** 2
    out = np.zeros((size, size, 4), np.uint8)
    out[..., :3] = color
    out[..., 3] = (a * 255).astype(np.uint8)
    return Image.fromarray(out, "RGBA")


def lens_glint(size: int, t: float) -> Image.Image:
    """A diagonal band of light at position t (0..1) across the lens, clipped to the glass."""
    cx, cy, r = LENS[0] * size, LENS[1] * size, LENS[2] * size * 0.9
    layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    band = Image.new("L", (size, size), 0)
    d = ImageDraw.Draw(band)
    x = cx - 1.6 * r + t * 3.2 * r
    w = r * 0.34
    d.polygon([(x - w, cy - r * 1.2), (x + w, cy - r * 1.2), (x + w - r * 0.9, cy + r * 1.2), (x - w - r * 0.9, cy + r * 1.2)], fill=200)
    band = band.filter(ImageFilter.GaussianBlur(r * 0.12))
    clip = Image.new("L", (size, size), 0)
    ImageDraw.Draw(clip).ellipse((cx - r, cy - r, cx + r, cy + r), fill=255)
    layer.putalpha(ImageChops.multiply(band, clip))
    white = Image.new("RGBA", (size, size), (255, 250, 235, 0))
    white.putalpha(layer.getchannel("A"))
    return white


def frame(base: Image.Image, closed: Image.Image, mask: Image.Image, i: int, n: int) -> Image.Image:
    size = base.width
    phase = i / n
    # one blink, a third of the way in: half, closed, closed, half
    blink = {int(n * .38): .55, int(n * .38) + 1: 1.0, int(n * .38) + 2: 1.0, int(n * .38) + 3: .5}.get(i, 0.0)
    pic = base
    if blink:
        m = mask.point(lambda v: int(v * blink))
        pic = Image.composite(closed, base, m)
    # breathing: a slow rise of the chest, anchored at the bottom edge
    s = 1 + 0.007 * (0.5 - 0.5 * math.cos(2 * math.pi * phase))
    h = round(size * s)
    breathed = pic.resize((size, h), Image.LANCZOS).crop((0, h - size, size, h))
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    out.alpha_composite(breathed)
    # light on the staff head: the moonstone pulses, a glint sweeps the lens once per loop
    pulse = 0.35 + 0.35 * (0.5 - 0.5 * math.cos(2 * math.pi * phase * 2))
    g = glow(int(size * 0.12), (226, 214, 255), size * 0.06)
    g.putalpha(g.getchannel("A").point(lambda v: int(v * pulse)))
    out.alpha_composite(g, (int(MOONSTONE[0] * size - g.width / 2), int(MOONSTONE[1] * size - g.height / 2)))
    if 0.08 <= phase <= 0.30:
        out.alpha_composite(lens_glint(size, (phase - 0.08) / 0.22))
    # motes of light drifting up from the staff head, each on its own loop
    motes = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(motes)
    for k in range(6):
        p = (phase + k / 6) % 1
        x = LENS[0] * size + math.sin(2 * math.pi * (p * 1.3 + k * .37)) * size * 0.06 + (k - 2.5) * size * 0.018
        y = (LENS[1] + LENS[2] * 1.1) * size - p * size * 0.30
        a = int(220 * math.sin(math.pi * p))
        rr = size * (0.006 + 0.003 * (k % 3))
        d.ellipse((x - rr * 2.2, y - rr * 2.2, x + rr * 2.2, y + rr * 2.2), fill=(255, 214, 140, a // 5))
        d.ellipse((x - rr, y - rr, x + rr, y + rr), fill=(255, 240, 200, a))
    out.alpha_composite(motes.filter(ImageFilter.GaussianBlur(0.6)))
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("main"); ap.add_argument("blink"); ap.add_argument("out")
    ap.add_argument("--size", type=int, default=240)
    ap.add_argument("--fps", type=int, default=12)
    ap.add_argument("--seconds", type=float, default=6)
    a = ap.parse_args(argv)
    main_raw, blink_raw = Image.open(a.main).convert("RGB"), Image.open(a.blink).convert("RGB")
    if blink_raw.size != main_raw.size:
        blink_raw = blink_raw.resize(main_raw.size, Image.LANCZOS)
    mask = eye_mask(main_raw, blink_raw)
    base = key_rgba(main_raw).resize((WORK, WORK), Image.LANCZOS)
    closed = key_rgba(blink_raw).resize((WORK, WORK), Image.LANCZOS)
    mask = mask.resize((WORK, WORK), Image.LANCZOS)
    n = round(a.fps * a.seconds)
    # cut to her outline made square, as tools/make_assets.py does with the stills, so the loop and the
    # mood pictures stand at the same size in the card
    x0, y0, x1, y1 = base.getchannel("A").point(lambda v: 255 if v > 20 else 0).getbbox()
    side = max(x1 - x0, y1 - y0)
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    box = (round(cx - side / 2), round(cy - side / 2), round(cx + side / 2), round(cy + side / 2))
    frames = [frame(base, closed, mask, i, n).crop(box).resize((a.size, a.size), Image.LANCZOS) for i in range(n)]
    frames[0].save(a.out, save_all=True, append_images=frames[1:], duration=round(1000 / a.fps), loop=0,
                   format="WEBP", quality=72, method=6, lossless=False)
    print(f"wrote {a.out}: {n} frames, {a.size}px, {Path(a.out).stat().st_size // 1024} KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
