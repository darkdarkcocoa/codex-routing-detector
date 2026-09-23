"""Words of the web window (codex_routing_webui): status lines, dialogs, the plain-words verdict
and the help pages, in Korean and English.

The fallback tkinter window keeps its own texts in codex_routing_detector_gui (they describe
that window's controls). Here the tone is friendly, and the verdict only says which model was
called and which one answered; plan and usage figures stay in Details and the copied report.

Help pages are data, not prose: the page renders every section as a card. Inside a string,
`code` becomes an inline code chip and **bold** becomes bold.
"""
from typing import Dict

# Status lines and dialogs. Every key overrides the same key in codex_routing_detector_gui.STRINGS.
TEXT: Dict[str, Dict[str, str]] = {
    "ko": {
        "starting": "Codex를 준비하는 중이에요 ({version})...",
        "cancelling": "취소하는 중이에요...",
        "cancelled": "검사를 취소했어요.",
        "failed": "검사를 시작하지 못했어요.",
        "copied": "보고서를 복사했어요!",
        "saved": "저장했어요: {path}",
        "fake": "(샘플 데이터, 실제 검사 아님)",
        "codex_hint": "검사 탭 설정 줄 오른쪽 끝의 \"codex · 자동 탐지\"를 눌러 codex 실행 파일을 직접 골라 주세요 "
                      "(npm 패키지 안의 codex.exe 또는 Codex Desktop 번들).",
        "live_needs_crypto": "라이브 모니터에는 cryptography 패키지가 필요해요: pip install cryptography",
        "live_codex_exit": "Codex가 종료돼서(종료 코드 {rc}) 모니터도 멈췄어요.",
        "live_stopped": "멈췄어요.",
        "live_cfg_none": "기본값",
        "confirm_title": "검사해 볼까요?",
        "confirm_body": "Codex를 통해 **{model}** 모델에 아주 짧은 프롬프트 하나를 보낼게요. \"pong\" 한 마디만 답해 "
                        "달라는 부탁이에요. 그다음 서버가 돌려준 응답에서 실제로 대답한 모델 이름을 읽어 올게요. "
                        "Codex 사용량이 아주 조금 들어요.",
        "confirm_skip": "다시 묻지 않기",
        "confirm_ok": "검사 시작",
        "confirm_cancel": "다음에요",
        "confirm_live_title": "라이브 모니터를 시작할까요?",
        "confirm_live_body": "새 터미널 창에 Codex CLI를 열어 드릴게요. 그 창의 통신은 이 컴퓨터 안의 프록시"
                             "(127.0.0.1)를 거쳐요. 이번 세션에만 쓰는 인증서로 서버 응답 속 모델 이름을 읽고, "
                             "프롬프트·파일·답변은 그대로 지나가게 두고 저장하지 않아요. 모니터를 중지하면 그 Codex "
                             "창도 같이 닫혀요.",
        "confirm_live_ok": "시작",
        "live_stop_confirm": "중지하면 지켜보던 Codex 창도 같이 닫혀요. 지금 중지할까요?",
        "live_close_confirm": "라이브 모니터가 아직 돌고 있어요. 이 창을 닫으면 지켜보던 Codex 창도 같이 닫혀요. "
                              "닫을까요?",
        "update_pip": "새 버전(v{new})이 나왔어요! 업데이트 명령: pipx upgrade codex-routing-detector",
        "update_manual": "새 버전(v{new})이 나왔어요! 왼쪽 아래 NEW를 눌러 받아 주세요.",
        "update_downloading": "새 버전(v{new})을 받는 중이에요... {mb} MB",
        "update_restarting": "다 받았어요! 새 버전(v{new})으로 다시 시작할게요...",
        "update_failed": "새 버전(v{new})으로 자동 업데이트하지 못했어요 ({err}). 왼쪽 아래 NEW를 눌러 직접 받아 "
                         "주세요.",
        "updated": "새 버전(v{current})으로 업데이트했어요!",
    },
    "en": {
        "starting": "Getting Codex ready ({version})...",
        "cancelling": "Cancelling...",
        "cancelled": "Check cancelled.",
        "failed": "The check couldn't start.",
        "copied": "Report copied!",
        "saved": "Saved to {path}",
        "fake": "(sample data, not a real check)",
        "codex_hint": "On the Check tab, click \"codex · auto-detect\" at the right end of the Setup row to pick the "
                      "codex binary yourself (codex.exe inside the npm package, or the Codex Desktop bundle).",
        "live_needs_crypto": "The live monitor needs the cryptography package: pip install cryptography",
        "live_codex_exit": "Codex exited (exit code {rc}), so the monitor stopped too.",
        "live_stopped": "Stopped.",
        "live_cfg_none": "default",
        "confirm_title": "Ready to check?",
        "confirm_body": "I'll send one tiny prompt to **{model}** through Codex, asking it to reply with just "
                        "\"pong\". Then I'll read the server's response to see which model really answered. It uses "
                        "a tiny bit of your Codex usage.",
        "confirm_skip": "Don't ask again",
        "confirm_ok": "Check",
        "confirm_cancel": "Not now",
        "confirm_live_title": "Start the live monitor?",
        "confirm_live_body": "I'll open the Codex CLI in a new terminal window. Its traffic goes through a proxy on "
                             "this computer (127.0.0.1), and a certificate made just for this session lets me read "
                             "the model name in each server response. Prompts, files and answers pass straight "
                             "through and are never saved. Stopping the monitor closes that Codex window too.",
        "confirm_live_ok": "Start",
        "live_stop_confirm": "Stopping also closes the Codex window I'm watching. Stop now?",
        "live_close_confirm": "The live monitor is still running. Closing this window also closes the Codex window "
                              "I'm watching. Close it?",
        "update_pip": "Version {new} is out! Update with: pipx upgrade codex-routing-detector",
        "update_manual": "Version {new} is out! Click NEW at the bottom left to get it.",
        "update_downloading": "Downloading v{new}... {mb} MB",
        "update_restarting": "All downloaded! Restarting as v{new}...",
        "update_failed": "The automatic update to v{new} failed ({err}). Click NEW at the bottom left to get it.",
        "updated": "Updated to v{current}!",
    },
}

# The verdict card: headline and the plain-words paragraph under it. Model names are **bold**;
# no plan or usage talk here (that lives in Details and the copied report).
VERDICT: Dict[str, Dict[str, str]] = {
    "ko": {
        "idleBrief": "검사하기를 누르면 Codex에 아주 짧은 프롬프트 하나를 보내고, 실제로 어떤 모델이 대답했는지 "
                     "알려 드릴게요.",
        "runBrief": "Codex에 프롬프트를 보냈어요. 누가 대답하는지 지켜보는 중이에요...",
        "okHead": "정상! {model} 모델이 대답했어요",
        "okBrief": "**{model}** 모델을 불렀고, **{model}** 모델이 직접 대답했어요. 바꿔치기 없이 깔끔해요!",
        "badBrief": "**{requested}** 모델을 불렀는데, 실제로는 **{served}** 모델이 대답했어요! (응답 {total}개 중 {bad}개)",
        "badTip": "잠시 뒤에 다시 검사해 보거나, 당분간 다른 모델을 써 보세요.",
        "unsupportedHead": "이 계정에서는 쓸 수 없는 모델이에요",
        "unsupportedBrief": "**{requested}** 모델을 불렀는데, 이 계정에서는 쓸 수 없는 모델이라며 서버가 거절했어요. "
                            "바꿔치기는 아니에요. 이 계정에서 쓸 수 있는 모델로 다시 검사해 주세요.",
        "errorHead": "확인하지 못했어요",
        "errorBrief": "**{requested}** 모델을 불렀는데, 서버가 대답 대신 오류({errors})를 보냈어요. 바꿔치기는 "
                      "아니니까 잠시 뒤에 다시 검사해 주세요.",
        "nodataBrief": "**{requested}** 모델을 불렀는데, 서버에서 끝까지 확인할 수 있는 대답이 오지 않았어요. 이유는 "
                       "아래 상세 정보에 적어 뒀어요.",
        "fatalHead": "검사를 시작하지 못했어요",
        "fatalBrief": "앗! 무엇이 문제였는지 아래 상세 정보에 적어 뒀어요.",
        "cancelledBrief": "검사를 중간에 취소했어요. 준비되면 **다시 검사**를 눌러 주세요.",
        "liveIdleHead": "모니터가 쉬고 있어요",
        "liveIdleBrief": "모니터링 시작을 누르면 Codex CLI 창이 열려요. 거기서 요청할 때마다 실제로 대답한 모델을 "
                         "여기에 한 줄씩 적어 드릴게요. (Codex 데스크톱 앱은 아직 지켜볼 수 없어요)",
        "liveWaitHead": "지켜보는 중이에요",
        "liveWaitBrief": "Codex 창이 열렸어요! 거기서 뭐든 입력하면 누가 대답했는지 바로 알려 드릴게요.",
        "livePendingBrief": "Codex가 **{requested}** 모델을 불렀어요. 대답이 끝나기를 기다리는 중이에요...",
        "liveOkHead": "지금까지 모두 정상이에요",
        "liveOkBrief": "Codex가 **{requested}** 모델을 불렀고, 지금까지 응답 {n}개 모두 **{requested}** 모델이 직접 "
                       "대답했어요.",
        "liveBadBrief": "Codex가 **{requested}** 모델을 불렀는데, 응답 {total}개 중 {bad}개는 **{served}** 모델이 "
                        "대답했어요!",
        "liveUnsupportedBrief": "Codex가 **{requested}** 모델을 불렀는데, 이 계정에서는 쓸 수 없는 모델이라며 서버가 "
                                "거절했어요. 바꿔치기는 아니에요.",
        "liveErrorHead": "서버가 오류를 보냈어요",
        "liveErrorBrief": "Codex가 **{requested}** 모델을 불렀는데, 지금까지 서버가 오류({errors})만 보냈어요. "
                          "바꿔치기는 아니에요.",
        "liveUnknownHead": "확인하지 못한 대답이 있어요",
        "liveUnknownBrief": "Codex가 **{requested}** 모델을 불렀는데, 아직 끝까지 확인할 수 있는 대답이 없어요. "
                            "바꿔치기는 아니에요. 목록의 상태 칸에서 이유를 볼 수 있어요.",
    },
    "en": {
        "idleBrief": "Press Check and I'll send Codex one tiny prompt, then tell you which model really answered.",
        "runBrief": "The prompt is on its way. Watching who answers...",
        "okHead": "All good! {model} answered",
        "okBrief": "You called **{model}**, and **{model}** itself answered. No switcheroo this time!",
        "badBrief": "You called **{requested}**, but **{served}** answered instead! ({bad} of {total} responses)",
        "badTip": "Check again in a little while, or use another model for now.",
        "unsupportedHead": "Not available on this account",
        "unsupportedBrief": "You called **{requested}**, but the server said this account can't use it. That's not a "
                            "switcheroo; pick a model this account can use and check again.",
        "errorHead": "Couldn't check",
        "errorBrief": "You called **{requested}**, but the server sent back an error ({errors}) instead of an answer. "
                      "Not a switcheroo; check again in a moment.",
        "nodataBrief": "You called **{requested}**, but no complete answer came back from the server. The reason is "
                       "in Details below.",
        "fatalHead": "The check couldn't start",
        "fatalBrief": "Oops! What went wrong is in Details below.",
        "cancelledBrief": "The check was cancelled partway. Press **Check again** whenever you're ready.",
        "liveIdleHead": "The monitor is resting",
        "liveIdleBrief": "Press Start monitoring and a Codex CLI window opens. Every time it makes a request, I'll "
                         "add a line here with the model that really answered. (The Codex desktop app can't be "
                         "watched yet.)",
        "liveWaitHead": "Watching...",
        "liveWaitBrief": "The Codex window is open! Type anything there and I'll tell you right away who answered.",
        "livePendingBrief": "Codex called **{requested}**. Waiting for the answer to finish...",
        "liveOkHead": "All good so far",
        "liveOkBrief": "Codex called **{requested}**, and every response so far ({n}) came from **{requested}** "
                       "itself.",
        "liveBadBrief": "Codex called **{requested}**, but {bad} of {total} responses came from **{served}**!",
        "liveUnsupportedBrief": "Codex called **{requested}**, but the server said this account can't use it. That's "
                                "not a switcheroo.",
        "liveErrorHead": "The server sent errors",
        "liveErrorBrief": "Codex called **{requested}**, but so far the server has only sent errors ({errors}). "
                          "That's not a switcheroo.",
        "liveUnknownHead": "Some answers couldn't be confirmed",
        "liveUnknownBrief": "Codex called **{requested}**, but no answer could be confirmed yet. That's not a "
                            "switcheroo; the Status column shows why.",
    },
}

# Help pages. A section is {"icon", "title", "items"} and may set "numbered"; an item is a string,
# {"term", "text"} or {"chip", "tone", "text"} (tone: ok / bad / warn / idle).
HELP: Dict[str, dict] = {
    "ko": {
        "usage": [
            {"icon": "🐾", "title": "검사는 버튼 하나면 끝나요", "numbered": True, "items": [
                "**설정** 줄에서 검사할 모델을 골라요. 처음에는 `~/.codex/config.toml`에 적힌 모델이 선택돼 있어요.",
                "**검사하기**를 누르면 Codex에 아주 짧은 프롬프트 하나를 보내요. \"pong\" 한 마디만 답해 달라는 "
                "부탁이에요.",
                "30초쯤 지나면 맨 위 카드가 결과를 알려 줘요. 아래 **응답 기록**에는 요청한 모델과 실제로 대답한 "
                "모델이 나란히 적혀요.",
            ]},
            {"icon": "🎨", "title": "카드 색으로 결과 읽기", "items": [
                {"chip": "바꿔치기", "tone": "bad", "text": "요청한 모델이 아닌 다른 모델이 대답했어요."},
                {"chip": "정상", "tone": "ok", "text": "고른 모델이 직접 대답했어요."},
                {"chip": "확인 필요", "tone": "warn", "text": "이 계정에서 쓸 수 없는 모델이라 서버가 거절했거나, "
                 "\"at capacity\" 같은 서버 오류가 났거나, 대답을 끝까지 받지 못했어요. 바꿔치기는 아니에요. "
                 "이유는 **상세 정보**에 있어요."},
            ]},
            {"icon": "📋", "title": "결과 챙기기", "items": [
                {"term": "보고서 복사", "text": "응답 ID까지 모두 담긴 보고서를 클립보드에 넣어요. 제보나 문의할 때 "
                 "그대로 붙여 넣으면 돼요."},
                {"term": "JSON 저장", "text": "같은 내용을 JSON 파일로 저장해요."},
                {"term": "로그 폴더", "text": "서버가 보낸 원본 기록이 든 폴더를 열어요."},
                {"term": "상세 정보", "text": "계정 플랜과 사용량, Codex 경로, 로그 위치가 적혀 있어요."},
            ]},
            {"icon": "⚙️", "title": "설정 줄 살펴보기", "items": [
                {"term": "모델", "text": "목록은 Codex의 모델 카탈로그에서 가져와요. 목록에 없는 모델은 맨 아래 "
                 "**직접 입력...**으로 적어요. `openai/gpt-6-astra`처럼 앞에 `openai/`가 붙은 이름은 떼고 "
                 "검사해요(서버가 붙은 이름은 거절하거든요)."},
                {"term": "노력", "text": "검사 요청에 담아 보내는 `reasoning effort` 값이에요. 고른 모델이 지원하는 "
                 "단계만 보여요(`ultra`는 하위 에이전트를 여럿 띄워 비용이 커서 뺐어요). `low`가 사용량이 가장 "
                 "적게 들고, 지금까지 확인된 바꿔치기는 이 값과 상관없이 일어났어요."},
                {"term": "반복", "text": "검사를 1~10번 되풀이해요. 서버 상태가 오락가락하는지 볼 때 좋아요."},
                {"term": "Wire 모드", "text": "mitmproxy로 Codex 바깥에서 통신을 기록해요. 판정 결과는 기본 방식과 "
                 "같고, 다른 사람에게 보여 줄 증거가 필요할 때 켜면 좋아요. `pip install mitmproxy`로 설치한 뒤 이 "
                 "창을 다시 열어야 켤 수 있어요."},
                {"term": "codex · 자동 탐지", "text": "codex 실행 파일은 알아서 찾아요. 못 찾았을 때만 눌러서 직접 "
                 "골라 주세요."},
            ]},
            {"icon": "👀", "title": "라이브 모니터 (Codex CLI 전용)", "items": [
                "**모니터링 시작**을 누르면 Codex CLI 창이 새로 열려요. 거기서 평소처럼 작업하면 요청마다 한 줄씩 "
                "쌓여요.",
                "**세션** 줄에는 `config.toml`에 적힌 **모델**과 **노력** 값이 보여요. 파일이 바뀌면 다시 읽고, "
                "**config.toml**을 누르면 파일이 열려요.",
                "**작업 폴더**는 Codex 창이 열릴 폴더예요. **모니터링 시작** 버튼 옆의 경로를 눌러 바꿔요. "
                "모니터가 꺼져 있을 때만 바꿀 수 있고, 한 번 고르면 기억해요.",
                "**중지**를 누르면 Codex 창도 같이 닫혀요. 모니터 없이는 그 창이 서버에 연결할 수 없거든요. Codex "
                "창을 직접 닫아도 모니터가 멈춰요.",
                "응답 기록은 **보고서 복사**로 클립보드에 넣을 수 있어요. 모니터를 멈춘 뒤 **지우기**를 누르거나 "
                "**모니터링 시작**을 다시 누르면 지워져요.",
                "Codex 데스크톱 앱은 지켜볼 수 없어요. 데스크톱 앱을 쓴다면 **검사** 탭으로 확인해 주세요.",
            ]},
            {"icon": "🔒", "title": "비용과 프라이버시", "items": [
                "검사 한 번에 요청 2개(웜업 + 턴)가 나가요. **반복**을 3으로 두면 6개예요. 일반 Codex 사용량에서 "
                "아주 조금 차감되고, 라이브 모니터는 스스로 요청을 보내지 않아요.",
                "검사 로그에는 스레드 ID, 계정 사용자 ID, 검사 프롬프트가 남아요. 토큰과 쿠키는 없고, 요청 본문과 "
                "홈 폴더 경로도 적지 않아요.",
                "라이브 모니터는 모델 이름·응답 ID·상태·시각·오류 코드와 계정 플랜·사용량만 메모리에 둬요. "
                "프롬프트·파일·답변은 지나가기만 하고 저장하지 않아요.",
                "프록시는 127.0.0.1에서만 연결을 받고, 인증서는 이번 세션용으로 만들었다가 끝나면 지워요. 시스템 "
                "인증서 저장소에는 아무것도 설치하지 않아요.",
                "시작할 때 `api.github.com`에 새 버전이 있는지 한 번 물어봐요. exe 버전은 새 버전이 있으면 "
                "GitHub에서 받아 검증한 뒤 스스로 업데이트해요(`--no-auto-update`로 끄고, `--no-update-check`로 "
                "확인 자체를 꺼요). 그 밖에 이 창이 인터넷에서 받아 오는 건 없어요.",
            ]},
        ],
        "terms": [
            {"icon": "🔤", "title": "자주 나오는 말", "items": [
                {"term": "요청한 모델", "text": "내가 고른 모델이에요. 클라이언트가 요청에 적은 이름이에요."},
                {"term": "실제 응답 모델", "text": "서버가 자기 응답 객체(`response.created`, `response.completed`)에 "
                 "적은 이름이에요. 진짜로 대답한 모델이고, Codex 로그가 아니라 WebSocket 메시지 원문에서 읽어요."},
                {"term": "턴", "text": "프롬프트를 담아 보내고 모델의 대답을 받는 요청이에요."},
                {"term": "웜업", "text": "Codex가 턴 바로 전에 알아서 보내는 준비 요청이에요(내부 이름 `prewarm`). "
                 "이것도 고른 모델로 가는 진짜 요청이라, 다른 모델이 대답하면 바꿔치기 증거가 돼요."},
                {"term": "응답 ID", "text": "서버가 응답마다 붙이는 ID(`resp_...`)예요. 제보할 때 적어 주면 서버 "
                 "쪽에서 그 요청을 찾을 수 있어요."},
                {"term": "시각", "text": "검사 탭은 서버가 찍은 UTC 시각(끝에 `Z`), 라이브 탭은 내 컴퓨터 "
                 "시각이에요."},
                {"term": "상태", "text": "서버가 알려 준 `completed` / `failed` / `in_progress` 그대로예요."},
            ]},
            {"icon": "🏷️", "title": "판정 종류", "items": [
                "표에서는 줄 색이 판정이에요. 줄에 마우스를 올리면 아래 이름이 보이고, 상세 정보와 복사한 보고서에도 "
                "같은 이름으로 적혀요.",
                {"chip": "ok", "tone": "ok", "text": "고른 모델이 대답했고, 턴도 잘 끝났어요."},
                {"chip": "REROUTED", "tone": "bad", "text": "응답 객체에 다른 모델 이름이 적혀 있어요. 웜업이든 "
                 "턴이든, 그 응답이 나중에 실패했더라도 바꿔치기 증거예요."},
                {"chip": "UNSUPPORTED", "tone": "warn", "text": "이 계정에서는 쓸 수 없는 모델이라며 서버가 "
                 "거절했어요. 바꿔치기는 아니에요."},
                {"chip": "ERROR", "tone": "warn", "text": "서버 오류예요. 예를 들어 `server_is_overloaded`는 Codex "
                 "화면에 \"Selected model is at capacity\"로 보여요. 잠시 뒤에 다시 해 보세요."},
                {"chip": "UNKNOWN", "tone": "warn", "text": "확인할 수 없었어요. 응답에 모델 이름이 없었거나, 턴이 "
                 "끝나기 전에 끊겼거나, 웜업만 보였어요."},
                {"chip": "NO_DATA", "tone": "warn", "text": "WebSocket 메시지가 하나도 보이지 않았어요. 로그인이 안 "
                 "됐거나, Codex가 실행되지 못했거나, 이 도구가 읽을 수 없는 방식(HTTP로 통신하는 옛 버전 등)으로 "
                 "통신했어요. 이유는 상세 정보에 있어요."},
            ]},
            {"icon": "🔧", "title": "어떻게 알아내나요?", "items": [
                {"term": "Trace 모드", "text": "기본 방식이에요. Codex를 `RUST_LOG=tungstenite::protocol=trace`로 "
                 "실행하면 WebSocket 라이브러리가 받은 메시지를 Codex가 손대기 전에 원문 그대로 로그에 남기고, "
                 "거기서 모델 이름을 읽어요."},
                {"term": "Wire 모드", "text": "임시 인증서로 로컬 mitmproxy를 띄워 WebSocket 양방향을 기록해요."},
                {"term": "라이브 모니터", "text": "127.0.0.1의 내장 프록시와 세션 전용 인증서를 써요. `HTTPS_PROXY`는 "
                 "그 프록시를, `CODEX_CA_CERTIFICATE`는 그 인증서를 가리키게 해서 Codex CLI를 실행하고, 지나가는 "
                 "응답을 읽기만 해요. 바꾸거나 저장하는 건 없어요."},
                {"term": "대조군", "text": "터미널 버전은 기본으로 내 모델 바로 뒤에 비교용 모델(`gpt-5.6-sol`)을 "
                 "하나 더 검사해요(`--control`로 바꾸고 `--no-control`로 꺼요). 그쪽은 정상인데 내 모델만 다르면, "
                 "내 모델에만 바꿔치기가 일어난다는 뜻이에요. 창에서는 쓰지 않아요."},
            ]},
        ],
        "guide": {
            "heading": "안녕하세요! 이 탭은 이런 일을 해요",
            "items": [
                {"icon": "🚀", "title": "모니터링 시작을 눌러요",
                 "text": "Codex CLI 창이 새로 열려요. 그 창에서 평소처럼 작업하면 돼요."},
                {"icon": "🔍", "title": "대답한 모델을 한 줄씩 적어요",
                 "text": "Codex가 모델을 부를 때마다 실제로 누가 대답했는지 확인해서, 요청한 모델과 대답한 모델을 "
                         "한 줄에 나란히 적어요. 판정은 줄 색으로 보여 줘요."},
                {"icon": "🚦", "title": "초록은 정상, 빨강은 바꿔치기",
                 "text": "초록이면 고른 모델이 대답한 거고, 빨강이면 몰래 다른 모델로 넘어간 거예요. 주황이면 서버 "
                         "오류처럼 한 번 확인해 볼 일이 생긴 거예요."},
                {"icon": "🔒", "title": "전부 내 컴퓨터 안에서 처리해요",
                 "text": "프롬프트·파일·답변은 저장하지 않고, 모델 이름과 ID 같은 짧은 기록만 메모리에 둬요."},
                {"icon": "💻", "title": "Codex CLI 전용이에요",
                 "text": "데스크톱 앱은 아직 지켜볼 수 없어요. 다 끝나면 중지를 눌러 주세요."},
            ],
            "skip": "다시 보지 않기",
            "ok": "알겠어요!",
        },
        "about": {
            "lead": "Codex 요청에 실제로 어떤 모델이 대답했는지 알려 주는 고양이 탐정이에요.",
            "paras": [
                "서버가 응답 객체에 적어 보낸 모델 이름을 읽어요. 화면에 보이는 이름이 아니라 실제로 대답한 "
                "모델이에요.",
                "2026년 9월 22일, ChatGPT Pro 계정에서 gpt-6-astra 모델 요청을 gpt-5.6-luna 모델이 처리하는 것을 "
                "패킷 캡처로 확인하고 이 도구를 만들었어요.",
                "터미널 버전(`codex-routing-detector`, 소스에서는 `python codex_routing_detector.py`)에는 옵션이 "
                "더 많아요. 자세한 건 README를 봐 주세요.",
            ],
            "repo": "GitHub에서 보기",
        },
    },
    "en": {
        "usage": [
            {"icon": "🐾", "title": "One button is all it takes", "numbered": True, "items": [
                "Pick the model to check in the **Setup** row. It starts on the model in "
                "`~/.codex/config.toml`.",
                "Press **Check** and I'll send Codex one tiny prompt, asking it to reply with just \"pong\".",
                "About 30 seconds later the big card at the top tells you the result. The **Responses** list "
                "below shows the model you asked for next to the one that really answered.",
            ]},
            {"icon": "🎨", "title": "Reading the card colors", "items": [
                {"chip": "Rerouted", "tone": "bad", "text": "A different model answered instead of the one you "
                 "asked for."},
                {"chip": "OK", "tone": "ok", "text": "The model you chose answered, just as asked."},
                {"chip": "Needs a look", "tone": "warn", "text": "The server refused a model this account can't "
                 "use, returned an error such as \"at capacity\", or no complete answer came back. Not a "
                 "switcheroo; **Details** says which."},
            ]},
            {"icon": "📋", "title": "Keeping the result", "items": [
                {"term": "Copy report", "text": "Puts the full report, response ids included, on the clipboard. "
                 "Paste it straight into a bug report or a support ticket."},
                {"term": "Save JSON", "text": "Saves the same report as a JSON file."},
                {"term": "Log folder", "text": "Opens the folder with the raw frames the server sent."},
                {"term": "Details", "text": "Shows your plan and usage, the Codex path and where the logs are."},
            ]},
            {"icon": "⚙️", "title": "The Setup row", "items": [
                {"term": "model", "text": "The list comes from Codex's own model catalog. For anything else, "
                 "pick **Type a model...** at the bottom. A router-style name such as `openai/gpt-6-astra` is "
                 "checked without the `openai/` prefix (the server refuses the prefixed name)."},
                {"term": "effort", "text": "The `reasoning effort` sent with the check. Only the levels the chosen "
                 "model supports are offered (`ultra` is left out: it spawns sub-agents and costs far more). "
                 "`low` uses the least, and the substitutions seen so far happened regardless of it."},
                {"term": "repeat", "text": "Runs the check 1 to 10 times. Handy for seeing whether the server "
                 "flips back and forth."},
                {"term": "Wire mode", "text": "Records the traffic outside Codex with mitmproxy. The verdict is the "
                 "same as the default mode; turn it on when you need evidence to show someone. Install it with "
                 "`pip install mitmproxy`, then reopen this window to enable the switch."},
                {"term": "codex · auto-detect", "text": "I find the codex binary by myself. Only if I can't, click "
                 "here and pick it yourself."},
            ]},
            {"icon": "👀", "title": "Live monitor (Codex CLI only)", "items": [
                "Press **Start monitoring** and a new Codex CLI window opens. Work there as usual; every request "
                "adds a line here.",
                "The **Session** row shows the **model** and **effort** set in `config.toml`. I re-read the file "
                "whenever it changes, and clicking **config.toml** opens it.",
                "**Folder** is where the Codex window opens. Click the path next to the **Start monitoring** "
                "button to change it. You can change it while the monitor is off, and it's remembered.",
                "**Stop** closes the Codex window too, because that window can't reach the server without the "
                "monitor. Closing the Codex window yourself stops the monitor too.",
                "**Copy report** puts the rows on the clipboard. They're cleared when you press **Clear** (after "
                "stopping) or start monitoring again.",
                "The Codex desktop app can't be watched. Desktop users can use the **Check** tab instead.",
            ]},
            {"icon": "🔒", "title": "Cost and privacy", "items": [
                "Each check sends two requests (warm-up + turn); with **repeat** at 3 that's six. They count like "
                "any other Codex usage, and the live monitor sends nothing of its own.",
                "Check logs keep your thread ids, your account user id and the probe prompt. No tokens or cookies, "
                "and never the request body or your home folder path.",
                "The live monitor keeps only model names, response ids, statuses, times, error codes and your "
                "plan and usage line, in memory. Prompts, files and answers pass through and are never saved.",
                "The proxy listens on 127.0.0.1 only, and its certificate is made for the session and deleted "
                "afterwards. Nothing is installed in the system certificate store.",
                "At startup I ask `api.github.com` once whether a newer version exists. The exe then downloads it "
                "from GitHub, verifies it and updates itself (`--no-auto-update` turns that off; "
                "`--no-update-check` skips the question too). Nothing else is fetched from the internet.",
            ]},
        ],
        "terms": [
            {"icon": "🔤", "title": "Words you'll see", "items": [
                {"term": "Requested model", "text": "The model you chose: the name the client put in its request."},
                {"term": "Served by", "text": "The name the server wrote into its own response object "
                 "(`response.created`, `response.completed`). That's the model that really answered, read from "
                 "the raw WebSocket messages, not from Codex's logs."},
                {"term": "Turn", "text": "The request that carries the prompt and gets the model's answer."},
                {"term": "Warm-up", "text": "A request Codex sends by itself right before the turn (internally "
                 "`prewarm`). It's a real request for the chosen model, so a warm-up answered by another model "
                 "is evidence too."},
                {"term": "Response id", "text": "The server's id for one response (`resp_...`). Quote it in a bug "
                 "report so the provider can look the request up."},
                {"term": "Time", "text": "The Check tab shows the server's UTC time (ending in `Z`); the Live "
                 "tab shows your computer's time."},
                {"term": "Status", "text": "`completed` / `failed` / `in_progress`, exactly as the server said."},
            ]},
            {"icon": "🏷️", "title": "Verdicts", "items": [
                "In the table, each row's color is its verdict. Hover a row to see the name below; Details and the "
                "copied report use the same names.",
                {"chip": "ok", "tone": "ok", "text": "The model you chose answered, and the turn completed."},
                {"chip": "REROUTED", "tone": "bad", "text": "A response object names another model. Warm-up or "
                 "turn, even if that response failed later, it's evidence of a switcheroo."},
                {"chip": "UNSUPPORTED", "tone": "warn", "text": "The server refused the model for this account. "
                 "Not a switcheroo."},
                {"chip": "ERROR", "tone": "warn", "text": "A server error, such as `server_is_overloaded`, which "
                 "Codex shows as \"Selected model is at capacity\". Try again in a moment."},
                {"chip": "UNKNOWN", "tone": "warn", "text": "Couldn't be confirmed: the response had no model name, "
                 "the turn was cut off before it finished, or only the warm-up was seen."},
                {"chip": "NO_DATA", "tone": "warn", "text": "No WebSocket messages at all. Codex isn't signed in, "
                 "couldn't start, or talks in a way this tool can't read (older Codex versions stream over HTTP). "
                 "Details says which."},
            ]},
            {"icon": "🔧", "title": "How does it find out?", "items": [
                {"term": "Trace mode", "text": "The default. Codex runs with "
                 "`RUST_LOG=tungstenite::protocol=trace`, so its WebSocket library logs every message it "
                 "receives, verbatim, before Codex touches it. The model name is read from there."},
                {"term": "Wire mode", "text": "A local mitmproxy with a throw-away certificate records both "
                 "directions of the WebSocket."},
                {"term": "Live monitor", "text": "A built-in proxy on 127.0.0.1 with a session-only certificate. "
                 "The Codex CLI starts with `HTTPS_PROXY` pointing at the proxy and `CODEX_CA_CERTIFICATE` "
                 "pointing at the certificate; responses are only read as they pass. Nothing is changed or "
                 "stored."},
                {"term": "Control", "text": "By default the terminal version also checks a second model "
                 "(`gpt-5.6-sol`) right after yours; `--control` picks another, `--no-control` turns it off. If "
                 "that one is fine while yours isn't, the substitution is specific to your model. The window "
                 "doesn't use it."},
            ]},
        ],
        "guide": {
            "heading": "Hi! Here's what this tab does",
            "items": [
                {"icon": "🚀", "title": "Press Start monitoring",
                 "text": "A new Codex CLI window opens. Work in it just like you always do."},
                {"icon": "🔍", "title": "One line per answer",
                 "text": "Every time Codex calls a model, I check which one really answered and add a line with the "
                         "model Codex asked for next to the one that answered. The line's color shows the verdict."},
                {"icon": "🚦", "title": "Green is good, red is a switcheroo",
                 "text": "Green means the model you chose answered. Red means it was quietly swapped for another "
                         "one. Amber means something needs a look, like a server error."},
                {"icon": "🔒", "title": "Everything stays on your computer",
                 "text": "Prompts, files and answers are never saved; only short records like model names and ids "
                         "are kept in memory."},
                {"icon": "💻", "title": "Codex CLI only",
                 "text": "The desktop app can't be watched yet. Press Stop when you're done."},
            ],
            "skip": "Don't show this again",
            "ok": "Got it!",
        },
        "about": {
            "lead": "A cat detective that tells you which model really answered your Codex request.",
            "paras": [
                "It reads the model name the server writes into its own response objects: the model that really "
                "answered, not the one on screen.",
                "Made on 22 September 2026, after packet captures showed gpt-6-astra requests being answered by "
                "gpt-5.6-luna on a ChatGPT Pro account.",
                "The terminal version (`codex-routing-detector`, or `python codex_routing_detector.py` from a "
                "checkout) has more options; see the README.",
            ],
            "repo": "View on GitHub",
        },
    },
}
