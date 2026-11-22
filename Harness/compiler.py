# SPDX-License-Identifier: MIT
"""Compiler invocation for timing.

The timed process is the compiler proper (cc1plus), launched with exactly the
command line the g++ driver would use (taken from `g++ -###`). Timing cc1plus
directly lets the harness give the process that does the work high priority (a
child of a high-priority driver would run at normal priority on Windows) and
removes driver start-up from the external wall time. The primary metric,
-ftime-report TOTAL, is printed by cc1plus itself either way.
"""
from __future__ import annotations
import os
import pathlib
import re
import shlex
import subprocess
import time

import deps

HERE = pathlib.Path(__file__).resolve().parent
PROJECT = HERE.parent

# The protocol compiler is chosen explicitly per session (campaign.py --gxx, recorded in
# the session file); this default only serves development probes.
GXX = os.environ.get("RB_GXX", "C:/msys64/home/kacha/gcc-16-install/bin/g++.exe")
UCRT_BIN = os.environ.get("RB_UCRT_BIN", "C:/msys64/ucrt64/bin")
BASE_FLAGS = ["-std=c++26", "-freflection", f"-B{UCRT_BIN}/"]
MODES = {
    "syntax": ["-fsyntax-only"],
    "full": ["-O2", "-c"],
}
HIGH = getattr(subprocess, "HIGH_PRIORITY_CLASS", 0)

# -ftime-report rows kept per run (name in the report -> column suffix). Rows with a
# leading "|" are nested timers: their time is already inside a phase. GCC omits a row
# whose wall time is under ~5 ms and whose GGC is under 1 MiB; such a row is recorded
# as 0.0 (below the print threshold), not as missing.
TIMERS = {
    "phase setup": "setup",
    "phase parsing": "parsing",
    "phase lang. deferred": "deferred",
    "phase opt and generate": "optgen",
    "template instantiation": "tmpl_inst",
    "constant expression evaluation": "consteval",
    "|name lookup": "name_lookup",
    "|overload resolution": "overload",
    "TOTAL": "total",
}
_ROW = re.compile(r"^\s*(.+?)\s*:\s*([0-9]+\.[0-9]+)\s*\(\s*\d+%\)\s+([0-9.]+)([kMG]?)\s")
_TOTAL = re.compile(r"^\s*TOTAL\s*:\s*([0-9]+\.[0-9]+)\s+([0-9.]+)([kMG]?)")
_UNIT_MB = {"": 1 / 2**20, "k": 1 / 2**10, "M": 1.0, "G": 2.0**10}


def env(gxx: str = GXX) -> dict:
    e = dict(os.environ)
    e["PATH"] = UCRT_BIN + os.pathsep + str(pathlib.Path(gxx).parent) + os.pathsep + e.get("PATH", "")
    return e


def include_flags(extra_dirs) -> list[str]:
    dirs = [PROJECT / "Include", *extra_dirs, *deps.include_dirs()]
    return [f"-I{d}" for d in dirs]


def driver_command(tu: pathlib.Path, mode: str, flags, extra_dirs, gxx: str = GXX,
                   report: bool = True, base=tuple(BASE_FLAGS)) -> list[str]:
    out = ["-o", os.devnull] if mode == "full" else []
    return [gxx, *base, *MODES[mode], *flags, *include_flags(extra_dirs),
            *(["-ftime-report"] if report else []), *out, str(tu)]


_cache: dict[tuple, list[str]] = {}


def cc1plus_command(tu: pathlib.Path, mode: str, flags=(), extra_dirs=(), gxx: str = GXX,
                    report: bool = True, base=tuple(BASE_FLAGS)) -> list[str]:
    """The driver's own cc1plus command line for this compile (cached). `base` replaces
    the protocol's standard and reflection flags (pfrprobe.py compiles other modes)."""
    key = (gxx, str(tu), mode, tuple(flags), tuple(map(str, extra_dirs)), report, tuple(base))
    if key in _cache:
        return _cache[key]
    proc = subprocess.run([*driver_command(tu, mode, flags, extra_dirs, gxx, report, base), "-###"],
                          capture_output=True, text=True, env=env(gxx))
    lines = [ln for ln in proc.stderr.splitlines() if "cc1plus" in ln and ln.lstrip().startswith('"')]
    if len(lines) != 1:
        raise RuntimeError(f"expected one cc1plus line from -###, got {len(lines)}:\n{proc.stderr}")
    args = shlex.split(lines[0])
    if mode == "full":
        # cc1plus writes assembly; the driver would hand it to `as`. Discard it instead:
        # the timed work (cc1plus, including code generation) is unchanged.
        i = args.index("-o")
        args[i + 1] = "NUL" if os.name == "nt" else "/dev/null"
    _cache[key] = args
    return args


def parse_report(stderr: str) -> dict:
    out = {}
    for line in stderr.splitlines():
        t = _TOTAL.match(line)
        if t:
            out["ft_total_s"] = float(t.group(1))
            out["ggc_total_mb"] = float(t.group(2)) * _UNIT_MB[t.group(3)]
            continue
        m = _ROW.match(line)
        if m and m.group(1) in TIMERS:
            col = TIMERS[m.group(1)]
            out[f"ft_{col}_s"] = float(m.group(2))
            out[f"ggc_{col}_mb"] = float(m.group(3)) * _UNIT_MB[m.group(4)]
    if "ft_total_s" in out:
        for col in TIMERS.values():
            out.setdefault(f"ft_{col}_s", 0.0)
            out.setdefault(f"ggc_{col}_mb", 0.0)
    return out


# OS counters of each compile, read from the exited process (columns os_<name>).
OS_COUNTERS = ("user_s", "kernel_s", "cycles", "peak_ws_mb", "peak_commit_mb", "page_faults")
# The longest planned compile takes about 2 minutes (Boost.PFR's C++17 path at N = 4,000).
COMPILE_TIMEOUT_S = 1800


def _process_counters(handle: int) -> dict:
    """CPU time (user, kernel; Windows counts it in 15.6 ms ticks), CPU cycles, peak working
    set, peak commit and page faults of an exited child, read through its still-open
    handle after the timed interval. Empty when unavailable; never raises."""
    if os.name != "nt":
        return {}
    try:
        import ctypes
        from ctypes import wintypes

        class Counters(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                        ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                        ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]

        k32 = ctypes.WinDLL("kernel32")
        psapi = ctypes.WinDLL("psapi")
        h = wintypes.HANDLE(handle)
        out = {}
        created, exited, kernel, user = (wintypes.FILETIME() for _ in range(4))
        if k32.GetProcessTimes(h, ctypes.byref(created), ctypes.byref(exited),
                               ctypes.byref(kernel), ctypes.byref(user)):
            seconds = lambda f: ((f.dwHighDateTime << 32) | f.dwLowDateTime) / 1e7
            out["os_user_s"], out["os_kernel_s"] = seconds(user), seconds(kernel)
        cycles = ctypes.c_uint64()
        if k32.QueryProcessCycleTime(h, ctypes.byref(cycles)):
            out["os_cycles"] = float(cycles.value)
        mem = Counters()
        mem.cb = ctypes.sizeof(Counters)
        if psapi.GetProcessMemoryInfo(h, ctypes.byref(mem), mem.cb):
            out["os_peak_ws_mb"] = round(mem.PeakWorkingSetSize / 2**20, 2)
            out["os_peak_commit_mb"] = round(mem.PeakPagefileUsage / 2**20, 2)
            out["os_page_faults"] = float(mem.PageFaultCount)
        return out
    except Exception:  # noqa: BLE001 — the counters are a by-product; a timed compile never fails on them
        return {}


def compile_once(cmd: list[str], priority: int = HIGH, gxx: str = GXX, report: bool = True,
                 timeout: float = COMPILE_TIMEOUT_S) -> dict:
    # Popen + communicate is what subprocess.run does; the handle stays open for the counters.
    t0 = time.perf_counter()
    with subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                          creationflags=priority, env=env(gxx)) as proc:
        try:
            _, stderr = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate()
            raise RuntimeError(f"compile timed out after {timeout:.0f} s:\n{' '.join(cmd)}") from None
        wall = time.perf_counter() - t0
        counters = _process_counters(int(proc._handle)) if os.name == "nt" else {}
    if proc.returncode != 0:
        raise RuntimeError(f"compile failed (rc={proc.returncode}):\n{' '.join(cmd)}\n{stderr[-4000:]}")
    rep = parse_report(stderr)
    if report and "ft_total_s" not in rep:
        raise RuntimeError("-ftime-report TOTAL missing (format or locale changed?):\n" + stderr[-2000:])
    rep["wall_s"] = round(wall, 4)
    rep.update(counters)
    rep["_stderr"] = stderr
    return rep


def version(gxx: str = GXX) -> str:
    out = subprocess.run([gxx, "--version"], capture_output=True, text=True, env=env(gxx))
    return out.stdout.splitlines()[0] if out.stdout else "unknown"
