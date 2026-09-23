#!/usr/bin/env python3
"""codex-routing-detector: find out which model actually answers your Codex requests.

Codex (OpenAI's coding agent) lets you pick a model such as `gpt-6-astra`, but the
server may answer with a different one. The client UI and the local session logs only
record the model you *asked* for, so they cannot show this. This tool runs one tiny
Codex turn per model and reads the model name the *server* put into its own response
object (`response.created` / `response.completed`), which is the model that served
the request.

Two ways of getting at the server's bytes:

  trace (default)  Run the real `codex` binary with
                   RUST_LOG=tungstenite::protocol=trace. `tungstenite` is the
                   WebSocket library underneath Codex; at trace level it prints every
                   frame it receives from the socket, verbatim, before Codex's own code
                   touches it. No extra software needed.

  --wire           Put mitmproxy between Codex and chatgpt.com (HTTPS_PROXY plus
                   CODEX_CA_CERTIFICATE, no changes to the OS certificate store) and
                   record both directions of the WebSocket. Needs `pip install mitmproxy`.

  --live           Watch a real Codex CLI session instead of sending probes: opens Codex in
                   a new terminal window behind the built-in proxy (codex_routing_proxy) and
                   prints one line per server response as it happens. Needs
                   `pip install cryptography`. The Codex desktop app cannot be watched.

Exit codes: 0 = every checked model was served as requested, 2 = at least one request
(including the control) was served by a different model, 1 = the check could not be
completed or a usage error.

Requires Python 3.8+ and a Codex install that is signed in. No third-party packages.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import glob
import json
import os
import platform
import re
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

__version__ = "1.6.1"

FALLBACK_MODEL = "gpt-6-astra"
DEFAULT_CONTROL = "gpt-5.6-sol"
DEFAULT_PROMPT = "Reply with exactly the single word: pong"
# Only the WebSocket library's message log. `tungstenite::protocol::frame` (raw frame
# headers) is switched off, and Codex's own HTTP logging is never enabled because it
# prints response headers, including session cookies.
TRACE_FILTER = "tungstenite::protocol=trace,tungstenite::protocol::frame=off"

RECEIVED_RE = re.compile(r"tungstenite::protocol: Received message (\{.*)$")
SENDING_RE = re.compile(r"tungstenite::protocol: Sending frame")
TRACE_LINE_RE = re.compile(r"^\S+Z?\s+(TRACE|DEBUG|INFO|WARN|ERROR)\s")
BANNER_MODEL_RE = re.compile(r"^model:\s*(\S+)\s*$", re.M)
TOML_TABLE_HEADER_RE = re.compile(r"^\s*\[\[?[^\[\]\n]+\]\]?\s*(?:#.*)?$")

# Redaction for anything written to disk or printed. Values stop at the next quote,
# backslash (JSON-escaped quote) or line end, so JSON stays parseable.
_SECRET_KEYS = r"(?:authorization|proxy-authorization|cookie|set-cookie|x-oai-attestation|x-codex-turn-state)"
_TOKEN_KEYS = r"(?:access_token|refresh_token|id_token|accessToken|refreshToken|idToken|api_key|apiKey|OPENAI_API_KEY|CODEX_API_KEY)"
REDACT_RES = [
    (re.compile(r"(?i)((?:\\?\")?" + _SECRET_KEYS + r"(?:\\?\")?\s*[:=]\s*(?:\\?\")?)([^\"\\\r\n]*)"), r"\1<redacted>"),
    (re.compile(r"((?:\\?\")" + _TOKEN_KEYS + r"(?:\\?\")\s*:\s*(?:\\?\"))([^\"\\\r\n]*)"), r"\1<redacted>"),
    (re.compile(r"Bearer\s+[A-Za-z0-9._~+/=-]{16,}"), "Bearer <redacted>"),
    # query-string style: ?access_token=...&refresh_token=...
    (re.compile(r"(?i)\b(" + _TOKEN_KEYS + r"|token)=([^&\s\"'<>]+)"), r"\1=<redacted>"),
]
# Fields of a client `response.create` frame that are kept in a saved --wire recording.
C2S_KEEP = ("type", "model", "service_tier", "reasoning", "previous_response_id", "store", "stream", "text")

TERMINAL_STATUSES = {"completed", "failed", "incomplete", "cancelled"}
# The server refusing a model for this account/plan is not a substitution.
UNSUPPORTED_RE = re.compile(r"(?i)not supported|not available|unsupported model|does not have access|"
                            r"model_not_found|no access to|not entitled|not enabled for")


def is_unsupported_error(code: Optional[str], message: Optional[str]) -> bool:
    text = f"{code or ''} {message or ''}"
    return bool(UNSUPPORTED_RE.search(text)) and ("model" in text.lower() or "access" in text.lower())
MITMPROXY_MIN_MAJOR = 7
# Child processes never get a console window of their own (matters when the GUI build,
# which has no console, launches codex.exe or mitmdump.exe).
_NO_WINDOW = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}


# --------------------------------------------------------------------------- models
# "openai/gpt-6-astra" is how routers such as OpenRouter or LiteLLM spell a model. Codex passes
# the name through unchanged and the ChatGPT backend refuses it ("not supported when using Codex
# with a ChatGPT account"), which reads like the account cannot use the model at all.
PROVIDER_PREFIX_RE = re.compile(r"(?i)^\s*openai/(?=\S)")


def strip_provider_prefix(model: str) -> str:
    """`openai/gpt-6-astra` -> `gpt-6-astra`; any other name is returned stripped of spaces."""
    return PROVIDER_PREFIX_RE.sub("", model).strip()


def models_match(requested: str, served: Optional[str]) -> Tuple[bool, Optional[str]]:
    """(match, note). A dated snapshot of the requested model counts as a match."""
    if not served:
        return False, None
    r, s = requested.strip().lower(), served.strip().lower()
    if r == s:
        return True, None
    if re.fullmatch(re.escape(r) + r"-\d{4}-\d{2}-\d{2}", s):  # exactly `<requested>-YYYY-MM-DD`
        return True, f"served a dated snapshot of {requested}: {served}"
    return False, None


@dataclass
class ResponseRecord:
    """One server response object as seen in the stream."""
    response_id: str
    model: Optional[str]
    status: Optional[str]
    service_tier: Optional[str]
    created_at: Optional[int]
    kind: str  # "warmup" (no previous_response_id) or "turn"
    models_seen: List[str] = field(default_factory=list)
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    usage: Optional[dict] = None

    def verdict(self, requested: str) -> str:
        if is_unsupported_error(self.error_code, self.error_message):
            return "UNSUPPORTED"
        # A response object naming another model is evidence even if the response then failed.
        if any(not models_match(requested, m)[0] for m in self.models_seen):
            return "REROUTED"
        if self.error_code or self.status == "failed":
            return "ERROR"
        if not self.models_seen or self.status != "completed":
            return "UNKNOWN"  # no model field, or the response never completed (timeout, crash)
        return "ok"

    def notes(self, requested: str) -> List[str]:
        out = []
        if len(self.models_seen) > 1:
            out.append("model changed mid-response: " + " -> ".join(self.models_seen))
        for m in self.models_seen:
            ok, note = models_match(requested, m)
            if ok and note:
                out.append(note)
        return out


@dataclass
class Probe:
    index: int
    requested: str
    effort: str
    tier: Optional[str]
    is_control: bool
    method: str
    banner_model: Optional[str] = None
    wire_requested: List[str] = field(default_factory=list)
    exit_code: Optional[int] = None
    timed_out: bool = False
    duration_s: float = 0.0
    frames_received: int = 0
    frames_unparsed: int = 0
    frames_sent: int = 0
    responses: List[ResponseRecord] = field(default_factory=list)
    stream_errors: List[Tuple[Optional[str], Optional[str]]] = field(default_factory=list)
    rate_limits: Optional[dict] = None
    metadata_headers: Optional[dict] = None
    log_path: Optional[str] = None
    notes: List[str] = field(default_factory=list)

    def turns(self) -> List[ResponseRecord]:
        return [r for r in self.responses if r.kind == "turn"]

    def unsupported(self) -> bool:
        """The server said this account cannot use the requested model."""
        return any(r.verdict(self.requested) == "UNSUPPORTED" for r in self.responses) or \
            any(is_unsupported_error(c, m) for c, m in self.stream_errors)

    def verdict(self) -> str:
        """REROUTED if any response object (warm-up or turn) names another model: that is direct
        evidence. `ok` only if the real turn was served as requested; a warm-up alone cannot
        stand in for a turn that failed or never started. UNSUPPORTED when the server refused
        the model for this account (a warm-up answered by the plan's default model is then not
        counted as a substitution)."""
        if self.unsupported():
            return "UNSUPPORTED"
        verdicts = [r.verdict(self.requested) for r in self.responses]
        if "REROUTED" in verdicts:
            return "REROUTED"
        turns = self.turns()
        if turns:
            tv = [r.verdict(self.requested) for r in turns]
            return "ok" if "ok" in tv else ("ERROR" if "ERROR" in tv else "UNKNOWN")
        if self.stream_errors:
            return "ERROR"
        if not verdicts:
            return "NO_DATA"
        if len(verdicts) >= 2:
            # No previous_response_id anywhere (a client that does not send it): the last
            # response is taken as the turn. A single warm-up is never enough for `ok`.
            return verdicts[-1]
        return "ERROR" if verdicts[0] == "ERROR" else "UNKNOWN"


# ------------------------------------------------------------------------ parsing
_DECODER = json.JSONDecoder()


def _decode_prefix(text: str) -> Optional[object]:
    """Parse the JSON object at the start of `text`, ignoring anything after it."""
    try:
        obj, _ = _DECODER.raw_decode(text)
        return obj
    except ValueError:
        return None


def parse_trace_frames(text: str) -> Tuple[List[dict], int, int]:
    """Return (received JSON frames in order, count of 'Sending frame' lines, unparsed count).

    Splits on '\\n' only: JSON strings may legally contain U+2028/U+2029/U+0085, which
    str.splitlines() would treat as line breaks.
    """
    frames: List[dict] = []
    sent = unparsed = 0
    for line in text.split("\n"):
        line = line.rstrip("\r")
        if SENDING_RE.search(line):
            sent += 1
            continue
        m = RECEIVED_RE.search(line)
        if not m:
            continue
        obj = _decode_prefix(m.group(1))
        if isinstance(obj, dict):
            frames.append(obj)
        else:
            unparsed += 1
    return frames, sent, unparsed


def parse_wire_frames(jsonl_text: str) -> Tuple[List[dict], List[str]]:
    """Return (server->client JSON frames, requested models seen in client->server frames)."""
    frames: List[dict] = []
    requested: List[str] = []
    for line in jsonl_text.split("\n"):
        try:
            rec = json.loads(line)
            obj = json.loads(rec["text"])
        except (json.JSONDecodeError, KeyError, TypeError):
            continue
        if not isinstance(obj, dict):
            continue
        if rec.get("dir") == "c2s":
            if obj.get("type") == "response.create" and obj.get("model"):
                requested.append(str(obj["model"]))
        else:
            frames.append(obj)
    return frames, requested


class ResponseCollector:
    """Builds ResponseRecords from server frames, one frame at a time (the live monitor feeds
    frames as they arrive; collect_responses() feeds a whole capture)."""

    def __init__(self) -> None:
        self.by_id: Dict[str, ResponseRecord] = {}
        self.order: List[str] = []
        self.stream_errors: List[Tuple[Optional[str], Optional[str]]] = []

    @property
    def records(self) -> List[ResponseRecord]:
        return [self.by_id[i] for i in self.order]

    def feed(self, f: dict) -> Tuple[Optional[ResponseRecord], bool]:
        """Apply one frame. Returns (the record it touched or None, True if a stream error
        that belongs to no response was added)."""
        t = str(f.get("type", ""))
        r = f.get("response")
        if isinstance(r, dict) and r.get("id"):
            rid = str(r["id"])
            rec = self.by_id.get(rid)
            if rec is None:
                rec = ResponseRecord(
                    response_id=rid, model=None, status=None,
                    service_tier=r.get("service_tier"), created_at=r.get("created_at"),
                    kind="turn" if r.get("previous_response_id") else "warmup",
                )
                self.by_id[rid] = rec
                self.order.append(rid)
            model = r.get("model")
            if model:
                model = str(model)
                rec.model = model
                if model not in rec.models_seen:
                    rec.models_seen.append(model)
            rec.status = r.get("status") or rec.status
            rec.service_tier = r.get("service_tier") or rec.service_tier
            if rec.created_at is None and r.get("created_at") is not None:
                rec.created_at = r.get("created_at")
            if r.get("usage"):
                rec.usage = r["usage"]
            err = r.get("error")
            if isinstance(err, dict) and (err.get("code") or err.get("message")):
                rec.error_code = err.get("code") or err.get("type") or rec.error_code
                rec.error_message = err.get("message") or rec.error_message
            return rec, False
        if t == "error":
            e = f.get("error") if isinstance(f.get("error"), dict) else {}
            code = e.get("code") or e.get("type")
            msg = e.get("message") or f.get("message")
            target = self.by_id[self.order[-1]] if self.order else None
            if target is not None and target.status not in TERMINAL_STATUSES and not target.error_code:
                target.error_code, target.error_message = code, msg
                return target, False
            if target is not None and target.error_code and target.error_code == code:
                return None, False  # the same failure reported twice (response.failed followed by an `error` frame)
            self.stream_errors.append((code, msg))
            return None, True
        return None, False


def collect_responses(frames: List[dict]) -> Tuple[List[ResponseRecord], List[Tuple[Optional[str], Optional[str]]]]:
    c = ResponseCollector()
    for f in frames:
        c.feed(f)
    return c.records, c.stream_errors


def collect_rate_limits(frames: List[dict]) -> Optional[dict]:
    last = None
    for f in frames:
        if f.get("type") == "codex.rate_limits":
            last = f
    return last


def collect_metadata_headers(frames: List[dict]) -> Optional[dict]:
    last = None
    for f in frames:
        if f.get("type") == "codex.response.metadata" and isinstance(f.get("headers"), dict):
            last = {k: v for k, v in f["headers"].items() if k.lower() != "x-codex-turn-state"}
    return last


def redact(text: str) -> str:
    for rx, repl in REDACT_RES:
        text = rx.sub(repl, text)
    return text


def display_path(p: object) -> str:
    """Collapse the home directory to '~' so reports can be shared without a username."""
    s = str(p)
    home = str(Path.home())
    for h in {home, home.replace("\\", "/")}:
        if h and s.lower().startswith(h.lower()) and (len(s) == len(h) or s[len(h)] in "\\/"):
            return "~" + s[len(h):]
    return s


def hide_home(text: str) -> str:
    """Replace the home directory with '~', including JSON-escaped and double-escaped spellings."""
    home = str(Path.home())
    if not home or len(home) <= 3:
        return text
    variants = {home, home.replace("\\", "/"), home.replace("\\", "\\\\"), home.replace("\\", "\\\\\\\\")}
    pattern = "|".join(re.escape(v) for v in sorted(variants, key=len, reverse=True))
    return re.sub(pattern, "~", text, flags=re.I)


def sanitize_log(text: str) -> str:
    """What may be written to disk: no outgoing frames (they hold the whole request,
    compressed but trivially inflatable), no secrets, no home directory."""
    kept = [line for line in text.split("\n") if not SENDING_RE.search(line)]
    return hide_home(redact("\n".join(kept)))


def sanitize_wire_jsonl(text: str) -> str:
    """A --wire recording that may be kept: client frames are reduced to their routing fields
    (the rest is the whole prompt, tool list and working directory); server frames are kept."""
    out = []
    for line in text.split("\n"):
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(rec, dict):
            continue
        if rec.get("dir") == "c2s":
            obj = _decode_prefix(str(rec.get("text", "")))
            if isinstance(obj, dict):
                rec["text"] = json.dumps({k: obj[k] for k in C2S_KEEP if k in obj}, ensure_ascii=False)
                rec["reduced"] = "input, instructions, tools and client_metadata dropped"
            else:
                rec["text"] = "<dropped>"
        out.append(json.dumps(rec, ensure_ascii=False))
    return sanitize_log("\n".join(out) + "\n")


def last_meaningful_stderr_line(text: str) -> Optional[str]:
    for line in reversed(text.split("\n")):
        s = line.strip()
        if s and not TRACE_LINE_RE.match(s) and s != "--------":
            return s[:200]
    return None


# ---------------------------------------------------------------- codex discovery
def codex_home() -> Path:
    return Path(os.environ.get("CODEX_HOME") or (Path.home() / ".codex"))


def read_config_values() -> Tuple[Optional[str], Optional[str], str]:
    """(model, service_tier, source) from ~/.codex/config.toml, top-level keys only."""
    cfg = codex_home() / "config.toml"
    if not cfg.exists():
        return None, None, "no config.toml"
    try:
        text = cfg.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None, None, "config.toml (unreadable)"
    try:
        import tomllib  # Python 3.11+
        data = tomllib.loads(text)
        m, t = data.get("model"), data.get("service_tier")
        return (str(m) if m is not None else None), (str(t) if t is not None else None), "config.toml"
    except ImportError:
        pass
    except Exception:
        return None, None, "config.toml (could not be parsed)"
    vals = toml_top_level_strings(text, ("model", "service_tier"))
    return vals["model"], vals["service_tier"], "config.toml (top-level keys only)"


def toml_top_level_strings(text: str, keys: Tuple[str, ...]) -> Dict[str, Optional[str]]:
    """Fallback for Python < 3.11: quoted string values of top-level keys, i.e. everything
    before the first `[table]` / `[[array-of-tables]]` header line. Lines inside a multi-line
    array (bracket depth > 0) are never taken as headers."""
    top_lines: List[str] = []
    depth = 0
    for line in text.split("\n"):
        if depth == 0 and TOML_TABLE_HEADER_RE.match(line):
            break
        top_lines.append(line)
        # Strings first (escape-aware), then the comment: brackets and `#` inside strings do not count.
        code = re.sub(r"\"(?:[^\"\\]|\\.)*\"|'[^']*'", "", line).split("#", 1)[0]
        depth = max(0, depth + code.count("[") - code.count("]"))
    top = "\n".join(top_lines)
    out: Dict[str, Optional[str]] = {}
    for key in keys:
        m = re.search(rf"^\s*{re.escape(key)}\s*=\s*([\"'])(.*?)\1", top, re.M)
        out[key] = m.group(2) if m else None
    return out


def _platform_tag() -> Tuple[str, str]:
    m = platform.machine().lower()
    arch = "arm64" if m in ("arm64", "aarch64") else "x64"
    sysname = "win32" if os.name == "nt" else ("darwin" if sys.platform == "darwin" else "linux")
    return sysname, arch


def _native_from_package(pkg: Path) -> Optional[str]:
    """Native codex binary inside an installed @openai/codex npm package (npm/yarn/pnpm layouts)."""
    exe = "codex.exe" if os.name == "nt" else "codex"
    cands = glob.glob(str(pkg / "node_modules" / "@openai" / "codex-*" / "vendor" / "*" / "bin" / exe))
    cands += glob.glob(str(pkg.parent.parent / ".pnpm" / "@openai+codex-*" / "node_modules" / "@openai" / "codex-*" / "vendor" / "*" / "bin" / exe))
    sysname, arch = _platform_tag()
    pref = [c for c in cands if f"codex-{sysname}-{arch}" in c.replace("\\", "/")]
    pick = pref or cands
    return max(pick, key=os.path.getmtime) if pick else None


def find_codex(explicit: Optional[str]) -> Tuple[Optional[List[str]], str]:
    """Return (command prefix, how it was found). The prefix is a list so that a
    JavaScript launcher (`node codex.js`) can be used when no native binary is found."""
    if explicit or os.environ.get("CODEX_BIN"):
        raw = explicit or os.environ["CODEX_BIN"]
        resolved = shutil.which(raw) or raw
        if not os.path.exists(resolved):
            return None, f"{raw!r} not found"
        resolved = os.path.abspath(resolved)
        source = "--codex" if explicit else "CODEX_BIN"
        if os.name == "nt" and Path(resolved).suffix.lower() in (".cmd", ".bat", ".ps1"):
            nat = _native_from_package(Path(resolved).parent / "node_modules" / "@openai" / "codex")
            if nat:
                return [nat], f"{source} (shim resolved to the native binary)"
            return [resolved], f"{source} (shell shim; timeouts and %VAR% in prompts are unreliable)"
        return [resolved], source
    w = shutil.which("codex")
    if w:
        real = Path(os.path.realpath(w))
        for pkg in (Path(w).parent / "node_modules" / "@openai" / "codex", real.parent.parent):
            if (pkg / "package.json").exists():
                nat = _native_from_package(pkg)
                if nat:
                    return [nat], "npm package (native binary)"
                js = pkg / "bin" / "codex.js"
                node = shutil.which("node")
                if js.exists() and node:
                    return [node, str(js)], "npm package (node launcher)"
        if os.name == "nt" and Path(w).suffix.lower() in (".cmd", ".bat", ".ps1", ""):
            for ext in (".exe", ".cmd", ".bat"):
                alt = Path(w).with_suffix(ext)
                if alt.exists():
                    return [str(alt)], "PATH (shell shim; timeouts and %VAR% in prompts are unreliable)"
        return [w], "PATH"
    if os.name == "nt":
        la = os.environ.get("LOCALAPPDATA")
        if la:
            hits = glob.glob(os.path.join(la, "OpenAI", "Codex", "bin", "*", "codex.exe"))
            if hits:
                return [max(hits, key=os.path.getmtime)], "Codex Desktop bundle"
        # npm's global prefix, for a double-clicked exe whose PATH does not include it.
        appdata = os.environ.get("APPDATA")
        if appdata:
            pkg = Path(appdata) / "npm" / "node_modules" / "@openai" / "codex"
            if (pkg / "package.json").exists():
                nat = _native_from_package(pkg)
                if nat:
                    return [nat], "npm global package (%APPDATA%)"
    else:
        for c in ("/Applications/Codex.app/Contents/Resources/codex",
                  os.path.expanduser("~/Applications/Codex.app/Contents/Resources/codex")):
            if os.path.exists(c):
                return [c], "Codex Desktop bundle (unverified location)"
    return None, "not found on PATH"


def kill_tree(p: subprocess.Popen) -> None:
    """Kill the child and everything it spawned (MCP servers, node launchers, ...)."""
    if os.name == "nt":
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(p.pid)], capture_output=True, **_NO_WINDOW)
    else:
        try:
            os.killpg(os.getpgid(p.pid), signal.SIGKILL)
        except Exception:
            p.kill()


class Canceller:
    """Lets another thread (the GUI) stop a running check: kills the current codex process
    tree and makes run_check() stop before the next probe."""

    def __init__(self) -> None:
        self.event = threading.Event()
        self.proc: Optional[subprocess.Popen] = None
        self.extra: List[subprocess.Popen] = []  # helpers such as mitmdump, killed on cancel too
        self.killed = False  # a running codex process was actually killed

    def attach(self, p: subprocess.Popen) -> None:
        self.proc = p
        if self.event.is_set():
            kill_tree(p)
            self.killed = True

    def attach_extra(self, p: subprocess.Popen) -> None:
        self.extra.append(p)
        if self.event.is_set():
            kill_tree(p)

    def cancel(self) -> None:
        self.event.set()
        p = self.proc
        if p is not None and p.poll() is None:
            kill_tree(p)
            self.killed = True
        for x in self.extra:
            if x.poll() is None:
                kill_tree(x)

    def cancelled(self) -> bool:
        return self.event.is_set()


def run_capture(cmd: List[str], timeout: float, env: Optional[dict] = None, cwd: Optional[str] = None,
                on_start=None) -> Tuple[Optional[int], bytes, bytes, bool]:
    """(returncode, stdout, stderr, timed_out). The whole process tree is killed on timeout;
    otherwise grandchildren holding the pipes would make the timeout meaningless.
    `on_start(popen)` is called right after the process starts (used for cancellation)."""
    kw = dict(_NO_WINDOW) if os.name == "nt" else {"start_new_session": True}
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL,
                         env=env, cwd=cwd, **kw)
    if on_start is not None:
        on_start(p)
    try:
        out, err = p.communicate(timeout=timeout)
        return p.returncode, out, err, False
    except subprocess.TimeoutExpired:
        kill_tree(p)
        try:
            out, err = p.communicate(timeout=15)
        except subprocess.TimeoutExpired:
            out, err = b"", b""
        return p.returncode, out, err, True
    except BaseException:  # Ctrl-C: do not leave codex running (and spending quota) in its own session
        kill_tree(p)
        raise


def run_quiet(cmd: List[str], timeout: float = 60, on_start=None) -> Tuple[int, str]:
    try:
        rc, out, err, _ = run_capture(cmd, timeout, on_start=on_start)
        return (rc if rc is not None else -1), (out + err).decode("utf-8", "replace")
    except OSError as e:
        return -1, str(e)


def toml_str(value: str) -> str:
    return json.dumps(value)  # a JSON string is a valid TOML basic string for plain model names


def build_codex_cmd(codex: List[str], model: str, effort: str, tier: Optional[str], prompt: str,
                    ephemeral: bool) -> List[str]:
    cmd = list(codex) + ["exec"]
    if ephemeral:
        cmd.append("--ephemeral")
    cmd += [
        "-c", f"model={toml_str(model)}",
        "-c", f"model_reasoning_effort={toml_str(effort)}",
        "-c", "notify=[]",
        "-s", "read-only",
        "--skip-git-repo-check",
        "--color", "never",
    ]
    if tier:
        cmd += ["-c", f"service_tier={toml_str(tier)}"]
    cmd.append(prompt)
    return cmd


# ------------------------------------------------------------------- wire mode
WIRE_ADDON = r'''
import json, os
from mitmproxy import http

OUT = os.environ["CMC_WIRE_OUT"]

def websocket_message(flow: http.HTTPFlow):
    if "/backend-api/codex/responses" not in flow.request.pretty_url:
        return
    msg = flow.websocket.messages[-1]
    data = msg.content if isinstance(msg.content, str) else msg.content.decode("utf-8", "replace")
    with open(OUT, "a", encoding="utf-8") as f:
        f.write(json.dumps({"dir": "c2s" if msg.from_client else "s2c", "text": data}) + "\n")
'''


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_for(pred, timeout: float) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        if pred():
            return True
        time.sleep(0.2)
    return False


def port_open(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.3)
        return s.connect_ex(("127.0.0.1", port)) == 0


class WireProxy:
    """mitmproxy in regular mode with a throw-away CA, recording Codex's responses WebSocket."""

    def __init__(self, workdir: Path):
        self.workdir = workdir
        self.port = free_port()
        # Private dir (0700 from mkdtemp) for the addon, the recording and the ephemeral CA.
        self.private = Path(tempfile.mkdtemp(prefix="cmc-mitm-"))
        self.jsonl = self.private / "wire-frames.jsonl"
        self.addon = self.private / "wire_addon.py"
        self.ca = self.private / "mitmproxy-ca-cert.pem"
        self.proc: Optional[subprocess.Popen] = None

    def start(self, cancel: Optional["Canceller"] = None) -> None:
        mitmdump = shutil.which("mitmdump")
        if not mitmdump:
            raise RuntimeError("--wire needs mitmproxy: pip install mitmproxy (then `mitmdump` must be on PATH)")
        _, ver = run_quiet([mitmdump, "--version"], 30)
        m = re.search(r"Mitmproxy:\s*(\d+)", ver)
        if m and int(m.group(1)) < MITMPROXY_MIN_MAJOR:
            raise RuntimeError(f"mitmproxy {m.group(1)}.x is too old; need {MITMPROXY_MIN_MAJOR}+ (pip install -U mitmproxy)")
        self.addon.write_text(WIRE_ADDON, encoding="utf-8")
        env = dict(os.environ, CMC_WIRE_OUT=str(self.jsonl), PYTHONDONTWRITEBYTECODE="1")
        self.proc = subprocess.Popen(
            [mitmdump, "--mode", "regular", "--listen-host", "127.0.0.1", "--listen-port", str(self.port),
             "--set", f"confdir={self.private}", "--set", "websocket=true", "-q", "-s", str(self.addon)],
            stdout=(self.workdir / "mitmdump.log").open("wb"), stderr=subprocess.STDOUT, env=env,
            stdin=subprocess.DEVNULL, **_NO_WINDOW,
        )
        if cancel is not None:
            cancel.attach_extra(self.proc)  # so that cancelling (or closing the window) kills it
        cancelled = (lambda: cancel.cancelled()) if cancel is not None else (lambda: False)
        if not wait_for(lambda: cancelled() or (port_open(self.port) and self.ca.exists()), 30):
            raise RuntimeError("mitmdump did not start; see " + display_path(self.workdir / "mitmdump.log"))
        if cancelled():
            raise RuntimeError("cancelled")

    def env(self) -> Tuple[dict, List[str]]:
        """(env vars to add, env vars to remove) for the Codex child process."""
        proxy = f"http://127.0.0.1:{self.port}"
        add = {
            "HTTPS_PROXY": proxy, "HTTP_PROXY": proxy, "ALL_PROXY": proxy,
            "https_proxy": proxy, "http_proxy": proxy, "all_proxy": proxy,
            # Codex's own custom-CA hook (codex_http_client::custom_ca). Nothing is installed system-wide.
            "CODEX_CA_CERTIFICATE": str(self.ca), "SSL_CERT_FILE": str(self.ca),
        }
        return add, ["NO_PROXY", "no_proxy"]  # an inherited NO_PROXY would silently bypass the proxy

    def take_frames(self) -> Tuple[List[dict], List[str], str]:
        """Return (server frames, requested models, raw JSONL text) and reset the recording."""
        if not self.jsonl.exists():
            return [], [], ""
        text = self.jsonl.read_text(encoding="utf-8", errors="replace")
        self.jsonl.unlink()
        frames, requested = parse_wire_frames(text)
        return frames, requested, text

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        shutil.rmtree(self.private, ignore_errors=True)  # unredacted recording, addon and CA key


# ------------------------------------------------------------------- probing
def run_probe(codex: List[str], probe: Probe, prompt: str, timeout: float, ephemeral: bool,
              outdir: Path, wire: Optional[WireProxy], cancel: Optional[Canceller] = None) -> Probe:
    env = dict(os.environ)
    env["RUST_LOG"] = TRACE_FILTER
    env.pop("RUST_LOG_STYLE", None)
    if wire:
        add, drop = wire.env()
        env.update(add)
        for k in drop:
            env.pop(k, None)
    cmd = build_codex_cmd(codex, probe.requested, probe.effort, probe.tier, prompt, ephemeral)
    tag = f"probe-{probe.index:02d}-{re.sub(r'[^A-Za-z0-9.-]+', '_', probe.requested)}"
    t0 = time.time()
    try:
        rc, stdout, stderr, timed_out = run_capture(cmd, timeout, env=env, cwd=str(outdir),
                                                    on_start=cancel.attach if cancel else None)
    except OSError as e:
        probe.notes.append(f"could not start codex: {sanitize_log(str(e))}")
        return probe
    probe.exit_code, probe.timed_out = rc, timed_out
    probe.duration_s = round(time.time() - t0, 1)
    err_text = stderr.decode("utf-8", "replace")
    out_text = stdout.decode("utf-8", "replace")
    m = BANNER_MODEL_RE.search(err_text)
    probe.banner_model = m.group(1) if m else None

    frames, sent, unparsed = parse_trace_frames(err_text)
    probe.frames_sent, probe.frames_unparsed = sent, unparsed
    if wire:
        wframes, wreq, wire_text = wire.take_frames()
        if wire_text:
            (outdir / f"{tag}.wire.jsonl").write_text(sanitize_wire_jsonl(wire_text), encoding="utf-8")
        if wframes:
            frames = wframes
            probe.wire_requested = wreq
        else:
            probe.notes.append("nothing seen on the wire (see mitmdump.log; older Codex builds ignore "
                               "CODEX_CA_CERTIFICATE and fail the TLS handshake); using trace frames instead")
    probe.frames_received = len(frames)
    probe.responses, probe.stream_errors = collect_responses(frames)
    probe.rate_limits = collect_rate_limits(frames)
    probe.metadata_headers = collect_metadata_headers(frames)

    log = outdir / f"{tag}.stderr.log"
    log.write_text(sanitize_log(err_text), encoding="utf-8")
    (outdir / f"{tag}.stdout.log").write_text(sanitize_log(out_text), encoding="utf-8")
    probe.log_path = display_path(log)

    # Only a probe that actually lost its process counts as cancelled; Cancel pressed while a
    # finished probe is being post-processed does not.
    was_cancelled = cancel is not None and cancel.cancelled() and cancel.killed
    if was_cancelled:
        probe.notes.append("cancelled by the user")
    elif timed_out:
        probe.notes.append(f"codex exec did not finish within {timeout:.0f}s and was killed")
    if probe.unsupported():
        probe.notes.append(f"the server refused {probe.requested} for this account; a warm-up answered by "
                           "another model here is the plan's default, not a substitution")
    if was_cancelled:
        pass  # a killed process explains everything below; no diagnosis needed
    elif not probe.responses and not probe.stream_errors:
        if probe.frames_unparsed and not probe.frames_received:
            probe.notes.append(f"{probe.frames_unparsed} frames received but none could be parsed (log format changed?)")
        elif rc not in (0, None) and not timed_out:
            last = last_meaningful_stderr_line(sanitize_log(err_text))
            probe.notes.append(f"codex exited with code {rc} before any model response"
                               + (f": {last}" if last else "") + " (not signed in? run `codex login`)")
        elif probe.frames_sent == 0 and probe.frames_received == 0:
            probe.notes.append("no WebSocket traffic seen. Older Codex versions stream over HTTP instead of a "
                               "WebSocket; try --wire, or upgrade Codex")
        elif probe.frames_received == 0:
            probe.notes.append("WebSocket frames were sent but none received")
    elif rc not in (0, None) and not timed_out and probe.verdict() not in ("ERROR",):
        probe.notes.append(f"codex exited with code {rc}")
    if probe.banner_model and probe.banner_model.lower() != probe.requested.lower():
        probe.notes.append(f"codex reported model '{probe.banner_model}' in its banner, expected '{probe.requested}'")
    if probe.wire_requested and any(m.lower() != probe.requested.lower() for m in probe.wire_requested):
        probe.notes.append(f"wire request frames carried model(s) {sorted(set(probe.wire_requested))}")
    turns = probe.turns()
    tv = [r.verdict(probe.requested) for r in turns]
    if probe.verdict() == "REROUTED":
        if turns and all(v == "ok" for v in tv):
            probe.notes.append("only the warm-up request was served by another model; the turn itself was served as requested")
        elif turns and all(v == "ERROR" for v in tv):
            codes = ", ".join(sorted({r.error_code or "?" for r in turns}))
            probe.notes.append(f"the turn failed ({codes}); the verdict rests on the warm-up response")
        elif not turns:
            probe.notes.append("no turn response was seen; the verdict rests on the warm-up response")
    elif not turns and probe.responses:
        if len(probe.responses) == 1:
            if probe.responses[0].verdict(probe.requested) == "ERROR":
                probe.notes.append("the warm-up request failed; no turn was started")
            else:
                probe.notes.append("only the warm-up response was seen; the turn never completed, so the model could not be confirmed")
        else:
            probe.notes.append("no response carried previous_response_id; the last response was taken as the turn")
    for r in probe.responses:
        if not r.models_seen:
            probe.notes.append(f"response {short_id(r.response_id)} carried no model field")
        elif r.status not in TERMINAL_STATUSES:
            probe.notes.append(f"response {short_id(r.response_id)} never completed (last status: {r.status or '?'})")
        elif r.status != "completed" and r.verdict(probe.requested) == "UNKNOWN":
            probe.notes.append(f"response {short_id(r.response_id)} ended with status {r.status}, not completed")
    for r in probe.responses:
        probe.notes.extend(r.notes(probe.requested))
    return probe


# ------------------------------------------------------------------- reporting
def short_id(rid: str) -> str:
    return rid if len(rid) <= 24 else rid[:14] + ".." + rid[-6:]


def fmt_time(ts: object) -> str:
    try:
        return _dt.datetime.fromtimestamp(int(ts), _dt.timezone.utc).strftime("%H:%M:%SZ")  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError, OSError):
        return "-" if ts in (None, "") else str(ts)[:10]


def _continuation(text: str, width: int = 110) -> List[str]:
    words, lines, cur = text.split(), [], ""
    for w in words:
        if cur and len(cur) + 1 + len(w) > width:
            lines.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}" if cur else w
    if cur:
        lines.append(cur)
    return ["     " + l for l in lines]


def summarize(probes: List[Probe]) -> Tuple[str, int, List[str]]:
    """Overall verdict, exit code and the summary lines."""
    main = [p for p in probes if not p.is_control]
    ctrl = [p for p in probes if p.is_control]
    lines: List[str] = []
    if not probes:
        return "ERROR", 1, ["VERDICT: nothing was checked."]
    rerouted = sorted({p.requested for p in main if p.verdict() == "REROUTED"})
    ok = sorted({p.requested for p in main if p.verdict() == "ok"} - set(rerouted))
    unsupported = sorted({p.requested for p in main if p.verdict() == "UNSUPPORTED"} - set(rerouted) - set(ok))
    unchecked = sorted({p.requested for p in main} - set(rerouted) - set(ok) - set(unsupported))
    ctrl_rerouted = [p for p in ctrl if p.verdict() == "REROUTED"]
    plan = next((p.rate_limits.get("plan_type") for p in probes if p.rate_limits), None)
    plan_s = f" (plan: {plan})" if plan else ""

    if rerouted:
        parts = []
        for model in rerouted:
            scored = [r for p in main if p.requested == model for r in p.responses]
            bad = [r for r in scored if r.verdict(model) == "REROUTED"]
            served = sorted({m for r in bad for m in r.models_seen if not models_match(model, m)[0]})
            parts.append(f"{model} -> {', '.join(served)} ({len(bad)} of {len(scored)} responses)")
        lines.append("VERDICT: REROUTED - served by a different model: " + "; ".join(parts) + ".")
        if any(p.verdict() == "ok" for p in main if p.requested in rerouted):
            lines.append("note: the substitution was intermittent within this run (some repeats were served correctly).")
        overall, code = "REROUTED", 2
    elif ctrl_rerouted:
        lines.append("VERDICT: REROUTED - the control model " + ", ".join(sorted({p.requested for p in ctrl_rerouted}))
                     + " was served by a different model" + (f"; {', '.join(ok)} was fine." if ok else "."))
        overall, code = "REROUTED", 2
    elif unsupported and not ok and not unchecked:
        lines.append(f"VERDICT: UNSUPPORTED - this account cannot use {', '.join(unsupported)}{plan_s}; "
                     "the server refused the model, which is not a substitution. Check a model your plan includes.")
        overall, code = "UNSUPPORTED", 1
    elif unchecked or unsupported:
        parts = []
        if unchecked:
            parts.append("could not check " + ", ".join(unchecked) + " (see notes / ERROR rows)")
        if unsupported:
            parts.append(f"{', '.join(unsupported)} is not available on this account{plan_s}")
        lines.append("VERDICT: " + "; ".join(parts) + (f"; {', '.join(ok)} was served as requested." if ok else "."))
        overall, code = "ERROR", 1
    else:
        lines.append(f"VERDICT: OK - {', '.join(ok)} was served as requested.")
        if any(p.verdict() != "ok" for p in main):
            lines.append("note: some repeats could not be checked (see the ERROR rows and notes).")
        overall, code = "OK", 0
    if ok and rerouted:
        lines.append(f"served correctly: {', '.join(ok)}.")
    if unchecked and overall != "ERROR":
        lines.append(f"could not check: {', '.join(unchecked)}.")
    by_model: Dict[str, List[str]] = {}
    for p in ctrl:
        by_model.setdefault(p.requested, []).append(p.verdict())
    for model, cvs in by_model.items():
        n_ok, n_bad, n = cvs.count("ok"), cvs.count("REROUTED"), len(cvs)
        if n_bad and n_ok:
            rest = ""
            if n_ok + n_bad < n:
                rest = "; the rest ended with " + ", ".join(sorted({v for v in cvs if v not in ("ok", "REROUTED")}))
            lines.append(f"control: {model} was served correctly in {n_ok} of {n} probes and by a different model in {n_bad}{rest}.")
        elif n_bad and n_bad < n:
            others = ", ".join(sorted({v for v in cvs if v != "REROUTED"}))
            lines.append(f"control: {model} was served by a different model in {n_bad} of {n} probes; the rest ended with {others}.")
        elif n_bad:
            if rerouted:
                lines.append(f"control: {model} was also served by a different model; this is not limited to one model.")
        elif n_ok == n:
            lines.append(f"control: {model} was served correctly" +
                         (", so the substitution is model-specific." if rerouted else "."))
        elif n_ok:
            others = ", ".join(sorted({v for v in cvs if v != "ok"}))
            lines.append(f"control: {model} was served correctly in {n_ok} of {n} probes; the rest ended with {others}.")
        elif "UNSUPPORTED" in cvs:
            lines.append(f"control: {model} is not available on this account{plan_s}; pick a control model your plan includes.")
        else:
            lines.append(f"control: {model} probe ended with {', '.join(sorted(set(cvs)))}.")
    return overall, code, lines


def account_line(probes: List[Probe]) -> Optional[str]:
    rl = next((p.rate_limits for p in probes if p.rate_limits), None)
    if not rl:
        return None
    prim = (rl.get("rate_limits") or {}).get("primary") or {}
    lr = (rl.get("rate_limits") or {}).get("limit_reached")
    wm = prim.get("window_minutes")
    window = f"{wm // 1440}-day" if isinstance(wm, int) and wm % 1440 == 0 else (f"{wm}-min" if wm else "?")
    return f"plan={rl.get('plan_type')}  primary usage={prim.get('used_percent')}% of {window} window  limit_reached={lr}"


def render_report(probes: List[Probe], codex_desc: str, codex_version: str, method: str, outdir: Path,
                  full_ids: bool, model_source: str, summary: Optional[Tuple[str, int, List[str]]] = None
                  ) -> Tuple[str, str, int]:
    """(report text, overall verdict, exit code). `summary` overrides summarize() (cancelled runs)."""
    out: List[str] = []
    now = _dt.datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %z")
    out.append(f"codex-routing-detector {__version__}   {now}   method={method}")
    out.append(f"codex binary : {codex_desc}  ({codex_version})")
    out.append(f"models       : {', '.join(sorted({p.requested for p in probes if not p.is_control}))} ({model_source})"
               + (f"; control {', '.join(sorted({p.requested for p in probes if p.is_control}))}" if any(p.is_control for p in probes) else ""))
    acct = account_line(probes)
    if acct:
        out.append(f"account      : {acct}")
    out.append("")
    # columns grow with long names such as gpt-daybreak-blue-latest instead of pushing the row out of line
    wr = max([16] + [len(p.requested) for p in probes])
    ws = max([16] + [len(r.model or "?") for p in probes for r in p.responses])
    hdr = f"{'#':>2} {'requested':<{wr}} {'eff':<6} {'tier':<9} {'kind':<7} {'served':<{ws}} {'status':<10} {'created':<10} {'verdict':<9} response id"
    out.append(hdr)
    out.append("-" * len(hdr))
    for p in probes:
        tier = p.tier or "(config)"
        if not p.responses and not p.stream_errors:
            out.append(f"{p.index:>2} {p.requested:<{wr}} {p.effort:<6} {tier:<9} {'-':<7} {'-':<{ws}} {'-':<10} {'-':<10} {'NO_DATA':<9} -")
        for r in p.responses:
            rid = r.response_id if full_ids else short_id(r.response_id)
            v = r.verdict(p.requested)
            out.append(f"{p.index:>2} {p.requested:<{wr}} {p.effort:<6} {tier:<9} {r.kind:<7} {(r.model or '?'):<{ws}} "
                       f"{(r.status or '?'):<10} {fmt_time(r.created_at):<10} {v:<9} {rid}")
            if v == "ERROR" or r.error_code or r.error_message:  # a rerouted response can also have failed
                out.extend(_continuation(f"error {r.error_code or '?'}: {r.error_message or ''}"))
        for code, msg in p.stream_errors:
            # the same per-row verdict the windows show; a refused model is not a server error
            v = "UNSUPPORTED" if is_unsupported_error(code, msg) else "ERROR"
            out.append(f"{p.index:>2} {p.requested:<{wr}} {p.effort:<6} {tier:<9} {'-':<7} {'-':<{ws}} {'-':<10} {'-':<10} {v:<9} -")
            out.extend(_continuation(f"error {code or '?'}: {msg or ''}"))
        for n in p.notes:
            out.extend(_continuation("note: " + n))
    out.append("")
    overall, code, lines = summary if summary is not None else summarize(probes)
    out.extend(lines)
    out.append(f"raw logs     : {display_path(outdir)}")
    return "\n".join(out), overall, code


def print_report(probes: List[Probe], codex_desc: str, codex_version: str, method: str, outdir: Path,
                 full_ids: bool, model_source: str) -> Tuple[str, int]:
    text, overall, code = render_report(probes, codex_desc, codex_version, method, outdir, full_ids, model_source)
    print(text)
    return overall, code


def to_json(probes: List[Probe], codex_desc: str, codex_version: str, method: str, overall: str, code: int,
            outdir: Path) -> dict:
    return {
        "tool": "codex-routing-detector", "version": __version__,
        "time": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
        "codex": {"command": codex_desc, "version": codex_version}, "method": method,
        "overall": {"verdict": overall, "exit_code": code}, "log_dir": display_path(outdir),
        "probes": [
            {**{k: v for k, v in asdict(p).items() if k not in ("responses", "rate_limits", "metadata_headers")},
             "verdict": p.verdict(),
             "responses": [{**asdict(r), "verdict": r.verdict(p.requested)} for r in p.responses],
             "rate_limits": p.rate_limits, "metadata_headers": p.metadata_headers}
            for p in probes
        ],
    }


# --------------------------------------------------------------- update check
EXE_ASSET_NAME = "codex-routing-detector.exe"
REPO = "darkdarkcocoa/codex-routing-detector"
RELEASES_URL = f"https://github.com/{REPO}/releases"
LATEST_API_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
NO_UPDATE_ENV = "CODEX_ROUTING_DETECTOR_NO_UPDATE"


def version_tuple(v: str) -> Tuple[int, ...]:
    """'v1.2.10' -> (1, 2, 10); anything non-numeric is ignored."""
    return tuple(int(x) for x in re.findall(r"\d+", v)) or (0,)


def check_for_update(current: str = __version__, timeout: float = 4.0, fetch=None) -> Optional[dict]:
    """Return {"version", "url"} when GitHub has a newer release, None otherwise (also on any
    error). One anonymous GET to api.github.com; disabled when NO_UPDATE_ENV is set."""
    if os.environ.get(NO_UPDATE_ENV):
        return None
    try:
        if fetch is None:
            import urllib.request
            req = urllib.request.Request(LATEST_API_URL, headers={"User-Agent": f"codex-routing-detector/{current}",
                                                                   "Accept": "application/vnd.github+json"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8", "replace"))
        else:
            data = fetch()
        tag = str(data.get("tag_name") or data.get("name") or "")
        if not tag or version_tuple(tag) <= version_tuple(current):
            return None
        info = {"version": tag.lstrip("vV"), "url": data.get("html_url") or RELEASES_URL, "asset": None}
        for a in data.get("assets") or []:
            if isinstance(a, dict) and a.get("name") == EXE_ASSET_NAME and a.get("browser_download_url"):
                info["asset"] = {"url": a["browser_download_url"], "size": a.get("size"), "digest": a.get("digest")}
                break
        return info
    except Exception:
        return None


# ---------------------------------------------------------------- self update
def is_frozen() -> bool:
    """True inside the PyInstaller build (the only case where self-replacement makes sense)."""
    return bool(getattr(sys, "frozen", False)) and os.name == "nt"


def download_file(url: str, dest: Path, progress=None, timeout: float = 30.0) -> None:
    """Stream `url` to `dest`; progress(done_bytes, total_bytes_or_None) is called as data arrives."""
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": f"codex-routing-detector/{__version__}"})
    with urllib.request.urlopen(req, timeout=timeout) as resp, dest.open("wb") as out:
        total = resp.headers.get("Content-Length")
        total_n = int(total) if total and total.isdigit() else None
        done = 0
        while True:
            chunk = resp.read(256 * 1024)
            if not chunk:
                break
            out.write(chunk)
            done += len(chunk)
            if progress is not None:
                progress(done, total_n)


def verify_download(path: Path, expected_size: Optional[int] = None, digest: Optional[str] = None) -> Optional[str]:
    """Return None when the file looks like the released exe, else a reason."""
    try:
        size = path.stat().st_size
    except OSError as e:
        return f"download missing: {e}"
    if size < 1_000_000:
        return f"download too small ({size} bytes)"
    if expected_size and size != int(expected_size):
        return f"size mismatch (got {size}, expected {expected_size})"
    with path.open("rb") as f:
        if f.read(2) != b"MZ":
            return "not a Windows executable"
    if digest and str(digest).lower().startswith("sha256:"):
        import hashlib
        h = hashlib.sha256()
        with path.open("rb") as f:
            for block in iter(lambda: f.read(1 << 20), b""):
                h.update(block)
        if h.hexdigest() != str(digest)[7:].lower():
            return "SHA-256 mismatch"
    return None


def self_update_script(target: Path, new: Path, pid: int, relaunch_args: List[str]) -> str:
    """cmd script: wait for `pid` to exit, swap the exe, start the new one, delete itself."""
    args = " ".join(f'"{a}"' for a in relaunch_args)
    log = new.with_suffix(".update.log")  # a short trace of what the helper did, for support
    # No pipelines here: in a console-less (DETACHED_PROCESS) cmd.exe, `tasklist | find` hangs
    # forever. Windows refuses to overwrite a running exe, so retrying `move` until it succeeds
    # is both the wait-for-exit and the swap (about a minute at most).
    return "\r\n".join([
        "@echo off",
        f'echo helper started for pid {pid} > "{log}"',
        "set N=0",
        ":swap",
        f'move /y "{new}" "{target}" >> "{log}" 2>&1',
        "if not errorlevel 1 goto run",
        "set /a N+=1",
        "if %N% geq 60 goto fail",
        "ping -n 2 127.0.0.1 >nul",
        "goto swap",
        ":run",
        f'echo starting new version >> "{log}"',
        f'start "" "{target}" {args}'.rstrip(),
        f'del "{log}"',
        "goto done",
        ":fail",
        f'echo giving up: could not replace the exe >> "{log}"',
        ":done",
        'del "%~f0"',
        "",
    ])


def launch_replacer(target: Path, new: Path, relaunch_args: List[str]) -> Path:
    """Write the swap script next to the temp exe and start it detached; the caller must exit."""
    script = new.with_suffix(".update.cmd")
    script.write_text(self_update_script(target, new, os.getpid(), relaunch_args), encoding="utf-8")
    base = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NO_WINDOW", 0)
    breakaway = 0x01000000  # CREATE_BREAKAWAY_FROM_JOB: survive a job object that kills children with us
    env = clean_child_env()
    last_error: Optional[Exception] = None
    for flags in (base | breakaway, base):
        try:
            p = subprocess.Popen(["cmd.exe", "/c", str(script)], creationflags=flags, close_fds=True, env=env,
                                 stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError as e:  # breakaway refused by the job: retry without it
            last_error = e
            continue
        time.sleep(0.5)
        if p.poll() is None:
            return script
        last_error = RuntimeError(f"update helper exited at once (code {p.returncode})")
    raise RuntimeError(f"could not start the update helper: {last_error}")


def clean_child_env() -> dict:
    """The environment for the update helper and the relaunched exe. A PyInstaller one-file
    app marks its own child process with _PYI_* / _MEIPASS2 variables; a new instance that
    inherits them believes it is that child and never shows a window."""
    return {k: v for k, v in os.environ.items() if not k.upper().startswith(("_PYI", "_MEIPASS"))}


def dir_writable(path: Path) -> bool:
    try:
        probe = path / f".write-test-{os.getpid()}"
        probe.write_bytes(b"x")
        probe.unlink()
        return True
    except OSError:
        return False


# ------------------------------------------------------------------ run_check
@dataclass
class CheckOptions:
    models: List[str] = field(default_factory=list)  # empty: model from config.toml, else FALLBACK_MODEL
    control: Optional[str] = DEFAULT_CONTROL          # None: no control probe
    effort: str = "low"
    tier: Optional[str] = None                        # None: whatever config.toml says
    repeat: int = 1
    prompt: str = DEFAULT_PROMPT
    timeout: float = 240
    codex: Optional[str] = None
    wire: bool = False
    out_dir: Optional[str] = None


@dataclass
class CheckResult:
    probes: List[Probe] = field(default_factory=list)
    codex_desc: str = ""
    codex_version: str = ""
    how: str = ""
    method: str = "trace"
    model_source: str = ""
    outdir: Optional[Path] = None
    overall: str = "ERROR"
    exit_code: int = 1
    summary_lines: List[str] = field(default_factory=list)
    error: Optional[str] = None       # fatal setup problem (codex not found, mitmproxy failed)
    error_kind: Optional[str] = None  # "codex_missing" | "codex_failed" | "wire" | "cancelled"
    cancelled: bool = False

    def report(self, full_ids: bool = False) -> str:
        if self.error:
            return self.error
        summary = (self.overall, self.exit_code, self.summary_lines) if self.cancelled else None
        text, _, _ = render_report(self.probes, self.codex_desc, self.codex_version, self.method,
                                   self.outdir or Path("."), full_ids, self.model_source, summary)
        return text

    def json(self) -> dict:
        return to_json(self.probes, self.codex_desc, self.codex_version, self.method, self.overall,
                       self.exit_code, self.outdir or Path("."))


def run_check(opts: CheckOptions, progress=None, cancel: Optional[Canceller] = None) -> CheckResult:
    """Run the whole check. `progress(event, info)` receives ("start", {...}),
    ("probe_start", {...}) and ("probe_done", {...}); `cancel` stops it early."""
    def emit(event: str, **info) -> None:
        if progress is not None:
            progress(event, info)

    res = CheckResult()
    cfg_model, cfg_tier, cfg_source = read_config_values()
    codex, how = find_codex(opts.codex)
    if not codex:
        res.error = (f"codex binary not found ({how}). Install Codex (npm i -g @openai/codex) and sign in, "
                     f"or set the CODEX_BIN environment variable to the codex binary (command line: --codex PATH).")
        res.error_kind = "codex_missing"
        return res
    res.how = how
    res.codex_desc = " ".join(display_path(c) for c in codex)
    on_start = cancel.attach if cancel is not None else None  # even the version probe must be cancellable

    def is_cancelled() -> bool:
        if cancel is not None and cancel.cancelled():
            res.cancelled, res.overall, res.exit_code = True, "CANCELLED", 1
            res.summary_lines = ["VERDICT: CANCELLED before the first probe."]
            return True
        return False

    rc, ver = run_quiet(codex + ["--version"], on_start=on_start)
    if is_cancelled():
        return res
    res.codex_version = ver.strip().splitlines()[0] if ver.strip() else "version unknown"
    if rc != 0 and "codex" not in res.codex_version.lower():
        res.error = f"could not run {res.codex_desc}: {ver.strip()[:200]}"
        res.error_kind = "codex_failed"
        return res
    _, help_text = run_quiet(codex + ["exec", "--help"], on_start=on_start)
    if is_cancelled():
        return res
    ephemeral = "--ephemeral" in help_text

    if opts.models:
        models, res.model_source = list(opts.models), "from -m"
    elif cfg_model:
        models, res.model_source = [cfg_model], f"from {cfg_source}"
    else:
        models, res.model_source = [FALLBACK_MODEL], "built-in default"
    tier = opts.tier if opts.tier is not None else cfg_tier
    outdir = Path(opts.out_dir) if opts.out_dir else Path(tempfile.mkdtemp(prefix="codex-routing-detector-"))
    outdir.mkdir(parents=True, exist_ok=True)
    res.outdir = outdir

    wire: Optional[WireProxy] = None
    if opts.wire:
        wire = WireProxy(outdir)
        try:
            wire.start(cancel)
        except RuntimeError as e:
            wire.stop()
            if is_cancelled():
                return res
            res.error, res.error_kind = str(e), "wire"
            return res
        except BaseException:  # Ctrl-C while mitmdump starts: do not leave it running
            wire.stop()
            raise
        res.method = "wire"

    # A provider prefix is dropped before Codex sees the name; each probe notes it (see below).
    spelled: Dict[str, str] = {}
    for name in models + ([opts.control] if opts.control else []):
        if strip_provider_prefix(name) != name.strip():
            spelled[strip_provider_prefix(name)] = name.strip()
    models = [strip_provider_prefix(m) for m in models]
    control_name = strip_provider_prefix(opts.control) if opts.control else None
    plan: List[Tuple[str, bool]] = []
    control = control_name if control_name and control_name.lower() not in {m.lower() for m in models} else None
    for _ in range(max(1, opts.repeat)):
        plan += [(m, False) for m in models]
        if control:
            plan.append((control, True))
    emit("start", n=len(plan), codex_version=res.codex_version, how=how, codex_desc=res.codex_desc)
    try:
        for i, (model, is_control) in enumerate(plan, 1):
            if cancel is not None and cancel.cancelled():
                res.cancelled = True
                break
            probe = Probe(index=i, requested=model, effort=opts.effort, tier=tier, is_control=is_control,
                          method=res.method)
            emit("probe_start", i=i, n=len(plan), model=model, effort=opts.effort, tier=tier)
            run_probe(codex, probe, opts.prompt, opts.timeout, ephemeral, outdir, wire, cancel)
            if model in spelled:
                probe.notes.append(f"requested as {spelled[model]}; checked as {model} (Codex model names "
                                   f"carry no 'openai/' prefix, and the server refuses the prefixed name)")
            res.probes.append(probe)
            emit("probe_done", i=i, n=len(plan), probe=probe)
            # Cancel pressed after the very last probe finished is not a cancellation.
            if cancel is not None and cancel.cancelled() and (i < len(plan) or cancel.killed):
                res.cancelled = True
                break
    finally:
        if wire:
            wire.stop()
    res.overall, res.exit_code, res.summary_lines = summarize(res.probes)
    if res.cancelled:
        note = f"note: the run was cancelled after {len(res.probes)} of {len(plan)} probe(s)."
        if res.overall == "REROUTED":
            res.summary_lines = res.summary_lines + [note]  # evidence already found is kept
        else:
            res.overall, res.exit_code = "CANCELLED", 1
            res.summary_lines = [f"VERDICT: CANCELLED after {len(res.probes)} of {len(plan)} probe(s)."]
    return res


# ---------------------------------------------------------------------- main
class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # exit 1, not argparse's 2 (2 means REROUTED here)
        self.print_usage(sys.stderr)
        print(f"{self.prog}: error: {message}", file=sys.stderr)
        sys.exit(1)


def main(argv: Optional[List[str]] = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except Exception:
        pass
    cfg_model, cfg_tier, cfg_source = read_config_values()
    ap = _Parser(prog="codex-routing-detector", description=__doc__.split("\n\n")[0],
                 formatter_class=argparse.RawDescriptionHelpFormatter,
                 epilog="Exit codes: 0 served as requested, 2 served by another model (any probe, control "
                        "included), 1 check failed or usage error.")
    ap.add_argument("-m", "--model", action="append", dest="models", metavar="MODEL",
                    help=f"model to check (repeatable). Default: `model` from config.toml ({cfg_model or 'not set'}), "
                         f"else {FALLBACK_MODEL}")
    ap.add_argument("--control", default=DEFAULT_CONTROL, metavar="MODEL",
                    help=f"control model checked alongside (default {DEFAULT_CONTROL}; skipped when it equals the "
                         "checked model); use --no-control to skip")
    ap.add_argument("--no-control", action="store_true", help="do not run the control probe")
    ap.add_argument("-e", "--effort", default="low", metavar="LEVEL",
                    help="model_reasoning_effort for the probes (default low, the cheapest; config.toml is not used)")
    ap.add_argument("-t", "--tier", default=None, metavar="TIER",
                    help=f"service_tier override (default: whatever config.toml says: {cfg_tier or 'unset'})")
    ap.add_argument("-r", "--repeat", type=int, default=1, metavar="N", help="run each probe N times (default 1)")
    ap.add_argument("--prompt", default=DEFAULT_PROMPT, metavar="TEXT",
                    help="prompt sent in the probe turn (default: %(default)r)")
    ap.add_argument("--timeout", type=float, default=240, metavar="SEC",
                    help="seconds to wait for each codex exec (default 240)")
    ap.add_argument("--codex", default=None, metavar="PATH", help="codex binary (default: auto-detect; env CODEX_BIN)")
    ap.add_argument("--wire", action="store_true", help="capture with mitmproxy instead of trace logging")
    ap.add_argument("--live", action="store_true",
                    help="watch a real Codex CLI session in a new terminal window instead of sending probes; "
                         "arguments after `--` are passed to codex (default: the interactive TUI)")
    ap.add_argument("--live-dir", default=None, metavar="DIR", help="folder to open Codex in for --live (default: current)")
    ap.add_argument("codex_args", nargs="*", help=argparse.SUPPRESS)
    ap.add_argument("--json", dest="json_path", metavar="FILE", help="write a machine-readable report")
    ap.add_argument("--out", dest="out_dir", metavar="DIR", help="where to keep raw logs (default: a new temp dir)")
    ap.add_argument("--full-ids", action="store_true", help="print full response ids in the table")
    ap.add_argument("--no-update-check", action="store_true",
                    help=f"skip the one request to api.github.com that looks for a newer release (or set {NO_UPDATE_ENV}=1)")
    ap.add_argument("--version", action="version", version=f"codex-routing-detector {__version__}")
    a = ap.parse_args(argv)
    if a.repeat < 1:
        ap.error("--repeat must be at least 1")
    if a.codex_args and not a.live:
        ap.error("positional arguments are only accepted after --live (they are passed to codex)")
    if a.live:
        import codex_routing_live
        return codex_routing_live.run_live_cli(a.codex, a.live_dir, a.codex_args)

    def progress(event: str, info: dict) -> None:
        if event == "start":
            print(f"running {info['n']} probe(s) with {info['codex_version']} [{info['how']}] ...", file=sys.stderr)
        elif event == "probe_start":
            tier_s = f", {info['tier']}" if info.get("tier") else ""
            print(f"  [{info['i']}/{info['n']}] {info['model']} ({info['effort']}{tier_s}) ...",
                  file=sys.stderr, end="", flush=True)
        elif event == "probe_done":
            print(f" {info['probe'].verdict()} ({info['probe'].duration_s}s)", file=sys.stderr)

    opts = CheckOptions(models=a.models or [], control=None if a.no_control else a.control, effort=a.effort,
                        tier=a.tier, repeat=a.repeat, prompt=a.prompt, timeout=a.timeout, codex=a.codex,
                        wire=a.wire, out_dir=a.out_dir)
    update_box: List[Optional[dict]] = [None]
    if not a.no_update_check:
        t = threading.Thread(target=lambda: update_box.__setitem__(0, check_for_update()), daemon=True)
        t.start()  # runs while the probes do; never delays the check itself
    res = run_check(opts, progress=progress)
    if res.error:
        print(res.error, file=sys.stderr)
        return 1
    print(file=sys.stderr)
    print(res.report(a.full_ids))
    if a.json_path:
        Path(a.json_path).write_text(json.dumps(res.json(), indent=2), encoding="utf-8")
        print(f"json report  : {display_path(a.json_path)}")
    upd = update_box[0]
    if upd:
        print(f"update       : version {upd['version']} is available (you have {__version__}): {upd['url']}")
    return res.exit_code


if __name__ == "__main__":
    sys.exit(main())
