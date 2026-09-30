"""Drive real conversations against the candidate's own /chat/stream.

Runs INSIDE the isolated api container. Every upstream model request goes
through the gateway, which holds this task to 60 reservations. Prints each
turn's final text, the tools that actually executed, and timing — nothing is
reconstructed or simulated.

  python tests/assistant_acceptance/convention_drive.py <token> <script.json>

`script.json` is a list of {"conversation": <label>, "turns": [str, ...]} —
a new conversation label starts a fresh conversation_id, which is how the
new-conversation readback case is expressed.
"""
import json
import sys
import time
import urllib.request
import uuid


def send(token, message, conversation_id):
    body = {
        "messages": [{"role": "user", "content": message,
                      "client_message_id": str(uuid.uuid4())}],
        "conversation_id": conversation_id,
        "source": "webapp",
    }
    req = urllib.request.Request(
        "http://localhost:8000/chat/stream",
        data=json.dumps(body).encode(),
        method="POST",
        headers={"Authorization": f"Bearer {token}",
                 "Content-Type": "application/json",
                 "Accept": "text/event-stream"},
    )
    text_parts, tools, conv, err = [], [], conversation_id, None
    t0 = time.monotonic()
    with urllib.request.urlopen(req, timeout=240) as resp:
        for raw in resp:
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data:"):
                continue
            try:
                obj = json.loads(line[5:].strip())
            except json.JSONDecodeError:
                continue
            if not isinstance(obj, dict):
                continue
            etype = obj.get("type")
            data = obj.get("data") if isinstance(obj.get("data"), dict) else {}
            if etype == "final_response":
                text_parts = [obj.get("content") or data.get("content") or ""]
            elif etype == "text_chunk" and not text_parts:
                text_parts.append(obj.get("content") or data.get("content") or "")
            elif etype in ("tool_call", "tool_start", "tool_result", "tool_complete"):
                name = obj.get("tool") or data.get("tool") or data.get("name")
                if name:
                    tools.append(f"{etype}:{name}")
            elif etype == "error":
                err = obj.get("message") or data.get("message") or str(obj)
            for key in ("conversation_id",):
                if obj.get(key):
                    conv = obj[key]
                if data.get(key):
                    conv = data[key]
    return {"text": "".join(text_parts).strip(), "tools": tools,
            "conversation_id": conv, "error": err,
            "seconds": round(time.monotonic() - t0, 1)}


def main():
    token, script_path = sys.argv[1], sys.argv[2]
    script = json.load(open(script_path))
    out = []
    for block in script:
        conv_id = None
        print(f"\n{'=' * 78}\nCONVERSATION: {block['conversation']}\n{'=' * 78}")
        for turn in block["turns"]:
            print(f"\n>>> DAVID: {turn}")
            try:
                r = send(token, turn, conv_id)
            except Exception as exc:
                print(f"!!! TRANSPORT FAILURE: {type(exc).__name__}: {exc}")
                out.append({"conversation": block["conversation"], "user": turn,
                            "error": f"{type(exc).__name__}: {exc}"})
                continue
            conv_id = r["conversation_id"] or conv_id
            print(f"<<< SARA ({r['seconds']}s): {r['text']}")
            if r["tools"]:
                print(f"    tools: {r['tools']}")
            if r["error"]:
                print(f"    ERROR EVENT: {r['error']}")
            r.update({"conversation": block["conversation"], "user": turn})
            out.append(r)
    dest = script_path.replace(".json", "_results.json")
    with open(dest, "w") as fh:
        json.dump(out, fh, indent=2)
    print(f"\nwrote {dest}")


if __name__ == "__main__":
    main()
