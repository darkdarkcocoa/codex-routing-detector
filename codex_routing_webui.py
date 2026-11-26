#!/usr/bin/env python3
"""codex-routing-detector web UI ("Soft Sheet"): a pywebview window, Python keeps all the logic.

The window is an embedded browser page (design: design_handoff_routing_detector_ui). All
checking, monitoring and reporting stays in Python (codex_routing_detector / codex_routing_live);
the page only renders a view model pushed from here and calls back through pywebview's js_api.

Falls back to the tkinter window (codex_routing_detector_gui) when pywebview or a web engine is
not available.

Flags: --lang ko|en starts in that language. Development-only flags:
  --fake          feed the bundled fixture runs instead of launching codex (no quota, no network)
  --auto-check    press Check as soon as the window is up
  --auto-live     start the live monitor as soon as the window is up
  --fake-live     with --fake: feed made-up live responses (screenshots)
  --exit-after S  close the window S seconds after a check finished (or failed to start)
"""
from __future__ import annotations

import argparse
import json
import os
import queue
import sys
import threading
import time
import webbrowser
from pathlib import Path
from typing import Dict, List, Optional

import codex_routing_assets as assets
import codex_routing_fonts as fonts
import codex_routing_webtext as webtext
import codex_routing_detector as cmc
import codex_routing_detector_gui as tkgui  # shared strings, briefing and settings helpers
import codex_routing_live as live
import codex_routing_proxy as crp

APP_TITLE = tkgui.APP_TITLE
REPO_URL = tkgui.REPO_URL
EFFORTS = tkgui.EFFORTS  # offered for a model the catalog does not describe
# "ultra" makes the model spawn sub-agents at max effort: far too costly for a one-word probe.
PROBE_EXCLUDED_EFFORTS = {"ultra"}


def catalog_efforts() -> Dict[str, List[str]]:
    """Reasoning efforts each model supports, from Codex's own catalog cache (models_cache.json),
    without the ones a probe should never use. Empty when the cache is missing or unreadable."""
    try:
        data = json.loads((cmc.codex_home() / "models_cache.json").read_text(encoding="utf-8"))
    except Exception:
        return {}
    out: Dict[str, List[str]] = {}
    for m in data.get("models", []) if isinstance(data, dict) else []:
        if not isinstance(m, dict) or not m.get("slug"):
            continue
        levels: List[str] = []
        for lv in m.get("supported_reasoning_levels") or []:
            name = lv.get("effort") if isinstance(lv, dict) else lv
            if isinstance(name, str) and name and name not in PROBE_EXCLUDED_EFFORTS and name not in levels:
                levels.append(name)
        if levels:
            out[str(m["slug"])] = levels
    return out
MAX_REPEAT = tkgui.MAX_REPEAT

# ------------------------------------------------------------------ UI strings
# Labels and headlines of the redesigned page (the briefing paragraphs, help texts and
# confirmation dialogs reuse tkgui.STRINGS / HELP_* so both UIs stay in step).
UI: Dict[str, Dict[str, str]] = {
    "ko": {
        "subtitle": "내 요청에 실제로 답한 모델은?",
        "tabCheck": "검사", "tabLive": "라이브 모니터",
        "settings": "설정", "session": "세션",
        "model": "모델", "effort": "노력", "repeat": "반복",
        "wire": "Wire 모드", "wireOff": "Wire 모드 (mitmproxy 없음)",
        "results": "응답 기록", "copy": "보고서 복사", "json": "JSON 저장", "logs": "로그 폴더",
        "clear": "지우기",
        "colKind": "종류", "colRoute": "요청 → 실제 응답", "colStatus": "상태", "colTime": "시각",
        "colId": "응답 ID", "routeAsked": "부른 모델", "routeServed": "대답한 모델",
        "empty": "아직 검사하지 않았어요. 버튼 한 번만 눌러 주세요.",
        "liveEmpty": "Codex 창에서 뭐든 입력하면 여기에 한 줄씩 쌓여요.",
        "details": "상세 정보", "detailsHint": "계정 · Codex 경로 · 로그 위치",
        "detailsHintLive": "프록시 · 진행 기록",
        "detailsEmpty": "아직 적을 내용이 없어요.",
        "liveFolder": "작업 폴더",
        "foot": "짧은 프롬프트 하나만 보내고, 서버가 적어 보낸 모델명을 읽어요.",
        "idleHead": "준비됐어요", "runHead": "살펴보는 중...",
        "badHead": "바꿔치기 감지",
        "cancelledHead": "취소했어요",
        "cta": "검사하기", "ctaAgain": "다시 검사", "ctaRun": "검사 중...", "cancel": "취소",
        "chipIdle": "대기", "chipRun": "검사 중", "chipOk": "정상", "chipBad": "바꿔치기",
        "chipWarn": "확인 필요",
        "statusIdle": "준비됨", "statusDone": "{secs}초 소요",
        "liveStart": "모니터링 시작", "liveStop": "중지",
        "liveChipOff": "꺼짐", "liveChipOn": "감시 중", "liveChipBad": "바꿔치기", "liveChipWarn": "확인 필요",
        "liveStatusOff": "대기 중",
        "helpUsage": "기본 사용법", "helpTerms": "용어 설명", "helpGuide": "라이브 모니터 안내",
        "helpAbout": "정보", "helpTitle": "도움말", "close": "닫기", "ok": "확인",
        "statusPreparing": "Codex를 준비하는 중이에요...", "confirmRepeat": "반복이 {n}번이라 {n}번 보내요.",
        "closeTitle": "창을 닫을까요?",
        "customModel": "직접 입력...", "customModelTitle": "모델 이름 직접 입력",
    },
    "en": {
        "subtitle": "Which model really answered your request?",
        "tabCheck": "Check", "tabLive": "Live monitor",
        "settings": "Setup", "session": "Session",
        "model": "model", "effort": "effort", "repeat": "repeat",
        "wire": "Wire mode", "wireOff": "Wire mode (mitmproxy missing)",
        "results": "Responses", "copy": "Copy report", "json": "Save JSON", "logs": "Log folder",
        "clear": "Clear",
        "colKind": "Kind", "colRoute": "Requested → Served by", "colStatus": "Status", "colTime": "Time",
        "colId": "Response id", "routeAsked": "Called", "routeServed": "Answered by",
        "empty": "Nothing checked yet. One press is all it takes.",
        "liveEmpty": "Type anything in the Codex window and it shows up here.",
        "details": "Details", "detailsHint": "account · codex path · logs",
        "detailsHintLive": "proxy · session notes",
        "detailsEmpty": "Nothing to note yet.",
        "liveFolder": "Folder",
        "foot": "One short prompt goes out; we read the model name the server wrote back.",
        "idleHead": "Ready when you are", "runHead": "Sniffing around...",
        "badHead": "Rerouted",
        "cancelledHead": "Cancelled",
        "cta": "Check", "ctaAgain": "Check again", "ctaRun": "Checking...", "cancel": "Cancel",
        "chipIdle": "Idle", "chipRun": "Checking", "chipOk": "OK", "chipBad": "Rerouted",
        "chipWarn": "Needs a look",
        "statusIdle": "ready", "statusDone": "done in {secs}s",
        "liveStart": "Start monitoring", "liveStop": "Stop",
        "liveChipOff": "Off", "liveChipOn": "Watching", "liveChipBad": "Rerouted", "liveChipWarn": "Needs a look",
        "liveStatusOff": "idle",
        "helpUsage": "How to use", "helpTerms": "Glossary", "helpGuide": "Live monitor guide",
        "helpAbout": "About", "helpTitle": "Help", "close": "Close", "ok": "OK",
        "statusPreparing": "Getting Codex ready...", "confirmRepeat": "With repeat at {n}, it goes out {n} times.",
        "closeTitle": "Close the window?",
        "customModel": "Type a model...", "customModelTitle": "Enter a model slug",
    },
}

VERDICT_TONE = {  # verdict -> row/hero tone
    "ok": "ok", "OK": "ok", "REROUTED": "bad",
    "ERROR": "warn", "UNSUPPORTED": "warn", "UNKNOWN": "warn", "NO_DATA": "warn",
    "CANCELLED": "idle",
}


def _tone_of(verdict: str) -> str:
    return VERDICT_TONE.get(verdict, "warn")


def _is_pending(row: "live.LiveRow") -> bool:
    """A response still being streamed: no error, not completed, no other model named yet."""
    rec = row.record
    return (rec is not None and row.verdict() == "UNKNOWN" and not rec.error_code
            and rec.status in (None, "in_progress", "queued"))


# ------------------------------------------------------------------ the page
def _data_uri(name: str) -> str:
    data = assets.IMAGES.get(name, "")
    kind = "webp" if data.startswith("UklGR") else "png"  # base64 of "RIFF", the start of every WebP file
    return f"data:image/{kind};base64," + data


PAGE = r"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Codex Routing Detector</title>
<style>
/* Embedded fonts (codex_routing_fonts): no request leaves the machine for a font CDN. */
@font-face { font-family: "JetBrains Mono"; font-style: normal; font-weight: 100 800;
  src: url(__FONT_MONO__) format("woff2"); }
__FONT_KO_FACES__
/* "Night Launcher": the window of a modern fantasy game launcher. A deep navy night, frosted-glass
   panels with a thin light edge, one violet accent, and the seer standing large in the verdict card
   before a glowing ring. Text is plain sans-serif in high contrast; the verdict's two model names are
   the biggest thing on the card. Latin text uses Segoe UI (every Windows install has it), Korean the
   embedded NanumSquareRound. */
:root {
  --bg0: #080b17; --bg1: #0d1226;
  --panel: rgba(22, 28, 52, .68); --panel-hi: rgba(30, 38, 70, .78); --edge: rgba(150, 165, 255, .16);
  --field: rgba(255, 255, 255, .05); --field-edge: rgba(255, 255, 255, .10);
  --ink: #f3f5fb; --body: #c6cce0; --muted: #929bb9; --faint: #6f7898;
  --accent: #8b7bff; --accent2: #c46bff; --accent-ink: #b9b0ff;
  --ok: #3ee6a0; --bad: #ff5872; --warn: #ffb547; --run: #5cc8ff;
  --sans: "Segoe UI Variable Text", "Segoe UI", "NanumSquareRound", "Malgun Gothic", system-ui, sans-serif;
  --mono: "JetBrains Mono", Consolas, monospace;
}
* { box-sizing: border-box; }
html, body { margin: 0; }
body { font-family: var(--sans); color: var(--ink); -webkit-font-smoothing: antialiased; overflow-y: scroll;
  background: var(--bg0); }
a { color: var(--accent-ink); text-decoration: none; } a:hover { color: #ffffff; }
button { font-family: inherit; border: 0; background: none; padding: 0; cursor: pointer; color: inherit; }
button:disabled { cursor: default; }
:focus-visible { outline: 2px solid var(--accent-ink); outline-offset: 2px; }

@keyframes rise { 0% { transform: translateY(14px); opacity: 0 } 100% { transform: translateY(0); opacity: 1 } }
@keyframes drift { 0% { transform: translate(0, 0); opacity: 0 } 15% { opacity: var(--o, .6) } 85% { opacity: var(--o, .6) } 100% { transform: translate(var(--dx), -140px); opacity: 0 } }
@keyframes spin { to { transform: rotate(360deg) } }
@keyframes spinBack { to { transform: rotate(-360deg) } }
@keyframes breathe { 0%, 100% { transform: translateY(0) } 50% { transform: translateY(-5px) } }
@keyframes pulse { 0%, 100% { opacity: .55; transform: scale(1) } 50% { opacity: 1; transform: scale(1.06) } }
@keyframes shake { 0%, 100% { transform: translate(0, 0) } 20% { transform: translate(-6px, 1px) } 40% { transform: translate(5px, -2px) } 60% { transform: translate(-3px, 1px) } 80% { transform: translate(2px, 0) } }
@keyframes flash { 0% { opacity: .9 } 100% { opacity: 0 } }
@keyframes pop { 0% { transform: scale(0); opacity: 0 } 55% { transform: scale(1.25); opacity: 1 } 100% { transform: scale(1); opacity: 1 } }
@keyframes flow { 0% { transform: translateX(-4px); opacity: .4 } 50% { opacity: 1 } 100% { transform: translateX(4px); opacity: .4 } }
@keyframes shine { 0% { transform: translateX(-120%) skewX(-20deg) } 100% { transform: translateX(260%) skewX(-20deg) } }
@keyframes burst { 0% { transform: translate(0, 0) scale(.3) rotate(45deg); opacity: 0 } 15% { opacity: 1 } 100% { transform: translate(var(--dx), var(--dy)) scale(1) rotate(45deg); opacity: 0 } }
@keyframes rowIn { 0% { transform: translateY(8px); opacity: 0 } 100% { transform: translateY(0); opacity: 1 } }
@keyframes slideTab { 0% { transform: translateY(10px); opacity: 0 } 100% { transform: translateY(0); opacity: 1 } }
@keyframes stripe { 0% { background-position: 0 0 } 100% { background-position: 48px 0 } }
@keyframes walk { 0% { left: 0% } 100% { left: calc(100% - 30px) } }

#shell { position: relative; width: 1180px; margin: 0 auto; min-height: 100vh; }
/* the night: two soft glows and a little drifting light dust */
#sky { position: fixed; inset: 0; pointer-events: none; overflow: hidden; z-index: 0;
  background: radial-gradient(900px 520px at 12% -8%, rgba(124, 92, 255, .30), transparent 70%),
              radial-gradient(700px 480px at 92% 4%, rgba(255, 88, 114, .13), transparent 70%),
              radial-gradient(900px 600px at 50% 120%, rgba(60, 120, 255, .14), transparent 70%),
              linear-gradient(180deg, var(--bg0), var(--bg1)); }
#sky .dust { position: absolute; width: 3px; height: 3px; border-radius: 50%; background: #dcd6ff;
  box-shadow: 0 0 8px 2px rgba(170, 150, 255, .5); opacity: 0; }
#shell > *:not(#sky) { position: relative; z-index: 1; }

/* the glass every panel is made of */
.win { position: relative; background: var(--panel); border: 1px solid var(--edge); border-radius: 16px;
  backdrop-filter: blur(16px) saturate(1.2);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, .06), 0 18px 40px rgba(3, 5, 16, .45); }
body.opening .page > * { animation: rise .5s cubic-bezier(.2, .8, .2, 1) both; }
body.opening .page > :nth-child(2) { animation-delay: .07s; }
body.opening .page > :nth-child(3) { animation-delay: .14s; }
body.opening .page > :nth-child(4) { animation-delay: .2s; }

/* top bar: who we are, the two tabs, language and help */
.header { display: flex; align-items: center; gap: 14px; padding: 20px 32px 6px; }
.header img.logo { width: 42px; height: 42px; object-fit: cover; border-radius: 12px;
  box-shadow: 0 0 0 1.5px rgba(185, 176, 255, .5), 0 6px 18px rgba(124, 92, 255, .3); }
.header .names { display: flex; flex-direction: column; gap: 2px; }
.header .appname { font-size: 17px; font-weight: 800; letter-spacing: -.2px; color: var(--ink); }
.header .subtitle { font-size: 12.5px; color: var(--muted); }
.tabs { display: flex; gap: 4px; margin-left: 28px; margin-right: auto; padding: 4px; border-radius: 12px;
  background: var(--field); border: 1px solid var(--field-edge); }
.tab { display: flex; align-items: center; height: 34px; padding: 0 16px; border-radius: 9px; font-size: 14px; font-weight: 700;
  color: var(--muted); cursor: pointer; transition: color .15s ease, background .15s ease; }
.tab:hover { color: var(--ink); }
.tab.on { color: #ffffff; background: linear-gradient(135deg, var(--accent), var(--accent2));
  box-shadow: 0 6px 16px rgba(139, 123, 255, .35); }
.tab .bar { display: none; }
.langtoggle { display: flex; align-items: center; gap: 2px; padding: 4px; border-radius: 10px; font-size: 12.5px; font-weight: 700; }
.langtoggle span { padding: 6px 11px; border-radius: 7px; color: var(--muted); cursor: pointer; }
.langtoggle span:hover { color: var(--ink); }
.langtoggle span.on { background: rgba(255, 255, 255, .12); color: var(--ink); }
.helpbtn { display: grid; place-items: center; width: 38px; height: 38px; border-radius: 10px; color: var(--body); font-size: 15px; font-weight: 800; }
.helpbtn:hover { color: #ffffff; border-color: rgba(185, 176, 255, .45); }

/* page */
.page { display: flex; flex-direction: column; gap: 14px; padding: 16px 32px 10px; }
.page.slide { animation: slideTab .3s ease-out both; }
.hidden { display: none !important; }

/* hero: the seer, the verdict, the two model names */
.hero { display: grid; grid-template-columns: 310px 1fr; align-items: stretch; gap: 8px; padding: 0 36px 0 0; min-height: 308px;
  overflow: hidden; background: linear-gradient(100deg, rgba(30, 38, 72, .82) 0%, var(--panel) 46%); }
.hero > .clip { position: absolute; inset: 0; pointer-events: none; }
.hero.shake { animation: shake .45s ease-out both; }
.hero .flash { position: absolute; inset: 0; opacity: 0; background: radial-gradient(600px 300px at 18% 60%, rgba(255, 88, 114, .45), transparent 70%); }
.hero .flash.on { animation: flash .9s ease-out both; }
.hero .left { position: relative; min-height: 306px; display: flex; align-items: flex-end; justify-content: center; }
.hero .left::before { content: ""; position: absolute; left: 50%; bottom: 0; width: 300px; height: 300px; margin-left: -150px; border-radius: 50%;
  background: radial-gradient(circle, var(--tone, var(--accent)) 0%, transparent 62%); opacity: .38; filter: blur(8px); transition: background .4s ease; }
.hero .circle { position: absolute; width: 250px; height: 250px; left: 30px; top: 50%; margin-top: -135px; color: var(--tone, var(--accent));
  opacity: .45; animation: spin 50s linear infinite; }
.hero .circle .inner { transform-origin: 100px 100px; animation: spinBack 24s linear infinite; }
.hero .mascot { position: relative; display: block; width: 300px; height: 300px; object-fit: contain; object-position: 50% 100%;
  margin-bottom: -4px; filter: drop-shadow(0 12px 22px rgba(0, 0, 0, .5)); animation: breathe 5s ease-in-out infinite;
  -webkit-mask-image: linear-gradient(90deg, transparent 0, #000 7%, #000 93%, transparent 100%);
  mask-image: linear-gradient(90deg, transparent 0, #000 7%, #000 93%, transparent 100%); }
.hero .exclaim { position: absolute; right: 22px; top: 26px; width: 40px; height: 40px; display: grid; place-items: center;
  font-size: 24px; font-weight: 900; color: #fff; background: var(--bad); border-radius: 50%; z-index: 3; opacity: 0;
  box-shadow: 0 0 0 4px rgba(255, 88, 114, .25), 0 8px 24px rgba(255, 88, 114, .55); }
.hero[data-tone="bad"] .exclaim { animation: pop .45s cubic-bezier(.2, .9, .3, 1.4) .1s both; }
.hero .right { display: flex; flex-direction: column; justify-content: center; gap: 12px; min-width: 0; padding: 28px 0; }
.hero .statusrow { display: flex; align-items: center; gap: 10px; }
.chip { display: inline-flex; align-items: center; gap: 6px; font-size: 12px; font-weight: 800; padding: 4px 10px; border-radius: 999px;
  color: var(--tone, var(--accent-ink)); background: color-mix(in srgb, var(--tone, var(--accent)) 16%, transparent);
  border: 1px solid color-mix(in srgb, var(--tone, var(--accent)) 38%, transparent); }
.chip::before { content: ""; width: 6px; height: 6px; border-radius: 50%; background: currentColor; box-shadow: 0 0 8px currentColor; }
.statusline { font-size: 13px; color: var(--muted); }
.headline { font-size: 30px; font-weight: 800; letter-spacing: -.5px; line-height: 1.2; color: var(--ink); }
/* the call and the answer, side by side */
.vroute { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.vroute .mdl { display: flex; flex-direction: column; gap: 3px; padding: 9px 16px 10px; border-radius: 12px;
  background: var(--field); border: 1px solid var(--field-edge); min-width: 0; }
.vroute .mdl .lbl { font-size: 11.5px; font-weight: 700; color: var(--muted); }
.vroute .mdl .nm { font-family: var(--mono); font-size: 19px; font-weight: 700; color: var(--ink); letter-spacing: -.3px; }
.vroute .mdl.srv { border-color: color-mix(in srgb, var(--rtone, var(--ok)) 55%, transparent);
  background: color-mix(in srgb, var(--rtone, var(--ok)) 12%, transparent); box-shadow: 0 0 24px color-mix(in srgb, var(--rtone, var(--ok)) 22%, transparent); }
.vroute .mdl.srv .nm { color: var(--rtone, var(--ok)); }
.vroute .rarrow { font-size: 20px; font-weight: 800; color: var(--rtone, var(--muted)); animation: flow 1.4s ease-in-out infinite alternate; }
.brief { font-size: 15px; line-height: 1.65; color: var(--body); max-width: 680px; text-wrap: pretty; }
.brief b { color: var(--ink); font-weight: 800; }
.brief code { font-family: var(--mono); font-size: 13px; color: var(--ink); }
.actionrow { display: flex; align-items: center; gap: 12px; padding-top: 4px; }
.cta { position: relative; overflow: hidden; height: 46px; padding: 0 30px; border-radius: 12px; font-size: 15px; font-weight: 800; color: #ffffff;
  background: linear-gradient(135deg, var(--accent), var(--accent2)); box-shadow: 0 10px 24px rgba(139, 123, 255, .35), inset 0 1px 0 rgba(255, 255, 255, .25);
  transition: transform .12s ease, box-shadow .15s ease, filter .15s ease; }
.cta::after { content: ""; position: absolute; top: 0; bottom: 0; left: 0; width: 40%; background: linear-gradient(90deg, transparent, rgba(255, 255, 255, .35), transparent);
  transform: translateX(-120%) skewX(-20deg); }
.cta:hover:not(:disabled) { filter: brightness(1.08); box-shadow: 0 12px 30px rgba(139, 123, 255, .5), inset 0 1px 0 rgba(255, 255, 255, .25); }
.cta:hover:not(:disabled)::after { animation: shine .8s ease-out; }
.cta:active:not(:disabled) { transform: translateY(1px) scale(.98); }
.cta:disabled, .cta.off { background: rgba(255, 255, 255, .08); color: var(--muted); box-shadow: none; }
.cta.stop { background: linear-gradient(135deg, #ff5872, #ff7d5c); box-shadow: 0 10px 24px rgba(255, 88, 114, .35); }
.quietbtn { height: 32px; padding: 0 13px; border-radius: 9px; font-size: 12.5px; font-weight: 700; color: var(--body);
  background: var(--field); border: 1px solid var(--field-edge); transition: color .12s ease, border-color .12s ease, background .12s ease; }
.quietbtn:hover:not(:disabled) { color: #ffffff; border-color: rgba(185, 176, 255, .45); background: rgba(139, 123, 255, .12); }
.quietbtn:disabled { color: #4f5775; border-color: rgba(255, 255, 255, .05); }
/* while checking: a striped bar filling, with her tiny self walking along it */
.walker { position: relative; width: 240px; height: 34px; }
.walker .track { position: absolute; left: 0; right: 0; bottom: 6px; height: 8px; border-radius: 999px; background: rgba(255, 255, 255, .08); overflow: hidden; }
.walker .fill { height: 100%; width: 100%; border-radius: 999px;
  background: repeating-linear-gradient(115deg, var(--run) 0 12px, #8fdcff 12px 24px); animation: stripe .8s linear infinite; }
.walker img { position: absolute; bottom: 12px; width: 30px; height: 30px; object-fit: contain; animation: walk 2.6s ease-in-out infinite alternate; }
.folderline { font-size: 12.5px; color: var(--muted); }
.folderline .path { font-family: var(--mono); color: var(--body); cursor: pointer; }
.folderline .path:hover { color: #ffffff; }
#confetti { position: absolute; left: 150px; top: 150px; width: 1px; height: 1px; pointer-events: none; z-index: 3; }
#confetti div { position: absolute; width: 8px; height: 8px; border-radius: 2px; }

/* Windows' "Animation effects" off: the page holds still too (the seer swaps to her still picture) */
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { animation: none !important; transition: none !important; }
  #sky .dust, #confetti { display: none; }
  .hero[data-tone="bad"] .exclaim { opacity: 1; }
}

/* tones: the glow behind her, the ring and the chip take the verdict's colour */
.hero[data-tone="idle"] { --tone: var(--accent); }
.hero[data-tone="running"] { --tone: var(--run); }
.hero[data-tone="running"] .circle { opacity: .9; animation-duration: 3.5s; }
.hero[data-tone="running"] .circle .inner { animation-duration: 2s; }
.hero[data-tone="running"] .left::before { animation: pulse 1.6s ease-in-out infinite; }
.hero[data-tone="bad"] { --tone: var(--bad); }
.hero[data-tone="bad"] .circle { opacity: .7; animation-duration: 14s; }
.hero[data-tone="ok"] { --tone: var(--ok); }
.hero[data-tone="warn"] { --tone: var(--warn); }
.hero[data-tone="warn"] .circle { opacity: .35; animation-duration: 90s; }
.chip[data-tone="idle"] { --tone: var(--accent-ink); }
.chip[data-tone="running"] { --tone: var(--run); }
.chip[data-tone="bad"] { --tone: var(--bad); }
.chip[data-tone="ok"] { --tone: var(--ok); }
.chip[data-tone="warn"] { --tone: var(--warn); }
.vroute[data-tone="bad"] { --rtone: var(--bad); }
.vroute[data-tone="ok"] { --rtone: var(--ok); }
.vroute[data-tone="warn"] { --rtone: var(--warn); }
.vroute[data-tone="idle"] { --rtone: var(--muted); }

/* settings: a row of fields */
.strip { display: flex; align-items: center; gap: 8px; padding: 0 2px; flex-wrap: wrap; }
.strip .lead { font-size: 13px; font-weight: 800; color: var(--body); margin-right: 6px; }
.pill { position: relative; display: flex; align-items: center; gap: 8px; height: 40px; padding: 0 12px 0 14px; font-size: 13.5px; font-weight: 700;
  background: var(--panel); border: 1px solid var(--edge); border-radius: 11px; backdrop-filter: blur(12px); transition: border-color .12s ease, background .12s ease; }
.pill:hover { border-color: rgba(185, 176, 255, .5); background: var(--panel-hi); }
.pill .k { color: var(--muted); font-weight: 600; }
.pill .v { color: var(--ink); }
.pill .caret { color: var(--muted); font-size: 9px; }
.pill select { position: absolute; inset: 0; opacity: 0; width: 100%; cursor: pointer; }
.pill select option { color: #10142a; }
.pill.static { padding-right: 14px; }
.stepper { gap: 10px; }
.stepper button { display: grid; place-items: center; width: 24px; height: 24px; border-radius: 7px; background: var(--field);
  border: 1px solid var(--field-edge); color: var(--body); font-size: 14px; line-height: 1; }
.stepper button:hover:not(:disabled) { background: var(--accent); border-color: var(--accent); color: #ffffff; }
.stepper .v { min-width: 10px; text-align: center; }
.switchpill { color: var(--body); cursor: pointer; padding: 0 14px; }
.switchpill.disabled { color: var(--faint); cursor: default; }
.switch { display: inline-block; width: 34px; height: 20px; border-radius: 999px; background: rgba(255, 255, 255, .12);
  position: relative; transition: background .15s ease; flex: none; }
.switch .knob { position: absolute; top: 3px; left: 3px; width: 14px; height: 14px; border-radius: 50%; background: #ffffff;
  box-shadow: 0 1px 3px rgba(0, 0, 0, .3); transition: left .15s ease; }
.switch.on { background: linear-gradient(135deg, var(--accent), var(--accent2)); }
.switch.on .knob { left: 17px; }
.strip .tail { margin-left: auto; font-size: 13px; color: var(--muted); cursor: pointer; }
.strip .tail:hover { color: #ffffff; }
.strip .tail.plain { cursor: default; }
.strip .tail.plain:hover { color: var(--muted); }

/* results */
.card { padding: 6px 10px 10px; }
.card .head { display: flex; align-items: center; gap: 10px; padding: 14px 12px 12px; }
.card .title { font-size: 15px; font-weight: 800; color: var(--ink); }
.card .count { font-size: 12px; font-weight: 800; color: var(--accent-ink); background: rgba(139, 123, 255, .16); border-radius: 999px; padding: 2px 9px; }
.card .btns { margin-left: auto; display: flex; gap: 6px; }
.cols, .row { display: grid; grid-template-columns: 30px 82px 1fr 110px 92px 190px; align-items: center; gap: 12px; }
.cols { padding: 0 14px 8px; font-size: 12px; font-weight: 700; color: var(--muted); }
.row { position: relative; padding: 12px 14px; border-radius: 11px; margin-bottom: 4px; background: rgba(255, 255, 255, .03);
  border: 1px solid transparent; transition: background .15s ease, border-color .15s ease; }
.row:hover { background: rgba(255, 255, 255, .06); border-color: var(--field-edge); }
.row::before { content: ""; position: absolute; left: 0; top: 10px; bottom: 10px; width: 3px; border-radius: 0 3px 3px 0; background: var(--ok); }
.row[data-tone="bad"] { background: rgba(255, 88, 114, .07); }
.row[data-tone="bad"]::before { background: var(--bad); box-shadow: 0 0 10px var(--bad); }
.row[data-tone="warn"]::before { background: var(--warn); }
.row[data-tone="idle"]::before { background: var(--faint); }
.row.anim { animation: rowIn .35s cubic-bezier(.2, .8, .2, 1) both; }
.row .dot { display: grid; place-items: center; width: 24px; height: 24px; border-radius: 50%; font-size: 11.5px; font-weight: 800;
  color: var(--ok); background: rgba(62, 230, 160, .14); }
.row[data-tone="bad"] .dot { color: var(--bad); background: rgba(255, 88, 114, .16); }
.row[data-tone="warn"] .dot { color: var(--warn); background: rgba(255, 181, 71, .16); }
.row[data-tone="idle"] .dot { color: var(--muted); background: rgba(255, 255, 255, .08); }
.row .kind { justify-self: start; font-size: 12px; font-weight: 700; padding: 3px 9px; border-radius: 7px; background: var(--field); color: var(--body); }
.row .route { display: flex; align-items: center; gap: 10px; font-size: 14.5px; font-weight: 700; min-width: 0; flex-wrap: nowrap; }
.row .route .req { color: var(--body); }
.row .route .arr { color: var(--faint); }
.row .route .srv { color: var(--ok); }
.row[data-tone="bad"] .route .arr, .row[data-tone="bad"] .route .srv { color: var(--bad); }
.row[data-tone="warn"] .route .srv { color: var(--warn); }
.row[data-tone="idle"] .route .srv { color: var(--muted); }
.row .st { font-size: 13px; color: var(--body); }
.row .tm { font-size: 12.5px; color: var(--muted); font-family: var(--mono); }
.row .rid { font-size: 12px; color: var(--faint); font-family: var(--mono); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.emptystate { display: flex; flex-direction: column; align-items: center; gap: 10px; padding: 26px 0 24px; color: var(--muted); font-size: 14px; }
.emptystate img { width: 56px; height: 56px; object-fit: cover; border-radius: 14px; opacity: .9; }

/* details */
.details .dhead { display: flex; align-items: center; gap: 10px; padding: 14px 18px; cursor: pointer; font-size: 14px; font-weight: 800; color: var(--ink); }
.details .dhead:hover .caret { color: var(--accent-ink); }
.details .dhead .caret { display: inline-block; transition: transform .2s ease; color: var(--muted); }
.details.open .dhead .caret { transform: rotate(90deg); }
.details .dhead .hint { font-weight: 600; color: var(--muted); font-size: 13px; }
.details .dbody { display: none; padding: 0 16px 16px; }
.details.open .dbody { display: block; }
.details pre { margin: 0; padding: 14px 16px; background: rgba(0, 0, 0, .25); border: 1px solid var(--field-edge); border-radius: 11px;
  font-family: var(--mono); font-size: 12.5px; line-height: 1.7; color: var(--body); white-space: pre-wrap; word-break: break-all; }

/* footer */
.footer { display: flex; align-items: center; gap: 12px; padding: 6px 34px 24px; font-size: 12.5px; color: var(--muted); }
.footer .ver { font-family: var(--mono); }
.footer .ver.new { color: var(--bad); font-weight: 700; cursor: pointer; }
.footer .tagline { margin-left: auto; }

/* modal */
#overlay { position: fixed; inset: 0; background: rgba(4, 6, 16, .6); backdrop-filter: blur(6px); display: grid; place-items: center; z-index: 40; }
.modal { width: 560px; max-width: calc(100vw - 60px); max-height: calc(100vh - 60px); overflow: auto; padding: 22px 24px 20px;
  background: rgba(20, 26, 50, .92); border-radius: 20px; animation: rise .3s cubic-bezier(.2, .8, .2, 1) both; }
.modal.guide { width: 600px; }
.modal.help { width: 840px; display: flex; flex-direction: column; overflow: hidden; }
.mhead { display: flex; align-items: center; gap: 12px; margin-bottom: 16px; }
.mhead img { width: 44px; height: 44px; object-fit: cover; flex: none; border-radius: 12px; box-shadow: 0 0 0 1.5px rgba(185, 176, 255, .5); }
.mhead .mtitles { min-width: 0; }
.mhead .mt { font-size: 18px; font-weight: 800; color: var(--ink); letter-spacing: -.2px; }
.mhead .ms { font-size: 12.5px; color: var(--muted); margin-top: 2px; }
.xbtn { margin-left: auto; flex: none; display: grid; place-items: center; width: 34px; height: 34px; border-radius: 10px;
  background: var(--field); border: 1px solid var(--field-edge); color: var(--body); font-size: 13px; font-weight: 800; }
.xbtn:hover { color: #ffffff; }
.modal .mbody { font-size: 14.5px; line-height: 1.75; color: var(--body); white-space: pre-wrap; background: rgba(0, 0, 0, .22);
  border: 1px solid var(--field-edge); border-radius: 12px; padding: 14px 16px; }
.modal .mcheck { display: flex; align-items: center; gap: 8px; margin-top: 14px; font-size: 13px; color: var(--muted); cursor: pointer; }
.modal .mcheck input { accent-color: var(--accent); width: 16px; height: 16px; }
.modal .mrow { display: flex; justify-content: flex-end; gap: 8px; margin-top: 18px; flex: none; }
.minput { width: 100%; margin-top: 2px; padding: 12px 14px; border: 1px solid var(--field-edge); border-radius: 11px;
  font: 600 13.5px var(--mono); color: var(--ink); background: rgba(0, 0, 0, .25); outline: none; }
.minput:focus { border-color: var(--accent); box-shadow: 0 0 0 3px rgba(139, 123, 255, .25); }
.mbtn { height: 40px; padding: 0 22px; border-radius: 11px; font-size: 14px; font-weight: 800; transition: transform .1s ease, filter .12s ease; }
.mbtn:hover { filter: brightness(1.1); }
.mbtn:active { transform: translateY(1px); }
.mbtn.primary { color: #ffffff; background: linear-gradient(135deg, var(--accent), var(--accent2)); box-shadow: 0 8px 20px rgba(139, 123, 255, .35); }
.mbtn.plain { background: var(--field); border: 1px solid var(--field-edge); color: var(--body); }
.modal code { font-family: var(--mono); font-size: 12.5px; background: rgba(139, 123, 255, .14); border-radius: 6px; padding: 1px 6px; color: #dcd7ff; word-break: break-word; }
.modal b { color: var(--ink); font-weight: 800; }

/* help pages */
.helptabs { display: flex; gap: 4px; flex-wrap: wrap; margin-bottom: 14px; flex: none; padding: 4px; border-radius: 12px; background: var(--field);
  border: 1px solid var(--field-edge); width: max-content; }
.helptabs button { height: 32px; padding: 0 14px; border-radius: 9px; font-size: 13px; font-weight: 700; color: var(--muted); transition: background .15s ease, color .15s ease; }
.helptabs button:hover { color: var(--ink); }
.helptabs button.on { color: #ffffff; background: linear-gradient(135deg, var(--accent), var(--accent2)); }
.helpbody { overflow-y: auto; min-height: 0; flex: 1; padding-right: 4px; }
.helpbody.fresh { animation: slideTab .25s ease-out both; }
.hsec { background: rgba(255, 255, 255, .035); border: 1px solid var(--field-edge); border-radius: 14px; padding: 16px 18px 12px; margin-bottom: 10px; }
.hsec:last-child { margin-bottom: 2px; }
.hsec h4 { margin: 0 0 8px; display: flex; align-items: center; gap: 10px; font-size: 15.5px; font-weight: 800; color: var(--ink); }
.bub { display: grid; place-items: center; width: 34px; height: 34px; border-radius: 10px; background: rgba(139, 123, 255, .14); font-size: 16px; flex: none; }
.hitem { position: relative; font-size: 14px; line-height: 1.7; color: var(--body); padding: 4px 0 4px 18px; }
.hitem::before { content: ""; position: absolute; left: 4px; top: 13px; width: 6px; height: 6px; border-radius: 50%; background: var(--accent); }
.hitem.num { padding-left: 34px; }
.hitem.num::before { content: none; }
.hitem .n { position: absolute; left: 0; top: 6px; display: grid; place-items: center; width: 22px; height: 22px; border-radius: 7px;
  background: rgba(139, 123, 255, .2); color: var(--accent-ink); font-size: 12px; font-weight: 800; }
.hrow { display: grid; grid-template-columns: 150px 1fr; gap: 14px; align-items: baseline; padding: 9px 2px; font-size: 14px; line-height: 1.65; color: var(--body); }
.hrow + .hrow { border-top: 1px solid rgba(255, 255, 255, .06); }
.hrow .term { font-weight: 800; color: var(--ink); }
.hrow .chip { justify-self: start; }
.gsteps { display: flex; flex-direction: column; gap: 8px; }
.gstep { display: flex; gap: 14px; align-items: flex-start; background: rgba(255, 255, 255, .035); border: 1px solid var(--field-edge); border-radius: 14px; padding: 13px 16px;
  animation: rowIn .35s cubic-bezier(.2, .8, .2, 1) both; }
.hsec .gstep { background: rgba(255, 255, 255, .03); }
.gstep .gt { font-size: 14.5px; font-weight: 800; color: var(--ink); margin: 1px 0 3px; }
.gstep .gx { font-size: 13.5px; line-height: 1.6; color: var(--body); }
.about { display: flex; gap: 22px; align-items: center; border-radius: 16px; padding: 18px 24px; margin-bottom: 10px;
  background: linear-gradient(110deg, rgba(139, 123, 255, .2), rgba(196, 107, 255, .06)); border: 1px solid var(--edge); }
.about img { width: 120px; height: 120px; object-fit: contain; flex: none; filter: drop-shadow(0 8px 16px rgba(0, 0, 0, .5)); }
.about .an { font-size: 22px; font-weight: 800; color: var(--ink); letter-spacing: -.3px; }
.about .av { font-family: var(--mono); font-size: 12.5px; color: var(--muted); margin-top: 3px; }
.about .al { font-size: 15px; line-height: 1.6; color: var(--body); margin-top: 8px; font-weight: 600; }
.arepo { margin-top: 12px; }
</style>
</head>
<body>
<div id="shell">
  <div id="sky"></div>

  <div class="header">
    <img class="logo" src="__AVATAR__" alt="">
    <div class="names">
      <div class="appname">Codex Routing Detector</div>
      <div class="subtitle" id="subtitle"></div>
    </div>
    <nav class="tabs">
      <div class="tab on" id="tab-check"><span></span><div class="bar"></div></div>
      <div class="tab" id="tab-live"><span></span><div class="bar"></div></div>
    </nav>
    <div class="langtoggle win" id="langtoggle">
      <span data-lang="ko">한국어</span><span data-lang="en">EN</span>
    </div>
    <button class="helpbtn win" id="helpbtn">?</button>
  </div>

  <div class="page" id="page-check">
    <div class="hero win" id="c-hero" data-tone="idle">
      <div class="clip"><div class="flash"></div></div>
      <div class="left"><svg class="circle" viewBox="0 0 200 200" fill="none" stroke="currentColor" aria-hidden="true"><circle cx="100" cy="100" r="97" stroke-width="1.6"/><circle cx="100" cy="100" r="92" stroke-width=".7" stroke-dasharray="1.5 3.5"/><circle cx="100" cy="100" r="74" stroke-width="1"/><g stroke-width=".9"><line x1="176.0" y1="100.0" x2="188.0" y2="100.0"/><line x1="177.8" y1="113.7" x2="184.7" y2="114.9"/><line x1="174.2" y1="127.0" x2="180.8" y2="129.4"/><line x1="165.8" y1="138.0" x2="176.2" y2="144.0"/><line x1="160.5" y1="150.8" x2="165.9" y2="155.3"/><line x1="150.8" y1="160.5" x2="155.3" y2="165.9"/><line x1="138.0" y1="165.8" x2="144.0" y2="176.2"/><line x1="127.0" y1="174.2" x2="129.4" y2="180.8"/><line x1="113.7" y1="177.8" x2="114.9" y2="184.7"/><line x1="100.0" y1="176.0" x2="100.0" y2="188.0"/><line x1="86.3" y1="177.8" x2="85.1" y2="184.7"/><line x1="73.0" y1="174.2" x2="70.6" y2="180.8"/><line x1="62.0" y1="165.8" x2="56.0" y2="176.2"/><line x1="49.2" y1="160.5" x2="44.7" y2="165.9"/><line x1="39.5" y1="150.8" x2="34.1" y2="155.3"/><line x1="34.2" y1="138.0" x2="23.8" y2="144.0"/><line x1="25.8" y1="127.0" x2="19.2" y2="129.4"/><line x1="22.2" y1="113.7" x2="15.3" y2="114.9"/><line x1="24.0" y1="100.0" x2="12.0" y2="100.0"/><line x1="22.2" y1="86.3" x2="15.3" y2="85.1"/><line x1="25.8" y1="73.0" x2="19.2" y2="70.6"/><line x1="34.2" y1="62.0" x2="23.8" y2="56.0"/><line x1="39.5" y1="49.2" x2="34.1" y2="44.7"/><line x1="49.2" y1="39.5" x2="44.7" y2="34.1"/><line x1="62.0" y1="34.2" x2="56.0" y2="23.8"/><line x1="73.0" y1="25.8" x2="70.6" y2="19.2"/><line x1="86.3" y1="22.2" x2="85.1" y2="15.3"/><line x1="100.0" y1="24.0" x2="100.0" y2="12.0"/><line x1="113.7" y1="22.2" x2="114.9" y2="15.3"/><line x1="127.0" y1="25.8" x2="129.4" y2="19.2"/><line x1="138.0" y1="34.2" x2="144.0" y2="23.8"/><line x1="150.8" y1="39.5" x2="155.3" y2="34.1"/><line x1="160.5" y1="49.2" x2="165.9" y2="44.7"/><line x1="165.8" y1="62.0" x2="176.2" y2="56.0"/><line x1="174.2" y1="73.0" x2="180.8" y2="70.6"/><line x1="177.8" y1="86.3" x2="184.7" y2="85.1"/></g><g class="inner" stroke-width="1"><polygon points="100,34 157.2,133 42.8,133"/><polygon points="100,166 42.8,67 157.2,67"/><circle cx="100" cy="100" r="33" stroke-dasharray="3 3"/><circle cx="164.7" cy="126.8" r="4.2"/><path d="M164.7 123.8v6"/><circle cx="126.8" cy="164.7" r="4.2"/><path d="M126.8 161.7v6"/><circle cx="73.2" cy="164.7" r="4.2"/><path d="M73.2 161.7v6"/><circle cx="35.3" cy="126.8" r="4.2"/><path d="M35.3 123.8v6"/><circle cx="35.3" cy="73.2" r="4.2"/><path d="M35.3 70.2v6"/><circle cx="73.2" cy="35.3" r="4.2"/><path d="M73.2 32.3v6"/><circle cx="126.8" cy="35.3" r="4.2"/><path d="M126.8 32.3v6"/><circle cx="164.7" cy="73.2" r="4.2"/><path d="M164.7 70.2v6"/></g></svg><img class="mascot" src="__MASCOT__" alt=""><div class="exclaim">!</div></div>
      <div class="right">
        <div class="statusrow"><span class="chip" id="c-chip"></span><span class="statusline" id="c-status"></span></div>
        <div class="headline" id="c-head"></div>
        <div class="vroute hidden" id="c-route"><div class="mdl req"><span class="lbl" id="c-rlreq"></span><span class="nm" id="c-rreq"></span></div>
          <span class="rarrow">&#10140;</span>
          <div class="mdl srv"><span class="lbl" id="c-rlsrv"></span><span class="nm" id="c-rsrv"></span></div></div>
        <div class="brief" id="c-brief"></div>
        <div class="actionrow">
          <button class="cta" id="c-cta"></button>
          <div class="walker hidden" id="c-walker">
            <div class="track"><div class="fill"></div></div>
            <img src="__MASCOT__" alt="">
          </div>
          <button class="quietbtn hidden" id="c-cancel"></button>
        </div>
      </div>
      <div id="confetti"></div>
    </div>

    <div class="strip">
      <span class="lead" id="c-lead"></span>
      <div class="pill"><span class="k" id="k-model"></span><span class="v" id="v-model"></span>
        <span class="caret">&#9660;</span><select id="sel-model"></select></div>
      <div class="pill"><span class="k" id="k-effort"></span><span class="v" id="v-effort"></span>
        <span class="caret">&#9660;</span><select id="sel-effort"></select></div>
      <div class="pill stepper"><span class="k" id="k-repeat"></span>
        <button id="rep-minus">&#8722;</button><span class="v" id="v-repeat">1</span><button id="rep-plus">+</button></div>
      <div class="pill switchpill" id="wirepill">
        <span class="switch" id="wireswitch"><span class="knob"></span></span><span id="k-wire"></span></div>
      <span class="tail" id="codexpill" title=""></span>
    </div>

    <div class="card win">
      <div class="head">
        <span class="title" id="c-results"></span><span class="count" id="c-count">0</span>
        <div class="btns">
          <button class="quietbtn" id="btn-copy"></button>
          <button class="quietbtn" id="btn-json"></button>
          <button class="quietbtn" id="btn-logs"></button>
        </div>
      </div>
      <div class="cols" id="c-cols"></div>
      <div id="c-rows"></div>
      <div class="emptystate hidden" id="c-empty"><img id="c-empty-img" src="__MOOD_IDLE__" alt=""><span id="c-empty-text"></span></div>
    </div>

    <div class="details win" id="c-details">
      <div class="dhead" id="c-dhead"><span class="caret">&#9656;</span><span id="c-dlabel"></span><span class="hint" id="c-dhint"></span></div>
      <div class="dbody"><pre id="c-dpre"></pre></div>
    </div>
  </div>

  <div class="page hidden" id="page-live">
    <div class="hero win" id="l-hero" data-tone="idle">
      <div class="clip"><div class="flash"></div></div>
      <div class="left"><svg class="circle" viewBox="0 0 200 200" fill="none" stroke="currentColor" aria-hidden="true"><circle cx="100" cy="100" r="97" stroke-width="1.6"/><circle cx="100" cy="100" r="92" stroke-width=".7" stroke-dasharray="1.5 3.5"/><circle cx="100" cy="100" r="74" stroke-width="1"/><g stroke-width=".9"><line x1="176.0" y1="100.0" x2="188.0" y2="100.0"/><line x1="177.8" y1="113.7" x2="184.7" y2="114.9"/><line x1="174.2" y1="127.0" x2="180.8" y2="129.4"/><line x1="165.8" y1="138.0" x2="176.2" y2="144.0"/><line x1="160.5" y1="150.8" x2="165.9" y2="155.3"/><line x1="150.8" y1="160.5" x2="155.3" y2="165.9"/><line x1="138.0" y1="165.8" x2="144.0" y2="176.2"/><line x1="127.0" y1="174.2" x2="129.4" y2="180.8"/><line x1="113.7" y1="177.8" x2="114.9" y2="184.7"/><line x1="100.0" y1="176.0" x2="100.0" y2="188.0"/><line x1="86.3" y1="177.8" x2="85.1" y2="184.7"/><line x1="73.0" y1="174.2" x2="70.6" y2="180.8"/><line x1="62.0" y1="165.8" x2="56.0" y2="176.2"/><line x1="49.2" y1="160.5" x2="44.7" y2="165.9"/><line x1="39.5" y1="150.8" x2="34.1" y2="155.3"/><line x1="34.2" y1="138.0" x2="23.8" y2="144.0"/><line x1="25.8" y1="127.0" x2="19.2" y2="129.4"/><line x1="22.2" y1="113.7" x2="15.3" y2="114.9"/><line x1="24.0" y1="100.0" x2="12.0" y2="100.0"/><line x1="22.2" y1="86.3" x2="15.3" y2="85.1"/><line x1="25.8" y1="73.0" x2="19.2" y2="70.6"/><line x1="34.2" y1="62.0" x2="23.8" y2="56.0"/><line x1="39.5" y1="49.2" x2="34.1" y2="44.7"/><line x1="49.2" y1="39.5" x2="44.7" y2="34.1"/><line x1="62.0" y1="34.2" x2="56.0" y2="23.8"/><line x1="73.0" y1="25.8" x2="70.6" y2="19.2"/><line x1="86.3" y1="22.2" x2="85.1" y2="15.3"/><line x1="100.0" y1="24.0" x2="100.0" y2="12.0"/><line x1="113.7" y1="22.2" x2="114.9" y2="15.3"/><line x1="127.0" y1="25.8" x2="129.4" y2="19.2"/><line x1="138.0" y1="34.2" x2="144.0" y2="23.8"/><line x1="150.8" y1="39.5" x2="155.3" y2="34.1"/><line x1="160.5" y1="49.2" x2="165.9" y2="44.7"/><line x1="165.8" y1="62.0" x2="176.2" y2="56.0"/><line x1="174.2" y1="73.0" x2="180.8" y2="70.6"/><line x1="177.8" y1="86.3" x2="184.7" y2="85.1"/></g><g class="inner" stroke-width="1"><polygon points="100,34 157.2,133 42.8,133"/><polygon points="100,166 42.8,67 157.2,67"/><circle cx="100" cy="100" r="33" stroke-dasharray="3 3"/><circle cx="164.7" cy="126.8" r="4.2"/><path d="M164.7 123.8v6"/><circle cx="126.8" cy="164.7" r="4.2"/><path d="M126.8 161.7v6"/><circle cx="73.2" cy="164.7" r="4.2"/><path d="M73.2 161.7v6"/><circle cx="35.3" cy="126.8" r="4.2"/><path d="M35.3 123.8v6"/><circle cx="35.3" cy="73.2" r="4.2"/><path d="M35.3 70.2v6"/><circle cx="73.2" cy="35.3" r="4.2"/><path d="M73.2 32.3v6"/><circle cx="126.8" cy="35.3" r="4.2"/><path d="M126.8 32.3v6"/><circle cx="164.7" cy="73.2" r="4.2"/><path d="M164.7 70.2v6"/></g></svg><img class="mascot" src="__MASCOT__" alt=""><div class="exclaim">!</div></div>
      <div class="right">
        <div class="statusrow"><span class="chip" id="l-chip"></span><span class="statusline" id="l-status"></span></div>
        <div class="headline" id="l-head"></div>
        <div class="vroute hidden" id="l-route"><div class="mdl req"><span class="lbl" id="l-rlreq"></span><span class="nm" id="l-rreq"></span></div>
          <span class="rarrow">&#10140;</span>
          <div class="mdl srv"><span class="lbl" id="l-rlsrv"></span><span class="nm" id="l-rsrv"></span></div></div>
        <div class="brief" id="l-brief"></div>
        <div class="actionrow">
          <button class="cta" id="l-cta"></button>
          <span class="folderline"><span id="l-folderlabel"></span> <span class="path" id="l-folder" title=""></span></span>
        </div>
      </div>
    </div>

    <div class="strip">
      <span class="lead" id="l-lead"></span>
      <div class="pill static"><span class="k" id="lk-model"></span><span class="v" id="lv-model">—</span></div>
      <div class="pill static"><span class="k" id="lk-effort"></span><span class="v" id="lv-effort">—</span></div>
      <div class="pill static" id="cfgpill" style="cursor:pointer"><span class="k">config.toml</span></div>
      <span class="tail plain" id="l-proxy">—</span>
    </div>

    <div class="card win">
      <div class="head">
        <span class="title" id="l-results"></span><span class="count" id="l-count">0</span>
        <div class="btns">
          <button class="quietbtn" id="btn-livecopy"></button>
          <button class="quietbtn" id="btn-liveclear"></button>
        </div>
      </div>
      <div class="cols" id="l-cols"></div>
      <div id="l-rows"></div>
      <div class="emptystate hidden" id="l-empty"><img id="l-empty-img" src="__MOOD_IDLE__" alt=""><span id="l-empty-text"></span></div>
    </div>

    <div class="details win" id="l-details">
      <div class="dhead" id="l-dhead"><span class="caret">&#9656;</span><span id="l-dlabel"></span><span class="hint" id="l-dhint"></span></div>
      <div class="dbody"><pre id="l-dpre"></pre></div>
    </div>
  </div>

  <div class="footer">
    <span class="ver" id="version"></span>
    <a href="#" id="github">GitHub</a>
    <span class="tagline" id="tagline"></span>
  </div>
</div>

<div id="overlay" class="hidden"></div>

<script>
"use strict";
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g,
  (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));

const REDUCE_MOTION = window.matchMedia("(prefers-reduced-motion: reduce)");

const crd = {
  T: null, HELPS: null, vm: null, pendingVm: null, tab: "check",
  prevRows: { check: -1, live: -1 }, prevTone: { check: null, live: null }, prevLang: null,
  prevPhase: null, prevBrief: { check: null, live: null },
  toastTimer: { check: null, live: null }, toast: { check: null, live: null },
  guidePending: false,
};
window.crd = crd;

function api() { return window.pywebview.api; }

/* ---------------------------------------------------------------- sky */
function buildSky() {
  let html = "", seed = 11;
  const rnd = () => { seed = (seed * 16807) % 2147483647; return seed / 2147483647; };
  for (let i = 0; i < 26; i++) {
    html += '<div class="dust" style="left:' + (rnd() * 100).toFixed(2) + "%;top:" + (25 + rnd() * 75).toFixed(2) +
      "%;--dx:" + ((rnd() - .5) * 60).toFixed(0) + "px;--o:" + (.25 + rnd() * .5).toFixed(2) + ";animation:drift " +
      (9 + rnd() * 8).toFixed(2) + "s linear " + (rnd() * 12).toFixed(2) + 's infinite"></div>';
  }
  $("sky").innerHTML = html;
}

/* the verdict card's model pair: the first swapped answer, else the latest one */
function setRoute(prefix, rows) {
  const box = $(prefix + "-route");
  const r = rows.find((x) => x.tone === "bad") || rows[rows.length - 1];
  box.classList.toggle("hidden", !r || !r.served);
  if (!r) return;
  const s = t();
  $(prefix + "-rlreq").textContent = s.routeAsked; $(prefix + "-rlsrv").textContent = s.routeServed;
  $(prefix + "-rreq").textContent = r.requested; $(prefix + "-rsrv").textContent = r.served;
  box.setAttribute("data-tone", r.tone);
}

/* a reroute: the card shakes and flashes red, and she shouts */
function alarm(hero) {
  if (REDUCE_MOTION.matches) return;
  hero.classList.remove("shake"); void hero.offsetWidth; hero.classList.add("shake");
  const f = hero.querySelector(".flash");
  f.classList.remove("on"); void f.offsetWidth; f.classList.add("on");
}

/* ---------------------------------------------------------------- rendering */
function t() { return crd.T[crd.vm.lang]; }

function heroPicture(tone) { return window.HERO_SRC[tone] || window.HERO_SRC.idle; }

/* while idle or checking she moves, unless motion is turned down (followed live, not just at start) */
function setMotion() {
  const moving = REDUCE_MOTION.matches ? window.MASCOT_SRC : window.MASCOT_ANIM_SRC;
  window.HERO_SRC.idle = window.HERO_SRC.running = moving;
  ["c-hero", "l-hero"].forEach((id) => {
    const hero = $(id);
    const pic = heroPicture(hero.getAttribute("data-tone"));
    if (hero.querySelector(".mascot").src !== pic) hero.querySelector(".mascot").src = pic;
  });
}

function setChip(el, tone, label) {
  el.setAttribute("data-tone", tone);
  el.textContent = label;
}

function renderRows(holder, rows, animateFrom) {
  holder.innerHTML = "";
  rows.forEach((r, i) => {
    const d = document.createElement("div");
    d.className = "row";
    d.setAttribute("data-tone", r.tone);
    if (animateFrom >= 0 && i >= animateFrom) {
      d.classList.add("anim");
      d.style.animationDelay = ((i - animateFrom) * 90) + "ms";
    }
    if (r.verdict) d.title = r.verdict;
    d.innerHTML =
      '<div class="dot">' + esc(r.n) + "</div>" +
      '<div class="kind">' + esc(r.kind) + "</div>" +
      '<div class="route"><span class="req">' + esc(r.requested) + '</span><span class="arr">&#8594;</span><span class="srv">' + esc(r.served) + "</span></div>" +
      '<div class="st">' + esc(r.status) + "</div>" +
      '<div class="tm">' + esc(r.time) + "</div>" +
      '<div class="rid" title="' + esc(r.rid) + '">' + esc(r.rid) + "</div>";
    holder.appendChild(d);
  });
}

function bopHero(el) { el.classList.remove("bop"); void el.offsetWidth; el.classList.add("bop"); }  /* no style: the verdict types itself out instead */

function popConfetti() {
  if (REDUCE_MOTION.matches) return;
  const holder = $("confetti");
  holder.innerHTML = "";
  const colors = ["#3ee6a0", "#b9b0ff", "#ffffff", "#8fdcff"];
  for (let i = 0; i < 18; i++) {
    const d = document.createElement("div");
    const a = (i / 18) * Math.PI * 2, r = 80 + (i % 3) * 34;
    d.style.background = colors[i % 4];
    d.style.boxShadow = "0 0 10px " + colors[i % 4];
    d.style.setProperty("--dx", Math.round(Math.cos(a) * r) + "px");
    d.style.setProperty("--dy", Math.round(Math.sin(a) * r) + "px");
    d.style.animation = "burst " + (0.9 + (i % 4) * 0.18) + "s cubic-bezier(.1,.8,.3,1) " + (i * 0.02) + "s both";
    holder.appendChild(d);
  }
  setTimeout(() => { if ($("confetti")) $("confetti").innerHTML = ""; }, 2400);
}

function renderStatics() {
  const s = t();
  $("subtitle").textContent = s.subtitle;
  $("tab-check").querySelector("span").textContent = s.tabCheck;
  $("tab-live").querySelector("span").textContent = s.tabLive;
  document.querySelectorAll("#langtoggle span").forEach((el) =>
    el.classList.toggle("on", el.dataset.lang === crd.vm.lang));
  $("c-lead").textContent = s.settings; $("l-lead").textContent = s.session;
  $("k-model").textContent = s.model; $("k-effort").textContent = s.effort; $("k-repeat").textContent = s.repeat;
  $("lk-model").textContent = s.model; $("lk-effort").textContent = s.effort;
  $("c-results").textContent = s.results; $("l-results").textContent = s.results;
  $("btn-copy").textContent = s.copy; $("btn-json").textContent = s.json; $("btn-logs").textContent = s.logs;
  $("btn-livecopy").textContent = s.copy; $("btn-liveclear").textContent = s.clear;
  const cols = "<div>#</div><div>" + esc(s.colKind) + "</div><div>" + esc(s.colRoute) + "</div><div>" +
    esc(s.colStatus) + "</div><div>" + esc(s.colTime) + "</div><div>" + esc(s.colId) + "</div>";
  $("c-cols").innerHTML = cols; $("l-cols").innerHTML = cols;
  $("c-dlabel").textContent = s.details; $("c-dhint").textContent = s.detailsHint;
  $("l-dlabel").textContent = s.details; $("l-dhint").textContent = s.detailsHintLive;
  $("l-folderlabel").textContent = s.liveFolder;
  $("tagline").textContent = s.foot;
}

function render(vm) {
  if (!crd.T) { crd.pendingVm = vm; return; }  // a push can land before init() resolves
  const langChanged = crd.prevLang !== null && crd.prevLang !== vm.lang;
  crd.vm = vm;
  const s = t();
  renderStatics();

  /* check hero */
  const c = vm.check;
  const hero = $("c-hero");
  if (crd.prevTone.check !== c.tone) {
    hero.setAttribute("data-tone", c.tone);
    hero.querySelector(".mascot").src = heroPicture(c.tone);
    bopHero(hero);
    if (c.tone === "ok" && crd.prevTone.check !== null) popConfetti();
    if (c.tone === "bad" && crd.prevTone.check !== null) alarm(hero);
    crd.prevTone.check = c.tone;
  }
  setChip($("c-chip"), c.tone, c.chip);
  $("c-status").textContent = crd.toast.check || c.status;
  $("c-head").textContent = c.head;
  if (crd.prevBrief.check !== c.brief) {
    $("c-brief").innerHTML = md(c.brief);
    crd.prevBrief.check = c.brief;
  }
  const cta = $("c-cta");
  cta.textContent = c.running ? s.ctaRun : (c.phase === "done" ? s.ctaAgain : s.cta);
  cta.disabled = c.running || !c.canCheck;
  cta.classList.toggle("off", c.running);
  $("c-walker").classList.toggle("hidden", !c.running);
  const cancelBtn = $("c-cancel");
  cancelBtn.classList.toggle("hidden", !c.running);
  cancelBtn.textContent = s.cancel;
  cancelBtn.disabled = c.cancelling;

  /* setup strip */
  $("v-model").textContent = c.model; $("v-effort").textContent = c.effort;
  const sel = $("sel-model");
  if (c.model && ![...sel.options].some((o) => o.value === c.model)) {
    const o = document.createElement("option");  // e.g. the config.toml model, or a typed slug
    o.value = c.model; o.textContent = c.model;
    sel.insertBefore(o, sel.firstChild);
  }
  const custom = sel.querySelector('option[value="__custom__"]');
  if (custom) custom.textContent = s.customModel;
  sel.value = c.model;
  const eff = $("sel-effort"), effKey = (c.efforts || []).join(",");
  if (eff.dataset.key !== effKey) {  /* the choices follow the model (from Codex's catalog) */
    eff.innerHTML = c.efforts.map((m) => '<option value="' + esc(m) + '">' + esc(m) + "</option>").join("");
    eff.dataset.key = effKey;
  }
  eff.value = c.effort;
  $("v-repeat").textContent = c.repeat;
  const wp = $("wirepill");
  $("k-wire").textContent = c.wireEnabled ? s.wire : s.wireOff;
  wp.classList.toggle("disabled", !c.wireEnabled);
  $("wireswitch").classList.toggle("on", c.wire);
  $("codexpill").textContent = "codex · " + c.codexLabel;
  $("codexpill").title = c.codexTitle || "";

  /* check results */
  $("c-count").textContent = c.rows.length;
  setRoute("c", c.rows);
  const phaseFlip = crd.prevPhase === "running" && c.phase === "done";  // replay the stagger on completion
  const animFrom = langChanged ? -1 : phaseFlip ? 0 :
    (c.rows.length > Math.max(0, crd.prevRows.check) ? Math.max(0, crd.prevRows.check) : -1);
  renderRows($("c-rows"), c.rows, animFrom);
  crd.prevPhase = c.phase;
  crd.prevRows.check = c.rows.length;
  $("c-empty").classList.toggle("hidden", c.rows.length > 0);
  $("c-empty-text").textContent = s.empty;
  $("c-empty-img").src = (c.tone === "warn") ? window.MOOD_ERROR_SRC : window.MOOD_IDLE_SRC;
  $("btn-copy").disabled = !c.canCopy; $("btn-json").disabled = !c.canJson; $("btn-logs").disabled = !c.canLogs;
  $("c-dpre").textContent = c.details || s.detailsEmpty;

  /* live */
  const l = vm.live;
  const lhero = $("l-hero");
  if (crd.prevTone.live !== l.tone) {
    lhero.setAttribute("data-tone", l.tone);
    lhero.querySelector(".mascot").src = heroPicture(l.tone);
    bopHero(lhero);
    if (l.tone === "bad" && crd.prevTone.live !== null) alarm(lhero);
    crd.prevTone.live = l.tone;
  }
  setChip($("l-chip"), l.tone, l.chip);
  $("l-status").textContent = crd.toast.live || l.status;
  $("l-head").textContent = l.head;
  if (crd.prevBrief.live !== l.brief) {
    $("l-brief").innerHTML = md(l.brief);
    crd.prevBrief.live = l.brief;
  }
  const lcta = $("l-cta");
  lcta.textContent = l.on ? s.liveStop : s.liveStart;
  lcta.classList.toggle("stop", l.on);
  lcta.disabled = !l.canStart && !l.on;
  $("l-folder").textContent = l.folder;
  $("l-folder").title = l.folderFull || l.folder;
  $("lv-model").textContent = l.cfgModel || "—";
  $("lv-effort").textContent = l.cfgEffort || "—";
  $("cfgpill").title = l.cfgSource || "";
  $("l-proxy").textContent = l.proxy || "—";

  $("l-count").textContent = l.rows.length;
  setRoute("l", l.rows);
  const lAnimFrom = langChanged ? -1 : (l.rows.length > Math.max(0, crd.prevRows.live) ? Math.max(0, crd.prevRows.live) : -1);
  renderRows($("l-rows"), l.rows, lAnimFrom);
  crd.prevRows.live = l.rows.length;
  $("l-empty").classList.toggle("hidden", l.rows.length > 0);
  $("l-empty-text").textContent = s.liveEmpty;
  $("l-empty-img").src = (l.tone === "warn") ? window.MOOD_ERROR_SRC : window.MOOD_IDLE_SRC;
  $("btn-livecopy").disabled = !l.canCopy; $("btn-liveclear").disabled = !l.canClear;
  $("l-dpre").textContent = l.notes || s.detailsEmpty;

  /* footer */
  const ver = $("version");
  if (vm.updateBadge) { ver.textContent = vm.updateBadge; ver.classList.add("new"); }
  else { ver.textContent = "v" + vm.version; ver.classList.remove("new"); }

  crd.prevLang = vm.lang;
}
window.render = render;

function toast(tab, msg) {
  crd.toast[tab] = msg;
  $((tab === "check" ? "c" : "l") + "-status").textContent = msg;
  clearTimeout(crd.toastTimer[tab]);
  crd.toastTimer[tab] = setTimeout(() => {
    crd.toast[tab] = null;
    if (crd.vm) $((tab === "check" ? "c" : "l") + "-status").textContent =
      (tab === "check" ? crd.vm.check.status : crd.vm.live.status);
  }, 3500);
}
window.toast = toast;

/* ---------------------------------------------------------------- tabs */
function selectTab(name) {
  if (crd.tab === name) return;
  crd.tab = name;
  $("tab-check").classList.toggle("on", name === "check");
  $("tab-live").classList.toggle("on", name === "live");
  const page = $(name === "check" ? "page-check" : "page-live");
  const other = $(name === "check" ? "page-live" : "page-check");
  other.classList.add("hidden");
  page.classList.remove("hidden");
  page.classList.remove("slide"); void page.offsetWidth; page.classList.add("slide");
  if (name === "live" && crd.guidePending) { crd.guidePending = false; showGuide(); }
}

/* ---------------------------------------------------------------- modals */
function closeOverlay() { const ov = $("overlay"); ov.classList.add("hidden"); ov.innerHTML = ""; resetOverlay(); }

/* only Help closes on a backdrop click, and only when the press also started on the backdrop
   (a text selection dragged out of the card ends with a click on the overlay) */
function resetOverlay() { const ov = $("overlay"); ov.onclick = null; ov.onmousedown = null; }
function closeOnBackdrop() {
  const ov = $("overlay");
  let downOnBackdrop = false;
  ov.onmousedown = (e) => { downOnBackdrop = e.target === ov; };
  ov.onclick = (e) => { if (downOnBackdrop && e.target === ov) closeOverlay(); downOnBackdrop = false; };
}

/* help and dialog text: escaped, then `code` becomes a code chip and **bold** bold */
function md(text) {
  return esc(text).replace(/`([^`]+)`/g, "<code>$1</code>").replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>");
}

function modalHead(title, sub, closable) {
  return '<div class="mhead"><img src="' + window.AVATAR_SRC + '" alt=""><div class="mtitles"><div class="mt">' +
    esc(title) + "</div>" + (sub ? '<div class="ms">' + esc(sub) + "</div>" : "") + "</div>" +
    (closable ? '<button class="xbtn" id="m-x">&#10005;</button>' : "") + "</div>";
}

function showConfirm(opts) {
  resetOverlay();
  const ov = $("overlay");
  ov.innerHTML =
    '<div class="modal win">' + modalHead(opts.title) +
    '<div class="mbody">' + md(opts.body) + "</div>" +
    (opts.checkbox ? '<label class="mcheck"><input type="checkbox" id="m-skip"> ' + esc(opts.checkbox) + "</label>" : "") +
    '<div class="mrow"><button class="mbtn plain" id="m-cancel">' + esc(opts.cancel) + "</button>" +
    '<button class="mbtn primary" id="m-ok">' + esc(opts.ok) + "</button></div></div>";
  ov.classList.remove("hidden");
  $("m-cancel").onclick = () => { closeOverlay(); if (opts.onCancel) opts.onCancel(); };
  $("m-ok").onclick = () => {
    const skip = opts.checkbox ? $("m-skip").checked : false;
    closeOverlay(); opts.onOk(skip);
  };
  $("m-ok").focus();
}

function showPrompt(title, initial, onOk) {
  resetOverlay();
  const s = t();
  const ov = $("overlay");
  ov.innerHTML =
    '<div class="modal win">' + modalHead(title) +
    '<input id="m-input" class="minput" type="text" spellcheck="false">' +
    '<div class="mrow"><button class="mbtn plain" id="m-cancel">' + esc(s.cancel) + "</button>" +
    '<button class="mbtn primary" id="m-ok">' + esc(s.ok) + "</button></div></div>";
  ov.classList.remove("hidden");
  const input = $("m-input");
  input.value = initial || "";
  const done = () => { const v = input.value.trim(); closeOverlay(); if (v) onOk(v); };
  $("m-cancel").onclick = closeOverlay;
  $("m-ok").onclick = done;
  input.onkeydown = (e) => {
    if (e.key === "Enter") done();
    if (e.key === "Escape") { e.stopPropagation(); closeOverlay(); }
  };
  input.focus(); input.select();
}

/* a help page is a list of sections; an item is a string, {term, text} or {chip, tone, text} */
function helpSections(sections) {
  return sections.map((sec) => {
    let n = 0;
    const items = sec.items.map((it) => {
      if (typeof it === "string") {
        n += 1;
        return sec.numbered
          ? '<div class="hitem num"><span class="n">' + n + "</span>" + md(it) + "</div>"
          : '<div class="hitem">' + md(it) + "</div>";
      }
      const left = it.chip
        ? '<span class="chip" data-tone="' + esc(it.tone || "idle") + '">' + esc(it.chip) + "</span>"
        : '<span class="term">' + md(it.term) + "</span>";
      return '<div class="hrow">' + left + "<span>" + md(it.text) + "</span></div>";
    }).join("");
    return '<section class="hsec"><h4><span class="bub">' + esc(sec.icon) + "</span>" + esc(sec.title) + "</h4>" +
      items + "</section>";
  }).join("");
}

function guideSteps(g) {
  return '<div class="gsteps">' + g.items.map((it, i) =>
    '<div class="gstep" style="animation-delay:' + (i * 70) + 'ms"><span class="bub">' + esc(it.icon) +
    '</span><div><div class="gt">' + md(it.title) + '</div><div class="gx">' + md(it.text) + "</div></div></div>"
  ).join("") + "</div>";
}

function aboutPage(a) {
  return '<div class="about"><img src="' + window.MASCOT_SRC + '" alt=""><div><div class="an">Codex Routing Detector</div>' +
    '<div class="av">v' + esc(a.version) + '</div><div class="al">' + md(a.lead) + "</div></div></div>" +
    '<section class="hsec">' + a.paras.map((p) => '<div class="hitem">' + md(p) + "</div>").join("") +
    '<div class="arepo"><button class="mbtn primary" id="m-repo">' + esc(a.repo) + "</button></div></section>";
}

function setHelpTab(which) {
  const h = crd.HELPS[crd.vm.lang];
  document.querySelectorAll("#overlay [data-help]").forEach((b) => b.classList.toggle("on", b.dataset.help === which));
  const body = $("m-helpbody");
  if (which === "guide") {
    body.innerHTML = '<section class="hsec"><h4><span class="bub">&#128075;</span>' + esc(h.guide.heading) +
      "</h4>" + guideSteps(h.guide) + "</section>";
  } else if (which === "about") {
    body.innerHTML = aboutPage(h.about);
    $("m-repo").onclick = () => call(api().open_repo());
  } else {
    body.innerHTML = helpSections(h[which]);
  }
  body.scrollTop = 0;
  body.classList.remove("fresh"); void body.offsetWidth; body.classList.add("fresh");
}

function showHelp(which) {
  if (!crd.T) return;  // not initialised yet (e.g. --show-help firing early)
  const s = t();
  const kinds = [["usage", s.helpUsage], ["terms", s.helpTerms], ["guide", s.helpGuide], ["about", s.helpAbout]];
  const ov = $("overlay");
  ov.innerHTML =
    '<div class="modal help win">' + modalHead(s.helpTitle, "Codex Routing Detector", true) +
    '<div class="helptabs">' + kinds.map(([k, label]) =>
      '<button data-help="' + k + '">' + esc(label) + "</button>").join("") + "</div>" +
    '<div class="helpbody" id="m-helpbody"></div>' +
    '<div class="mrow"><button class="mbtn plain" id="m-close">' + esc(s.close) + "</button></div></div>";
  ov.classList.remove("hidden");
  ov.querySelectorAll("[data-help]").forEach((b) => b.onclick = () => setHelpTab(b.dataset.help));
  $("m-close").onclick = closeOverlay;
  $("m-x").onclick = closeOverlay;
  closeOnBackdrop();
  setHelpTab(which);
}
window.showHelp = showHelp;

function showGuide() {
  if (!crd.T) return;  // not initialised yet
  const g = crd.HELPS[crd.vm.lang].guide;
  resetOverlay();
  const ov = $("overlay");
  ov.innerHTML =
    '<div class="modal guide win">' + modalHead(g.heading) + guideSteps(g) +
    '<label class="mcheck"><input type="checkbox" id="m-skip"> ' + esc(g.skip) + "</label>" +
    '<div class="mrow"><button class="mbtn primary" id="m-ok">' + esc(g.ok) + "</button></div></div>";
  ov.classList.remove("hidden");
  $("m-ok").onclick = () => { const skip = $("m-skip").checked; closeOverlay(); call(api().guide_closed(skip)); };
  $("m-ok").focus();
}
window.showGuide = showGuide;

function showStopConfirm(mode) {  /* mode: "stop" | "close" */
  if (!crd.T) return;  // not initialised yet (e.g. closing right after --auto-live)
  const g = crd.HELPS[crd.vm.lang];
  const s = t();
  const closing = mode === "close";
  showConfirm({
    title: closing ? s.closeTitle : s.liveStop,
    body: closing ? g.live_close_confirm : g.live_stop_confirm,
    ok: closing ? s.close : s.liveStop, cancel: s.cancel, checkbox: null,
    onOk: () => { call(mode === "close" ? api().confirm_close() : api().stop_live_confirmed()); },
  });
}
window.showStopConfirm = showStopConfirm;

/* Escape: cancel a question, close help, or acknowledge the guide */
document.addEventListener("keydown", (e) => {
  if (e.key !== "Escape" || $("overlay").classList.contains("hidden")) return;
  const b = $("m-cancel") || $("m-close") || $("m-ok");
  if (b) b.click();
});

/* ---------------------------------------------------------------- clipboard */
function copyText(text, tab, doneMsg) {
  const finish = () => toast(tab, doneMsg);
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(text).then(finish, () => { fallbackCopy(text); finish(); });
  } else { fallbackCopy(text); finish(); }
}
function fallbackCopy(text) {
  const ta = document.createElement("textarea");
  ta.value = text; ta.style.position = "fixed"; ta.style.opacity = "0";
  document.body.appendChild(ta); ta.select();
  try { document.execCommand("copy"); } catch (e) {}
  document.body.removeChild(ta);
}

/* ---------------------------------------------------------------- wiring */
function call(p) { return p.catch(() => null); }  // js_api errors surface as rejected promises

function wire() {
  $("tab-check").onclick = () => selectTab("check");
  $("tab-live").onclick = () => selectTab("live");
  document.querySelectorAll("#langtoggle span").forEach((el) =>
    el.onclick = () => call(api().set_lang(el.dataset.lang)));
  $("helpbtn").onclick = () => showHelp("usage");
  $("github").onclick = (e) => { e.preventDefault(); call(api().open_repo()); };
  $("version").onclick = () => { if (crd.vm && crd.vm.updateBadge) call(api().open_update()); };

  $("c-cta").onclick = () => call(api().request_check()).then((ask) => {
    if (!ask) return;
    showConfirm({
      title: ask.title, body: ask.body, checkbox: ask.checkbox, ok: ask.ok, cancel: ask.cancel,
      onOk: (skip) => call(api().run_check_confirmed(skip)),
    });
  });
  $("c-cancel").onclick = () => call(api().cancel_check());
  $("sel-model").onchange = (e) => {
    if (e.target.value === "__custom__") {
      e.target.value = crd.vm.check.model;  // restore until the prompt answers
      showPrompt(t().customModelTitle, crd.vm.check.model, (v) => call(api().set_option("model", v)));
      return;
    }
    call(api().set_option("model", e.target.value));
  };
  $("sel-effort").onchange = (e) => call(api().set_option("effort", e.target.value));
  $("rep-minus").onclick = () => call(api().set_option("repeat", String(crd.vm.check.repeat - 1)));
  $("rep-plus").onclick = () => call(api().set_option("repeat", String(crd.vm.check.repeat + 1)));
  $("wirepill").onclick = () => { if (crd.vm.check.wireEnabled) call(api().set_option("wire", crd.vm.check.wire ? "" : "1")); };
  $("codexpill").onclick = () => call(api().pick_codex());

  $("btn-copy").onclick = () => call(api().copy_report()).then((r) => { if (r) copyText(r.text, "check", r.msg); });
  $("btn-json").onclick = () => call(api().save_json()).then((r) => { if (r) toast("check", r.msg); });
  $("btn-logs").onclick = () => call(api().open_logs());
  $("c-dhead").onclick = () => $("c-details").classList.toggle("open");
  $("l-dhead").onclick = () => $("l-details").classList.toggle("open");

  $("l-cta").onclick = () => call(api().request_live()).then((ask) => {
    if (!ask) return;
    if (ask.mode === "stop") { showStopConfirm("stop"); return; }
    showConfirm({
      title: ask.title, body: ask.body, checkbox: ask.checkbox, ok: ask.ok, cancel: ask.cancel,
      onOk: (skip) => call(api().start_live_confirmed(skip)),
    });
  });
  $("l-folder").onclick = () => { if (!crd.vm.live.on) call(api().pick_live_dir()); };
  $("cfgpill").onclick = () => call(api().open_config());
  $("btn-livecopy").onclick = () => call(api().copy_live_report()).then((r) => { if (r) copyText(r.text, "live", r.msg); });
  $("btn-liveclear").onclick = () => call(api().clear_live());
}

function fillSelects(models, efforts) {
  $("sel-model").innerHTML = models.map((m) => '<option value="' + esc(m) + '">' + esc(m) + "</option>").join("") +
    '<option value="__custom__"></option>';
  $("sel-effort").innerHTML = efforts.map((m) => '<option value="' + esc(m) + '">' + esc(m) + "</option>").join("");
}

window.addEventListener("pywebviewready", () => {
  api().init().then((data) => {
    crd.T = data.t; crd.HELPS = data.helps;
    window.MOOD_IDLE_SRC = $("c-empty-img").src;
    window.MOOD_ERROR_SRC = data.moodError;
    window.MASCOT_SRC = $("c-hero").querySelector(".mascot").src;
    window.AVATAR_SRC = document.querySelector(".header img.logo").src;
    /* the verdict card shows her mood (setMotion fills in idle and running) */
    window.MASCOT_ANIM_SRC = data.hero.anim;
    window.HERO_SRC = { ok: data.hero.ok, bad: data.hero.bad, warn: data.hero.warn };
    crd.guidePending = data.showGuide && !crd.guideSuppressed;
    fillSelects(data.models, data.efforts);
    buildSky();
    document.body.classList.add("opening");
    setTimeout(() => document.body.classList.remove("opening"), 1400);
    wire();
    const first = crd.pendingVm || data.vm;  // a push may have landed before init() resolved
    crd.pendingVm = null;
    setMotion();
    render(first);
    REDUCE_MOTION.addEventListener("change", setMotion);
  });
});
</script>
</body>
</html>
"""


def _korean_faces() -> str:
    """NanumSquareRound in the weights the page uses: 400 for text, 700 for labels and titles
    (the browser also picks it for 600), 800 for the verdict headline."""
    rule = ('@font-face {{ font-family: "NanumSquareRound"; font-style: normal; font-weight: {w};\n'
            '  src: url(data:font/woff2;base64,{b64}) format("woff2"); }}')
    return "\n".join(rule.format(w=w, b64=b64) for w, b64 in sorted(fonts.NANUM_SQUARE_ROUND.items()))


def build_page() -> str:
    return (PAGE
            .replace("__MASCOT__", _data_uri("mascot_256"))
            .replace("__AVATAR__", _data_uri("icon_112"))
            .replace("__MOOD_IDLE__", _data_uri("mood_idle_56"))
            .replace("__FONT_MONO__", "data:font/woff2;base64," + fonts.FONTS["jetbrains_mono"])
            .replace("__FONT_KO_FACES__", _korean_faces()))


def preview_page(data: dict, after: str = "") -> str:
    """Development only (screenshots, tests): the page with a stand-in for pywebview's API whose init()
    returns `data` and whose other calls do nothing; the JavaScript `after` runs once it has rendered."""
    stub = ("<script>window.pywebview = {api: new Proxy({}, {get: (t, k) => k === 'init' ? "
            "() => Promise.resolve(" + json.dumps(data) + ") : () => Promise.resolve(null)})};"
            "setTimeout(() => { window.dispatchEvent(new Event('pywebviewready')); "
            "setTimeout(() => { " + after + " }, 300); }, 50);</script>")
    return build_page().replace("</body>", stub + "</body>")


# ------------------------------------------------------------------ view model
class WebApp:
    """All state and logic behind the page. `window` is a pywebview window (or None in tests);
    the page calls the public methods through js_api, Python pushes the view model back with
    render()."""

    def __init__(self, lang: str = "en", fake: bool = False, exit_after: Optional[float] = None,
                 update_check: bool = True, auto_update: bool = True, updated_from: Optional[str] = None,
                 confirm: bool = True) -> None:
        self.window = None  # set by main() after create_window
        self.lock = threading.RLock()
        self.settings = tkgui.load_settings()
        self.lang = lang if lang in UI else "en"
        self.fake = fake
        self.exit_after = exit_after
        self.confirm_before_check = confirm and not bool(self.settings.get("skip_confirm"))
        self.confirm_live = confirm

        # check state
        self.phase = "idle"          # idle | running | done
        self.worker: Optional[threading.Thread] = None
        self.cancel: Optional[cmc.Canceller] = None
        self.cancelling = False
        self.result: Optional[cmc.CheckResult] = None
        self.run_probes: List[cmc.Probe] = []
        self.progress: Optional[tuple] = None  # (event, info)
        self.t0 = 0.0
        self.done_secs = 0.0
        self.models = tkgui.listed_models()
        self.model_efforts = catalog_efforts()
        cfg_model, self.cfg_tier, _ = cmc.read_config_values()
        self.opt = {"model": cfg_model or self.models[0], "effort": "low", "repeat": 1, "wire": False}
        self.have_mitm = bool(cmc.shutil.which("mitmdump"))
        self.codex_path: Optional[str] = None

        # live state
        self.monitor: Optional[live.LiveMonitor] = None
        self.agg = live.LiveAggregator()
        self.live_lines: List[str] = []
        self.live_ended: Optional[str] = None
        self.live_dir = str(self.settings.get("live_dir") or Path.home())
        if not os.path.isdir(self.live_dir):
            self.live_dir = str(Path.home())
        self.launcher = tkgui.fake_launcher if fake else live.launch_in_terminal
        self.cfg_live = live.read_config_model_effort()
        self._cfg_mtime = live.config_mtime()
        self.guide_shown = False

        # updates
        self.auto_update = auto_update
        self.updated_from = updated_from
        self.updating = False
        self.update_info: Optional[dict] = None
        self.update_status: Optional[str] = None
        self.exe_path = Path(sys.executable)
        self._threads_started = False
        self._closed = False
        self._exit_timer_started = False
        # All evaluate_js calls go through one pusher thread: a worker calling into the WebView2
        # UI thread directly (Control.Invoke) can deadlock against a closing window.
        self._push_evt = threading.Event()
        threading.Thread(target=self._push_loop, name="crd-push", daemon=True).start()
        if update_check:
            threading.Thread(target=self._check_update, daemon=True).start()

    # ------------------------------------------------------------ strings
    def s(self, key: str, **kw) -> str:
        """Status lines and dialogs: the web window's own wording first, then the shared table."""
        text = webtext.TEXT[self.lang].get(key) or tkgui.STRINGS[self.lang][key]
        return text.format(**kw)

    def v(self, key: str, **kw) -> str:
        """The verdict card's headline and plain-words paragraph."""
        text = webtext.VERDICT[self.lang][key]
        return text.format(**kw) if kw else text

    def u(self, key: str, **kw) -> str:
        text = UI[self.lang][key]
        return text.format(**kw) if kw else text

    # ------------------------------------------------------------ push
    def push(self) -> None:
        """Ask the pusher thread to send the current view model to the page. Never blocks, so it
        is safe from any thread and from inside `with self.lock` blocks."""
        self._push_evt.set()

    def _push_loop(self) -> None:
        while True:
            self._push_evt.wait()
            self._push_evt.clear()
            if self._closed:
                return
            win = self.window
            if win is None:
                continue
            try:
                win.evaluate_js("window.render(%s)" % json.dumps(self.build_vm(), ensure_ascii=True))
            except Exception:
                pass  # window already gone

    def _js(self, script: str) -> None:
        win = self.window
        if win is None:
            return
        try:
            win.evaluate_js(script)
        except Exception:
            pass

    # ------------------------------------------------------------ view model
    def build_vm(self) -> dict:
        with self.lock:
            return {
                "lang": self.lang,
                "version": cmc.__version__,
                "updateBadge": self.s("update_new", new=self.update_info["version"]) if self.update_info else None,
                "check": self._check_vm(),
                "live": self._live_vm(),
            }

    def _check_status_line(self) -> str:
        if self.update_status:
            return self.update_status
        if self.phase == "running":
            if self.cancelling:
                return self.s("cancelling")
            if self.progress and self.progress[0] == "probe_start":
                i = self.progress[1]
                return f"probe {i['i']}/{i['n']} · {i['model']} ({i['effort']})"
            if self.progress and self.progress[0] == "start":
                return self.s("starting", version=self.progress[1]["codex_version"])
            return self.u("statusPreparing")
        if self.phase == "done" and self.result is not None:
            res = self.result
            if res.error:
                return self.s("failed")
            if res.cancelled:
                return self.s("cancelled")
            text = self.u("statusDone", secs=self.done_secs)
            if self.fake:
                text += "  " + self.s("fake")
            return text
        if self.updated_from:
            return self.s("updated", current=cmc.__version__)
        return self.u("statusIdle")

    def _check_verdict(self) -> str:
        res = self.result
        if res is None:
            return "IDLE"
        if res.error:
            return "ERROR"
        if res.overall == "REROUTED":
            return "REROUTED"
        if res.cancelled:
            return "CANCELLED"
        return res.overall

    def _check_head_chip(self) -> tuple:
        """(tone, chip label, headline) for the check hero."""
        if self.phase == "running":
            return "running", self.u("chipRun"), self.u("runHead")
        if self.phase == "idle" or self.result is None:
            return "idle", self.u("chipIdle"), self.u("idleHead")
        res = self.result
        v = self._check_verdict()
        if v == "REROUTED":
            return "bad", self.u("chipBad"), self.u("badHead")
        if v == "OK":
            return "ok", self.u("chipOk"), self.v("okHead", model=self._requested(res))
        if v == "CANCELLED":
            return "idle", self.u("chipIdle"), self.u("cancelledHead")
        if v == "UNSUPPORTED":
            return "warn", self.u("chipWarn"), self.v("unsupportedHead")
        if res.error:
            return "warn", self.u("chipWarn"), self.v("fatalHead")
        return "warn", self.u("chipWarn"), self.v("errorHead")

    @staticmethod
    def _requested(res: cmc.CheckResult) -> str:
        return ", ".join(sorted({p.requested for p in res.probes if not p.is_control})) or "?"

    def _check_brief(self) -> str:
        """Plain words under the headline: which model was called and which one answered.
        Plan and usage figures are left to Details and the copied report."""
        if self.phase == "running":
            return self.v("runBrief")
        res = self.result
        if res is None:
            return self.v("idleBrief")
        if res.error:
            return self.v("fatalBrief")
        requested = self._requested(res)
        main = [p for p in res.probes if not p.is_control]
        if res.overall == "REROUTED":  # before `cancelled`: a substitution already found is kept
            served, bad, total = set(), 0, 0
            for p in main:
                for r in p.responses:
                    verdict = r.verdict(p.requested)
                    if verdict in ("ok", "REROUTED"):
                        total += 1
                    if verdict == "REROUTED":
                        bad += 1
                        served.update(m for m in r.models_seen if not cmc.models_match(p.requested, m)[0])
            return " ".join([self.v("badBrief", requested=requested, served=", ".join(sorted(served)) or "?",
                                    bad=bad, total=total), self.v("badTip")])
        if res.overall == "OK":
            return self.v("okBrief", model=requested)
        if res.overall == "UNSUPPORTED":
            return self.v("unsupportedBrief", requested=requested)
        if res.cancelled:
            return self.v("cancelledBrief")
        errors = sorted({r.error_code or "?" for p in main for r in p.responses if r.error_code} |
                        {c or "?" for p in main for c, _ in p.stream_errors})
        if errors:
            return self.v("errorBrief", requested=requested, errors=", ".join(errors))
        return self.v("nodataBrief", requested=requested)

    def _check_rows(self) -> List[dict]:
        rows: List[dict] = []
        kind_name = {"warmup": self.s("kind_warmup"), "turn": self.s("kind_turn")}
        probes = self.run_probes if self.phase == "running" else \
            (self.result.probes if self.result is not None else [])
        for p in probes:
            if not p.responses and not p.stream_errors:
                v = p.verdict()
                rows.append({"n": p.index, "kind": "-", "requested": p.requested, "served": "-",
                             "status": v, "time": "-", "rid": "-", "tone": _tone_of(v), "verdict": v})
            for r in p.responses:
                v = r.verdict(p.requested)
                rows.append({"n": p.index, "kind": kind_name.get(r.kind, r.kind), "requested": p.requested,
                             "served": r.model or "?", "status": r.status or "?",
                             "time": cmc.fmt_time(r.created_at), "rid": r.response_id,
                             "tone": _tone_of(v), "verdict": v})
            for code, msg in p.stream_errors:
                v = "UNSUPPORTED" if cmc.is_unsupported_error(code, msg) else "ERROR"
                rows.append({"n": p.index, "kind": "-", "requested": p.requested, "served": "-",
                             "status": code or "?", "time": "-", "rid": "-", "tone": _tone_of(v), "verdict": v})
        return rows

    def _check_details(self) -> str:
        res = self.result
        if res is None:
            return ""
        lines: List[str] = []
        if res.error:
            lines.append(res.error)
            if res.error_kind in ("codex_missing", "codex_failed"):
                lines.append(self.s("codex_hint"))
        else:
            acct = cmc.account_line(res.probes)
            if acct:
                lines.append(f"{self.s('account')}: {acct}")
            lines.append(f"{self.s('codex')}: {res.codex_desc} ({res.codex_version}, {res.method})")
            if res.outdir:
                lines.append(f"logs: {cmc.display_path(res.outdir)}")
            lines.extend(res.summary_lines)
            for p in res.probes:
                for r in p.responses:
                    if r.verdict(p.requested) == "ERROR" or r.error_code or r.error_message:
                        lines.append(f"#{p.index} {p.requested}: error {r.error_code}: {r.error_message}")
                for code, msg in p.stream_errors:
                    lines.append(f"#{p.index} {p.requested}: error {code}: {msg}")
                for n in p.notes:
                    lines.append(f"#{p.index} {p.requested}: {n}")
        return "\n".join(lines)

    def _check_vm(self) -> dict:
        tone, chip, head = self._check_head_chip()
        res = self.result
        running = self.phase == "running"
        have = res is not None and not running
        usable = have and res is not None and res.error is None and res.outdir is not None
        codex_label = Path(self.codex_path).name if self.codex_path else self.s("codex_auto")
        return {
            "phase": self.phase, "running": running, "cancelling": self.cancelling,
            "tone": tone, "chip": chip, "head": head,
            "brief": self._check_brief(), "status": self._check_status_line(),
            "rows": self._check_rows(), "details": self._check_details(),
            "canCheck": not running and not self.updating,
            "canCopy": bool(have), "canJson": bool(usable), "canLogs": bool(usable),
            "model": self.opt["model"], "effort": self.opt["effort"], "repeat": self.opt["repeat"],
            "efforts": self.efforts_for(self.opt["model"]),
            "wire": bool(self.opt["wire"]) and self.have_mitm, "wireEnabled": self.have_mitm,
            "codexLabel": codex_label, "codexTitle": self.codex_path or "",
        }

    # ------------------------------------------------------------ live view model
    def _live_state(self) -> tuple:
        """(tone, chip, head, brief) for the live hero, mirroring the tkinter summary. Per the
        design spec, a stopped monitor always shows the neutral off hero; the rows (and the
        copyable report) keep the session's verdicts until 지우기/Clear."""
        running = self.monitor is not None
        if not running:
            return "idle", self.u("liveChipOff"), self.v("liveIdleHead"), self.v("liveIdleBrief")
        rows = self.agg.rows
        requested = ", ".join(sorted({r.requested for r in rows if r.requested})) or "?"
        # A response that is still streaming has no final verdict yet (UNKNOWN): it is neither an
        # error nor a confirmed answer, so it only makes the card wait.
        pending = [r for r in rows if _is_pending(r)]
        settled = [r for r in rows if not _is_pending(r)]
        verdicts = [r.verdict() for r in settled]
        if "REROUTED" in verdicts:
            served = sorted({m for r in settled for m in r.other_models()})
            brief = " ".join([self.v("liveBadBrief", requested=requested, served=", ".join(served) or "?",
                                     bad=verdicts.count("REROUTED"), total=len(settled)), self.v("badTip")])
            return "bad", self.u("liveChipBad"), self.u("badHead"), brief
        ok_turn = any(r.kind == "turn" and v == "ok" for r, v in zip(settled, verdicts))
        if ok_turn or ("ok" in verdicts and not pending and set(verdicts) == {"ok"}):
            return ("running", self.u("liveChipOn"), self.v("liveOkHead"),
                    self.v("liveOkBrief", requested=requested, n=verdicts.count("ok")))
        if "UNSUPPORTED" in verdicts:
            return ("warn", self.u("liveChipWarn"), self.v("unsupportedHead"),
                    self.v("liveUnsupportedBrief", requested=requested))
        if "ERROR" in verdicts:
            errs = sorted({(r.error_code or (r.record.error_code if r.record else None) or "?")
                           for r in settled if r.verdict() == "ERROR"})
            return ("warn", self.u("liveChipWarn"), self.v("liveErrorHead"),
                    self.v("liveErrorBrief", requested=requested, errors=", ".join(errs)))
        if pending:
            return "running", self.u("liveChipOn"), self.v("liveWaitHead"), self.v("livePendingBrief", requested=requested)
        if "UNKNOWN" in verdicts:
            return ("warn", self.u("liveChipWarn"), self.v("liveUnknownHead"),
                    self.v("liveUnknownBrief", requested=requested))
        return "running", self.u("liveChipOn"), self.v("liveWaitHead"), self.v("liveWaitBrief")

    def _live_rows(self) -> List[dict]:
        kind_name = {"warmup": self.s("kind_warmup"), "turn": self.s("kind_turn"), "error": "-"}
        rows = []
        for r in self.agg.rows:
            v = r.verdict()
            rows.append({"n": r.n, "kind": kind_name.get(r.kind, r.kind), "requested": r.requested or "?",
                         "served": r.served or "-", "status": r.status or r.error_code or "-",
                         "time": time.strftime("%H:%M:%S", time.localtime(r.first_seen)),
                         "rid": r.response_id, "tone": _tone_of(v), "verdict": v})
        return rows

    def _live_status_line(self) -> str:
        mon = self.monitor
        if mon is not None and mon.proxy is not None:
            pid = (mon.proc.pid if mon.proc is not None else 0) or "?"
            return f"pid {pid} · 127.0.0.1:{mon.proxy.port}"
        if self.live_ended is None:
            return self.u("liveStatusOff")
        if self.live_ended.startswith("exit:"):
            return self.s("live_codex_exit", rc=self.live_ended[5:])
        return self.s("live_stopped")

    def _live_vm(self) -> dict:
        tone, chip, head, brief = self._live_state()
        running = self.monitor is not None
        have = bool(self.agg.rows) or bool(self.live_lines)
        model, effort, src = self.cfg_live
        return {
            "on": running, "tone": tone, "chip": chip, "head": head, "brief": brief,
            "status": self._live_status_line(),
            "rows": self._live_rows(), "notes": "\n".join(self.live_lines),
            "cfgModel": model or self.s("live_cfg_none"), "cfgEffort": effort or self.s("live_cfg_none"),
            "cfgSource": src,
            "folder": cmc.display_path(self.live_dir), "folderFull": self.live_dir,
            "proxy": (f"127.0.0.1:{self.monitor.proxy.port}" if running and self.monitor.proxy else None),
            "canStart": not self.updating, "canCopy": bool(self.agg.rows),
            "canClear": bool(have and not running),
        }

    # ------------------------------------------------------------ js_api: general
    def init(self) -> dict:
        with self.lock:
            self._start_threads()
            helps = {}
            for lang in ("ko", "en"):
                pages = webtext.HELP[lang]
                helps[lang] = {
                    "usage": pages["usage"], "terms": pages["terms"], "guide": pages["guide"],
                    "about": dict(pages["about"], version=cmc.__version__),
                    "live_stop_confirm": webtext.TEXT[lang]["live_stop_confirm"],
                    "live_close_confirm": webtext.TEXT[lang]["live_close_confirm"],
                }
            return {
                "t": UI, "helps": helps, "models": self.models, "efforts": EFFORTS,
                "moodError": _data_uri("mood_error_56"),
                "hero": {"anim": _data_uri("mascot_anim"), "ok": _data_uri("mood_ok_256"),
                         "bad": _data_uri("mood_rerouted_256"), "warn": _data_uri("mood_error_256")},
                "showGuide": not bool(self.settings.get("skip_live_guide")),
                "vm": self.build_vm(),
            }

    def _start_threads(self) -> None:
        if self._threads_started:
            return
        self._threads_started = True
        threading.Thread(target=self._watch_config, daemon=True).start()

    def set_lang(self, lang: str) -> None:
        with self.lock:
            if lang not in UI:
                return
            self.lang = lang
            self.settings["lang"] = lang
            tkgui.save_settings(self.settings)
        self.push()

    def guide_closed(self, skip: bool) -> None:
        with self.lock:
            self.guide_shown = True
            if skip:
                self.settings["skip_live_guide"] = True
                tkgui.save_settings(self.settings)

    def open_repo(self) -> None:
        webbrowser.open(REPO_URL)

    def open_update(self) -> None:
        webbrowser.open((self.update_info or {}).get("url") or cmc.RELEASES_URL)

    def open_config(self) -> None:
        cfg = cmc.codex_home() / "config.toml"
        if cfg.exists():
            self._open_path(cfg)

    def _open_path(self, path: Path) -> None:
        try:
            if os.name == "nt":
                os.startfile(str(path))  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                cmc.subprocess.Popen(["open", str(path)])
            else:
                cmc.subprocess.Popen(["xdg-open", str(path)])
        except Exception:
            pass

    # ------------------------------------------------------------ js_api: check
    def set_option(self, key: str, value: str) -> None:
        with self.lock:
            if key == "model" and value:
                self.opt["model"] = value
                self._fit_effort()
            elif key == "effort" and value in self.efforts_for(self.opt["model"]):
                self.opt["effort"] = value
            elif key == "repeat":
                try:
                    self.opt["repeat"] = min(MAX_REPEAT, max(1, int(value)))
                except ValueError:
                    pass
            elif key == "wire":
                self.opt["wire"] = bool(value) and self.have_mitm
        self.push()

    def efforts_for(self, model: str) -> List[str]:
        """The efforts the window offers for `model`: what Codex's catalog says it supports
        (minus ultra), or the classic four for a model the catalog does not know."""
        return self.model_efforts.get(cmc.strip_provider_prefix(model)) or list(EFFORTS)

    def _fit_effort(self) -> None:
        """A model switch keeps the effort when the new model has it, else falls back to low."""
        levels = self.efforts_for(self.opt["model"])
        if self.opt["effort"] not in levels:
            self.opt["effort"] = "low" if "low" in levels else levels[0]

    def pick_codex(self) -> None:
        import webview
        win = self.window
        if win is None:
            return
        # pywebview only accepts "*" / "*.ext" patterns in filters (a bare name raises ValueError)
        kinds = ("codex (*.exe;*.cmd)", "All files (*.*)") if os.name == "nt" else ("All files (*.*)",)
        picked = win.create_file_dialog(webview.OPEN_DIALOG, file_types=kinds)
        if picked:
            self.codex_path = picked[0] if isinstance(picked, (list, tuple)) else str(picked)
        self.push()

    def options(self) -> cmc.CheckOptions:
        return cmc.CheckOptions(models=[str(self.opt["model"]).strip() or cmc.FALLBACK_MODEL], control=None,
                                effort=self.opt["effort"] or "low", repeat=int(self.opt["repeat"]),
                                wire=bool(self.opt["wire"]) and self.have_mitm, codex=self.codex_path)

    def request_check(self) -> Optional[dict]:
        """Returns the confirmation dialog to show, or None when the check started directly."""
        with self.lock:
            if self.worker is not None or self.updating:
                return None
            if not self.confirm_before_check:
                self._start_check()
                return None
            opts = self.options()
            body = self.s("confirm_body", model=opts.models[0])
            if opts.repeat > 1:
                body += " " + self.u("confirmRepeat", n=opts.repeat)
            return {"title": self.s("confirm_title"), "body": body,
                    "checkbox": self.s("confirm_skip"), "ok": self.s("confirm_ok"),
                    "cancel": self.s("confirm_cancel")}

    def run_check_confirmed(self, skip: bool) -> None:
        with self.lock:
            if skip:
                self.settings["skip_confirm"] = True
                tkgui.save_settings(self.settings)
                self.confirm_before_check = False
            self._start_check()

    def start_check(self, confirm: Optional[bool] = None) -> None:
        """Programmatic start (dev flags / tests); `confirm=False` skips the dialog."""
        with self.lock:
            if confirm is None and self.confirm_before_check:
                return  # interactive path goes through request_check
            self._start_check()

    def _start_check(self) -> None:
        if self.worker is not None or self.updating:
            return
        self.update_status = None  # a pip/manual/failed update hint must not mask the run status
        opts = self.options()
        self.cancel = cmc.Canceller()
        self.cancelling = False
        self.result = None
        self.run_probes = []
        self.progress = None
        self.phase = "running"
        self.t0 = time.time()
        cancel = self.cancel

        def work() -> None:
            try:
                res = cmc.run_check(opts, progress=self._on_progress, cancel=cancel)
                self._on_done(res)
            except Exception as e:  # keep the UI alive whatever happens in the worker
                self._on_done(cmc.CheckResult(error=f"{type(e).__name__}: {e}"))

        self.worker = threading.Thread(target=work, daemon=True)
        self.worker.start()
        self.push()

    def _on_progress(self, ev: str, info: dict) -> None:
        with self.lock:
            if ev == "probe_done":
                self.run_probes.append(info["probe"])
            else:
                self.progress = (ev, info)
        self.push()

    def _on_done(self, res: cmc.CheckResult) -> None:
        with self.lock:
            self.worker = None
            self.done_secs = round(time.time() - self.t0, 1)
            self.result = res
            self.phase = "done"
            self.cancelling = False
        self.push()
        if self.exit_after is not None and not self._exit_timer_started:
            self._exit_timer_started = True
            timer = threading.Timer(self.exit_after, self._destroy)
            timer.daemon = True  # never keep the process alive after the window is closed
            timer.start()

    def cancel_check(self) -> None:
        with self.lock:
            if self.cancel is not None and self.phase == "running":
                self.cancelling = True
                self.cancel.cancel()
        self.push()

    def copy_report(self) -> Optional[dict]:
        with self.lock:
            res = self.result
            if res is None:
                return None
            return {"text": res.report(full_ids=True), "msg": self.s("copied")}

    def save_json(self) -> Optional[dict]:
        import webview
        with self.lock:
            res = self.result
        if res is None or res.error or self.window is None:
            return None
        picked = self.window.create_file_dialog(webview.SAVE_DIALOG, save_filename="codex-routing-detector.json",
                                                file_types=("JSON (*.json)",))
        if not picked:
            return None
        path = picked[0] if isinstance(picked, (list, tuple)) else str(picked)
        try:
            Path(path).write_text(json.dumps(res.json(), indent=2), encoding="utf-8")
        except OSError as e:  # e.g. a read-only folder: tell the user instead of failing silently
            return {"msg": f"{type(e).__name__}: {e}"}
        return {"msg": self.s("saved", path=cmc.display_path(path))}

    def open_logs(self) -> None:
        if self.result is not None and self.result.outdir:
            self._open_path(self.result.outdir)

    # ------------------------------------------------------------ js_api: live
    def request_live(self) -> Optional[dict]:
        """Start/stop button. Returns a dialog description, or None when handled directly."""
        with self.lock:
            if self.monitor is not None:
                if self.monitor.codex_running():
                    return {"mode": "stop"}
                self._end_live("stopped")
                self.push()
                return None
            if self.updating:
                return None
            if not crp.have_crypto():
                self._live_note(self.s("live_needs_crypto"))
                self.push()
                return None
            # The live dialog asks for consent to the local proxy and certificate, so only its own
            # "don't ask again" (skip_confirm_live) skips it, not the check dialog's (skip_confirm).
            ask = self.confirm_live and not self.settings.get("skip_confirm_live")
            if not ask:
                self._start_live()
                return None
            return {"mode": "start", "title": self.s("confirm_live_title"), "body": self.s("confirm_live_body"),
                    "checkbox": self.s("confirm_skip"), "ok": self.s("confirm_live_ok"),
                    "cancel": self.s("confirm_cancel")}

    def start_live_confirmed(self, skip: bool) -> None:
        with self.lock:
            if skip:
                self.settings["skip_confirm_live"] = True
                tkgui.save_settings(self.settings)
            self._start_live()

    def start_live(self, confirm: Optional[bool] = None) -> None:
        """Programmatic start (dev flags / tests)."""
        with self.lock:
            if self.monitor is not None or self.updating:
                return
            if not crp.have_crypto():
                self._live_note(self.s("live_needs_crypto"))
                self.push()
                return
            self._start_live()

    def _start_live(self) -> None:
        if self.monitor is not None:
            return
        codex, how = cmc.find_codex(self.codex_path)
        if not codex:
            self._live_note(f"codex binary not found ({how}). " + self.s("codex_hint"))
            self.push()
            return
        self._clear_live()
        mon = live.LiveMonitor(codex, self.live_dir, launcher=self.launcher)
        try:
            mon.start()
        except Exception as e:
            self._live_note(f"{type(e).__name__}: {e}")
            self.push()
            return
        self.monitor = mon
        self.live_ended = None
        self._live_note(f"{self.s('codex')}: {' '.join(cmc.display_path(c) for c in codex)} ({how})")
        threading.Thread(target=self._live_pump, args=(mon,), daemon=True).start()
        self.push()

    def _live_pump(self, mon: live.LiveMonitor) -> None:
        """Drains the monitor's event queue until the session ends; pushes after each batch."""
        while True:
            with self.lock:
                if self.monitor is not mon:
                    return
            try:
                ev = mon.events.get(timeout=0.25)
            except queue.Empty:
                continue
            events = [ev]
            while True:
                try:
                    events.append(mon.events.get_nowait())
                except queue.Empty:
                    break
            ended = self._feed_live_events(mon, events)
            self.push()
            if ended:
                return

    def _feed_live_events(self, mon: live.LiveMonitor, events: List[tuple]) -> bool:
        """Apply a batch of monitor events. Returns True when the session ended."""
        exit_code: Optional[int] = None
        with self.lock:
            if self.monitor is not mon:
                return True
            for ev in events:
                kind = ev[0]
                if kind == "message":
                    self.agg.feed(ev[1])
                elif kind == "ws_open":
                    self.agg.note_hint(ev[1]["conn"], ev[1].get("routing_hint", ""))
                elif kind == "notice":
                    self._live_note(ev[1])
                elif kind == "codex_exit":
                    exit_code = ev[1]  # keep draining: frames decoded just before the exit count too
            if exit_code is not None:
                self._live_note(self.s("live_codex_exit", rc=exit_code))
                self._end_live(f"exit:{exit_code}")
                return True
        return False

    def stop_live_confirmed(self) -> None:
        with self.lock:
            self._end_live("stopped")
        self.push()

    def stop_live(self, ask: bool = False) -> None:
        """Programmatic stop (tests / dev flags): never asks."""
        with self.lock:
            self._end_live("stopped")
        self.push()

    def _end_live(self, how: str) -> None:
        mon = self.monitor
        if mon is None:
            return
        self.monitor = None
        mon.stop()
        self.live_ended = how

    def _live_note(self, text: str) -> None:
        self.live_lines.append(f"{time.strftime('%H:%M:%S')}  {text}")
        self.live_lines = self.live_lines[-200:]

    def pick_live_dir(self) -> None:
        import webview
        win = self.window
        if win is None or self.monitor is not None:
            return
        picked = win.create_file_dialog(webview.FOLDER_DIALOG, directory=self.live_dir)
        if picked:
            path = picked[0] if isinstance(picked, (list, tuple)) else str(picked)
            with self.lock:
                self.live_dir = path
                self.settings["live_dir"] = path
                tkgui.save_settings(self.settings)
        self.push()

    def copy_live_report(self) -> Optional[dict]:
        with self.lock:  # the pump thread mutates the aggregator under the same lock
            if not self.agg.rows:
                return None
            return {"text": self.agg.report(), "msg": self.s("copied")}

    def clear_live(self) -> None:
        with self.lock:
            if self.monitor is not None:
                return
            self._clear_live()
        self.push()

    def _clear_live(self) -> None:
        self.agg = live.LiveAggregator()
        self.live_lines = []
        self.live_ended = None

    def _watch_config(self) -> None:
        while True:
            time.sleep(2)
            try:
                mtime = live.config_mtime()
                if mtime != self._cfg_mtime:
                    self._cfg_mtime = mtime
                    with self.lock:
                        self.cfg_live = live.read_config_model_effort()
                    self.push()
            except Exception:
                pass

    # ------------------------------------------------------------ closing
    def on_closing(self) -> bool:
        """pywebview closing handler: False keeps the window open (a live session is running).
        Runs synchronously on the WebView2 UI thread, so it must never call evaluate_js itself:
        the call would wait on the very message pump this handler is blocking (deadlock)."""
        with self.lock:
            mon = self.monitor
            live_running = mon is not None and mon.codex_running()
        if live_running and self.exit_after is None:
            threading.Thread(target=lambda: self._js("window.showStopConfirm('close')"), daemon=True).start()
            return False
        self.shutdown()
        return True

    def confirm_close(self) -> None:
        with self.lock:
            self._end_live("stopped")
        self._destroy()

    def shutdown(self) -> None:
        self._closed = True
        self._push_evt.set()  # release the pusher thread
        with self.lock:
            self._end_live("stopped")
        if self.worker is not None and self.cancel is not None:
            self.cancel.cancel()
            self.worker.join(timeout=10)

    def _destroy(self) -> None:
        self.shutdown()
        win = self.window
        if win is not None:
            try:
                win.destroy()
            except Exception:
                pass

    # ------------------------------------------------------------ updates
    def _check_update(self) -> None:
        info = cmc.check_for_update()
        with self.lock:
            self.update_info = info
            if not info:
                return
            new = info["version"]
            busy = self.updating or self.worker is not None or self.result is not None or self.monitor is not None
            if busy:
                pass  # badge only: never restart the app under the user
            elif not cmc.is_frozen():
                self.update_status = self.s("update_pip", new=new, repo=REPO_URL)
            elif not (self.auto_update and info.get("asset") and cmc.dir_writable(self.exe_path.parent)):
                self.update_status = self.s("update_manual", new=new)
            else:
                self._start_auto_update(info)
        self.push()

    def _start_auto_update(self, info: dict) -> None:
        self.updating = True
        asset, new = info["asset"], info["version"]
        dest = self.exe_path.with_name(self.exe_path.stem + ".new.exe")
        self.update_status = self.s("update_downloading", new=new, mb=f"{(asset.get('size') or 0) / 1e6:.1f}")

        def work() -> None:
            try:
                def prog(done, total):
                    mb = f"{done / 1e6:.1f}/{total / 1e6:.1f}" if total else f"{done / 1e6:.1f}"
                    with self.lock:
                        self.update_status = self.s("update_downloading", new=new, mb=mb)
                    self.push()

                cmc.download_file(asset["url"], dest, progress=prog)
                err = cmc.verify_download(dest, asset.get("size"), asset.get("digest"))
                if err:
                    raise RuntimeError(err)
                with self.lock:
                    self.update_status = self.s("update_restarting", new=new)
                self.push()
                cmc.launch_replacer(self.exe_path, dest, ["--updated-from", cmc.__version__, "--lang", self.lang])
                time.sleep(0.3)
                self._destroy()
            except Exception as e:
                try:
                    dest.unlink()
                except OSError:
                    pass
                with self.lock:
                    self.updating = False
                    self.update_status = self.s("update_failed", new=new, err=f"{type(e).__name__}: {e}")
                self.push()

        threading.Thread(target=work, daemon=True).start()


class JsApi:
    """The object handed to pywebview as js_api. pywebview walks every public attribute of that
    object (recursively) to build the JS bridge, so it must hold nothing but the exposed methods:
    handing it the WebApp itself would make it crawl the window, threads and subprocesses."""

    _METHODS = ("init", "set_lang", "guide_closed", "open_repo", "open_update", "open_config",
                "request_check", "run_check_confirmed", "cancel_check", "set_option", "pick_codex",
                "copy_report", "save_json", "open_logs", "request_live", "start_live_confirmed",
                "stop_live_confirmed", "confirm_close", "pick_live_dir", "copy_live_report", "clear_live")

    def __init__(self, app: WebApp) -> None:
        self._app = app
        for name in self._METHODS:
            setattr(self, name, getattr(app, name))


def feed_fake_live(app: WebApp) -> None:
    """--fake-live: same made-up responses the tkinter window uses for screenshots."""
    tkgui.feed_fake_live(app)  # duck-typed: only touches app.monitor.events


# ------------------------------------------------------------------ entry point
def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="codex-routing-detector-gui", add_help=True)
    ap.add_argument("--lang", default=None, choices=["en", "ko"], help="interface language (remembered)")
    ap.add_argument("--fake", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--auto-check", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--auto-live", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--fake-live", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--exit-after", type=float, default=None, help=argparse.SUPPRESS)
    ap.add_argument("--show-help", choices=["usage", "terms", "about"], default=None, help=argparse.SUPPRESS)
    ap.add_argument("--tk", action="store_true", help="use the old tkinter window instead of the web view")
    ap.add_argument("--no-update-check", action="store_true",
                    help=f"do not ask api.github.com for a newer release at startup (or set {cmc.NO_UPDATE_ENV}=1)")
    ap.add_argument("--no-auto-update", action="store_true",
                    help="show the NEW badge only; never download and replace this exe by itself")
    ap.add_argument("--updated-from", default=None, help=argparse.SUPPRESS)
    a = ap.parse_args(argv)

    def fall_back() -> int:
        args = list(argv) if argv is not None else sys.argv[1:]
        return tkgui.main([x for x in args if x != "--tk"])

    if a.tk:
        return fall_back()
    try:
        import webview
    except ImportError:
        return fall_back()

    if a.fake_live and not a.fake:
        tkgui._report_startup_error("--fake-live is a screenshot mode and needs --fake as well")
        return 1
    if a.fake and not tkgui.install_fake_runner():
        tkgui._report_startup_error("fixtures not found; --fake needs tests/fixtures next to this file")
        return 1

    def note(msg: str) -> None:  # a fallback notice: worth printing, not worth a dialog
        if sys.stderr is not None:
            print(msg, file=sys.stderr)

    lang = a.lang or tkgui.load_settings().get("lang") or "en"
    try:
        app = WebApp(lang=lang, fake=a.fake, exit_after=a.exit_after,
                     update_check=not a.no_update_check and not a.fake,
                     auto_update=not a.no_auto_update, updated_from=a.updated_from)
    except Exception as e:  # a windowed build has no console: show the reason instead of dying silently
        tkgui._report_startup_error(f"{APP_TITLE} could not start: {type(e).__name__}: {e}")
        return 1
    # The page goes through a temp file, not create_window(html=...): with the embedded fonts it
    # is larger than the ~2 MB WebView2 NavigateToString limit, which fails with a blank window.
    page_dir: Optional[str] = None
    try:
        import shutil
        import tempfile
        page_dir = tempfile.mkdtemp(prefix="codex-routing-ui-")
        page_path = Path(page_dir) / "codex-routing-detector.html"
        page_path.write_text(build_page(), encoding="utf-8")
        window = webview.create_window(APP_TITLE, url=page_path.as_uri(), js_api=JsApi(app),
                                       width=1240, height=1000, min_size=(1000, 800),
                                       background_color="#f4f6f2", text_select=True)
    except Exception as e:
        note(f"web view not available ({type(e).__name__}: {e}); falling back to the tkinter window")
        if page_dir:
            shutil.rmtree(page_dir, ignore_errors=True)
        return fall_back()
    app.window = window
    window.events.closing += app.on_closing

    def after_start() -> None:
        time.sleep(0.8)  # let the page load and call init()
        if a.auto_check:
            app.start_check(confirm=False)
        if a.auto_live or a.fake_live:
            app.start_live(confirm=False)
            app._js("window.crd && (crd.guideSuppressed = true, crd.guidePending = false)")
        if a.fake_live:
            time.sleep(0.6)
            feed_fake_live(app)
        if a.show_help:
            app._js("window.showHelp(%s)" % json.dumps(a.show_help))
        if a.exit_after is not None and not a.auto_check:
            time.sleep(a.exit_after)
            app._destroy()

    threading.Thread(target=after_start, daemon=True).start()
    try:
        webview.start()
    except Exception as e:
        note(f"web view could not start ({type(e).__name__}: {e}); falling back to the tkinter window")
        shutil.rmtree(page_dir, ignore_errors=True)
        return fall_back()
    app.shutdown()
    shutil.rmtree(page_dir, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
