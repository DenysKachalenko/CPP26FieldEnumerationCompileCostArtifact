# SPDX-License-Identifier: MIT
"""Checks that must pass before any timing.

1. Pins: every library tree matches its pinned archive.
2. Flags: every arm's flags reach the exact cc1plus command that is timed, and
   -fno-reflection really switches reflection off.
3. Oracles: value-level byte equality of every arm, for every flag set a timed arm uses
   (with the backend configuration the build reports checked against the expected one),
   on the scalar, rich and heterogeneous corpora, at the largest M and N timed; the
   overload-matrix oracle; the P3394 Transient path (Test/Correctness.cpp).
4. Manipulation checks for every arm pair: compiled functions and backend markers,
   markers in the preprocessed source, and identical disassembly where code must be
   identical; the shape of every overload idiom.
5. An -O2 profile of the FullN arms (recorded, not pass/fail).

    python preflight.py --gxx PATH [--out report.json]
"""
from __future__ import annotations
import argparse
import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile

import arms
import compiler
import deps
import generate
import overload
import plan

PROJECT = pathlib.Path(__file__).resolve().parent.parent
BIN = pathlib.Path(compiler.UCRT_BIN)
NM, OBJDUMP, SIZE = (str(BIN / f"{t}.exe") for t in ("nm", "objdump", "size"))
# Large oracle TUs exceed the PE/COFF section limit; without big-obj the link fails with
# thousands of spurious undefined references. (Timed compiles never assemble.)
OBJ_FLAGS = ["-Wa,-mbig-obj"] if os.name == "nt" else []
CONFIG = re.compile(r"config: BOOST_PFR_USE_CPP26=(\d) BOOST_PFR_USE_CPP26_REFLECTION=(\d) "
                    r"GLZ_REFLECTION26=(\d) REFLECTCPP_USE_CPP26_REFLECTION=(\d)")
CONFIG_KEYS = ("BOOST_PFR_USE_CPP26", "BOOST_PFR_USE_CPP26_REFLECTION", "GLZ_REFLECTION26",
               "REFLECTCPP_USE_CPP26_REFLECTION")


def _build(gxx, src, out, flags, extra_dirs, objects_only=False, opt="-O0"):
    cmd = [gxx, *compiler.BASE_FLAGS, opt, *OBJ_FLAGS, *flags, *compiler.include_flags(extra_dirs),
           *(["-c"] if objects_only else []), "-o", str(out), str(src)]
    p = subprocess.run(cmd, capture_output=True, text=True, env=compiler.env(gxx))
    if p.returncode != 0:
        raise RuntimeError(f"build failed: {' '.join(cmd)}\n{p.stderr[-3000:]}")


def _run_exe(exe, gxx):
    p = subprocess.run([str(exe)], capture_output=True, text=True, env=compiler.env(gxx))
    return p.returncode, p.stdout.strip().splitlines()


def _shapes():
    m_max = max(max(j.sweep) for j in plan.JOBS if j.dim == "M")
    n_hetero = max(max(j.sweep) for j in plan.JOBS if j.corpus == "hetero")
    return [("scalar", 5, 16), ("scalar", 3, m_max), ("rich", 5, 16), ("rich", 3, m_max),
            ("hetero", n_hetero, 8)]


def flag_checks(gxx: str, work: pathlib.Path) -> list[dict]:
    gen = work / "flags"
    generate.generate(gen, 2, 2, "scalar")
    probe = gen / "probe.cpp"
    probe.write_text("int x;\n")
    out = []
    for a in arms.ARMS.values():
        cmd = compiler.cc1plus_command(gen / a.tu, "syntax", a.flags, [gen], gxx, a.report)
        text = " ".join(cmd)
        problems = [f"flag {f} missing from the cc1plus command" for f in a.flags
                    if f.removeprefix("-D") not in text and f not in cmd]
        if ("-ftime-report" in cmd) != a.report:
            problems.append("-ftime-report presence does not match the arm")
        if "-fno-reflection" in a.flags:
            # The driver may drop the overridden -freflection altogether; if it keeps it,
            # -fno-reflection must come later.
            if "-freflection" in cmd and cmd.index("-fno-reflection") < cmd.index("-freflection"):
                problems.append("-fno-reflection does not come after -freflection")
        p = subprocess.run([gxx, *compiler.BASE_FLAGS, *a.flags, "-E", "-dM", str(probe)],
                           capture_output=True, text=True, env=compiler.env(gxx))
        has_refl = "__cpp_impl_reflection" in p.stdout
        if has_refl == ("-fno-reflection" in a.flags):
            problems.append(f"__cpp_impl_reflection {'defined' if has_refl else 'missing'} under the arm's flags")
        out.append({"arm": a.name, "ok": not problems, "problems": problems})
    return out


def oracles(gxx: str, work: pathlib.Path) -> list[dict]:
    results = []
    variants = arms.oracle_variants()
    for corpus, n, m in _shapes():
        gen = work / f"oracle_{corpus}_{n}_{m}"
        generate.generate(gen, n, m, corpus)
        for flags, v in variants.items():
            src = gen / ("correctness_synth.cpp" if v["reflection"] else "correctness_noreflect.cpp")
            exe = gen / f"oracle_{abs(hash(flags))}.exe"
            _build(gxx, src, exe, flags, [gen])
            rc, lines = _run_exe(exe, gxx)
            cfg = next((CONFIG.search(l) for l in lines if CONFIG.search(l)), None)
            got = dict(zip(CONFIG_KEYS, cfg.groups())) if cfg else {}
            problems = []
            if not (rc == 0 and lines and lines[-1].startswith("OK:")):
                problems.append("oracle failed")
            if got != v["expect"]:
                problems.append(f"backend configuration {got} != expected {v['expect']}")
            results.append({"corpus": corpus, "n": n, "m": m, "flags": list(flags) or ["(none)"],
                            "ok": not problems, "problems": problems, "output": lines[-1:] if lines else []})
    gen = work / "oracle_overload"
    src = overload.oracle(gen, 5, 16)
    exe = gen / "oracle_overload.exe"
    _build(gxx, src, exe, (), [gen])
    rc, lines = _run_exe(exe, gxx)
    results.append({"corpus": "overload", "n": 5, "m": 16, "flags": ["(none)"],
                    "ok": rc == 0 and bool(lines) and lines[-1].startswith("OK:"), "problems": [],
                    "output": lines[-1:]})
    exe = work / "correctness.exe"
    _build(gxx, PROJECT / "Test" / "Correctness.cpp", exe, (), [])
    rc, lines = _run_exe(exe, gxx)
    results.append({"corpus": "Transient (P3394)", "n": 1, "m": 8, "flags": ["(none)"],
                    "ok": rc == 0 and bool(lines) and lines[-1].startswith("OK:"), "problems": [],
                    "output": lines[-1:]})
    return results


def _functions(obj: pathlib.Path) -> set[str]:
    p = subprocess.run([NM, "-C", "--defined-only", str(obj)], capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"nm failed on {obj}: {p.stderr}")
    out = set()
    for ln in p.stdout.splitlines():
        parts = ln.split(" ", 2)
        if len(parts) == 3 and parts[1] == "T":
            out.add(parts[2])
    if not out:
        raise RuntimeError(f"no functions defined in {obj}")
    return out


_HEX = re.compile(r"\b[0-9a-f]+ <")
_OFF = re.compile(r"\+0x[0-9a-f]+>")


def _disassembly(obj: pathlib.Path) -> dict[str, list[str]]:
    """Per function: its instructions, with addresses and symbol offsets removed."""
    p = subprocess.run([OBJDUMP, "-d", "-C", "--no-show-raw-insn", str(obj)], capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"objdump failed on {obj}: {p.stderr}")
    funcs, cur = {}, None
    for ln in p.stdout.splitlines():
        m = re.match(r"^[0-9a-f]+ <(.+)>:$", ln)
        if m:
            cur = m.group(1)
            funcs[cur] = []
            continue
        if cur and "\t" in ln:
            ins = ln.split(":", 1)[1].strip() if ":" in ln else ln.strip()
            funcs[cur].append(_OFF.sub(">", _HEX.sub("<", ins)))
    return funcs


def _preprocessed(gxx, tu, flags, extra_dirs) -> str:
    p = subprocess.run([gxx, *compiler.BASE_FLAGS, *flags, *compiler.include_flags(extra_dirs),
                        "-E", "-P", str(tu)], capture_output=True, text=True, env=compiler.env(gxx))
    if p.returncode != 0:
        raise RuntimeError(f"preprocessing failed for {tu}: {p.stderr[-2000:]}")
    return p.stdout


def manipulation(gxx: str, work: pathlib.Path) -> list[dict]:
    gen = work / "manip"
    generate.generate(gen, 5, 16, "scalar")
    objs, funcs, srcs = {}, {}, {}
    for name in {a for p in arms.PAIRS for a in (p.a, p.b)}:
        arm = arms.ARMS[name]
        objs[name] = gen / f"{name}.o"
        _build(gxx, gen / arm.tu, objs[name], arm.flags, [gen], objects_only=True)
        funcs[name] = _functions(objs[name])
        srcs[name] = _preprocessed(gxx, gen / arm.tu, arm.flags, [gen])
    results = []
    for p in arms.PAIRS:
        fa, fb = funcs[p.a], funcs[p.b]
        only_a, only_b = fa - fb, fb - fa
        problems = []
        if p.expect == "identical":
            da, db = _disassembly(objs[p.a]), _disassembly(objs[p.b])
            if da != db:
                diff = sorted(set(da) ^ set(db)) or sorted(k for k in da if da[k] != db.get(k))
                problems.append(f"disassembly differs ({len(diff)} functions, e.g. {diff[:2]})")
        elif not (only_a or only_b) and not (p.src_only_in_a or p.src_only_in_b):
            problems.append("expected different code, got identical function sets and no source marker")
        for rx in p.only_in_a:
            if not any(re.search(rx, f) for f in only_a):
                problems.append(f"object marker {rx!r} not found only in {p.a}")
        for rx in p.only_in_b:
            if not any(re.search(rx, f) for f in only_b):
                problems.append(f"object marker {rx!r} not found only in {p.b}")
        for rx in p.src_only_in_a:
            if not (re.search(rx, srcs[p.a]) and not re.search(rx, srcs[p.b])):
                problems.append(f"source marker {rx!r} not only in {p.a}")
        for rx in p.src_only_in_b:
            if not (re.search(rx, srcs[p.b]) and not re.search(rx, srcs[p.a])):
                problems.append(f"source marker {rx!r} not only in {p.b}")
        results.append({"a": p.a, "b": p.b, "expect": p.expect, "isolates": p.isolates,
                        "functions": [len(fa), len(fb)], "only_a": len(only_a), "only_b": len(only_b),
                        "ok": not problems, "problems": problems})
    for v in overload.VARIANTS:
        results.append({"a": v, "b": "(idiom shape)", "expect": "shape", "isolates": overload.VARIANTS[v],
                        "functions": [0, 0], "only_a": 0, "only_b": 0, "ok": overload.shape_ok(v),
                        "problems": [] if overload.shape_ok(v) else ["generated TU lacks the idiom's shape"]})
    return results


def o2_profile(gxx: str, work: pathlib.Path) -> list[dict]:
    """Recorded, not checked: what -O2 does to each FullN arm (out-of-line functions and
    code size) — the context for -O2 ratios between arms."""
    gen = work / "o2"
    generate.generate(gen, 200, 16, "scalar")
    out = []
    for name in plan.by_name("FullN").arms:
        a = arms.ARMS[name]
        obj = gen / f"{name}.o"
        _build(gxx, gen / a.tu, obj, a.flags, [gen], objects_only=True, opt="-O2")
        text = subprocess.run([SIZE, "-A", str(obj)], capture_output=True, text=True).stdout
        tsize = sum(int(l.split()[1]) for l in text.splitlines() if l.startswith(".text"))
        out.append({"arm": name, "functions": len(_functions(obj)), "text_bytes": tsize})
    return out


def run(gxx: str) -> dict:
    report = {"compiler": compiler.version(gxx), "deps_ok": deps.verify()}
    with tempfile.TemporaryDirectory(prefix="rb_preflight_") as tmp:
        work = pathlib.Path(tmp)
        report["flags"] = flag_checks(gxx, work)
        report["oracles"] = oracles(gxx, work)
        report["manipulation"] = manipulation(gxx, work)
        report["o2_profile"] = o2_profile(gxx, work)
    report["ok"] = (report["deps_ok"] and all(x["ok"] for x in report["flags"])
                    and all(o["ok"] for o in report["oracles"])
                    and all(m["ok"] for m in report["manipulation"]))
    return report


def print_report(r: dict) -> None:
    print(f"compiler: {r['compiler']}   deps: {'ok' if r['deps_ok'] else 'FAIL'}")
    bad_flags = [f for f in r["flags"] if not f["ok"]]
    print(f"  flags: {len(r['flags']) - len(bad_flags)}/{len(r['flags'])} arms ok")
    for f in bad_flags:
        print(f"    FAIL {f['arm']}: {'; '.join(f['problems'])}")
    for o in r["oracles"]:
        print(f"  oracle {o['corpus']:<17} N={o['n']:<4} M={o['m']:<3} {' '.join(o['flags']):<45} "
              f"{'ok ' if o['ok'] else 'FAIL'} {'; '.join(o['problems'])}")
    for m in r["manipulation"]:
        print(f"  pair {m['a']:>20} vs {m['b']:<20} {m['expect']:<9} {'ok ' if m['ok'] else 'FAIL'} "
              f"({m['only_a']}/{m['only_b']}) {'; '.join(m['problems'])}")
    for p in r.get("o2_profile", []):
        print(f"  -O2 N=200 {p['arm']:<15} {p['functions']:5d} functions, .text {p['text_bytes']:8d} bytes")
    print("PREFLIGHT", "PASSED" if r["ok"] else "FAILED")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--gxx", required=True)
    ap.add_argument("--out", default="")
    args = ap.parse_args()
    rep = run(args.gxx)
    print_report(rep)
    if args.out:
        pathlib.Path(args.out).write_text(json.dumps(rep, indent=2))
    sys.exit(0 if rep["ok"] else 1)
