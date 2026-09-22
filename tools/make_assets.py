#!/usr/bin/env python3
"""Build codex_routing_assets.py (base64 PNGs) and docs/icon.ico from the source pictures.

Usage: python tools/make_assets.py SOURCE_DIR
SOURCE_DIR holds mascot.png, mood_ok.png, mood_rerouted.png, mood_idle.png, mood_error.png
(any size, transparent background). Needs Pillow at build time only; the app itself does not.
"""
import base64
import io
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
SIZES = {"mascot": (72, 96, 256), "mood_ok": (56,), "mood_rerouted": (56,), "mood_idle": (56,), "mood_error": (56,),
         "sticker_flower": (26, 44), "sticker_leaf": (26, 44), "sticker_sparkle": (26, 44), "sticker_heart": (26, 44)}


def trim(img: Image.Image) -> Image.Image:
    """Crop to the non-transparent content and make it square."""
    img = img.convert("RGBA")
    box = img.getbbox()
    if box:
        img = img.crop(box)
    w, h = img.size
    side = max(w, h)
    square = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    square.paste(img, ((side - w) // 2, (side - h) // 2))
    return square


def main(src: str) -> int:
    src_dir = Path(src)
    images = {}
    icon_frames = []
    for name, sizes in SIZES.items():
        path = src_dir / f"{name}.png"
        if not path.exists():
            print(f"missing {path}", file=sys.stderr)
            continue
        base = trim(Image.open(path))
        for size in sizes:
            small = base.resize((size, size), Image.LANCZOS)
            buf = io.BytesIO()
            small.save(buf, format="PNG", optimize=True)
            images[f"{name}_{size}"] = base64.b64encode(buf.getvalue()).decode("ascii")
            if name == "mascot":
                icon_frames.append(small)
    if icon_frames:
        ico = ROOT / "docs" / "icon.ico"
        big = trim(Image.open(src_dir / "mascot.png"))
        big.resize((256, 256), Image.LANCZOS).save(ico, format="ICO", sizes=[(256, 256), (64, 64), (48, 48), (32, 32), (16, 16)])
        print(f"wrote {ico}")
    out = ROOT / "codex_routing_assets.py"
    lines = ['"""Pictures used by the window (mascot and its moods), embedded as base64 PNG so the single-file',
             'exe needs no image files. Regenerate with tools/make_assets.py from the source PNGs."""',
             "IMAGES: dict = {"]
    for key, data in images.items():
        lines.append(f'    "{key}": (')
        for i in range(0, len(data), 100):
            lines.append(f'        "{data[i:i + 100]}"')
        lines.append("    ),")
    lines.append("}")
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    total = sum(len(v) for v in images.values())
    print(f"wrote {out} ({len(images)} images, {total // 1024} KB of base64)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "."))
