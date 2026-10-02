#!/usr/bin/env python3
"""Does the configured vision endpoint actually accept an image?

FITNESS_COACH_IMPLEMENTATION_PLAN Step 27.1:

    "Verify selected endpoint/model with isolated nonpersonal test images;
     do not assume Qwen text lane handles multimodal input. Resolve actual
     UserSettings/defaults explicitly and record capability result."

Two reasons this cannot be assumed:

* `app/routes/vision.py` and `app/core/llm_config.py` disagree.
  `DEFAULT_VISION_ENDPOINT` is an Ollama at :11434; `llm_config.vision_url`
  is a llama-server at :8686. Only one of them is going to answer.
* A llama.cpp server started WITHOUT `--mmproj` serves the same model over
  the same API and silently ignores the image part — it answers the text
  prompt and describes nothing. That failure looks exactly like a model
  with poor vision, which is how "Qwen handles images" becomes a belief
  nobody checked. (The chat lane had precisely this problem until
  2026-08-20: `:8082` lacked `--mmproj`.)

The images here are SYNTHETIC — coloured shapes drawn in-process. No
athlete's photo goes near a probe.

    python backend/scripts/fitness_vision_probe.py
    python backend/scripts/fitness_vision_probe.py --json
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import io
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def synthetic_image(shape: str) -> bytes:
    """A plain PNG a sighted model can describe and a blind one cannot.

    Deliberately trivial: one large shape in one colour on white. If the
    answer names the shape and the colour, the image reached the model. If
    it does not, nothing about the physique prompt is worth trying.
    """
    from PIL import Image, ImageDraw

    canvas = Image.new("RGB", (512, 512), (255, 255, 255))
    draw = ImageDraw.Draw(canvas)
    if shape == "circle":
        draw.ellipse((96, 96, 416, 416), fill=(220, 30, 30))
    elif shape == "triangle":
        draw.polygon([(256, 80), (440, 432), (72, 432)], fill=(30, 90, 220))
    else:
        draw.rectangle((112, 112, 400, 400), fill=(30, 180, 90))
    buf = io.BytesIO()
    canvas.save(buf, format="PNG")
    return buf.getvalue()


PROBE_PROMPT = (
    "Answer with two words only: the colour and the shape you can see. "
    "If you cannot see an image, answer exactly: NO IMAGE."
)

#: What a sighted answer must contain, per shape.
EXPECTED = {
    "circle": (("red", "crimson"), ("circle", "round", "ellipse")),
    "triangle": (("blue",), ("triangle",)),
    "square": (("green",), ("square", "rectangle")),
}


async def probe_openai(endpoint: str, model: str, shape: str) -> dict:
    from app.routes.vision import call_openai_vision

    image = base64.b64encode(synthetic_image(shape)).decode()
    started = time.monotonic()
    try:
        result = await call_openai_vision(
            image, PROBE_PROMPT, model, endpoint, max_tokens=40,
        )
    except Exception as exc:
        return {
            "transport": "openai", "endpoint": endpoint, "model": model,
            "shape": shape, "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
        }
    elapsed = time.monotonic() - started
    answer = (result.get("response") or "").strip()
    colours, shapes = EXPECTED[shape]
    lowered = answer.lower()
    sighted = (
        any(c in lowered for c in colours) and any(s in lowered for s in shapes)
    )
    return {
        "transport": "openai", "endpoint": endpoint,
        "model_requested": model, "model_actual": result.get("model"),
        "shape": shape, "answer": answer, "ok": sighted,
        "seconds": round(elapsed, 1),
        "blind_marker": "no image" in lowered,
    }


async def probe_ollama(endpoint: str, model: str, shape: str) -> dict:
    from app.routes.vision import call_ollama_vision

    image = base64.b64encode(synthetic_image(shape)).decode()
    try:
        # No `max_tokens` here: `call_ollama_vision` does not take one.
        # Keeping the two probe calls shaped alike would have hidden the
        # real result behind a TypeError.
        result = await call_ollama_vision(
            image, PROBE_PROMPT, model, endpoint,
        )
    except Exception as exc:
        return {
            "transport": "ollama", "endpoint": endpoint, "model": model,
            "shape": shape, "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
        }
    answer = (result.get("response") or "").strip()
    colours, shapes = EXPECTED[shape]
    lowered = answer.lower()
    return {
        "transport": "ollama", "endpoint": endpoint,
        "model_requested": model, "model_actual": result.get("model"),
        "shape": shape, "answer": answer,
        "ok": any(c in lowered for c in colours) and any(s in lowered for s in shapes),
    }


def configured() -> list[tuple[str, str, str]]:
    """Every endpoint/model pair the code might actually pick.

    Resolved explicitly rather than assumed, which is the point: the two
    modules disagree, and a probe that only tried one would confirm
    whichever belief it started with.
    """
    pairs = []
    try:
        from app.routes.vision import (
            DEFAULT_VISION_ENDPOINT, DEFAULT_VISION_MODEL,
        )
        pairs.append(("ollama", DEFAULT_VISION_ENDPOINT, DEFAULT_VISION_MODEL))
    except Exception:
        pass
    try:
        from app.core.llm_config import llm_config
        pairs.append(("openai", llm_config.vision_url, llm_config.vision_model))
    except Exception:
        pass
    return pairs


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--shapes", default="circle,triangle")
    args = parser.parse_args()

    results = []
    for transport, endpoint, model in configured():
        for shape in args.shapes.split(","):
            if transport == "ollama":
                results.append(await probe_ollama(endpoint, model, shape.strip()))
            else:
                results.append(await probe_openai(endpoint, model, shape.strip()))

    if args.json:
        print(json.dumps(results, indent=2))
    else:
        for row in results:
            verdict = "SIGHTED" if row.get("ok") else "FAILED "
            print(
                f"{verdict} {row['transport']:7} {row['endpoint']} "
                f"{row.get('model_actual') or row.get('model')}"
            )
            if row.get("answer"):
                print(f"         shape={row['shape']} -> {row['answer']!r}")
            if row.get("error"):
                print(f"         {row['error']}")
            if row.get("blind_marker"):
                print(
                    "         the model said NO IMAGE — the endpoint is "
                    "serving this model without multimodal support"
                )

    usable = [r for r in results if r.get("ok")]
    print(
        f"\n{len(usable)}/{len(results)} probes saw the image."
        + ("" if usable else " No vision capability is available.")
    )
    return 0 if usable else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
