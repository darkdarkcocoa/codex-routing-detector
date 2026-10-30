#!/usr/bin/env python3
"""Build codex_routing_assets.py (base64 pictures) and docs/icon.ico from the source pictures.

Usage: python tools/make_assets.py [SOURCE_DIR]   (default: art/source)
SOURCE_DIR holds mascot.png, mood_ok.png, mood_rerouted.png, mood_idle.png, mood_error.png (any size,
transparent background), optionally icon.png (a closer crop for the window icon; mascot.png otherwise),
mascot_anim.webp (the animated mascot, embedded as it is; the READMEs show this very file) and the
sticker_*.png decorations. A picture whose source is missing keeps its current data, so the stickers need
no source to rebuild the rest. It also writes the copies the READMEs and the design handoff show
(docs/mood-*.png, docs/mascot.png, design_handoff_routing_detector_ui/assets/), so they never fall
behind. Needs Pillow at build time only; the app itself does not.
"""
import base64
import io
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
# (size, format) of each embedded copy. The PNGs also serve the tkinter window, which reads only PNG;
# the 256px moods fill the web window's verdict card, where WebP keeps them small (the idle card shows
# the animation instead, so the idle mood is only needed small).
MOOD = ((56, "png"), (256, "webp"))
SIZES = {"mascot": ((72, "png"), (96, "png"), (256, "png")),
         "mood_ok": MOOD, "mood_rerouted": MOOD, "mood_idle": ((56, "png"),), "mood_error": MOOD,
         "sticker_flower": ((26, "png"), (44, "png")), "sticker_leaf": ((26, "png"), (44, "png")),
         "sticker_sparkle": ((26, "png"), (44, "png")), "sticker_heart": ((26, "png"), (44, "png"))}
ANIMATIONS = ("mascot_anim",)
# copies outside the program: path -> embedded picture
COPIES = {"docs/mascot.png": "mascot_256",
          **{f"docs/mood-{m}.png": f"mood_{m}_56" for m in ("ok", "rerouted", "error")},
          **{f"design_handoff_routing_detector_ui/assets/{k}.png": k
             for k in ("mascot_72", "mascot_96", "mascot_256",
                       "mood_ok_56", "mood_rerouted_56", "mood_idle_56", "mood_error_56")}}


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


def encode(img: Image.Image, fmt: str) -> bytes:
    buf = io.BytesIO()
    if fmt == "webp":
        img.save(buf, format="WEBP", quality=85, method=6)
    else:
        img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def current_images() -> dict:
    """The pictures embedded now. A broken assets file stops the build: carrying on would silently
    drop every picture that has no source (the stickers)."""
    try:
        import codex_routing_assets
    except ModuleNotFoundError:
        return {}
    return dict(codex_routing_assets.IMAGES)


def main(src: str) -> int:
    src_dir = Path(src)
    old = current_images()
    images = {}
    for name, sizes in SIZES.items():
        path = src_dir / f"{name}.png"
        if not path.exists():
            kept = [f"{name}_{size}" for size, _ in sizes if f"{name}_{size}" in old]
            images.update({k: old[k] for k in kept})
            print(f"no {path}: kept {', '.join(kept) or 'nothing'}", file=sys.stderr)
            continue
        base = trim(Image.open(path))
        for size, fmt in sizes:
            small = base.resize((size, size), Image.LANCZOS)
            images[f"{name}_{size}"] = base64.b64encode(encode(small, fmt)).decode("ascii")
    for name in ANIMATIONS:
        path = src_dir / f"{name}.webp"
        if path.exists():
            images[name] = base64.b64encode(path.read_bytes()).decode("ascii")
        elif name in old:
            images[name] = old[name]
            print(f"no {path}: kept {name}", file=sys.stderr)
    missing = sorted({key for key in COPIES.values() if key not in images})
    if missing:  # check before writing anything, so a failed run leaves every file as it was
        print(f"no source and no current data for {', '.join(missing)}: nothing written", file=sys.stderr)
        return 1
    icon_src = next((p for p in (src_dir / "icon.png", src_dir / "mascot.png") if p.exists()), None)
    if icon_src:
        ico = ROOT / "docs" / "icon.ico"
        trim(Image.open(icon_src)).resize((256, 256), Image.LANCZOS).save(
            ico, format="ICO", sizes=[(256, 256), (64, 64), (48, 48), (32, 32), (16, 16)])
        print(f"wrote {ico}")
    out = ROOT / "codex_routing_assets.py"
    lines = ['"""Pictures used by the window (mascot, its moods and its animation), embedded as base64 PNG and',
             'WebP so the single-file exe needs no image files. Regenerate with tools/make_assets.py from art/source."""',
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
    for path, key in COPIES.items():
        (ROOT / path).write_bytes(base64.b64decode(images[key]))
    print(f"wrote {len(COPIES)} copies in docs/ and design_handoff_routing_detector_ui/assets/")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else str(ROOT / "art" / "source")))
