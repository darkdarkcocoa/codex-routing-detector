#!/usr/bin/env python3
"""Turn the mascot art, drawn on a flat pure green (#00FF00) background, into transparent pictures.

Usage:
  python tools/key_green.py image RAW.png OUT.png [--crop X0,Y0,X1,Y1] [--max 384]
  python tools/key_green.py grid RAW.png OUT_DIR NAME NAME NAME NAME [--max 384]   # 2x2 sheet, cells left to right
  python tools/key_green.py frames VIDEO.mp4 OUT.webp FIRST LAST [--fps 12] [--size 200] [--step 2] [--fade 0]

The image generators cannot draw real transparency (they paint a checkerboard instead), so the art is
drawn on green and keyed here. --crop cuts the keyed picture (before --max), --max shrinks it so its
longer side is at most that many pixels (the sources in art/source are 384). `frames` keys every frame
of a short video the same way and writes an animated WebP that loops (ffmpeg reads the video); --fade folds that many end frames into the start, for
a clip whose last frame does not already match its first. Needs numpy and Pillow at build time only.
"""
import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

# share of the art below which an edge pixel is dropped: compression noise in the background otherwise
# leaves faint specks
ALPHA_FLOOR = 0.08
QUALITY = 70  # WebP quality of the animation frames


def key_rgba(img: Image.Image) -> Image.Image:
    """The picture with its green background made transparent and the green taken out of its edges.

    Only a pixel whose green stands above both red and blue holds background. The art's own colours keep
    their green between red and blue (skin, hair, lavender, gold, white), so the green above the middle
    of red and blue is taken as the background's share: an edge pixel that is a share t of the art over
    #00FF00 has red t*R, blue t*B and green about t*(R+B)/2 + (1-t)*255.
    """
    a = np.asarray(img.convert("RGB")).astype(np.float32)
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    mixed = g > np.maximum(r, b)
    mid = (r + b) / 2.0
    t = np.where(mixed, np.clip(1.0 - (g - mid) / 255.0, 0.0, 1.0), 1.0)
    safe = np.maximum(t, 1e-3)
    r = np.where(mixed, r / safe, r)
    b = np.where(mixed, b / safe, b)
    g = np.where(mixed, np.minimum(mid / safe, np.maximum(r, b)), g)
    alpha = np.clip((t - ALPHA_FLOOR) / (1.0 - ALPHA_FLOOR), 0.0, 1.0)
    rgb = np.where(alpha[..., None] > 0, np.dstack([r, g, b]), 0.0)  # fully transparent: no stray colour
    rgba = np.dstack([rgb, alpha * 255.0]).round().clip(0, 255).astype(np.uint8)
    return Image.fromarray(rgba, "RGBA")


def content_box(img: Image.Image):
    """The box around the visible content, ignoring faint specks, or None when nothing is visible."""
    return img.getchannel("A").point(lambda v: 255 if v > 24 else 0).getbbox()


def key(img: Image.Image) -> Image.Image:
    """key_rgba(), cropped to the content."""
    out = key_rgba(img)
    box = content_box(out)
    return out.crop(box) if box else out


def square(img: Image.Image, margin: float = 0.04) -> Image.Image:
    """The picture centered on a transparent square with a small margin."""
    w, h = img.size
    side = int(max(w, h) * (1 + 2 * margin))
    sq = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    sq.paste(img, ((side - w) // 2, (side - h) // 2))
    return sq


def crossfade_loop(frames, n: int):
    """Fold the last n frames into the first n, so the end of the loop runs smoothly into its start."""
    if n <= 0 or len(frames) <= 2 * n:
        return frames
    body = frames[:len(frames) - n]
    tail = frames[len(frames) - n:]
    out = []
    for i, (head, end) in enumerate(zip(body[:n], tail)):
        t = (i + 1) / (n + 1)  # share of the start frame
        a = np.asarray(head).astype(np.float32)
        b = np.asarray(end).astype(np.float32)
        # blend in premultiplied alpha, or a fading edge would pick up the colour of transparent pixels
        pa = a[..., :3] * a[..., 3:] / 255.0
        pb = b[..., :3] * b[..., 3:] / 255.0
        alpha = a[..., 3:] * t + b[..., 3:] * (1 - t)
        rgb = (pa * t + pb * (1 - t)) * 255.0 / np.maximum(alpha, 1e-3)
        out.append(Image.fromarray(np.dstack([rgb, alpha]).round().clip(0, 255).astype(np.uint8), "RGBA"))
    return out + body[n:]


def shrink(img: Image.Image, longest: int) -> Image.Image:
    """The picture with its longer side at most `longest` pixels (0: unchanged)."""
    w, h = img.size
    if not longest or max(w, h) <= longest:
        return img
    s = longest / max(w, h)
    small = np.asarray(img.resize((round(w * s), round(h * s)), Image.LANCZOS)).copy()
    small[small[..., 3] < 3] = 0  # resampling leaves near-invisible pixels with stray colour
    return Image.fromarray(small, "RGBA")


def cmd_image(args) -> None:
    img = key(Image.open(args.raw))
    if args.crop:
        img = img.crop(tuple(int(v) for v in args.crop.split(",")))
    shrink(img, args.max).save(args.out, optimize=True)
    print(f"wrote {args.out}")


def cmd_grid(args) -> None:
    img = Image.open(args.raw).convert("RGB")
    w, h = img.size
    for name, (cx, cy) in zip(args.names, [(0, 0), (1, 0), (0, 1), (1, 1)]):
        cell = img.crop((cx * w // 2, cy * h // 2, (cx + 1) * w // 2, (cy + 1) * h // 2))
        path = Path(args.out_dir) / f"{name}.png"
        shrink(key(cell), args.max).save(path, optimize=True)
        print(f"wrote {path}")


def cmd_frames(args) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run(["ffmpeg", "-loglevel", "error", "-i", args.video, str(Path(tmp) / "f%04d.png")], check=True)
        files = sorted(Path(tmp).glob("f*.png"))
        picked = files[args.first:args.last + 1:args.step]
        if not picked:
            sys.exit(f"no frames between {args.first} and {args.last}: the video has {len(files)}")
        keyed = [key_rgba(Image.open(f)) for f in picked]
    # one crop box for every frame, so the character does not jump between frames
    boxes = [b for b in (content_box(k) for k in keyed) if b]
    if not boxes:
        sys.exit("every frame is plain background: nothing to key")
    x0, y0 = min(b[0] for b in boxes), min(b[1] for b in boxes)
    x1, y1 = max(b[2] for b in boxes), max(b[3] for b in boxes)
    frames = [square(k.crop((x0, y0, x1, y1))).resize((args.size, args.size), Image.LANCZOS) for k in keyed]
    frames = crossfade_loop(frames, args.fade)
    frames[0].save(args.out, save_all=True, append_images=frames[1:], duration=round(1000 / args.fps), loop=0,
                   lossless=False, quality=QUALITY, method=6, minimize_size=True, allow_mixed=True)
    print(f"wrote {args.out} ({len(frames)} frames, {Path(args.out).stat().st_size // 1024} KB)")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("image", help="key one picture")
    p.add_argument("raw")
    p.add_argument("out")
    p.add_argument("--crop", help="X0,Y0,X1,Y1 in the keyed picture")
    p.add_argument("--max", type=int, default=0)
    p.set_defaults(run=cmd_image)
    p = sub.add_parser("grid", help="key the four cells of a 2x2 sheet")
    p.add_argument("raw")
    p.add_argument("out_dir")
    p.add_argument("names", nargs=4)
    p.add_argument("--max", type=int, default=0)
    p.set_defaults(run=cmd_grid)
    p = sub.add_parser("frames", help="key a video into a looping animated WebP")
    p.add_argument("video")
    p.add_argument("out")
    p.add_argument("first", type=int)
    p.add_argument("last", type=int)
    p.add_argument("--fps", type=int, default=12)
    p.add_argument("--size", type=int, default=200)
    p.add_argument("--step", type=int, default=2)
    p.add_argument("--fade", type=int, default=0)
    p.set_defaults(run=cmd_frames)
    args = ap.parse_args(argv)
    args.run(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
