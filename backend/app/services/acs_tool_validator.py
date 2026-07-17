"""Static validation for Sara's user-defined tools.

This is the gate between her authoring a tool and that tool ever being stored
or invoked. It is *not* the sandbox — the runtime sandbox lives in a separate
process. The validator only enforces:

  - the code parses
  - it defines a top-level `def run(args: dict) -> dict`
  - imports come from a small whitelist
  - banned names (filesystem, exec, dunder access, etc.) don't appear

Anything that gets past this still runs in a resource-limited subprocess —
defense in depth. But rejecting obvious violations here means we don't store
junk, the audit trail is cleaner, and her own author-feedback loop is faster.
"""
from __future__ import annotations

import ast


# Modules she can import. Network goes through httpx; everything else is pure-
# python utility. Adding to this list is a real decision — anything with an os
# / fs / process surface stays out.
ALLOWED_IMPORTS = frozenset({
    "httpx",
    "json",
    "re",
    "datetime",
    "math",
    "collections",
    "itertools",
    "functools",
    "typing",
    "statistics",
    "urllib.parse",
    "hashlib",
    "base64",
    "string",
    "decimal",
    "fractions",
    "random",
    "html",
})


# Names she may not reference at all. Includes anything that opens a path to
# the filesystem, subprocess, raw memory, or eval-style code execution.
BANNED_NAMES = frozenset({
    "os", "sys", "subprocess", "importlib", "ctypes", "multiprocessing",
    "socket", "signal", "resource", "pathlib", "shutil", "tempfile",
    "pickle", "marshal", "shelve",
    "open", "eval", "exec", "compile",
    "globals", "locals", "vars",
    "__import__", "__builtins__",
    "input", "breakpoint",
})


# Cap on stored code size — keeps the row sane and makes sure she's not
# trying to ship a whole library as a "tool."
MAX_CODE_BYTES = 32 * 1024


class ToolValidationError(ValueError):
    """Raised when submitted tool code fails static validation."""


def _check_imports(node: ast.AST) -> None:
    if isinstance(node, ast.Import):
        for alias in node.names:
            top = alias.name.split(".")[0]
            if top not in ALLOWED_IMPORTS:
                raise ToolValidationError(f"import not allowed: {alias.name}")
    elif isinstance(node, ast.ImportFrom):
        mod = (node.module or "").split(".")[0]
        if mod not in ALLOWED_IMPORTS:
            raise ToolValidationError(
                f"import not allowed: from {node.module or '.'} import …"
            )


def _check_names(node: ast.AST) -> None:
    if isinstance(node, ast.Name) and node.id in BANNED_NAMES:
        raise ToolValidationError(f"name not allowed: {node.id}")
    if isinstance(node, ast.Attribute) and isinstance(node.attr, str):
        if node.attr.startswith("__") and node.attr.endswith("__"):
            # Dunder access: not banned uniformly (e.g. Pydantic uses __dict__),
            # but a small explicit blocklist of escape vectors.
            if node.attr in {"__import__", "__builtins__", "__class__",
                             "__bases__", "__subclasses__", "__globals__",
                             "__code__", "__closure__"}:
                raise ToolValidationError(f"attribute not allowed: .{node.attr}")


def _has_run_entrypoint(tree: ast.Module) -> bool:
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "run":
            args = node.args.args
            if not args:
                raise ToolValidationError(
                    "`run` must take exactly one positional argument: `args: dict`"
                )
            return True
    return False


def validate_tool_code(code: str) -> None:
    """Raise ToolValidationError with a clear message if the code is unsafe to store.

    Order matters: size cap first (cheapest), parse second, then walk for
    imports/names/dunders, finally check for the run() entry point.
    """
    if not isinstance(code, str) or not code.strip():
        raise ToolValidationError("code is empty")
    if len(code.encode("utf-8")) > MAX_CODE_BYTES:
        raise ToolValidationError(
            f"code exceeds size cap of {MAX_CODE_BYTES} bytes"
        )

    try:
        tree = ast.parse(code, mode="exec")
    except SyntaxError as e:
        raise ToolValidationError(f"syntax error: {e.msg} (line {e.lineno})") from e

    for node in ast.walk(tree):
        _check_imports(node)
        _check_names(node)

    if not _has_run_entrypoint(tree):
        raise ToolValidationError(
            "must define a top-level `def run(args: dict) -> dict` entry point"
        )


def validate_args_schema(schema: dict) -> None:
    """Shape check on the JSON Schema she submits for a tool's args.

    Full meta-schema validation would need the `jsonschema` library; we don't
    have that as a dep yet, so we enforce the minimum shape needed to render
    and validate args at invoke time.
    """
    if not isinstance(schema, dict):
        raise ToolValidationError("args_schema must be a JSON object")
    if schema.get("type") != "object":
        raise ToolValidationError("args_schema must have type='object' at the root")
    props = schema.get("properties")
    if props is not None and not isinstance(props, dict):
        raise ToolValidationError("args_schema.properties must be an object")
    required = schema.get("required")
    if required is not None and not isinstance(required, list):
        raise ToolValidationError("args_schema.required must be an array")
