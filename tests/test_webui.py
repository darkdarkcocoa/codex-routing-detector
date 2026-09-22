"""Web UI logic tests: drive WebApp without a window (window=None) and read the view model the
page would render. No codex process is launched: run_capture() is replaced by the fixture runs."""
import json
import os
import pathlib
import sys
import tempfile
import time
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import codex_routing_detector as cmc  # noqa: E402
import codex_routing_detector_gui as gui  # noqa: E402
import codex_routing_proxy as crp  # noqa: E402
import codex_routing_webui as webui  # noqa: E402


def msg(direction: str, obj: dict, conn: int = 1) -> crp.WsMessage:
    return crp.WsMessage(direction, json.dumps(obj), time.time(), conn)


class WebUiBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.orig_capture, cls.orig_find = cmc.run_capture, cmc.find_codex
        assert gui.install_fake_runner(), "fixtures missing"

    @classmethod
    def tearDownClass(cls):
        cmc.run_capture, cmc.find_codex = cls.orig_capture, cls.orig_find

    def setUp(self):
        os.environ[gui.SETTINGS_ENV] = str(pathlib.Path(tempfile.mkdtemp()) / "settings.json")
        self.app = webui.WebApp(lang="en", fake=True, update_check=False, confirm=False)

    def tearDown(self):
        self.app.shutdown()

    def wait_done(self, seconds: float = 20.0):
        end = time.time() + seconds
        while time.time() < end:
            if self.app.worker is None and self.app.result is not None:
                return
            time.sleep(0.05)
        self.fail("check did not finish in time")

    def wait_vm(self, pred, seconds: float = 5.0):
        end = time.time() + seconds
        while time.time() < end:
            vm = self.app.build_vm()
            if pred(vm):
                return vm
            time.sleep(0.05)
        self.fail("view model never satisfied the condition")


class CheckFlow(WebUiBase):
    def test_check_fills_rows_and_verdict(self):
        self.app.set_option("model", "gpt-6-astra")
        self.app.start_check(confirm=False)
        self.assertEqual(self.app.build_vm()["check"]["phase"], "running")
        self.assertFalse(self.app.build_vm()["check"]["canCheck"])
        self.wait_done()
        vm = self.app.build_vm()
        c = vm["check"]
        self.assertEqual(self.app.result.overall, "REROUTED")
        self.assertEqual(c["tone"], "bad")
        self.assertEqual(c["chip"], webui.UI["en"]["chipBad"])
        self.assertEqual(len(c["rows"]), 2)  # warm-up + turn, no control probe
        self.assertEqual(c["rows"][0]["requested"], "gpt-6-astra")
        self.assertEqual(c["rows"][0]["served"], "gpt-5.6-luna")
        self.assertEqual(c["rows"][0]["tone"], "bad")
        self.assertIn("plan=pro", c["details"])
        self.assertIn("logs:", c["details"])
        self.assertTrue(c["canCopy"] and c["canJson"] and c["canLogs"])
        self.assertTrue(c["canCheck"])
        report = self.app.copy_report()
        self.assertIn("resp_", report["text"])

    def test_window_runs_no_control_probe(self):
        self.assertIsNone(self.app.options().control)

    def test_language_toggle_keeps_the_result(self):
        self.app.start_check(confirm=False)
        self.wait_done()
        self.app.set_lang("ko")
        vm = self.app.build_vm()
        self.assertEqual(vm["lang"], "ko")
        self.assertEqual(vm["check"]["head"], webui.UI["ko"]["badHead"])
        self.assertEqual(len(vm["check"]["rows"]), 2)
        self.assertIn("요청했지만", vm["check"]["brief"])  # ko brief_rerouted

    def test_unsupported_maps_to_warn_tone(self):
        self.app.set_option("model", "gpt-5.6-sol")  # the sol fixture is a capacity error
        self.app.start_check(confirm=False)
        self.wait_done()
        c = self.app.build_vm()["check"]
        self.assertEqual(c["tone"], "warn")
        self.assertEqual(c["chip"], webui.UI["en"]["chipWarn"])

    def test_repeat_is_clamped(self):
        self.app.set_option("repeat", "99")
        self.assertEqual(self.app.opt["repeat"], webui.MAX_REPEAT)
        self.app.set_option("repeat", "0")
        self.assertEqual(self.app.opt["repeat"], 1)
        self.app.set_option("repeat", "junk")
        self.assertEqual(self.app.opt["repeat"], 1)

    def test_confirm_dialog_flow_and_skip_is_remembered(self):
        app = webui.WebApp(lang="en", fake=True, update_check=False, confirm=True)
        try:
            ask = app.request_check()
            self.assertIsNotNone(ask)
            self.assertIn("gpt-", ask["body"])
            self.assertIsNone(app.worker)  # not started yet
            app.run_check_confirmed(skip=True)
            self.assertIsNotNone(app.worker)
            self.assertTrue(gui.load_settings().get("skip_confirm"))
            end = time.time() + 20
            while app.worker is not None and time.time() < end:
                time.sleep(0.05)
            self.assertIsNone(app.request_check())  # second run starts without a dialog
            end = time.time() + 20
            while app.worker is not None and time.time() < end:
                time.sleep(0.05)
        finally:
            app.shutdown()

    def test_fatal_error_keeps_ui_usable(self):
        self.app.result = cmc.CheckResult(error="boom", error_kind="codex_missing")
        self.app.phase = "done"
        c = self.app.build_vm()["check"]
        self.assertEqual(c["tone"], "warn")
        self.assertIn("boom", c["details"])
        self.assertIn(gui.STRINGS["en"]["codex_hint"], c["details"])
        self.assertTrue(c["canCopy"])
        self.assertFalse(c["canJson"] or c["canLogs"])

    def test_page_builds_with_embedded_assets(self):
        page = webui.build_page()
        self.assertIn("data:image/png;base64,", page)
        self.assertNotIn("__MASCOT__", page)
        # regression: asset-token replacement must never rewrite the page's own script
        # (a JS global named like a token once became "window.data:image/png..." — a syntax error)
        self.assertIn("window.MOOD_IDLE_SRC", page)
        self.assertNotIn("window.data:", page)
        for anchor in ("c-hero", "l-hero", "sel-model", "btn-livecopy", "c-details"):
            self.assertIn(anchor, page)

    def test_js_api_facade_exposes_only_methods(self):
        # regression: handing WebApp itself to pywebview made it crawl the window/threads
        # (public attributes are walked recursively to build the JS bridge)
        api = webui.JsApi(self.app)
        public = [n for n in dir(api) if not n.startswith("_")]
        self.assertEqual(sorted(public), sorted(webui.JsApi._METHODS))
        for n in public:
            self.assertTrue(callable(getattr(api, n)), n)
        self.assertIsNone(api.request_check())  # delegation reaches the app (confirm off -> starts)
        self.wait_done()

    def test_vm_is_json_serializable(self):
        self.app.start_check(confirm=False)
        self.wait_done()
        json.dumps(self.app.build_vm())


@unittest.skipUnless(crp.have_crypto(), "cryptography not installed")
class LiveFlow(WebUiBase):
    def start(self):
        self.app.start_live(confirm=False)
        self.assertIsNotNone(self.app.monitor)

    def feed(self, *messages):
        for m in messages:
            self.app.monitor.events.put(("message", m))

    def test_live_rows_summary_stop_and_clear(self):
        self.start()
        vm = self.wait_vm(lambda v: "proxy listening" in v["live"]["notes"])
        self.assertTrue(vm["live"]["on"])
        self.assertEqual(vm["live"]["tone"], "running")
        self.assertIn("127.0.0.1:", vm["live"]["status"])
        self.app.monitor.events.put(("ws_open", {"conn": 1, "routing_hint": "model=gpt-6-astra;tier=priority",
                                                 "watched": True, "deflate": True}))
        self.feed(msg("c2s", {"type": "response.create", "model": "gpt-6-astra", "input": [{"role": "user"}]}),
                  msg("s2c", {"type": "codex.rate_limits", "plan_type": "pro",
                              "rate_limits": {"primary": {"used_percent": 9}, "limit_reached": False}}),
                  msg("s2c", {"type": "response.created", "response": {"id": "resp_a", "model": "gpt-5.6-luna",
                                                                       "status": "in_progress"}}))
        vm = self.wait_vm(lambda v: len(v["live"]["rows"]) == 1)
        row = vm["live"]["rows"][0]
        self.assertEqual((row["requested"], row["served"], row["tone"]), ("gpt-6-astra", "gpt-5.6-luna", "bad"))
        self.assertEqual(vm["live"]["tone"], "bad")
        self.assertIn("1 of 1 responses were answered by gpt-5.6-luna", vm["live"]["brief"])
        self.assertIn("not a usage-limit fallback", vm["live"]["brief"])

        self.feed(msg("s2c", {"type": "response.completed", "response": {"id": "resp_a", "model": "gpt-5.6-luna",
                                                                         "status": "completed"}}))
        vm = self.wait_vm(lambda v: v["live"]["rows"] and v["live"]["rows"][0]["status"] == "completed")
        self.assertEqual(len(vm["live"]["rows"]), 1)  # updated in place, not duplicated

        report = self.app.copy_live_report()
        self.assertIn("resp_a", report["text"])

        self.app.stop_live()
        self.assertIsNone(self.app.monitor)
        vm = self.app.build_vm()
        self.assertFalse(vm["live"]["on"])
        self.assertEqual(vm["live"]["status"], gui.STRINGS["en"]["live_stopped"])
        # per the design spec the hero returns to the neutral off state on Stop...
        self.assertEqual(vm["live"]["tone"], "idle")
        # ...while the rows keep the session's verdicts until Clear
        self.assertEqual(vm["live"]["rows"][0]["tone"], "bad")
        self.assertEqual(vm["live"]["rows"][0]["verdict"], "REROUTED")
        self.assertTrue(vm["live"]["canClear"])
        self.app.clear_live()
        vm = self.app.build_vm()
        self.assertEqual(vm["live"]["rows"], [])
        self.assertEqual(vm["live"]["tone"], "idle")

    def test_codex_exit_ends_the_session_without_losing_messages(self):
        self.start()
        self.feed(msg("c2s", {"type": "response.create", "model": "gpt-6-astra", "input": [{"role": "user"}]}),
                  msg("s2c", {"type": "response.completed", "response": {"id": "resp_b", "model": "gpt-6-astra",
                                                                         "status": "completed",
                                                                         "previous_response_id": "resp_a"}}))
        self.app.monitor.events.put(("codex_exit", 0))
        vm = self.wait_vm(lambda v: not v["live"]["on"])
        self.assertEqual(len(vm["live"]["rows"]), 1)  # the message queued before the exit is kept
        self.assertIn("exited", vm["live"]["status"])
        self.assertIsNone(self.app.monitor)

    def test_start_is_refused_without_codex(self):
        cmc.find_codex = lambda explicit: (None, "not found")
        try:
            self.app.start_live(confirm=False)
            self.assertIsNone(self.app.monitor)
            vm = self.app.build_vm()
            self.assertIn("codex binary not found", vm["live"]["notes"])
        finally:
            assert gui.install_fake_runner()

    def test_stop_confirm_path(self):
        self.start()
        ask = self.app.request_live()
        self.assertEqual(ask, {"mode": "stop"})  # a running fake session asks before stopping
        self.app.stop_live_confirmed()
        self.assertIsNone(self.app.monitor)


class FakeWindow:
    """Records evaluate_js calls; an optional delay imitates a busy WebView2 UI thread."""

    def __init__(self, delay: float = 0.0):
        self.calls = []
        self.destroyed = False
        self.delay = delay

    def evaluate_js(self, script):
        if self.delay:
            time.sleep(self.delay)
        self.calls.append(script)

    def destroy(self):
        self.destroyed = True


class Regressions(WebUiBase):
    def wait_calls(self, win, pred, seconds=3.0):
        end = time.time() + seconds
        while time.time() < end:
            if pred(win.calls):
                return
            time.sleep(0.02)
        self.fail(f"expected evaluate_js call never arrived; got {win.calls!r}")

    def test_file_dialog_filters_are_valid_for_pywebview(self):
        # regression: a bare "codex" pattern raised ValueError inside pywebview, so the
        # codex picker silently did nothing on Windows
        webview_util = __import__("webview.util", fromlist=["parse_file_type"])
        for filt in ("codex (*.exe;*.cmd)", "All files (*.*)", "JSON (*.json)"):
            webview_util.parse_file_type(filt)  # raises on an invalid filter

    def test_push_never_blocks_the_caller(self):
        # regression: workers used to call evaluate_js directly (Control.Invoke), which could
        # deadlock against a closing window; push() must only signal the pusher thread
        win = FakeWindow(delay=0.4)
        self.app.window = win
        t0 = time.time()
        self.app.push()
        self.assertLess(time.time() - t0, 0.2)
        self.wait_calls(win, lambda c: any("window.render" in s for s in c))

    @unittest.skipUnless(crp.have_crypto(), "cryptography not installed")
    def test_on_closing_defers_the_confirm_and_never_evaluates_js_inline(self):
        # regression: on_closing ran evaluate_js on the UI thread it was blocking (deadlock)
        win = FakeWindow()
        self.app.window = win
        self.app.start_live(confirm=False)
        self.assertIsNotNone(self.app.monitor)
        t0 = time.time()
        keep_open = self.app.on_closing()
        self.assertLess(time.time() - t0, 0.5)
        self.assertFalse(keep_open)
        self.assertFalse(any("showStopConfirm" in s for s in win.calls[:1]))  # not called inline
        self.wait_calls(win, lambda c: any("showStopConfirm" in s for s in c))
        self.app.confirm_close()
        self.assertIsNone(self.app.monitor)
        self.assertTrue(win.destroyed)

    def test_update_hint_does_not_mask_the_run_status(self):
        # regression: a pip/manual update hint stayed in the status line forever
        self.app.update_status = "NEW version hint"
        self.app.start_check(confirm=False)
        self.assertNotIn("hint", self.app.build_vm()["check"]["status"])
        self.wait_done()
        self.assertNotIn("hint", self.app.build_vm()["check"]["status"])

    def test_custom_model_slug_is_accepted(self):
        # the tkinter combobox allowed free-text models; the web UI keeps that via the
        # "type a model" prompt -> set_option
        self.app.set_option("model", "gpt-experimental-unlisted")
        self.assertEqual(self.app.build_vm()["check"]["model"], "gpt-experimental-unlisted")
        self.assertEqual(self.app.options().models, ["gpt-experimental-unlisted"])
        self.assertIn("__custom__", webui.PAGE)

    def test_check_rows_carry_the_exact_verdict(self):
        # the verdict word (not just a colour) must stay readable per row
        self.app.start_check(confirm=False)
        self.wait_done()
        rows = self.app.build_vm()["check"]["rows"]
        self.assertTrue(all(r["verdict"] == "REROUTED" for r in rows))

    def test_page_loads_no_external_resources(self):
        # regression: the page fetched Google Fonts on every launch, contradicting the
        # README's "no network calls of its own" promise
        page = webui.build_page()
        self.assertNotIn("googleapis.com", page)
        self.assertNotIn("gstatic.com", page)
        self.assertNotIn("http://", page.split("<body>")[0])
        self.assertIn("data:font/woff2;base64,", page)
        # the Korean face ships as Google Fonts' unicode-range slices, all embedded
        self.assertGreater(page.count('font-family: "Jua"'), 50)
        self.assertNotIn("__FONT_GOWUN_FACES__", page)


if __name__ == "__main__":
    unittest.main()
