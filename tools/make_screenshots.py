"""Render the README screenshots (docs/screenshot*.png, 1240x1005) with headless Edge.

The window's own page is loaded with a stand-in for pywebview's API (webui.preview_page) that hands it a
view model from a real WebApp in --fake mode: the bundled fixture runs for the check tab, the made-up
--fake-live responses for the live tab. Nothing is sent to OpenAI. Windows only (Edge)."""
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import codex_routing_detector_gui as gui
import codex_routing_webui as webui

EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
# CSS animations (tab slide, card pop, row stagger) end at once, so a capture never lands mid-way
FREEZE = ("<style>*, *::before, *::after { animation-duration: 0s !important; animation-delay: 0s !important;"
          " transition: none !important; }</style>")


def wait(pred, seconds=20.0):
    end = time.time() + seconds
    while time.time() < end:
        if pred():
            return
        time.sleep(0.05)
    sys.exit("the sample data did not arrive in time")


def shot(work: Path, data: dict, out: str, after: str = "") -> None:
    page = work / (Path(out).stem + ".html")
    page.write_text(webui.preview_page(dict(data, showGuide=False), after).replace("</head>", FREEZE + "</head>"),
                    encoding="utf-8")
    png = work / out  # the old screenshot stays until a new one exists
    subprocess.run([EDGE, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--window-size=1240,1005",
                    "--virtual-time-budget=8000", f"--user-data-dir={work / 'edge'}",
                    f"--screenshot={png}", page.as_uri()], capture_output=True, timeout=90)
    end = time.time() + 30
    while not png.exists() and time.time() < end:
        time.sleep(0.5)
    if not png.exists():
        sys.exit(f"Edge wrote no {out}")
    time.sleep(0.5)  # let Edge finish writing
    shutil.move(str(png), str(ROOT / "docs" / out))
    print(ROOT / "docs" / out, (ROOT / "docs" / out).stat().st_size)


def main() -> None:
    if not Path(EDGE).exists():
        sys.exit(f"Edge not found at {EDGE}")
    if not gui.install_fake_runner():
        sys.exit("tests/fixtures not found")
    with tempfile.TemporaryDirectory(prefix="shots-") as tmp:
        work = Path(tmp)
        os.environ[gui.SETTINGS_ENV] = str(work / "settings.json")  # never the user's own settings
        for lang, suffix in (("en", ""), ("ko", "-ko")):
            app = webui.WebApp(lang=lang, fake=True, update_check=False, confirm=False)
            try:
                data = app.init()
                app.set_option("model", "gpt-6-astra")
                app.start_check(confirm=False)
                wait(lambda: app.worker is None and app.result is not None)
                app.start_live(confirm=False)
                wait(lambda: app.monitor is not None and app.monitor.proc is not None)
                app.monitor.proc.pid = 21884  # the stand-in Codex process has none; a real session shows its pid
                webui.feed_fake_live(app)
                wait(lambda: len(app.build_vm()["live"]["rows"]) == 3)
                data["vm"] = app.build_vm()
                shot(work, data, f"screenshot{suffix}.png")
                shot(work, data, f"screenshot-live{suffix}.png", "selectTab('live');")
                app.stop_live()
                wait(lambda: not app.build_vm()["live"]["on"])
                data["vm"] = app.build_vm()
                shot(work, data, f"screenshot-guide{suffix}.png", "selectTab('live'); showGuide();")
            finally:
                app.shutdown()


if __name__ == "__main__":
    main()
