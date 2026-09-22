#!/usr/bin/env python3
"""codex-routing-detector GUI: one window, one Check button.

Wraps codex_routing_detector.run_check() in a tkinter window: pick a model, press Check, and see
which model actually answered. Everything else (how the check works, what the verdicts mean,
privacy notes) is in README.md.

Flags: --lang ko|en starts in that language. Development-only flags:
  --fake          feed the bundled fixture runs instead of launching codex (no quota, no network)
  --auto-check    press Check as soon as the window is up
  --exit-after S  close the window S seconds after a check finished (or failed to start)
"""
from __future__ import annotations

import argparse
import json
import os
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import codex_routing_assets as assets
import codex_routing_detector as cmc
import codex_routing_live as live
import codex_routing_proxy as crp

APP_TITLE = "Codex Routing Detector"
REPO_URL = "https://github.com/darkdarkcocoa/codex-routing-detector"
# 16x16 GitHub-style mark (dark disc, white silhouette), embedded so the exe needs no image file.
GITHUB_ICON_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAYAAAAf8/9hAAAAXElEQVR42mNgwAJUNPX/Y8MMhAAujUQZRKxmrIbABGGAWD5BA9AxVgOwKSAEULyC"
    "yxZiNA9SA/AZgjU6CYU4oZjBmYjQ4x9vYiI23olKjcQaQFR+wBny5OZKbGoBaIzPPu93aOcAAAAASUVORK5CYII="
)
FALLBACK_MODELS = ["gpt-6-astra", "gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna", "gpt-5.5"]
EFFORTS = ["low", "medium", "high", "xhigh"]
MAX_REPEAT = 10

STRINGS: Dict[str, Dict[str, str]] = {
    "en": {
        "model": "Model", "effort": "Effort", "repeat": "Repeat",
        "wire": "Wire mode (mitmproxy)", "no_mitm": "Wire mode (mitmproxy missing)",
        "codex_btn": "Codex...", "codex_auto": "auto-detect", "codex_pick_title": "Pick the codex binary",
        "check": "Check", "cancel": "Cancel", "copy": "Copy report", "save_json": "Save JSON...", "open_logs": "Open log folder",
        "lang": "한국어", "idle": "Ready. Press Check to run one short Codex turn per model.",
        "starting": "Starting codex ({version})...", "running": "Running probe {i}/{n}: {model} ({effort})...",
        "done": "Done in {secs}s. Raw logs: {dir}", "cancelling": "Cancelling...", "cancelled": "Cancelled.",
        "failed": "The check could not start.",
        "col_n": "#", "col_requested": "Requested", "col_kind": "Kind", "col_served": "Served by",
        "col_status": "Status", "col_created": "Created (UTC)", "col_verdict": "Verdict", "col_id": "Response id",
        "kind_warmup": "warm-up", "kind_turn": "turn",
        "banner_idle": "No result yet", "banner_running": "Checking...",
        "banner_rerouted": "REROUTED: {pairs}", "banner_ok": "OK: {models} served as requested",
        "banner_error": "Could not check {models}", "banner_cancelled": "Cancelled", "banner_fatal": "Error",
        "banner_unsupported": "{models} is not available on this account (plan: {plan})",
        "notes": "Details", "account": "Account", "codex": "Codex",
        "codex_hint": "Use the \"Codex...\" button to pick the codex binary by hand (codex.exe inside the npm package, or the Codex Desktop bundle).",
        "copied": "Report copied to the clipboard.", "saved": "Saved {path}", "fake": "(fixture data, not a live check)",
        "update_new": "NEW v{new}",
        "update_pip": "Version {new} is available: pipx upgrade codex-routing-detector  (or pip install -U git+{repo})",
        "update_manual": "Version {new} is available. Click NEW at the bottom right to download it.",
        "update_downloading": "Updating to v{new}: downloading {mb} MB...",
        "update_restarting": "Update downloaded. Restarting as v{new}...",
        "update_failed": "Automatic update to v{new} failed ({err}). Click NEW at the bottom right to download it.",
        "updated": "Updated to v{current}.",
        "subtitle": "Which model really answered your Codex request?",
        "brief": "Briefing",
        "brief_idle": "Press Check. One short prompt goes to Codex; the server's reply tells us which model actually answered.",
        "brief_running": "Sending a short prompt to Codex and waiting for the server's response objects...",
        "brief_rerouted": "You asked for {models}, but the server answered with {served} ({bad} of {total} responses).",
        "brief_ok": "{models} answered your request itself; no substitution right now.",
        "brief_unsupported": "Your account (plan: {plan}) cannot use {models}: the server refused it. This is plan gating, not a substitution.",
        "brief_error": "The check of {models} did not complete: the server returned {errors}.",
        "brief_nodata": "No response from the server for {models}; see the details below for what Codex reported.",
        "brief_cancelled": "Cancelled after {n} probe(s).",
        "brief_fatal": "The check could not start: {error}",
        "brief_account": "Plan {plan}, {used}% of the usage window used.",
        "brief_not_limit": "So this is not a usage-limit fallback.",
        "brief_limit": "The usage limit is reached, which can trigger a fallback model.",
        "brief_advice_rerouted": "Use another model for now, or check again in a while; the routing state changes over time. Copy the report if you want to file it.",
        "brief_advice_ok": "Good time to work with this model. Check again later if answers start to feel off.",
        "brief_advice_unsupported": "Pick a model your plan includes and press Check again.",
        "brief_advice_error": "Press Check again in a moment; capacity errors usually pass.",
        "confirm_title": "Run the check?",
        "confirm_body": "Codex Routing Detector will send one short prompt to Codex as {model} (\"Reply with exactly the single word: pong\") and read the server's response objects to see which model really answered.",
        "confirm_skip": "Don't ask again",
        "confirm_ok": "Check",
        "confirm_cancel": "Cancel",
        "tab_check": "Check", "tab_live": "Live monitor (CLI)",
        "live_cfg": "Codex settings", "live_cfg_value": "model {model}  ·  effort {effort}   ({source})",
        "live_cfg_none": "no model in config.toml (Codex picks its default)",
        "live_folder": "Working folder", "live_folder_btn": "Folder...", "live_folder_title": "Folder to open Codex in",
        "live_start": "Start monitoring", "live_stop": "Stop",
        "live_idle": "Off. Start opens a Codex CLI window whose requests are watched here.",
        "live_running": "Watching Codex (pid {pid}) through 127.0.0.1:{port}. Work in the Codex window as usual.",
        "live_stopped": "Stopped.", "live_codex_exit": "Codex exited (code {rc}). Monitoring stopped.",
        "live_failed": "The live monitor could not start.",
        "live_needs_crypto": "The live monitor needs the cryptography package: pip install cryptography",
        "live_stop_confirm": "Stopping closes the Codex window that is being watched. Stop now?",
        "live_close_confirm": "The live monitor is running. Closing this window also closes the watched Codex window. Close?",
        "live_copy": "Copy live report", "live_clear": "Clear",
        "col_time": "Time",
        "banner_live_idle": "Live monitor off",
        "banner_live_waiting": "Watching... waiting for the first request",
        "banner_live_ok": "OK so far: {n} response(s) served as requested",
        "banner_live_rerouted": "REROUTED: {pairs} ({bad} of {total})",
        "banner_live_unsupported": "{models} is not available on this account",
        "banner_live_error": "No confirmed response yet ({n} error(s))",
        "brief_live_idle": "Codex CLI only. Start opens a terminal with Codex routed through a local proxy on this computer; every request you make there is listed here with the model that really answered. The Codex desktop app cannot be watched.",
        "brief_live_running": "Codex is running in its own window. Each request appears here as soon as the server answers; no traffic is written to disk.",
        "brief_live_waiting": "No request yet. Type something in the Codex window.",
        "brief_live_rerouted": "{bad} of {total} responses were answered by {served} although Codex asked for {requested}.",
        "brief_live_ok": "{n} response(s) so far, all answered by the model Codex asked for.",
        "brief_live_unsupported": "The server refused {models} for this account (plan gating, not a substitution).",
        "brief_live_error": "The server has only returned errors so far ({errors}).",
        "confirm_live_title": "Start the live monitor?",
        "confirm_live_body": "A new terminal window opens with the Codex CLI. Its connections go through a local proxy on this computer (127.0.0.1 only) with a certificate that exists for this session only, so the model name in every server response can be read. Prompts, files and answers pass through and are not saved. Stopping the monitor closes that Codex window.",
        "confirm_live_ok": "Start",
        "guide_title": "Live monitor",
        "guide_heading": "\U0001F44B  Hi! Here is what this tab does",
        "guide_body": (
            "\U0001F680  Press Start monitoring.\nA Codex CLI window opens by itself. Work in it as you always do.\n\n"
            "\U0001F50D  Every time Codex calls a model, this tab checks which model really answered\n"
            "and adds a line: the model Codex asked for, the model that answered, and the verdict.\n\n"
            "\U0001F7E2  Green: the model you chose answered.\n\U0001F534  Red: it was quietly routed to another model.\n\n"
            "\U0001F512  Everything stays on your computer.\nPrompts, files and answers are never saved; only model names and ids are kept.\n\n"
            "\U0001F4BB  Codex CLI only (not the Codex desktop app).\nWhen you are done, press Stop."
        ),
        "guide_ok": "Got it!",
        "guide_skip": "Don't show this again",
        "panel_options": "Options", "panel_results": "Results", "panel_session": "Session",
    },
    "ko": {
        "model": "모델", "effort": "Effort", "repeat": "반복",
        "wire": "Wire 모드 (mitmproxy)", "no_mitm": "Wire 모드 (mitmproxy 없음)",
        "codex_btn": "Codex...", "codex_auto": "자동 탐지", "codex_pick_title": "codex 실행 파일 선택",
        "check": "Check", "cancel": "취소", "copy": "보고서 복사", "save_json": "JSON 저장...", "open_logs": "로그 폴더 열기",
        "lang": "English", "idle": "준비됨. Check를 누르면 모델마다 짧은 Codex 턴을 하나 보냅니다.",
        "starting": "codex 시작 중 ({version})...", "running": "검사 중 {i}/{n}: {model} ({effort})...",
        "done": "완료 ({secs}초). 원문 로그: {dir}", "cancelling": "취소하는 중...", "cancelled": "취소됨.",
        "failed": "검사를 시작하지 못했습니다.",
        "col_n": "#", "col_requested": "요청한 모델", "col_kind": "종류", "col_served": "실제 응답 모델",
        "col_status": "상태", "col_created": "생성 (UTC)", "col_verdict": "판정", "col_id": "응답 ID",
        "kind_warmup": "웜업", "kind_turn": "턴",
        "banner_idle": "아직 결과 없음", "banner_running": "검사 중...",
        "banner_rerouted": "바꿔치기 감지: {pairs}", "banner_ok": "정상: {models} 요청대로 응답",
        "banner_error": "확인 실패: {models}", "banner_cancelled": "취소됨", "banner_fatal": "오류",
        "banner_unsupported": "{models}은(는) 이 계정(플랜 {plan})에서 쓸 수 없는 모델입니다",
        "notes": "상세", "account": "계정", "codex": "Codex",
        "codex_hint": "\"Codex...\" 버튼으로 codex 실행 파일을 직접 고를 수 있습니다 (npm 패키지 안의 codex.exe 또는 Codex Desktop 번들).",
        "copied": "보고서를 클립보드에 복사했습니다.", "saved": "저장함: {path}", "fake": "(샘플 데이터, 실제 검사 아님)",
        "update_new": "NEW v{new}",
        "update_pip": "새 버전 {new}: pipx upgrade codex-routing-detector  (또는 pip install -U git+{repo})",
        "update_manual": "새 버전 {new}이 있습니다. 오른쪽 아래 NEW를 눌러 받으세요.",
        "update_downloading": "v{new}로 업데이트 중: {mb} MB 다운로드...",
        "update_restarting": "다운로드 완료. v{new}로 다시 시작합니다...",
        "update_failed": "v{new} 자동 업데이트 실패 ({err}). 오른쪽 아래 NEW를 눌러 직접 받으세요.",
        "updated": "v{current}로 업데이트됨.",
        "subtitle": "내 Codex 요청에 실제로 어떤 모델이 응답했을까?",
        "brief": "브리핑",
        "brief_idle": "Check를 누르세요. Codex에 짧은 프롬프트 하나를 보내고, 서버의 응답에서 실제로 답한 모델을 읽습니다.",
        "brief_running": "Codex에 짧은 프롬프트를 보내고 서버의 응답 객체를 기다리는 중...",
        "brief_rerouted": "{models}로 요청했지만 서버는 {served}로 응답했습니다(응답 {total}개 중 {bad}개).",
        "brief_ok": "{models}가 직접 응답했습니다. 지금은 바꿔치기가 없습니다.",
        "brief_unsupported": "이 계정(플랜 {plan})에서는 {models}를 쓸 수 없어 서버가 거절했습니다. 요금제 제한이지 바꿔치기가 아닙니다.",
        "brief_error": "{models} 검사가 끝나지 못했습니다. 서버 오류: {errors}.",
        "brief_nodata": "{models}에 대한 서버 응답이 없습니다. 아래 상세에 Codex가 남긴 내용이 있습니다.",
        "brief_cancelled": "검사 {n}개 후 취소했습니다.",
        "brief_fatal": "검사를 시작하지 못했습니다: {error}",
        "brief_account": "플랜 {plan}, 사용량 창의 {used}% 사용.",
        "brief_not_limit": "따라서 한도 소진 때문에 예비 모델로 넘어간 것이 아닙니다.",
        "brief_limit": "사용량 한도에 도달한 상태라 예비 모델로 넘어갔을 수 있습니다.",
        "brief_advice_rerouted": "당분간 다른 모델을 쓰거나 잠시 뒤 다시 확인하세요. 라우팅 상태는 시간에 따라 바뀝니다. 제보하려면 보고서 복사를 누르세요.",
        "brief_advice_ok": "지금 이 모델로 작업하기 좋은 때입니다. 답이 이상해지면 다시 확인하세요.",
        "brief_advice_unsupported": "요금제에 포함된 모델을 고르고 다시 Check를 누르세요.",
        "brief_advice_error": "잠시 뒤 다시 Check를 누르세요. capacity 오류는 대개 곧 지나갑니다.",
        "confirm_title": "검사를 실행할까요?",
        "confirm_body": "Codex Routing Detector가 {model} 모델로 Codex에 짧은 프롬프트 하나(\"Reply with exactly the single word: pong\")를 보내고, 서버가 돌려준 응답 객체를 읽어 실제로 어떤 모델이 답했는지 확인합니다.",
        "confirm_skip": "다시 묻지 않기",
        "confirm_ok": "검사 시작",
        "confirm_cancel": "취소",
        "tab_check": "Check", "tab_live": "라이브 모니터 (CLI)",
        "live_cfg": "Codex 설정", "live_cfg_value": "모델 {model}  ·  effort {effort}   ({source})",
        "live_cfg_none": "config.toml에 모델이 없습니다 (Codex 기본값 사용)",
        "live_folder": "작업 폴더", "live_folder_btn": "폴더...", "live_folder_title": "Codex를 열 폴더",
        "live_start": "모니터링 시작", "live_stop": "중지",
        "live_idle": "꺼짐. 시작을 누르면 Codex CLI 창이 열리고 그 요청을 여기서 감시합니다.",
        "live_running": "Codex(pid {pid})를 127.0.0.1:{port} 프록시로 감시 중. Codex 창에서 평소처럼 작업하세요.",
        "live_stopped": "중지됨.", "live_codex_exit": "Codex가 종료됐습니다 (코드 {rc}). 모니터링을 멈췄습니다.",
        "live_failed": "라이브 모니터를 시작하지 못했습니다.",
        "live_needs_crypto": "라이브 모니터에는 cryptography 패키지가 필요합니다: pip install cryptography",
        "live_stop_confirm": "중지하면 감시 중인 Codex 창도 닫힙니다. 중지할까요?",
        "live_close_confirm": "라이브 모니터가 실행 중입니다. 이 창을 닫으면 감시 중인 Codex 창도 닫힙니다. 닫을까요?",
        "live_copy": "라이브 보고서 복사", "live_clear": "지우기",
        "col_time": "시각",
        "banner_live_idle": "라이브 모니터 꺼짐",
        "banner_live_waiting": "감시 중... 첫 요청을 기다립니다",
        "banner_live_ok": "지금까지 정상: 응답 {n}개 모두 요청대로",
        "banner_live_rerouted": "바꿔치기 감지: {pairs} ({total}개 중 {bad}개)",
        "banner_live_unsupported": "{models}은(는) 이 계정에서 쓸 수 없는 모델입니다",
        "banner_live_error": "아직 확인된 응답 없음 (오류 {n}개)",
        "brief_live_idle": "Codex CLI 전용입니다. 시작을 누르면 이 컴퓨터의 로컬 프록시를 거치는 Codex 터미널이 열리고, 거기서 보내는 모든 요청이 실제로 답한 모델과 함께 여기에 쌓입니다. Codex 데스크톱 앱은 감시할 수 없습니다.",
        "brief_live_running": "Codex가 별도 창에서 실행 중입니다. 서버가 답하는 즉시 요청이 여기에 나타나며, 통신 내용은 디스크에 저장하지 않습니다.",
        "brief_live_waiting": "아직 요청이 없습니다. Codex 창에 무엇이든 입력해 보세요.",
        "brief_live_rerouted": "Codex는 {requested}로 요청했지만 응답 {total}개 중 {bad}개는 {served}가 답했습니다.",
        "brief_live_ok": "지금까지 응답 {n}개 모두 Codex가 요청한 모델이 답했습니다.",
        "brief_live_unsupported": "서버가 이 계정에서는 {models}를 쓸 수 없다고 거절했습니다 (요금제 제한이지 바꿔치기가 아닙니다).",
        "brief_live_error": "지금까지 서버가 오류만 돌려줬습니다 ({errors}).",
        "confirm_live_title": "라이브 모니터를 시작할까요?",
        "confirm_live_body": "Codex CLI가 새 터미널 창에서 열립니다. 그 창의 통신은 이 컴퓨터 안의 로컬 프록시(127.0.0.1 전용)를 거치고, 이번 세션에만 쓰는 인증서로 서버 응답 속 모델명을 읽습니다. 프롬프트, 파일, 답변은 그대로 지나가며 저장하지 않습니다. 모니터를 중지하면 그 Codex 창도 닫힙니다.",
        "confirm_live_ok": "시작",
        "guide_title": "라이브 모니터",
        "guide_heading": "\U0001F44B  안녕하세요! 이 탭은 이런 일을 해요",
        "guide_body": (
            "\U0001F680  모니터링 시작을 누르세요.\nCodex CLI 창이 자동으로 열려요. 그 창에서 평소처럼 작업하시면 돼요.\n\n"
            "\U0001F50D  Codex가 모델을 호출할 때마다 실제로 어떤 모델이 답했는지 확인해서\n"
            "여기에 한 줄씩 적어요. 요청한 모델, 실제로 답한 모델, 판정이 나란히 보여요.\n\n"
            "\U0001F7E2  초록: 고른 모델이 답했어요.\n\U0001F534  빨강: 몰래 다른 모델로 라우팅됐어요.\n\n"
            "\U0001F512  전부 내 컴퓨터 안에서만 일어나요.\n프롬프트·파일·답변은 저장하지 않고, 모델명과 ID만 기억해요.\n\n"
            "\U0001F4BB  Codex CLI에서만 돼요 (데스크톱 앱은 아직 안 돼요).\n다 끝나면 중지를 눌러 주세요."
        ),
        "guide_ok": "알겠어요!",
        "guide_skip": "다시 보지 않기",
        "panel_options": "옵션", "panel_results": "결과", "panel_session": "세션",
    },
}

MENU: Dict[str, Dict[str, str]] = {
    "en": {"help": "Help", "usage": "How to use", "terms": "Glossary", "about": "About", "close": "Close",
           "guide": "Live monitor guide"},
    "ko": {"help": "도움말", "usage": "기본 사용법", "terms": "용어 설명", "about": "정보", "close": "닫기",
           "guide": "라이브 모니터 안내"},
}

HELP_USAGE = {
    "en": """HOW TO USE

1. Pick the model to check. The default is the model in ~/.codex/config.toml.

2. Press Check. Each probe is one short Codex turn ("Reply with exactly the single word: pong"). The table fills in as probes finish; Cancel stops the run.

3. Read the banner.
REROUTED: the server answered with a different model than you asked for.
OK: the model you asked for answered.
Not available on this account: your plan does not include that model (the server refused it). Pick another model.
Could not check: a server error or a missing response. Press Check again.

4. Copy report puts the full text report (with response ids) on the clipboard, ready for a bug report or a support ticket. Save JSON writes the same data as JSON. Open log folder shows the raw server frames.

OPTIONS

Effort: reasoning effort sent with the probe. low is the cheapest, and the substitution seen so far did not depend on it.
Repeat: run every probe N times (1 to 10). Useful because the server state changes over time.
Wire mode: capture with mitmproxy instead of trace logging (needs pip install mitmproxy).
Codex...: pick the codex binary by hand if it was not found automatically.

LIVE MONITOR (second tab, Codex CLI only)

Instead of sending probes, watch your own Codex session. Start monitoring opens a new terminal window with the Codex CLI; work there as usual. Every request you make is listed in the table as soon as the server answers, with the model Codex asked for, the model that really answered and the verdict. The banner and briefing sum it up as you go.

Codex settings shows the model and reasoning effort from ~/.codex/config.toml (re-read when the file changes) so you can see what Codex will ask for. Working folder is where the Codex window opens.

Stop closes the Codex window (it cannot reach the server without the monitor). Closing Codex yourself also ends the monitor. Copy live report puts the table on the clipboard.

The Codex desktop app cannot be watched: it is a packaged application that does not take settings from another program. Use the Check tab for it.

COST AND PRIVACY

One check sends two requests per model (warm-up plus turn), counted like any other Codex usage. The live monitor sends nothing of its own.
Check logs contain your thread ids, account user id and the probe prompt, but no tokens or cookies; the request body and your home directory are never written.
The live monitor keeps only model names, response ids, statuses, timestamps and error codes, in memory. Your prompts, files and the model's answers pass through it and are never stored. It listens on 127.0.0.1 only and uses a certificate that is created for the session and deleted afterwards; nothing is installed in the system certificate store.
""",
    "ko": """기본 사용법

1. 검사할 모델을 고릅니다. 기본값은 ~/.codex/config.toml에 적힌 모델입니다.

2. Check를 누릅니다. 검사 하나는 아주 짧은 Codex 턴 하나입니다 ("Reply with exactly the single word: pong"). 끝나는 대로 표에 행이 추가되고, 취소 버튼으로 중단할 수 있습니다.

3. 배너를 읽습니다.
바꿔치기 감지: 서버가 요청한 것과 다른 모델로 응답했습니다.
정상: 요청한 모델이 응답했습니다.
이 계정에서 쓸 수 없는 모델: 요금제에 그 모델이 없어 서버가 거절했습니다. 다른 모델을 고르세요.
확인 실패: 서버 오류나 응답 누락입니다. 다시 Check를 눌러 보세요.

4. 보고서 복사는 응답 ID가 든 전체 보고서를 클립보드에 복사합니다 (이슈 제출·지원 문의용). JSON 저장은 같은 내용을 JSON으로 저장하고, 로그 폴더 열기는 서버 프레임 원문 폴더를 엽니다.

옵션

Effort: 검사에 보낼 reasoning effort. low가 가장 저렴하고, 지금까지 관찰된 바꿔치기는 effort와 무관했습니다.
반복: 각 검사를 N번(1~10) 반복합니다. 서버 상태가 시간에 따라 바뀌므로 유용합니다.
Wire 모드: trace 로그 대신 mitmproxy로 패킷을 캡처합니다 (pip install mitmproxy 필요).
Codex...: Codex를 자동으로 못 찾을 때 실행 파일을 직접 지정합니다.

라이브 모니터 (두 번째 탭, Codex CLI 전용)

검사 요청을 보내는 대신 내 Codex 세션을 그대로 지켜봅니다. 모니터링 시작을 누르면 Codex CLI가 새 터미널 창에서 열리고, 거기서 평소처럼 작업하면 됩니다. 보내는 요청마다 서버가 답하는 즉시 표에 한 줄씩 쌓입니다 (Codex가 요청한 모델, 실제로 답한 모델, 판정). 배너와 브리핑은 그때그때 요약을 보여줍니다.

Codex 설정에는 ~/.codex/config.toml의 모델과 reasoning effort가 표시되며, 파일이 바뀌면 다시 읽습니다. 작업 폴더는 Codex 창이 열릴 폴더입니다.

중지를 누르면 Codex 창도 닫힙니다 (모니터 없이는 서버에 연결할 수 없기 때문입니다). Codex를 직접 닫아도 모니터가 끝납니다. 라이브 보고서 복사는 표 내용을 클립보드에 넣습니다.

Codex 데스크톱 앱은 감시할 수 없습니다. 패키지 형태로 설치되는 앱이라 다른 프로그램이 설정을 넣어 줄 수 없습니다. 데스크톱 앱 사용자는 Check 탭을 쓰세요.

비용과 프라이버시

검사 한 번에 모델당 요청 2개(웜업 + 턴)가 나가며, 일반 Codex 사용량으로 차감됩니다. 라이브 모니터는 스스로 요청을 보내지 않습니다.
검사 로그에는 스레드 ID, 계정 사용자 ID, 검사 프롬프트가 남지만 토큰과 쿠키는 없고, 요청 본문과 홈 폴더 경로는 기록되지 않습니다.
라이브 모니터는 모델명, 응답 ID, 상태, 시각, 오류 코드만 메모리에 둡니다. 프롬프트, 파일, 모델의 답변은 그대로 지나가며 저장하지 않습니다. 127.0.0.1에서만 듣고, 인증서는 이번 세션용으로 만들었다가 끝나면 지웁니다. 시스템 인증서 저장소에는 아무것도 설치하지 않습니다.
""",
}

HELP_TERMS = {
    "en": """GLOSSARY

Requested model
The model name the client put in its request, i.e. what you chose.

Served by
The model name the server wrote into its own response object (response.created / response.completed). This is the model that actually answered. It is read from the raw WebSocket frames, not from Codex's logs.

Turn
Your real request: the prompt goes to the server and the model answers. Its response carries previous_response_id.

Warm-up
A request Codex sends by itself just before the turn, with no user input, to open the connection and pre-load the system prompt (internally "prewarm"). It is a real request for the chosen model, so a warm-up answered by another model is evidence too.

Control (command line only)
The terminal version can check a second model right after yours (--control, default gpt-5.6-sol): if that one is served correctly while yours is not, the substitution is specific to your model. The window does not use it.

Effort
model_reasoning_effort: low / medium / high / xhigh.

Service tier
"priority" (faster, more usage) or default; taken from config.toml.

Response id
The server's id for one response (resp_...). Quote it in bug reports so the provider can look the request up.

Created (UTC)
The server's own timestamp for the response.

Status
completed / failed / in_progress, as reported by the server.

VERDICTS

ok: served as requested and the turn completed.
REROUTED: a response object named another model (warm-up or turn, even if it then failed).
ERROR: the server answered with an error, e.g. server_is_overloaded, which Codex shows as "Selected model is at capacity". Not a substitution; try again.
UNSUPPORTED: the server refused the model for this account ("not supported when using Codex with a ChatGPT account" and similar). Your plan does not include it; not a substitution.
UNKNOWN: could not be confirmed. No model field, a turn that never completed, or only the warm-up was seen.
NO_DATA: no WebSocket frames at all. Codex is not signed in, could not start, or uses a transport this tool cannot read (see the note under the row).

MODES

Trace mode (default): runs codex with RUST_LOG=tungstenite::protocol=trace so the WebSocket library prints every frame it receives, verbatim, before Codex's own code sees it.
Wire mode: runs a local mitmproxy with a throw-away certificate and records both directions of the WebSocket. Needs mitmproxy installed.
Live monitor: a built-in proxy on 127.0.0.1 with a session-only certificate; the Codex CLI is started with HTTPS_PROXY and CODEX_CA_CERTIFICATE pointing at it, so the responses WebSocket can be decoded as it passes through. Nothing is changed or stored.

Rate limits
The "Account" line: plan type and the share of the usage window already used. If limit_reached is False, a substitution is not a usage-limit fallback.
""",
    "ko": """용어 설명

요청한 모델
클라이언트가 요청에 적은 모델명, 즉 사용자가 고른 모델입니다.

실제 응답 모델
서버가 자기 응답 객체(response.created / response.completed)에 적은 모델명입니다. 실제로 응답한 모델이며, Codex 로그가 아니라 WebSocket 프레임 원문에서 읽습니다.

턴
실제 요청입니다. 프롬프트가 서버로 가고 모델이 답을 만듭니다. 응답에 previous_response_id가 붙어 있습니다.

웜업
Codex가 턴 직전에 스스로 보내는 요청입니다. 사용자 입력 없이 연결을 열고 시스템 프롬프트를 미리 올려 둡니다 (내부 이름 prewarm). 고른 모델로 보내는 진짜 요청이라, 웜업이 다른 모델로 응답돼도 바꿔치기의 증거가 됩니다.

대조군 (터미널 전용)
터미널 버전은 내 모델 바로 뒤에 비교용 모델을 하나 더 검사할 수 있습니다(--control, 기본 gpt-5.6-sol). 그쪽은 정상인데 내 모델만 다르면 "내 모델만 바꿔치기"라는 뜻입니다. 창에서는 쓰지 않습니다.

Effort
model_reasoning_effort: low / medium / high / xhigh.

Service tier
"priority"(더 빠름, 사용량 더 씀) 또는 기본. config.toml 값을 따릅니다.

응답 ID
서버가 응답마다 붙이는 ID(resp_...)입니다. 이슈나 문의에 적으면 서버 쪽에서 추적할 수 있습니다.

생성 (UTC)
서버가 찍은 응답 생성 시각입니다.

상태
completed / failed / in_progress. 서버가 보고한 값입니다.

판정

ok: 요청대로 응답했고 턴이 정상 완료됨.
REROUTED: 응답 객체에 다른 모델명이 있음 (웜업이든 턴이든, 이후 실패했더라도).
ERROR: 서버 오류. 예: server_is_overloaded, Codex 화면의 "Selected model is at capacity". 바꿔치기가 아니니 다시 시도.
UNSUPPORTED: 서버가 이 계정에서는 그 모델을 쓸 수 없다고 거절함("not supported when using Codex with a ChatGPT account" 등). 요금제에 없는 모델이며 바꿔치기가 아님.
UNKNOWN: 확인 불가. model 필드 없음, 턴이 완료 전에 끊김, 웜업만 보임.
NO_DATA: WebSocket 프레임이 전혀 없음. 로그인 안 됨, Codex 시작 실패, 또는 이 도구가 읽지 못하는 전송 방식 (행 아래 note 참고).

모드

Trace 모드(기본): codex를 RUST_LOG=tungstenite::protocol=trace로 실행해서 WebSocket 라이브러리가 받은 프레임을 원문 그대로 찍게 합니다. Codex 코드가 손대기 전 단계입니다.
Wire 모드: 임시 인증서로 로컬 mitmproxy를 띄워 WebSocket 양방향을 기록합니다. mitmproxy 설치가 필요합니다.
라이브 모니터: 127.0.0.1에서 듣는 내장 프록시와 세션 전용 인증서를 씁니다. Codex CLI를 HTTPS_PROXY와 CODEX_CA_CERTIFICATE가 그 프록시를 가리키도록 실행해서, 지나가는 responses WebSocket을 해독합니다. 바꾸거나 저장하는 것은 없습니다.

한도 (rate limits)
"계정" 줄에 플랜 종류와 사용량 창의 소진 비율이 나옵니다. limit_reached가 False면 한도 소진 때문에 예비 모델로 넘어간 게 아닙니다.
""",
}

HELP_ABOUT = {
    "en": """codex-routing-detector v{version}

Shows which model actually answers your Codex requests, by reading the model name the server
writes into its own response objects. Built on 2026-09-22 after wire captures showed
gpt-6-astra requests being served by gpt-5.6-luna on a ChatGPT Pro account.

The command-line version (codex_routing_detector.py) has more options; see README.md.
Source and updates: {repo}
""",
    "ko": """codex-routing-detector v{version}

서버가 응답 객체에 적은 모델명을 읽어서, Codex 요청에 실제로 어떤 모델이 응답했는지
보여줍니다. 2026-09-22에 ChatGPT Pro 계정에서 gpt-6-astra 요청이 gpt-5.6-luna로 처리되는
것을 패킷 캡처로 확인한 뒤 만들었습니다.

명령줄 버전(codex_routing_detector.py)에 더 많은 옵션이 있습니다. README.md를 참고하세요.
소스와 업데이트: {repo}
""",
}

# ------------------------------------------------------------------ theme
PALETTE = {  # soft pastel: lavender accent on a blush background
    "bg": "#fff5fa", "card": "#ffffff", "border": "#f2d6e6", "text": "#4a3b5c", "muted": "#9a8aae",
    "accent": "#b48cff", "accent_dark": "#9b6bff", "accent_text": "#ffffff", "head": "#f7f0ff",
    "row_alt": "#fcf8ff", "secondary": "#ffe1ee", "secondary_dark": "#ffcbe0", "secondary_text": "#7a3b5c",
    "disabled": "#e9e2f2", "disabled_text": "#b8adc9", "tab": "#f7e9f3",
    "outline": "#5b3d6e", "shadow": "#5b3d6e",
}
PASTEL = {"pink": "#ffd6e7", "lavender": "#dcd0ff", "mint": "#cfeee5", "yellow": "#fff1b8", "peach": "#ffe0cc",
          "sky": "#d6ecff", "white": "#ffffff"}
FONT_UI = "Segoe UI" if os.name == "nt" else "TkDefaultFont"
FONT_MONO = "Consolas" if os.name == "nt" else "TkFixedFont"
VERDICT_STYLE = {  # verdict: (background, foreground, glyph)
    "ok": ("#dff7ea", "#1f7a4d", "✔"), "REROUTED": ("#ffe1e6", "#c0304f", "✖"),
    "ERROR": ("#fff0d6", "#a3600b", "⚠"), "UNSUPPORTED": ("#fff0d6", "#a3600b", "⚠"),
    "UNKNOWN": ("#efeaf7", "#5d4e75", "•"), "NO_DATA": ("#efeaf7", "#5d4e75", "•"),
    "CANCELLED": ("#efeaf7", "#5d4e75", "•"), "RUNNING": ("#e8e6ff", "#4b3fa3", "…"),
    "IDLE": ("#f3eef8", "#7a6c8f", "•"),
}
# which mascot picture goes with a banner state
VERDICT_MOOD = {"ok": "mood_ok", "REROUTED": "mood_rerouted", "ERROR": "mood_error", "UNSUPPORTED": "mood_error",
                "UNKNOWN": "mood_error", "NO_DATA": "mood_error", "CANCELLED": "mood_idle", "RUNNING": "mood_idle",
                "IDLE": "mood_idle"}
VERDICT_COLORS = {k: (v[0], v[1]) for k, v in VERDICT_STYLE.items()}

SETTINGS_ENV = "CODEX_ROUTING_DETECTOR_SETTINGS"


def settings_path() -> Path:
    return Path(os.environ.get(SETTINGS_ENV) or (Path.home() / ".codex-routing-detector.json"))


def load_settings() -> dict:
    try:
        data = json.loads(settings_path().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_settings(data: dict) -> None:
    try:
        settings_path().write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception:
        pass  # a read-only home directory must not break the app


def listed_models() -> List[str]:
    """Model slugs from Codex's own catalog cache, falling back to a built-in list."""
    try:
        data = json.loads((cmc.codex_home() / "models_cache.json").read_text(encoding="utf-8"))
        slugs = [m["slug"] for m in data.get("models", []) if isinstance(m, dict) and m.get("slug")
                 and m.get("visibility", "list") == "list"]
        if slugs:
            return slugs
    except Exception:
        pass
    return list(FALLBACK_MODELS)


def open_folder(path: Path) -> None:
    try:
        if os.name == "nt":
            os.startfile(str(path))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])
    except Exception as e:  # pragma: no cover - depends on the desktop
        messagebox.showerror(APP_TITLE, str(e))


def install_fake_runner() -> bool:
    """Replace the codex launcher with the bundled fixture runs (tests, screenshots)."""
    fx = Path(__file__).resolve().parent / "tests" / "fixtures"
    astra = fx / "astra_served_by_luna.log"
    sol = fx / "sol_capacity_error.log"
    if not astra.exists() or not sol.exists():
        return False
    astra_t, sol_t = astra.read_bytes(), sol.read_bytes()

    def fake_capture(cmd, timeout, env=None, cwd=None, on_start=None):
        time.sleep(0.4)
        joined = " ".join(cmd)
        if "--version" in cmd:
            return 0, b"codex-cli 0.153.4 (fake)\n", b"", False
        if "--help" in cmd:
            return 0, b"--ephemeral\n", b"", False
        body = astra_t if "astra" in joined else sol_t
        return (0 if body is astra_t else 1), b"pong\n", body, False

    cmc.run_capture = fake_capture  # type: ignore[assignment]
    cmc.find_codex = lambda explicit: (["codex-fake"], "fixture runner")  # type: ignore[assignment]
    return True


class FakeCodexProcess:
    """Stands in for the Codex window in --fake mode and in tests: never exits by itself."""

    def __init__(self) -> None:
        self.pid = 0
        self._done = threading.Event()
        self.returncode = 0

    def poll(self):
        return self.returncode if self._done.is_set() else None

    def wait(self):
        self._done.wait()
        return self.returncode

    def finish(self, rc: int = 0) -> None:
        self.returncode = rc
        self._done.set()


def fake_launcher(cmd, env, cwd) -> FakeCodexProcess:
    return FakeCodexProcess()


def feed_fake_live(app: "App") -> None:
    """--fake-live: a few made-up responses for screenshots (ids are placeholders)."""
    if app.monitor is None:
        return
    now = time.time()

    def m(direction: str, obj: dict, conn: int, dt: float) -> crp.WsMessage:
        return crp.WsMessage(direction, json.dumps(obj), now + dt, conn)

    resp = lambda rid, model, status, prev=None, dt=0.0, conn=1: m(  # noqa: E731
        "s2c", {"type": "response.completed" if status == "completed" else "response.created",
                "response": {"id": rid, "model": model, "status": status, "previous_response_id": prev}}, conn, dt)
    events = [
        ("ws_open", {"conn": 1, "routing_hint": "model=gpt-6-astra;tier=priority", "watched": True, "deflate": True}),
        ("message", m("c2s", {"type": "response.create", "model": "gpt-6-astra"}, 1, 0)),
        ("message", m("s2c", {"type": "codex.rate_limits", "plan_type": "pro",
                              "rate_limits": {"primary": {"used_percent": 9}, "limit_reached": False}}, 1, 0)),
        ("message", resp("resp_0000000000000000000000000000000000000000000000000001", "gpt-5.6-luna", "in_progress", dt=0.1)),
        ("message", resp("resp_0000000000000000000000000000000000000000000000000001", "gpt-5.6-luna", "completed", dt=0.1)),
        ("message", m("c2s", {"type": "response.create", "model": "gpt-6-astra", "input": [{"role": "user"}]}, 1, 1)),
        ("message", resp("resp_0000000000000000000000000000000000000000000000000002", "gpt-5.6-luna", "in_progress", "resp_1", 1.2)),
        ("message", resp("resp_0000000000000000000000000000000000000000000000000002", "gpt-5.6-luna", "completed", "resp_1", 1.2)),
        ("message", m("c2s", {"type": "response.create", "model": "gpt-6-astra", "input": [{"role": "user"}]}, 1, 40)),
        ("message", resp("resp_0000000000000000000000000000000000000000000000000003", "gpt-6-astra", "completed", "resp_2", 41)),
    ]
    for ev in events:
        app.monitor.events.put(ev)


def build_brief(res: cmc.CheckResult, lang: str) -> str:
    """Two to four plain sentences about the result, in the interface language."""
    t = STRINGS[lang if lang in STRINGS else "en"]
    main = [p for p in res.probes if not p.is_control]
    models = ", ".join(sorted({p.requested for p in main})) or "?"
    parts: List[str] = []
    if res.error:
        parts.append(t["brief_fatal"].format(error=res.error))
        return " ".join(parts)
    rl = next((p.rate_limits for p in res.probes if p.rate_limits), None)
    plan = rl.get("plan_type") if rl else None
    prim = ((rl or {}).get("rate_limits") or {}).get("primary") or {}
    used = prim.get("used_percent")
    reached = ((rl or {}).get("rate_limits") or {}).get("limit_reached")
    if res.overall == "REROUTED":
        served, bad, total = set(), 0, 0
        for p in main:
            for r in p.responses:
                v = r.verdict(p.requested)
                if v in ("ok", "REROUTED"):
                    total += 1
                if v == "REROUTED":
                    bad += 1
                    served.update(m for m in r.models_seen if not cmc.models_match(p.requested, m)[0])
        parts.append(t["brief_rerouted"].format(models=models, served=", ".join(sorted(served)) or "?", bad=bad, total=total))
        if plan:
            parts.append(t["brief_account"].format(plan=plan, used=used if used is not None else "?"))
            parts.append(t["brief_not_limit"] if reached is False else t["brief_limit"])
        parts.append(t["brief_advice_rerouted"])
    elif res.overall == "OK":
        parts.append(t["brief_ok"].format(models=models))
        if plan:
            parts.append(t["brief_account"].format(plan=plan, used=used if used is not None else "?"))
        parts.append(t["brief_advice_ok"])
    elif res.overall == "UNSUPPORTED":
        parts.append(t["brief_unsupported"].format(models=models, plan=plan or "?"))
        parts.append(t["brief_advice_unsupported"])
    elif res.cancelled:
        parts.append(t["brief_cancelled"].format(n=len(res.probes)))
    else:
        errs = sorted({r.error_code or "?" for p in main for r in p.responses if r.error_code} |
                      {c or "?" for p in main for c, _ in p.stream_errors})
        if errs:
            parts.append(t["brief_error"].format(models=models, errors=", ".join(errs)))
        else:
            parts.append(t["brief_nodata"].format(models=models))
        parts.append(t["brief_advice_error"])
    return " ".join(parts)


def rounded_rect(canvas: tk.Canvas, x1: float, y1: float, x2: float, y2: float, r: float, **kw) -> int:
    pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2, x2 - r, y2, x1 + r, y2,
           x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
    return canvas.create_polygon(pts, smooth=True, **kw)


BUTTON_STYLES = {  # kind: {state: (fill, text colour)}
    "primary": {"normal": (PASTEL["lavender"], "#4a3b5c"), "hover": ("#cbb9ff", "#4a3b5c"),
                "disabled": ("#efe9f5", "#b8adc9")},
    "secondary": {"normal": (PASTEL["pink"], "#7a3b5c"), "hover": ("#ffc4dc", "#7a3b5c"),
                  "disabled": ("#efe9f5", "#b8adc9")},
    "tab": {"normal": ("#ffffff", "#9a8aae"), "hover": (PASTEL["yellow"], "#4a3b5c"), "disabled": ("#efe9f5", "#b8adc9")},
    "tab_selected": {"normal": (PASTEL["mint"], "#4a3b5c"), "hover": (PASTEL["mint"], "#4a3b5c"),
                     "disabled": (PASTEL["mint"], "#4a3b5c")},
}


_FONT_CACHE: dict = {}


def _font(spec):
    """tkinter.font.Font objects are cached for the process: one collected by the garbage
    collector on a worker thread would call into Tk from that thread (and stall it)."""
    import tkinter.font as tkfont
    key = tuple(spec) if isinstance(spec, (list, tuple)) else spec
    f = _FONT_CACHE.get(key)
    if f is not None:
        try:
            f.metrics("linespace")
            return f
        except tk.TclError:
            pass
    f = tkfont.Font(font=spec)
    _FONT_CACHE[key] = f
    return f


class RoundedButton(tk.Canvas):
    """A sticker-style button: rounded pill with a thick outline and an offset shadow, drawn on a
    canvas (tk.Button cannot look like this). Supports the subset of the tk.Button interface the
    app uses: text, state, command."""

    OUTLINE_W = 2
    SHADOW = 3

    def __init__(self, parent: tk.Misc, text: str = "", command=None, kind: str = "primary", bg: str = "",
                 padx: int = 22, pady: int = 7, font=None, state: str = "normal", **_ignored) -> None:
        super().__init__(parent, highlightthickness=0, bd=0, bg=bg or PALETTE["bg"], cursor="hand2")
        self._text, self._command, self._kind, self._state = text, command, kind, state
        self._padx, self._pady = padx, pady
        self._font = font or (FONT_UI, 11, "bold")
        self._hover = False
        self._pressed = False
        self.bind("<Enter>", lambda _e: self._set_hover(True))
        self.bind("<Leave>", lambda _e: self._set_hover(False))
        self.bind("<ButtonPress-1>", lambda _e: self._press(True))
        self.bind("<ButtonRelease-1>", self._release)
        self._draw()

    def _set_hover(self, on: bool) -> None:
        self._hover = on
        self._draw()

    def _press(self, on: bool) -> None:
        self._pressed = on
        self._draw()

    def _release(self, e) -> None:
        inside = 0 <= e.x <= self.winfo_width() and 0 <= e.y <= self.winfo_height()
        was = self._pressed
        self._pressed = False
        self._draw()
        if was and inside:
            self.invoke()

    def invoke(self) -> None:
        if self._state == "normal" and self._command is not None:
            self._command()

    def _draw(self) -> None:
        f = _font(self._font)
        w = f.measure(self._text) + 2 * self._padx + self.SHADOW
        h = f.metrics("linespace") + 2 * self._pady + self.SHADOW
        tk.Canvas.configure(self, width=w, height=h)
        self.delete("all")
        disabled = self._state != "normal"
        state = "disabled" if disabled else ("hover" if self._hover else "normal")
        fill, text = BUTTON_STYLES[self._kind][state]
        r = min((h - self.SHADOW) / 2, 16)
        down = self._pressed and not disabled
        dx = self.SHADOW if down else 0
        if not disabled and not down:
            rounded_rect(self, 1 + self.SHADOW, 1 + self.SHADOW, w - 1, h - 1, r, fill=PALETTE["shadow"], outline="")
        rounded_rect(self, 1 + dx, 1 + dx, w - 1 - self.SHADOW + dx, h - 1 - self.SHADOW + dx, r, fill=fill,
                     outline=PALETTE["outline"] if not disabled else "#d8cfe3", width=self.OUTLINE_W)
        self.create_text((w - self.SHADOW) / 2 + dx, (h - self.SHADOW) / 2 + dx, text=self._text, fill=text,
                         font=self._font)
        tk.Canvas.configure(self, cursor="arrow" if disabled else "hand2")

    def configure(self, cnf=None, **kw):  # type: ignore[override]
        if isinstance(cnf, dict):
            kw.update(cnf)
        redraw = False
        for key in ("text", "state", "command", "kind"):
            if key in kw:
                setattr(self, "_" + key, kw.pop(key))
                redraw = True
        for key in ("bg", "fg", "activebackground", "activeforeground", "disabledforeground", "relief", "bd",
                    "padx", "pady", "font", "cursor"):
            kw.pop(key, None)
        if kw:
            tk.Canvas.configure(self, **kw)
        if redraw:
            self._draw()

    config = configure

    def cget(self, key: str):  # type: ignore[override]
        if key in ("text", "state", "command", "kind"):
            return getattr(self, "_" + key)
        return tk.Canvas.cget(self, key)

    def __getitem__(self, key: str):
        return self.cget(key)


class RetroPanel(tk.Canvas):
    """A pastel 'retro window' card: rounded outline, coloured title bar with three dots, offset
    shadow. Put widgets into `.body` (a ttk Card frame)."""

    TITLE_H = 30
    PAD = 10
    SHADOW = 4
    RADIUS = 14

    def __init__(self, parent: tk.Misc, title: str = "", color: str = "pink", bg: str = "", expand: bool = False,
                 min_height: int = 140) -> None:
        super().__init__(parent, bg=bg or PALETTE["bg"], highlightthickness=0, bd=0)
        self.color = PASTEL.get(color, color)
        self.title = title
        self.expand = expand
        self.sticker: Optional[tk.PhotoImage] = None
        self.body = ttk.Frame(self, style="Card.TFrame", padding=(12, 8))
        self._win = self.create_window(self.PAD + 2, self.TITLE_H + 6, window=self.body, anchor="nw")
        tk.Canvas.configure(self, height=(min_height if expand else 60))  # never the canvas default of 7 cm
        self.bind("<Configure>", lambda _e: self._redraw(), add="+")
        self.body.bind("<Configure>", lambda _e: self.after_idle(self._fit), add="+")
        self.after_idle(self._fit)

    def set_title(self, text: str) -> None:
        self.title = text
        self._redraw()

    def set_sticker(self, img: Optional[tk.PhotoImage]) -> None:
        self.sticker = img
        self._redraw()

    def _fit(self) -> None:
        """Non-expanding panels take exactly the height their body asks for."""
        if self.expand or not self.winfo_exists():
            return
        want = self.body.winfo_reqheight() + self.TITLE_H + 6 + self.PAD + self.SHADOW + 2
        if abs(int(self.cget("height")) - want) > 1:
            tk.Canvas.configure(self, height=want)

    def _redraw(self) -> None:
        w, h = self.winfo_width(), self.winfo_height()
        if w < 10 or h < 10:
            return
        self.delete("chrome")
        o, r, sh = PALETTE["outline"], self.RADIUS, self.SHADOW
        x1, y1, x2, y2 = 1, 1, w - 1 - sh, h - 1 - sh
        rounded_rect(self, x1 + sh, y1 + sh, x2 + sh, y2 + sh, r, fill=PALETTE["shadow"], outline="", tags="chrome")
        rounded_rect(self, x1, y1, x2, y2, r, fill=PALETTE["card"], outline="", tags="chrome")
        rounded_rect(self, x1, y1, x2, y1 + self.TITLE_H + r, r, fill=self.color, outline="", tags="chrome")
        self.create_rectangle(x1 + 1, y1 + self.TITLE_H, x2 - 1, y1 + self.TITLE_H + r + 2, fill=PALETTE["card"],
                              outline="", tags="chrome")
        # faint grid on the title bar, like graph paper
        for gx in range(x1 + 8, x2, 12):
            self.create_line(gx, y1 + 3, gx, y1 + self.TITLE_H - 1, fill="#ffffff", tags="chrome")
        self.create_line(x1, y1 + self.TITLE_H, x2, y1 + self.TITLE_H, fill=o, width=2, tags="chrome")
        rounded_rect(self, x1, y1, x2, y2, r, fill="", outline=o, width=2, tags="chrome")
        self.create_text(x1 + 16, y1 + self.TITLE_H / 2, text=self.title, anchor="w", fill=o,
                         font=(FONT_UI, 10, "bold"), tags="chrome")
        for i, c in enumerate((PASTEL["pink"], PASTEL["yellow"], PASTEL["mint"])):
            cx = x2 - 16 - i * 18
            self.create_oval(cx - 6, y1 + self.TITLE_H / 2 - 6, cx + 6, y1 + self.TITLE_H / 2 + 6, fill=c, outline=o,
                             width=2, tags="chrome")
        if self.sticker is not None:
            self.create_image(x2 - 70, y1 + self.TITLE_H / 2, image=self.sticker, anchor="center", tags="chrome")
        self.tag_lower("chrome")
        self.coords(self._win, x1 + self.PAD, y1 + self.TITLE_H + 6)
        if self.expand:
            self.itemconfigure(self._win, width=max(10, x2 - x1 - 2 * self.PAD),
                               height=max(10, y2 - y1 - self.TITLE_H - 6 - self.PAD))
        else:  # the body keeps its natural height, so content changes reach _fit through <Configure>
            self.itemconfigure(self._win, width=max(10, x2 - x1 - 2 * self.PAD))


def tint_title_bar(root: tk.Tk) -> None:
    """Windows 11: paint the OS title bar in the app's pastel colours (harmless elsewhere)."""
    if os.name != "nt":
        return
    try:
        import ctypes
        hwnd = int(root.wm_frame(), 16)
        dwm = ctypes.windll.dwmapi
        for attr, rgb in ((35, PASTEL["pink"]), (36, PALETTE["outline"]), (34, PALETTE["outline"])):
            r_, g_, b_ = int(rgb[1:3], 16), int(rgb[3:5], 16), int(rgb[5:7], 16)
            value = ctypes.c_int((b_ << 16) | (g_ << 8) | r_)
            dwm.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(value), 4)
    except Exception:
        pass


_IMAGE_CACHE: Dict[str, tk.PhotoImage] = {}


def load_image(name: str, size: Optional[int] = None) -> Optional[tk.PhotoImage]:
    """A bundled picture (mascot, moods) as a PhotoImage, or None when it is missing or Tk cannot
    show it. Images are cached for the life of the process: a PhotoImage collected by the garbage
    collector on a worker thread would call into Tk from that thread."""
    data = assets.IMAGES.get(name)
    if not data:
        return None
    img = _IMAGE_CACHE.get(name)
    if img is not None:
        try:
            img.width()
            return img
        except tk.TclError:
            pass  # its interpreter is gone (tests create several roots)
    try:
        img = tk.PhotoImage(data=data)
    except tk.TclError:
        return None
    _IMAGE_CACHE[name] = img
    return img


class ConfirmDialog:
    """Modal 'we are about to send one prompt to Codex' box with a don't-ask-again checkbox."""

    def __init__(self, parent: tk.Misc, title: str, message: str, checkbox: str, ok: str, cancel: str) -> None:
        self.result = (False, False)
        self.win = tk.Toplevel(parent)
        self.win.title(title)
        self.win.configure(bg=PALETTE["outline"])
        self.win.transient(parent.winfo_toplevel())
        self.win.resizable(False, False)
        body = ttk.Frame(self.win, style="Card.TFrame", padding=(22, 18))
        body.pack(fill="both", expand=True, padx=3, pady=3)
        ttk.Label(body, text=title, style="CardTitle.TLabel").pack(anchor="w")
        ttk.Label(body, text=message, style="Card.TLabel", wraplength=460, justify="left").pack(anchor="w", pady=(8, 14))
        self.var_skip = tk.BooleanVar(value=False)
        ttk.Checkbutton(body, text=checkbox, variable=self.var_skip, style="Card.TCheckbutton").pack(anchor="w")
        row = ttk.Frame(body, style="Card.TFrame")
        row.pack(fill="x", pady=(16, 0))
        self.btn_ok = RoundedButton(row, text=ok, command=self._ok, bg=PALETTE["card"], font=(FONT_UI, 10, "bold"),
                                    padx=20, pady=7)
        self.btn_ok.pack(side="right")
        RoundedButton(row, text=cancel, command=self._cancel, kind="secondary", bg=PALETTE["card"],
                      font=(FONT_UI, 10, "bold"), padx=16, pady=7).pack(side="right", padx=(0, 8))
        self.win.bind("<Return>", lambda _e: self._ok())
        self.win.bind("<Escape>", lambda _e: self._cancel())
        self.win.protocol("WM_DELETE_WINDOW", self._cancel)
        self.win.update_idletasks()
        px, py = parent.winfo_rootx(), parent.winfo_rooty()
        pw, ph = parent.winfo_width(), parent.winfo_height()
        w, h = self.win.winfo_reqwidth(), self.win.winfo_reqheight()
        self.win.geometry(f"+{px + max(0, (pw - w) // 2)}+{py + max(0, (ph - h) // 3)}")
        self.win.grab_set()
        self.btn_ok.focus_set()

    def _ok(self) -> None:
        self.result = (True, bool(self.var_skip.get()))
        self.win.destroy()

    def _cancel(self) -> None:
        self.result = (False, False)
        self.win.destroy()

    @classmethod
    def ask(cls, parent: tk.Misc, title: str, message: str, checkbox: str, ok: str, cancel: str):
        dlg = cls(parent, title, message, checkbox, ok, cancel)
        parent.wait_window(dlg.win)
        return dlg.result


class GuideDialog:
    """Friendly first-time explanation of the live monitor tab, with a don't-show-again box."""

    def __init__(self, parent: tk.Misc, title: str, heading: str, body: str, checkbox: str, ok: str) -> None:
        self.skip = False
        self.win = tk.Toplevel(parent)
        self.win.title(title)
        self.win.configure(bg=PALETTE["outline"])
        self.win.transient(parent.winfo_toplevel())
        self.win.resizable(False, False)
        head = tk.Frame(self.win, bg=PASTEL["lavender"])
        head.pack(fill="x", padx=3, pady=(3, 0))
        self.mascot = load_image("mascot_96")
        if self.mascot is not None:
            tk.Label(head, image=self.mascot, bg=PASTEL["lavender"], padx=18, pady=10).pack(side="left")
        tk.Label(head, text=heading, bg=PASTEL["lavender"], fg=PALETTE["outline"], font=(FONT_UI, 13, "bold"),
                 padx=(6 if self.mascot else 22), pady=14, anchor="w", justify="left", wraplength=440).pack(side="left", fill="x")
        frame = ttk.Frame(self.win, style="Card.TFrame", padding=(24, 18))
        frame.pack(fill="both", expand=True, padx=3, pady=(0, 3))
        # one label per paragraph: a blank line between them and the emoji marker hanging on the left
        for para in [p.strip() for p in body.split("\n\n") if p.strip()]:
            row = ttk.Frame(frame, style="Card.TFrame")
            row.pack(fill="x", pady=(0, 10))
            marker, _, text = para.partition("  ")
            ttk.Label(row, text=marker, style="Card.TLabel", font=(FONT_UI, 12), width=3).pack(side="left", anchor="n")
            ttk.Label(row, text=text or marker, style="Card.TLabel", wraplength=470, justify="left",
                      font=(FONT_UI, 10)).pack(side="left", anchor="n", fill="x")
        self.var_skip = tk.BooleanVar(value=False)
        ttk.Checkbutton(frame, text=checkbox, variable=self.var_skip, style="Card.TCheckbutton").pack(anchor="w", pady=(6, 0))
        self.btn_ok = RoundedButton(frame, text=ok, command=self._ok, bg=PALETTE["card"], font=(FONT_UI, 10, "bold"),
                                    padx=24, pady=8)
        self.btn_ok.pack(anchor="e", pady=(14, 0))
        self.win.bind("<Return>", lambda _e: self._ok())
        self.win.bind("<Escape>", lambda _e: self._ok())
        self.win.protocol("WM_DELETE_WINDOW", self._ok)
        self.win.update_idletasks()
        px, py = parent.winfo_rootx(), parent.winfo_rooty()
        pw, ph = parent.winfo_width(), parent.winfo_height()
        w, h = self.win.winfo_reqwidth(), self.win.winfo_reqheight()
        self.win.geometry(f"+{px + max(0, (pw - w) // 2)}+{py + max(0, (ph - h) // 3)}")
        self.btn_ok.focus_set()

    def _ok(self) -> None:
        self.skip = bool(self.var_skip.get())
        self.win.destroy()


def apply_theme(root: tk.Tk) -> None:
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass
    p = PALETTE
    root.configure(bg=p["bg"])
    style.configure(".", background=p["bg"], foreground=p["text"], font=(FONT_UI, 10))
    style.configure("TFrame", background=p["bg"])
    style.configure("Card.TFrame", background=p["card"])
    style.configure("TLabel", background=p["bg"], foreground=p["text"])
    style.configure("Card.TLabel", background=p["card"], foreground=p["text"])
    style.configure("Muted.TLabel", background=p["bg"], foreground=p["muted"])
    style.configure("CardMuted.TLabel", background=p["card"], foreground=p["muted"])
    style.configure("Title.TLabel", background=p["bg"], foreground=p["text"], font=(FONT_UI, 18, "bold"))
    style.configure("CardTitle.TLabel", background=p["card"], foreground=p["accent_dark"], font=(FONT_UI, 11, "bold"))
    style.configure("TCheckbutton", background=p["bg"], foreground=p["text"])
    style.configure("Card.TCheckbutton", background=p["card"], foreground=p["text"])
    style.configure("TButton", padding=(12, 5), background=p["secondary"], foreground=p["secondary_text"], borderwidth=0,
                    bordercolor=p["secondary"], lightcolor=p["secondary"], darkcolor=p["secondary"], relief="flat",
                    font=(FONT_UI, 10, "bold"))
    style.map("TButton", background=[("active", p["secondary_dark"]), ("disabled", p["disabled"])],
              foreground=[("disabled", p["disabled_text"])])
    style.configure("TCombobox", fieldbackground=PASTEL["yellow"], background=PASTEL["yellow"], bordercolor=p["outline"],
                    arrowcolor=p["outline"], padding=4)
    style.configure("TSpinbox", fieldbackground=PASTEL["yellow"], background=PASTEL["yellow"], bordercolor=p["outline"],
                    arrowcolor=p["outline"], padding=4)
    style.configure("Treeview", background=p["card"], fieldbackground=p["card"], foreground=p["text"],
                    rowheight=26, borderwidth=0, font=(FONT_UI, 10))
    style.configure("Treeview.Heading", background=PASTEL["lavender"], foreground=p["outline"], font=(FONT_UI, 9, "bold"),
                    relief="flat", padding=(6, 6))
    style.map("Treeview.Heading", background=[("active", p["head"])])
    style.map("Treeview", background=[("selected", "#dbeafe")], foreground=[("selected", p["text"])])
    style.configure("TProgressbar", troughcolor=PASTEL["pink"], background=p["accent"], borderwidth=0, thickness=8)
    style.layout("TNotebook.Tab", [])  # the app draws its own sticker tabs
    style.configure("TNotebook", background=p["bg"], borderwidth=0, tabmargins=(0, 4, 0, 0))
    style.configure("TNotebook.Tab", background=p["tab"], foreground=p["muted"], padding=(18, 8), borderwidth=0,
                    font=(FONT_UI, 10, "bold"))
    style.map("TNotebook.Tab", background=[("selected", p["accent"])], foreground=[("selected", p["accent_text"])],
              expand=[("selected", (0, 0, 0, 0))])
    style.configure("Treeview", rowheight=28)
    style.configure("TScrollbar", troughcolor=p["bg"], background=p["border"], arrowcolor=p["muted"], borderwidth=0)


class App:
    def __init__(self, root: tk.Tk, lang: str = "en", fake: bool = False, exit_after: Optional[float] = None,
                 update_check: bool = True, auto_update: bool = True, updated_from: Optional[str] = None,
                 confirm: bool = True) -> None:
        self.root = root
        self.settings = load_settings()
        self.lang = lang if lang in STRINGS else "en"
        self.fake = fake
        self.exit_after = exit_after
        self.confirm_before_check = confirm and not bool(self.settings.get("skip_confirm"))
        self.q: "queue.Queue[tuple]" = queue.Queue()
        self.worker: Optional[threading.Thread] = None
        self.cancel: Optional[cmc.Canceller] = None
        self.result: Optional[cmc.CheckResult] = None
        self.live_probes: List[cmc.Probe] = []
        self.last_progress: Optional[tuple] = None
        self.done_secs = 0.0
        self.t0 = 0.0
        self.codex_path: Optional[str] = None
        self.auto_update = auto_update
        self.updating = False
        self.updated_from = updated_from
        self.exe_path = Path(sys.executable)  # the file that gets replaced by a self-update (frozen build)
        self.update_info: Optional[dict] = None
        self.cfg_model, self.cfg_tier, _ = cmc.read_config_values()
        self.guide_shown = False
        self.moods: Dict[str, tk.PhotoImage] = {}
        self.panels: List[RetroPanel] = []
        self.have_mitm = bool(cmc.shutil.which("mitmdump"))
        self.models = listed_models()
        apply_theme(root)
        for name in ("mood_ok", "mood_rerouted", "mood_idle", "mood_error"):
            img = load_image(name + "_56")
            if img is not None:
                self.moods[name] = img
        self._build()
        self._apply_language()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.root.after(100, self._poll)
        if update_check:
            threading.Thread(target=lambda: self.q.put(("update", cmc.check_for_update())), daemon=True).start()

    # ---------------------------------------------------------------- layout
    STICKERS = {"panel_options": "sticker_sparkle", "panel_session": "sticker_sparkle", "brief": "sticker_flower",
                "panel_results": "sticker_leaf", "notes": "sticker_heart"}

    def _card(self, parent: tk.Misc, title_key: str = "panel_options", color: str = "pink", min_height: int = 140,
              **grid) -> ttk.Frame:
        expand = "n" in grid.get("sticky", "") and "s" in grid.get("sticky", "")
        panel = RetroPanel(parent, title=self.s(title_key), color=color, expand=expand, min_height=min_height)
        panel.set_sticker(load_image(self.STICKERS.get(title_key, "sticker_sparkle") + "_26"))
        panel.title_key = title_key  # type: ignore[attr-defined]
        panel.grid(**grid)
        self.panels.append(panel)
        return panel.body

    def _build(self) -> None:
        r = self.root
        p = PALETTE
        r.title(APP_TITLE)
        r.geometry("1180x960")
        r.minsize(1000, 800)
        r.columnconfigure(0, weight=1)
        r.rowconfigure(1, weight=1)

        self.menubar = tk.Menu(r)
        self.help_menu = tk.Menu(self.menubar, tearoff=0)
        self.help_menu.add_command(command=lambda: self.show_help("usage"))
        self.help_menu.add_command(command=lambda: self.show_help("terms"))
        self.help_menu.add_command(command=lambda: self.show_guide(force=True))
        self.help_menu.add_separator()
        self.help_menu.add_command(command=lambda: self.show_help("about"))
        self.menubar.add_cascade(menu=self.help_menu)
        r.configure(menu=self.menubar)
        self.help_windows: Dict[str, tk.Toplevel] = {}

        header = ttk.Frame(r)
        header.grid(row=0, column=0, sticky="ew", padx=18, pady=(8, 2))
        header.columnconfigure(1, weight=1)
        self.img_mascot = load_image("mascot_72")
        if self.img_mascot is not None:
            tk.Label(header, image=self.img_mascot, bg=p["bg"]).grid(row=0, column=0, rowspan=2, padx=(0, 12))
            try:
                icon = load_image("mascot_96")
                if icon is not None:
                    r.iconphoto(True, icon)
                    self.img_icon = icon
            except tk.TclError:
                pass
        self.lbl_title = ttk.Label(header, text=APP_TITLE, style="Title.TLabel")
        self.lbl_title.grid(row=0, column=1, sticky="sw")
        self.img_sparkle = load_image("sticker_sparkle_44")
        if self.img_sparkle is not None:
            tk.Label(header, image=self.img_sparkle, bg=p["bg"]).grid(row=0, column=2, rowspan=2, padx=(12, 0), sticky="e")
        self.lbl_subtitle = ttk.Label(header, style="Muted.TLabel")
        self.lbl_subtitle.grid(row=1, column=1, sticky="nw")

        self.tabbar = ttk.Frame(r)
        self.tabbar.grid(row=1, column=0, sticky="ew", padx=18, pady=(6, 0))
        self.nb = ttk.Notebook(r)
        self.nb.grid(row=2, column=0, sticky="nsew", padx=18, pady=(2, 0))
        r.rowconfigure(1, weight=0)
        r.rowconfigure(2, weight=1)
        page = self.page_check = ttk.Frame(self.nb)
        self.nb.add(page)
        self.page_live = ttk.Frame(self.nb)
        self.nb.add(self.page_live)
        self.tab_btns: Dict[ttk.Frame, RoundedButton] = {}
        for pg in (self.page_check, self.page_live):
            btn = RoundedButton(self.tabbar, kind="tab", bg=p["bg"], padx=22, pady=6, font=(FONT_UI, 10, "bold"),
                                command=lambda pg=pg: self.nb.select(pg))
            btn.pack(side="left", padx=(0, 8))
            self.tab_btns[pg] = btn
        self.guide_window: Optional[tk.Toplevel] = None
        self.nb.bind("<<NotebookTabChanged>>", lambda _e: self._on_tab_changed())
        page.columnconfigure(0, weight=1)
        page.rowconfigure(5, weight=3)
        page.rowconfigure(6, weight=1)

        opts = self._card(page, "panel_options", "lavender", row=1, column=0, sticky="ew", padx=0, pady=(10, 8))
        pad = {"padx": (0, 6), "pady": 2}
        self.lbl_model = ttk.Label(opts, style="CardMuted.TLabel")
        self.lbl_model.grid(row=0, column=0, **pad)
        self.var_model = tk.StringVar(value=self.cfg_model or self.models[0])
        self.cb_model = ttk.Combobox(opts, textvariable=self.var_model, values=self.models, width=22)
        self.cb_model.grid(row=0, column=1, padx=(0, 18), pady=2)
        self.lbl_effort = ttk.Label(opts, style="CardMuted.TLabel")
        self.lbl_effort.grid(row=0, column=2, **pad)
        self.var_effort = tk.StringVar(value="low")
        ttk.Combobox(opts, textvariable=self.var_effort, values=EFFORTS, width=8, state="readonly").grid(row=0, column=3, padx=(0, 18), pady=2)
        self.lbl_repeat = ttk.Label(opts, style="CardMuted.TLabel")
        self.lbl_repeat.grid(row=0, column=4, **pad)
        self.var_repeat = tk.StringVar(value="1")
        vcmd = (r.register(lambda s: s == "" or (s.isdigit() and len(s) <= 2)), "%P")
        ttk.Spinbox(opts, from_=1, to=MAX_REPEAT, textvariable=self.var_repeat, width=4,
                    validate="key", validatecommand=vcmd).grid(row=0, column=5, padx=(0, 18), pady=2)
        self.var_wire = tk.BooleanVar(value=False)
        self.chk_wire = ttk.Checkbutton(opts, variable=self.var_wire, style="Card.TCheckbutton")
        self.chk_wire.grid(row=0, column=6, padx=(0, 18), pady=2)
        if not self.have_mitm:
            self.chk_wire.state(["disabled"])
        self.btn_codex = RoundedButton(opts, command=self.pick_codex, kind="secondary", bg=p["card"], padx=14, pady=4,
                                       font=(FONT_UI, 9, "bold"))
        self.btn_codex.grid(row=0, column=7, padx=(0, 6), pady=2)
        self.var_codex = tk.StringVar()
        ttk.Label(opts, textvariable=self.var_codex, style="CardMuted.TLabel").grid(row=0, column=8, pady=2)

        act = ttk.Frame(page)
        act.grid(row=2, column=0, sticky="ew", padx=0, pady=(2, 4))
        act.columnconfigure(2, weight=1)
        self.btn_check = RoundedButton(act, command=self.start_check, bg=p["bg"], padx=34, pady=10,
                                       font=(FONT_UI, 12, "bold"))
        self.btn_check.grid(row=0, column=0, padx=(0, 10), pady=4)
        self.btn_cancel = RoundedButton(act, command=self.cancel_check, state="disabled", kind="secondary", bg=p["bg"],
                                        padx=18, pady=8, font=(FONT_UI, 10, "bold"))
        self.btn_cancel.grid(row=0, column=1, padx=(0, 12), pady=4)
        self.var_status = tk.StringVar()
        ttk.Label(act, textvariable=self.var_status, style="Muted.TLabel", anchor="w").grid(row=0, column=2, sticky="ew")
        self.progress = ttk.Progressbar(act, mode="indeterminate", length=200)
        self.progress.grid(row=0, column=3, padx=(10, 0))
        self.progress.grid_remove()

        self.banner_frame, self.banner_glyph, self.banner = self._banner(page, row=3)

        brief = self._card(page, "brief", "pink", row=4, column=0, sticky="ew", padx=0, pady=(0, 8))
        brief.columnconfigure(0, weight=1)
        self.lbl_brief_title = ttk.Label(brief, style="CardTitle.TLabel")
        self.lbl_brief = ttk.Label(brief, style="Card.TLabel", justify="left", anchor="w", wraplength=1080)
        self.lbl_brief.grid(row=1, column=0, sticky="ew", pady=(4, 0))
        brief.bind("<Configure>", lambda e: self.lbl_brief.configure(wraplength=max(300, e.width - 30)), add="+")

        table = self._card(page, "panel_results", "mint", 230, row=5, column=0, sticky="nsew", padx=0, pady=(0, 8))
        table.columnconfigure(0, weight=1)
        table.rowconfigure(0, weight=1)
        cols = ("n", "requested", "kind", "served", "status", "created", "verdict", "rid")
        self.tree = ttk.Treeview(table, columns=cols, show="headings", height=5)
        widths = {"n": 36, "requested": 160, "kind": 80, "served": 160, "status": 90, "created": 100, "verdict": 110, "rid": 430}
        for c in cols:
            self.tree.column(c, width=widths[c], minwidth=widths[c], anchor="w", stretch=(c == "rid"))
        for v, (bg, fg, _g) in VERDICT_STYLE.items():
            self.tree.tag_configure(v, background=bg, foreground=fg)
        ysb = ttk.Scrollbar(table, orient="vertical", command=self.tree.yview)
        xsb = ttk.Scrollbar(table, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=ysb.set, xscrollcommand=xsb.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        ysb.grid(row=0, column=1, sticky="ns")
        xsb.grid(row=1, column=0, sticky="ew")

        details = self._card(page, "notes", "yellow", 120, row=6, column=0, sticky="nsew", padx=0, pady=(0, 8))
        details.columnconfigure(0, weight=1)
        details.rowconfigure(1, weight=1)
        self.lbl_notes_title = ttk.Label(details, style="CardTitle.TLabel")
        self.notes = tk.Text(details, height=3, wrap="word", font=(FONT_MONO, 10), state="disabled",
                             bg=PALETTE["card"], fg=PALETTE["text"], relief="flat", bd=0, highlightthickness=0)
        self.notes.grid(row=1, column=0, sticky="nsew", pady=(4, 0))
        nsb = ttk.Scrollbar(details, orient="vertical", command=self.notes.yview)
        self.notes.configure(yscrollcommand=nsb.set)
        nsb.grid(row=1, column=1, sticky="ns")

        bottom = ttk.Frame(page)
        bottom.grid(row=7, column=0, sticky="ew", padx=0, pady=(0, 10))
        small = {"kind": "secondary", "bg": p["bg"], "padx": 16, "pady": 6, "font": (FONT_UI, 10, "bold")}
        self.btn_copy = RoundedButton(bottom, command=self.copy_report, state="disabled", **small)
        self.btn_copy.pack(side="left", padx=(0, 8))
        self.btn_json = RoundedButton(bottom, command=self.save_json, state="disabled", **small)
        self.btn_json.pack(side="left", padx=(0, 8))
        self.btn_logs = RoundedButton(bottom, command=self.open_logs, state="disabled", **small)
        self.btn_logs.pack(side="left", padx=(0, 8))

        self._build_live(self.page_live)

        foot = ttk.Frame(r)
        foot.grid(row=3, column=0, sticky="ew", padx=18, pady=(6, 10))
        r.after(50, lambda: tint_title_bar(r))
        self.lbl_version = tk.Label(foot, text=f"v{cmc.__version__}", bg=p["bg"], fg=p["muted"], font=(FONT_UI, 9))
        self.lbl_version.pack(side="right", padx=(8, 0))
        try:
            self.github_icon = tk.PhotoImage(master=self.root, data=GITHUB_ICON_PNG_B64)
        except tk.TclError:  # very old Tk without PNG support: text-only link
            self.github_icon = None
        self.link_github = tk.Label(foot, text="GitHub", image=self.github_icon, compound="left",
                                    bg=p["bg"], fg=p["accent"], cursor="hand2", padx=4, font=(FONT_UI, 9))
        self.link_github.pack(side="right", padx=6)
        self.link_github.bind("<Button-1>", lambda _e: self.open_repo())
        self.btn_lang = RoundedButton(foot, command=self.toggle_language, kind="secondary", bg=p["bg"], padx=16, pady=6,
                                      font=(FONT_UI, 10, "bold"))
        self.btn_lang.pack(side="right", padx=4)

    def _banner(self, parent: tk.Misc, row: int):
        outer = tk.Frame(parent, bg=PALETTE["outline"], bd=0)
        outer.grid(row=row, column=0, sticky="ew", padx=0, pady=(4, 8))
        frame = tk.Frame(outer, bg=VERDICT_STYLE["IDLE"][0], bd=0)
        frame.pack(fill="x", padx=2, pady=2)
        glyph = tk.Label(frame, text=VERDICT_STYLE["IDLE"][2], font=(FONT_UI, 18, "bold"),
                         bg=VERDICT_STYLE["IDLE"][0], fg=VERDICT_STYLE["IDLE"][1], padx=14, pady=8)
        glyph.pack(side="left")
        label = tk.Label(frame, font=(FONT_UI, 15, "bold"), anchor="w",
                         bg=VERDICT_STYLE["IDLE"][0], fg=VERDICT_STYLE["IDLE"][1], padx=4, pady=10)
        label.pack(side="left", fill="x", expand=True)
        return frame, glyph, label

    def _build_live(self, page: ttk.Frame) -> None:
        p = PALETTE
        page.columnconfigure(0, weight=1)
        page.rowconfigure(5, weight=3)
        page.rowconfigure(6, weight=1)

        opts = self._card(page, "panel_session", "lavender", row=1, column=0, sticky="ew", padx=0, pady=(10, 8))
        opts.columnconfigure(1, weight=1)
        self.lbl_live_cfg = ttk.Label(opts, style="CardMuted.TLabel")
        self.lbl_live_cfg.grid(row=0, column=0, sticky="w", padx=(0, 10), pady=2)
        self.var_live_cfg = tk.StringVar()
        ttk.Label(opts, textvariable=self.var_live_cfg, style="Card.TLabel").grid(row=0, column=1, sticky="w", pady=2)
        self.lbl_live_folder = ttk.Label(opts, style="CardMuted.TLabel")
        self.lbl_live_folder.grid(row=1, column=0, sticky="w", padx=(0, 10), pady=2)
        self.live_dir = str(self.settings.get("live_dir") or Path.home())
        if not os.path.isdir(self.live_dir):
            self.live_dir = str(Path.home())
        self.var_live_dir = tk.StringVar(value=cmc.display_path(self.live_dir))
        ttk.Label(opts, textvariable=self.var_live_dir, style="Card.TLabel").grid(row=1, column=1, sticky="w", pady=2)
        self.btn_live_dir = RoundedButton(opts, command=self.pick_live_dir, kind="secondary", bg=p["card"], padx=14, pady=4,
                                          font=(FONT_UI, 9, "bold"))
        self.btn_live_dir.grid(row=1, column=2, sticky="e", pady=2)

        act = ttk.Frame(page)
        act.grid(row=2, column=0, sticky="ew", padx=0, pady=(2, 4))
        act.columnconfigure(2, weight=1)
        self.btn_live_start = RoundedButton(act, command=self.start_live, bg=p["bg"], padx=34, pady=10,
                                            font=(FONT_UI, 12, "bold"))
        self.btn_live_start.grid(row=0, column=0, padx=(0, 10), pady=4)
        self.btn_live_stop = RoundedButton(act, command=self.stop_live, state="disabled", kind="secondary", bg=p["bg"],
                                           padx=18, pady=8, font=(FONT_UI, 10, "bold"))
        self.btn_live_stop.grid(row=0, column=1, padx=(0, 12), pady=4)
        self.var_live_status = tk.StringVar()
        ttk.Label(act, textvariable=self.var_live_status, style="Muted.TLabel", anchor="w").grid(row=0, column=2, sticky="ew")
        self.live_progress = ttk.Progressbar(act, mode="indeterminate", length=200)
        self.live_progress.grid(row=0, column=3, padx=(10, 0))
        self.live_progress.grid_remove()

        self.live_banner_frame, self.live_banner_glyph, self.live_banner = self._banner(page, row=3)

        brief = self._card(page, "brief", "pink", row=4, column=0, sticky="ew", padx=0, pady=(0, 8))
        brief.columnconfigure(0, weight=1)
        self.lbl_live_brief_title = ttk.Label(brief, style="CardTitle.TLabel")
        self.lbl_live_brief = ttk.Label(brief, style="Card.TLabel", justify="left", anchor="w", wraplength=1080)
        self.lbl_live_brief.grid(row=1, column=0, sticky="ew", pady=(4, 0))
        brief.bind("<Configure>", lambda e: self.lbl_live_brief.configure(wraplength=max(300, e.width - 30)), add="+")

        table = self._card(page, "panel_results", "mint", 230, row=5, column=0, sticky="nsew", padx=0, pady=(0, 8))
        table.columnconfigure(0, weight=1)
        table.rowconfigure(0, weight=1)
        cols = ("n", "time", "requested", "kind", "served", "status", "verdict", "rid")
        self.live_tree = ttk.Treeview(table, columns=cols, show="headings", height=5)
        widths = {"n": 36, "time": 80, "requested": 160, "kind": 80, "served": 160, "status": 110, "verdict": 110, "rid": 400}
        for c in cols:
            self.live_tree.column(c, width=widths[c], minwidth=widths[c], anchor="w", stretch=(c == "rid"))
        for v, (bg, fg, _g) in VERDICT_STYLE.items():
            self.live_tree.tag_configure(v, background=bg, foreground=fg)
        ysb = ttk.Scrollbar(table, orient="vertical", command=self.live_tree.yview)
        xsb = ttk.Scrollbar(table, orient="horizontal", command=self.live_tree.xview)
        self.live_tree.configure(yscrollcommand=ysb.set, xscrollcommand=xsb.set)
        self.live_tree.grid(row=0, column=0, sticky="nsew")
        ysb.grid(row=0, column=1, sticky="ns")
        xsb.grid(row=1, column=0, sticky="ew")

        details = self._card(page, "notes", "yellow", 120, row=6, column=0, sticky="nsew", padx=0, pady=(0, 8))
        details.columnconfigure(0, weight=1)
        details.rowconfigure(1, weight=1)
        self.lbl_live_notes_title = ttk.Label(details, style="CardTitle.TLabel")
        self.live_notes = tk.Text(details, height=3, wrap="word", font=(FONT_MONO, 10), state="disabled",
                                  bg=PALETTE["card"], fg=PALETTE["text"], relief="flat", bd=0, highlightthickness=0)
        self.live_notes.grid(row=1, column=0, sticky="nsew", pady=(4, 0))
        nsb = ttk.Scrollbar(details, orient="vertical", command=self.live_notes.yview)
        self.live_notes.configure(yscrollcommand=nsb.set)
        nsb.grid(row=1, column=1, sticky="ns")

        bottom = ttk.Frame(page)
        bottom.grid(row=7, column=0, sticky="ew", padx=0, pady=(0, 10))
        small = {"kind": "secondary", "bg": p["bg"], "padx": 16, "pady": 6, "font": (FONT_UI, 10, "bold")}
        self.btn_live_copy = RoundedButton(bottom, command=self.copy_live_report, state="disabled", **small)
        self.btn_live_copy.pack(side="left", padx=(0, 8))
        self.btn_live_clear = RoundedButton(bottom, command=self.clear_live, state="disabled", **small)
        self.btn_live_clear.pack(side="left", padx=(0, 8))

        self.monitor: Optional[live.LiveMonitor] = None
        self.agg = live.LiveAggregator()
        self.live_items: Dict[int, str] = {}
        self.live_lines: List[str] = []
        self.live_ended: Optional[str] = None  # "stopped" | "exit:<rc>" after a session ended
        self.launcher = fake_launcher if self.fake else live.launch_in_terminal
        self._cfg_mtime: Optional[float] = None
        self.cfg_live: tuple = (None, None, "")
        self._refresh_config(first=True)

    def s(self, key: str, **kw) -> str:
        return STRINGS[self.lang][key].format(**kw)

    def _set_banner(self, key: str, text: str, target: str = "check") -> None:
        bg, fg, glyph = VERDICT_STYLE.get(key, VERDICT_STYLE["IDLE"])
        if target == "live":
            frame, glabel, label = self.live_banner_frame, self.live_banner_glyph, self.live_banner
        else:
            frame, glabel, label = self.banner_frame, self.banner_glyph, self.banner
        frame.configure(bg=bg)
        mood = self.moods.get(VERDICT_MOOD.get(key, "mood_idle"))
        if mood is not None:
            glabel.configure(image=mood, text="", bg=bg, fg=fg, padx=10, pady=2)
        else:
            glabel.configure(text=glyph, bg=bg, fg=fg)
        label.configure(text=text, bg=bg, fg=fg)

    def _apply_language(self) -> None:
        m = MENU[self.lang]
        self.menubar.entryconfigure(1, label=m["help"])
        self.help_menu.entryconfigure(0, label=m["usage"])
        self.help_menu.entryconfigure(1, label=m["terms"])
        self.help_menu.entryconfigure(2, label=m["guide"])
        self.help_menu.entryconfigure(4, label=m["about"])
        for kind, win in list(self.help_windows.items()):
            if win.winfo_exists():
                self._fill_help(win, kind)
        self.lbl_subtitle.configure(text=self.s("subtitle"))
        self.lbl_model.configure(text=self.s("model"))
        self.lbl_effort.configure(text=self.s("effort"))
        self.lbl_repeat.configure(text=self.s("repeat"))
        self.chk_wire.configure(text=self.s("wire") if self.have_mitm else self.s("no_mitm"))
        self.btn_codex.configure(text=self.s("codex_btn"))
        if not self.codex_path:
            self.var_codex.set(self.s("codex_auto"))
        self.btn_check.configure(text=self.s("check"))
        self.btn_cancel.configure(text=self.s("cancel"))
        self.btn_copy.configure(text=self.s("copy"))
        self.btn_json.configure(text=self.s("save_json"))
        self.btn_logs.configure(text=self.s("open_logs"))
        self.btn_lang.configure(text=self.s("lang"))
        self.lbl_notes_title.configure(text=self.s("notes"))
        self.lbl_brief_title.configure(text=self.s("brief"))
        for panel in self.panels:
            panel.set_title(self.s(panel.title_key))  # type: ignore[attr-defined]
        self.nb.tab(self.page_check, text=self.s("tab_check"))
        self.nb.tab(self.page_live, text=self.s("tab_live"))
        for page, btn in self.tab_btns.items():
            btn.configure(text=self.nb.tab(page, "text"))
        self.lbl_live_cfg.configure(text=self.s("live_cfg"))
        self.lbl_live_folder.configure(text=self.s("live_folder"))
        self.btn_live_dir.configure(text=self.s("live_folder_btn"))
        self.btn_live_start.configure(text=self.s("live_start"))
        self.btn_live_stop.configure(text=self.s("live_stop"))
        self.btn_live_copy.configure(text=self.s("live_copy"))
        self.btn_live_clear.configure(text=self.s("live_clear"))
        self.lbl_live_brief_title.configure(text=self.s("brief"))
        self.lbl_live_notes_title.configure(text=self.s("notes"))
        for c, key in (("n", "col_n"), ("time", "col_time"), ("requested", "col_requested"), ("kind", "col_kind"),
                       ("served", "col_served"), ("status", "col_status"), ("verdict", "col_verdict"), ("rid", "col_id")):
            self.live_tree.heading(c, text=self.s(key))
        self._show_config()
        self.live_tree.delete(*self.live_tree.get_children())
        self.live_items.clear()
        for row in self.agg.rows:
            self._render_live_row(row)
        self._render_live_summary()
        self._show_live_status()
        if self.update_info:
            self.show_update(self.update_info)
        for c, key in (("n", "col_n"), ("requested", "col_requested"), ("kind", "col_kind"), ("served", "col_served"),
                       ("status", "col_status"), ("created", "col_created"), ("verdict", "col_verdict"), ("rid", "col_id")):
            self.tree.heading(c, text=self.s(key))
        if self.updating:
            pass  # the update status line is rewritten by the next progress message
        elif self.result is not None:
            self._render_result(self.result)
        elif self.worker is not None:  # mid-run: relabel what is on screen so far
            self._set_banner("RUNNING", self.s("banner_running"))
            self.tree.delete(*self.tree.get_children())
            for p in self.live_probes:
                self._add_probe_rows(p)
            if self.last_progress is not None:
                self._show_progress(*self.last_progress)
        else:
            self.var_status.set(self.s("updated", current=cmc.__version__) if self.updated_from else self.s("idle"))
            self._set_banner("IDLE", self.s("banner_idle"))
            self.lbl_brief.configure(text=self.s("brief_idle"))

    def toggle_language(self) -> None:
        self.lang = "ko" if self.lang == "en" else "en"
        self.settings["lang"] = self.lang
        save_settings(self.settings)
        self._apply_language()

    # ------------------------------------------------------------------- help
    def help_text(self, kind: str) -> str:
        table = {"usage": HELP_USAGE, "terms": HELP_TERMS, "about": HELP_ABOUT}[kind]
        return table[self.lang].format(version=cmc.__version__, repo=REPO_URL)

    def show_help(self, kind: str) -> tk.Toplevel:
        win = self.help_windows.get(kind)
        if win is not None and win.winfo_exists():
            self._fill_help(win, kind)
            win.lift()
            return win
        win = tk.Toplevel(self.root)
        win.configure(bg=PALETTE["bg"])
        win.geometry("760x560" if kind != "about" else "640x300")
        win.transient(self.root)
        frame = ttk.Frame(win, padding=8)
        frame.pack(fill="both", expand=True)
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        text = tk.Text(frame, wrap="word", font=(FONT_UI, 10), state="disabled", bg=PALETTE["card"],
                       fg=PALETTE["text"], relief="flat", padx=12, pady=10, spacing1=2, spacing3=2)
        text.grid(row=0, column=0, sticky="nsew")
        sb = ttk.Scrollbar(frame, orient="vertical", command=text.yview)
        text.configure(yscrollcommand=sb.set)
        sb.grid(row=0, column=1, sticky="ns")
        btn = RoundedButton(frame, command=win.destroy, kind="secondary", bg=PALETTE["bg"], padx=20, pady=7,
                            font=(FONT_UI, 10, "bold"))
        btn.grid(row=1, column=0, columnspan=2, pady=(8, 0))
        win.help_text = text  # type: ignore[attr-defined]
        win.help_button = btn  # type: ignore[attr-defined]
        self.help_windows[kind] = win
        self._fill_help(win, kind)
        return win

    def _fill_help(self, win: tk.Toplevel, kind: str) -> None:
        win.title(f"{APP_TITLE} - {MENU[self.lang][kind]}")
        text = win.help_text  # type: ignore[attr-defined]
        text.configure(state="normal")
        text.delete("1.0", "end")
        text.insert("1.0", self.help_text(kind))
        text.configure(state="disabled")
        win.help_button.configure(text=MENU[self.lang]["close"])  # type: ignore[attr-defined]

    # ----------------------------------------------------------------- actions
    def options(self) -> cmc.CheckOptions:
        try:
            repeat = int(self.var_repeat.get())
        except (tk.TclError, ValueError):
            repeat = 1
        repeat = min(MAX_REPEAT, max(1, repeat))
        self.var_repeat.set(str(repeat))
        return cmc.CheckOptions(models=[self.var_model.get().strip() or cmc.FALLBACK_MODEL], control=None,
                                effort=self.var_effort.get() or "low", repeat=repeat,
                                wire=bool(self.var_wire.get()) and self.have_mitm, codex=self.codex_path)

    def pick_codex(self) -> None:
        kinds = [("codex", "codex.exe codex codex.cmd"), ("all files", "*")] if os.name == "nt" else [("all files", "*")]
        path = filedialog.askopenfilename(title=self.s("codex_pick_title"), filetypes=kinds)
        if path:
            self.codex_path = path
            self.var_codex.set(Path(path).name)  # full path is shown in the details after a run

    def start_check(self, confirm: Optional[bool] = None) -> None:
        if self.worker is not None or self.updating:
            return
        opts = self.options()
        if self.confirm_before_check if confirm is None else confirm:
            ok, skip = ConfirmDialog.ask(self.root, self.s("confirm_title"),
                                         self.s("confirm_body", model=opts.models[0], n=2 * opts.repeat),
                                         self.s("confirm_skip"), self.s("confirm_ok"), self.s("confirm_cancel"))
            if skip:
                self.settings["skip_confirm"] = True
                save_settings(self.settings)
                self.confirm_before_check = False
            if not ok:
                return
        self.cancel = cmc.Canceller()
        self.result = None
        self.live_probes = []
        self.last_progress = None
        self.t0 = time.time()
        self._set_running(True)
        self.tree.delete(*self.tree.get_children())
        self._set_notes("")
        self._set_banner("RUNNING", self.s("banner_running"))
        self.lbl_brief.configure(text=self.s("brief_running"))
        self.var_status.set(self.s("starting", version="..."))
        cancel = self.cancel

        def work() -> None:
            try:
                res = cmc.run_check(opts, progress=lambda ev, info: self.q.put(("progress", ev, info)), cancel=cancel)
                self.q.put(("done", res))
            except Exception as e:  # keep the UI alive whatever happens in the worker
                self.q.put(("fatal", f"{type(e).__name__}: {e}"))

        self.worker = threading.Thread(target=work, daemon=True)
        self.worker.start()

    def cancel_check(self) -> None:
        if self.cancel is not None:
            self.var_status.set(self.s("cancelling"))
            self.btn_cancel.configure(state="disabled")
            self.cancel.cancel()

    def on_close(self) -> None:
        """Window closed: stop codex (and mitmdump) instead of leaving them running."""
        if self.monitor is not None and self.monitor.codex_running() and self.exit_after is None:
            if not messagebox.askyesno(APP_TITLE, self.s("live_close_confirm"), parent=self.root):
                return
        if self.monitor is not None:
            self.monitor.stop()
            self.monitor = None
        if self.worker is not None and self.cancel is not None:
            self.cancel.cancel()
            self.worker.join(timeout=10)
        self.root.destroy()

    def _set_running(self, running: bool) -> None:
        self.btn_check.configure(state="disabled" if running else "normal")
        self.btn_cancel.configure(state="normal" if running else "disabled")
        have = self.result is not None and not running
        self.btn_copy.configure(state="normal" if have else "disabled")
        usable = have and self.result is not None and self.result.error is None and self.result.outdir is not None
        self.btn_json.configure(state="normal" if usable else "disabled")
        self.btn_logs.configure(state="normal" if usable else "disabled")
        if running:
            self.progress.grid()
            self.progress.start(12)
        else:
            self.progress.stop()
            self.progress.grid_remove()

    def _poll(self) -> None:
        try:
            while True:
                msg = self.q.get_nowait()
                self._handle(msg)
        except queue.Empty:
            pass
        except Exception as e:  # never let one bad message stop the loop or freeze the buttons
            self._set_notes(f"{type(e).__name__}: {e}")
            if self.worker is not None and not self.worker.is_alive():
                self.worker = None  # only re-enable Check when nothing is running any more
                self._set_running(False)
        try:
            self._poll_live()
        except Exception as e:
            self._live_note(f"{type(e).__name__}: {e}")
        finally:
            self.root.after(100, self._poll)

    # ------------------------------------------------------------ live monitor
    def _on_tab_changed(self) -> None:
        current = self.nb.select()
        for pg, btn in self.tab_btns.items():
            btn.configure(kind="tab_selected" if str(pg) == current else "tab")
        if current == str(self.page_live):
            self.show_guide()

    def show_guide(self, force: bool = False) -> Optional[tk.Toplevel]:
        """The friendly explanation of the live tab: once per install unless asked for again."""
        if not force and (self.settings.get("skip_live_guide") or self.guide_shown):
            return None
        if self.guide_window is not None and self.guide_window.winfo_exists():
            self.guide_window.lift()
            return self.guide_window
        self.guide_shown = True
        dlg = GuideDialog(self.root, self.s("guide_title"), self.s("guide_heading"), self.s("guide_body"),
                          self.s("guide_skip"), self.s("guide_ok"))
        self.guide_window = dlg.win

        def closed(_e=None) -> None:
            if dlg.skip:
                self.settings["skip_live_guide"] = True
                save_settings(self.settings)

        dlg.win.bind("<Destroy>", closed)
        return dlg.win

    def _refresh_config(self, first: bool = False) -> None:
        """Mirror model / effort from ~/.codex/config.toml; re-read whenever the file changes."""
        mtime = live.config_mtime()
        if first or mtime != self._cfg_mtime:
            self._cfg_mtime = mtime
            self.cfg_live = live.read_config_model_effort()
            self._show_config()
        self.root.after(2000, self._refresh_config)

    def _show_config(self) -> None:
        model, effort, source = self.cfg_live
        if model:
            self.var_live_cfg.set(self.s("live_cfg_value", model=model, effort=effort or "default", source=source))
        else:
            self.var_live_cfg.set(self.s("live_cfg_none"))

    def pick_live_dir(self) -> None:
        path = filedialog.askdirectory(title=self.s("live_folder_title"), initialdir=self.live_dir, mustexist=True)
        if path:
            self.live_dir = path
            self.var_live_dir.set(cmc.display_path(path))
            self.settings["live_dir"] = path
            save_settings(self.settings)

    def start_live(self, confirm: Optional[bool] = None) -> None:
        if self.monitor is not None or self.updating:
            return
        if not crp.have_crypto():
            self.var_live_status.set(self.s("live_needs_crypto"))
            self._live_note(self.s("live_needs_crypto"))
            return
        ask = (confirm if confirm is not None else self.confirm_before_check) and not self.settings.get("skip_confirm_live")
        if ask:
            ok, skip = ConfirmDialog.ask(self.root, self.s("confirm_live_title"), self.s("confirm_live_body"),
                                         self.s("confirm_skip"), self.s("confirm_live_ok"), self.s("confirm_cancel"))
            if skip:
                self.settings["skip_confirm_live"] = True
                save_settings(self.settings)
            if not ok:
                return
        codex, how = cmc.find_codex(self.codex_path)
        if not codex:
            self.var_live_status.set(self.s("live_failed"))
            self._live_note(f"codex binary not found ({how}). " + self.s("codex_hint"))
            return
        self.clear_live()
        mon = live.LiveMonitor(codex, self.live_dir, launcher=self.launcher)
        try:
            mon.start()
        except Exception as e:
            self.var_live_status.set(self.s("live_failed"))
            self._live_note(f"{type(e).__name__}: {e}")
            return
        self.monitor = mon
        self.live_ended = None
        self._live_note(f"{self.s('codex')}: {' '.join(cmc.display_path(c) for c in codex)} ({how})")
        self._set_live_running(True)
        self._show_live_status()
        self._render_live_summary()

    def stop_live(self, ask: bool = True) -> None:
        mon = self.monitor
        if mon is None:
            return
        if ask and mon.codex_running():
            if not messagebox.askyesno(APP_TITLE, self.s("live_stop_confirm"), parent=self.root):
                return
        self._end_live("stopped")

    def _end_live(self, how: str) -> None:
        mon = self.monitor
        if mon is None:
            return
        mon.stop()
        self.monitor = None
        self.live_ended = how
        self._set_live_running(False)
        self._show_live_status()
        self._render_live_summary()

    def _set_live_running(self, running: bool) -> None:
        self.btn_live_start.configure(state="disabled" if running else "normal")
        self.btn_live_stop.configure(state="normal" if running else "disabled")
        self.btn_live_dir.configure(state="disabled" if running else "normal")
        have = bool(self.agg.rows) or bool(self.live_lines)
        self.btn_live_copy.configure(state="normal" if self.agg.rows else "disabled")
        self.btn_live_clear.configure(state="normal" if have and not running else "disabled")
        if running:
            self.live_progress.grid()
            self.live_progress.start(12)
        else:
            self.live_progress.stop()
            self.live_progress.grid_remove()

    def _show_live_status(self) -> None:
        mon = self.monitor
        if mon is not None and mon.proxy is not None:
            pid = (mon.proc.pid if mon.proc is not None else 0) or "?"
            self.var_live_status.set(self.s("live_running", pid=pid, port=mon.proxy.port))
        elif self.live_ended is None:
            self.var_live_status.set(self.s("live_idle"))
        elif self.live_ended.startswith("exit:"):
            self.var_live_status.set(self.s("live_codex_exit", rc=self.live_ended[5:]))
        else:
            self.var_live_status.set(self.s("live_stopped"))

    def _poll_live(self) -> None:
        mon = self.monitor
        if mon is None:
            return
        changed = False
        exit_code: Optional[int] = None
        while True:
            try:
                ev = mon.events.get_nowait()
            except queue.Empty:
                break
            kind = ev[0]
            if kind == "message":
                for name, info in self.agg.feed(ev[1]):
                    if name == "row":
                        self._render_live_row(info["row"])
                        changed = True
                    elif name == "rate_limits":
                        changed = True
            elif kind == "ws_open":
                self.agg.note_hint(ev[1]["conn"], ev[1].get("routing_hint", ""))
            elif kind == "notice":
                self._live_note(ev[1])
            elif kind == "codex_exit":
                exit_code = ev[1]  # keep draining: frames decoded just before the exit are still queued
        if changed:
            self._render_live_summary()
            self.btn_live_copy.configure(state="normal")
        if exit_code is not None:
            self._live_note(self.s("live_codex_exit", rc=exit_code))
            self._end_live(f"exit:{exit_code}")

    def _render_live_row(self, row: "live.LiveRow") -> None:
        kind_name = {"warmup": self.s("kind_warmup"), "turn": self.s("kind_turn"), "error": "-"}
        v = row.verdict()
        values = (row.n, time.strftime("%H:%M:%S", time.localtime(row.first_seen)), row.requested or "?",
                  kind_name.get(row.kind, row.kind), row.served or "-", row.status or row.error_code or "-", v,
                  row.response_id)
        item = self.live_items.get(row.n)
        if item is None:
            self.live_items[row.n] = self.live_tree.insert("", "end", values=values, tags=(v,))
            self.live_tree.see(self.live_items[row.n])
        else:
            self.live_tree.item(item, values=values, tags=(v,))

    def _render_live_summary(self) -> None:
        agg = self.agg
        running = self.monitor is not None
        overall = agg.overall()
        counts = agg.counts()
        total = len(agg.rows)
        requested = ", ".join(sorted({r.requested for r in agg.rows if r.requested})) or "?"
        if overall == "REROUTED":
            bad = counts.get("REROUTED", 0)
            served = sorted({m for r in agg.rows for m in r.other_models()})
            self._set_banner("REROUTED", self.s("banner_live_rerouted", pairs="; ".join(agg.pairs()), bad=bad, total=total), "live")
            brief = [self.s("brief_live_rerouted", bad=bad, total=total, served=", ".join(served) or "?", requested=requested)]
            acct = self._live_account_sentence()
            if acct:
                brief.append(acct)
            brief.append(self.s("brief_advice_rerouted"))
        elif overall == "OK":
            self._set_banner("ok", self.s("banner_live_ok", n=counts.get("ok", 0)), "live")
            brief = [self.s("brief_live_ok", n=counts.get("ok", 0))]
            acct = self._live_account_sentence()
            if acct:
                brief.append(acct)
        elif overall == "UNSUPPORTED":
            self._set_banner("UNSUPPORTED", self.s("banner_live_unsupported", models=requested), "live")
            brief = [self.s("brief_live_unsupported", models=requested), self.s("brief_advice_unsupported")]
        elif overall == "ERROR":
            errs = sorted({(r.error_code or (r.record.error_code if r.record else None) or "?") for r in agg.rows
                           if r.verdict() in ("ERROR", "UNKNOWN")})
            self._set_banner("ERROR", self.s("banner_live_error", n=total), "live")
            brief = [self.s("brief_live_error", errors=", ".join(errs))]
        elif running:
            self._set_banner("RUNNING", self.s("banner_live_waiting"), "live")
            brief = [self.s("brief_live_running"), self.s("brief_live_waiting")]
        else:
            self._set_banner("IDLE", self.s("banner_live_idle"), "live")
            brief = [self.s("brief_live_idle")]
        if running and overall in ("REROUTED", "OK", "UNSUPPORTED", "ERROR"):
            brief.insert(0, self.s("brief_live_running"))
        self.lbl_live_brief.configure(text=" ".join(brief))

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

    def _live_note(self, text: str) -> None:
        self.live_lines.append(f"{time.strftime('%H:%M:%S')}  {text}")
        self.live_lines = self.live_lines[-200:]
        self.live_notes.configure(state="normal")
        self.live_notes.delete("1.0", "end")
        self.live_notes.insert("1.0", "\n".join(self.live_lines))
        self.live_notes.see("end")
        self.live_notes.configure(state="disabled")

    def copy_live_report(self) -> None:
        self.root.clipboard_clear()
        self.root.clipboard_append(self.agg.report())
        self.var_live_status.set(self.s("copied"))

    def clear_live(self) -> None:
        if self.monitor is not None:
            return
        self.agg = live.LiveAggregator()
        self.live_items.clear()
        self.live_tree.delete(*self.live_tree.get_children())
        self.live_lines = []
        self.live_notes.configure(state="normal")
        self.live_notes.delete("1.0", "end")
        self.live_notes.configure(state="disabled")
        self.live_ended = None
        self._set_live_running(False)
        self._show_live_status()
        self._render_live_summary()

    def _handle(self, msg: tuple) -> None:
        if msg[0] == "progress":
            _, ev, info = msg
            if ev == "probe_done":
                self.live_probes.append(info["probe"])
                self._add_probe_rows(info["probe"])
            else:
                self.last_progress = (ev, info)
                self._show_progress(ev, info)
        elif msg[0] == "update":
            self.show_update(msg[1])
        elif msg[0] == "update_progress":
            _, done, total, new = msg
            mb = f"{done / 1e6:.1f}/{total / 1e6:.1f}" if total else f"{done / 1e6:.1f}"
            self.var_status.set(self.s("update_downloading", new=new, mb=mb))
            if total:
                self.progress.configure(mode="determinate", maximum=total, value=done)
        elif msg[0] == "update_ready":
            _, new_path, new = msg
            self.var_status.set(self.s("update_restarting", new=new))
            self.root.update_idletasks()
            try:
                cmc.launch_replacer(self.exe_path, new_path, ["--updated-from", cmc.__version__, "--lang", self.lang])
            except Exception as e:
                self._update_failed(str(e), new)
                return
            self.root.after(300, self.root.destroy)
        elif msg[0] == "update_failed":
            _, err, new = msg
            self._update_failed(err, new)
        elif msg[0] in ("done", "fatal"):
            self.worker = None
            self.done_secs = round(time.time() - self.t0, 1)
            self.result = msg[1] if msg[0] == "done" else cmc.CheckResult(error=msg[1])
            self._set_running(False)
            self.show_result(self.result)
            if self.exit_after is not None:
                self.root.after(int(self.exit_after * 1000), self.root.destroy)

    def _show_progress(self, ev: str, info: dict) -> None:
        if ev == "start":
            self.var_status.set(self.s("starting", version=info["codex_version"]))
        elif ev == "probe_start":
            self.var_status.set(self.s("running", i=info["i"], n=info["n"], model=info["model"], effort=info["effort"]))

    # ----------------------------------------------------------------- output
    def _add_probe_rows(self, p: cmc.Probe) -> None:
        kind_name = {"warmup": self.s("kind_warmup"), "turn": self.s("kind_turn")}
        if not p.responses and not p.stream_errors:
            v = p.verdict()
            self.tree.insert("", "end", values=(p.index, p.requested, "-", "-", "-", "-", v, "-"), tags=(v,))
        for r in p.responses:
            v = r.verdict(p.requested)
            self.tree.insert("", "end", values=(p.index, p.requested, kind_name.get(r.kind, r.kind), r.model or "?",
                                                r.status or "?", cmc.fmt_time(r.created_at), v, r.response_id), tags=(v,))
        for _code, _msg in p.stream_errors:
            v = "UNSUPPORTED" if cmc.is_unsupported_error(_code, _msg) else "ERROR"
            self.tree.insert("", "end", values=(p.index, p.requested, "-", "-", "-", "-", v, "-"), tags=(v,))

    def _render_result(self, res: cmc.CheckResult) -> None:
        """Table, banner, briefing and details for a finished check (status line untouched)."""
        self.tree.delete(*self.tree.get_children())
        for p in res.probes:
            self._add_probe_rows(p)
        main = [p for p in res.probes if not p.is_control]
        models = ", ".join(sorted({p.requested for p in main})) or "?"
        if res.error:
            text, key = self.s("banner_fatal"), "ERROR"
        elif res.overall == "REROUTED":  # before `cancelled`: a substitution already found is kept
            pairs = []
            for p in res.probes:
                if p.verdict() == "REROUTED":
                    served = sorted({m for r in p.responses for m in r.models_seen if not cmc.models_match(p.requested, m)[0]})
                    pairs.append(f"{p.requested} -> {', '.join(served)}")
            text, key = self.s("banner_rerouted", pairs="; ".join(sorted(set(pairs)))), "REROUTED"
        elif res.cancelled:
            text, key = self.s("banner_cancelled"), "CANCELLED"
        elif res.overall == "UNSUPPORTED":
            plan = next((p.rate_limits.get("plan_type") for p in res.probes if p.rate_limits), None) or "?"
            text, key = self.s("banner_unsupported", models=models, plan=plan), "UNSUPPORTED"
        elif res.overall == "OK":
            text, key = self.s("banner_ok", models=models), "ok"
        else:
            text, key = self.s("banner_error", models=models), "ERROR"
        if self.fake:
            text += "  " + self.s("fake")
        self._set_banner(key, text)
        self.lbl_brief.configure(text=build_brief(res, self.lang))

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
            lines.extend(res.summary_lines)
            for p in res.probes:
                for r in p.responses:
                    if r.verdict(p.requested) == "ERROR" or r.error_code or r.error_message:
                        lines.append(f"#{p.index} {p.requested}: error {r.error_code}: {r.error_message}")
                for code, msg in p.stream_errors:
                    lines.append(f"#{p.index} {p.requested}: error {code}: {msg}")
                for n in p.notes:
                    lines.append(f"#{p.index} {p.requested}: {n}")
        self._set_notes("\n".join(lines))

    def show_result(self, res: cmc.CheckResult) -> None:
        self._render_result(res)
        if res.error:
            self.var_status.set(self.s("failed"))
        elif res.cancelled:
            self.var_status.set(self.s("cancelled"))
        elif res.outdir:
            self.var_status.set(self.s("done", secs=self.done_secs, dir=cmc.display_path(res.outdir)))
        else:
            self.var_status.set(self.s("idle"))
        self._set_running(False)

    def _set_notes(self, text: str) -> None:
        self.notes.configure(state="normal")
        self.notes.delete("1.0", "end")
        self.notes.insert("1.0", text)
        self.notes.configure(state="disabled")

    def copy_report(self) -> None:
        if self.result is None:
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(self.result.report(full_ids=True))
        self.var_status.set(self.s("copied"))

    def save_json(self) -> None:
        if self.result is None or self.result.error:
            return
        path = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("JSON", "*.json")],
                                            initialfile="codex-routing-detector.json")
        if path:
            Path(path).write_text(json.dumps(self.result.json(), indent=2), encoding="utf-8")
            self.var_status.set(self.s("saved", path=cmc.display_path(path)))

    def open_logs(self) -> None:
        if self.result is not None and self.result.outdir:
            open_folder(self.result.outdir)

    def open_repo(self) -> None:
        import webbrowser
        webbrowser.open(REPO_URL)

    # ----------------------------------------------------------------- updates
    def show_update(self, info: Optional[dict]) -> None:
        """Red NEW badge that opens the release page; the frozen build also updates itself."""
        self.update_info = info
        if not info:
            return
        new = info["version"]
        self.lbl_version.configure(text=self.s("update_new", new=new), fg="#b3261e",
                                   font=(FONT_UI, 10, "bold"), cursor="hand2")
        self.lbl_version.bind("<Button-1>", lambda _e: self.open_update())
        if self.updating or self.worker is not None or self.result is not None or self.monitor is not None:
            return  # a check or live session is running or done: do not restart the app under the user
        if not cmc.is_frozen():
            self.var_status.set(self.s("update_pip", new=new, repo=REPO_URL))
        elif not (self.auto_update and info.get("asset") and cmc.dir_writable(self.exe_path.parent)):
            self.var_status.set(self.s("update_manual", new=new))
        else:
            self._start_auto_update(info)

    def _start_auto_update(self, info: dict) -> None:
        self.updating = True
        self.btn_check.configure(state="disabled")
        self.progress.grid()
        asset, new = info["asset"], info["version"]
        dest = self.exe_path.with_name(self.exe_path.stem + ".new.exe")
        self.var_status.set(self.s("update_downloading", new=new, mb=f"{(asset.get('size') or 0) / 1e6:.1f}"))

        def work() -> None:
            try:
                cmc.download_file(asset["url"], dest, progress=lambda d, t: self.q.put(("update_progress", d, t, new)))
                err = cmc.verify_download(dest, asset.get("size"), asset.get("digest"))
                if err:
                    raise RuntimeError(err)
                self.q.put(("update_ready", dest, new))
            except Exception as e:
                try:
                    dest.unlink()
                except OSError:
                    pass
                self.q.put(("update_failed", f"{type(e).__name__}: {e}", new))

        threading.Thread(target=work, daemon=True).start()

    def _update_failed(self, err: str, new: str) -> None:
        self.updating = False
        self.progress.stop()
        self.progress.configure(mode="indeterminate", value=0)
        self.progress.grid_remove()
        self.btn_check.configure(state="normal")
        self.var_status.set(self.s("update_failed", new=new, err=err))

    def open_update(self) -> None:
        import webbrowser
        webbrowser.open((self.update_info or {}).get("url") or cmc.RELEASES_URL)


def _enable_dpi_awareness() -> None:
    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)  # type: ignore[attr-defined]
        except Exception:
            pass


def _report_startup_error(msg: str) -> None:
    if sys.stderr is not None:
        print(msg, file=sys.stderr)
    else:  # frozen --windowed build: no console to print to
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(APP_TITLE, msg)
        root.destroy()


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="codex-routing-detector-gui", add_help=True)
    ap.add_argument("--lang", default=None, choices=["en", "ko"], help="interface language (remembered)")
    ap.add_argument("--fake", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--auto-check", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--auto-live", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--fake-live", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--exit-after", type=float, default=None, help=argparse.SUPPRESS)
    ap.add_argument("--show-help", choices=["usage", "terms", "about"], default=None, help=argparse.SUPPRESS)
    ap.add_argument("--no-update-check", action="store_true",
                    help=f"do not ask api.github.com for a newer release at startup (or set {cmc.NO_UPDATE_ENV}=1)")
    ap.add_argument("--no-auto-update", action="store_true",
                    help="show the NEW badge only; never download and replace this exe by itself")
    ap.add_argument("--updated-from", default=None, help=argparse.SUPPRESS)
    a = ap.parse_args(argv)
    if a.fake_live and not a.fake:
        _report_startup_error("--fake-live is a screenshot mode and needs --fake as well")
        return 1
    if a.fake and not install_fake_runner():
        _report_startup_error("fixtures not found; --fake needs tests/fixtures next to this file")
        return 1
    _enable_dpi_awareness()
    lang = a.lang or load_settings().get("lang") or "en"
    try:
        root = tk.Tk()
        app = App(root, lang=lang, fake=a.fake, exit_after=a.exit_after,
                  update_check=not a.no_update_check and not a.fake,
                  auto_update=not a.no_auto_update, updated_from=a.updated_from)
        if a.auto_check:
            root.after(300, lambda: app.start_check(confirm=False))
        if a.auto_live or a.fake_live:
            root.after(300, lambda: (app.nb.select(app.page_live), app.start_live(confirm=False)))
        if a.fake_live:
            root.after(900, lambda: feed_fake_live(app))
        if a.show_help:
            root.after(300, lambda: app.show_help(a.show_help))
        if a.exit_after is not None and not a.auto_check:
            root.after(int(a.exit_after * 1000), app.on_close)
        root.mainloop()
        if app.monitor is not None:  # the window went away without on_close (destroy from elsewhere)
            app.monitor.stop()
    except Exception as e:  # a windowed build has no console: show the reason instead of dying silently
        _report_startup_error(f"{APP_TITLE} could not start: {type(e).__name__}: {e}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
