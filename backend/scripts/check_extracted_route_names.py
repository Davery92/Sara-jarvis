#!/usr/bin/env python3
"""Static unresolved-name check for handlers extracted out of main_simple.py.

Why this exists (2026-09-30): the monolith-extraction gates verified that every
route was still REGISTERED (a full route-table diff) and that each moved route
resolved the same auth dependency (by identity). Neither one ever EXECUTED a
handler body, so a name the handler used but the new module did not import was
invisible — it only appears as a NameError when that endpoint is actually hit.

Twelve of them shipped. `/api/health/sync-recovery` 500'd in production with
`name 'local_today' is not defined`; `/analytics/dashboard` was missing six
models plus `embedding_service` and `naive_local_now`;
`/api/pi-dashboard/voice/transcribe` was missing `os`. Every one came from an
`import` in main_simple.py rather than an assignment, which is exactly what the
original analysis did not collect.

Run it after moving anything else out of the monolith:
    python backend/scripts/check_extracted_route_names.py
Exit 0 means every name each listed handler uses resolves in its new home.
"""
import ast
import builtins
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]

# handler name -> module it now lives in. Add a row when you extract something.
EXTRACTED = {
    "backend/app/routes/health_metrics.py": [
        "sync_health_data", "get_health_episode_summary", "sync_recovery_from_health"],
    "backend/app/routes/voice_agent.py": ["transcribe_audio", "speak_text"],
    "backend/app/routes/notes.py": ["search_notes_api", "search_notes", "_search_notes_rows"],
    "backend/app/routes/workspace.py": ["get_pending_workspace_commands"],
    "backend/app/routes/assistant_analytics.py": ["get_analytics_dashboard"],
    "backend/app/routes/subconscious.py": ["get_shadow_active"],
    "backend/app/routes/pi_dashboard.py": [
        "pi_dashboard_voice_transcribe", "pi_dashboard_voice_speak"],
}


def module_level_names(tree):
    """Names bound at MODULE level only.

    Deliberately iterates `tree.body` rather than `ast.walk(tree)`. The first
    version walked the whole tree, so a function-LOCAL `from x import y` in some
    other function counted as module-level and made `y` look available
    everywhere. That is precisely how `mirror_hrv_morning` slipped past this
    check and 500'd `/api/health/sync-recovery` a second time: health_metrics.py
    imports it inside a different handler, 700 lines away from the one that
    needed it. A handler that imports a name itself still passes, because
    `bound_in` collects its own local imports.
    """
    names = set(dir(builtins))
    for n in tree.body:
        if isinstance(n, ast.ImportFrom):
            names |= {a.asname or a.name for a in n.names}
        elif isinstance(n, ast.Import):
            names |= {a.asname or a.name.split(".")[0] for a in n.names}
        elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(n.name)
        elif isinstance(n, ast.Assign):
            for t in n.targets:
                names |= {x.id for x in ast.walk(t) if isinstance(x, ast.Name)}
        elif isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name):
            names.add(n.target.id)
    return names


def bound_in(node):
    """Every name bound anywhere inside `node`, including nested scopes.

    Deliberately over-broad — a nested def's parameters and comprehension
    targets count as bound. This check is for MISSING IMPORTS, so a false
    negative is better than the false positive that `default` (a nested
    function's own parameter) produced in the first version.
    """
    bound = set()
    for n in ast.walk(node):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            a = n.args
            bound |= {x.arg for x in a.args + a.kwonlyargs + a.posonlyargs}
            for x in (a.vararg, a.kwarg):
                if x:
                    bound.add(x.arg)
            bound.add(n.name)
        elif isinstance(n, ast.Name) and isinstance(n.ctx, (ast.Store, ast.Del)):
            bound.add(n.id)
        elif isinstance(n, ast.ExceptHandler) and n.name:
            bound.add(n.name)
        elif isinstance(n, (ast.Import, ast.ImportFrom)):
            bound |= {x.asname or x.name.split(".")[0] for x in n.names}
        elif isinstance(n, ast.ClassDef):
            bound.add(n.name)
        elif isinstance(n, ast.Global):
            bound |= set(n.names)
    return bound


def main():
    problems = []
    for rel, handlers in EXTRACTED.items():
        path = REPO / rel
        if not path.exists():
            problems.append((rel, "-", f"module missing: {rel}"))
            continue
        tree = ast.parse(path.read_text())
        available = module_level_names(tree)
        found = set()
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if node.name not in handlers:
                continue
            found.add(node.name)
            local = bound_in(node)
            seen = set()
            for n in ast.walk(node):
                if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load):
                    if n.id in local or n.id in available or n.id in seen:
                        continue
                    seen.add(n.id)
                    problems.append((rel, node.name, f"{n.id!r} (line {n.lineno})"))
        for missing in sorted(set(handlers) - found):
            problems.append((rel, missing, "handler not found in this module"))

    if problems:
        print(f"UNRESOLVED NAMES: {len(problems)}\n")
        for rel, fn, what in problems:
            print(f"  {rel}\n    {fn}(): {what}")
        return 1
    total = sum(len(v) for v in EXTRACTED.values())
    print(f"OK — every name resolves in {total} extracted handlers "
          f"across {len(EXTRACTED)} modules")
    return 0


if __name__ == "__main__":
    sys.exit(main())
