"""Controlled recording adapter simulating FatSecret's OAuth2 client-credentials
token endpoint and REST food API, for I-category (food/nutrition) cases.

Protocol-faithful: implements the exact two calls app/services/fatsecret_service.py
makes (`POST /connect/token` with Basic auth + client_credentials grant, then
`POST /rest/server.api` with `method=foods.search` / `method=food.get.v4`), in
FatSecret's own response shapes, against a small fixed fixture catalog — not a
blanket "always succeeds" stub. Records every request.

Fixture per the acceptance plan's exact spec (J05): plain chicken, 165 kcal and
31g protein per 100g.
"""
import json
import os
import time
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs

LEDGER_PATH = os.environ.get("LEDGER_PATH", "/ledger/fatsecret_sink_ledger.jsonl")
LISTEN_PORT = int(os.environ.get("LISTEN_PORT", "8095"))

# Fixture catalog. food_description strings match the exact
# "Per X - Calories: Ykcal | Fat: Zg | Carbs: Wg | Protein: Vg" shape
# fatsecret_service._parse_food_description expects.
FOODS = {
    "1000001": {
        "food_id": "1000001",
        "food_name": "Chicken Breast, Plain, Fixture",
        "food_type": "Generic",
        "brand_name": None,
        "food_description": "Per 100g - Calories: 165kcal | Fat: 3.60g | Carbs: 0.00g | Protein: 31.00g",
        "servings": [
            {
                "serving_id": "9000001",
                "serving_description": "100 g",
                "metric_serving_amount": "100.000",
                "metric_serving_unit": "g",
                "number_of_units": "1.000",
                "measurement_description": "g",
                "calories": "165", "protein": "31.00", "carbohydrate": "0.00", "fat": "3.60",
                "fiber": "0.00", "sugar": "0.00", "sodium": "74", "saturated_fat": "1.00",
            },
        ],
    },
}


def _utcnow():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _append(record: dict) -> None:
    os.makedirs(os.path.dirname(LEDGER_PATH), exist_ok=True)
    with open(LEDGER_PATH, "a") as fh:
        fh.write(json.dumps(record, sort_keys=True) + "\n")


class FSHandler(BaseHTTPRequestHandler):
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

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0) or 0)
        raw = self.rfile.read(length) if length else b""
        form = {k: v[0] for k, v in parse_qs(raw.decode()).items()}

        if self.path == "/connect/token":
            _append({"event": "token_request", "ts": _utcnow(), "grant_type": form.get("grant_type")})
            self._json(200, {
                "access_token": f"fixture-token-{uuid.uuid4().hex}",
                "token_type": "bearer",
                "expires_in": 86400,
                "scope": form.get("scope", "basic"),
            })
            return

        if self.path == "/rest/server.api":
            method = form.get("method")
            _append({"event": "api_request", "ts": _utcnow(), "method": method, "params": form})

            if method == "foods.search":
                query = (form.get("search_expression") or "").lower()
                matches = [f for f in FOODS.values() if query in f["food_name"].lower()]
                self._json(200, {
                    "foods": {
                        "food": matches if len(matches) != 1 else matches[0],
                        "total_results": str(len(matches)),
                        "max_results": form.get("max_results", "20"),
                        "page_number": form.get("page_number", "0"),
                    } if matches else {"total_results": "0"}
                })
                return

            if method == "food.get.v4":
                food_id = form.get("food_id")
                food = FOODS.get(food_id)
                if not food:
                    self._json(200, {"food": {}})
                    return
                servings = food["servings"]
                self._json(200, {
                    "food": {
                        "food_id": food["food_id"],
                        "food_name": food["food_name"],
                        "food_type": food["food_type"],
                        "brand_name": food["brand_name"],
                        "servings": {"serving": servings if len(servings) != 1 else servings[0]},
                    }
                })
                return

            self._json(400, {"error": f"unsupported method {method}"})
            return

        self._json(404, {"error": "not found"})


def main():
    server = ThreadingHTTPServer(("0.0.0.0", LISTEN_PORT), FSHandler)
    _append({"event": "sink_start", "ts": _utcnow()})
    server.serve_forever()


if __name__ == "__main__":
    main()
