# Codex Routing Detector (한국어)

[English README](README.md)

Codex 요청에 **실제로 어떤 모델이 응답했는지** 보여주는 도구입니다. 실행하고 **Check**를 누르면,
내가 고른 `gpt-6-astra`가 정말 `gpt-6-astra`로 처리됐는지, 아니면 몰래 `gpt-5.6-luna`로
처리됐는지 알려줍니다.

![실제 검사 후의 Codex Routing Detector 창](docs/screenshot.png)

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
  후 `codex-routing-detector-gui`(창) 또는 `codex-routing-detector`(터미널).

어느 쪽이든 ChatGPT로 로그인된 Codex CLI 또는 Codex Desktop이 필요합니다.

## 창 사용법

1. 모델을 고릅니다. 기본값은 `~/.codex/config.toml`의 모델입니다.
2. 대조군(기본 `gpt-5.6-sol`)은 켜 두는 것을 권합니다. 대조군이 정상인데 검사 모델만 다르게
   응답하면 "그 모델만 바꿔치기"라는 뜻이고, 계정이나 클라이언트 문제와 구분됩니다.
3. **Check**를 누릅니다. 검사 하나는 아주 짧은 Codex 턴 하나입니다
   ("Reply with exactly the single word: pong"). 끝나는 대로 표에 행이 추가되고, 취소로 중단할
   수 있습니다.
4. 배너를 읽습니다. **바꿔치기 감지**(다른 모델이 응답) / **정상**(요청대로 응답) /
   **확인 실패**(서버 오류나 응답 누락, 다시 시도).
5. **보고서 복사**는 응답 ID가 든 전체 보고서를 클립보드에 복사합니다(이슈 제출·지원 문의용).
   **JSON 저장**은 같은 내용을 JSON으로, **로그 폴더 열기**는 서버 프레임 원문 폴더를 엽니다.

오른쪽 아래 버튼으로 한국어/영어를 바꿀 수 있고(`--lang ko`로 시작 가능), 상단 **도움말**
메뉴에 기본 사용법·용어 설명·정보가 있습니다. Codex를 자동으로 못 찾으면 **Codex...** 버튼으로
실행 파일을 직접 고를 수 있습니다. 백신이 exe를 막으면 `run_gui.bat`(Python 필요)을 쓰세요.

옵션: **Effort**는 검사에 보낼 reasoning effort(기본 low, 가장 저렴. 지금까지 관찰된
바꿔치기는 effort와 무관했습니다). **반복**은 각 검사를 N번(1~10) 돌립니다. **Wire 모드**는
trace 로그 대신 mitmproxy로 패킷을 캡처합니다(`pip install mitmproxy` 필요). 판정 정확도는
두 모드가 같고, wire 모드는 클라이언트가 보낸 요청 프레임까지 기록하므로 제3자를 설득할 증거가
필요할 때 씁니다.

## 터미널 버전

```
codex-routing-detector                 # config.toml의 모델 + 대조군 확인
codex-routing-detector -m gpt-6-astra  # 특정 모델만
codex-routing-detector -r 3            # 3번 반복
codex-routing-detector --json out.json --full-ids
codex-routing-detector --wire          # mitmproxy로 패킷 수준 확인
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

프로브마다 새 Codex 세션을 씁니다(`--ephemeral`, 샌드박스 read-only, notify 훅 끔). Codex는
세션마다 요청을 두 번 보냅니다(웜업 + 턴). 둘 다 표에 나오며, 어느 하나라도 다른 모델명을
담으면 `REROUTED`, `ok`는 턴이 정상 완료됐을 때만 줍니다.

## 비용과 프라이버시

- 검사 한 번에 모델당 요청 2개(웜업 + 턴), 기본 대조군까지 4개. 시스템 프롬프트 때문에
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
