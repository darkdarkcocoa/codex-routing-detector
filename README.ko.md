# Codex Routing Detector (한국어)

[English README](README.md)

Codex 요청에 **실제로 어떤 모델이 응답했는지** 보여주는 도구입니다. 실행하고 **Check**를 누르면,
내가 고른 `gpt-6-astra`가 정말 `gpt-6-astra`로 처리됐는지, 아니면 몰래 `gpt-5.6-luna`로
처리됐는지 알려줍니다. **라이브 모니터** 탭은 내 Codex CLI 세션을 작업하는 동안 요청 하나하나
같은 방식으로 지켜봅니다.

![검사 후의 Codex Routing Detector 창](docs/screenshot.png)

## 왜 만들었나

2026년 9월, Codex에서 `gpt-6-astra`를 골라 쓰는데 답이 갑자기 하위 모델 수준으로 떨어지고
"Selected model is at capacity" 오류가 잦아졌습니다. Codex 클라이언트와 `chatgpt.com` 사이의
통신을 캡처해 보니 이유가 보였습니다. 요청에는 `model: gpt-6-astra`라고 적혀 있었는데, 서버가
돌려준 응답 객체에는 `model: gpt-5.6-luna`라고 적혀 있었습니다. 같은 시간에 `gpt-5.6-sol`,
`terra`, `luna` 요청은 요청한 대로 처리됐고, 계정의 사용량 한도는 한참 남아 있었고,
클라이언트에는 아무 알림도 오지 않았습니다. Codex 프로토콜에는 `model/rerouted` 알림과
"한도 때문에 전환됨" 배너가 있는데 둘 다 울리지 않았습니다. 화면은 astra라고 표시하고,
사용량은 astra 기준으로 차감되고, 답은 luna에서 왔습니다. 정상 결제한 Plus·Pro 계정에서도
다른 사람들이 독립적으로 같은 현상을 재현했습니다.

Codex 안에서는 이걸 볼 수 없습니다. 화면과 로컬 세션 로그는 **요청한** 모델만 기록하기
때문입니다. 이 도구는 **서버가** 응답 객체에 적어 보낸 모델명, 즉 실제로 실행된 모델을 읽어서
불일치를 보고합니다. 서버 상태는 시간에 따라 바뀝니다(같은 계정이 한 시간 안에 정상 →
바꿔치기 → 정상을 오갔습니다). 그러니 중요할 때마다 다시 확인하세요.

## 설치

- **Windows, Python 없음**: [Releases](https://github.com/darkdarkcocoa/codex-routing-detector/releases)에서
  `codex-routing-detector.exe`를 받아 더블클릭합니다. 처음 한 번 SmartScreen 경고가 뜨면
  "추가 정보" → "실행"을 누르세요(코드 서명이 없어서 그렇습니다).
- **Python 3.8 이상**: `pipx install git+https://github.com/darkdarkcocoa/codex-routing-detector`
  후 `codex-routing-detector-gui`(창) 또는 `codex-routing-detector`(터미널). 의존성은
  라이브 모니터의 인증서를 만드는 `cryptography` 하나뿐이며 같이 설치됩니다.

어느 쪽이든 ChatGPT로 로그인된 Codex CLI 또는 Codex Desktop이 필요합니다(라이브 모니터는 CLI가
있어야 합니다. 아래 참고).

## 바로 쓰기

설정할 것 없이 켜서 **Check**만 누르면 됩니다.

1. `codex-routing-detector.exe`(또는 `codex-routing-detector-gui`)를 실행합니다.
2. **Check**를 누르고 작은 확인 창에서 "검사 시작"을 누릅니다(Codex에 짧은 프롬프트 하나를
   보낸다는 안내입니다. "다시 묻지 않기"를 켜면 다음부터 안 뜹니다). 모델은
   `~/.codex/config.toml`에서, 로그인은 Codex 것을 그대로 씁니다.
3. 30초쯤 뒤 배너를 읽습니다.
   - **바꿔치기 감지: gpt-6-astra -> gpt-5.6-luna**(빨강): 서버가 다른 모델로 응답했습니다.
   - **정상**(초록): 고른 모델이 응답했습니다.
   - **이 계정에서 쓸 수 없는 모델**(주황): 요금제에 그 모델이 없어 서버가 거절했습니다. 다른
     모델을 고르세요.
   - **확인 실패**(주황): "at capacity" 같은 서버 오류입니다. 다시 Check를 누르세요.

배너 아래 **브리핑** 카드에 무슨 일이 있었고 뭘 하면 되는지가 쉬운 말로 적히고, 그 아래 표와
상세에 증거(응답 ID, 플랜, 사용량)가 있습니다.

검사는 이게 전부입니다. 아래는 알아 두면 좋은 것들입니다.

## 라이브 모니터 (Codex CLI 전용)

두 번째 탭은 검사 요청을 보내는 대신 내 Codex 세션을 그대로 지켜봅니다. **모니터링 시작**을
누르면 Codex CLI가 새 터미널 창에서 열리고, 거기서 보내는 요청마다 서버가 답하는 즉시 표에
한 줄씩 쌓입니다(Codex가 요청한 모델, 실제로 답한 모델, 판정). 배너와 브리핑은 누적 집계를
보여 주므로, 작업 도중에 바꿔치기가 시작되면 그 순간 바로 드러납니다.

![세션 중의 라이브 모니터 탭](docs/screenshot-live.png)

탭을 처음 열면 짧은 안내 팝업이 뜹니다 (도움말 > 라이브 모니터 안내로 다시 볼 수 있습니다).

- **Codex 설정**은 `~/.codex/config.toml`의 `model`과 `model_reasoning_effort`를 그대로
  보여 주고, 파일이 바뀌면 다시 읽습니다. Codex가 무엇을 요청할지 미리 알 수 있습니다.
- **작업 폴더**는 Codex 창이 열릴 폴더(내 프로젝트)입니다. 한 번 고르면 기억합니다.
- **중지**를 누르면 Codex 창도 닫힙니다. 모니터 없이는 그 창이 서버에 연결할 수 없기 때문입니다.
  Codex를 직접 끝내도(`/exit` 또는 Ctrl-C) 모니터가 끝납니다. 결과는 화면에 남고,
  **라이브 보고서 복사**로 표를 클립보드에 넣을 수 있습니다.
- 추가 비용은 없습니다. 모니터는 스스로 요청을 보내지 않습니다.
- 원리: Codex CLI를 `HTTPS_PROXY`가 이 도구에 내장된 작은 프록시(127.0.0.1에서만 듣습니다)를,
  `CODEX_CA_CERTIFICATE`가 이번 세션용으로 만든 인증서를 가리키도록 실행합니다. 시스템 인증서
  저장소에는 아무것도 설치하지 않고, 바이트 하나 바꾸지 않으며, 통신 내용은 디스크에 저장하지
  않습니다. 프롬프트·파일·답변은 그대로 지나가고, 모델명·응답 ID·상태·오류 코드만 메모리에
  둡니다. (세션용 인증서와 개인 키는 모니터가 멈출 때까지 전용 임시 폴더에 있고, 고른 작업
  폴더는 설정 파일에 기억됩니다.)
- Windows에서 테스트했습니다. macOS·Linux에서는 터미널 창을 최선의 방법으로 열지만 모니터와
  분리되어 **중지**가 그 창을 닫지 못합니다. Codex를 직접 끝내세요.
- **Codex 데스크톱 앱은 감시할 수 없습니다.** 패키지(MSIX) 형태로 설치되는 앱이라 다른 프로그램이
  이런 설정을 넣어 줄 수 없고, 실제 응답 모델을 디스크 어디에도 남기지 않습니다. 데스크톱 앱
  사용자는 Check 탭에서 한 번에 하나씩 같은 답을 얻을 수 있습니다.

터미널에서는 `codex-routing-detector --live`가 Codex TUI를 새 창에 열고, Codex가 끝나거나
Ctrl-C를 누를 때까지 응답마다 한 줄씩 출력합니다. `--live-dir DIR`로 폴더를 고르고, `--` 뒤의
인자는 codex에 그대로 넘어갑니다(예: `--live -- exec "hello"`). 하나라도 다른 모델이 답하면
종료 코드 2입니다.

## 추가 설명

- **모델**: 검사하고 싶은 모델입니다. (터미널 버전은 `--control`로 비교용 모델을 하나 더
  검사할 수 있어요. 그쪽은 정상인데 내 모델만 다르면 "내 모델만 바꿔치기"라는 뜻입니다. 창은
  단순하게 가려고 이 기능을 넣지 않았습니다.)
- **반복**: 검사를 N번(1~10) 돌립니다. 서버 상태가 시간에 따라 바뀌니, 세 번쯤 돌리면
  안정적인지 오락가락하는지 보입니다.
- **Effort**: 검사에 보낼 reasoning effort. `low`가 가장 저렴하고, 지금까지 관찰된 바꿔치기는
  effort와 무관했습니다.
- **Wire 모드**: 판정은 같고 증거의 위치가 다릅니다. 기본 모드는 Codex 프로세스 안에서 서버
  프레임을 읽고, Wire 모드는 mitmproxy로 프로세스 바깥에서 통신을 통째로 기록합니다(Codex가
  보낸 요청까지). 남을 설득할 증거가 필요할 때 켜세요. `pip install mitmproxy` 필요.
- **Codex… / 자동 탐지**: `codex` 실행 파일은 도구가 알아서 찾습니다(PATH, npm 패키지, Codex
  Desktop 번들). 버튼은 못 찾는 드문 경우에만 씁니다.
- **웜업 / 턴**: Codex는 세션마다 요청을 두 번 보냅니다. *웜업*은 사용자 입력 없이 연결을
  여는 자동 요청, *턴*은 실제 프롬프트입니다. 둘 다 표에 나오고, 어느 쪽이든 다른 모델이
  응답하면 REROUTED, **ok**는 턴이 정상일 때만 줍니다.
- **보고서 복사 / JSON 저장 / 로그 폴더 열기**: 응답 ID 전체가 든 텍스트 보고서(이슈·문의용),
  같은 내용의 JSON, 서버 프레임 원문 폴더입니다.
- **NEW 배지 / 자동 업데이트**: 시작할 때 새 릴리스가 있는지 봅니다. exe는 새 파일을 받아
  검증한 뒤 스스로 다시 실행되고, 오른쪽 아래 배지를 누르면 릴리스 페이지가 열립니다. 끄는
  방법은 "업데이트" 항목에 있습니다.
- **한국어 / English**: 도움말까지 모든 글자를 바꿉니다.

## 터미널 버전

```
codex-routing-detector                 # config.toml의 모델 + 대조군(gpt-5.6-sol) 확인
codex-routing-detector -m gpt-6-astra  # 특정 모델만
codex-routing-detector -r 3            # 3번 반복
codex-routing-detector --json out.json --full-ids
codex-routing-detector --wire          # mitmproxy로 패킷 수준 확인
codex-routing-detector --live          # 내 Codex CLI 세션을 새 창에 열고 실시간으로 감시
```

종료 코드: 0 전부 요청대로, 2 하나라도 다른 모델이 응답(대조군 포함), 1 확인 실패 또는 인자
오류. 나머지 옵션은 `--help`에 있습니다.

## 용어와 판정

- **요청한 모델 / 실제 응답 모델**: 클라이언트가 요청에 적은 모델명 / 서버가 응답 객체
  (`response.created`, `response.completed`)에 적은 모델명. 후자가 실제로 응답한 모델입니다.
- **턴**: 실제 요청. 프롬프트가 서버로 가고 모델이 답합니다.
- **웜업**: Codex가 턴 직전에 스스로 보내는 요청(사용자 입력 없이 연결을 열고 시스템
  프롬프트를 미리 올려 둠). 고른 모델로 보내는 진짜 요청이라, 웜업이 다른 모델로 응답돼도
  바꿔치기의 증거입니다.
- `REROUTED`: 응답 객체에 다른 모델명이 있음(웜업이든 턴이든, 이후 실패했더라도).
- `ok`: 요청대로 응답했고 턴이 정상 완료됨.
- `UNSUPPORTED`: 서버가 이 계정에서는 그 모델을 쓸 수 없다고 거절함("not supported when using
  Codex with a ChatGPT account" 등). 요금제에 없는 모델이며 바꿔치기가 아닙니다. 이때 웜업이
  요금제 기본 모델로 응답된 것은 바꿔치기로 세지 않습니다.
- `ERROR`: 서버 오류. 예: `server_is_overloaded`(Codex 화면의 "Selected model is at capacity").
  바꿔치기가 아니니 다시 시도하세요.
- `UNKNOWN`: 확인 불가. `model` 필드가 없거나, 턴이 완료 전에 끊겼거나, 웜업 응답만 보임.
  행 아래 note에 이유가 적힙니다.
- `NO_DATA`: WebSocket 프레임이 전혀 없음. 행 아래 note에 Codex 종료 코드와 마지막 오류 줄이
  적힙니다(로그인 안 됨 등). 정상 종료인데 프레임이 없으면 구버전 Codex이니 `--wire`를
  쓰세요. 사용자 지정 provider(Bedrock 등)는 확인할 수 없습니다.

## 동작 원리

기본(trace) 모드는 실제 `codex` 실행 파일을 `RUST_LOG=tungstenite::protocol=trace`로
실행합니다. `tungstenite`는 Codex 아래에 있는 WebSocket 라이브러리로, 이 로그 레벨에서는
소켓에서 받은 프레임을 Codex 코드가 손대기 전에 원문 그대로 찍습니다. 도구는 거기서
서버의 `response.created` / `response.completed`에 적힌 `model`을 읽습니다. `--wire` 모드는
임시 인증서로 로컬 mitmproxy를 띄워 WebSocket 양방향을 기록하며(OS 인증서 저장소는 건드리지
않음), 끝나면 인증서와 프록시를 지웁니다. 두 모드를 나란히 돌려 서버 응답 객체가 동일함을
확인했습니다.

라이브 모니터는 `--wire`와 같은 발상을 mitmproxy 없이 구현한 것입니다. `codex_routing_proxy.py`는
CONNECT 프록시로, 세션마다 새로 만든 인증 기관(EC P-256, `cryptography` 패키지 사용)으로 TLS를
종단하고 실제 서버 쪽으로 다시 암호화해 모든 바이트를 그대로 중계합니다. responses WebSocket에
한해 프레임(마스킹, 분할, context takeover가 있는 `permessage-deflate`)을 해독해서 클라이언트의
`response.create`에 적힌 모델과 서버의 `response.created` / `response.completed` 객체를 읽습니다.
`codex_routing_live.py`가 이를 응답당 한 행으로 정리하고 Codex 창을 열고 닫습니다.

프로브마다 새 Codex 세션을 씁니다(`--ephemeral`, 샌드박스 read-only, notify 훅 끔). Codex는
세션마다 요청을 두 번 보냅니다(웜업 + 턴). 둘 다 표에 나오며, 어느 하나라도 다른 모델명을
담으면 `REROUTED`, `ok`는 턴이 정상 완료됐을 때만 줍니다.

## 비용과 프라이버시

- 검사 한 번에 모델당 요청 2개(웜업 + 턴). 창은 2개, 터미널은 기본 대조군을 켜면 4개. 시스템 프롬프트 때문에
  입력 토큰이 1만 몇천 개씩 들지만 출력은 몇 토큰이라, 일반 Codex 사용량으로 조금 차감됩니다.
- 로그는 마지막 줄에 찍힌 폴더(기본은 새 임시 폴더)에 남습니다. 서버 프레임(스레드·세션 ID,
  계정 사용자 ID `safety_identifier`, 검사 프롬프트, 플랜과 사용량)이 들어 있습니다. 요청
  본문(작업 폴더 경로 포함)은 저장 전에 버리고, 인증 헤더와 쿠키는 애초에 로그에 찍히지
  않으며 `x-codex-turn-state` 토큰은 가립니다. 홈 폴더 경로는 `~`로 적습니다. 필요 없으면
  폴더를 지우세요.
- `--json` 보고서에는 사용자 이름이 든 경로가 없습니다. 플랜·사용량·크레딧 잔액은 이슈 제보에
  유용해서 남겨 두니, 공유하기 싫으면 지우세요.
- trace 모드에서 도구가 하는 네트워크 통신은 아래 업데이트 확인뿐입니다. `--wire` 모드에서는
  프로브 동안 Codex의 모든 HTTPS 요청(토큰 갱신, 원격 측정 포함)이 이 도구가 띄운 로컬
  mitmproxy를 지나가며, 기록되는 것은 responses WebSocket뿐입니다.
- 라이브 모니터는 모델명·응답 ID·상태·시각·오류 코드만 메모리에 두며, 지우기를 누르거나 창을
  닫으면 사라집니다. 원문 메시지는 어디에도 쓰지 않습니다. 세션 동안 Codex의 모든 HTTPS 통신(토큰
  갱신, 원격 측정, 네트워크 MCP 서버 포함)이 127.0.0.1의 내장 프록시를 지나가며, 해독하는 것은
  responses WebSocket뿐입니다. 인증 기관은 세션 전용 임시 폴더에 있다가 모니터가 멈추면 지워집니다.
- 샌드박스가 read-only여도 사용자 지정 `--prompt`로 모델이 파일을 읽어 OpenAI로 보내게 할 수
  있습니다(다른 Codex 턴과 같음). 기본 프롬프트를 쓰세요.

## 업데이트

시작할 때 `api.github.com`에 익명 요청 하나를 보내 새 릴리스가 있는지 봅니다(사용자에 대한
정보는 보내지 않음). 있으면 오른쪽 아래에 빨간 **NEW** 배지가 뜹니다(클릭하면 릴리스 페이지).
**Windows exe는 스스로 업데이트합니다.** 새 exe를 자기 옆에 내려받아 크기·MZ 헤더·GitHub가
공개하는 SHA-256으로 검증한 뒤, 옛 프로세스가 끝나면 파일을 교체하고 새 버전으로 다시
실행되어 "v…로 업데이트됨"이라고 표시합니다. 시작 직후에만 하고, 검사 중에는 하지 않으며,
exe 폴더에 쓰기 가능할 때만 합니다. `--no-auto-update`는 배지만 남기고 파일을 바꾸지 않으며,
`--no-update-check` 또는 환경변수 `CODEX_ROUTING_DETECTOR_NO_UPDATE=1`은 확인 자체를 끕니다.
pip/pipx 설치는 건드리지 않고 배지와 `pipx upgrade codex-routing-detector` 안내만 보여줍니다.

## 제보할 때

`REROUTED`가 나오면 응답 ID, `created_at`(UTC), 요청/응답 모델 쌍, 플랜과 사용량 줄, Codex
버전이 유용합니다. `--json`이 전부 기록하고, 창의 **보고서 복사**도 같은 내용을 줍니다.

## 테스트와 빌드

```
python -m unittest discover -s tests -v   # 파서·판정·GUI 테스트 (실제 Codex 호출 없음)
build_exe.bat                             # dist\codex-routing-detector.exe 빌드 (PyInstaller)
```

`tests/fixtures`는 2026-09-22 실제 캡처에서 ID를 자리표시자로 바꾼 두 개의 전체 실행
기록입니다(astra 요청이 luna로 처리된 것, `server_is_overloaded`로 끝난 것).
`tests/test_live.py`는 내장 프록시를 로컬 TLS WebSocket 에코 서버에 대고 끝까지 돌려 봅니다
(CONNECT, 임시 인증 기관, 마스킹·압축 프레임). `tests/test_gui_live.py`는 가짜 Codex
프로세스로 라이브 탭을 구동합니다. `python codex_routing_detector_gui.py --fake --fake-live`는
라이브 탭을 샘플 행으로 채워 보여 줍니다(개발용).
