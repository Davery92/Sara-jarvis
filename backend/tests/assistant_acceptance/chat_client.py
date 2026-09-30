"""Minimal real SSE client against the isolated api's /chat/stream, run
inside the `shell` container (container-DNS `api:8000`, same internal_net).
Prints every SSE event and the final assembled text; does not parse
production's prompt assembly itself (per plan: never reconstruct a
simplified harness) — this only drives the real HTTP endpoint and reads
whatever comes back.
"""
import argparse
import json
import sys
import time
import urllib.request
import uuid


def send_turn(token: str, message: str, conversation_id: str | None, client_message_id: str | None = None, source: str = "webapp"):
    body = {
        "messages": [{"role": "user", "content": message, "client_message_id": client_message_id or str(uuid.uuid4())}],
        "conversation_id": conversation_id,
        "source": source,
    }
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        "http://api:8000/chat/stream",
        data=data,
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        },
    )
    t0 = time.monotonic()
    first_byte_t = None
    first_text_chunk_t = None
    events = []
    text_chunk_deltas = []  # incremental deltas from the real streaming path (event 'content' field)
    final_response_content = None
    conversation_id_seen = None
    tool_events = []
    saw_done = False
    saw_error = None
    with urllib.request.urlopen(req, timeout=170) as resp:
        for raw_line in resp:
            if first_byte_t is None:
                first_byte_t = time.monotonic()
            line = raw_line.decode("utf-8", errors="replace").rstrip("\n")
            if not line:
                continue
            events.append(line)
            if line.startswith("data:"):
                payload = line[len("data:"):].strip()
                try:
                    obj = json.loads(payload)
                except json.JSONDecodeError:
                    continue
                if not isinstance(obj, dict):
                    continue
                etype = obj.get("type")
                d = obj.get("data") if isinstance(obj.get("data"), dict) else obj
                if etype == "text_chunk":
                    if first_text_chunk_t is None:
                        first_text_chunk_t = time.monotonic()
                    c = d.get("content")
                    if isinstance(c, str):
                        text_chunk_deltas.append(c)
                elif etype == "final_response":
                    final_response_content = d.get("content")
                    conversation_id_seen = d.get("conversation_id")
                elif etype == "done":
                    saw_done = True
                elif etype == "error":
                    saw_error = d.get("message")
                elif etype and ("tool" in etype):
                    tool_events.append(obj)
    t_end = time.monotonic()
    # `text_chunk` deltas may themselves each carry the FULL accumulated text
    # (some paths) or true incremental deltas (the real per-token streaming
    # path) — report both raw concatenation and the last chunk seen so a
    # human/analysis script can tell which shape this turn actually used,
    # rather than silently guessing.
    return {
        "http_ok": True,
        "elapsed_total_s": round(t_end - t0, 3),
        "elapsed_first_byte_s": round((first_byte_t - t0), 3) if first_byte_t else None,
        "elapsed_first_text_chunk_s": round((first_text_chunk_t - t0), 3) if first_text_chunk_t else None,
        "raw_event_count": len(events),
        "text_chunk_count": len(text_chunk_deltas),
        "text_chunk_concat": "".join(text_chunk_deltas),
        "text_chunk_last": text_chunk_deltas[-1] if text_chunk_deltas else None,
        "final_response_content": final_response_content,
        "conversation_id": conversation_id_seen,
        "tool_event_count": len(tool_events),
        "tool_events": tool_events,
        "saw_done": saw_done,
        "saw_error": saw_error,
        "raw_tail": events[-8:],
    }


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--token", required=True)
    p.add_argument("--message", required=True)
    p.add_argument("--conversation-id", default=None)
    p.add_argument("--client-message-id", default=None)
    args = p.parse_args()
    result = send_turn(args.token, args.message, args.conversation_id, args.client_message_id)
    print(json.dumps(result, indent=2))
