"""Live monitor tab: start with a fake Codex process, feed decoded messages, check the table,
banner and briefing, then end the session both ways (Stop, and Codex exiting by itself)."""
import json
import os
import gc
import pathlib
import sys
import tempfile
import time
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import codex_routing_detector as cmc  # noqa: E402
import codex_routing_proxy as crp  # noqa: E402

try:
    import tkinter as tk
    _root = getattr(tk, "_default_root", None) or tk.Tk()  # share the interpreter with test_gui.py
    _root.withdraw()
    HAVE_DISPLAY = True
except Exception:  # pragma: no cover - no display
    _root = None
    HAVE_DISPLAY = False

if HAVE_DISPLAY:
    import codex_routing_detector_gui as gui  # noqa: E402


def msg(direction: str, obj: dict, conn: int = 1) -> crp.WsMessage:
    return crp.WsMessage(direction, json.dumps(obj), time.time(), conn)


@unittest.skipUnless(HAVE_DISPLAY, "no display for tkinter")
@unittest.skipUnless(crp.have_crypto(), "cryptography not installed")
class LiveTab(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.orig_capture, cls.orig_find = cmc.run_capture, cmc.find_codex
        assert gui.install_fake_runner(), "fixtures missing"

    @classmethod
    def tearDownClass(cls):
        cmc.run_capture, cmc.find_codex = cls.orig_capture, cls.orig_find

    def setUp(self):
        os.environ[gui.SETTINGS_ENV] = str(pathlib.Path(tempfile.mkdtemp()) / "settings.json")
        self.root = tk.Toplevel(_root)
        self.root.withdraw()
        self.app = gui.App(self.root, lang="en", fake=True, update_check=False, confirm=False)

    def tearDown(self):
        gc.collect()  # dead Tk variables/images must be collected on the main thread, not in a worker
        if self.app.monitor is not None:
            self.app.monitor.stop()
            self.app.monitor = None
        self.root.destroy()

    def _pump(self, seconds: float = 0.6):
        end = time.time() + seconds
        while time.time() < end:
            self.root.update()
            time.sleep(0.05)

    def _feed(self, *messages):
        for m in messages:
            self.app.monitor.events.put(("message", m))
        self._pump(0.4)

    def test_tab_is_idle_at_start(self):
        self.assertEqual(self.app.nb.tab(self.app.page_live, "text"), "Live monitor (CLI)")
        self.assertEqual(str(self.app.btn_live_stop["state"]), "disabled")
        self.assertIn("Live monitor off", self.app.live_banner.cget("text"))
        self.assertIn("Codex CLI only", self.app.lbl_live_brief.cget("text"))
        self.assertTrue(self.app.var_live_cfg.get())

    def test_session_rows_banner_and_stop(self):
        self.app.start_live(confirm=False)
        self.assertIsNotNone(self.app.monitor)
        self.assertEqual(str(self.app.btn_live_start["state"]), "disabled")
        self.assertEqual(str(self.app.btn_live_stop["state"]), "normal")
        self._pump(0.4)
        self.assertIn("Watching", self.app.live_banner.cget("text"))
        self.assertIn("127.0.0.1:", self.app.var_live_status.get())
        notes = self.app.live_notes.get("1.0", "end")
        self.assertIn("proxy listening", notes)
        self.assertIn("codex-fake", notes)

        self.app.monitor.events.put(("ws_open", {"conn": 1, "routing_hint": "model=gpt-6-astra;tier=priority",
                                                 "watched": True, "deflate": True}))
        self._feed(msg("c2s", {"type": "response.create", "model": "gpt-6-astra", "input": [{"role": "user"}]}),
                   msg("s2c", {"type": "codex.rate_limits", "plan_type": "pro",
                               "rate_limits": {"primary": {"used_percent": 9}, "limit_reached": False}}),
                   msg("s2c", {"type": "response.created", "response": {"id": "resp_a", "model": "gpt-5.6-luna",
                                                                       "status": "in_progress"}}))
        rows = [self.app.live_tree.item(i, "values") for i in self.app.live_tree.get_children()]
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0][2], rows[0][3], rows[0][4], rows[0][6]), ("gpt-6-astra", "turn", "gpt-5.6-luna", "REROUTED"))
        self.assertIn("REROUTED: gpt-6-astra -> gpt-5.6-luna (1 of 1)", self.app.live_banner.cget("text"))
        brief = self.app.lbl_live_brief.cget("text")
        self.assertIn("1 of 1 responses were answered by gpt-5.6-luna", brief)
        self.assertIn("Plan pro, 9%", brief)
        self.assertIn("not a usage-limit fallback", brief)

        self._feed(msg("s2c", {"type": "response.completed", "response": {"id": "resp_a", "model": "gpt-5.6-luna",
                                                                         "status": "completed"}}))
        rows = [self.app.live_tree.item(i, "values") for i in self.app.live_tree.get_children()]
        self.assertEqual(len(rows), 1)  # updated in place, not duplicated
        self.assertEqual(rows[0][5], "completed")
        self.assertEqual(str(self.app.btn_live_copy["state"]), "normal")

        # language toggle keeps the rows and relabels the banner
        self.app.toggle_language()
        self.assertIn("바꿔치기 감지", self.app.live_banner.cget("text"))
        self.assertEqual(len(self.app.live_tree.get_children()), 1)
        self.app.toggle_language()

        self.app.stop_live(ask=False)
        self.assertIsNone(self.app.monitor)
        self.assertEqual(self.app.var_live_status.get(), "Stopped.")
        self.assertEqual(str(self.app.btn_live_start["state"]), "normal")
        self.assertIn("REROUTED", self.app.live_banner.cget("text"))  # the result stays on screen
        self.app.root.clipboard_clear()
        self.app.copy_live_report()
        self.assertIn("resp_a", self.app.root.clipboard_get())
        self.app.clear_live()
        self.assertEqual(len(self.app.live_tree.get_children()), 0)
        self.assertIn("Live monitor off", self.app.live_banner.cget("text"))

    def test_codex_exit_ends_the_session_and_ok_summary(self):
        self.app.start_live(confirm=False)
        self._feed(msg("c2s", {"type": "response.create", "model": "gpt-6-astra"}),
                   msg("s2c", {"type": "response.completed", "response": {"id": "r1", "model": "gpt-6-astra",
                                                                         "status": "completed", "previous_response_id": "p"}}))
        self.assertIn("OK so far: 1 response(s)", self.app.live_banner.cget("text"))
        proc = self.app.monitor.proc
        proc.finish(0)
        self._pump(0.8)
        self.assertIsNone(self.app.monitor)
        self.assertIn("Codex exited (code 0)", self.app.var_live_status.get())
        self.assertIn("OK so far", self.app.live_banner.cget("text"))
        self.assertEqual(str(self.app.btn_live_start["state"]), "normal")

    def test_start_is_refused_without_codex(self):
        orig = cmc.find_codex
        cmc.find_codex = lambda explicit: (None, "not found on PATH")
        try:
            self.app.start_live(confirm=False)
            self.assertIsNone(self.app.monitor)
            self.assertIn("could not start", self.app.var_live_status.get())
            self.assertIn("not found", self.app.live_notes.get("1.0", "end"))
        finally:
            cmc.find_codex = orig

    def test_messages_queued_before_codex_exit_are_not_lost(self):
        self.app.start_live(confirm=False)
        self._pump(0.3)
        q = self.app.monitor.events
        q.put(("message", msg("c2s", {"type": "response.create", "model": "gpt-6-astra"})))
        q.put(("codex_exit", 0))
        q.put(("message", msg("s2c", {"type": "response.completed", "response": {"id": "late", "model": "gpt-5.6-luna",
                                                                                "status": "completed", "previous_response_id": "p"}})))
        self._pump(0.5)
        self.assertIsNone(self.app.monitor)
        self.assertEqual(len(self.app.live_tree.get_children()), 1)
        self.assertIn("REROUTED", self.app.live_banner.cget("text"))

    def test_guide_popup_on_first_visit_and_skip_flag(self):
        self.app.nb.select(self.app.page_live)
        self._pump(0.3)
        win = self.app.guide_window
        self.assertIsNotNone(win)
        self.assertTrue(win.winfo_exists())
        self.assertIn("Live monitor", win.title())
        win.destroy()
        self._pump(0.2)
        self.app.nb.select(self.app.page_check)
        self.app.nb.select(self.app.page_live)
        self._pump(0.2)
        self.assertFalse(self.app.guide_window.winfo_exists())  # once per session
        win = self.app.show_guide(force=True)
        self.assertTrue(win.winfo_exists())
        self.app.settings["skip_live_guide"] = True
        gui.save_settings(self.app.settings)
        win.destroy()
        self._pump(0.2)
        root2 = tk.Toplevel(_root)
        root2.withdraw()
        app2 = gui.App(root2, lang="ko", fake=True, update_check=False, confirm=False)
        app2.nb.select(app2.page_live)
        root2.update()
        self.assertIsNone(app2.guide_window)
        root2.destroy()

    def test_check_tab_still_works_next_to_the_live_tab(self):
        self.app.var_model.set("gpt-6-astra")
        self.app.start_check()
        end = time.time() + 15
        while time.time() < end and self.app.result is None:
            self.root.update()
            time.sleep(0.05)
        self.assertIsNotNone(self.app.result)
        self.assertEqual(self.app.result.overall, "REROUTED")
        self.assertEqual(len(self.app.tree.get_children()), 2)


if __name__ == "__main__":
    unittest.main()
