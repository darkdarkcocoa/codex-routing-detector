"""GUI smoke tests: build the window off-screen, feed it results, check what it shows.

They need a display (tkinter cannot run headless); they are skipped where none is available.
No codex process is launched: run_capture() is replaced by the bundled fixture runs.
"""
import pathlib
import sys
import time
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import codex_routing_detector as cmc  # noqa: E402

try:
    import tkinter as tk
    _root = tk.Tk()
    _root.withdraw()
    HAVE_DISPLAY = True
except Exception:  # pragma: no cover - no display
    _root = None
    HAVE_DISPLAY = False

if HAVE_DISPLAY:
    import codex_routing_detector_gui as gui  # noqa: E402


@unittest.skipUnless(HAVE_DISPLAY, "no display for tkinter")
class GuiSmoke(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.orig_capture, cls.orig_find = cmc.run_capture, cmc.find_codex
        assert gui.install_fake_runner(), "fixtures missing"

    @classmethod
    def tearDownClass(cls):
        cmc.run_capture, cmc.find_codex = cls.orig_capture, cls.orig_find

    def setUp(self):
        self.root = tk.Toplevel(_root)
        self.root.withdraw()
        self.app = gui.App(self.root, lang="en", fake=True, update_check=False)

    def tearDown(self):
        self.root.destroy()

    def _pump(self, seconds: float):
        end = time.time() + seconds
        while time.time() < end:
            self.root.update()
            if self.app.worker is None and self.app.result is not None:
                return
            time.sleep(0.05)

    def test_check_button_runs_and_fills_the_table(self):
        self.app.var_model.set("gpt-6-astra")
        self.app.var_control.set("gpt-5.6-sol")
        self.app.start_check()
        self.assertEqual(str(self.app.btn_check["state"]), "disabled")
        self._pump(15)
        res = self.app.result
        self.assertIsNotNone(res)
        self.assertEqual(res.overall, "REROUTED")
        rows = [self.app.tree.item(i, "values") for i in self.app.tree.get_children()]
        self.assertEqual(len(rows), 4)  # warm-up + turn for astra and for the control
        self.assertEqual(rows[0][1], "gpt-6-astra")
        self.assertEqual(rows[0][3], "gpt-5.6-luna")
        self.assertEqual(rows[0][6], "REROUTED")
        self.assertEqual(rows[3][6], "ERROR")  # control fixture ends in server_is_overloaded
        self.assertIn("REROUTED", self.app.banner.cget("text"))
        self.assertIn("gpt-6-astra -> gpt-5.6-luna", self.app.banner.cget("text"))
        self.assertEqual(str(self.app.btn_check["state"]), "normal")
        notes = self.app.notes.get("1.0", "end")
        self.assertIn("plan=pro", notes)
        self.assertIn("server_is_overloaded", notes)

    def test_language_toggle_relabels_without_losing_the_result(self):
        self.app.start_check()
        self._pump(15)
        self.app.toggle_language()
        self.assertEqual(self.app.btn_cancel.cget("text"), "취소")
        self.assertEqual(self.app.tree.heading("served")["text"], "실제 응답 모델")
        self.assertIn("바꿔치기 감지", self.app.banner.cget("text"))
        self.assertEqual(len(self.app.tree.get_children()), 4)
        self.app.toggle_language()
        self.assertEqual(self.app.btn_cancel.cget("text"), "Cancel")

    def test_no_control_option_in_either_language(self):
        self.app.var_control.set("(none)")
        opts = self.app.options()
        self.assertIsNone(opts.control)
        self.assertEqual(opts.models, [self.app.var_model.get()])
        self.app.var_control.set("(없음)")
        self.assertIsNone(self.app.options().control)
        self.app.toggle_language()
        self.assertEqual(self.app.var_control.get(), "(없음)")
        self.assertEqual(self.app.cb_control.cget("values")[0], "(없음)")

    def test_repeat_is_clamped(self):
        self.app.var_repeat.set("99")
        self.assertEqual(self.app.options().repeat, 10)
        self.app.var_repeat.set("")
        self.assertEqual(self.app.options().repeat, 1)

    def test_fatal_result_keeps_buttons_sane(self):
        self.app.q.put(("fatal", "RuntimeError: boom"))
        self._pump(3)
        self.assertIsNotNone(self.app.result)
        self.assertEqual(self.app.result.error, "RuntimeError: boom")
        self.assertEqual(str(self.app.btn_check["state"]), "normal")
        self.assertEqual(str(self.app.btn_json["state"]), "disabled")
        self.assertEqual(str(self.app.btn_logs["state"]), "disabled")
        self.assertEqual(str(self.app.btn_copy["state"]), "normal")
        self.assertIn("boom", self.app.notes.get("1.0", "end"))
        self.app.toggle_language()  # relabelling after an error keeps the error banner
        self.assertTrue(self.app.banner.cget("text").startswith("오류"), self.app.banner.cget("text"))

    def test_language_toggle_keeps_status_text(self):
        self.app.start_check()
        self._pump(15)
        self.app.var_status.set("custom status")
        self.app.toggle_language()
        self.assertEqual(self.app.var_status.get(), "custom status")

    def test_close_while_running_cancels_and_joins(self):
        self.app.start_check()
        self.root.update()
        self.app.on_close()
        self.assertTrue(self.app.cancel.cancelled())
        self.assertFalse(self.app.worker.is_alive())
        self.root = tk.Toplevel(_root)  # on_close destroyed the window; give tearDown a fresh one
        self.root.withdraw()

    def test_rerouted_then_cancelled_shows_rerouted_banner(self):
        self.app.start_check()
        self._pump(15)
        res = self.app.result
        res.cancelled = True
        self.app._render_result(res)
        self.assertIn("REROUTED", self.app.banner.cget("text"))

    def test_wire_error_gets_no_codex_hint(self):
        res = cmc.CheckResult(error="--wire needs mitmproxy", error_kind="wire")
        self.app.result = res
        self.app._render_result(res)
        notes = self.app.notes.get("1.0", "end")
        self.assertIn("mitmproxy", notes)
        self.assertNotIn("Codex...", notes)

    def test_language_toggle_mid_run_relabels_rows(self):
        self.app.start_check()
        end = time.time() + 15
        while time.time() < end and len(self.app.live_probes) < 1:
            self.root.update()
            time.sleep(0.05)
        self.app.toggle_language()
        rows = [self.app.tree.item(i, "values") for i in self.app.tree.get_children()]
        self.assertTrue(rows and rows[0][2] == "웜업", rows)
        self._pump(15)

    def test_help_menu_and_windows(self):
        self.assertEqual(self.app.menubar.entrycget(1, "label"), "Help")
        self.assertEqual(self.app.help_menu.entrycget(1, "label"), "Glossary")
        win = self.app.show_help("terms")
        body = win.help_text.get("1.0", "end")
        self.assertIn("Warm-up", body)
        self.assertIn("REROUTED", body)
        self.app.toggle_language()
        self.assertEqual(self.app.menubar.entrycget(1, "label"), "도움말")
        self.assertIn("웜업", win.help_text.get("1.0", "end"))  # open window follows the language
        usage = self.app.show_help("usage").help_text.get("1.0", "end")
        self.assertIn("기본 사용법", usage)
        about = self.app.show_help("about").help_text.get("1.0", "end")
        self.assertIn(cmc.__version__, about)
        self.assertIs(self.app.show_help("terms"), win)  # reused, not duplicated

    def test_github_link_opens_the_repository(self):
        import webbrowser
        opened = []
        original = webbrowser.open
        webbrowser.open = lambda url, *a, **k: opened.append(url) or True
        try:
            self.assertIn("<Button-1>", self.app.link_github.bind())  # click is wired up
            self.app.open_repo()  # a withdrawn window does not receive synthetic clicks
        finally:
            webbrowser.open = original
        self.assertEqual(opened, [gui.REPO_URL])
        self.assertIsNotNone(self.app.github_icon)
        self.assertIn(gui.REPO_URL, self.app.show_help("about").help_text.get("1.0", "end"))

    def test_update_badge_appears_and_opens_release_page(self):
        import webbrowser
        self.assertEqual(self.app.lbl_version.cget("text"), f"v{cmc.__version__}")
        self.app.q.put(("update", {"version": "9.9.9", "url": "https://example.test/rel"}))
        self._pump(1)
        text = self.app.lbl_version.cget("text")
        self.assertIn("NEW v9.9.9", text)
        self.assertEqual(self.app.lbl_version.cget("fg"), "#b3261e")
        opened = []
        original = webbrowser.open
        webbrowser.open = lambda url, *a, **k: opened.append(url) or True
        try:
            self.app.open_update()
        finally:
            webbrowser.open = original
        self.assertEqual(opened, ["https://example.test/rel"])
        self.app.toggle_language()
        self.assertIn("NEW v9.9.9", self.app.lbl_version.cget("text"))  # badge survives relabelling

    def _fake_update_env(self, frozen, download_ok=True):
        """Patch the pieces that touch the network, the exe file and the process."""
        import tempfile
        self._patched = (cmc.is_frozen, cmc.download_file, cmc.launch_replacer, cmc.dir_writable)
        calls = {"launch": [], "downloads": []}
        tmp = pathlib.Path(tempfile.mkdtemp())
        self.app.exe_path = tmp / "codex-routing-detector.exe"
        self.app.exe_path.write_bytes(b"MZ" + b"\0" * 10)

        def fake_download(url, dest, progress=None, timeout=30):
            calls["downloads"].append(url)
            if not download_ok:
                raise OSError("network down")
            dest.write_bytes(b"MZ" + b"\0" * 1_200_000)
            if progress:
                progress(1_200_002, 1_200_002)

        cmc.is_frozen = lambda: frozen
        cmc.download_file = fake_download
        cmc.launch_replacer = lambda target, new, args: calls["launch"].append((target, new, args)) or new
        cmc.dir_writable = lambda p: True
        self.addCleanup(self._restore_update_env)
        return calls

    def _restore_update_env(self):
        cmc.is_frozen, cmc.download_file, cmc.launch_replacer, cmc.dir_writable = self._patched

    def test_frozen_build_updates_itself_and_restarts(self):
        calls = self._fake_update_env(frozen=True)
        info = {"version": "9.9.9", "url": "https://x/rel",
                "asset": {"url": "https://x/codex-routing-detector.exe", "size": 1_200_002, "digest": None}}
        self.app.q.put(("update", info))
        end = time.time() + 5
        while time.time() < end and not calls["launch"]:
            try:
                self.root.update()
            except tk.TclError:  # the window destroys itself right after launching the replacer
                break
            time.sleep(0.05)
        self.assertEqual(len(calls["launch"]), 1, calls)
        target, new, args = calls["launch"][0]
        self.assertEqual(target, self.app.exe_path)
        self.assertEqual(new.name, "codex-routing-detector.new.exe")
        self.assertEqual(args[:2], ["--updated-from", cmc.__version__])
        self.assertIn("NEW v9.9.9", self.app.lbl_version.cget("text"))
        self.root = tk.Toplevel(_root)  # the app destroyed its window; give tearDown a fresh one
        self.root.withdraw()

    def test_failed_download_falls_back_to_the_badge(self):
        calls = self._fake_update_env(frozen=True, download_ok=False)
        info = {"version": "9.9.9", "url": "https://x/rel", "asset": {"url": "https://x/a.exe", "size": 1, "digest": None}}
        self.app.q.put(("update", info))
        self._pump(3)
        self.assertEqual(calls["launch"], [])
        self.assertIn("failed", self.app.var_status.get())
        self.assertFalse(self.app.updating)
        self.assertEqual(str(self.app.btn_check["state"]), "normal")
        self.assertIn("NEW v9.9.9", self.app.lbl_version.cget("text"))

    def test_source_install_gets_badge_and_pip_hint_only(self):
        calls = self._fake_update_env(frozen=False)
        info = {"version": "9.9.9", "url": "https://x/rel", "asset": {"url": "https://x/a.exe", "size": 1, "digest": None}}
        self.app.q.put(("update", info))
        self._pump(1)
        self.assertEqual(calls["downloads"], [])
        self.assertIn("pipx upgrade", self.app.var_status.get())
        self.assertIn("NEW v9.9.9", self.app.lbl_version.cget("text"))

    def test_updated_from_shows_confirmation(self):
        app = gui.App(tk.Toplevel(_root), lang="en", fake=True, update_check=False, updated_from="1.0.0")
        self.assertEqual(app.var_status.get(), f"Updated to v{cmc.__version__}.")
        app.root.destroy()

    def test_no_update_leaves_version_label_alone(self):
        self.app.q.put(("update", None))
        self._pump(1)
        self.assertEqual(self.app.lbl_version.cget("text"), f"v{cmc.__version__}")

    def test_poll_survives_a_bad_message(self):
        self.app.q.put(("progress", "probe_done", {"probe": object()}))  # malformed probe
        self._pump(1)
        self.app.q.put(("fatal", "after"))
        self._pump(3)
        self.assertEqual(self.app.result.error, "after")  # the loop kept polling

    def test_copy_report_puts_full_ids_on_clipboard(self):
        self.app.start_check()
        self._pump(15)
        self.app.copy_report()
        self.root.update()
        text = self.root.clipboard_get()
        self.assertIn("codex-routing-detector", text)
        self.assertIn("resp_TEST001", text)


class RunCheckOffline(unittest.TestCase):
    """run_check() end to end with the fixture runner, no tkinter needed."""

    def setUp(self):
        self.orig = cmc.run_capture, cmc.find_codex
        import codex_routing_detector_gui as g  # noqa: F401  (import works without a display for this part)
        assert g.install_fake_runner()

    def tearDown(self):
        cmc.run_capture, cmc.find_codex = self.orig

    def test_progress_events_and_result(self):
        events = []
        res = cmc.run_check(cmc.CheckOptions(models=["gpt-6-astra"], control="gpt-5.6-sol"),
                            progress=lambda ev, info: events.append(ev))
        self.assertIsNone(res.error)
        self.assertEqual(events, ["start", "probe_start", "probe_done", "probe_start", "probe_done"])
        self.assertEqual(res.overall, "REROUTED")
        self.assertEqual(res.exit_code, 2)
        self.assertIn("VERDICT: REROUTED", res.report())
        self.assertEqual(res.json()["overall"]["verdict"], "REROUTED")

    def test_cancel_before_second_probe(self):
        cancel = cmc.Canceller()

        def progress(ev, info):
            if ev == "probe_done":
                cancel.cancel()

        res = cmc.run_check(cmc.CheckOptions(models=["gpt-6-astra"], control="gpt-5.6-sol"), progress=progress, cancel=cancel)
        self.assertTrue(res.cancelled)
        self.assertEqual(len(res.probes), 1)
        # probe 1 already proved the substitution, so the verdict is kept and the cancellation is a note
        self.assertEqual(res.overall, "REROUTED")
        self.assertTrue(any("cancelled after 1 of 2" in l for l in res.summary_lines))
        self.assertIn("cancelled after 1 of 2", res.report())

    def test_cancel_after_a_rerouted_probe_keeps_the_evidence(self):
        cancel = cmc.Canceller()

        def progress(ev, info):
            if ev == "probe_done":
                cancel.event.set()  # pressed while probe 2 has not started yet
        res = cmc.run_check(cmc.CheckOptions(models=["gpt-6-astra"], control="gpt-5.6-sol"), progress=progress, cancel=cancel)
        self.assertTrue(res.cancelled)
        self.assertEqual((res.overall, res.exit_code), ("REROUTED", 2))
        self.assertTrue(res.summary_lines[0].startswith("VERDICT: REROUTED"))
        self.assertTrue(any("cancelled after 1 of 2" in l for l in res.summary_lines))
        self.assertIn("VERDICT: REROUTED", res.report())

    def test_version_probe_is_cancellable(self):
        seen = []
        original = cmc.run_capture

        def capture(cmd, timeout, env=None, cwd=None, on_start=None):
            seen.append(on_start is not None)
            return original(cmd, timeout, env, cwd, on_start)
        cmc.run_capture = capture
        try:
            cmc.run_check(cmc.CheckOptions(models=["gpt-6-astra"], control=None), cancel=cmc.Canceller())
        finally:
            cmc.run_capture = original
        self.assertTrue(all(seen))  # --version, exec --help and the probe all got on_start

    def test_cancel_before_first_probe_is_not_reported_as_ok(self):
        cancel = cmc.Canceller()
        cancel.cancel()
        res = cmc.run_check(cmc.CheckOptions(models=["gpt-6-astra"], control=None), cancel=cancel)
        self.assertTrue(res.cancelled)
        self.assertEqual(res.probes, [])
        self.assertNotIn("VERDICT: OK", res.report())
        self.assertIn("CANCELLED", res.report())

    def test_cancel_after_last_probe_is_a_complete_run(self):
        cancel = cmc.Canceller()

        def progress(ev, info):
            if ev == "probe_done":
                cancel.cancel()  # nothing is running any more, so nothing was killed

        res = cmc.run_check(cmc.CheckOptions(models=["gpt-6-astra"], control=None), progress=progress, cancel=cancel)
        self.assertFalse(res.cancelled)
        self.assertEqual(res.overall, "REROUTED")


if __name__ == "__main__":
    unittest.main()
