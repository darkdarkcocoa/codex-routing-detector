"""Render docs/social-preview.png (1280x640), the repository's social preview card, with headless Edge.

Upload the result by hand: Settings > General > Social preview (GitHub has no API for it)."""
import base64, sys, subprocess, tempfile, time
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import codex_routing_fonts as f
HERE = Path(tempfile.mkdtemp(prefix="social-"))
mascot = base64.b64encode((ROOT / "design_handoff_routing_detector_ui/assets/mascot_256.png").read_bytes()).decode()
def star(cx, cy, r, color):
    k = r * .28
    return (f'<path d="M{cx},{cy-r} Q{cx+k},{cy-k} {cx+r},{cy} Q{cx+k},{cy+k} {cx},{cy+r} Q{cx-k},{cy+k} {cx-r},{cy} '
            f'Q{cx-k},{cy-k} {cx},{cy-r}Z" fill="{color}"/>')
html = f'''<!doctype html><html><head><meta charset="utf-8"><style>
@font-face {{ font-family: Fredoka; font-weight: 300 700; src: url(data:font/woff2;base64,{f.FONTS["fredoka"]}) format("woff2"); }}
@font-face {{ font-family: "JetBrains Mono"; font-weight: 100 800; src: url(data:font/woff2;base64,{f.FONTS["jetbrains_mono"]}) format("woff2"); }}
html,body {{ margin:0; width:1280px; height:640px; overflow:hidden; }}
body {{ background: radial-gradient(circle at 22% 45%, #ffffff 0, #f4f6f2 38%, #e9efe8 100%); font-family: Fredoka, sans-serif; color:#2f3a36; position:relative; }}
.cat {{ position:absolute; left:70px; top:120px; width:400px; height:400px; }}
.shadow {{ position:absolute; left:150px; top:505px; width:240px; height:26px; border-radius:50%; background:#8a7aa8; opacity:.18; }}
svg.deco {{ position:absolute; left:0; top:0; }}
.text {{ position:absolute; left:520px; top:78px; right:60px; }}
h1 {{ margin:0; font-size:68px; font-weight:700; letter-spacing:-1.5px; line-height:1; }}
.tag {{ margin-top:20px; font-size:31px; font-weight:500; color:#55605b; line-height:1.25; }}
.rows {{ margin-top:30px; display:flex; flex-direction:column; gap:14px; }}
.row {{ display:inline-flex; align-items:center; gap:16px; padding:12px 22px; border-radius:999px; font-family:"JetBrains Mono"; font-size:25px; font-weight:600; width:max-content; }}
.bad {{ background:#fdecec; color:#9b2c2c; }} .ok {{ background:#e6f4ec; color:#23704a; }}
.chip {{ font-family:Fredoka; font-size:22px; font-weight:600; padding:4px 14px; border-radius:999px; background:#ffffff; }}
.foot {{ position:absolute; left:520px; right:40px; bottom:40px; font-size:22px; line-height:1.45; color:#6b7671; font-weight:500; }}
.foot b {{ color:#2a7d96; font-weight:600; }}
</style></head><body>
<div class="shadow"></div>
<img class="cat" src="data:image/png;base64,{mascot}">
<svg class="deco" width="1280" height="640">{star(96,150,22,"#f6c453")}{star(62,330,15,"#b9a4f0")}{star(118,470,13,"#8fd3c9")}{star(430,110,11,"#f5a3c0")}{star(1210,80,14,"#b9a4f0")}{star(1180,560,18,"#f6c453")}</svg>
<div class="text">
  <h1>Codex Routing Detector</h1>
  <div class="tag">Did the model you picked really answer?<br>The cat detective checks for you. 🔍</div>
  <div class="rows">
    <div class="row bad"><span class="chip">Rerouted</span>gpt-6-astra → gpt-5.6-luna</div>
    <div class="row ok"><span class="chip">All good</span>gpt-6-astra → gpt-6-astra</div>
  </div>
</div>
<div class="foot">Free &amp; open source · Windows app + CLI<br><b>github.com/darkdarkcocoa/codex-routing-detector</b></div>
</body></html>'''
(HERE / "social.html").write_text(html, encoding="utf-8")
EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
out = ROOT / "docs" / "social-preview.png"; out.unlink(missing_ok=True)
subprocess.run([EDGE, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--window-size=1280,640", "--virtual-time-budget=3000",
                f"--user-data-dir={tempfile.mkdtemp()}", f"--screenshot={out}", (HERE / "social.html").as_uri()], capture_output=True, timeout=60)
end = time.time() + 30
while not out.exists() and time.time() < end: time.sleep(.5)
time.sleep(1); print(out, out.stat().st_size)
