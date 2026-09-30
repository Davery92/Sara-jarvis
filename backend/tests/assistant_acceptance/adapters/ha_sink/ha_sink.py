"""Recording adapter simulating Home Assistant's REST API
(GET /api/states, GET /api/states/{entity_id}, POST /api/services/{domain}/{service})
for M-category / J11 cases.

Seeded, stateful, protocol-faithful: maintains real in-memory entity state
that service calls actually mutate (not a stub that always says success),
records every request durably, and supports a "stale/unavailable" entity
(M02) that never changes state regardless of commands sent to it.
"""
import json
import os
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

LEDGER_PATH = os.environ.get("LEDGER_PATH", "/ledger/ha_sink_ledger.jsonl")
LISTEN_PORT = int(os.environ.get("LISTEN_PORT", "8123"))

STATE = {
    "light.test_porch": {"entity_id": "light.test_porch", "state": "off", "attributes": {"brightness": None, "friendly_name": "Test Porch Light"}, "last_changed": None},
    "climate.test_thermostat": {"entity_id": "climate.test_thermostat", "state": "idle", "attributes": {"temperature": 68, "friendly_name": "Test Thermostat"}, "last_changed": None},
    "lock.test_front_door": {"entity_id": "lock.test_front_door", "state": "locked", "attributes": {"friendly_name": "Test Front Door"}, "last_changed": None},
    # M02: stale/unavailable device — never acknowledges commands.
    "lock.test_stale_lock": {"entity_id": "lock.test_stale_lock", "state": "unavailable", "attributes": {"friendly_name": "Test Stale Lock"}, "last_changed": "2026-09-01T00:00:00+00:00"},
}


def _utcnow():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _append(record: dict) -> None:
    os.makedirs(os.path.dirname(LEDGER_PATH), exist_ok=True)
    with open(LEDGER_PATH, "a") as fh:
        fh.write(json.dumps(record, sort_keys=True) + "\n")


class HAHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        pass

    def _json(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/api/states":
            _append({"event": "get_states", "ts": _utcnow()})
            self._json(200, list(STATE.values()))
            return
        if self.path.startswith("/api/states/"):
            entity_id = self.path[len("/api/states/"):]
            _append({"event": "get_state", "entity_id": entity_id, "ts": _utcnow()})
            if entity_id in STATE:
                self._json(200, STATE[entity_id])
            else:
                self._json(404, {"message": "Entity not found"})
            return
        self._json(404, {"message": "not found"})

    def do_POST(self):
        if not self.path.startswith("/api/services/"):
            self._json(404, {"message": "not found"})
            return
        parts = self.path[len("/api/services/"):].split("/")
        if len(parts) != 2:
            self._json(400, {"message": "bad service path"})
            return
        domain, service = parts
        length = int(self.headers.get("Content-Length", 0) or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            data = {}
        entity_id = data.get("entity_id")
        record = {"event": "call_service", "domain": domain, "service": service, "entity_id": entity_id, "data": data, "ts": _utcnow()}

        affected = []
        ent = STATE.get(entity_id) if entity_id else None
        if ent is None:
            _append({**record, "outcome": "entity_not_found"})
            self._json(404, {"message": f"Entity {entity_id} not found"})
            return

        if ent["state"] == "unavailable":
            # Stale/offline device: commands are accepted by HA's own API
            # shape (still 200) but never actually change state — mirrors
            # a real unresponsive device, not a fabricated success.
            _append({**record, "outcome": "device_unavailable_no_state_change"})
            self._json(200, [ent])
            return

        if domain == "light" and service in ("turn_on", "turn_off"):
            ent["state"] = "on" if service == "turn_on" else "off"
            if "brightness_pct" in data:
                ent["attributes"]["brightness"] = round(255 * data["brightness_pct"] / 100)
            ent["last_changed"] = _utcnow()
            affected.append(ent)
        elif domain == "lock" and service in ("lock", "unlock"):
            ent["state"] = "locked" if service == "lock" else "unlocked"
            ent["last_changed"] = _utcnow()
            affected.append(ent)
        elif domain == "climate" and service == "set_temperature":
            ent["attributes"]["temperature"] = data.get("temperature", ent["attributes"]["temperature"])
            ent["last_changed"] = _utcnow()
            affected.append(ent)
        else:
            _append({**record, "outcome": "unsupported_service"})
            self._json(400, {"message": f"unsupported service {domain}.{service}"})
            return

        _append({**record, "outcome": "ok", "new_state": ent["state"]})
        self._json(200, affected)


def main():
    server = ThreadingHTTPServer(("0.0.0.0", LISTEN_PORT), HAHandler)
    _append({"event": "sink_start", "ts": _utcnow()})
    server.serve_forever()


if __name__ == "__main__":
    main()
