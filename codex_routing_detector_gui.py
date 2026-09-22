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

import codex_routing_detector as cmc

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
    },
}

MENU: Dict[str, Dict[str, str]] = {
    "en": {"help": "Help", "usage": "How to use", "terms": "Glossary", "about": "About", "close": "Close"},
    "ko": {"help": "도움말", "usage": "기본 사용법", "terms": "용어 설명", "about": "정보", "close": "닫기"},
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

COST AND PRIVACY

One check sends two requests per model (warm-up plus turn), counted like any other Codex usage.
Logs contain your thread ids, account user id and the probe prompt, but no tokens or cookies; the request body and your home directory are never written.
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

비용과 프라이버시

검사 한 번에 모델당 요청 2개(웜업 + 턴)가 나가며, 일반 Codex 사용량으로 차감됩니다.
로그에는 스레드 ID, 계정 사용자 ID, 검사 프롬프트가 남지만 토큰과 쿠키는 없고, 요청 본문과 홈 폴더 경로는 기록되지 않습니다.
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

VERDICT_COLORS = {
    "ok": ("#e6f4ea", "#1e7e34"), "REROUTED": ("#fdecea", "#b3261e"), "ERROR": ("#fff4e5", "#9a5b00"),
    "UNKNOWN": ("#eeeeee", "#555555"), "NO_DATA": ("#eeeeee", "#555555"), "CANCELLED": ("#eeeeee", "#555555"),
    "UNSUPPORTED": ("#fff4e5", "#9a5b00"),
}


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


class App:
    def __init__(self, root: tk.Tk, lang: str = "en", fake: bool = False, exit_after: Optional[float] = None,
                 update_check: bool = True, auto_update: bool = True, updated_from: Optional[str] = None) -> None:
        self.root = root
        self.lang = lang if lang in STRINGS else "en"
        self.fake = fake
        self.exit_after = exit_after
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
        self.cfg_model, self.cfg_tier, _ = cmc.read_config_values()
        self.have_mitm = bool(cmc.shutil.which("mitmdump"))
        self.models = listed_models()
        self._build()
        self._apply_language()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.root.after(100, self._poll)
        if update_check:
            threading.Thread(target=lambda: self.q.put(("update", cmc.check_for_update())), daemon=True).start()

    # ---------------------------------------------------------------- layout
    def _build(self) -> None:
        r = self.root
        r.title(APP_TITLE)
        r.geometry("1180x680")
        r.minsize(1000, 600)
        r.columnconfigure(0, weight=1)
        r.rowconfigure(3, weight=3)
        r.rowconfigure(4, weight=2)
        pad = {"padx": 6, "pady": 4}

        self.menubar = tk.Menu(r)
        self.help_menu = tk.Menu(self.menubar, tearoff=0)
        self.help_menu.add_command(command=lambda: self.show_help("usage"))
        self.help_menu.add_command(command=lambda: self.show_help("terms"))
        self.help_menu.add_separator()
        self.help_menu.add_command(command=lambda: self.show_help("about"))
        self.menubar.add_cascade(menu=self.help_menu)
        r.configure(menu=self.menubar)
        self.help_windows: Dict[str, tk.Toplevel] = {}

        top = ttk.Frame(r)
        top.grid(row=0, column=0, columnspan=2, sticky="ew", padx=8, pady=(8, 0))
        self.lbl_model = ttk.Label(top)
        self.lbl_model.grid(row=0, column=0, **pad)
        self.var_model = tk.StringVar(value=self.cfg_model or self.models[0])
        self.cb_model = ttk.Combobox(top, textvariable=self.var_model, values=self.models, width=20)
        self.cb_model.grid(row=0, column=1, **pad)
        self.lbl_effort = ttk.Label(top)
        self.lbl_effort.grid(row=0, column=4, **pad)
        self.var_effort = tk.StringVar(value="low")
        ttk.Combobox(top, textvariable=self.var_effort, values=EFFORTS, width=8, state="readonly").grid(row=0, column=5, **pad)
        self.lbl_repeat = ttk.Label(top)
        self.lbl_repeat.grid(row=0, column=6, **pad)
        self.var_repeat = tk.StringVar(value="1")
        vcmd = (r.register(lambda s: s == "" or (s.isdigit() and len(s) <= 2)), "%P")
        ttk.Spinbox(top, from_=1, to=MAX_REPEAT, textvariable=self.var_repeat, width=4,
                    validate="key", validatecommand=vcmd).grid(row=0, column=7, **pad)
        self.var_wire = tk.BooleanVar(value=False)
        self.chk_wire = ttk.Checkbutton(top, variable=self.var_wire)
        self.chk_wire.grid(row=0, column=8, **pad)
        if not self.have_mitm:
            self.chk_wire.state(["disabled"])
        self.btn_codex = ttk.Button(top, command=self.pick_codex)
        self.btn_codex.grid(row=0, column=9, padx=(14, 2), pady=4)
        self.var_codex = tk.StringVar()
        ttk.Label(top, textvariable=self.var_codex, foreground="#555555").grid(row=0, column=10, **pad)

        act = ttk.Frame(r)
        act.grid(row=1, column=0, columnspan=2, sticky="ew", padx=8, pady=(2, 0))
        act.columnconfigure(2, weight=1)
        style = ttk.Style(r)
        style.configure("Check.TButton", font=("TkDefaultFont", 11, "bold"), padding=(22, 6))
        self.btn_check = ttk.Button(act, style="Check.TButton", command=self.start_check)
        self.btn_check.grid(row=0, column=0, padx=6, pady=4)
        self.btn_cancel = ttk.Button(act, command=self.cancel_check, state="disabled")
        self.btn_cancel.grid(row=0, column=1, padx=6, pady=4)
        self.var_status = tk.StringVar()
        ttk.Label(act, textvariable=self.var_status, anchor="w").grid(row=0, column=2, sticky="ew", padx=10)
        self.progress = ttk.Progressbar(act, mode="indeterminate", length=180)
        self.progress.grid(row=0, column=3, padx=6)
        self.progress.grid_remove()

        self.banner = tk.Label(r, font=("TkDefaultFont", 15, "bold"), anchor="w", padx=14, pady=10,
                               bg=VERDICT_COLORS["UNKNOWN"][0], fg=VERDICT_COLORS["UNKNOWN"][1])
        self.banner.grid(row=2, column=0, columnspan=2, sticky="ew", padx=8, pady=6)

        cols = ("n", "requested", "kind", "served", "status", "created", "verdict", "rid")
        self.tree = ttk.Treeview(r, columns=cols, show="headings", height=8)
        widths = {"n": 36, "requested": 160, "kind": 80, "served": 160, "status": 90, "created": 100, "verdict": 100, "rid": 430}
        for c in cols:
            self.tree.column(c, width=widths[c], minwidth=widths[c], anchor="w", stretch=(c == "rid"))
        for v, (bg, fg) in VERDICT_COLORS.items():
            self.tree.tag_configure(v, background=bg, foreground=fg)
        ysb = ttk.Scrollbar(r, orient="vertical", command=self.tree.yview)
        xsb = ttk.Scrollbar(r, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=ysb.set, xscrollcommand=xsb.set)
        self.tree.grid(row=3, column=0, sticky="nsew", padx=(8, 0))
        ysb.grid(row=3, column=1, sticky="ns", padx=(0, 8))
        xsb.grid(row=4, column=0, sticky="ew", padx=(8, 0))
        r.rowconfigure(4, weight=0)
        r.rowconfigure(5, weight=2)

        self.notes_frame = ttk.LabelFrame(r)
        self.notes_frame.grid(row=5, column=0, columnspan=2, sticky="nsew", padx=8, pady=6)
        self.notes_frame.columnconfigure(0, weight=1)
        self.notes_frame.rowconfigure(0, weight=1)
        self.notes = tk.Text(self.notes_frame, height=8, wrap="word", font=("TkFixedFont", 10), state="disabled")
        self.notes.grid(row=0, column=0, sticky="nsew")
        nsb = ttk.Scrollbar(self.notes_frame, orient="vertical", command=self.notes.yview)
        self.notes.configure(yscrollcommand=nsb.set)
        nsb.grid(row=0, column=1, sticky="ns")

        bottom = ttk.Frame(r)
        bottom.grid(row=6, column=0, columnspan=2, sticky="ew", padx=8, pady=(0, 8))
        self.btn_copy = ttk.Button(bottom, command=self.copy_report, state="disabled")
        self.btn_copy.pack(side="left", padx=4)
        self.btn_json = ttk.Button(bottom, command=self.save_json, state="disabled")
        self.btn_json.pack(side="left", padx=4)
        self.btn_logs = ttk.Button(bottom, command=self.open_logs, state="disabled")
        self.btn_logs.pack(side="left", padx=4)
        self.lbl_version = tk.Label(bottom, text=f"v{cmc.__version__}")
        self.lbl_version.pack(side="right", padx=8)
        self.update_info: Optional[dict] = None
        try:
            self.github_icon = tk.PhotoImage(data=GITHUB_ICON_PNG_B64)
        except tk.TclError:  # very old Tk without PNG support: text-only link
            self.github_icon = None
        self.link_github = tk.Label(bottom, text="GitHub", image=self.github_icon, compound="left",
                                    fg="#0969da", cursor="hand2", padx=4)
        self.link_github.pack(side="right", padx=6)
        self.link_github.bind("<Button-1>", lambda _e: self.open_repo())
        self.btn_lang = ttk.Button(bottom, command=self.toggle_language)
        self.btn_lang.pack(side="right", padx=4)

    def s(self, key: str, **kw) -> str:
        return STRINGS[self.lang][key].format(**kw)

    def _apply_language(self) -> None:
        m = MENU[self.lang]
        self.menubar.entryconfigure(1, label=m["help"])
        self.help_menu.entryconfigure(0, label=m["usage"])
        self.help_menu.entryconfigure(1, label=m["terms"])
        self.help_menu.entryconfigure(3, label=m["about"])
        for kind, win in list(self.help_windows.items()):
            if win.winfo_exists():
                self._fill_help(win, kind)
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
        self.notes_frame.configure(text=self.s("notes"))
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
            self.banner.configure(text=self.s("banner_running"))
            self.tree.delete(*self.tree.get_children())
            for p in self.live_probes:
                self._add_probe_rows(p)
            if self.last_progress is not None:
                self._show_progress(*self.last_progress)
        else:
            self.var_status.set(self.s("updated", current=cmc.__version__) if self.updated_from else self.s("idle"))
            self.banner.configure(text=self.s("banner_idle"))

    def toggle_language(self) -> None:
        self.lang = "ko" if self.lang == "en" else "en"
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
        win.geometry("760x560" if kind != "about" else "620x260")
        win.transient(self.root)
        frame = ttk.Frame(win)
        frame.pack(fill="both", expand=True, padx=8, pady=8)
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        text = tk.Text(frame, wrap="word", font=("TkDefaultFont", 10), state="disabled",
                       padx=10, pady=8, spacing1=2, spacing3=2)
        text.grid(row=0, column=0, sticky="nsew")
        sb = ttk.Scrollbar(frame, orient="vertical", command=text.yview)
        text.configure(yscrollcommand=sb.set)
        sb.grid(row=0, column=1, sticky="ns")
        btn = ttk.Button(frame, command=win.destroy)
        btn.grid(row=1, column=0, columnspan=2, pady=(6, 0))
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

    def start_check(self) -> None:
        if self.worker is not None or self.updating:
            return
        opts = self.options()
        self.cancel = cmc.Canceller()
        self.result = None
        self.live_probes = []
        self.last_progress = None
        self.t0 = time.time()
        self._set_running(True)
        self.tree.delete(*self.tree.get_children())
        self._set_notes("")
        self.banner.configure(text=self.s("banner_running"), bg=VERDICT_COLORS["UNKNOWN"][0], fg=VERDICT_COLORS["UNKNOWN"][1])
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
        finally:
            self.root.after(100, self._poll)

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
            self.tree.insert("", "end", values=(p.index, p.requested, "-", "-", "-", "-", "ERROR", "-"), tags=("ERROR",))

    def _render_result(self, res: cmc.CheckResult) -> None:
        """Table, banner and details for a finished check (status line untouched)."""
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
        bg, fg = VERDICT_COLORS[key]
        self.banner.configure(text=text, bg=bg, fg=fg)

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

    def show_update(self, info: Optional[dict]) -> None:
        """Red NEW badge that opens the release page; the frozen build also updates itself."""
        self.update_info = info
        if not info:
            return
        new = info["version"]
        self.lbl_version.configure(text=self.s("update_new", new=new), fg="#b3261e",
                                   font=("TkDefaultFont", 10, "bold"), cursor="hand2")
        self.lbl_version.bind("<Button-1>", lambda _e: self.open_update())
        if self.updating or self.worker is not None or self.result is not None:
            return  # a check is running or already done: do not restart the app under the user
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
    ap.add_argument("--lang", default="en", choices=["en", "ko"], help="interface language")
    ap.add_argument("--fake", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--auto-check", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--exit-after", type=float, default=None, help=argparse.SUPPRESS)
    ap.add_argument("--show-help", choices=["usage", "terms", "about"], default=None, help=argparse.SUPPRESS)
    ap.add_argument("--no-update-check", action="store_true",
                    help=f"do not ask api.github.com for a newer release at startup (or set {cmc.NO_UPDATE_ENV}=1)")
    ap.add_argument("--no-auto-update", action="store_true",
                    help="show the NEW badge only; never download and replace this exe by itself")
    ap.add_argument("--updated-from", default=None, help=argparse.SUPPRESS)
    a = ap.parse_args(argv)
    if a.fake and not install_fake_runner():
        _report_startup_error("fixtures not found; --fake needs tests/fixtures next to this file")
        return 1
    _enable_dpi_awareness()
    try:
        root = tk.Tk()
        app = App(root, lang=a.lang, fake=a.fake, exit_after=a.exit_after,
                  update_check=not a.no_update_check and not a.fake,
                  auto_update=not a.no_auto_update, updated_from=a.updated_from)
        if a.auto_check:
            root.after(300, app.start_check)
        if a.show_help:
            root.after(300, lambda: app.show_help(a.show_help))
        if a.exit_after is not None and not a.auto_check:
            root.after(int(a.exit_after * 1000), root.destroy)
        root.mainloop()
    except Exception as e:  # a windowed build has no console: show the reason instead of dying silently
        _report_startup_error(f"{APP_TITLE} could not start: {type(e).__name__}: {e}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
