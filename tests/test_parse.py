"""Regression tests for the frame parser, verdict logic, report summary and log sanitizing.

Fixtures are complete `RUST_LOG=tungstenite::protocol=trace` runs captured on 2026-09-22 with
every response id, thread id and the user id replaced by placeholders:

  astra_served_by_luna.log   requested gpt-6-astra, both responses served by gpt-5.6-luna
  sol_capacity_error.log     requested gpt-5.6-sol, warm-up ok, turn failed with server_is_overloaded
"""
import io
import json
import os
import pathlib
import subprocess
import sys
import time
import unittest
from contextlib import redirect_stdout

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import codex_routing_detector as cmc  # noqa: E402

FIX = pathlib.Path(__file__).parent / "fixtures"


def load(name: str) -> str:
    return (FIX / name).read_text(encoding="utf-8")


def probe(requested, responses=(), stream_errors=(), is_control=False, index=1):
    p = cmc.Probe(index=index, requested=requested, effort="low", tier=None, is_control=is_control, method="trace")
    p.responses = list(responses)
    p.stream_errors = list(stream_errors)
    return p


def rec(rid, model, status="completed", kind="turn", **kw):
    r = cmc.ResponseRecord(rid, model, status, "default", 1790000000, kind, **kw)
    if model:
        r.models_seen = [model]
    return r


class ParseTraceFrames(unittest.TestCase):
    def test_full_astra_run(self):
        frames, sent, unparsed = cmc.parse_trace_frames(load("astra_served_by_luna.log"))
        self.assertEqual(unparsed, 0)
        self.assertEqual(sent, 2)
        types = [f["type"] for f in frames]
        self.assertEqual(types.count("response.created"), 2)
        self.assertEqual(types.count("response.completed"), 2)
        self.assertIn("codex.rate_limits", types)

    def test_non_trace_lines_are_ignored(self):
        text = "model: gpt-6-astra\nERROR: Selected model is at capacity. Please try a different model.\n"
        self.assertEqual(cmc.parse_trace_frames(text), ([], 0, 0))

    def test_truncated_json_is_counted_not_raised(self):
        line = '2026-09-22T02:16:47Z TRACE tungstenite::protocol: Received message {"type":"response.created","response":{"id":"resp_x"\n'
        frames, _, unparsed = cmc.parse_trace_frames(line)
        self.assertEqual((frames, unparsed), ([], 1))

    def test_trailing_text_after_json_is_tolerated(self):
        line = 'x TRACE tungstenite::protocol: Received message {"type":"response.created","response":{"id":"resp_1","model":"m"}} \x1b[0m\n'
        frames, _, unparsed = cmc.parse_trace_frames(line)
        self.assertEqual(unparsed, 0)
        self.assertEqual(frames[0]["response"]["model"], "m")

    def test_unicode_line_separators_inside_json_do_not_split_the_frame(self):
        payload = json.dumps({"type": "response.created", "response": {"id": "resp_1", "model": "a b"}}, ensure_ascii=False)
        frames, _, unparsed = cmc.parse_trace_frames("x TRACE tungstenite::protocol: Received message " + payload + "\r\n")
        self.assertEqual(unparsed, 0)
        self.assertEqual(frames[0]["response"]["model"], "a b")


class ServedModelDetection(unittest.TestCase):
    def test_astra_request_served_by_luna_is_rerouted_for_warmup_and_turn(self):
        frames, _, _ = cmc.parse_trace_frames(load("astra_served_by_luna.log"))
        responses, errors = cmc.collect_responses(frames)
        self.assertEqual(errors, [])
        self.assertEqual([r.kind for r in responses], ["warmup", "turn"])
        self.assertEqual([r.model for r in responses], ["gpt-5.6-luna", "gpt-5.6-luna"])
        self.assertEqual([r.status for r in responses], ["completed", "completed"])
        self.assertEqual([r.verdict("gpt-6-astra") for r in responses], ["REROUTED", "REROUTED"])
        self.assertEqual(responses[1].verdict("gpt-5.6-luna"), "ok")
        self.assertIsNotNone(responses[1].usage)
        self.assertEqual(probe("gpt-6-astra", responses).verdict(), "REROUTED")

    def test_capacity_error_on_the_turn_is_error_not_reroute(self):
        frames, _, _ = cmc.parse_trace_frames(load("sol_capacity_error.log"))
        responses, errors = cmc.collect_responses(frames)
        self.assertEqual(errors, [])
        self.assertEqual([r.kind for r in responses], ["warmup", "turn"])
        warm, turn = responses
        self.assertEqual((warm.model, warm.status, warm.verdict("gpt-5.6-sol")), ("gpt-5.6-sol", "completed", "ok"))
        self.assertEqual((turn.model, turn.status, turn.error_code), ("gpt-5.6-sol", "failed", "server_is_overloaded"))
        self.assertEqual(turn.verdict("gpt-5.6-sol"), "ERROR")
        self.assertEqual(probe("gpt-5.6-sol", responses).verdict(), "ERROR")

    def test_error_before_any_turn_makes_the_probe_an_error_even_if_warmup_was_fine(self):
        frames = [
            {"type": "response.created", "response": {"id": "resp_w", "model": "gpt-6-astra", "status": "in_progress"}},
            {"type": "response.completed", "response": {"id": "resp_w", "model": "gpt-6-astra", "status": "completed"}},
            {"type": "error", "error": {"code": "server_is_overloaded", "message": "overloaded"}},
        ]
        responses, errors = cmc.collect_responses(frames)
        self.assertEqual(responses[0].error_code, None)
        self.assertEqual(errors, [("server_is_overloaded", "overloaded")])
        self.assertEqual(probe("gpt-6-astra", responses, errors).verdict(), "ERROR")

    def test_model_change_mid_response_is_rerouted_and_noted(self):
        frames = [
            {"type": "response.created", "response": {"id": "resp_t", "model": "gpt-6-astra", "status": "in_progress",
                                                       "previous_response_id": "resp_w"}},
            {"type": "response.completed", "response": {"id": "resp_t", "model": "gpt-5.6-luna", "status": "completed",
                                                         "previous_response_id": "resp_w"}},
        ]
        responses, _ = cmc.collect_responses(frames)
        r = responses[0]
        self.assertEqual(r.models_seen, ["gpt-6-astra", "gpt-5.6-luna"])
        self.assertEqual(r.verdict("gpt-6-astra"), "REROUTED")
        self.assertIn("model changed mid-response: gpt-6-astra -> gpt-5.6-luna", r.notes("gpt-6-astra"))

    def test_case_and_dated_snapshot_count_as_match(self):
        self.assertEqual(cmc.models_match("gpt-6-astra", "GPT-6-Astra"), (True, None))
        ok, note = cmc.models_match("gpt-6-astra", "gpt-6-astra-2026-09-01")
        self.assertTrue(ok)
        self.assertIn("snapshot", note)
        self.assertEqual(cmc.models_match("gpt-6-astra", "gpt-6-astra-mini")[0], False)
        self.assertEqual(cmc.models_match("gpt-6-astra", "gpt-6-astra-mini-2026-09-01")[0], False)  # sibling model
        self.assertEqual(cmc.models_match("gpt-6-astra", "gpt-6-astra-2026-09-01-preview")[0], False)
        self.assertEqual(cmc.models_match("gpt-6-astra", None)[0], False)

    def test_same_failure_reported_twice_gives_one_error(self):
        frames = [
            {"type": "response.created", "response": {"id": "resp_t", "model": "gpt-5.6-sol", "status": "in_progress",
                                                       "previous_response_id": "resp_w"}},
            {"type": "response.failed", "response": {"id": "resp_t", "model": "gpt-5.6-sol", "status": "failed",
                                                      "previous_response_id": "resp_w",
                                                      "error": {"code": "server_is_overloaded", "message": "x"}}},
            {"type": "error", "error": {"code": "server_is_overloaded", "message": "x"}},
        ]
        responses, errors = cmc.collect_responses(frames)
        self.assertEqual(len(responses), 1)
        self.assertEqual(errors, [])
        self.assertEqual(responses[0].error_code, "server_is_overloaded")

    def test_kind_is_turn_when_previous_response_id_present(self):
        frames = [
            {"type": "response.created", "response": {"id": "resp_a", "model": "m", "status": "in_progress"}},
            {"type": "response.created", "response": {"id": "resp_b", "model": "m", "status": "in_progress",
                                                       "previous_response_id": "resp_a"}},
        ]
        responses, _ = cmc.collect_responses(frames)
        self.assertEqual([r.kind for r in responses], ["warmup", "turn"])

    def test_retry_with_fresh_id_after_error_is_scored_on_the_successful_turn(self):
        responses = [rec("resp_w", "gpt-6-astra", kind="warmup"),
                     rec("resp_t1", "gpt-6-astra", status="failed", error_code="server_is_overloaded"),
                     rec("resp_t2", "gpt-6-astra")]
        self.assertEqual(probe("gpt-6-astra", responses).verdict(), "ok")

    def test_rate_limits_and_metadata_headers(self):
        frames, _, _ = cmc.parse_trace_frames(load("astra_served_by_luna.log"))
        rl = cmc.collect_rate_limits(frames)
        self.assertEqual(rl["plan_type"], "pro")
        self.assertEqual(rl["rate_limits"]["primary"]["used_percent"], 8)
        headers = cmc.collect_metadata_headers(frames)
        self.assertNotIn("x-codex-turn-state", headers)
        self.assertEqual(headers.get("x-codex-safety-buffering-faster-model"), "gpt-5.6-luna")


class UnsupportedModel(unittest.TestCase):
    MSG = "The 'gpt-5.6-sol' model is not supported when using Codex with a ChatGPT account."

    def test_free_plan_refusal_is_unsupported_not_rerouted(self):
        # warm-up answered by the plan's default model, then the turn refused: what a Free account sees
        frames = [
            {"type": "codex.rate_limits", "plan_type": "free", "rate_limits": {"limit_reached": False, "primary": {"used_percent": 0, "window_minutes": 43200}}},
            {"type": "response.created", "response": {"id": "resp_w", "model": "gpt-5.6-luna", "status": "in_progress"}},
            {"type": "response.completed", "response": {"id": "resp_w", "model": "gpt-5.6-luna", "status": "completed"}},
            {"type": "error", "error": {"type": "invalid_request_error", "code": None, "message": self.MSG}},
            {"type": "error", "error": {"type": "invalid_request_error", "code": None, "message": self.MSG}},
        ]
        responses, errors = cmc.collect_responses(frames)
        p = probe("gpt-5.6-sol", responses, errors)
        p.rate_limits = cmc.collect_rate_limits(frames)
        self.assertTrue(p.unsupported())
        self.assertEqual(p.verdict(), "UNSUPPORTED")
        overall, code, lines = cmc.summarize([p])
        self.assertEqual((overall, code), ("UNSUPPORTED", 1))
        self.assertIn("cannot use gpt-5.6-sol (plan: free)", lines[0])
        self.assertNotIn("REROUTED", lines[0])

    def test_unsupported_control_gets_its_own_line(self):
        c = probe("gpt-5.6-sol", [], [("invalid_request_error", self.MSG)], is_control=True, index=2)
        m = probe("gpt-5.6-luna", [rec("resp_a", "gpt-5.6-luna")])
        overall, code, lines = cmc.summarize([m, c])
        self.assertEqual((overall, code), ("OK", 0))
        self.assertTrue(any("control: gpt-5.6-sol is not available on this account" in l for l in lines), lines)

    def test_matcher(self):
        self.assertTrue(cmc.is_unsupported_error("invalid_request_error", self.MSG))
        self.assertTrue(cmc.is_unsupported_error("model_not_found", None))
        self.assertFalse(cmc.is_unsupported_error("server_is_overloaded", "Our servers are currently overloaded."))

    def test_control_equal_to_model_is_skipped(self):
        import codex_routing_detector_gui as g
        assert g.install_fake_runner()
        try:
            res = cmc.run_check(cmc.CheckOptions(models=["gpt-6-astra"], control="GPT-6-ASTRA"))
        finally:
            pass
        self.assertEqual([p.is_control for p in res.probes], [False])


class Summary(unittest.TestCase):
    def test_rerouted_summary_names_only_the_rerouted_model_and_counts_responses(self):
        probes = [probe("gpt-5.5", [rec("resp_a", "gpt-5.5", kind="warmup"), rec("resp_b", "gpt-5.5")], index=1),
                  probe("gpt-6-astra", [rec("resp_c", "gpt-5.6-luna", kind="warmup"), rec("resp_d", "gpt-5.6-luna")], index=2),
                  probe("gpt-5.6-sol", [rec("resp_e", "gpt-5.6-sol")], is_control=True, index=3)]
        overall, code, lines = cmc.summarize(probes)
        self.assertEqual((overall, code), ("REROUTED", 2))
        self.assertIn("gpt-6-astra -> gpt-5.6-luna (2 of 2 responses)", lines[0])
        self.assertNotIn("gpt-5.5 ->", lines[0])
        self.assertTrue(any("served correctly: gpt-5.5" in l for l in lines))
        self.assertTrue(any(l.startswith("control: gpt-5.6-sol was served correctly, so") for l in lines))

    def test_ok_summary_does_not_claim_unchecked_models(self):
        probes = [probe("gpt-5.5", [rec("resp_a", "gpt-5.5")], index=1),
                  probe("gpt-6-astra", [], index=2)]
        overall, code, lines = cmc.summarize(probes)
        self.assertEqual((overall, code), ("ERROR", 1))
        self.assertIn("could not check gpt-6-astra", lines[0])
        self.assertIn("gpt-5.5 was served as requested", lines[0])

    def test_empty_probe_list_is_not_ok(self):
        overall, code, lines = cmc.summarize([])
        self.assertEqual((overall, code), ("ERROR", 1))
        self.assertNotIn("OK", lines[0])

    def test_all_ok(self):
        probes = [probe("gpt-6-astra", [rec("resp_a", "gpt-6-astra")]),
                  probe("gpt-5.6-sol", [rec("resp_b", "gpt-5.6-sol")], is_control=True, index=2)]
        overall, code, lines = cmc.summarize(probes)
        self.assertEqual((overall, code), ("OK", 0))
        self.assertEqual(lines[0], "VERDICT: OK - gpt-6-astra was served as requested.")

    def test_rerouted_control_alone_is_still_exit_2(self):
        probes = [probe("gpt-6-astra", [rec("resp_a", "gpt-6-astra")]),
                  probe("gpt-5.6-sol", [rec("resp_b", "gpt-5.6-luna")], is_control=True, index=2)]
        overall, code, lines = cmc.summarize(probes)
        self.assertEqual((overall, code), ("REROUTED", 2))
        self.assertIn("control model gpt-5.6-sol was served by a different model", lines[0])
        self.assertNotIn("also", lines[0])

    def test_warmup_only_reroute_counts(self):
        probes = [probe("gpt-6-astra", [rec("resp_w", "gpt-5.6-luna", kind="warmup")])]
        overall, code, lines = cmc.summarize(probes)
        self.assertEqual((overall, code), ("REROUTED", 2))
        self.assertIn("(1 of 1 responses)", lines[0])

    def test_rerouted_warmup_with_failed_or_ok_turn_is_still_rerouted(self):
        failed_turn = rec("resp_t", "gpt-6-astra", status="failed", error_code="server_is_overloaded")
        p = probe("gpt-6-astra", [rec("resp_w", "gpt-5.6-luna", kind="warmup"), failed_turn])
        self.assertEqual(p.verdict(), "REROUTED")
        p2 = probe("gpt-6-astra", [rec("resp_w", "gpt-5.6-luna", kind="warmup"), rec("resp_t", "gpt-6-astra")])
        self.assertEqual(p2.verdict(), "REROUTED")

    def test_turn_that_named_another_model_then_failed_is_rerouted(self):
        turn = rec("resp_t", "gpt-5.6-luna", status="failed", error_code="server_is_overloaded")
        self.assertEqual(turn.verdict("gpt-6-astra"), "REROUTED")
        p = probe("gpt-6-astra", [rec("resp_w", "gpt-6-astra", kind="warmup"), turn])
        self.assertEqual(p.verdict(), "REROUTED")

    def test_warmup_only_ok_is_unknown_not_ok(self):
        p = probe("gpt-6-astra", [rec("resp_w", "gpt-6-astra", kind="warmup")])
        self.assertEqual(p.verdict(), "UNKNOWN")
        overall, code, lines = cmc.summarize([p])
        self.assertEqual((overall, code), ("ERROR", 1))
        self.assertIn("could not check gpt-6-astra", lines[0])

    def test_client_without_previous_response_id_uses_the_last_response(self):
        p = probe("gpt-6-astra", [rec("resp_a", "gpt-6-astra", kind="warmup"), rec("resp_b", "gpt-6-astra", kind="warmup")])
        self.assertEqual(p.verdict(), "ok")

    def test_control_with_mixed_repeats_gets_one_line(self):
        probes = [probe("gpt-6-astra", [rec("resp_a", "gpt-5.6-luna")], index=1),
                  probe("gpt-5.6-sol", [rec("resp_b", "gpt-5.6-sol")], is_control=True, index=2),
                  probe("gpt-5.6-sol", [rec("resp_c", "gpt-5.6-luna")], is_control=True, index=3)]
        _, _, lines = cmc.summarize(probes)
        ctrl = [l for l in lines if l.startswith("control:")]
        self.assertEqual(len(ctrl), 1)
        self.assertIn("1 of 2 probes", ctrl[0])

    def test_ok_needs_the_turn(self):
        p = probe("gpt-6-astra", [rec("resp_w", "gpt-6-astra", kind="warmup"),
                                  rec("resp_t", "gpt-6-astra", status="failed", error_code="server_is_overloaded")])
        self.assertEqual(p.verdict(), "ERROR")
        p2 = probe("gpt-6-astra", [rec("resp_w", "gpt-6-astra", kind="warmup"), rec("resp_t", "gpt-6-astra")])
        self.assertEqual(p2.verdict(), "ok")

    def test_mid_response_change_reports_the_foreign_model(self):
        r = rec("resp_t", "gpt-6-astra")
        r.models_seen = ["gpt-5.6-luna", "gpt-6-astra"]
        _, _, lines = cmc.summarize([probe("gpt-6-astra", [r])])
        self.assertIn("gpt-6-astra -> gpt-5.6-luna", lines[0])

    def test_intermittent_reroute_across_repeats_is_flagged(self):
        probes = [probe("gpt-6-astra", [rec("resp_a", "gpt-5.6-luna")], index=1),
                  probe("gpt-6-astra", [rec("resp_b", "gpt-6-astra")], index=2)]
        overall, code, lines = cmc.summarize(probes)
        self.assertEqual((overall, code), ("REROUTED", 2))
        self.assertTrue(any("intermittent" in l for l in lines))

    def test_report_shows_the_error_of_a_rerouted_response_that_failed(self):
        p = probe("gpt-6-astra", [rec("resp_t", "gpt-5.6-luna", status="failed", error_code="server_is_overloaded",
                                      error_message="overloaded")])
        text, overall, code = cmc.render_report([p], "codex", "v", "trace", pathlib.Path("."), False, "from -m")
        self.assertEqual(overall, "REROUTED")
        self.assertIn("error server_is_overloaded: overloaded", text)

    def test_print_report_runs_and_wraps_long_errors(self):
        p = probe("gpt-5.6-sol", [rec("resp_" + "a" * 50, "gpt-5.6-sol", status="failed",
                                      error_code="server_is_overloaded", error_message="x " * 120)])
        buf = io.StringIO()
        with redirect_stdout(buf):
            overall, code = cmc.print_report([p], "codex", "codex-cli 0.0", "trace", pathlib.Path("."), False, "from -m")
        out = buf.getvalue()
        self.assertEqual((overall, code), ("ERROR", 1))
        self.assertTrue(all(len(l) <= 120 for l in out.splitlines()), max(out.splitlines(), key=len))
        self.assertIn("error server_is_overloaded", out)


class Formatting(unittest.TestCase):
    def test_fmt_time_accepts_int_str_and_garbage(self):
        self.assertEqual(cmc.fmt_time(0), "00:00:00Z")
        self.assertEqual(cmc.fmt_time("1790043482"), cmc.fmt_time(1790043482))
        self.assertEqual(cmc.fmt_time(None), "-")
        self.assertEqual(cmc.fmt_time("soon"), "soon")

    def test_short_id(self):
        self.assertEqual(cmc.short_id("resp_short"), "resp_short")
        self.assertEqual(cmc.short_id("resp_" + "0" * 50), "resp_000000000..000000")


class Sanitizing(unittest.TestCase):
    def test_secrets_are_removed(self):
        text = ('headers: {"set-cookie": "__oailb=abc; Path=/", "authorization": "Bearer eyJhbGciOiJFUzI1NiIsInR5cCI"} '
                'x "access_token":"tok" Bearer zzz.yyy.xxx.www.vvv.uuuu '
                '{"x-codex-turn-state":"gAAAAABq"} escaped: \\"set-cookie\\": \\"__cf_bm=1; Path=/\\"')
        out = cmc.redact(text)
        for leaked in ("__oailb=abc", "eyJhbGci", '"tok"', "zzz.yyy", "gAAAAABq", "__cf_bm=1"):
            self.assertNotIn(leaked, out, leaked)
        self.assertIn('"x-codex-turn-state":"<redacted>"', out)
        self.assertIn('\\"set-cookie\\": \\"<redacted>\\"', out)  # JSON escaping survives

    def test_redaction_leaves_prose_alone(self):
        self.assertEqual(cmc.redact("the bearer of this ring"), "the bearer of this ring")

    def test_sanitize_log_drops_outgoing_frames_and_home_dir(self):
        home = str(pathlib.Path.home())
        text = ("x TRACE tungstenite::protocol: Sending frame: Frame { payload: b\"\\xec\\xbd\" }\n"
                f"workdir: {home}{os.sep}tmp\n"
                'x TRACE tungstenite::protocol: Received message {"type":"codex.rate_limits"}\n')
        out = cmc.sanitize_log(text)
        self.assertNotIn("Sending frame", out)
        self.assertNotIn(home, out)
        self.assertIn("workdir: ~", out)
        self.assertIn('"codex.rate_limits"', out)

    def test_query_string_tokens_are_redacted(self):
        out = cmc.redact("GET /cb?access_token=abc123def&state=1 and token=xyz")
        self.assertNotIn("abc123def", out)
        self.assertNotIn("token=xyz", out)
        self.assertIn("state=1", out)

    def test_wire_recording_drops_request_bodies_and_double_escaped_home(self):
        home = str(pathlib.Path.home())
        c2s = json.dumps({"type": "response.create", "model": "gpt-6-astra", "service_tier": "priority",
                          "reasoning": {"effort": "low"}, "instructions": "SECRET SYSTEM PROMPT",
                          "input": [{"role": "user", "content": "<cwd>" + home + "</cwd>"}],
                          "tools": [{"name": "shell"}], "client_metadata": {"x": "y"}})
        s2c = json.dumps({"type": "response.created", "response": {"id": "resp_1", "model": "gpt-5.6-luna"}})
        text = json.dumps({"dir": "c2s", "text": c2s}) + "\n" + json.dumps({"dir": "s2c", "text": s2c}) + "\n"
        self.assertIn(home.replace("\\", "\\\\\\\\"), text) if "\\" in home else None
        out = cmc.sanitize_wire_jsonl(text)
        self.assertNotIn("SECRET SYSTEM PROMPT", out)
        self.assertNotIn("<cwd>", out)
        self.assertNotIn(home, out)
        self.assertNotIn(home.replace("\\", "\\\\\\\\"), out)
        recs = [json.loads(l) for l in out.splitlines()]
        self.assertEqual(json.loads(recs[0]["text"])["model"], "gpt-6-astra")
        self.assertEqual(json.loads(recs[0]["text"])["service_tier"], "priority")
        self.assertIn("reduced", recs[0])
        self.assertEqual(json.loads(recs[1]["text"])["response"]["model"], "gpt-5.6-luna")

    def test_fixtures_contain_no_secrets(self):
        for f in FIX.glob("*.log"):
            t = f.read_text(encoding="utf-8")
            for bad in ("Bearer ", "set-cookie", "authorization", "gAAAA"):
                self.assertNotIn(bad, t, f"{f.name} contains {bad}")
            self.assertEqual(cmc.redact(t), t, f"{f.name} changes under redact()")


class ConfigAndCommand(unittest.TestCase):
    def test_codex_command_uses_toml_strings(self):
        cmd = cmc.build_codex_cmd(["codex"], "gpt-5.5", "low", "priority", "hi", ephemeral=True)
        self.assertIn('model="gpt-5.5"', cmd)
        self.assertIn('service_tier="priority"', cmd)
        self.assertIn("--ephemeral", cmd)
        self.assertEqual(cmd[-1], "hi")

    def test_node_launcher_prefix_is_preserved(self):
        cmd = cmc.build_codex_cmd(["node", "codex.js"], "gpt-6-astra", "low", None, "hi", ephemeral=False)
        self.assertEqual(cmd[:3], ["node", "codex.js", "exec"])
        self.assertFalse(any(x.startswith("service_tier=") for x in cmd))
        self.assertNotIn("--ephemeral", cmd)

    def test_config_fallback_reads_only_top_level_keys(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            cfg = pathlib.Path(d) / "config.toml"
            cfg.write_text('profile = "fast"\nservice_tier = \'priority\'\n[profiles.fast]\nmodel = "gpt-5.5"\n', encoding="utf-8")
            old = os.environ.get("CODEX_HOME")
            os.environ["CODEX_HOME"] = d
            try:
                model, tier, source = cmc.read_config_values()
            finally:
                if old is None:
                    del os.environ["CODEX_HOME"]
                else:
                    os.environ["CODEX_HOME"] = old
        self.assertIsNone(model)
        self.assertEqual(tier, "priority")

    def test_toml_fallback_survives_multiline_arrays_and_finds_tables(self):
        text = 'x = [\n  [1, 2],\n]\nmodel = "gpt-6-astra"\n[profiles.fast]\nmodel = "gpt-5.5"\n'
        self.assertEqual(cmc.toml_top_level_strings(text, ("model",))["model"], "gpt-6-astra")
        text2 = "[profiles.fast]\nmodel = \"gpt-5.5\"\n"
        self.assertIsNone(cmc.toml_top_level_strings(text2, ("model",))["model"])
        no_comma = 'x = [\n  [1, 2]\n]\nmodel = "b"\n'
        self.assertEqual(cmc.toml_top_level_strings(no_comma, ("model",))["model"], "b")
        aot = '[[arr]]\nmodel = "c"\n'
        self.assertIsNone(cmc.toml_top_level_strings(aot, ("model",))["model"])
        bracket_in_string = 'note = "see [1"\n[profiles.fast]\nmodel = "c"\n'
        self.assertIsNone(cmc.toml_top_level_strings(bracket_in_string, ("model",))["model"])
        hash_in_string = 'note = "[ # ]"\n[profiles.fast]\nmodel = "c"\n'
        self.assertIsNone(cmc.toml_top_level_strings(hash_in_string, ("model",))["model"])
        escaped_quote = 'note = "say \\"[\\" now"\n[profiles.fast]\nmodel = "c"\n'
        self.assertIsNone(cmc.toml_top_level_strings(escaped_quote, ("model",))["model"])

    def test_control_three_way_mix_names_the_rest(self):
        probes = [probe("gpt-6-astra", [rec("resp_a", "gpt-5.6-luna")], index=1),
                  probe("gpt-5.6-sol", [rec("resp_b", "gpt-5.6-sol")], is_control=True, index=2),
                  probe("gpt-5.6-sol", [rec("resp_c", "gpt-5.6-luna")], is_control=True, index=3),
                  probe("gpt-5.6-sol", [rec("resp_d", "gpt-5.6-sol", status="failed", error_code="x")], is_control=True, index=4)]
        _, _, lines = cmc.summarize(probes)
        ctrl = [l for l in lines if l.startswith("control:")][0]
        self.assertIn("1 of 3 probes", ctrl)
        self.assertIn("the rest ended with ERROR", ctrl)

    def test_no_previous_response_id_uses_the_last_response(self):
        p = probe("gpt-6-astra", [rec("resp_a", "gpt-6-astra", kind="warmup"),
                                  rec("resp_b", "gpt-6-astra", kind="warmup", status="failed", error_code="server_is_overloaded")])
        self.assertEqual(p.verdict(), "ERROR")

    def test_ok_summary_notes_unchecked_repeats(self):
        probes = [probe("gpt-6-astra", [rec("resp_a", "gpt-6-astra")], index=1),
                  probe("gpt-6-astra", [rec("resp_b", "gpt-6-astra", kind="warmup")], index=2)]
        overall, code, lines = cmc.summarize(probes)
        self.assertEqual((overall, code), ("OK", 0))
        self.assertTrue(any("could not be checked" in l for l in lines), lines)

    def test_control_rerouted_and_errored_repeats_are_both_mentioned(self):
        probes = [probe("gpt-6-astra", [rec("resp_a", "gpt-6-astra")], index=1),
                  probe("gpt-5.6-sol", [rec("resp_b", "gpt-5.6-luna")], is_control=True, index=2),
                  probe("gpt-5.6-sol", [rec("resp_c", "gpt-5.6-sol", status="failed", error_code="x")], is_control=True, index=3)]
        _, _, lines = cmc.summarize(probes)
        ctrl = [l for l in lines if l.startswith("control:")]
        self.assertEqual(len(ctrl), 1)
        self.assertIn("1 of 2 probes", ctrl[0])
        self.assertIn("ERROR", ctrl[0])

    def test_display_path_collapses_home(self):
        home = pathlib.Path.home()
        self.assertEqual(cmc.display_path(home / "x" / "y"), "~" + os.sep + "x" + os.sep + "y")
        self.assertEqual(cmc.display_path("/somewhere/else"), "/somewhere/else")


class RunProbeNotes(unittest.TestCase):
    """run_probe() with run_capture() replaced: checks verdicts and note texts without launching codex."""

    def _run(self, stderr_lines, rc=0, timed_out=False):
        import tempfile
        text = "\n".join(stderr_lines) + "\n"
        original = cmc.run_capture
        cmc.run_capture = lambda cmd, timeout, env=None, cwd=None, on_start=None: (rc, b"pong\n", text.encode("utf-8"), timed_out)
        try:
            with tempfile.TemporaryDirectory() as d:
                p = cmc.Probe(index=1, requested="gpt-6-astra", effort="low", tier=None, is_control=False, method="trace")
                return cmc.run_probe(["codex"], p, "p", 10, False, pathlib.Path(d), None)
        finally:
            cmc.run_capture = original

    @staticmethod
    def _frame(obj):
        return "x TRACE tungstenite::protocol: Received message " + json.dumps(obj)

    def test_warmup_only_is_unknown_with_note(self):
        p = self._run([self._frame({"type": "response.created", "response": {"id": "resp_w", "model": "gpt-6-astra", "status": "in_progress"}}),
                       self._frame({"type": "response.completed", "response": {"id": "resp_w", "model": "gpt-6-astra", "status": "completed"}})],
                      timed_out=True)
        self.assertEqual(p.verdict(), "UNKNOWN")
        self.assertTrue(any("only the warm-up response was seen" in n for n in p.notes), p.notes)
        self.assertTrue(any("did not finish" in n for n in p.notes), p.notes)

    def test_turn_that_never_completed_is_unknown_with_note(self):
        p = self._run([self._frame({"type": "response.completed", "response": {"id": "resp_w", "model": "gpt-6-astra", "status": "completed"}}),
                       self._frame({"type": "response.created", "response": {"id": "resp_t", "model": "gpt-6-astra", "status": "in_progress",
                                                                             "previous_response_id": "resp_w"}})],
                      timed_out=True)
        self.assertEqual(p.verdict(), "UNKNOWN")
        self.assertTrue(any("never completed" in n for n in p.notes), p.notes)

    def test_response_without_model_gets_a_note(self):
        p = self._run([self._frame({"type": "response.completed", "response": {"id": "resp_w", "status": "completed"}}),
                       self._frame({"type": "response.completed", "response": {"id": "resp_t", "status": "completed",
                                                                               "previous_response_id": "resp_w"}})])
        self.assertEqual(p.verdict(), "UNKNOWN")
        self.assertTrue(any("carried no model field" in n for n in p.notes), p.notes)

    def test_pre_socket_failure_quotes_codex_and_hides_home(self):
        home = str(pathlib.Path.home())
        p = self._run(["OpenAI Codex v0.153.4", f"ERROR: refresh failed for {home}{os.sep}.codex{os.sep}auth.json Bearer eyJhbGciOiJFUzI1NiIsInR5cCI"], rc=1)
        self.assertEqual(p.verdict(), "NO_DATA")
        note = " ".join(p.notes)
        self.assertIn("exited with code 1", note)
        self.assertNotIn(home, note)
        self.assertNotIn("eyJhbGci", note)

    def test_failed_warmup_alone_gets_a_specific_note(self):
        p = self._run([self._frame({"type": "response.failed", "response": {"id": "resp_w", "model": "gpt-6-astra", "status": "failed",
                                                                            "error": {"code": "server_is_overloaded", "message": "x"}}})], rc=1)
        self.assertEqual(p.verdict(), "ERROR")
        self.assertTrue(any("warm-up request failed; no turn was started" in n for n in p.notes), p.notes)

    def test_incomplete_turn_is_unknown_with_status_note(self):
        p = self._run([self._frame({"type": "response.completed", "response": {"id": "resp_w", "model": "gpt-6-astra", "status": "completed"}}),
                       self._frame({"type": "response.incomplete", "response": {"id": "resp_t", "model": "gpt-6-astra", "status": "incomplete",
                                                                                "previous_response_id": "resp_w"}})])
        self.assertEqual(p.verdict(), "UNKNOWN")
        self.assertTrue(any("ended with status incomplete" in n for n in p.notes), p.notes)

    def test_cancel_without_a_kill_leaves_no_cancelled_note(self):
        cancel = cmc.Canceller()
        cancel.event.set()  # pressed after the process had already exited
        original = cmc.run_capture
        cmc.run_capture = lambda cmd, timeout, env=None, cwd=None, on_start=None: (0, b"pong\n", load("astra_served_by_luna.log").encode("utf-8"), False)
        try:
            import tempfile
            with tempfile.TemporaryDirectory() as d:
                p = cmc.Probe(index=1, requested="gpt-6-astra", effort="low", tier=None, is_control=False, method="trace")
                cmc.run_probe(["codex"], p, "p", 10, False, pathlib.Path(d), None, cancel)
        finally:
            cmc.run_capture = original
        self.assertNotIn("cancelled by the user", p.notes)
        self.assertEqual(p.verdict(), "REROUTED")

    def test_unreadable_config_does_not_raise(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            (pathlib.Path(d) / "config.toml").mkdir()  # a directory where the file should be
            old = os.environ.get("CODEX_HOME")
            os.environ["CODEX_HOME"] = d
            try:
                model, tier, source = cmc.read_config_values()
            finally:
                if old is None:
                    del os.environ["CODEX_HOME"]
                else:
                    os.environ["CODEX_HOME"] = old
        self.assertEqual((model, tier), (None, None))
        self.assertIn("unreadable", source)

    def test_cancelled_probe_gets_no_sign_in_diagnosis(self):
        cancel = cmc.Canceller()
        cancel.cancel()
        cancel.killed = True  # the running process was killed
        text = "OpenAI Codex v0.153.4\n"
        original = cmc.run_capture
        cmc.run_capture = lambda cmd, timeout, env=None, cwd=None, on_start=None: (1, b"", text.encode(), False)
        try:
            import tempfile
            with tempfile.TemporaryDirectory() as d:
                p = cmc.Probe(index=1, requested="gpt-6-astra", effort="low", tier=None, is_control=False, method="trace")
                cmc.run_probe(["codex"], p, "p", 10, False, pathlib.Path(d), None, cancel)
        finally:
            cmc.run_capture = original
        self.assertIn("cancelled by the user", p.notes)
        self.assertFalse(any("codex login" in n for n in p.notes), p.notes)

    def test_rerouted_warmup_with_failed_turn_notes_the_basis(self):
        p = self._run([self._frame({"type": "response.completed", "response": {"id": "resp_w", "model": "gpt-5.6-luna", "status": "completed"}}),
                       self._frame({"type": "response.failed", "response": {"id": "resp_t", "model": "gpt-6-astra", "status": "failed",
                                                                            "previous_response_id": "resp_w",
                                                                            "error": {"code": "server_is_overloaded", "message": "x"}}})],
                      rc=1)
        self.assertEqual(p.verdict(), "REROUTED")
        self.assertTrue(any("rests on the warm-up" in n for n in p.notes), p.notes)


class UpdateCheck(unittest.TestCase):
    def test_version_tuple(self):
        self.assertEqual(cmc.version_tuple("v1.2.10"), (1, 2, 10))
        self.assertEqual(cmc.version_tuple("garbage"), (0,))
        self.assertLess(cmc.version_tuple("v1.2.9"), cmc.version_tuple("v1.2.10"))

    def test_newer_release_is_reported_with_its_exe_asset(self):
        info = cmc.check_for_update(current="1.2.1", fetch=lambda: {"tag_name": "v1.3.0", "html_url": "https://x/rel"})
        self.assertEqual(info, {"version": "1.3.0", "url": "https://x/rel", "asset": None})
        data = {"tag_name": "v1.3.0", "html_url": "https://x/rel", "assets": [
            {"name": "other.zip", "browser_download_url": "https://x/o.zip"},
            {"name": "codex-routing-detector.exe", "browser_download_url": "https://x/c.exe", "size": 123, "digest": "sha256:ab"}]}
        info = cmc.check_for_update(current="1.2.1", fetch=lambda: data)
        self.assertEqual(info["asset"], {"url": "https://x/c.exe", "size": 123, "digest": "sha256:ab"})

    def test_verify_download_and_swap_script(self):
        import hashlib, tempfile
        d = pathlib.Path(tempfile.mkdtemp())
        f = d / "x.exe"
        f.write_bytes(b"MZ" + b"\0" * 1_500_000)
        self.assertIsNone(cmc.verify_download(f, f.stat().st_size, "sha256:" + hashlib.sha256(f.read_bytes()).hexdigest()))
        self.assertIn("size mismatch", cmc.verify_download(f, 5))
        self.assertIn("SHA-256", cmc.verify_download(f, None, "sha256:" + "0" * 64))
        (d / "small.exe").write_bytes(b"MZ")
        self.assertIn("too small", cmc.verify_download(d / "small.exe"))
        (d / "text.exe").write_bytes(b"#!" + b"\0" * 1_500_000)
        self.assertIn("not a Windows executable", cmc.verify_download(d / "text.exe"))
        script = cmc.self_update_script(pathlib.Path(r"C:\a b\app.exe"), pathlib.Path(r"C:\a b\app.new.exe"), 4321, ["--updated-from", "1.0"])
        self.assertNotIn("|", script)  # pipelines hang in a console-less cmd.exe
        self.assertNotIn("tasklist", script)
        self.assertIn("if %N% geq 60 goto fail", script)
        self.assertIn('move /y "C:\\a b\\app.new.exe" "C:\\a b\\app.exe"', script)
        self.assertIn("app.new.update.log", script)
        self.assertIn('start "" "C:\\a b\\app.exe" "--updated-from" "1.0"', script)
        self.assertIn('del "%~f0"', script)

    def test_helper_is_started_without_pyinstaller_child_markers(self):
        import tempfile
        os.environ["_PYI_PARENT_PROCESS_LEVEL"] = "1"
        os.environ["_MEIPASS2"] = r"C:\tmp\_MEI1"
        captured = {}

        class FakeProc:
            pid = 1
            returncode = None
            def poll(self):
                return None

        real_popen = cmc.subprocess.Popen
        cmc.subprocess.Popen = lambda *a, **kw: captured.update(kw) or FakeProc()
        try:
            d = pathlib.Path(tempfile.mkdtemp())
            cmc.launch_replacer(d / "app.exe", d / "app.new.exe", ["--updated-from", "1.0"])
        finally:
            cmc.subprocess.Popen = real_popen
            del os.environ["_PYI_PARENT_PROCESS_LEVEL"], os.environ["_MEIPASS2"]
        env = captured["env"]
        self.assertNotIn("_PYI_PARENT_PROCESS_LEVEL", env)
        self.assertNotIn("_MEIPASS2", env)
        self.assertIn("PATH", env)

    def test_same_or_older_release_is_ignored(self):
        self.assertIsNone(cmc.check_for_update(current="1.2.1", fetch=lambda: {"tag_name": "v1.2.1"}))
        self.assertIsNone(cmc.check_for_update(current="1.2.1", fetch=lambda: {"tag_name": "v1.0.0"}))

    def test_errors_and_opt_out_are_silent(self):
        def boom():
            raise OSError("offline")
        self.assertIsNone(cmc.check_for_update(current="1.2.1", fetch=boom))
        os.environ[cmc.NO_UPDATE_ENV] = "1"
        try:
            self.assertIsNone(cmc.check_for_update(current="0.0.1", fetch=lambda: {"tag_name": "v9.9.9"}))
        finally:
            del os.environ[cmc.NO_UPDATE_ENV]


class ProcessControl(unittest.TestCase):
    def test_timeout_kills_the_whole_tree(self):
        # parent python spawns a grandchild that keeps the pipe open; the timeout must still be enforced
        script = ("import subprocess,sys,time;"
                  "p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)']);"
                  "p.wait()")
        t0 = time.time()
        rc, out, err, timed_out = cmc.run_capture([sys.executable, "-c", script], timeout=2)
        self.assertTrue(timed_out)
        self.assertLess(time.time() - t0, 20)


if __name__ == "__main__":
    unittest.main()
