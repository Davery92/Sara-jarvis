#!/usr/bin/env python3
"""
sara-fleet-agent — a tiny, stdlib-only health agent for every Linux box.

It does two things (FLEET_DESIGN.md §4):

  1. Collects system telemetry every ~60s and pushes a compact snapshot to the
     Sara backend every `report_interval` seconds (default 300). Spools to disk
     when the backend is unreachable and backfills on reconnect.
  2. Long-polls the backend for read-only diagnostic commands, re-validates each
     against its OWN authoritative whitelist (the backend is untrusted input),
     executes it with shell=False, and posts the captured output back.

No third-party packages. No listening socket. Outbound HTTPS only. The systemd
unit (sara-fleet-agent.service) makes the filesystem read-only to this process
and strips privileges, so even a whitelist bug cannot mutate the machine.

Config: /etc/sara-agent/config.json  →  {"url": "...", "token": "...", "report_interval": 300}
"""

import json
import os
import re
import shlex
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

AGENT_VERSION = "1.0.0"
CONFIG_PATH = os.environ.get("SARA_AGENT_CONFIG", "/etc/sara-agent/config.json")
SPOOL_DIR = os.environ.get("SARA_AGENT_SPOOL", "/var/spool/sara-agent")
COLLECT_INTERVAL = 60          # seconds between telemetry samples
UPDATES_INTERVAL = 3600        # re-check pending updates hourly (expensive)
CMD_TIMEOUT = 30               # per-command execution timeout
OUTPUT_CAP = 64 * 1024         # cap captured stdout/stderr
HTTP_TIMEOUT = 40              # long-poll needs > wait seconds
MAX_SPOOL = 24                 # keep at most this many spooled reports


def log(msg):
    sys.stderr.write(f"[sara-fleet-agent] {msg}\n")
    sys.stderr.flush()


def now_iso():
    return datetime.now(timezone.utc).isoformat()


# ===========================================================================
# Embedded read-only whitelist — KEEP IN SYNC with backend
# app/services/fleet/whitelist.py (this is the authoritative copy on the box).
# ===========================================================================

_PATH_ALLOW_PREFIXES = ("/proc", "/sys", "/var/log", "/etc")
_PATH_DENY_SUBSTRINGS = ("secret", "credential", "token", "password", "passwd", "shadow")
_PATH_DENY_SUFFIXES = (".pem", ".key")
_META = (";", "|", "&", ">", "<", "`", "$(", "\n", "\r", "&&", "||")

_ANY = {"kind": "any"}
_PATHS = {"kind": "paths"}


def _flags(*a, reject=None):
    return {"kind": "flags", "reject": set(reject or [])}


def _subs(*a, reject=None):
    return {"kind": "subs", "allowed": set(a), "reject": set(reject or [])}


RULES = {
    "uptime": _ANY, "uname": _ANY, "lscpu": _ANY, "lsmem": _ANY, "nproc": _ANY,
    "hostnamectl": _ANY, "who": _ANY, "w": _ANY, "id": _ANY, "date": _ANY,
    "sensors": _ANY, "nvidia-smi": _ANY, "vmstat": _ANY, "iostat": _ANY, "mpstat": _ANY,
    "free": _flags(reject=None),
    "df": _flags(reject=None),
    "lsblk": _flags(reject=None),
    "ps": _flags(reject=None),
    "top": _flags(reject=("-d",)),
    "ss": _flags(reject=None),
    "last": _flags(reject=None),
    "lsof": _flags(reject=None),
    "ip": _subs("addr", "route", "link", "a", "r", "l", "neigh", "-s", "-br",
                reject=("set", "add", "del", "delete", "flush", "change", "replace")),
    "dmesg": _flags(reject=None),
    "journalctl": _flags(reject=("-f", "--follow")),
    "systemctl": _subs("status", "list-units", "list-timers", "list-sockets", "show",
                       "is-active", "is-failed", "is-enabled", "cat", "list-dependencies", "--failed",
                       reject=("start", "stop", "restart", "reload", "enable", "disable",
                               "mask", "unmask", "kill", "isolate", "set-property", "edit", "reset-failed")),
    "docker": _subs("ps", "inspect", "logs", "stats", "images", "system", "version",
                    "info", "top", "port", "df",
                    reject=("run", "exec", "rm", "rmi", "stop", "start", "kill", "restart",
                            "build", "pull", "push", "create", "commit", "cp", "prune",
                            "network", "volume", "compose")),
    "vgs": _flags(), "lvs": _flags(), "pvs": _flags(),
    "zpool": _subs("status", "list", "iostat", "get", "history",
                   reject=("create", "destroy", "add", "remove", "attach", "detach",
                           "scrub", "clear", "offline", "online", "replace")),
    "zfs": _subs("list", "get",
                 reject=("create", "destroy", "set", "rename", "snapshot", "rollback",
                         "clone", "mount", "unmount", "send", "receive")),
    "cat": _PATHS, "head": _PATHS, "tail": _PATHS, "ls": _PATHS, "du": _PATHS,
    "find": _PATHS, "stat": _PATHS, "wc": _PATHS, "readlink": _PATHS,
}


def _check_subs(args, allowed, reject):
    sub = None
    for tok in args:
        if not tok.startswith("-"):
            sub = tok
            break
    if sub is None:
        return "a subcommand is required"
    if sub in reject:
        return "subcommand '%s' is not permitted (read-only)" % sub
    if sub not in allowed:
        return "subcommand '%s' is not in the whitelist" % sub
    for tok in args:
        if tok in reject:
            return "'%s' is not permitted (read-only)" % tok
    return None


def _check_paths(args):
    saw = False
    for tok in args:
        if tok.startswith("-"):
            if tok in ("-exec", "-execdir", "-delete", "-fprint", "-ok", "-okdir"):
                return "'%s' is not permitted" % tok
            continue
        saw = True
        if not tok.startswith("/"):
            return "path '%s' must be absolute" % tok
        real = os.path.realpath(tok)
        low = real.lower()
        if any(s in low for s in _PATH_DENY_SUBSTRINGS):
            return "path '%s' looks sensitive — denied" % tok
        if any(low.endswith(sfx) for sfx in _PATH_DENY_SUFFIXES):
            return "path '%s' looks like a key — denied" % tok
        if real.startswith("/etc/shadow") or real.startswith("/etc/ssh/") or real.startswith("/etc/sara-agent"):
            return "path '%s' is denied" % tok
        if real.startswith("/proc/") and real.endswith("/environ"):
            return "path '%s' would leak environment — denied" % tok
        if not any(real == p or real.startswith(p + "/") for p in _PATH_ALLOW_PREFIXES):
            return "path '%s' is outside the read-only allow-list" % tok
    if not saw:
        return "a path argument is required"
    return None


def validate_argv(argv):
    if not argv:
        return (False, "empty command")
    binary = os.path.basename(argv[0])
    args = argv[1:]
    rule = RULES.get(binary)
    if rule is None:
        return (False, "'%s' is not on the read-only whitelist" % binary)
    kind = rule["kind"]
    if kind == "any":
        return (True, "ok")
    if kind == "flags":
        for tok in args:
            base = tok.split("=", 1)[0]
            if tok in rule["reject"] or base in rule["reject"]:
                return (False, "flag '%s' is not permitted (read-only)" % tok)
        return (True, "ok")
    if kind == "subs":
        err = _check_subs(args, rule["allowed"], rule["reject"])
        return (err is None, err or "ok")
    if kind == "paths":
        if binary == "tail" and any(t in ("-f", "-F", "--follow") for t in args):
            return (False, "tail --follow is not permitted")
        err = _check_paths(args)
        return (err is None, err or "ok")
    return (False, "unknown rule")


def validate_command(command):
    try:
        argv = shlex.split(command)
    except ValueError as e:
        return (False, "could not parse: %s" % e, None)
    if not argv:
        return (False, "empty command", None)
    for tok in argv:
        for m in _META:
            if m in tok:
                return (False, "shell metacharacter '%s' is not allowed" % m, None)
    ok, reason = validate_argv(argv)
    return (ok, reason, argv if ok else None)


# ===========================================================================
# Telemetry collection
# ===========================================================================

def _read(path):
    try:
        with open(path) as f:
            return f.read()
    except Exception:
        return ""


def _run(argv, timeout=5):
    try:
        p = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                           timeout=timeout, shell=False)
        return p.stdout.decode("utf-8", "replace")
    except Exception:
        return ""


def _which(binary):
    for d in os.environ.get("PATH", "/usr/bin:/bin:/usr/sbin:/sbin").split(":"):
        cand = os.path.join(d, binary)
        if os.path.exists(cand):
            return cand
    return None


class Collector:
    """Samples telemetry; keeps deltas (CPU %, net rates) between samples."""

    def __init__(self):
        self._prev_cpu = None
        self._prev_net = None
        self._prev_net_t = None
        self._updates_cache = None
        self._updates_checked = 0
        self._machine_id = (_read("/etc/machine-id").strip()
                            or _read("/var/lib/dbus/machine-id").strip() or "unknown")

    # --- CPU % from /proc/stat delta ---
    def _cpu_pct(self):
        line = _read("/proc/stat").splitlines()
        if not line:
            return None
        parts = line[0].split()
        if parts[0] != "cpu":
            return None
        vals = [int(x) for x in parts[1:]]
        idle = vals[3] + (vals[4] if len(vals) > 4 else 0)
        total = sum(vals)
        pct = None
        if self._prev_cpu is not None:
            dt = total - self._prev_cpu[0]
            di = idle - self._prev_cpu[1]
            if dt > 0:
                pct = round(100.0 * (dt - di) / dt, 1)
        self._prev_cpu = (total, idle)
        return pct

    # --- memory ---
    def _mem(self):
        info = {}
        for ln in _read("/proc/meminfo").splitlines():
            k, _, rest = ln.partition(":")
            info[k.strip()] = int(rest.strip().split()[0]) * 1024  # kB → bytes
        total = info.get("MemTotal", 0)
        avail = info.get("MemAvailable", info.get("MemFree", 0))
        used = total - avail
        swap_total = info.get("SwapTotal", 0)
        swap_free = info.get("SwapFree", 0)
        swap_used = swap_total - swap_free
        return {
            "total": total, "used": used, "available": avail,
            "used_pct": round(used / total * 100, 1) if total else None,
            "swap_total": swap_total, "swap_used": swap_used,
            "swap_pct": round(swap_used / swap_total * 100, 1) if swap_total else 0.0,
        }

    # --- disks via statvfs over /proc/mounts ---
    def _disks(self):
        seen = set()
        out = []
        skip_fs = {"tmpfs", "devtmpfs", "squashfs", "overlay", "proc", "sysfs",
                   "cgroup", "cgroup2", "devpts", "mqueue", "efivarfs", "autofs",
                   "fuse.gvfsd-fuse", "tracefs", "debugfs", "ramfs", "nsfs", "binfmt_misc"}
        for ln in _read("/proc/mounts").splitlines():
            f = ln.split()
            if len(f) < 3:
                continue
            dev, mount, fstype = f[0], f[1], f[2]
            if fstype in skip_fs or mount in seen:
                continue
            if mount.startswith(("/proc", "/sys", "/dev", "/run")):
                continue
            seen.add(mount)
            try:
                st = os.statvfs(mount)
            except Exception:
                continue
            size = st.f_blocks * st.f_frsize
            avail = st.f_bavail * st.f_frsize
            used = size - (st.f_bfree * st.f_frsize)
            if size == 0:
                continue
            inode_pct = None
            if st.f_files:
                inode_pct = round((st.f_files - st.f_ffree) / st.f_files * 100, 1)
            out.append({
                "mount": mount, "size": size, "used": used, "avail": avail,
                "used_pct": round(used / size * 100, 1),
                "inode_pct": inode_pct,
            })
        return out

    # --- network rates from /proc/net/dev delta ---
    def _net(self):
        cur = {}
        for ln in _read("/proc/net/dev").splitlines():
            if ":" not in ln:
                continue
            iface, _, rest = ln.partition(":")
            iface = iface.strip()
            if iface == "lo" or iface.startswith(("veth", "docker", "br-")):
                continue
            cols = rest.split()
            if len(cols) < 9:
                continue
            cur[iface] = (int(cols[0]), int(cols[8]))  # rx_bytes, tx_bytes
        t = time.time()
        rx_bps = tx_bps = 0.0
        if self._prev_net is not None and self._prev_net_t:
            dt = t - self._prev_net_t
            if dt > 0:
                for iface, (rx, tx) in cur.items():
                    prx, ptx = self._prev_net.get(iface, (rx, tx))
                    rx_bps += max(0, rx - prx) / dt
                    tx_bps += max(0, tx - ptx) / dt
        self._prev_net = cur
        self._prev_net_t = t
        return {"rx_bps": round(rx_bps), "tx_bps": round(tx_bps),
                "default_iface": self._default_iface()}

    def _default_iface(self):
        for ln in _read("/proc/net/route").splitlines()[1:]:
            f = ln.split()
            if len(f) > 1 and f[1] == "00000000":
                return f[0]
        return None

    # --- temperatures from /sys/class/thermal ---
    def _temps(self):
        temps = {}
        base = "/sys/class/thermal"
        try:
            zones = os.listdir(base)
        except Exception:
            zones = []
        for z in zones:
            if not z.startswith("thermal_zone"):
                continue
            raw = _read(os.path.join(base, z, "temp")).strip()
            tp = _read(os.path.join(base, z, "type")).strip() or z
            try:
                c = int(raw) / 1000.0
                if 0 < c < 150:
                    temps[tp] = round(c, 1)
            except Exception:
                pass
        return temps

    # --- systemd failed units + reboot flag ---
    def _systemd(self):
        failed_names = []
        out = _run(["systemctl", "--failed", "--plain", "--no-legend", "--no-pager"], timeout=8)
        for ln in out.splitlines():
            toks = ln.strip().split()
            if toks:
                failed_names.append(toks[0])
        reboot = os.path.exists("/var/run/reboot-required") or os.path.exists("/run/reboot-required")
        return failed_names, reboot

    # --- pending updates (cached hourly) ---
    def _updates(self):
        if self._updates_cache is not None and (time.time() - self._updates_checked) < UPDATES_INTERVAL:
            return self._updates_cache
        count = None
        if _which("apt-get"):
            out = _run(["apt-get", "-s", "dist-upgrade"], timeout=30)
            count = sum(1 for ln in out.splitlines() if ln.startswith("Inst "))
        elif _which("dnf"):
            out = _run(["dnf", "-q", "check-update"], timeout=30)
            count = sum(1 for ln in out.splitlines() if ln and ln[0].isalnum())
        self._updates_cache = count
        self._updates_checked = time.time()
        return count

    # --- GPU (NVIDIA / Jetson) ---
    def _gpu(self):
        gpus = []
        if _which("nvidia-smi"):
            out = _run(["nvidia-smi",
                        "--query-gpu=name,memory.total,memory.used,utilization.gpu,temperature.gpu",
                        "--format=csv,noheader,nounits"], timeout=8)
            for ln in out.splitlines():
                cols = [c.strip() for c in ln.split(",")]
                if len(cols) >= 5:
                    gpus.append({"name": cols[0], "mem_total_mb": cols[1], "mem_used_mb": cols[2],
                                 "util_pct": cols[3], "temp_c": cols[4]})
        return gpus

    # --- docker (only if sara-agent is in the docker group) ---
    def _docker(self):
        if not _which("docker"):
            return None
        out = _run(["docker", "ps", "-a", "--format", "{{.Status}}"], timeout=8)
        if not out:
            return None
        running = exited = 0
        unhealthy = []
        for ln in out.splitlines():
            s = ln.strip().lower()
            if s.startswith("up"):
                running += 1
                if "unhealthy" in s:
                    unhealthy.append(ln.strip())
            elif s.startswith("exited"):
                exited += 1
        return {"running": running, "exited": exited, "unhealthy": unhealthy}

    def _top(self):
        out = _run(["ps", "-eo", "pid,pcpu,pmem,comm", "--sort=-pcpu"], timeout=6)
        lines = [l.strip() for l in out.splitlines()[1:6] if l.strip()]
        out_m = _run(["ps", "-eo", "pid,pcpu,pmem,comm", "--sort=-pmem"], timeout=6)
        lines_m = [l.strip() for l in out_m.splitlines()[1:6] if l.strip()]
        return lines, lines_m

    def collect(self):
        os_rel = {}
        for ln in _read("/etc/os-release").splitlines():
            k, _, v = ln.partition("=")
            os_rel[k] = v.strip().strip('"')
        loadavg = _read("/proc/loadavg").split()
        uptime = _read("/proc/uptime").split()
        failed_names, reboot = self._systemd()
        top_cpu, top_mem = self._top()
        net = self._net()
        temps = self._temps()
        mem = self._mem()

        snap = {
            "agent_version": AGENT_VERSION,
            "machine_id": self._machine_id,
            "hostname": socket.gethostname(),
            "os": os_rel.get("PRETTY_NAME") or os_rel.get("NAME"),
            "kernel": os.uname().release,
            "arch": os.uname().machine,
            "uptime_seconds": int(float(uptime[0])) if uptime else None,
            "cpu_count": os.cpu_count(),
            "cpu_pct": self._cpu_pct(),
            "load1": float(loadavg[0]) if loadavg else None,
            "load5": float(loadavg[1]) if len(loadavg) > 1 else None,
            "load15": float(loadavg[2]) if len(loadavg) > 2 else None,
            "mem": mem,
            "disks": self._disks(),
            "net": net,
            "net_rx_bps": net.get("rx_bps"),
            "net_tx_bps": net.get("tx_bps"),
            "temps": temps,
            "temp_max_c": max(temps.values()) if temps else None,
            "failed_units": len(failed_names),
            "failed_unit_names": failed_names,
            "reboot_required": reboot,
            "updates_pending": self._updates(),
            "gpu": self._gpu(),
            "docker": self._docker(),
            "sessions": len([l for l in _run(["who"], timeout=4).splitlines() if l.strip()]),
            "top_cpu": top_cpu,
            "top_mem": top_mem,
            "ts": now_iso(),
        }
        return snap


# ===========================================================================
# HTTP + backend client
# ===========================================================================

class Backend:
    def __init__(self, url, token):
        self.url = url.rstrip("/")
        self.token = token

    def _request(self, method, path, body=None, timeout=HTTP_TIMEOUT):
        url = self.url + path
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Authorization", "Bearer " + self.token)
        req.add_header("Content-Type", "application/json")
        # A real User-Agent: WAFs/Cloudflare in front of the backend 403 the default
        # "Python-urllib/x.y". Keep this set on every request.
        req.add_header("User-Agent", "sara-fleet-agent/" + AGENT_VERSION)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", "replace")
            return json.loads(raw) if raw else {}

    def report(self, snapshot, spool=None):
        return self._request("POST", "/api/fleet/report",
                             {"snapshot": snapshot, "spool": spool or []})

    def poll_commands(self, wait=25):
        return self._request("GET", "/api/fleet/commands?wait=%d" % wait, timeout=wait + 15)

    def post_result(self, cmd_id, result):
        return self._request("POST", "/api/fleet/commands/%d/result" % cmd_id, result)


# ===========================================================================
# Spool (offline report buffer)
# ===========================================================================

def spool_add(snapshot):
    try:
        os.makedirs(SPOOL_DIR, exist_ok=True)
        files = sorted(f for f in os.listdir(SPOOL_DIR) if f.endswith(".json"))
        while len(files) >= MAX_SPOOL:
            os.remove(os.path.join(SPOOL_DIR, files.pop(0)))
        fname = "%d.json" % int(time.time() * 1000)
        with open(os.path.join(SPOOL_DIR, fname), "w") as f:
            json.dump(snapshot, f)
    except Exception as e:
        log("spool write failed: %s" % e)


def spool_drain():
    try:
        files = sorted(f for f in os.listdir(SPOOL_DIR) if f.endswith(".json"))
    except Exception:
        return []
    out = []
    for f in files:
        try:
            with open(os.path.join(SPOOL_DIR, f)) as fh:
                out.append(json.load(fh))
        except Exception:
            pass
    return out


def spool_clear():
    try:
        for f in os.listdir(SPOOL_DIR):
            if f.endswith(".json"):
                os.remove(os.path.join(SPOOL_DIR, f))
    except Exception:
        pass


# ===========================================================================
# Loops
# ===========================================================================

def report_loop(backend, collector, interval):
    backoff = 10
    while True:
        try:
            snap = collector.collect()
        except Exception as e:
            log("collect failed: %s" % e)
            time.sleep(interval)
            continue
        try:
            spooled = spool_drain()
            backend.report(snap, spool=spooled)
            if spooled:
                spool_clear()
            backoff = 10
            time.sleep(interval)
        except Exception as e:
            log("report failed (%s), spooling; backoff %ds" % (e, backoff))
            spool_add(snap)
            time.sleep(backoff)
            backoff = min(backoff * 2, 300)


def command_loop(backend):
    while True:
        try:
            cmds = backend.poll_commands(wait=25)
        except urllib.error.URLError:
            time.sleep(15)
            continue
        except Exception as e:
            log("poll failed: %s" % e)
            time.sleep(15)
            continue
        if not cmds:
            continue
        for cmd in cmds:
            _handle_command(backend, cmd)


def _handle_command(backend, cmd):
    cmd_id = cmd.get("id")
    argv = cmd.get("argv") or []
    # If the server sent a raw string, re-parse; normally it's already argv.
    if isinstance(argv, str):
        ok, reason, parsed = validate_command(argv)
        argv = parsed or []
    else:
        ok, reason = validate_argv(argv)
    if not ok:
        log("DENIED cmd %s: %s (%s)" % (cmd_id, argv, reason))
        _safe_result(backend, cmd_id, {"denied": True, "denied_reason": reason})
        return
    try:
        p = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           timeout=CMD_TIMEOUT, shell=False)
        _safe_result(backend, cmd_id, {
            "exit_code": p.returncode,
            "stdout": p.stdout.decode("utf-8", "replace")[:OUTPUT_CAP],
            "stderr": p.stderr.decode("utf-8", "replace")[:OUTPUT_CAP],
        })
    except subprocess.TimeoutExpired:
        _safe_result(backend, cmd_id, {"exit_code": 124, "stderr": "timed out after %ds" % CMD_TIMEOUT})
    except Exception as e:
        _safe_result(backend, cmd_id, {"exit_code": 1, "stderr": str(e)})


def _safe_result(backend, cmd_id, result):
    try:
        backend.post_result(cmd_id, result)
    except Exception as e:
        log("post_result failed for %s: %s" % (cmd_id, e))


# ===========================================================================
# main
# ===========================================================================

def load_config():
    with open(CONFIG_PATH) as f:
        cfg = json.load(f)
    if not cfg.get("url") or not cfg.get("token"):
        raise SystemExit("config missing 'url' or 'token'")
    return cfg


def main():
    try:
        cfg = load_config()
    except Exception as e:
        log("cannot start: %s" % e)
        sys.exit(1)

    interval = int(cfg.get("report_interval", 300))
    backend = Backend(cfg["url"], cfg["token"])
    collector = Collector()
    log("starting v%s → %s (interval %ds, machine %s)"
        % (AGENT_VERSION, backend.url, interval, collector._machine_id))

    t = threading.Thread(target=command_loop, args=(backend,), daemon=True)
    t.start()
    # Report loop runs in the main thread (keeps the process alive).
    report_loop(backend, collector, interval)


if __name__ == "__main__":
    main()
