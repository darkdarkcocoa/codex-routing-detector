# Codex Routing Detector

Shows which model **actually** answers your Codex requests. Run it, press Check, and it tells
you whether the `gpt-6-astra` you selected was really served by `gpt-6-astra` or quietly by
`gpt-5.6-luna`.

![Codex Routing Detector after a live check](docs/screenshot.png)

## Why this exists

In September 2026 many Codex users noticed that `gpt-6-astra` suddenly felt like a smaller
model, alongside bursts of "Selected model is at capacity" errors. Capturing the traffic between
the Codex client and `chatgpt.com` showed why: the request said `model: gpt-6-astra`, but the
server's own response object said `model: gpt-5.6-luna`. Requests for `gpt-5.6-sol`, `terra` and
`luna` in the same minutes were served correctly, the account was nowhere near its usage limit,
and the client was never told. Codex has a `model/rerouted` notification and a "switched
because of usage limits" banner in its protocol, and neither fired. The UI kept saying astra;
the usage meter charged for astra; the answers came from luna. The same thing was reproduced
independently by other people on ordinary Plus and Pro accounts.

You cannot see this from inside Codex: the UI and the local session logs only record the model
you *asked for*. This tool reads the model name the **server** puts into its response objects,
which is the model that actually ran, and reports the mismatch. The state flips over time (the
same account went REROUTED -> OK -> REROUTED within an hour), so check whenever it matters.

## Install

- **Windows, no Python**: download `codex-routing-detector.exe` from
  [Releases](https://github.com/darkdarkcocoa/codex-routing-detector/releases) and double-click it
  (SmartScreen warns once: "More info" -> "Run anyway").
- **Python 3.8+**: `pipx install git+https://github.com/darkdarkcocoa/codex-routing-detector`,
  then `codex-routing-detector-gui` (window) or `codex-routing-detector` (terminal).

Either way you need a Codex CLI or Codex Desktop that is signed in with ChatGPT.

## The window

Pick the model (defaults to the one in your `config.toml`), press **Check**, and the table
fills in as each probe finishes, with a colored verdict banner and the details underneath.
Buttons copy the text report, save it as JSON or open the raw-log folder; the corner button
switches between English and Korean (`--lang ko` starts in Korean). The **Help** menu holds
the instructions and a glossary. If Codex is not found, the details say so and the
**Codex...** button lets you pick the binary by hand.

The window uses the same verdicts, logs and privacy rules as the command line (below), with the
default prompt, the 240 s timeout and the service tier from `config.toml`. `run_gui.bat`
starts the window with an installed Python; `build_exe.bat` rebuilds the exe.
## How Codex is found

The tool looks for `codex` on `PATH` and runs the native binary inside the npm package (npm,
yarn, pnpm-as-symlink; `codex.cmd` on Windows is resolved to the binary). Without a CLI it
tries the Windows Desktop bundle (`%LOCALAPPDATA%\OpenAI\Codexin\*\codex.exe`) and, unverified,
`/Applications/Codex.app/Contents/Resources/codex` on macOS. Otherwise pass `--codex PATH`, set
`CODEX_BIN`, or use the window's **Codex...** button. `--wire` additionally needs
`pip install mitmproxy` (7.0 or newer).

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
- On startup the tool makes one anonymous request to `api.github.com` to see whether a newer
  release exists. Nothing about you is sent. If there is one, the version label in the window
  turns into a red NEW badge that opens the release page, and the command line prints an
  `update` line after the report. Disable the check with `--no-update-check` or the environment
  variable `CODEX_ROUTING_DETECTOR_NO_UPDATE=1`.
- The **Windows exe updates itself**: it downloads the new `codex-routing-detector.exe` from
  the release next to itself, verifies size, `MZ` header and the SHA-256 digest GitHub
  publishes for the asset, swaps the file once the old process has exited, and starts the new
  version, which then reports "Updated to v…". This only happens right after startup, never
  while a check is running, and only when the exe's folder is writable. `--no-auto-update`
  keeps the badge but never replaces the file. Installs made with pip/pipx are not touched;
  they get the badge plus the `pipx upgrade codex-routing-detector` hint.
- Apart from that, in trace mode the tool only runs the Codex binary you already have and makes
  no network calls of its own. In `--wire` mode every HTTPS request Codex makes during the probe
  (including token refresh and telemetry) passes through the local mitmproxy process the tool
  launched on your machine; only the responses WebSocket is recorded.
- The probe runs with the sandbox in `read-only` mode, but a custom `--prompt` can still make
  the model read files and send them to OpenAI, as any Codex turn can. Keep the default prompt
  unless you know what you are doing.

## Reporting

If you see `REROUTED`, the useful facts for a bug report are the response ids, the
`created_at` times (UTC), the requested/served pair, your plan type and usage line, and the
Codex version. `--json` writes all of them.

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

**왜 만들었나.** 2026년 9월, Codex에서 `gpt-6-astra`를 골라 쓰는데 답이 갑자기 하위 모델
수준으로 떨어지고 "Selected model is at capacity" 오류가 잦아졌습니다. 통신을 캡처해 보니
요청은 `model: gpt-6-astra`였는데 서버가 돌려준 응답 객체에는 `model: gpt-5.6-luna`가
적혀 있었습니다. 같은 시간에 sol·terra·luna 요청은 정상이었고, 사용량 한도도 한참 남아
있었고, 클라이언트에는 아무 알림도 없었습니다. 화면은 astra, 사용량 차감도 astra, 실제
답은 luna. 정상 결제한 Plus·Pro 계정에서도 똑같이 재현됐습니다.

Codex 화면과 로컬 로그는 "요청한 모델"만 기록하기 때문에 이걸 보여주지 못합니다. 이 도구는
모델마다 아주 짧은 Codex 턴을 하나 돌리고, **서버가 직접 써서 보낸 응답 객체**의 `model`
값을 읽어서 실제로 응답한 모델을 알려줍니다. 서버 상태는 시간에 따라 바뀌니(같은 계정이
한 시간 안에 정상 ↔ 바꿔치기를 오갔습니다) 필요할 때마다 돌려 보세요.

**설치.** Windows에서 Python 없이 쓰려면 [Releases](https://github.com/darkdarkcocoa/codex-routing-detector/releases)의
`codex-routing-detector.exe`를 받아 더블클릭(SmartScreen 경고는 "추가 정보" → "실행").
Python 3.8+가 있으면 `pipx install git+https://github.com/darkdarkcocoa/codex-routing-detector`
후 `codex-routing-detector-gui`(창) 또는 `codex-routing-detector`(터미널). 어느 쪽이든
로그인된 Codex CLI나 Codex Desktop이 필요합니다.

```
python codex_routing_detector.py                # config.toml의 모델 + 대조군(gpt-5.6-sol) 확인
python codex_routing_detector.py -m gpt-6-astra # 특정 모델만
python codex_routing_detector.py -r 3           # 3번 반복
python codex_routing_detector.py --wire         # mitmproxy로 패킷 수준 확인 (pip install mitmproxy)
```

- 창 버전: 모델을 고르고 **Check**를 누르면 표와 판정 배너, 상세 내용이 표시되고,
  보고서 복사·JSON 저장·로그 폴더 열기 버튼이 있습니다. 오른쪽 아래 버튼으로 한국어/영어를
  바꿀 수 있고(`--lang ko`로 시작 가능), Codex를 못 찾으면 **Codex...** 버튼으로 실행 파일을
  직접 고를 수 있어요. 상단 **도움말** 메뉴에 기본 사용법·용어 설명(웜업, 턴, 대조군, 판정,
  trace/wire 모드)·정보가 있어요. 백신이 exe를 막으면 `run_gui.bat`(Python 필요)을 쓰세요.

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
- 업데이트: 시작할 때 `api.github.com`에 익명 요청 하나를 보내 새 릴리스가 있는지 봅니다.
  있으면 오른쪽 아래에 빨간 NEW 배지가 뜨고, **exe 버전은 새 파일을 받아 검증(크기·MZ
  헤더·SHA-256)한 뒤 자기 자신을 교체하고 새 버전으로 다시 실행**됩니다(시작 직후에만, 검사
  중에는 안 함, 폴더에 쓰기 가능할 때만). `--no-auto-update`면 배지만 표시하고,
  `--no-update-check` 또는 `CODEX_ROUTING_DETECTOR_NO_UPDATE=1`이면 확인 자체를 안 합니다.
  pip/pipx 설치는 배지와 `pipx upgrade codex-routing-detector` 안내만 나옵니다.
- 로그: 마지막 줄에 찍힌 폴더에 서버 프레임 원문이 남습니다. 스레드 ID, 계정 사용자 ID
  (`safety_identifier`), 프롬프트, 플랜/사용량이 들어 있고, 토큰·쿠키·요청 본문(작업 폴더
  경로 포함)은 기록되지 않습니다. `--json` 보고서에는 사용자 이름이 든 경로가 없습니다.
- `--wire` 모드에서는 프로브 동안 Codex가 보내는 모든 HTTPS 요청이 이 도구가 띄운 로컬
  mitmproxy를 지나갑니다(기록되는 것은 responses WebSocket뿐). 저장되는 기록에서 클라이언트
  요청 프레임은 `model`·`service_tier`·`reasoning` 같은 라우팅 필드만 남기고 프롬프트·도구
  목록·메타데이터는 버립니다. 인증서는 임시 폴더에 만들고 끝나면 지웁니다.
