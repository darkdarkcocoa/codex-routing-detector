# Codex Routing Detector

`codex-routing-detector`

Find out which model **actually** answers your Codex requests.

Codex lets you pick a model such as `gpt-6-astra`. The server may answer with a different
one (for example `gpt-5.6-luna`) without telling the client. The Codex UI and the local
session logs only record the model you *asked* for, so they cannot show this. This tool runs
one tiny Codex turn per model and reads the model name that the **server** wrote into its own
response object (`response.created` / `response.completed`). That field is the model that
served the request.

A run where the substitution was happening (real capture, 2026-09-22 02:24 UTC, re-rendered
in the current layout; binary path shortened, temp directory name illustrative):

```
$ python codex_routing_detector.py
running 2 probe(s) with codex-cli 0.153.4 [npm package (native binary)] ...
  [1/2] gpt-6-astra (low, priority) ... REROUTED (17.2s)
  [2/2] gpt-5.6-sol (low, priority) ... ERROR (19.7s)

codex-routing-detector 1.1.2   2026-09-22 11:25:26 +0900   method=trace
codex binary : ~\...\codex.exe  (codex-cli 0.153.4)
models       : gpt-6-astra (from config.toml); control gpt-5.6-sol
account      : plan=pro  primary usage=8% of 7-day window  limit_reached=False

 # requested        eff    tier      kind    served           status     created    verdict   response id
---------------------------------------------------------------------------------------------------------
 1 gpt-6-astra      low    priority  warmup  gpt-5.6-luna     completed  02:24:52Z  REROUTED  resp_0b635f3bc..95131c
 1 gpt-6-astra      low    priority  turn    gpt-5.6-luna     completed  02:24:54Z  REROUTED  resp_0b635f3bc..f051a1
 2 gpt-5.6-sol      low    priority  warmup  gpt-5.6-sol      completed  02:25:09Z  ok        resp_043668f54..2b27f7
 2 gpt-5.6-sol      low    priority  turn    gpt-5.6-sol      failed     02:25:11Z  ERROR     resp_043668f54..4f7e6c
     error server_is_overloaded: Our servers are currently overloaded. Please try again later.

VERDICT: REROUTED - served by a different model: gpt-6-astra -> gpt-5.6-luna (2 of 2 responses).
control: gpt-5.6-sol probe ended with ERROR.
raw logs     : ~\AppData\Local\Temp\codex-routing-detector-k3j2x1ab
```

Twenty minutes later the same account was served correctly (the server-side state changes over
time, so repeat the check when it matters):

```
 # requested        eff    tier      kind    served           status     created    verdict   response id
---------------------------------------------------------------------------------------------------------
 1 gpt-6-astra      low    priority  warmup  gpt-6-astra      completed  02:42:38Z  ok        resp_08d709874..f2e677
 1 gpt-6-astra      low    priority  turn    gpt-6-astra      completed  02:42:39Z  ok        resp_08d709874..94ac0d
 2 gpt-5.6-sol      low    priority  warmup  gpt-5.6-sol      completed  02:42:46Z  ok        resp_065f40412..5829ee
 2 gpt-5.6-sol      low    priority  turn    gpt-5.6-sol      completed  02:42:49Z  ok        resp_065f40412..e987f0

VERDICT: OK - gpt-6-astra was served as requested.
control: gpt-5.6-sol was served correctly.
```

## Window version (double-click)

## Install

Pick one:

- **Windows, no Python**: download `codex-routing-detector.exe` from the
  [Releases page](https://github.com/darkdarkcocoa/codex-routing-detector/releases) and double-click it.
  SmartScreen will warn once ("More info" -> "Run anyway"); the file is not code-signed.
- **With Python 3.8+** (any OS):
  ```
  pipx install git+https://github.com/darkdarkcocoa/codex-routing-detector
  codex-routing-detector          # command line
  codex-routing-detector-gui      # window
  ```
  (`pip install git+https://github.com/darkdarkcocoa/codex-routing-detector` works too; add
  `[wire]`, i.e. `...codex-routing-detector[wire]`, to pull in mitmproxy for `--wire`.)
- **Just the files**: `git clone https://github.com/darkdarkcocoa/codex-routing-detector`, then
  `python codex_routing_detector.py` or `run_gui.bat`.

All three need a Codex install (CLI or Desktop) that is signed in with ChatGPT.

![codex-routing-detector window after a live check](docs/screenshot.png)

`codex_routing_detector_gui.py` is the same check behind one **Check** button: pick the model
(defaults to the one in your `config.toml`), press Check, and the table fills in as each probe
finishes, with a colored verdict banner and the details underneath. Buttons copy the text
report, save the JSON report or open the raw-log folder; the button in the corner switches the
labels between English and Korean (`--lang ko` starts in Korean). If the tool cannot find
Codex, the details panel says so; the **Codex...** button lets you pick the binary by hand.
The **Help** menu has the basic instructions, a glossary (warm-up, turn, control, the
verdicts, trace vs wire mode) and an About box, in the current language.

- **Standalone Windows exe** (no Python needed on the PC that runs it): run `build_exe.bat`
  once on a PC with Python (it installs PyInstaller) to produce `dist\codex-routing-detector.exe`,
  a single file you can copy anywhere and double-click. It still needs a signed-in Codex
  install. Windows SmartScreen warns about unsigned downloads: choose "More info" -> "Run
  anyway"; some antivirus products also flag PyInstaller one-file executables, in which case
  use the next option.
- **With Python installed**: double-click `run_gui.bat` (it starts `pythonw`), or run
  `python codex_routing_detector_gui.py`.

The window uses the same verdicts, logs and privacy rules as the command line (below), with the
default prompt, the 240 s timeout and the service tier from `config.toml`; the process exit
code is not meaningful for the window, read the banner instead.

## Requirements

- Python 3.8 or newer. No packages.
- Codex CLI (`npm i -g @openai/codex`) **or** the Codex Desktop app, signed in with ChatGPT.
  The tool looks for `codex` on `PATH` and runs the native binary inside the npm package
  directly (npm and yarn layouts; pnpm only when its `codex` shim is a symlink; falls back to
  `node codex.js`, and on Windows resolves the `codex.cmd` shim to the binary). Without a CLI it tries
  the Windows Desktop bundle (`%LOCALAPPDATA%\OpenAI\Codex\bin\*\codex.exe`) and, unverified,
  `/Applications/Codex.app/Contents/Resources/codex` on macOS. Otherwise pass `--codex PATH`
  or set `CODEX_BIN`.
- Optional, for `--wire`: `pip install mitmproxy` (7.0 or newer).

## Usage

```
python codex_routing_detector.py                      # model from ~/.codex/config.toml + control
python codex_routing_detector.py -m gpt-6-astra       # a specific model
python codex_routing_detector.py -m gpt-6-astra -m gpt-5.5 --no-control
python codex_routing_detector.py -e high -t priority  # probe with a given effort / service tier
python codex_routing_detector.py -r 3                 # repeat each probe 3 times
python codex_routing_detector.py --json result.json --full-ids
python codex_routing_detector.py --wire               # packet-level capture with mitmproxy
```

| Option | Meaning |
|---|---|
| `-m/--model MODEL` | model to check (repeatable). Default: top-level `model` in `~/.codex/config.toml`, else `gpt-6-astra` |
| `--control MODEL` / `--no-control` | control model run alongside (default `gpt-5.6-sol`) |
| `-e/--effort LEVEL` | `model_reasoning_effort` for the probes. Default `low` (cheapest); the value in `config.toml` is **not** used |
| `-t/--tier TIER` | `service_tier` override. Default: whatever `config.toml` says, if anything |
| `-r/--repeat N` | run every probe N times |
| `--prompt TEXT` | prompt used for the probe turn |
| `--timeout SEC` | per-probe timeout (default 240); the whole process tree is killed on timeout |
| `--codex PATH` | codex binary (also `CODEX_BIN`) |
| `--wire` | use mitmproxy instead of trace logging |
| `--json FILE` | machine-readable report |
| `--out DIR` | keep raw logs here (default: a new private temp dir) |
| `--full-ids` | print full response ids (for bug reports) |
| `--version` | print the tool version |

Exit code: `0` every checked model was served as requested (a control probe or a repeat that
hit a server error does not change this; the summary says so), `2` at least one probe (control
included) was served by a different model, `1` a model could not be checked at all, or a usage
error.

## How it works

**trace (default).** The tool runs the real `codex exec` with
`RUST_LOG=tungstenite::protocol=trace,tungstenite::protocol::frame=off`. `tungstenite` is the
WebSocket library underneath Codex. At trace level it logs every message it receives from the
socket, verbatim, before any Codex code sees it. The tool parses those `Received message {...}`
lines and reads `response.model` from the server's `response.created` / `response.completed`
events. Outgoing frames are logged compressed, so the *requested* model is the `-c model=...`
value the tool passes, cross-checked against the `model:` line Codex prints in its banner.

**--wire.** mitmproxy runs as a local HTTPS proxy with a throw-away certificate authority
created in a private temp directory. Codex is started with `HTTPS_PROXY` pointing at the proxy
and `CODEX_CA_CERTIFICATE` pointing at that certificate (Codex's own custom-CA setting), so
nothing is installed into the OS certificate store; the proxy and its temporary certificate are
removed when the run ends, is cancelled, or the window is closed. Both
directions of the responses WebSocket are recorded, including the requested model in the
client's `response.create` frame. Trace mode and wire mode were checked against each other on
2026-09-22: the server response objects were identical.

Each probe is a fresh Codex session (`--ephemeral` where the Codex version supports it, sandbox
`read-only`, the `notify` hook disabled; your MCP servers and plugins still load). Codex sends
two requests per session: a warm-up request without user input and the real turn. Both are
shown. A response object that names another model, warm-up or turn, makes the probe
`REROUTED` (it is direct evidence); `ok` requires the turn itself to be served as requested,
so a probe whose turn failed is `ERROR`, not `ok`.

## Reading the result

- `REROUTED` - the server's response object names a different model than requested.
  Case differences are accepted silently; a dated snapshot of exactly the requested model
  (`gpt-6-astra-2026-09-01`) is accepted and noted under the row. A model whose name changes
  between `response.created` and `response.completed` is `REROUTED` and noted.
- `ok` - served as requested.
- `ERROR` - the server answered with an error (for example `server_is_overloaded`, which Codex
  shows as "Selected model is at capacity") and the response object, if there was one, named
  the requested model. Run again. (A response that named another model and then failed is
  still `REROUTED`.)
- `UNKNOWN` - the model could not be confirmed: a response object without a `model` field, a
  turn that never reached `completed` (timeout, crash, `incomplete`, `cancelled`), or only the
  warm-up response was seen. The note under the row says which.
- `NO_DATA` - no WebSocket frames were seen. The note under the row quotes Codex's exit code
  and last error line (typically: not signed in, API-key mode, no network), or, if Codex
  exited cleanly without any WebSocket traffic, suggests `--wire` or an upgrade (older Codex
  streams over HTTP). A custom `model_provider` (Bedrock, OSS) never reaches `chatgpt.com` and
  shows up the same way; it cannot be checked with this tool.

The control probe tells the cases apart: if the control model is served correctly while your
model is not, the substitution is specific to that model, not a broken account or client.

## Cost and privacy

- Each probe is two small requests (roughly 12-16k input tokens of system prompt and tool
  definitions, a few output tokens). With the default control that is four requests per run.
  They count against your Codex usage like any other turn.
- Raw logs are kept in the directory printed at the end (a private temp directory unless
  `--out` is given). They contain the server frames: your thread/session ids, the account user
  id in `safety_identifier`, the probe prompt, the plan type and usage percentages. Outgoing
  frames (which would contain the whole request, including the working directory) are dropped
  before saving; in `--wire` mode the client's request frames are reduced to their routing
  fields (`model`, `service_tier`, `reasoning`, ...) and the prompt, tool list and metadata
  are dropped. Authorization headers and cookies are never logged by the chosen log filter;
  the `x-codex-turn-state` token, which the server sends inside a `codex.response.metadata`
  message, is redacted before anything is written; your home directory is written as `~`.
  Delete the directory if you do not need it.
- The `--json` report contains no paths with your username. It does contain the rate-limit
  block (plan, usage, credit balance) because that is useful in a bug report; remove it if
  you would rather not share it.
- In trace mode the tool only runs the Codex binary you already have and makes no network
  calls of its own. In `--wire` mode every HTTPS request Codex makes during the probe
  (including token refresh and telemetry) passes through the local mitmproxy process the tool
  launched on your machine; only the responses WebSocket is recorded.
- The probe runs with the sandbox in `read-only` mode, but a custom `--prompt` can still make
  the model read files and send them to OpenAI, as any Codex turn can. Keep the default prompt
  unless you know what you are doing.

## Reporting

If you see `REROUTED`, the useful facts for a bug report are the response ids, the
`created_at` times (UTC), the requested/served pair, your plan type and usage line, and the
Codex version. `--json` writes all of them. A public tracker for the `gpt-6-astra` ->
`gpt-5.6-luna` case is openai/codex issue #46632.

## Without Python

The same check by hand. Drop `--ephemeral` on Codex versions that do not know the flag.

bash / Git Bash:

```
RUST_LOG='tungstenite::protocol=trace,tungstenite::protocol::frame=off' codex exec --ephemeral -s read-only --skip-git-repo-check \
  -c model=gpt-6-astra "Reply with exactly the single word: pong" 2>&1 </dev/null \
  | grep -o '"type":"response.completed","response":{"id":"[^"]*"[^}]*"model":"[^"]*"' \
  | grep -o '"model":"[^"]*"'
```

PowerShell:

```
$env:RUST_LOG = 'tungstenite::protocol=trace,tungstenite::protocol::frame=off'
codex exec --ephemeral -s read-only --skip-git-repo-check -c model=gpt-6-astra "Reply with exactly the single word: pong" 2>&1 |
  Select-String -Pattern '"type":"response.completed".*?"model":"([^"]+)"' | ForEach-Object { $_.Matches[0].Groups[1].Value }
Remove-Item Env:RUST_LOG
```

Both print the served model once for the warm-up and once for the turn. A turn that failed
(`response.failed`, for example "at capacity") prints nothing; run it again.

## Tests

```
python -m unittest discover -s tests -v
```

`tests/test_gui.py` builds the window off-screen and drives it with the fixture runs; it is
skipped where tkinter has no display. `python codex_routing_detector_gui.py --fake --auto-check`
shows the window with the fixture data instead of a live check (development only; the exe does
not include the fixtures).

The fixtures under `tests/fixtures` are two complete trace runs from 2026-09-22 with every id
replaced by a placeholder: an astra request served by luna, and a request that ended in
`server_is_overloaded`. One test also checks that a timed-out probe kills its whole process
tree.

---

## 한국어 요약

Codex에서 `gpt-6-astra`를 골라도 서버가 `gpt-5.6-luna`로 응답하는 경우가 있습니다. 화면과
로컬 세션 로그는 "요청한 모델"만 기록하기 때문에 이걸 보여주지 못합니다. 이 도구는 모델마다
아주 짧은 Codex 턴을 하나 돌리고, **서버가 직접 써서 보낸 응답 객체**(`response.created` /
`response.completed`)의 `model` 값을 읽어서 실제로 응답한 모델을 알려줍니다.

설치는 셋 중 하나예요.

- Windows, Python 없음: [Releases](https://github.com/darkdarkcocoa/codex-routing-detector/releases)에서
  `codex-routing-detector.exe`를 받아 더블클릭.
- Python 3.8+: `pipx install git+https://github.com/darkdarkcocoa/codex-routing-detector` 후
  `codex-routing-detector`(터미널) 또는 `codex-routing-detector-gui`(창).
- 소스 그대로: `git clone` 후 `python codex_routing_detector.py` 또는 `run_gui.bat`.

```
python codex_routing_detector.py                # config.toml의 모델 + 대조군(gpt-5.6-sol) 확인
python codex_routing_detector.py -m gpt-6-astra # 특정 모델만
python codex_routing_detector.py -r 3           # 3번 반복
python codex_routing_detector.py --wire         # mitmproxy로 패킷 수준 확인 (pip install mitmproxy)
```

- 창 버전: `run_gui.bat`을 더블클릭하거나(Python 필요) `build_exe.bat`으로 만든
  `dist\codex-routing-detector.exe`를 더블클릭하면 창이 뜹니다(exe는 Python 불필요, 로그인된
  Codex는 필요). 모델을 고르고 **Check**를 누르면 표와 판정 배너, 상세 내용이 표시되고,
  보고서 복사·JSON 저장·로그 폴더 열기 버튼이 있습니다. 오른쪽 아래 버튼으로 한국어/영어를
  바꿀 수 있고(`--lang ko`로 시작 가능), Codex를 못 찾으면 **Codex...** 버튼으로 실행 파일을
  직접 고를 수 있어요. 상단 **도움말** 메뉴에 기본 사용법·용어 설명(웜업, 턴, 대조군, 판정,
  trace/wire 모드)·정보가 있어요. exe는 서명이 없어서 처음 실행할 때 SmartScreen 경고가 뜨면
  "추가 정보" → "실행"을 누르면 되고, 백신이 막으면 `run_gui.bat`을 쓰세요.

- 필요한 것: Python 3.8+ (exe 버전은 불필요), 로그인된 Codex CLI 또는 Codex Desktop. 추가 패키지 없음.
- 결과: `REROUTED`(다른 모델이 응답) / `ok`(요청대로) / `ERROR`(서버 오류, 예: capacity) /
  `UNKNOWN`(확인 불가: `model` 필드가 없거나, 턴이 `completed`까지 가지 못했거나, 웜업 응답만
  보임. 행 아래 note에 이유가 적힘) / `NO_DATA`(WebSocket 프레임 없음. 행 아래의
  note에 Codex 종료 코드와 마지막 오류 줄이 적힙니다: 로그인 안 됨 등. 정상 종료인데 프레임이
  없으면 구버전 Codex이니 `--wire` 사용. 사용자 지정 provider는 확인 불가).
- 프로브마다 새 Codex 세션을 씁니다(`--ephemeral`을 지원하는 버전이면 사용, 샌드박스
  read-only). 아래 "Without Python"의 수동 명령에서 구버전이면 `--ephemeral`을 빼세요.
- 종료 코드: 0 정상, 2 바꿔치기 감지(대조군 포함), 1 확인 실패 또는 인자 오류.
- 서버 쪽 상태는 시간에 따라 바뀝니다. 같은 계정이 20분 사이에 REROUTED에서 OK로 바뀐 기록이
  있으니, 필요할 때마다 다시 돌려 보세요.
- 비용: 실행 한 번에 기본 4개 요청(모델 2개 × 웜업+턴). 일반 사용량으로 차감됩니다.
- 로그: 마지막 줄에 찍힌 폴더에 서버 프레임 원문이 남습니다. 스레드 ID, 계정 사용자 ID
  (`safety_identifier`), 프롬프트, 플랜/사용량이 들어 있고, 토큰·쿠키·요청 본문(작업 폴더
  경로 포함)은 기록되지 않습니다. `--json` 보고서에는 사용자 이름이 든 경로가 없습니다.
- `--wire` 모드에서는 프로브 동안 Codex가 보내는 모든 HTTPS 요청이 이 도구가 띄운 로컬
  mitmproxy를 지나갑니다(기록되는 것은 responses WebSocket뿐). 저장되는 기록에서 클라이언트
  요청 프레임은 `model`·`service_tier`·`reasoning` 같은 라우팅 필드만 남기고 프롬프트·도구
  목록·메타데이터는 버립니다. 인증서는 임시 폴더에 만들고 끝나면 지웁니다.
