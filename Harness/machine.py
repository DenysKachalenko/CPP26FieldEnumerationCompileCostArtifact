# SPDX-License-Identifier: MIT
"""Measurement environment: CPU topology (performance cores), the code fingerprint,
and a snapshot of the machine, toolchains and pins recorded with every session.

    python machine.py [GXX ...]     # print the snapshot as JSON
"""
from __future__ import annotations
import ctypes
import datetime
import hashlib
import json
import os
import pathlib
import platform
import struct
import subprocess
import sys
import tempfile
import time

import numpy
import psutil

import compiler
import deps

PROJECT = pathlib.Path(__file__).resolve().parent.parent
# Everything that determines what a session measures: the code that generates, checks,
# compiles and times the sources, the headers they include, and the library pins. Analysis
# code (stats, papernumbers, figures, paperlint) is left out, so it can change between and
# during sessions without making a session unresumable.
MEASUREMENT_MODULES = ("arms", "campaign", "compiler", "deps", "generate", "machine", "overload",
                       "plan", "preflight")
FINGERPRINT_GLOBS = [f"Harness/{m}.py" for m in MEASUREMENT_MODULES] + ["Include/RB/*", "Deps.json"]
# Host packages whose DLLs cc1plus loads at run time (MSYS2 UCRT64).
DLL_PACKAGES = ["mingw-w64-ucrt-x86_64-gmp", "mingw-w64-ucrt-x86_64-mpfr", "mingw-w64-ucrt-x86_64-mpc",
                "mingw-w64-ucrt-x86_64-isl", "mingw-w64-ucrt-x86_64-zstd", "mingw-w64-ucrt-x86_64-zlib",
                "mingw-w64-ucrt-x86_64-libiconv", "mingw-w64-ucrt-x86_64-libwinpthread",
                "mingw-w64-ucrt-x86_64-binutils"]


def core_layout() -> list[dict]:
    """Physical cores with their logical CPUs and efficiency class (Windows).
    On a hybrid CPU the performance cores have the highest efficiency class."""
    if os.name != "nt":
        return []
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    size = ctypes.c_ulong(0)
    k32.GetLogicalProcessorInformationEx(0, None, ctypes.byref(size))
    buf = ctypes.create_string_buffer(size.value)
    if not k32.GetLogicalProcessorInformationEx(0, buf, ctypes.byref(size)):
        raise OSError(ctypes.get_last_error(), "GetLogicalProcessorInformationEx failed")
    raw, cores, off = buf.raw, [], 0
    while off < size.value:
        rel, rec = struct.unpack_from("<II", raw, off)
        if rel == 0:  # RelationProcessorCore
            flags, eff = struct.unpack_from("<BB", raw, off + 8)
            group_count = struct.unpack_from("<H", raw, off + 8 + 22)[0]
            for g in range(group_count):
                mask, group = struct.unpack_from("<QH", raw, off + 8 + 24 + 16 * g)
                cpus = [64 * group + b for b in range(64) if mask >> b & 1]
                cores.append({"efficiency_class": eff, "smt": bool(flags & 1), "cpus": cpus})
        off += rec
    return cores


def performance_cpus() -> list[int]:
    cores = core_layout()
    if not cores:
        return []
    top = max(c["efficiency_class"] for c in cores)
    return sorted(cpu for c in cores if c["efficiency_class"] == top for cpu in c["cpus"])


def pin_to_performance_cores() -> list[int]:
    """Restrict this process (and so every compiler it launches) to the performance
    cores. Returns the CPU list, or [] when the CPU is not hybrid."""
    cores = core_layout()
    if not cores or len({c["efficiency_class"] for c in cores}) < 2:
        return []
    cpus = performance_cpus()
    psutil.Process().cpu_affinity(cpus)
    return cpus


def fingerprint() -> dict:
    """sha256 of every file that determines what a session measures, and one digest."""
    files = sorted({p for g in FINGERPRINT_GLOBS for p in PROJECT.glob(g) if p.is_file()})
    per = {str(p.relative_to(PROJECT)).replace("\\", "/"): _sha256(p) for p in files}
    digest = hashlib.sha256("".join(f"{k}={v}\n" for k, v in per.items()).encode()).hexdigest()
    return {"digest": digest, "files": per}


def _run(cmd) -> str:
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        return (out.stdout or out.stderr).strip()
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"unavailable: {exc}"


def _ps(command: str) -> str:
    return _run(["powershell.exe", "-NoProfile", "-Command", command])


def _sha256(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def compiler_record(gxx: str) -> dict:
    """Identity of one compiler: version, configure line, binary hashes and sizes."""
    with tempfile.TemporaryDirectory() as tmp:
        probe = pathlib.Path(tmp) / "probe.cpp"
        probe.write_text("int x;\n")
        # Flags every recorded compiler accepts (GCC 15 has no -freflection); the cc1plus
        # path does not depend on them.
        cc1 = pathlib.Path(compiler.cc1plus_command(
            probe, "syntax", gxx=gxx, base=("-std=c++20", f"-B{compiler.UCRT_BIN}/"))[0])
    drv = pathlib.Path(gxx)
    return {
        "driver": str(drv), "version": compiler.version(gxx),
        "configure": next((ln for ln in _run([str(drv), "-v"]).splitlines()
                           if ln.startswith("Configured with")), ""),
        "driver_sha256": _sha256(drv), "cc1plus": str(cc1), "cc1plus_sha256": _sha256(cc1),
        "cc1plus_bytes": cc1.stat().st_size,
    }


def _busiest(seconds: float) -> tuple[list, list]:
    """System load per CPU over `seconds`, and the processes using most CPU in that window."""
    procs = list(psutil.process_iter(["name", "pid"]))
    for p in procs:
        try:
            p.cpu_percent(None)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    load = psutil.cpu_percent(interval=seconds, percpu=True)
    usage = []
    for p in procs:
        if p.info["pid"] == 0:  # System Idle Process
            continue
        try:
            usage.append((p.cpu_percent(None) / psutil.cpu_count(), p.info["name"]))
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    usage.sort(reverse=True)
    return load, [{"name": n, "cpu_pct": round(u, 1)} for u, n in usage[:8]]


def snapshot(compilers: list[str] | None = None, sample_seconds: float = 5.0) -> dict:
    compilers = compilers or [compiler.GXX]
    load, busiest = _busiest(sample_seconds)
    pacman = pathlib.Path("C:/msys64/usr/bin/pacman.exe")
    git_head = _run(["git", "-C", str(PROJECT), "rev-parse", "HEAD"])
    git_dirty = _run(["git", "-C", str(PROJECT), "status", "--porcelain", "--", "."])
    return {
        "utc": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "os": {"platform": platform.platform(), "version": platform.version()},
        "cpu": {
            "name": _ps("(Get-CimInstance Win32_Processor).Name"),
            "logical": psutil.cpu_count(), "physical": psutil.cpu_count(logical=False),
            "cores": core_layout(), "performance_cpus": performance_cpus(),
        },
        "memory_gb": round(psutil.virtual_memory().total / 2**30, 1),
        "memory_available_gb": round(psutil.virtual_memory().available / 2**30, 1),
        "swap_used_gb": round(psutil.swap_memory().used / 2**30, 1),
        "power_plan": _run(["powercfg", "/getactivescheme"]),
        "defender_realtime": _ps("(Get-MpComputerStatus).RealTimeProtectionEnabled"),
        "load_percpu_pct": load,
        "load_total_pct": round(sum(load) / len(load), 1),
        "busiest_processes": busiest,
        "compilers": {g: compiler_record(g) for g in compilers},
        "assembler": _run([str(pathlib.Path(compiler.UCRT_BIN) / "as.exe"), "--version"]).splitlines()[0],
        "base_flags": compiler.BASE_FLAGS,
        "host_dll_packages": (_run([str(pacman), "-Q", *DLL_PACKAGES]).splitlines()
                              if pacman.is_file() else "pacman not found"),
        "deps": deps.pins_summary(),
        "fingerprint": fingerprint(),
        "python": {"version": sys.version.split()[0], "executable": sys.executable,
                   "numpy": numpy.__version__, "psutil": psutil.__version__},
        "project_git_head": git_head,
        "project_dirty_files": [ln for ln in git_dirty.splitlines() if ln.strip()],
    }


if __name__ == "__main__":
    print(json.dumps(snapshot(sys.argv[1:] or None), indent=2))
