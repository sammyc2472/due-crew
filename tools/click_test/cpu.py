"""CPU time of Anki (this process, every thread) and everything it started
(QtWebEngine's GPU and renderer processes): psutil when it's installed,
else /proc. percent() is CPU seconds over wall seconds, as % of one core."""

import os
import time

try:
    import psutil
except ImportError:
    psutil = None

HOW = "psutil" if psutil is not None else "/proc"
TICK = os.sysconf("SC_CLK_TCK") if hasattr(os, "sysconf") else 100


def _kids_proc(root):
    """{pid: (kind, cpu seconds)} of root's descendants, from /proc."""
    parent, info = {}, {}
    for d in os.listdir("/proc"):
        if not d.isdigit():
            continue
        try:
            with open(f"/proc/{d}/stat") as f:
                rest = f.read().rsplit(")", 1)[1].split()
            with open(f"/proc/{d}/cmdline", "rb") as f:
                cmd = f.read().decode("utf-8", "replace")
        except OSError:
            continue
        pid = int(d)
        parent[pid] = int(rest[1])
        info[pid] = (_kind(cmd), (int(rest[11]) + int(rest[12])) / TICK)
    out = {}
    for pid in info:
        p, seen = parent.get(pid), 0
        while p and p != root and seen < 20:
            p, seen = parent.get(p), seen + 1
        if p == root:
            out[pid] = info[pid]
    return out


def _kids_psutil(root):
    out = {}
    for c in psutil.Process(root).children(recursive=True):
        try:
            t = c.cpu_times()
            out[c.pid] = (_kind(" ".join(c.cmdline())), t.user + t.system)
        except psutil.Error:
            continue
    return out


def _kind(cmd):
    if "QtWebEngineProcess" not in cmd:
        return "other"
    for k in ("renderer", "gpu-process", "utility", "zygote"):
        if f"--type={k}" in cmd:
            return k.replace("-process", "")
    return "webengine"


def sample():
    me = os.getpid()
    t = os.times()
    kids = _kids_psutil(me) if psutil is not None else _kids_proc(me)
    return {"at": time.perf_counter(), "anki": t.user + t.system, "kids": kids}


def percent(a, b):
    """Between two samples: % of one core, Anki's own and each kind of child's."""
    secs = max(1e-6, b["at"] - a["at"])
    out = {"secs": round(secs, 1), "anki": round((b["anki"] - a["anki"]) / secs * 100, 1)}
    by = {}
    for pid, (kind, t) in b["kids"].items():
        was = a["kids"].get(pid, (kind, 0.0))[1]
        by[kind] = by.get(kind, 0.0) + max(0.0, t - was)
    for kind, t in sorted(by.items()):
        out[kind] = round(t / secs * 100, 1)
    out["total"] = round(out["anki"] + sum(t / secs * 100 for t in by.values()), 1)
    return out
