"""Drive one journey or conversation set against the candidate's own
/chat/stream, inside the isolated api container.

Reliable-assistant plan §10. Every upstream request goes through the gateway,
which holds this task to 300 reservations against an append-only ledger
(proven with a fake upstream by backend/tests/test_generation_budget_gateway.py,
at zero model cost).

  python tests/assistant_acceptance/reliable_drive.py <token> <script.json> <out.json>

A script is `{"name": ..., "conversations": [{"label": ..., "turns": [...]}]}`.
A turn is a string, or `{"say": str, "follow_up_if": str, "then_say": str}` —
the adaptive form, whose follow-up is chosen by a plain substring check on
Sara's own reply, never by another model call. The plan forbids a tested-model
user simulator, so there is none: user turns are fixed text written in advance,
and the one adaptive branch per turn is a deterministic string test.

Outcome checking does NOT happen here. It happens afterwards, in SQL, against
hidden outcome cards the model never sees — see reliable_check.py.
"""
import json
import sys
import time
import urllib.error
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
    chunks, tools, conv, err = [], [], conversation_id, None
    final = None
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
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
                data = obj.get("data") if isinstance(obj.get("data"), dict) else obj
                if etype == "text_chunk":
                    chunks.append(data.get("content") or "")
                elif etype == "final_response":
                    final = data.get("content")
                    conv = data.get("conversation_id") or conv
                elif etype == "error":
                    err = data.get("message")
                elif etype and "tool" in etype:
                    tools.append({"type": etype, "tool": data.get("tool")})
    except urllib.error.HTTPError as exc:
        err = f"HTTP {exc.code}: {exc.read()[:300].decode('utf-8', 'replace')}"
    except Exception as exc:  # noqa: BLE001 — the transcript records whatever happened
        err = f"{type(exc).__name__}: {exc}"
    return {
        "reply": final,
        "streamed_chunk_count": len(chunks),
        "streamed_text": "".join(chunks),
        "conversation_id": conv,
        "tool_events": tools,
        "elapsed_s": round(time.monotonic() - t0, 1),
        "error": err,
    }


def run(token, script):
    out = {"name": script.get("name"), "started": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "conversations": []}
    for conversation in script["conversations"]:
        conv_id = None
        record = {"label": conversation["label"], "turns": []}
        for raw_turn in conversation["turns"]:
            turn = {"say": raw_turn} if isinstance(raw_turn, str) else dict(raw_turn)
            said = turn["say"]
            result = send(token, said, conv_id)
            conv_id = result["conversation_id"] or conv_id
            record["turns"].append({"user": said, **result})
            print(f"\n>>> [{conversation['label']}] {said}")
            print(f"<<< {result['reply']!r}")
            if result["error"]:
                print(f"!!! {result['error']}")
                if "429" in str(result["error"]):
                    record["stopped_at_budget_ceiling"] = True
                    out["conversations"].append(record)
                    out["stopped_at_budget_ceiling"] = True
                    return out
            follow = turn.get("follow_up_if")
            if follow and result["reply"] and follow.lower() in result["reply"].lower():
                extra = turn["then_say"]
                extra_result = send(token, extra, conv_id)
                conv_id = extra_result["conversation_id"] or conv_id
                record["turns"].append({
                    "user": extra, "adaptive": True,
                    "adaptive_trigger": follow, **extra_result,
                })
                print(f"\n>>> [{conversation['label']}] (adaptive) {extra}")
                print(f"<<< {extra_result['reply']!r}")
        record["conversation_id"] = conv_id
        out["conversations"].append(record)
    return out


if __name__ == "__main__":
    token_arg, script_path, out_path = sys.argv[1], sys.argv[2], sys.argv[3]
    with open(script_path) as fh:
        script_obj = json.load(fh)
    result_obj = run(token_arg, script_obj)
    with open(out_path, "w") as fh:
        json.dump(result_obj, fh, indent=2)
    print(f"\nwrote {out_path}")
