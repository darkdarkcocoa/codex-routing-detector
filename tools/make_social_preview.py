"""Render docs/social-preview.png (1280x640), the repository's social preview card, with headless Edge.

Upload the result by hand: Settings > General > Social preview (GitHub has no API for it)."""
import base64, sys, subprocess, tempfile, time
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import codex_routing_fonts as f
HERE = Path(tempfile.mkdtemp(prefix="social-"))
mascot = base64.b64encode((ROOT / "design_handoff_routing_detector_ui/assets/mascot_256.png").read_bytes()).decode()
html = f'''<!doctype html><html><head><meta charset="utf-8"><style>
@font-face {{ font-family: Fredoka; font-weight: 300 700; src: url(data:font/woff2;base64,{f.FONTS["fredoka"]}) format("woff2"); }}
@font-face {{ font-family: "JetBrains Mono"; font-weight: 100 800; src: url(data:font/woff2;base64,{f.FONTS["jetbrains_mono"]}) format("woff2"); }}
html,body {{ margin:0; width:1280px; height:640px; overflow:hidden; }}
body {{ font-family: Fredoka, sans-serif; color:#f3f5fb; position:relative;
  background: radial-gradient(700px 420px at 14% 0%, rgba(124,92,255,.38), transparent 70%),
              radial-gradient(600px 400px at 95% 10%, rgba(255,88,114,.16), transparent 70%),
              radial-gradient(800px 500px at 50% 120%, rgba(60,120,255,.18), transparent 70%),
              linear-gradient(180deg, #080b17, #0d1226); }}
.panel {{ position:absolute; left:48px; top:56px; width:440px; height:528px; border-radius:24px; overflow:hidden;
  background: linear-gradient(160deg, rgba(30,38,72,.85), rgba(22,28,52,.6)); border:1px solid rgba(150,165,255,.18);
  box-shadow: inset 0 1px 0 rgba(255,255,255,.06), 0 24px 50px rgba(3,5,16,.5); }}
.glow {{ position:absolute; left:20px; top:70px; width:400px; height:400px; border-radius:50%;
  background: radial-gradient(circle, rgba(139,123,255,.55), transparent 62%); filter: blur(10px); }}
.ring {{ position:absolute; left:45px; top:95px; width:350px; height:350px; border-radius:50%; border:1.5px solid rgba(185,176,255,.45); }}
.mascot {{ position:absolute; left:10px; bottom:-6px; width:420px; height:420px; object-fit:contain; object-position:50% 100%;
  filter: drop-shadow(0 14px 24px rgba(0,0,0,.55)); }}
.text {{ position:absolute; left:540px; top:96px; right:56px; }}
h1 {{ margin:0; font-family:"Segoe UI Variable Display","Segoe UI",sans-serif; font-size:66px; font-weight:800; letter-spacing:-1.5px; line-height:1.02; color:#ffffff; }}
.tag {{ margin-top:20px; font-size:29px; font-weight:500; color:#c6cce0; line-height:1.3; }}
.rows {{ margin-top:30px; display:flex; flex-direction:column; gap:14px; }}
.row {{ display:inline-flex; align-items:center; gap:16px; padding:12px 22px 12px 14px; border-radius:16px; font-family:"JetBrains Mono"; font-size:25px; font-weight:700;
  width:max-content; background: rgba(22,28,52,.7); border:1px solid rgba(150,165,255,.18); }}
.bad {{ color:#ff5872; border-color: rgba(255,88,114,.45); box-shadow: 0 0 26px rgba(255,88,114,.18); }}
.ok {{ color:#3ee6a0; }}
.chip {{ font-family:Fredoka; font-size:20px; font-weight:700; padding:4px 14px; border-radius:999px; }}
.bad .chip {{ background: rgba(255,88,114,.16); }} .ok .chip {{ background: rgba(62,230,160,.14); }}
.foot {{ position:absolute; left:540px; right:40px; bottom:52px; font-size:21px; line-height:1.5; color:#929bb9; font-weight:500; }}
.foot b {{ color:#b9b0ff; font-weight:600; }}
</style></head><body>
<div class="panel"><div class="glow"></div><div class="ring"></div><img class="mascot" src="data:image/png;base64,{mascot}"></div>
<div class="text">
  <h1>Codex Routing Detector</h1>
  <div class="tag">Did the model you picked really answer?<br>The seer looks through her lens. 🔮</div>
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
