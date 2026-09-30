"""The generation budget actually stops at its ceiling.

Reliable-assistant plan §10, "Before the first generation":

  * "Use one persistent task ledger and atomic reservation before forwarding."
  * "Prove limit enforcement and restart persistence with a fake upstream."
  * "Stop at the cap. Do not exceed it because a journey is in flight."

This runs the real `gateway.py` in a subprocess against a **fake** upstream on
localhost, so it consumes zero model requests while proving the thing the whole
live-validation allocation depends on. A budget enforced by convention is not a
budget; the 2026-09-27 convention run found the opposite failure the same way
(its first live run consumed zero reservations while appearing to work, because
a hardcoded base_url bypassed the gateway entirely — "check the ledger, don't
trust the stack topology").
"""
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

import pytest

GATEWAY = Path(__file__).resolve().parents[1] / "tests" / "assistant_acceptance" / "gateway" / "gateway.py"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class FakeUpstream(BaseHTTPRequestHandler):
    """Counts what actually reached it. Nothing here is a model."""

    served = 0

    def log_message(self, *a):
        pass

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0) or 0)
        self.rfile.read(length)
        FakeUpstream.served += 1
        body = json.dumps({"choices": [{"message": {"content": "fake"}}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        body = b'{"data": []}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture
def fake_upstream():
    FakeUpstream.served = 0
    port = free_port()
    server = ThreadingHTTPServer(("127.0.0.1", port), FakeUpstream)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield port
    finally:
        server.shutdown()
        server.server_close()


class GatewayProcess:
    def __init__(self, ledger_path: Path, upstream_port: int, ceiling: int):
        self.port = free_port()
        self.ledger_path = ledger_path
        env = dict(os.environ)
        env.update({
            "UPSTREAM_HOST": "127.0.0.1",
            "UPSTREAM_PORT": str(upstream_port),
            "LISTEN_PORT": str(self.port),
            "BUDGET_CEILING": str(ceiling),
            "LEDGER_PATH": str(ledger_path),
            "REQUEST_TIMEOUT_S": "10",
        })
        self.proc = subprocess.Popen(
            [sys.executable, str(GATEWAY)], env=env,
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
        )
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            try:
                with socket.create_connection(("127.0.0.1", self.port), timeout=0.5):
                    return
            except OSError:
                if self.proc.poll() is not None:
                    raise RuntimeError(
                        f"gateway exited: {self.proc.stderr.read().decode()[:500]}")
                time.sleep(0.1)
        raise RuntimeError("gateway did not start")

    def post(self):
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/v1/chat/completions",
            data=b'{"messages": []}',
            headers={"Content-Type": "application/json", "X-Study-Context": "budget-test"},
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status
        except urllib.error.HTTPError as exc:
            return exc.code

    def get(self, path="/v1/models"):
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{self.port}{path}", timeout=10
            ) as resp:
                return resp.status
        except urllib.error.HTTPError as exc:
            return exc.code

    def stop(self):
        self.proc.terminate()
        try:
            self.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.proc.kill()


def ledger_events(path: Path):
    if not path.exists():
        return []
    out = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return out


def reserved(path: Path) -> int:
    return sum(1 for e in ledger_events(path) if e.get("event") == "reserved")


@pytest.fixture
def ledger(tmp_path):
    return tmp_path / "ledger" / "budget.jsonl"


class TestTheCeilingHolds:
    def test_it_forwards_exactly_the_ceiling_and_then_refuses(self, fake_upstream, ledger):
        gw = GatewayProcess(ledger, fake_upstream, ceiling=3)
        try:
            assert [gw.post() for _ in range(3)] == [200, 200, 200]
            assert gw.post() == 429, "the 4th request must be refused, not forwarded"
            assert gw.post() == 429
        finally:
            gw.stop()
        assert FakeUpstream.served == 3, (
            f"the upstream saw {FakeUpstream.served} requests against a ceiling of 3"
        )
        assert reserved(ledger) == 3

    def test_reservation_happens_before_forwarding(self, fake_upstream, ledger):
        """The order matters: a reservation written only on success lets a
        timing out or discarded attempt cost nothing, and the plan counts
        "retries, follow-up rounds, background inference, and failed attempts
        sent upstream"."""
        gw = GatewayProcess(ledger, fake_upstream, ceiling=2)
        try:
            gw.post()
            events = ledger_events(ledger)
        finally:
            gw.stop()
        # The OUTCOME may be `completed` or `failed` — on a loaded host the
        # forwarded call can time out, and that attempt still counted, which is
        # the whole point ("every attempt counts, including ones that later time
        # out"). What this pins is the ORDER: the reservation is written first.
        # Asserting `["reserved", "completed"]` made this a load-sensitive flake
        # (seen once in a full-suite run, passing in isolation).
        kinds = [e["event"] for e in events
                 if e["event"] in ("reserved", "completed", "failed")]
        assert kinds, "no reservation was recorded at all"
        assert kinds[0] == "reserved"
        assert kinds[1] in ("completed", "failed")

    def test_a_refusal_is_recorded_too(self, fake_upstream, ledger):
        gw = GatewayProcess(ledger, fake_upstream, ceiling=1)
        try:
            gw.post()
            gw.post()
        finally:
            gw.stop()
        events = [e["event"] for e in ledger_events(ledger)]
        assert "rejected_budget_exhausted" in events

    def test_metadata_requests_do_not_consume_budget(self, fake_upstream, ledger):
        gw = GatewayProcess(ledger, fake_upstream, ceiling=1)
        try:
            assert gw.get("/v1/models") == 200
            assert gw.get("/health") == 200
            assert reserved(ledger) == 0
            assert gw.post() == 200
            assert reserved(ledger) == 1
        finally:
            gw.stop()


class TestRestartPersistence:
    def test_a_restarted_gateway_does_not_hand_out_a_fresh_budget(self, fake_upstream, ledger):
        """"Do not create a fresh budget for each candidate" — nor for each
        restart. The ledger is the authority, not process memory."""
        first = GatewayProcess(ledger, fake_upstream, ceiling=2)
        try:
            assert first.post() == 200
            assert first.post() == 200
            assert first.post() == 429
        finally:
            first.stop()
        assert reserved(ledger) == 2

        second = GatewayProcess(ledger, fake_upstream, ceiling=2)
        try:
            assert second.post() == 429, "a restart must not reset the ceiling"
        finally:
            second.stop()
        assert FakeUpstream.served == 2
        assert reserved(ledger) == 2

    def test_the_restart_records_the_count_it_resumed_from(self, fake_upstream, ledger):
        first = GatewayProcess(ledger, fake_upstream, ceiling=5)
        try:
            first.post()
            first.post()
        finally:
            first.stop()
        second = GatewayProcess(ledger, fake_upstream, ceiling=5)
        try:
            starts = [e for e in ledger_events(ledger) if e["event"] == "gateway_start"]
            assert starts[-1]["reserved_count_at_start"] == 2
        finally:
            second.stop()


class TestNoBypass:
    def test_only_the_allowlisted_paths_are_proxied(self, fake_upstream, ledger):
        gw = GatewayProcess(ledger, fake_upstream, ceiling=5)
        try:
            for path in ("/v1/completions", "/v1/embeddings", "/", "/admin"):
                req = urllib.request.Request(
                    f"http://127.0.0.1:{gw.port}{path}", data=b"{}",
                    headers={"Content-Type": "application/json"},
                )
                try:
                    with urllib.request.urlopen(req, timeout=10) as resp:
                        code = resp.status
                except urllib.error.HTTPError as exc:
                    code = exc.code
                assert code == 403, f"{path} was not refused"
        finally:
            gw.stop()
        assert FakeUpstream.served == 0
        assert reserved(ledger) == 0

    def test_a_host_header_cannot_redirect_it(self, fake_upstream, ledger):
        """The destination comes from the gateway's own env, never from the
        client's Host header."""
        gw = GatewayProcess(ledger, fake_upstream, ceiling=5)
        try:
            req = urllib.request.Request(
                f"http://127.0.0.1:{gw.port}/v1/chat/completions",
                data=b'{"messages": []}',
                headers={"Content-Type": "application/json",
                         "Host": "somewhere-else.invalid:9999"},
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                assert resp.status == 200
        finally:
            gw.stop()
        assert FakeUpstream.served == 1, "the request went to the configured upstream"
