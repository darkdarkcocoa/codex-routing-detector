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
import codex_routing_detector as cmc
import codex_routing_detector_gui as tkgui  # shared strings, briefing and settings helpers
import codex_routing_live as live
import codex_routing_proxy as crp

APP_TITLE = tkgui.APP_TITLE
REPO_URL = tkgui.REPO_URL
EFFORTS = tkgui.EFFORTS
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
        "colId": "응답 ID",
        "empty": "아직 검사하지 않았어요. 버튼 한 번만 눌러 주세요.",
        "liveEmpty": "Codex 창에서 뭐든 입력하면 여기에 한 줄씩 쌓여요.",
        "details": "상세 정보", "detailsHint": "계정 · Codex 경로 · 로그 위치",
        "detailsHintLive": "프록시 · 진행 기록",
        "detailsEmpty": "아직 적을 내용이 없어요.",
        "liveFolder": "작업 폴더",
        "foot": "짧은 프롬프트 하나만 보내고, 서버가 적어 보낸 모델명을 읽어요.",
        "idleHead": "준비됐어요", "runHead": "살펴보는 중...",
        "okHead": "정상! {models}가 답했어요", "badHead": "바꿔치기 감지",
        "cancelledHead": "취소했어요",
        "cta": "검사하기", "ctaAgain": "다시 검사", "ctaRun": "검사 중...", "cancel": "취소",
        "chipIdle": "대기", "chipRun": "검사 중", "chipOk": "정상", "chipBad": "바꿔치기",
        "chipWarn": "확인 필요",
        "statusIdle": "준비됨", "statusDone": "{secs}초 소요",
        "liveStart": "모니터링 시작", "liveStop": "중지",
        "liveChipOff": "꺼짐", "liveChipOn": "감시 중", "liveChipBad": "바꿔치기", "liveChipWarn": "확인 필요",
        "liveStatusOff": "대기 중",
        "helpUsage": "기본 사용법", "helpTerms": "용어 설명", "helpGuide": "라이브 모니터 안내",
        "helpAbout": "정보", "close": "닫기", "ok": "확인",
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
        "colId": "Response id",
        "empty": "Nothing checked yet. One press is all it takes.",
        "liveEmpty": "Type anything in the Codex window and it shows up here.",
        "details": "Details", "detailsHint": "account · codex path · logs",
        "detailsHintLive": "proxy · session notes",
        "detailsEmpty": "Nothing to note yet.",
        "liveFolder": "Folder",
        "foot": "One short prompt goes out; we read the model name the server wrote back.",
        "idleHead": "Ready when you are", "runHead": "Sniffing around...",
        "okHead": "All good — {models} answered", "badHead": "Rerouted",
        "cancelledHead": "Cancelled",
        "cta": "Check", "ctaAgain": "Check again", "ctaRun": "Checking...", "cancel": "Cancel",
        "chipIdle": "Idle", "chipRun": "Checking", "chipOk": "OK", "chipBad": "Rerouted",
        "chipWarn": "Needs a look",
        "statusIdle": "ready", "statusDone": "done in {secs}s",
        "liveStart": "Start monitoring", "liveStop": "Stop",
        "liveChipOff": "Off", "liveChipOn": "Watching", "liveChipBad": "Rerouted", "liveChipWarn": "Needs a look",
        "liveStatusOff": "idle",
        "helpUsage": "How to use", "helpTerms": "Glossary", "helpGuide": "Live monitor guide",
        "helpAbout": "About", "close": "Close", "ok": "OK",
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


# ------------------------------------------------------------------ the page
def _data_uri(name: str) -> str:
    return "data:image/png;base64," + assets.IMAGES.get(name, "")


PAGE = r"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Codex Routing Detector</title>
<style>
/* Embedded fonts (codex_routing_fonts): no request leaves the machine for a font CDN. */
@font-face { font-family: "Fredoka"; font-style: normal; font-weight: 300 700;
  src: url(__FONT_LATIN__) format("woff2"); }
@font-face { font-family: "JetBrains Mono"; font-style: normal; font-weight: 100 800;
  src: url(__FONT_MONO__) format("woff2"); }
__FONT_KO_FACES__
:root {
  --paper: #f4f6f2; --card: #ffffff; --hairline: #e4e9e2; --chipground: #f2f5f1;
  --quiet: #f4f6f2; --ctrl: #f1f4f0; --pre: #f6f8f5; --disabled: #e7ece6;
  --ink: #2f3a36; --body: #55605b; --muted: #5f6b65; --faint: #6b7671; --caret: #7a857f;
  --accent: #2a7d96; --accent-link: #1f6070;
  --sans: "Fredoka", "Segoe UI Variable", "Segoe UI", "Jua", "Malgun Gothic", system-ui, sans-serif;
  --mono: "JetBrains Mono", Consolas, monospace;
}
* { box-sizing: border-box; }
html, body { margin: 0; }
body { background: var(--paper); font-family: var(--sans); color: var(--ink);
       -webkit-font-smoothing: antialiased; overflow-y: scroll; }
a { color: var(--accent-link); text-decoration: none; } a:hover { color: #2f8aa6; }
button { font-family: inherit; border: 0; background: none; padding: 0; cursor: pointer; color: inherit; }
button:disabled { cursor: default; }

@keyframes floatUp { 0% { transform: translateY(8px) scale(.9); opacity: 0 } 25% { opacity: .85 } 100% { transform: translateY(-46px) scale(1.05); opacity: 0 } }
@keyframes bopIn { 0% { transform: scale(.82) translateY(14px); opacity: 0 } 55% { transform: scale(1.04) translateY(-4px); opacity: 1 } 78% { transform: scale(.985) translateY(1px) } 100% { transform: scale(1) translateY(0); opacity: 1 } }
@keyframes rowIn { 0% { transform: translateX(-14px); opacity: 0 } 100% { transform: translateX(0); opacity: 1 } }
@keyframes bounce { 0%, 100% { transform: translateY(0) rotate(-1deg) } 50% { transform: translateY(-9px) rotate(2deg) } }
@keyframes sniff { 0%, 100% { transform: translateY(0) rotate(-3deg) } 30% { transform: translateY(-4px) rotate(3deg) } 60% { transform: translateY(-1px) rotate(-2deg) } }
@keyframes idleBreath { 0%, 100% { transform: scale(1) } 50% { transform: scale(1.025) } }
@keyframes walk { 0% { left: 0% } 100% { left: calc(100% - 30px) } }
@keyframes pulseRing { 0% { transform: scale(.7); opacity: .55 } 100% { transform: scale(1.45); opacity: 0 } }
@keyframes slideTab { 0% { transform: translateX(22px); opacity: 0 } 100% { transform: translateX(0); opacity: 1 } }
@keyframes confetti { 0% { transform: translate(0, 0) rotate(0deg); opacity: 0 } 12% { opacity: 1 } 100% { transform: translate(var(--dx), 190px) rotate(var(--rot)); opacity: 0 } }

#shell { position: relative; width: 1180px; margin: 0 auto; min-height: 100vh; }
#sparkles { position: absolute; inset: 0; pointer-events: none; overflow: hidden; }
#sparkles div { position: absolute; }

/* header */
.header { position: relative; display: flex; align-items: center; gap: 12px; padding: 20px 32px 0; }
.header img.logo { width: 40px; height: 40px; object-fit: contain; }
.header .names { display: flex; flex-direction: column; gap: 1px; margin-right: auto; }
.header .appname { font-size: 17px; font-weight: 700; letter-spacing: -0.2px; color: var(--ink); }
.header .subtitle { font-size: 12.5px; color: var(--muted); }
.langtoggle { display: flex; align-items: center; gap: 4px; background: var(--card); border-radius: 999px;
  padding: 5px; box-shadow: 0 1px 3px rgba(47,58,51,.08); font-size: 12px; font-weight: 600; }
.langtoggle span { padding: 4px 11px; border-radius: 999px; color: var(--muted); cursor: pointer; }
.langtoggle span.on { background: var(--accent); color: #ffffff; }
.helpbtn { display: grid; place-items: center; width: 34px; height: 34px; border-radius: 999px;
  background: var(--card); box-shadow: 0 1px 3px rgba(47,58,51,.08); color: var(--muted);
  font-size: 15px; font-weight: 700; }
.helpbtn:hover { color: var(--accent); }

/* tabs */
.tabbar { position: relative; display: flex; gap: 26px; padding: 18px 32px 0; align-items: stretch; }
.tab { position: relative; padding: 10px 2px 14px; font-size: 14px; font-weight: 700; color: var(--muted); cursor: pointer; }
.tab.on { color: var(--ink); }
.tab .bar { position: absolute; left: 0; right: 0; bottom: 0; height: 3px; border-radius: 999px; background: transparent; }
.tab.on .bar { background: var(--accent); }
.tabbar .rule { flex: 1; align-self: center; height: 1px; background: var(--hairline); }

/* page */
.page { position: relative; display: flex; flex-direction: column; gap: 14px; padding: 20px 32px 10px; }
.page.slide { animation: slideTab .32s ease-out both; }
.hidden { display: none !important; }

/* hero */
.hero { position: relative; display: flex; align-items: center; gap: 22px; background: var(--card);
  border-radius: 24px; padding: 26px 28px; box-shadow: 0 2px 14px rgba(47,58,51,.07); }
.hero.bop { animation: bopIn .5s cubic-bezier(.2,.9,.3,1.3) both; }
.hero .left { position: relative; width: 150px; flex: none; display: grid; place-items: center; }
.hero .ring { position: absolute; width: 142px; height: 142px; border-radius: 999px;
  border: 2px solid #cfe6d8; opacity: .45; }
.hero .cat { width: 124px; height: 124px; object-fit: contain; animation: idleBreath 3.4s ease-in-out infinite; }
.hero .right { flex: 1; display: flex; flex-direction: column; gap: 10px; min-width: 0; }
.hero .statusrow { display: flex; align-items: center; gap: 10px; }
.chip { font-size: 11.5px; font-weight: 700; letter-spacing: .3px; padding: 4px 11px; border-radius: 999px;
  background: #eef1ec; color: #4f5a55; }
.statusline { font-size: 12.5px; color: var(--muted); font-family: var(--mono); }
.headline { font-size: 28px; font-weight: 700; letter-spacing: -.4px; color: var(--ink); }
.brief { font-size: 14.5px; line-height: 1.6; color: var(--body); max-width: 760px; text-wrap: pretty; }
.actionrow { display: flex; align-items: center; gap: 10px; padding-top: 4px; }
.cta { background: var(--accent); color: #ffffff; border-radius: 999px; padding: 11px 26px;
  font-size: 14.5px; font-weight: 700; box-shadow: 0 4px 12px rgba(47,58,51,.14);
  transition: transform .12s ease, filter .12s ease; }
.cta:hover:not(:disabled) { filter: brightness(1.05); }
.cta:active:not(:disabled) { transform: translateY(2px) scale(.98); }
.cta:disabled, .cta.off { background: var(--disabled); color: var(--muted); box-shadow: none; }
.cta.stop { background: #fadcdd; color: #a8323b; }
.quietbtn { font-size: 12px; font-weight: 600; color: var(--muted); padding: 5px 11px;
  border-radius: 999px; background: var(--quiet); }
.quietbtn:hover:not(:disabled) { color: var(--accent); }
.quietbtn:disabled { color: #b3bcb6; }
.walker { position: relative; width: 250px; height: 30px; }
.walker .track { position: absolute; left: 0; right: 0; bottom: 5px; height: 8px; border-radius: 999px;
  background: var(--disabled); overflow: hidden; }
.walker .fill { height: 100%; width: 45%; border-radius: 999px;
  background: linear-gradient(90deg, #9fd8e8, var(--accent)); position: relative;
  animation: walk 2.4s ease-in-out infinite alternate; }
.walker img { position: absolute; bottom: 8px; width: 30px; height: 30px;
  animation: walk 2.4s ease-in-out infinite alternate, bounce .5s ease-in-out infinite; }
.folderline { font-size: 12.5px; color: var(--muted); }
.folderline .path { font-family: var(--mono); color: var(--faint); cursor: pointer; }
.folderline .path:hover { color: var(--accent); }
#confetti { position: absolute; left: 60px; top: 40px; width: 1px; height: 1px; pointer-events: none; }
#confetti div { position: absolute; border-radius: 2px; }

/* hero tones */
.hero[data-tone="running"] { background: #eef6fa; }
.hero[data-tone="running"] .headline { color: #1f5b70; }
.hero[data-tone="running"] .ring { border-color: #9fd8e8; opacity: 1; animation: pulseRing 1.6s ease-out infinite; }
.hero[data-tone="running"] .cat { animation: sniff .9s ease-in-out infinite; }
.hero[data-tone="bad"] { background: #fdf0f0; }
.hero[data-tone="bad"] .headline { color: #a8323b; }
.hero[data-tone="bad"] .ring { border-color: #f3bfc1; }
.hero[data-tone="bad"] .cat { animation: bounce 2.6s ease-in-out infinite; }
.hero[data-tone="ok"] { background: #eff9f3; }
.hero[data-tone="ok"] .headline { color: #1f6f52; }
.hero[data-tone="warn"] { background: #fdf6ec; }
.hero[data-tone="warn"] .headline { color: #8a5a12; }
.chip[data-tone="running"] { background: #d9edf5; color: #1f5b70; }
.chip[data-tone="bad"] { background: #fadcdd; color: #a8323b; }
.chip[data-tone="ok"] { background: #d8f0e4; color: #1f6f52; }
.chip[data-tone="warn"] { background: #f7e6c8; color: #8a5a12; }

/* setup strip */
.strip { display: flex; align-items: center; gap: 8px; padding: 2px 4px; flex-wrap: wrap; }
.strip .lead { font-size: 12px; font-weight: 600; color: var(--muted); margin-right: 4px; }
.pill { position: relative; display: flex; align-items: center; gap: 7px; background: var(--card);
  border-radius: 999px; padding: 7px 8px 7px 14px; box-shadow: 0 1px 3px rgba(47,58,51,.07);
  font-size: 13px; font-weight: 600; }
.pill:hover { box-shadow: 0 2px 8px rgba(47,58,51,.12); }
.pill .k { color: var(--muted); font-weight: 500; }
.pill .v { color: var(--ink); }
.pill .caret { color: var(--caret); font-size: 9px; }
.pill select { position: absolute; inset: 0; opacity: 0; width: 100%; cursor: pointer; }
.pill.static { padding-right: 14px; }
.stepper { padding: 7px 10px 7px 14px; gap: 10px; }
.stepper button { display: grid; place-items: center; width: 18px; height: 18px; border-radius: 999px;
  background: var(--ctrl); color: var(--body); font-size: 12px; line-height: 1; }
.stepper button:hover:not(:disabled) { background: #e4ece8; color: var(--accent); }
.stepper .v { min-width: 8px; text-align: center; }
.switchpill { color: var(--muted); cursor: pointer; padding: 7px 14px; }
.switchpill:hover { color: var(--accent); }
.switchpill.disabled { color: #b3bcb6; cursor: default; }
.switch { display: inline-block; width: 26px; height: 15px; border-radius: 999px; background: #eceff0;
  position: relative; transition: background .15s ease; flex: none; }
.switch .knob { position: absolute; top: 2px; left: 2px; width: 11px; height: 11px; border-radius: 999px;
  background: #ffffff; box-shadow: 0 1px 2px rgba(0,0,0,.15); transition: left .15s ease; }
.switch.on { background: var(--accent); }
.switch.on .knob { left: 13px; }
.strip .tail { margin-left: auto; font-size: 12px; color: var(--muted); font-family: var(--mono); cursor: pointer; }
.strip .tail:hover { color: var(--accent); }
.strip .tail.plain { cursor: default; }
.strip .tail.plain:hover { color: var(--muted); }

/* results card */
.card { background: var(--card); border-radius: 20px; padding: 6px 8px 10px; box-shadow: 0 2px 10px rgba(47,58,51,.06); }
.card .head { display: flex; align-items: center; gap: 10px; padding: 14px 16px 10px; }
.card .title { font-size: 14px; font-weight: 700; color: var(--ink); }
.card .count { font-size: 12px; font-weight: 600; color: var(--muted); background: var(--chipground);
  border-radius: 999px; padding: 3px 9px; }
.card .btns { margin-left: auto; display: flex; gap: 6px; }
.cols, .row { display: grid; grid-template-columns: 30px 88px 1fr 104px 88px 188px; align-items: center; gap: 12px; }
.cols { padding: 0 18px 8px; font-size: 11.5px; font-weight: 600; color: var(--muted); letter-spacing: .2px; }
.row { padding: 13px 18px; border-radius: 14px; margin-bottom: 6px; background: #f2faf6;
  transition: transform .18s ease; }
.row:hover { transform: translateY(-1px); }
.row.anim { animation: rowIn .34s cubic-bezier(.2,.9,.3,1.2) both; }
.row[data-tone="bad"] { background: #fdf1f1; }
.row[data-tone="warn"] { background: #fbf5e9; }
.row[data-tone="idle"] { background: #f4f6f2; }
.row .dot { display: grid; place-items: center; width: 24px; height: 24px; border-radius: 999px;
  font-size: 11.5px; font-weight: 700; color: #ffffff; background: #27805f; }
.row[data-tone="bad"] .dot { background: #b23a44; }
.row[data-tone="warn"] .dot { background: #b3843a; }
.row[data-tone="idle"] .dot { background: #8a948e; }
.row .kind { justify-self: start; font-size: 11.5px; font-weight: 600; padding: 3px 10px;
  border-radius: 999px; background: #ffffff; color: var(--body); }
.row .route { display: flex; align-items: center; gap: 9px; font-size: 14px; font-weight: 600; min-width: 0; }
.row .route .req { color: var(--body); }
.row .route .arr { font-size: 13px; color: #6f7d77; }
.row .route .srv { font-weight: 700; color: #257a59; }
.row[data-tone="bad"] .route .arr, .row[data-tone="bad"] .route .srv { color: #b23a44; }
.row[data-tone="warn"] .route .srv { color: #8a5a12; }
.row .st { font-size: 12.5px; color: var(--muted); font-weight: 500; }
.row .tm { font-size: 12.5px; color: var(--muted); font-family: var(--mono); }
.row .rid { font-size: 11.5px; color: var(--body); font-family: var(--mono);
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.emptystate { display: flex; flex-direction: column; align-items: center; gap: 8px;
  padding: 34px 0 30px; color: var(--muted); font-size: 13px; }
.emptystate img { width: 46px; height: 46px; opacity: .85; animation: idleBreath 3s ease-in-out infinite; }

/* details disclosure */
.details { background: var(--card); border-radius: 18px; box-shadow: 0 2px 10px rgba(47,58,51,.06); overflow: hidden; }
.details .dhead { display: flex; align-items: center; gap: 9px; padding: 14px 18px; cursor: pointer;
  font-size: 13px; font-weight: 700; color: var(--faint); }
.details .dhead:hover { color: var(--accent); }
.details .dhead .caret { display: inline-block; transition: transform .2s ease; color: var(--caret); }
.details.open .dhead .caret { transform: rotate(90deg); }
.details .dhead .hint { font-weight: 500; color: var(--muted); }
.details .dbody { display: none; padding: 0 18px 18px; }
.details.open .dbody { display: block; }
.details pre { margin: 0; padding: 14px 16px; background: var(--pre); border-radius: 12px;
  font-family: var(--mono); font-size: 12px; line-height: 1.7; color: var(--body); white-space: pre-wrap;
  word-break: break-all; }

/* footer */
.footer { position: relative; display: flex; align-items: center; gap: 12px; padding: 4px 34px 22px;
  font-size: 11.5px; color: var(--muted); }
.footer .ver { font-family: var(--mono); }
.footer .ver.new { color: #b3261e; font-weight: 700; cursor: pointer; }
.footer .tagline { margin-left: auto; }

/* modal */
#overlay { position: fixed; inset: 0; background: rgba(47,58,51,.35); display: grid; place-items: center; z-index: 40; }
.modal { width: 560px; max-width: calc(100vw - 60px); max-height: calc(100vh - 60px); overflow: auto;
  background: var(--card); border-radius: 20px; box-shadow: 0 24px 60px rgba(47,58,51,.3);
  padding: 24px 26px; animation: bopIn .4s cubic-bezier(.2,.9,.3,1.2) both; }
.modal.wide { width: 780px; }
.modal h3 { margin: 0 0 10px; font-size: 17px; color: var(--ink); display: flex; align-items: center; gap: 10px; }
.modal h3 img { width: 40px; height: 40px; object-fit: contain; }
.modal .mbody { font-size: 13.5px; line-height: 1.65; color: var(--body); white-space: pre-wrap; }
.modal .mbody.mono { font-family: var(--mono); font-size: 12px; line-height: 1.7; background: var(--pre);
  border-radius: 12px; padding: 14px 16px; max-height: 52vh; overflow: auto; }
.modal .mcheck { display: flex; align-items: center; gap: 8px; margin-top: 14px; font-size: 12.5px; color: var(--muted); }
.modal .mrow { display: flex; justify-content: flex-end; gap: 8px; margin-top: 18px; }
.modal .helppills { display: flex; gap: 6px; margin: 4px 0 12px; flex-wrap: wrap; }
.modal .helppills .quietbtn.on { background: var(--accent); color: #ffffff; }
.mbtn { border-radius: 999px; padding: 9px 22px; font-size: 13px; font-weight: 700;
  transition: transform .12s ease, filter .12s ease; }
.mbtn:hover { filter: brightness(1.05); }
.mbtn:active { transform: translateY(2px) scale(.98); }
.mbtn.primary { background: var(--accent); color: #ffffff; box-shadow: 0 4px 12px rgba(47,58,51,.14); }
.mbtn.plain { background: var(--quiet); color: var(--muted); }
</style>
</head>
<body>
<div id="shell">
  <div id="sparkles"></div>

  <div class="header">
    <img class="logo" src="__MASCOT__" alt="">
    <div class="names">
      <div class="appname">Codex Routing Detector</div>
      <div class="subtitle" id="subtitle"></div>
    </div>
    <div class="langtoggle" id="langtoggle">
      <span data-lang="ko">한국어</span><span data-lang="en">EN</span>
    </div>
    <button class="helpbtn" id="helpbtn">?</button>
  </div>

  <div class="tabbar">
    <div class="tab on" id="tab-check"><span></span><div class="bar"></div></div>
    <div class="tab" id="tab-live"><span></span><div class="bar"></div></div>
    <div class="rule"></div>
  </div>

  <div class="page" id="page-check">
    <div class="hero" id="c-hero" data-tone="idle">
      <div class="left"><div class="ring"></div><img class="cat" src="__MASCOT__" alt=""></div>
      <div class="right">
        <div class="statusrow"><span class="chip" id="c-chip"></span><span class="statusline" id="c-status"></span></div>
        <div class="headline" id="c-head"></div>
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

    <div class="card">
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

    <div class="details" id="c-details">
      <div class="dhead" id="c-dhead"><span class="caret">&#9656;</span><span id="c-dlabel"></span><span class="hint" id="c-dhint"></span></div>
      <div class="dbody"><pre id="c-dpre"></pre></div>
    </div>
  </div>

  <div class="page hidden" id="page-live">
    <div class="hero" id="l-hero" data-tone="idle">
      <div class="left"><div class="ring"></div><img class="cat" src="__MASCOT__" alt=""></div>
      <div class="right">
        <div class="statusrow"><span class="chip" id="l-chip"></span><span class="statusline" id="l-status"></span></div>
        <div class="headline" id="l-head"></div>
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

    <div class="card">
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

    <div class="details" id="l-details">
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

const crd = {
  T: null, HELPS: null, vm: null, pendingVm: null, tab: "check",
  prevRows: { check: -1, live: -1 }, prevTone: { check: null, live: null }, prevLang: null,
  prevPhase: null,
  toastTimer: { check: null, live: null }, toast: { check: null, live: null },
  guidePending: false,
};
window.crd = crd;

function api() { return window.pywebview.api; }

/* ---------------------------------------------------------------- sparkles */
function buildSparkles() {
  const glyphs = ["✦", "✧", "·", "✦", "✧", "•", "✦", "✧"];
  const colors = ["#bfe0ea", "#d9cfee", "#cfe6d8"];
  const holder = $("sparkles");
  holder.innerHTML = "";
  glyphs.forEach((g, i) => {
    const d = document.createElement("div");
    d.textContent = g;
    d.style.left = (6 + i * 11.5) + "%";
    d.style.bottom = (4 + ((i * 17) % 60)) + "%";
    d.style.fontSize = (9 + (i % 3) * 5) + "px";
    d.style.color = colors[i % 3];
    d.style.animation = "floatUp " + (7 + (i % 4) * 2.5) + "s ease-in-out " + (i * 0.9) + "s infinite";
    holder.appendChild(d);
  });
}

/* ---------------------------------------------------------------- rendering */
function t() { return crd.T[crd.vm.lang]; }

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

function bopHero(el) { el.classList.remove("bop"); void el.offsetWidth; el.classList.add("bop"); }

function popConfetti() {
  const holder = $("confetti");
  holder.innerHTML = "";
  const colors = ["#8fd3bb", "#f3c3cf", "#bfe0ea", "#f0dda2", "#cfc3ee"];
  for (let i = 0; i < 14; i++) {
    const d = document.createElement("div");
    d.style.width = (5 + (i % 3) * 2) + "px";
    d.style.height = (7 + (i % 2) * 4) + "px";
    d.style.background = colors[i % 5];
    d.style.setProperty("--dx", (((i * 37) % 120) - 60) + "px");
    d.style.setProperty("--rot", (180 + i * 40) + "deg");
    d.style.animation = "confetti " + (1.5 + (i % 4) * 0.35) + "s ease-in " + (i * 0.06) + "s both";
    holder.appendChild(d);
  }
  setTimeout(() => { if ($("confetti")) $("confetti").innerHTML = ""; }, 3200);
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
    bopHero(hero);
    if (c.tone === "ok" && crd.prevTone.check !== null) popConfetti();
    crd.prevTone.check = c.tone;
  }
  setChip($("c-chip"), c.tone, c.chip);
  $("c-status").textContent = crd.toast.check || c.status;
  $("c-head").textContent = c.head;
  $("c-brief").textContent = c.brief;
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
  sel.value = c.model; $("sel-effort").value = c.effort;
  $("v-repeat").textContent = c.repeat;
  const wp = $("wirepill");
  $("k-wire").textContent = c.wireEnabled ? s.wire : s.wireOff;
  wp.classList.toggle("disabled", !c.wireEnabled);
  $("wireswitch").classList.toggle("on", c.wire);
  $("codexpill").textContent = "codex · " + c.codexLabel;
  $("codexpill").title = c.codexTitle || "";

  /* check results */
  $("c-count").textContent = c.rows.length;
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
    bopHero(lhero);
    crd.prevTone.live = l.tone;
  }
  setChip($("l-chip"), l.tone, l.chip);
  $("l-status").textContent = crd.toast.live || l.status;
  $("l-head").textContent = l.head;
  $("l-brief").textContent = l.brief;
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
function closeOverlay() { $("overlay").classList.add("hidden"); $("overlay").innerHTML = ""; }

function showConfirm(opts) {
  const ov = $("overlay");
  ov.innerHTML =
    '<div class="modal"><h3><img src="' + window.MASCOT_SRC + '" alt="">' + esc(opts.title) + "</h3>" +
    '<div class="mbody">' + esc(opts.body) + "</div>" +
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
  const s = t();
  const ov = $("overlay");
  ov.innerHTML =
    '<div class="modal"><h3><img src="' + window.MASCOT_SRC + '" alt="">' + esc(title) + "</h3>" +
    '<input id="m-input" type="text" spellcheck="false" style="width:100%;box-sizing:border-box;margin-top:6px;' +
    'padding:10px 14px;border:1px solid var(--hairline);border-radius:12px;font:600 13px var(--mono);color:var(--ink);outline-color:var(--accent)">' +
    '<div class="mrow"><button class="mbtn plain" id="m-cancel">' + esc(s.cancel) + "</button>" +
    '<button class="mbtn primary" id="m-ok">' + esc(s.ok) + "</button></div></div>";
  ov.classList.remove("hidden");
  const input = $("m-input");
  input.value = initial || "";
  const done = () => { const v = input.value.trim(); closeOverlay(); if (v) onOk(v); };
  $("m-cancel").onclick = closeOverlay;
  $("m-ok").onclick = done;
  input.onkeydown = (e) => { if (e.key === "Enter") done(); if (e.key === "Escape") closeOverlay(); };
  input.focus(); input.select();
}

function showGuide() {
  if (!crd.T) return;  // not initialised yet
  const g = crd.HELPS[crd.vm.lang];
  const ov = $("overlay");
  ov.innerHTML =
    '<div class="modal"><h3><img src="' + window.MASCOT_SRC + '" alt="">' + esc(g.guide_heading) + "</h3>" +
    '<div class="mbody">' + esc(g.guide_body) + "</div>" +
    '<label class="mcheck"><input type="checkbox" id="m-skip"> ' + esc(g.guide_skip) + "</label>" +
    '<div class="mrow"><button class="mbtn primary" id="m-ok">' + esc(g.guide_ok) + "</button></div></div>";
  ov.classList.remove("hidden");
  $("m-ok").onclick = () => { const skip = $("m-skip").checked; closeOverlay(); call(api().guide_closed(skip)); };
  $("m-ok").focus();
}
window.showGuide = showGuide;

function showHelp(which) {
  if (!crd.T) return;  // not initialised yet (e.g. --show-help firing early)
  const s = t();
  const h = crd.HELPS[crd.vm.lang];
  const kinds = [["usage", s.helpUsage], ["terms", s.helpTerms], ["guide", s.helpGuide], ["about", s.helpAbout]];
  const ov = $("overlay");
  const pills = kinds.map(([k, label]) =>
    '<button class="quietbtn' + (k === which ? " on" : "") + '" data-help="' + k + '">' + esc(label) + "</button>").join("");
  const content = which === "guide" ? (h.guide_heading + "\n\n" + h.guide_body) : h[which];
  ov.innerHTML =
    '<div class="modal wide"><h3><img src="' + window.MASCOT_SRC + '" alt="">' + esc(APP()) + "</h3>" +
    '<div class="helppills">' + pills + "</div>" +
    '<div class="mbody mono">' + esc(content) + "</div>" +
    '<div class="mrow"><button class="mbtn plain" id="m-close">' + esc(s.close) + "</button></div></div>";
  ov.classList.remove("hidden");
  ov.querySelectorAll("[data-help]").forEach((b) => b.onclick = () => showHelp(b.dataset.help));
  $("m-close").onclick = closeOverlay;
}
window.showHelp = showHelp;
function APP() { return "Codex Routing Detector"; }

function showStopConfirm(mode) {  /* mode: "stop" | "close" */
  if (!crd.T) return;  // not initialised yet (e.g. closing right after --auto-live)
  const g = crd.HELPS[crd.vm.lang];
  const s = t();
  showConfirm({
    title: s.liveStop,
    body: mode === "close" ? g.live_close_confirm : g.live_stop_confirm,
    ok: s.liveStop, cancel: s.cancel, checkbox: null,
    onOk: () => { call(mode === "close" ? api().confirm_close() : api().stop_live_confirmed()); },
  });
}
window.showStopConfirm = showStopConfirm;

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
    window.MASCOT_SRC = $("c-hero").querySelector(".cat").src;
    crd.guidePending = data.showGuide && !crd.guideSuppressed;
    fillSelects(data.models, data.efforts);
    buildSparkles();
    wire();
    const first = crd.pendingVm || data.vm;  // a push may have landed before init() resolved
    crd.pendingVm = null;
    render(first);
  });
});
</script>
</body>
</html>
"""


def _korean_faces() -> str:
    """One @font-face per Google Fonts slice: the unicode-range keeps the browser from decoding
    slices the page never uses."""
    rule = ('@font-face {{ font-family: "Jua"; font-style: normal; font-weight: 400;\n'
            '  src: url(data:font/woff2;base64,{b64}) format("woff2"); unicode-range: {ur}; }}')
    return "\n".join(rule.format(b64=b64, ur=ur) for ur, b64 in fonts.JUA)


def build_page() -> str:
    return (PAGE
            .replace("__MASCOT__", _data_uri("mascot_256"))
            .replace("__MOOD_IDLE__", _data_uri("mood_idle_56"))
            .replace("__FONT_LATIN__", "data:font/woff2;base64," + fonts.FONTS["fredoka"])
            .replace("__FONT_MONO__", "data:font/woff2;base64," + fonts.FONTS["jetbrains_mono"])
            .replace("__FONT_KO_FACES__", _korean_faces()))


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
        return tkgui.STRINGS[self.lang][key].format(**kw)

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
            return self.s("starting", version="...")
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
        main = [p for p in res.probes if not p.is_control]
        models = ", ".join(sorted({p.requested for p in main})) or "?"
        v = self._check_verdict()
        if v == "REROUTED":
            return "bad", self.u("chipBad"), self.u("badHead")
        if v == "OK":
            return "ok", self.u("chipOk"), self.u("okHead", models=models)
        if v == "CANCELLED":
            return "idle", self.u("chipIdle"), self.u("cancelledHead")
        if v == "UNSUPPORTED":
            plan = next((p.rate_limits.get("plan_type") for p in res.probes if p.rate_limits), None) or "?"
            return "warn", self.u("chipWarn"), self.s("banner_unsupported", models=models, plan=plan)
        if res.error:
            return "warn", self.u("chipWarn"), self.s("banner_fatal")
        return "warn", self.u("chipWarn"), self.s("banner_error", models=models)

    def _check_brief(self) -> str:
        if self.phase == "running":
            return self.s("brief_running")
        if self.result is None:
            return self.s("brief_idle")
        return tkgui.build_brief(self.result, self.lang)

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
            return ("idle", self.u("liveChipOff"), self.s("banner_live_idle"), self.s("brief_live_idle"))
        overall = self.agg.overall()
        counts = self.agg.counts()
        total = len(self.agg.rows)
        requested = ", ".join(sorted({r.requested for r in self.agg.rows if r.requested})) or "?"
        brief: List[str] = []
        if overall == "REROUTED":
            bad = counts.get("REROUTED", 0)
            served = sorted({m for r in self.agg.rows for m in r.other_models()})
            tone, chip = "bad", self.u("liveChipBad")
            head = self.u("badHead")
            brief.append(self.s("brief_live_rerouted", bad=bad, total=total,
                                served=", ".join(served) or "?", requested=requested))
            acct = self._live_account_sentence()
            if acct:
                brief.append(acct)
            brief.append(self.s("brief_advice_rerouted"))
        elif overall == "OK":
            tone = "running" if running else "idle"
            chip = self.u("liveChipOn") if running else self.u("liveChipOff")
            head = self.s("banner_live_ok", n=counts.get("ok", 0))
            brief.append(self.s("brief_live_ok", n=counts.get("ok", 0)))
            acct = self._live_account_sentence()
            if acct:
                brief.append(acct)
        elif overall == "UNSUPPORTED":
            tone, chip = "warn", self.u("liveChipWarn")
            head = self.s("banner_live_unsupported", models=requested)
            brief.append(self.s("brief_live_unsupported", models=requested))
            brief.append(self.s("brief_advice_unsupported"))
        elif overall == "ERROR":
            errs = sorted({(r.error_code or (r.record.error_code if r.record else None) or "?")
                           for r in self.agg.rows if r.verdict() in ("ERROR", "UNKNOWN")})
            tone, chip = "warn", self.u("liveChipWarn")
            head = self.s("banner_live_error", n=total)
            brief.append(self.s("brief_live_error", errors=", ".join(errs)))
        elif running:
            tone, chip = "running", self.u("liveChipOn")
            head = self.s("banner_live_waiting")
            brief.append(self.s("brief_live_running"))
            brief.append(self.s("brief_live_waiting"))
        else:
            tone, chip = "idle", self.u("liveChipOff")
            head = self.s("banner_live_idle")
            brief.append(self.s("brief_live_idle"))
        if running and overall in ("REROUTED", "OK", "UNSUPPORTED", "ERROR"):
            brief.insert(0, self.s("brief_live_running"))
        return tone, chip, head, " ".join(brief)

    def _live_account_sentence(self) -> Optional[str]:
        rl = self.agg.rate_limits
        if not rl or not rl.get("plan_type"):
            return None
        lim = rl.get("rate_limits") or {}
        used = (lim.get("primary") or {}).get("used_percent")
        text = self.s("brief_account", plan=rl.get("plan_type"), used=used if used is not None else "?")
        if self.agg.overall() == "REROUTED":
            text += " " + (self.s("brief_not_limit") if lim.get("limit_reached") is False else self.s("brief_limit"))
        return text

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
            "cfgModel": model or self.s("live_cfg_none"), "cfgEffort": effort or "default",
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
                st = tkgui.STRINGS[lang]
                helps[lang] = {
                    "usage": tkgui.HELP_USAGE[lang],
                    "terms": tkgui.HELP_TERMS[lang],
                    "about": tkgui.HELP_ABOUT[lang].format(version=cmc.__version__, repo=REPO_URL),
                    "guide_heading": st["guide_heading"], "guide_body": st["guide_body"],
                    "guide_skip": st["guide_skip"], "guide_ok": st["guide_ok"],
                    "live_stop_confirm": st["live_stop_confirm"], "live_close_confirm": st["live_close_confirm"],
                }
            return {
                "t": UI, "helps": helps, "models": self.models, "efforts": EFFORTS,
                "moodError": _data_uri("mood_error_56"),
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
            elif key == "effort" and value in EFFORTS:
                self.opt["effort"] = value
            elif key == "repeat":
                try:
                    self.opt["repeat"] = min(MAX_REPEAT, max(1, int(value)))
                except ValueError:
                    pass
            elif key == "wire":
                self.opt["wire"] = bool(value) and self.have_mitm
        self.push()

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
            model = self.options().models[0]
            return {"title": self.s("confirm_title"), "body": self.s("confirm_body", model=model),
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
            ask = self.confirm_live and self.confirm_before_check and not self.settings.get("skip_confirm_live")
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
