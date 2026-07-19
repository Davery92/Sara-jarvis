"""
The read-only command whitelist — layer 1 (server) and layer 2 (agent).

This module is **pure Python stdlib** on purpose: the backend imports it, and a
verbatim copy is embedded in ``sara_fleet_agent.py`` so the agent re-validates
every command against its *own* authoritative copy (FLEET_DESIGN.md §5). Keep the
two in sync; there are no third-party imports here so the copy is literal.

The guarantee is defence-in-depth. This module provides three of the four layers'
worth of logic that lives in userspace:

  1. Only whitelisted *binaries* run.
  2. No shell — commands are ``shlex.split`` into an argv array and executed with
     ``shell=False``. Pipes / redirection / ``$(...)`` / ``;`` / ``&&`` are inert.
  3. File-reading binaries (cat/ls/find/du/head/tail) may only touch paths under a
     small allow-prefix set, minus a secret deny list, resolved with realpath so
     symlinks can't escape.

The fourth layer (kernel sandbox via systemd) lives in the unit file, not here.
"""

import os
import shlex

VERSION = "1"

# Binaries that read a file/dir argument — their path arguments are restricted.
_PATH_ALLOW_PREFIXES = ("/proc", "/sys", "/var/log", "/etc")
_PATH_DENY_SUBSTRINGS = ("secret", "credential", "token", "password", "passwd", "shadow")
_PATH_DENY_EXACT_PREFIXES = ("/etc/shadow", "/etc/ssh/", "/etc/sara-agent", "/proc/", )
# NOTE: /proc is allowed generally, but /proc/<pid>/environ leaks secrets → deny.
_PATH_DENY_SUFFIXES = (".pem", ".key")


def _bad(reason):
    return (False, reason, None)


def _check_flags(args, allowed, reject=None, allow_values=True):
    """Reject-set tokens are hard-denied; everything else is allowed.

    The binaries with a ``flags`` policy are all inherently read-only (df, ps,
    journalctl, …) — they cannot mutate the system. The real read-only boundary is
    the *binary* whitelist + no-shell execution + the kernel sandbox, not the flag
    set. So we only hard-deny the handful of flags that hang or follow (``-f``),
    and otherwise accept arguments (including flag *values* like ``--sort -pcpu``).
    ``allowed`` is retained as documentation of the expected flag vocabulary.
    """
    reject = reject or set()
    for tok in args:
        base = tok.split("=", 1)[0]
        if tok in reject or base in reject:
            return f"flag '{tok}' is not permitted (read-only)"
    return None


def _check_subcommands(args, allowed, reject=None):
    reject = reject or set()
    sub = None
    for tok in args:
        if not tok.startswith("-"):
            sub = tok
            break
    if sub is None:
        return "a subcommand is required"
    if sub in reject:
        return f"subcommand '{sub}' is not permitted (read-only)"
    if sub not in allowed:
        return f"subcommand '{sub}' is not in the whitelist"
    # Any rejected token anywhere (e.g. 'ip link set', 'systemctl start') is denied.
    for tok in args:
        if tok in reject:
            return f"'{tok}' is not permitted (read-only)"
    return None


def _check_paths(args):
    """Path-reading binaries: only safe, non-secret, absolute paths under allow-prefixes."""
    saw_path = False
    for tok in args:
        if tok.startswith("-"):
            # a few benign flags are fine; block anything that could exec/delete
            if tok in ("-exec", "-execdir", "-delete", "-fprint", "-ok", "-okdir"):
                return f"'{tok}' is not permitted"
            continue
        saw_path = True
        p = tok
        if not p.startswith("/"):
            return f"path '{p}' must be absolute"
        real = os.path.realpath(p)
        low = real.lower()
        if any(s in low for s in _PATH_DENY_SUBSTRINGS):
            return f"path '{p}' looks sensitive — denied"
        if any(low.endswith(sfx) for sfx in _PATH_DENY_SUFFIXES):
            return f"path '{p}' looks like a key — denied"
        if real.startswith("/etc/shadow") or real.startswith("/etc/ssh/") or real.startswith("/etc/sara-agent"):
            return f"path '{p}' is denied"
        if real.startswith("/proc/") and real.endswith("/environ"):
            return f"path '{p}' would leak environment — denied"
        if not any(real == pre or real.startswith(pre + "/") for pre in _PATH_ALLOW_PREFIXES):
            return f"path '{p}' is outside the read-only allow-list ({', '.join(_PATH_ALLOW_PREFIXES)})"
    if not saw_path:
        return "a path argument is required"
    return None


# ---------------------------------------------------------------------------
# Rule table — binary → policy. Keep in sync with the agent's embedded copy.
# ---------------------------------------------------------------------------
_ANY = {"kind": "any"}


def _flags(*allowed, reject=None):
    return {"kind": "flags", "allowed": set(allowed), "reject": set(reject or [])}


def _subs(*allowed, reject=None):
    return {"kind": "subs", "allowed": set(allowed), "reject": set(reject or [])}


_PATHS = {"kind": "paths"}

RULES = {
    "uptime": _ANY,
    "uname": _ANY,
    "lscpu": _ANY,
    "lsmem": _ANY,
    "nproc": _ANY,
    "hostnamectl": _ANY,
    "who": _ANY,
    "w": _ANY,
    "id": _ANY,
    "date": _ANY,
    "sensors": _ANY,
    "nvidia-smi": _ANY,
    "vmstat": _ANY,
    "iostat": _ANY,
    "mpstat": _ANY,
    "free":  _flags("-b", "-h", "-m", "-g", "-k", "-t", "-w", "--si", "-s", "-c"),
    "df":    _flags("-h", "-i", "-B1", "-B", "-x", "-a", "-T", "-l", "--output", "-P"),
    "lsblk": _flags("-f", "-o", "-a", "-b", "-p", "-J", "-l", "-t", "-m", "-S", "-d", "-n"),
    "ps":    _flags("-e", "-o", "-A", "--sort", "-f", "-F", "-l", "aux", "-u", "-H", "-p", "auxww"),
    "top":   _flags("-b", "-n", "-o", "-1", "-H"),
    "ss":    _flags("-t", "-u", "-l", "-n", "-p", "-s", "-a", "-4", "-6", "-x", "-m", "-i"),
    "last":  _flags("-n", "-a", "-i", "-x", "-F"),
    "lsof":  _flags("-i", "-n", "-P", "-p", "-u"),
    "ip":    _subs("addr", "route", "link", "a", "r", "l", "neigh", "-s", "-br",
                   reject=("set", "add", "del", "delete", "flush", "change", "replace")),
    "dmesg": _flags("--level", "-T", "--since", "-l", "-x", "-H", "-k", "-P", "--color"),
    "journalctl": _flags("-u", "-n", "--since", "--until", "-p", "--no-pager",
                         "-k", "-b", "-r", "-o", "--unit", "-x", "-e",
                         reject=("-f", "--follow")),
    "systemctl": _subs("status", "list-units", "list-timers", "list-sockets",
                       "show", "is-active", "is-failed", "is-enabled", "cat",
                       "list-dependencies", "--failed",
                       reject=("start", "stop", "restart", "reload", "enable",
                               "disable", "mask", "unmask", "kill", "isolate",
                               "set-property", "edit", "reset-failed")),
    "docker": _subs("ps", "inspect", "logs", "stats", "images", "system",
                    "version", "info", "top", "port", "df",
                    reject=("run", "exec", "rm", "rmi", "stop", "start", "kill",
                            "restart", "build", "pull", "push", "create", "commit",
                            "cp", "prune", "network", "volume", "compose")),
    "vgs": _flags("-o", "--noheadings", "--units", "-a"),
    "lvs": _flags("-o", "--noheadings", "--units", "-a"),
    "pvs": _flags("-o", "--noheadings", "--units", "-a"),
    "zpool": _subs("status", "list", "iostat", "get", "history",
                   reject=("create", "destroy", "add", "remove", "attach", "detach",
                           "scrub", "clear", "offline", "online", "replace")),
    "zfs": _subs("list", "get",
                 reject=("create", "destroy", "set", "rename", "snapshot", "rollback",
                         "clone", "mount", "unmount", "send", "receive")),
    # File readers — path-restricted.
    "cat":  _PATHS,
    "head": _PATHS,
    "tail": _PATHS,   # tail -f is rejected below (flag check inside paths)
    "ls":   _PATHS,
    "du":   _PATHS,
    "find": _PATHS,
    "stat": _PATHS,
    "wc":   _PATHS,
    "readlink": _PATHS,
}


def validate_argv(argv):
    """Validate an already-split argv. Returns (ok: bool, reason: str)."""
    if not argv:
        return (False, "empty command")
    binary = os.path.basename(argv[0])
    args = argv[1:]

    rule = RULES.get(binary)
    if rule is None:
        return (False, f"'{binary}' is not on the read-only whitelist")

    kind = rule["kind"]
    if kind == "any":
        err = None
    elif kind == "flags":
        err = _check_flags(args, rule["allowed"], rule.get("reject"))
    elif kind == "subs":
        err = _check_subcommands(args, rule["allowed"], rule.get("reject"))
    elif kind == "paths":
        # tail/head follow-mode is a hang, not a mutation, but reject it anyway.
        if binary == "tail" and any(t in ("-f", "-F", "--follow") for t in args):
            return (False, "tail --follow is not permitted")
        err = _check_paths(args)
    else:  # pragma: no cover
        err = f"unknown rule kind for '{binary}'"

    if err:
        return (False, err)
    return (True, "ok")


def validate_command(command):
    """Parse a command string with shlex and validate. Returns (ok, reason, argv).

    Any shell metacharacter that survives shlex as a separate token (``;`` ``|``
    ``&`` ``$`` ``` `` ``` ``>`` ``<``) is rejected outright — there is no shell, so
    these could only be an attempt to smuggle one.
    """
    try:
        argv = shlex.split(command)
    except ValueError as e:
        return (False, f"could not parse command: {e}", None)
    if not argv:
        return (False, "empty command", None)
    # No shell runs, so these could only be an attempt to smuggle one in. Reject as
    # substrings (catches merged tokens like '-h;' from 'df -h; rm -rf /').
    _META = (";", "|", "&", ">", "<", "`", "$(", "\n", "\r", "$(", "&&", "||")
    for tok in argv:
        for m in _META:
            if m in tok:
                return (False, f"shell metacharacter '{m}' is not allowed (no shell)", None)
    ok, reason = validate_argv(argv)
    return (ok, reason, argv if ok else None)


# A compact human-readable summary embedded in the fleet_diag tool description so
# the model proposes only runnable commands.
WHITELIST_SUMMARY = (
    "Read-only only. Allowed binaries: uptime, uname, lscpu, nproc, free, df, lsblk, "
    "ps, top, ss, lsof, who, w, last, ip (addr/route/link, never 'set'), dmesg, "
    "journalctl (no -f), systemctl (status/list-*/show/is-*/cat only), docker "
    "(ps/inspect/logs/stats/images/system df), nvidia-smi, sensors, vgs/lvs/pvs, "
    "zpool/zfs (list/status/get), and file readers cat/head/tail/ls/du/find/stat "
    "restricted to paths under /proc /sys /var/log /etc (no secrets/keys). No pipes, "
    "no redirection, no shell. Mutating subcommands are denied."
)
