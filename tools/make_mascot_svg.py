"""Build docs/mascot-animated.svg for the READMEs: the mascot PNG with a CSS hop, twinkling
sparkles and a floating heart (still for readers who prefer reduced motion)."""
import base64
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
png = base64.b64encode((ROOT / "design_handoff_routing_detector_ui/assets/mascot_256.png").read_bytes()).decode()

def star(cx, cy, r, color, cls):
    k = r * 0.28
    d = (f"M{cx},{cy - r} Q{cx + k},{cy - k} {cx + r},{cy} Q{cx + k},{cy + k} {cx},{cy + r} "
         f"Q{cx - k},{cy + k} {cx - r},{cy} Q{cx - k},{cy - k} {cx},{cy - r}Z")
    return f'<path class="{cls}" d="{d}" fill="{color}"/>'

heart = ("M0,6 C-7,-1 -13,4 -9,10 C-6,14 0,18 0,20 C0,18 6,14 9,10 C13,4 7,-1 0,6Z")

svg = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 320 300" width="320" height="300" role="img" aria-label="The lavender cat detective">
<style>
.cat {{ animation: hop 1.8s ease-in-out infinite; transform-box: view-box; transform-origin: 160px 270px; }}
.shadow {{ animation: squash 1.8s ease-in-out infinite; transform-box: fill-box; transform-origin: center; }}
.s1, .s2, .s3, .s4 {{ transform-box: fill-box; transform-origin: center; animation: twinkle 2.4s ease-in-out infinite; }}
.s2 {{ animation-delay: .6s; }} .s3 {{ animation-delay: 1.2s; }} .s4 {{ animation-delay: 1.8s; }}
.heart {{ animation: float 3.6s ease-out infinite; transform-box: fill-box; transform-origin: center; }}
@keyframes hop {{
  0%, 100% {{ transform: translateY(0) rotate(0deg); }}
  25% {{ transform: translateY(-5px) rotate(-2deg); }}
  50% {{ transform: translateY(-12px) rotate(0deg); }}
  75% {{ transform: translateY(-5px) rotate(2deg); }}
}}
@keyframes squash {{
  0%, 100% {{ transform: scaleX(1); opacity: .22; }}
  50% {{ transform: scaleX(.8); opacity: .12; }}
}}
@keyframes twinkle {{
  0%, 100% {{ transform: scale(.2) rotate(0deg); opacity: 0; }}
  30% {{ transform: scale(1) rotate(20deg); opacity: 1; }}
  60% {{ transform: scale(.6) rotate(45deg); opacity: .7; }}
}}
@keyframes float {{
  0% {{ transform: translate(0, 0) scale(.4); opacity: 0; }}
  15% {{ transform: translate(2px, -6px) scale(1); opacity: 1; }}
  70% {{ transform: translate(-6px, -40px) scale(1); opacity: .8; }}
  100% {{ transform: translate(4px, -60px) scale(.8); opacity: 0; }}
}}
@media (prefers-reduced-motion: reduce) {{
  .cat, .shadow, .s1, .s2, .s3, .s4, .heart {{ animation: none; }}
}}
</style>
<ellipse class="shadow" cx="160" cy="280" rx="70" ry="9" fill="#8a7aa8"/>
<g class="cat"><image x="32" y="20" width="256" height="256" href="data:image/png;base64,{png}"/></g>
{star(40, 70, 14, "#f6c453", "s1")}
{star(286, 118, 11, "#b9a4f0", "s2")}
{star(62, 196, 9, "#8fd3c9", "s3")}
{star(270, 40, 8, "#f5a3c0", "s4")}
<g transform="translate(236 150)"><path class="heart" d="{heart}" fill="#f5a3c0"/></g>
</svg>
'''
out = ROOT / "docs/mascot-animated.svg"
out.write_text(svg, encoding="utf-8", newline="\n")
print(out, len(svg))
