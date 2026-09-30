"""Recording adapter simulating Expo's push relay (`/--/api/v2/push/send`),
for the acceptance study's isolated worker/reminder-delivery cases.

Protocol-faithful, not a stub-always-success: accepts the same POST body
shape the real app sends (a list of {to, title, body, data, ...} messages),
records every request durably (append-only JSONL, one line per receipt) so
a case can assert "exactly one delivery reached the sink" independently of
whatever Sara said happened, and returns Expo's actual response shape
(`{"data": [{"status": "ok", "id": "..."}, ...]}`) so the app's own
response-parsing code (which expects that shape) behaves identically to
production. Supports injected per-token failure via the `SIMULATE_FAIL_TOKENS`
env var (comma-separated token substrings) for later failure-injection cases.
"""
import json
import os
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

LEDGER_PATH = os.environ.get("LEDGER_PATH", "/ledger/push_sink_ledger.jsonl")
LISTEN_PORT = int(os.environ.get("LISTEN_PORT", "8090"))
SIMULATE_FAIL_TOKENS = [
    t for t in os.environ.get("SIMULATE_FAIL_TOKENS", "").split(",") if t
]


def _utcnow():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _append(record: dict) -> None:
    os.makedirs(os.path.dirname(LEDGER_PATH), exist_ok=True)
    with open(LEDGER_PATH, "a") as fh:
        fh.write(json.dumps(record, sort_keys=True) + "\n")


class SinkHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        pass

    def do_POST(self):
        if self.path != "/--/api/v2/push/send":
            body = json.dumps({"error": "not found"}).encode()
            self.send_response(404)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(body)
            self.close_connection = True
            return

        length = int(self.headers.get("Content-Length", 0) or 0)
        raw = self.rfile.read(length) if length else b""
        try:
            messages = json.loads(raw)
        except json.JSONDecodeError:
            messages = None
        if isinstance(messages, dict):
            messages = [messages]
        if not isinstance(messages, list):
            messages = []

        tickets = []
        for msg in messages:
            token = str(msg.get("to", ""))
            receipt_id = uuid.uuid4().hex
            failed = any(f in token for f in SIMULATE_FAIL_TOKENS)
            record = {
                "event": "push_received",
                "ts": _utcnow(),
                "receipt_id": receipt_id,
                "to": token,
                "title": msg.get("title"),
                "body": msg.get("body"),
                "data": msg.get("data"),
                "priority": msg.get("priority"),
                "outcome": "failed_simulated" if failed else "ok",
            }
            _append(record)
            if failed:
                tickets.append({
                    "status": "error",
                    "message": "simulated failure",
                    "details": {"error": "DeviceNotRegistered"},
                })
            else:
                tickets.append({"status": "ok", "id": receipt_id})

        resp_body = json.dumps({"data": tickets}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(resp_body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True
        self.wfile.write(resp_body)


def main():
    server = ThreadingHTTPServer(("0.0.0.0", LISTEN_PORT), SinkHandler)
    _append({"event": "sink_start", "ts": _utcnow()})
    server.serve_forever()


if __name__ == "__main__":
    main()
