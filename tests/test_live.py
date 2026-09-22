"""Tests for the built-in proxy (codex_routing_proxy) and the live monitor (codex_routing_live).

The proxy is exercised end to end against a local TLS WebSocket echo server: a client goes
CONNECT -> TLS (trusting the proxy's throw-away CA) -> HTTP upgrade -> masked and
permessage-deflate frames, and the proxy must hand every message to its callback while the
bytes reach the server and the echoes come back unchanged. Tests that need the
`cryptography` package are skipped where it is missing.
"""
import base64
import hashlib
import json
import os
import pathlib
import queue
import socket
import ssl
import struct
import sys
import threading
import time
import unittest
import zlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import codex_routing_detector as cmc  # noqa: E402
import codex_routing_live as live  # noqa: E402
import codex_routing_proxy as crp  # noqa: E402

WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


# ------------------------------------------------------------------ helpers
def frame(payload: bytes, opcode: int = 1, fin: bool = True, rsv1: bool = False, mask: bool = False) -> bytes:
    b0 = (0x80 if fin else 0) | (0x40 if rsv1 else 0) | opcode
    n = len(payload)
    if n < 126:
        head = bytes([b0, (0x80 if mask else 0) | n])
    elif n < 65536:
        head = bytes([b0, (0x80 if mask else 0) | 126]) + struct.pack(">H", n)
    else:
        head = bytes([b0, (0x80 if mask else 0) | 127]) + struct.pack(">Q", n)
    if not mask:
        return head + payload
    key = os.urandom(4)
    return head + key + crp.unmask(payload, key)


def deflate_msg(comp: "zlib._Compress", data: bytes) -> bytes:
    out = comp.compress(data) + comp.flush(zlib.Z_SYNC_FLUSH)
    assert out.endswith(b"\x00\x00\xff\xff")
    return out[:-4]


def recv_head(sock: socket.socket) -> bytes:
    buf = b""
    while b"\r\n\r\n" not in buf:
        chunk = sock.recv(4096)
        if not chunk:
            raise ConnectionError("closed")
        buf += chunk
    return buf


class EchoServer(threading.Thread):
    """TLS server: answers a plain GET with a small body and speaks WebSocket (echo, with
    permessage-deflate and context takeover when the client offers it)."""

    def __init__(self, ctx: ssl.SSLContext) -> None:
        super().__init__(daemon=True)
        self.ctx = ctx
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(5)
        self.port = self.sock.getsockname()[1]
        self.seen: list = []

    def run(self) -> None:
        while True:
            try:
                raw, _ = self.sock.accept()
            except OSError:
                return
            threading.Thread(target=self._serve, args=(raw,), daemon=True).start()

    def _serve(self, raw: socket.socket) -> None:
        try:
            raw.settimeout(10)
            tls = self.ctx.wrap_socket(raw, server_side=True)
            head, rest = crp.read_head(tls)
            line, headers = crp.parse_head(head)
            if "websocket" not in headers.get("upgrade", "").lower():
                body = b'{"hello":"world"}'
                tls.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: "
                            + str(len(body)).encode() + b"\r\n\r\n" + body)
                head, rest = crp.read_head(tls)  # keep-alive: wait for the next request on this connection
                line, headers = crp.parse_head(head)
                if "websocket" not in headers.get("upgrade", "").lower():
                    tls.close()
                    return
            accept = base64.b64encode(hashlib.sha1((headers["sec-websocket-key"] + WS_GUID).encode()).digest()).decode()
            deflate = "permessage-deflate" in headers.get("sec-websocket-extensions", "")
            resp = ("HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                    f"Sec-WebSocket-Accept: {accept}\r\n")
            if deflate:
                resp += "Sec-WebSocket-Extensions: permessage-deflate\r\n"
            tls.sendall((resp + "\r\n").encode())
            parser = crp.WsParser(deflate=deflate)
            comp = zlib.compressobj(9, zlib.DEFLATED, -15)
            if rest:
                for _op, payload in parser.feed(rest):
                    self._echo(tls, payload, comp, deflate)
            while True:
                data = tls.recv(65536)
                if not data:
                    break
                for _op, payload in parser.feed(data):
                    self._echo(tls, payload, comp, deflate)
        except (OSError, crp.WsError, ConnectionError, KeyError):
            pass
        finally:
            for s in (locals().get("tls"), raw):
                try:
                    if s is not None:
                        s.close()
                except OSError:
                    pass

    def _echo(self, tls: ssl.SSLSocket, payload: bytes, comp, deflate: bool) -> None:
        self.seen.append(payload)
        if deflate:
            tls.sendall(frame(deflate_msg(comp, b"echo:" + payload), rsv1=True))
        else:
            tls.sendall(frame(b"echo:" + payload))

    def close(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass


# ------------------------------------------------------------------ parser
class WsParserTests(unittest.TestCase):
    def test_unmasked_and_masked_text(self):
        p = crp.WsParser()
        self.assertEqual(p.feed(frame(b"hi")), [(1, b"hi")])
        self.assertEqual(p.feed(frame(b"masked", mask=True)), [(1, b"masked")])

    def test_lengths_16_and_64_bit_and_split_delivery(self):
        p = crp.WsParser()
        big = b"x" * 70000
        data = frame(b"a" * 300, mask=True) + frame(big)
        out = []
        for i in range(0, len(data), 1000):  # arbitrary TCP segmentation
            out += p.feed(data[i:i + 1000])
        self.assertEqual(out, [(1, b"a" * 300), (1, big)])

    def test_fragments_and_control_frames_in_between(self):
        p = crp.WsParser()
        data = frame(b"ab", fin=False) + frame(b"", opcode=9) + frame(b"cd", opcode=0, fin=False) + frame(b"ef", opcode=0)
        self.assertEqual(p.feed(data), [(1, b"abcdef")])

    def test_permessage_deflate_with_context_takeover(self):
        comp = zlib.compressobj(9, zlib.DEFLATED, -15)
        m1 = deflate_msg(comp, b'{"type":"response.created","model":"gpt-6-astra"}')
        m2 = deflate_msg(comp, b'{"type":"response.completed","model":"gpt-6-astra"}')
        p = crp.WsParser(deflate=True)
        self.assertEqual(p.feed(frame(m1, rsv1=True)), [(1, b'{"type":"response.created","model":"gpt-6-astra"}')])
        self.assertEqual(p.feed(frame(m2, rsv1=True)), [(1, b'{"type":"response.completed","model":"gpt-6-astra"}')])
        # the second message relies on the shared window: a fresh parser cannot inflate it
        fresh = crp.WsParser(deflate=True)
        with self.assertRaises(crp.WsError):
            fresh.feed(frame(m2, rsv1=True))

    def test_no_context_takeover_resets_between_messages(self):
        c1, c2 = zlib.compressobj(9, zlib.DEFLATED, -15), zlib.compressobj(9, zlib.DEFLATED, -15)
        p = crp.WsParser(deflate=True, reset_context=True)
        self.assertEqual(p.feed(frame(deflate_msg(c1, b"one"), rsv1=True)), [(1, b"one")])
        self.assertEqual(p.feed(frame(deflate_msg(c2, b"two"), rsv1=True)), [(1, b"two")])

    def test_uncompressed_message_on_a_deflate_connection(self):
        p = crp.WsParser(deflate=True)
        self.assertEqual(p.feed(frame(b"plain")), [(1, b"plain")])

    def test_errors(self):
        with self.assertRaises(crp.WsError):
            crp.WsParser().feed(frame(b"x", opcode=0))  # continuation without a start
        with self.assertRaises(crp.WsError):
            crp.WsParser().feed(frame(b"x", rsv1=True))  # compressed without the extension
        with self.assertRaises(crp.WsError):
            crp.WsParser().feed(bytes([0x80 | 0x20, 1]) + b"x")  # RSV2 set

    def test_head_helpers(self):
        a, b = socket.socketpair()
        try:
            b.sendall(b"GET /x HTTP/1.1\r\nHost: h\r\nUpgrade: websocket\r\nX-Multi: 1\r\nX-Multi: 2\r\n\r\nBODY")
            head, rest = crp.read_head(a)
            line, headers = crp.parse_head(head)
            self.assertEqual(line, "GET /x HTTP/1.1")
            self.assertEqual(headers["upgrade"], "websocket")
            self.assertEqual(headers["x-multi"], "1, 2")
            self.assertEqual(rest, b"BODY")
        finally:
            a.close()
            b.close()
        self.assertEqual(crp.deflate_params("permessage-deflate; client_no_context_takeover"), (True, True, False))
        self.assertEqual(crp.deflate_params(""), (False, False, False))


# ------------------------------------------------------------------ proxy end to end
@unittest.skipUnless(crp.have_crypto(), "cryptography not installed")
class ProxyEndToEnd(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server_ca = crp.CertAuthority()
        cls.server = EchoServer(cls.server_ca.context_for("localhost"))
        cls.server.start()
        cls.proxy_ca = crp.CertAuthority()
        cls.messages: "queue.Queue[crp.WsMessage]" = queue.Queue()
        cls.events: list = []
        upstream = ssl.create_default_context(cafile=str(cls.server_ca.cert_path))
        cls.proxy = crp.InterceptProxy(cls.proxy_ca, on_message=cls.messages.put,
                                       on_event=lambda n, i: cls.events.append((n, i)), upstream_context=upstream)
        cls.proxy.start()

    @classmethod
    def tearDownClass(cls):
        cls.proxy.stop()
        cls.server.close()
        cls.proxy_ca.close()
        cls.server_ca.close()

    def _connect(self) -> ssl.SSLSocket:
        raw = socket.create_connection(("127.0.0.1", self.proxy.port), timeout=10)
        raw.sendall(f"CONNECT localhost:{self.server.port} HTTP/1.1\r\nHost: localhost\r\n\r\n".encode())
        self.assertTrue(recv_head(raw).startswith(b"HTTP/1.1 200"))
        ctx = ssl.create_default_context(cafile=str(self.proxy_ca.cert_path))
        tls = ctx.wrap_socket(raw, server_hostname="localhost")
        tls.settimeout(10)
        return tls

    def _drain(self, n: int, timeout: float = 10) -> list:
        out = []
        end = time.time() + timeout
        while len(out) < n and time.time() < end:
            try:
                out.append(self.messages.get(timeout=0.2))
            except queue.Empty:
                pass
        return out

    def test_certificates_are_per_host_and_cached(self):
        ctx1 = self.proxy_ca.context_for("chatgpt.com")
        self.assertIs(ctx1, self.proxy_ca.context_for("CHATGPT.com"))
        self.assertIsNot(ctx1, self.proxy_ca.context_for("127.0.0.1"))
        self.assertTrue((self.proxy_ca.dir / "chatgpt.com.pem").exists())
        self.assertIn(b"BEGIN CERTIFICATE", self.proxy_ca.cert_path.read_bytes())

    def test_websocket_messages_are_decoded_in_both_directions(self):
        tls = self._connect()
        tls.sendall(b"GET /backend-api/codex/responses HTTP/1.1\r\nHost: localhost\r\nUpgrade: websocket\r\n"
                    b"Connection: Upgrade\r\nSec-WebSocket-Version: 13\r\nSec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n"
                    b"x-codex-routing-hint: model=gpt-6-astra;tier=priority\r\n"
                    b"Sec-WebSocket-Extensions: permessage-deflate; client_max_window_bits\r\n\r\n")
        head = recv_head(tls)
        self.assertTrue(head.startswith(b"HTTP/1.1 101"))
        comp = zlib.compressobj(9, zlib.DEFLATED, -15)
        plain = json.dumps({"type": "response.create", "model": "gpt-6-astra"}).encode()
        tls.sendall(frame(plain, mask=True))
        second = json.dumps({"type": "response.create", "model": "gpt-6-astra", "n": 2}).encode()
        tls.sendall(frame(deflate_msg(comp, second), rsv1=True, mask=True))
        third = b"third-" + b"z" * 70000
        tls.sendall(frame(third[:100], fin=False, mask=True) + frame(third[100:], opcode=0, mask=True))
        client_parser = crp.WsParser(deflate=True)
        echoes = []
        while len(echoes) < 3:
            data = tls.recv(65536)
            self.assertTrue(data)
            echoes += [p for _op, p in client_parser.feed(data)]
        self.assertEqual(echoes, [b"echo:" + plain, b"echo:" + second, b"echo:" + third])
        tls.close()
        got = self._drain(6)
        # the two directions are decoded by two threads, so only the order within a direction is fixed
        self.assertEqual([m.text.encode() for m in got if m.direction == "c2s"], [plain, second, third])
        self.assertEqual([m.text.encode() for m in got if m.direction == "s2c"],
                         [b"echo:" + plain, b"echo:" + second, b"echo:" + third])
        self.assertEqual(len({m.conn for m in got}), 1)
        opened = [i for n, i in self.events if n == "ws_open"]
        self.assertTrue(opened and opened[-1]["watched"] and opened[-1]["deflate"])
        self.assertEqual(opened[-1]["routing_hint"], "model=gpt-6-astra;tier=priority")

    def test_other_paths_and_plain_requests_are_relayed_but_not_decoded(self):
        tls = self._connect()
        tls.sendall(b"GET /backend-api/codex/models HTTP/1.1\r\nHost: localhost\r\n\r\n")
        body = recv_head(tls).split(b"\r\n\r\n", 1)[1]
        while len(body) < 17:
            body += tls.recv(4096)
        self.assertEqual(body, b'{"hello":"world"}')
        tls.close()
        tls = self._connect()
        tls.sendall(b"GET /other/socket HTTP/1.1\r\nHost: localhost\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                    b"Sec-WebSocket-Version: 13\r\nSec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n\r\n")
        self.assertTrue(recv_head(tls).startswith(b"HTTP/1.1 101"))
        tls.sendall(frame(b"unwatched", mask=True))
        self.assertEqual(crp.WsParser().feed(tls.recv(4096)), [(1, b"echo:unwatched")])
        tls.close()
        self.assertEqual(self._drain(1, timeout=1), [])

    def test_non_connect_requests_are_refused(self):
        raw = socket.create_connection(("127.0.0.1", self.proxy.port), timeout=5)
        raw.sendall(b"GET http://example.com/ HTTP/1.1\r\nHost: example.com\r\n\r\n")
        self.assertTrue(recv_head(raw).startswith(b"HTTP/1.1 405"))
        raw.close()

    def test_unreachable_upstream_gives_502(self):
        raw = socket.create_connection(("127.0.0.1", self.proxy.port), timeout=5)
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            free = s.getsockname()[1]
        raw.sendall(f"CONNECT 127.0.0.1:{free} HTTP/1.1\r\n\r\n".encode())
        self.assertTrue(recv_head(raw).startswith(b"HTTP/1.1 502"))
        raw.close()

    def test_env_for_codex(self):
        add, drop = self.proxy.env()
        self.assertEqual(add["HTTPS_PROXY"], f"http://127.0.0.1:{self.proxy.port}")
        self.assertEqual(add["CODEX_CA_CERTIFICATE"], str(self.proxy_ca.cert_path))
        self.assertNotIn("SSL_CERT_FILE", add)  # would break every other TLS client in that console
        self.assertNotIn("HTTP_PROXY", add)  # plain http is not relayed
        for k in ("NO_PROXY", "HTTP_PROXY", "ALL_PROXY"):
            self.assertIn(k, drop)

    def test_upgrade_after_a_plain_request_on_the_same_tunnel_is_decoded(self):
        tls = self._connect()
        tls.sendall(b"GET /backend-api/codex/models HTTP/1.1\r\nHost: localhost\r\n\r\n")
        head = recv_head(tls)
        self.assertTrue(head.startswith(b"HTTP/1.1 200"))
        body = head.split(b"\r\n\r\n", 1)[1]
        while len(body) < 17:
            body += tls.recv(4096)
        self.assertEqual(body, b'{"hello":"world"}')
        tls.sendall(b"GET /backend-api/codex/responses HTTP/1.1\r\nHost: localhost\r\nUpgrade: websocket\r\n"
                    b"Connection: Upgrade\r\nSec-WebSocket-Version: 13\r\nSec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n\r\n")
        self.assertTrue(recv_head(tls).startswith(b"HTTP/1.1 101"))
        tls.sendall(frame(b'{"type":"response.create","model":"gpt-6-astra"}', mask=True))
        self.assertEqual(crp.WsParser().feed(tls.recv(4096)), [(1, b'echo:{"type":"response.create","model":"gpt-6-astra"}')])
        tls.close()
        got = self._drain(2)
        self.assertEqual(sorted(m.direction for m in got), ["c2s", "s2c"])


# ------------------------------------------------------------------ aggregation
def msg(direction: str, obj: dict, conn: int = 1, ts: float = 1000.0) -> crp.WsMessage:
    return crp.WsMessage(direction, json.dumps(obj), ts, conn)


class AggregatorTests(unittest.TestCase):
    def test_rerouted_turn_and_status_updates(self):
        agg = live.LiveAggregator()
        self.assertEqual(agg.feed(msg("c2s", {"type": "response.create", "model": "gpt-6-astra",
                                             "input": [{"role": "user", "content": "hi"}]})), [])
        ev = agg.feed(msg("s2c", {"type": "response.created", "response": {"id": "resp_1", "model": "gpt-5.6-luna",
                                                                          "status": "in_progress"}}))
        self.assertEqual(ev[0][0], "row")
        row = ev[0][1]["row"]
        self.assertTrue(ev[0][1]["new"])
        self.assertEqual((row.requested, row.served, row.kind, row.verdict()), ("gpt-6-astra", "gpt-5.6-luna", "turn", "REROUTED"))
        ev = agg.feed(msg("s2c", {"type": "response.completed", "response": {"id": "resp_1", "model": "gpt-5.6-luna",
                                                                            "status": "completed"}}))
        self.assertFalse(ev[0][1]["new"])
        self.assertIs(ev[0][1]["row"], row)
        self.assertEqual(row.status, "completed")
        self.assertEqual(agg.overall(), "REROUTED")
        self.assertEqual(agg.pairs(), ["gpt-6-astra -> gpt-5.6-luna"])
        self.assertIn("REROUTED: gpt-6-astra -> gpt-5.6-luna", agg.report())

    def test_ok_turn_warmup_and_rate_limits(self):
        agg = live.LiveAggregator()
        agg.feed(msg("c2s", {"type": "response.create", "model": "gpt-6-astra", "input": [{"role": "developer"}]}))
        ev = agg.feed(msg("s2c", {"type": "codex.rate_limits", "plan_type": "pro",
                                  "rate_limits": {"primary": {"used_percent": 8}, "limit_reached": False}}))
        self.assertEqual(ev[0][0], "rate_limits")
        agg.feed(msg("s2c", {"type": "response.created", "response": {"id": "w", "model": "gpt-6-astra", "status": "in_progress"}}))
        agg.feed(msg("s2c", {"type": "response.completed", "response": {"id": "w", "model": "gpt-6-astra", "status": "completed"}}))
        agg.feed(msg("c2s", {"type": "response.create", "model": "gpt-6-astra", "input": [{"role": "user"}]}))
        agg.feed(msg("s2c", {"type": "response.created", "response": {"id": "t", "model": "gpt-6-astra", "status": "in_progress"}}))
        self.assertEqual([r.kind for r in agg.rows], ["warmup", "turn"])
        self.assertEqual(agg.rows[1].verdict(), "UNKNOWN")  # not completed yet
        agg.feed(msg("s2c", {"type": "response.completed", "response": {"id": "t", "model": "gpt-6-astra", "status": "completed"}}))
        self.assertEqual(agg.rows[1].verdict(), "ok")
        self.assertEqual(agg.overall(), "OK")
        self.assertEqual(agg.account_line(), "plan=pro used=8% limit_reached=False")

    def test_dated_snapshot_counts_as_ok(self):
        agg = live.LiveAggregator()
        agg.feed(msg("c2s", {"type": "response.create", "model": "gpt-6-astra"}))
        agg.feed(msg("s2c", {"type": "response.completed", "response": {"id": "t", "model": "gpt-6-astra-2026-09-01",
                                                                       "status": "completed", "previous_response_id": "x"}}))
        self.assertEqual(agg.rows[0].verdict(), "ok")

    def test_stream_error_and_unsupported_rows(self):
        agg = live.LiveAggregator()
        agg.feed(msg("c2s", {"type": "response.create", "model": "gpt-5.6-sol"}))
        ev = agg.feed(msg("s2c", {"type": "error", "error": {"code": "invalid_request_error",
                                                             "message": "The 'gpt-5.6-sol' model is not supported when using Codex with a ChatGPT account."}}))
        self.assertEqual(ev[0][1]["row"].verdict(), "UNSUPPORTED")
        self.assertEqual(agg.overall(), "UNSUPPORTED")
        agg2 = live.LiveAggregator()
        agg2.feed(msg("c2s", {"type": "response.create", "model": "gpt-6-astra"}))
        agg2.feed(msg("s2c", {"type": "error", "error": {"code": "server_is_overloaded", "message": "busy"}}))
        self.assertEqual(agg2.rows[0].verdict(), "ERROR")
        self.assertEqual(agg2.overall(), "ERROR")

    def test_routing_hint_is_used_when_the_request_frame_was_missed(self):
        agg = live.LiveAggregator()
        agg.note_hint(3, "model=gpt-6-astra;tier=priority")
        agg.feed(msg("s2c", {"type": "response.completed", "response": {"id": "t", "model": "gpt-5.6-luna",
                                                                       "status": "completed", "previous_response_id": "p"}}, conn=3))
        self.assertEqual((agg.rows[0].requested, agg.rows[0].verdict()), ("gpt-6-astra", "REROUTED"))
        agg.feed(msg("s2c", {"type": "response.completed", "response": {"id": "u", "model": "gpt-5.6-luna",
                                                                       "status": "completed"}}, conn=9))
        self.assertEqual(agg.rows[1].verdict(), "UNKNOWN")  # nobody knows what was asked for

    def test_connections_are_kept_apart(self):
        agg = live.LiveAggregator()
        agg.feed(msg("c2s", {"type": "response.create", "model": "gpt-6-astra"}, conn=1))
        agg.feed(msg("c2s", {"type": "response.create", "model": "gpt-5.6-sol"}, conn=2))
        agg.feed(msg("s2c", {"type": "response.completed", "response": {"id": "a", "model": "gpt-5.6-luna", "status": "completed"}}, conn=1))
        agg.feed(msg("s2c", {"type": "response.completed", "response": {"id": "b", "model": "gpt-5.6-sol", "status": "completed"}}, conn=2))
        self.assertEqual([(r.requested, r.verdict()) for r in agg.rows], [("gpt-6-astra", "REROUTED"), ("gpt-5.6-sol", "ok")])

    def test_failed_turn_after_good_warmup_is_not_ok(self):
        agg = live.LiveAggregator()
        agg.feed(msg("c2s", {"type": "response.create", "model": "gpt-6-astra"}))
        agg.feed(msg("s2c", {"type": "response.completed", "response": {"id": "w", "model": "gpt-6-astra", "status": "completed"}}))
        self.assertEqual(agg.overall(), "OK")  # only a good warm-up so far
        agg.feed(msg("c2s", {"type": "response.create", "model": "gpt-6-astra", "input": [{"role": "user"}]}))
        agg.feed(msg("s2c", {"type": "response.failed", "response": {"id": "t", "model": "gpt-6-astra", "status": "failed",
                                                                    "error": {"code": "server_error", "message": "x"}}}))
        self.assertEqual([r.verdict() for r in agg.rows], ["ok", "ERROR"])
        self.assertEqual(agg.overall(), "ERROR")

    def test_request_frame_decoded_after_the_response_still_sets_requested(self):
        agg = live.LiveAggregator()
        agg.feed(msg("s2c", {"type": "response.created", "response": {"id": "t", "model": "gpt-5.6-luna", "status": "in_progress"}}))
        self.assertEqual(agg.rows[0].verdict(), "UNKNOWN")
        agg.feed(msg("c2s", {"type": "response.create", "model": "gpt-6-astra"}))
        agg.feed(msg("s2c", {"type": "response.completed", "response": {"id": "t", "model": "gpt-5.6-luna", "status": "completed"}}))
        self.assertEqual((agg.rows[0].requested, agg.rows[0].verdict()), ("gpt-6-astra", "REROUTED"))

    def test_user_input_flag_is_consumed_by_one_response(self):
        agg = live.LiveAggregator()
        agg.feed(msg("c2s", {"type": "response.create", "model": "gpt-6-astra", "input": [{"role": "user"}]}))
        agg.feed(msg("s2c", {"type": "response.completed", "response": {"id": "a", "model": "gpt-6-astra", "status": "completed"}}))
        agg.feed(msg("s2c", {"type": "response.completed", "response": {"id": "b", "model": "gpt-6-astra", "status": "completed"}}))
        self.assertEqual([r.kind for r in agg.rows], ["turn", "warmup"])

    def test_garbage_is_counted_not_raised(self):
        agg = live.LiveAggregator()
        self.assertEqual(agg.feed(crp.WsMessage("s2c", "not json", 1.0, 1)), [])
        self.assertEqual(agg.feed(crp.WsMessage("s2c", "[1,2]", 1.0, 1)), [])
        self.assertEqual(agg.unparsed, 2)
        self.assertEqual(agg.overall(), "NO_DATA")


# ------------------------------------------------------------------ session control
class FakeProc:
    def __init__(self) -> None:
        self.pid = 4242
        self._done = threading.Event()
        self.rc: int = 0
        self.killed = False

    def poll(self):
        return self.rc if self._done.is_set() else None

    def wait(self):
        self._done.wait()
        return self.rc

    def finish(self, rc: int = 0) -> None:
        self.rc = rc
        self._done.set()


@unittest.skipUnless(crp.have_crypto(), "cryptography not installed")
class MonitorTests(unittest.TestCase):
    def test_start_stop_and_codex_exit(self):
        launched = {}
        proc = FakeProc()

        def launcher(cmd, env, cwd):
            launched.update(cmd=cmd, env=env, cwd=cwd)
            return proc

        mon = live.LiveMonitor(["codex-fake"], "C:/work", codex_args=["--foo"], launcher=launcher)
        orig_kill = cmc.kill_tree
        cmc.kill_tree = lambda p: setattr(p, "killed", True)
        try:
            mon.start()
            self.assertEqual(launched["cmd"], ["codex-fake", "--foo"])
            self.assertEqual(launched["cwd"], "C:/work")
            self.assertEqual(launched["env"]["HTTPS_PROXY"], f"http://127.0.0.1:{mon.proxy.port}")
            self.assertNotIn("NO_PROXY", launched["env"])
            self.assertTrue(pathlib.Path(launched["env"]["CODEX_CA_CERTIFICATE"]).exists())
            self.assertIn("HTTPS_PROXY", mon.command_hint)
            self.assertTrue(mon.codex_running())
            notices = [mon.events.get(timeout=2)[1] for _ in range(2)]
            self.assertIn("proxy listening", notices[0])
            self.assertIn("pid 4242", notices[1])
            ca_dir = mon.ca.dir
            proc.finish(3)
            ev = mon.events.get(timeout=2)
            self.assertEqual(ev, ("codex_exit", 3))
            mon.stop()
            self.assertFalse(ca_dir.exists())
            self.assertFalse(proc.killed)  # already gone: nothing to kill
        finally:
            cmc.kill_tree = orig_kill

    def test_stop_kills_a_running_codex_and_launch_failure_cleans_up(self):
        proc = FakeProc()
        mon = live.LiveMonitor(["codex-fake"], ".", launcher=lambda c, e, w: proc)
        orig_kill = cmc.kill_tree
        cmc.kill_tree = lambda p: setattr(p, "killed", True)
        try:
            mon.start()
            mon.stop()
            self.assertTrue(proc.killed)
            self.assertIsNone(mon.proxy)
            mon2 = live.LiveMonitor(["codex-fake"], ".", launcher=lambda c, e, w: (_ for _ in ()).throw(OSError("nope")))
            with self.assertRaises(RuntimeError):
                mon2.start()
            self.assertIsNone(mon2.proxy)
        finally:
            cmc.kill_tree = orig_kill


class HelperTests(unittest.TestCase):
    def test_shell_hint_mentions_every_variable(self):
        hint = live.shell_hint({"HTTPS_PROXY": "http://127.0.0.1:1", "CODEX_CA_CERTIFICATE": "C:/x y/ca.pem"},
                               ["NO_PROXY"], ["C:/bin/codex.exe"])
        for needle in ("HTTPS_PROXY", "CODEX_CA_CERTIFICATE", "NO_PROXY", "codex.exe"):
            self.assertIn(needle, hint)

    def test_config_model_and_effort(self):
        import tempfile
        d = pathlib.Path(tempfile.mkdtemp())
        (d / "config.toml").write_text('model = "gpt-6-astra"\nmodel_reasoning_effort = "high"\n[x]\nmodel = "no"\n', encoding="utf-8")
        old = os.environ.get("CODEX_HOME")
        os.environ["CODEX_HOME"] = str(d)
        try:
            m, e, src = live.read_config_model_effort()
            self.assertEqual((m, e), ("gpt-6-astra", "high"))
            self.assertTrue(src.startswith("config.toml"))
            self.assertIsNotNone(live.config_mtime())
        finally:
            if old is None:
                del os.environ["CODEX_HOME"]
            else:
                os.environ["CODEX_HOME"] = old


if __name__ == "__main__":
    unittest.main()
