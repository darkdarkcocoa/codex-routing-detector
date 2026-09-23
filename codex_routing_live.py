#!/usr/bin/env python3
"""Live monitor: watch a real Codex CLI session and record which model answers each request.

The session is started by this module in a new terminal window with HTTPS_PROXY pointing at
the built-in proxy (codex_routing_proxy) and CODEX_CA_CERTIFICATE pointing at its throw-away
CA. Every message on the responses WebSocket is decoded in memory; only model names,
response ids, statuses, timestamps and error codes are kept. Prompts, file contents and the
model's answers pass through and are never stored.

Only the Codex CLI can be watched: the Codex desktop app is a packaged (MSIX) application
that does not take environment variables from another program.
"""
from __future__ import annotations

import json
import os
import queue
import shlex
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

import codex_routing_detector as cmc
import codex_routing_proxy as crp

Event = Tuple[str, dict]


def read_config_model_effort() -> Tuple[Optional[str], Optional[str], str]:
    """(model, model_reasoning_effort, source) from ~/.codex/config.toml, top-level keys only."""
    cfg = cmc.codex_home() / "config.toml"
    if not cfg.exists():
        return None, None, "no config.toml"
    try:
        text = cfg.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None, None, "config.toml (unreadable)"
    try:
        import tomllib  # Python 3.11+
        data = tomllib.loads(text)
        m, e = data.get("model"), data.get("model_reasoning_effort")
        return (str(m) if m is not None else None), (str(e) if e is not None else None), "config.toml"
    except ImportError:
        pass
    except Exception:
        return None, None, "config.toml (could not be parsed)"
    vals = cmc.toml_top_level_strings(text, ("model", "model_reasoning_effort"))
    return vals["model"], vals["model_reasoning_effort"], "config.toml (top-level keys only)"


def config_mtime() -> Optional[float]:
    try:
        return (cmc.codex_home() / "config.toml").stat().st_mtime
    except OSError:
        return None


# ------------------------------------------------------------------ aggregation
@dataclass
class LiveRow:
    """One server response object seen during the session (the table shows one line per row)."""
    n: int
    conn: int
    first_seen: float
    requested: Optional[str]
    kind: str  # "turn", "warmup" or "error" (a stream error that belongs to no response)
    record: Optional[cmc.ResponseRecord] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None

    @property
    def response_id(self) -> str:
        return self.record.response_id if self.record else "-"

    @property
    def served(self) -> Optional[str]:
        return self.record.model if self.record else None

    @property
    def status(self) -> Optional[str]:
        return self.record.status if self.record else None

    def verdict(self) -> str:
        if self.record is None:
            return "UNSUPPORTED" if cmc.is_unsupported_error(self.error_code, self.error_message) else "ERROR"
        if not self.requested:
            return "UNKNOWN"
        return self.record.verdict(self.requested)

    def other_models(self) -> List[str]:
        if self.record is None or not self.requested:
            return []
        return [m for m in self.record.models_seen if not cmc.models_match(self.requested, m)[0]]


@dataclass
class _Conn:
    collector: cmc.ResponseCollector = field(default_factory=cmc.ResponseCollector)
    requested: Optional[str] = None
    request_had_user_input: Optional[bool] = None
    rows_by_id: Dict[str, LiveRow] = field(default_factory=dict)


def _has_user_input(obj: dict) -> Optional[bool]:
    items = obj.get("input")
    if not isinstance(items, list):
        return None
    return any(isinstance(it, dict) and str(it.get("role", "")).lower() == "user" for it in items)


class LiveAggregator:
    """Turns decoded WebSocket messages into LiveRows and summary counts. Not thread-safe:
    feed it from one thread (the window's poll loop, or the command-line loop)."""

    def __init__(self) -> None:
        self.rows: List[LiveRow] = []
        self.rate_limits: Optional[dict] = None
        self.conns: Dict[int, _Conn] = {}
        self.hints: Dict[int, str] = {}  # conn -> model from the x-codex-routing-hint header
        self.unparsed = 0

    def note_hint(self, conn: int, hint: str) -> None:
        for part in hint.split(";"):
            k, _, v = part.strip().partition("=")
            if k.strip().lower() == "model" and v.strip():
                self.hints[conn] = v.strip()

    def feed(self, msg: crp.WsMessage) -> List[Event]:
        """Return the events this message caused: ("row", {"row": LiveRow, "new": bool}),
        ("rate_limits", {...})."""
        try:
            obj = json.loads(msg.text)
        except ValueError:
            self.unparsed += 1
            return []
        if not isinstance(obj, dict):
            self.unparsed += 1
            return []
        conn = self.conns.setdefault(msg.conn, _Conn())
        if msg.direction == "c2s":
            if obj.get("type") == "response.create":
                if obj.get("model"):
                    conn.requested = str(obj["model"])
                conn.request_had_user_input = _has_user_input(obj)
            return []
        events: List[Event] = []
        if obj.get("type") == "codex.rate_limits":
            self.rate_limits = obj
            events.append(("rate_limits", {"rate_limits": obj}))
        rec, stream_error = conn.collector.feed(obj)
        if rec is not None:
            row = conn.rows_by_id.get(rec.response_id)
            new = row is None
            if row is None:
                kind = rec.kind
                if kind != "turn" and conn.request_had_user_input:
                    kind = "turn"
                conn.request_had_user_input = None  # consumed by this response
                row = LiveRow(n=len(self.rows) + 1, conn=msg.conn, first_seen=msg.ts, requested=None,
                              kind=kind, record=rec)
                conn.rows_by_id[rec.response_id] = row
                self.rows.append(row)
            if row.requested is None:  # the request frame may be decoded after the first server frame
                row.requested = conn.requested or self.hints.get(msg.conn)
            events.append(("row", {"row": row, "new": new}))
        elif stream_error:
            code, message = conn.collector.stream_errors[-1]
            row = LiveRow(n=len(self.rows) + 1, conn=msg.conn, first_seen=msg.ts,
                          requested=conn.requested or self.hints.get(msg.conn), kind="error",
                          error_code=code, error_message=message)
            self.rows.append(row)
            events.append(("row", {"row": row, "new": True}))
        return events

    # summary
    def counts(self) -> Dict[str, int]:
        out: Dict[str, int] = {}
        for r in self.rows:
            v = r.verdict()
            out[v] = out.get(v, 0) + 1
        return out

    def pairs(self) -> List[str]:
        seen = []
        for r in self.rows:
            if r.verdict() == "REROUTED":
                p = f"{r.requested} -> {', '.join(sorted(set(r.other_models())))}"
                if p not in seen:
                    seen.append(p)
        return seen

    def overall(self) -> str:
        """REROUTED if any response named another model; OK if a turn completed as requested and
        nothing was rerouted; UNSUPPORTED / ERROR next; OK again if only warm-ups were seen and
        all of them were fine; NO_DATA when there is nothing yet."""
        pairs = [(r.kind, r.verdict()) for r in self.rows]
        verdicts = [v for _k, v in pairs]
        if "REROUTED" in verdicts:
            return "REROUTED"
        if any(k == "turn" and v == "ok" for k, v in pairs):
            return "OK"
        if "UNSUPPORTED" in verdicts:
            return "UNSUPPORTED"
        if "ERROR" in verdicts or "UNKNOWN" in verdicts:
            return "ERROR"
        if "ok" in verdicts:
            return "OK"
        return "NO_DATA"

    def report(self) -> str:
        lines = [f"codex-routing-detector {cmc.__version__} live monitor", ""]
        acct = self.account_line()
        if acct:
            lines.append(f"account: {acct}")
        lines.append(f"responses: {len(self.rows)}  " +
                     "  ".join(f"{k}={v}" for k, v in sorted(self.counts().items())))
        for p in self.pairs():
            lines.append(f"REROUTED: {p}")
        lines.append("")
        wr = max([22] + [len(r.requested or "?") for r in self.rows])
        ws = max([22] + [len(r.served or "-") for r in self.rows])
        lines.append(f"{'#':>3}  {'time':8}  {'requested':{wr}}  {'kind':7}  {'served by':{ws}}  {'status':11}  {'verdict':11}  response id")
        for r in self.rows:
            t = time.strftime("%H:%M:%S", time.localtime(r.first_seen))
            lines.append(f"{r.n:>3}  {t:8}  {(r.requested or '?'):{wr}}  {r.kind:7}  {(r.served or '-'):{ws}}  "
                         f"{(r.status or r.error_code or '-'):11}  {r.verdict():11}  {r.response_id}")
        return "\n".join(lines)

    def account_line(self) -> Optional[str]:
        rl = self.rate_limits
        if not rl:
            return None
        lim = rl.get("rate_limits") or {}
        prim = lim.get("primary") or {}
        used = prim.get("used_percent")
        parts = [f"plan={rl.get('plan_type') or '?'}"]
        if used is not None:
            parts.append(f"used={used}%")
        if lim.get("limit_reached") is not None:
            parts.append(f"limit_reached={lim.get('limit_reached')}")
        return " ".join(parts)


# ------------------------------------------------------------------ the session
def codex_command_line(codex: List[str], extra_args: Optional[List[str]] = None) -> List[str]:
    return list(codex) + list(extra_args or [])


def shell_hint(env_add: Dict[str, str], env_drop: List[str], cmd: List[str]) -> str:
    """The command a user could run by hand in another terminal (for platforms where no
    terminal window can be opened automatically)."""
    if os.name == "nt":
        parts = [f'set "{k}="' for k in env_drop] + [f'set "{k}={v}"' for k, v in env_add.items()]
        parts.append(subprocess.list2cmdline(cmd))
        return " && ".join(parts)
    parts = [f"unset {k}" for k in env_drop] + [f"export {k}={shlex.quote(v)}" for k, v in env_add.items()]
    parts.append(" ".join(shlex.quote(c) for c in cmd))
    return " && ".join(parts)


def launch_in_terminal(cmd: List[str], env: dict, cwd: str) -> subprocess.Popen:
    """Start `cmd` in a new terminal window. Windows: a new console (Windows Terminal when it is
    the default). macOS/Linux: best effort through a common terminal emulator."""
    if os.name == "nt":
        return subprocess.Popen(cmd, cwd=cwd, env=env, creationflags=subprocess.CREATE_NEW_CONSOLE)
    passthrough = [f"{k}={v}" for k, v in env.items() if k in PROXY_VARS]
    if sys.platform == "darwin":
        script = "cd " + shlex.quote(cwd) + " && env " + " ".join(shlex.quote(p) for p in passthrough) \
            + " " + " ".join(shlex.quote(c) for c in cmd)
        return subprocess.Popen(["osascript", "-e", f'tell application "Terminal" to do script {json.dumps(script)}'],
                                env=env)
    for term in (["x-terminal-emulator", "-e"], ["gnome-terminal", "--"], ["konsole", "-e"], ["xterm", "-e"]):
        if cmc.shutil.which(term[0]):
            # terminal servers (gnome-terminal, konsole) do not inherit env=, so pass it on the command line
            return subprocess.Popen(term + ["env"] + passthrough + cmd, cwd=cwd, env=env)
    raise RuntimeError("no terminal emulator found")


PROXY_VARS = ("HTTPS_PROXY", "https_proxy", "CODEX_CA_CERTIFICATE")
# On Windows the new console *is* the Codex process, so its exit ends the session. macOS/Linux
# terminal launchers return as soon as the window is handed off; there only Stop ends the session.
LAUNCHER_TRACKS_CODEX = os.name == "nt"


class LiveMonitor:
    """Owns the proxy, the CA and the Codex process. Messages and notices arrive on `events`
    (a queue) so the window can drain them from its own thread:
        ("message", WsMessage)   a decoded WebSocket message
        ("notice", str)          something for the details view
        ("codex_exit", int)      the Codex process ended with this code
    """

    def __init__(self, codex: List[str], workdir: str, codex_args: Optional[List[str]] = None,
                 launcher: Callable[[List[str], dict, str], subprocess.Popen] = launch_in_terminal) -> None:
        self.codex = codex
        self.workdir = workdir
        self.codex_args = codex_args or []
        self.launcher = launcher
        self.events: "queue.Queue[tuple]" = queue.Queue()
        self.ca: Optional[crp.CertAuthority] = None
        self.proxy: Optional[crp.InterceptProxy] = None
        self.proc: Optional[subprocess.Popen] = None
        self.started_at = 0.0
        self.command_hint = ""
        self._stopped = False
        self._announced: set = set()

    # lifecycle
    def start(self) -> None:
        if not crp.have_crypto():
            raise RuntimeError("the live monitor needs the cryptography package: pip install cryptography")
        self.ca = crp.CertAuthority()
        self.proxy = crp.InterceptProxy(self.ca, on_message=lambda m: self.events.put(("message", m)),
                                        on_event=self._proxy_event)
        port = self.proxy.start()
        add, drop = self.proxy.env()
        env = dict(os.environ)
        env.update(add)
        for k in drop:
            env.pop(k, None)
        cmd = codex_command_line(self.codex, self.codex_args)
        self.command_hint = shell_hint(add, drop, cmd)
        self.events.put(("notice", f"proxy listening on 127.0.0.1:{port}; CA certificate: {cmc.display_path(self.ca.cert_path)}"))
        try:
            self.proc = self.launcher(cmd, env, self.workdir)
        except Exception as e:
            self.stop()
            raise RuntimeError(f"could not start Codex: {e}. To run it by hand, start the monitor from the command "
                               f"line and use: {self.command_hint}")
        self.started_at = time.time()
        self.events.put(("notice", f"started {cmc.display_path(cmd[0])} in {cmc.display_path(self.workdir)} (pid {self.proc.pid})"))
        if LAUNCHER_TRACKS_CODEX or self.launcher is not launch_in_terminal:
            threading.Thread(target=self._wait_codex, name="crd-live-wait", daemon=True).start()
        else:
            self.events.put(("notice", "this platform's terminal detaches from Codex: press Stop when you are done "
                                       "(it will not close the Codex window)"))

    def _wait_codex(self) -> None:
        proc = self.proc
        if proc is None:
            return
        rc = proc.wait()
        if not self._stopped:
            self.events.put(("codex_exit", rc))

    def _proxy_event(self, name: str, info: dict) -> None:
        if name == "ws_open" and info.get("watched"):
            self._announced.add(info["conn"])
            self.events.put(("ws_open", info))
            self.events.put(("notice", f"responses WebSocket #{info['conn']} opened"
                             + (f" (routing hint: {info['routing_hint']})" if info.get("routing_hint") else "")
                             + ("" if info.get("deflate") else ", no compression")))
        elif name == "ws_close" and info.get("conn") in self._announced:
            self.events.put(("notice", f"WebSocket #{info['conn']} closed"))
        elif name == "parse_lost":
            self.events.put(("notice", f"WebSocket #{info['conn']} {info['direction']}: decoding stopped ({info['error']}); "
                                       "traffic still flows but this connection is no longer watched"))
        elif name == "error":
            self.events.put(("notice", f"proxy: {info.get('error')}"))

    def codex_running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def stop(self) -> None:
        """Close the Codex window (it cannot work without the proxy) and the proxy, and delete the CA."""
        self._stopped = True
        if self.proc is not None and self.proc.poll() is None and getattr(self.proc, "pid", 0):
            cmc.kill_tree(self.proc)
        if self.proxy is not None:
            self.proxy.stop()
            self.proxy = None
        if self.ca is not None:
            self.ca.close()
            self.ca = None


# ------------------------------------------------------------------ command line
def run_live_cli(codex_path: Optional[str], workdir: Optional[str], codex_args: List[str]) -> int:
    """`codex-routing-detector --live`: print one line per response until Codex exits or Ctrl-C.
    Exit code 2 if any response was served by another model, 0 otherwise, 1 on setup errors."""
    codex, how = cmc.find_codex(codex_path)
    if not codex:
        print(f"codex binary not found ({how})", file=sys.stderr)
        return 1
    mon = LiveMonitor(codex, workdir or os.getcwd(), codex_args)
    agg = LiveAggregator()
    try:
        mon.start()
    except RuntimeError as e:
        print(str(e), file=sys.stderr)
        return 1
    print(f"live monitor: watching {' '.join(cmc.display_path(c) for c in codex)} [{how}]; Ctrl-C stops it",
          file=sys.stderr)
    printed: Dict[int, tuple] = {}
    try:
        while True:
            try:
                ev = mon.events.get(timeout=0.5)
            except queue.Empty:
                continue
            if ev[0] == "message":
                for name, info in agg.feed(ev[1]):
                    if name == "row":
                        r = info["row"]
                        state = (r.served, r.status or r.error_code, r.verdict())
                        if printed.get(r.n) == state:
                            continue  # another frame of the same response, nothing new to show
                        printed[r.n] = state
                        t = time.strftime("%H:%M:%S", time.localtime(r.first_seen))
                        print(f"{t}  #{r.n:<3} {r.requested or '?':22} {r.kind:7} -> {r.served or '-':22} "
                              f"{r.status or r.error_code or '-':11} {r.verdict()}", flush=True)
            elif ev[0] == "ws_open":
                agg.note_hint(ev[1]["conn"], ev[1].get("routing_hint", ""))
            elif ev[0] == "notice":
                print(f"  [{ev[1]}]", file=sys.stderr, flush=True)
            elif ev[0] == "codex_exit":
                while True:  # messages decoded just before the exit are still worth showing
                    try:
                        late = mon.events.get_nowait()
                    except queue.Empty:
                        break
                    if late[0] == "message":
                        for name, info in agg.feed(late[1]):
                            if name == "row":
                                r = info["row"]
                                t = time.strftime("%H:%M:%S", time.localtime(r.first_seen))
                                print(f"{t}  #{r.n:<3} {r.requested or '?':22} {r.kind:7} -> {r.served or '-':22} "
                                      f"{r.status or r.error_code or '-':11} {r.verdict()}", flush=True)
                print(f"codex exited with code {ev[1]}", file=sys.stderr)
                break
    except KeyboardInterrupt:
        pass
    finally:
        mon.stop()
    print()
    print(agg.report())
    return 2 if agg.overall() == "REROUTED" else 0
