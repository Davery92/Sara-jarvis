"""Constrained model gateway for the Sara full-assistant acceptance study.

Sole egress path from the disposable, network-isolated study stack to the
real, shared chat-lane model endpoint. Enforces, for real (not merely by
convention):

  - a fixed upstream host:port — the caller cannot redirect it anywhere else
  - a fixed, short allowlist of paths (only what /chat/stream actually needs)
  - atomic budget reservation *before* every outbound attempt, against an
    append-only ledger file, with no auto-renewal
  - single generation concurrency across every caller (foreground and any
    background path), via a process-wide lock held for the request duration

This process has two network presences: the internal study network (where
the api/worker containers reach it) and a second, non-internal network that
actually routes to the upstream host. It is the only component in the study
topology attached to both.

Deliberately stdlib-only: no extra image layer/deps to keep the image build
fast and the trusted-code surface small.
"""
from __future__ import annotations

import fcntl
import http.client
import json
import os
import threading
import time
import urllib.parse
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

UPSTREAM_HOST = os.environ["UPSTREAM_HOST"]  # e.g. "100.104.68.115"
UPSTREAM_PORT = int(os.environ.get("UPSTREAM_PORT", "8082"))
LISTEN_PORT = int(os.environ.get("LISTEN_PORT", "8082"))
BUDGET_CEILING = int(os.environ.get("BUDGET_CEILING", "1600"))
LEDGER_PATH = os.environ.get("LEDGER_PATH", "/ledger/gateway_ledger.jsonl")
REQUEST_TIMEOUT_S = int(os.environ.get("REQUEST_TIMEOUT_S", "180"))

# Only what the OpenAI-compatible chat path actually needs. Anything else —
# including any attempt to reach a different host via a Host header trick,
# since we never read the client's Host header to choose a destination —
# is refused.
ALLOWED = {
    ("GET", "/v1/models"),       # identity/metadata only, not ledgered
    ("GET", "/health"),          # server capability probe (app.services.mtp_control);
                                  # metadata only, not ledgered — matches /v1/models treatment
    ("POST", "/v1/chat/completions"),  # the only ledgered, budget-consuming path
}

_gen_lock = threading.Lock()      # single generation concurrency, process-wide
_ledger_lock = threading.Lock()   # in-process serialization; fcntl for cross-process


def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _ledger_append(record: dict) -> None:
    line = json.dumps(record, sort_keys=True) + "\n"
    os.makedirs(os.path.dirname(LEDGER_PATH), exist_ok=True)
    with _ledger_lock:
        with open(LEDGER_PATH, "a") as fh:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
            try:
                fh.write(line)
                fh.flush()
                os.fsync(fh.fileno())
            finally:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


def _reserved_count() -> int:
    """Count of 'reserved' attempts already recorded. Every attempt counts,
    including ones that later time out or get discarded — reservation
    happens before the outbound call, and nothing here ever removes a
    reservation, matching the plan's no-auto-renewal requirement."""
    if not os.path.exists(LEDGER_PATH):
        return 0
    n = 0
    with open(LEDGER_PATH, "r") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_SH)
        try:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if rec.get("event") == "reserved":
                    n += 1
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
    return n


def _reserve_or_reject(context_header: str | None) -> tuple[bool, str, int]:
    """Atomic check-and-reserve using a single exclusive lock over the
    read-count-then-append sequence — not check-then-create against two
    separate operations."""
    attempt_id = uuid.uuid4().hex
    os.makedirs(os.path.dirname(LEDGER_PATH), exist_ok=True)
    # A dedicated lock file guards the whole reserve decision atomically,
    # since counting + appending must be one critical section.
    lock_path = LEDGER_PATH + ".lock"
    with open(lock_path, "a+") as lockfh:
        fcntl.flock(lockfh.fileno(), fcntl.LOCK_EX)
        try:
            current = _reserved_count()
            if current >= BUDGET_CEILING:
                _ledger_append({
                    "event": "rejected_budget_exhausted",
                    "attempt_id": attempt_id,
                    "ts": _utcnow(),
                    "reserved_count_at_rejection": current,
                    "ceiling": BUDGET_CEILING,
                    "context": context_header,
                })
                return False, attempt_id, current
            _ledger_append({
                "event": "reserved",
                "attempt_id": attempt_id,
                "ts": _utcnow(),
                "ordinal": current + 1,
                "ceiling": BUDGET_CEILING,
                "context": context_header,
            })
            return True, attempt_id, current + 1
        finally:
            fcntl.flock(lockfh.fileno(), fcntl.LOCK_UN)


class GatewayHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # noqa: A003 - stdlib signature
        # Route through the ledger instead of stderr spam; keep stdlib
        # default off so container logs stay readable.
        pass

    def _refuse(self, code: int, reason: str) -> None:
        body = json.dumps({"error": reason}).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        _ledger_append({
            "event": "refused",
            "ts": _utcnow(),
            "method": self.command,
            "path": self.path,
            "code": code,
            "reason": reason,
        })

    def _proxy(self, method: str, ledgered: bool) -> None:
        parsed = urllib.parse.urlsplit(self.path)
        key = (method, parsed.path)
        if key not in ALLOWED:
            self._refuse(403, f"path not allowlisted: {method} {parsed.path}")
            return

        length = int(self.headers.get("Content-Length", 0) or 0)
        body = self.rfile.read(length) if length else b""
        context_header = self.headers.get("X-Study-Context")

        attempt_id = None
        if ledgered:
            ok, attempt_id, ordinal = _reserve_or_reject(context_header)
            if not ok:
                self._refuse(429, f"study budget ceiling reached ({BUDGET_CEILING})")
                return

        start = time.monotonic()
        try:
            if ledgered:
                _gen_lock.acquire()  # single generation concurrency, held for the whole call
            conn = http.client.HTTPConnection(UPSTREAM_HOST, UPSTREAM_PORT, timeout=REQUEST_TIMEOUT_S)
            fwd_headers = {
                k: v for k, v in self.headers.items()
                if k.lower() not in ("host", "content-length", "connection")
            }
            fwd_headers["Content-Length"] = str(len(body))
            fwd_headers["Host"] = f"{UPSTREAM_HOST}:{UPSTREAM_PORT}"
            conn.request(method, self.path, body=body, headers=fwd_headers)
            resp = conn.getresponse()

            # Deliberately never forward upstream's Content-Length or
            # Transfer-Encoding: for a streaming chat completion
            # (main_simple.py sends "stream": true), http.client already
            # de-chunks on read(), so re-forwarding either header verbatim
            # would either be wrong (stale length) or absent — leaving an
            # HTTP/1.1 client unable to tell where the body ends, which
            # previously hung every non-Content-Length upstream response
            # (e.g. /health) until the *client's* timeout fired as a bare,
            # message-less asyncio.TimeoutError. Framing every response by
            # connection-close instead (valid for HTTP/1.1 responses per
            # RFC 7230 §3.3.3) is unambiguous for both the small fixed
            # /health body and true incremental streaming, and preserves
            # real first-byte/incremental timing since we still forward
            # each chunk to wfile as it arrives rather than buffering.
            self.send_response(resp.status)
            skip = {"transfer-encoding", "connection", "content-length"}
            for k, v in resp.getheaders():
                if k.lower() not in skip:
                    self.send_header(k, v)
            self.send_header("Connection", "close")
            self.end_headers()
            self.close_connection = True

            total_bytes = 0
            while True:
                chunk = resp.read(8192)
                if not chunk:
                    break
                total_bytes += len(chunk)
                try:
                    self.wfile.write(chunk)
                    self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError):
                    break
            conn.close()

            if ledgered:
                _ledger_append({
                    "event": "completed",
                    "attempt_id": attempt_id,
                    "ts": _utcnow(),
                    "upstream_status": resp.status,
                    "elapsed_s": round(time.monotonic() - start, 3),
                    "response_bytes": total_bytes,
                    "context": context_header,
                })
        except (TimeoutError, http.client.HTTPException, OSError) as exc:
            if ledgered and attempt_id:
                _ledger_append({
                    "event": "failed",
                    "attempt_id": attempt_id,
                    "ts": _utcnow(),
                    "error": repr(exc),
                    "elapsed_s": round(time.monotonic() - start, 3),
                    "context": context_header,
                })
            try:
                self._refuse(502, f"upstream error: {exc!r}")
            except Exception:
                pass
        finally:
            if ledgered:
                _gen_lock.release()

    def do_GET(self):
        self._proxy("GET", ledgered=False)

    def do_POST(self):
        self._proxy("POST", ledgered=True)


def main() -> None:
    server = ThreadingHTTPServer(("0.0.0.0", LISTEN_PORT), GatewayHandler)
    _ledger_append({
        "event": "gateway_start",
        "ts": _utcnow(),
        "upstream": f"{UPSTREAM_HOST}:{UPSTREAM_PORT}",
        "ceiling": BUDGET_CEILING,
        "reserved_count_at_start": _reserved_count(),
    })
    server.serve_forever()


if __name__ == "__main__":
    main()
