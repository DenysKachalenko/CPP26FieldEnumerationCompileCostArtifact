# SPDX-License-Identifier: MIT
"""Measurement sessions.

    python campaign.py estimate --gxx PATH [--compiler TAG=PATH] [--jobs A,B]
        Time one round of each job and predict the session's duration.
    python campaign.py run --session NAME --gxx PATH [--compiler TAG=PATH] [--jobs A,B]
        Run (or resume) a session into Data/Sessions/NAME/.

A session binds, in Data/Sessions/NAME/session.json, the compilers (path, version,
cc1plus sha256), the code fingerprint (sha256 of the measurement modules, Include/RB/*
and Deps.json; machine.FINGERPRINT_GLOBS) and the protocol parameters, and keeps a copy
of that code (code.zip). Resuming with a different compiler, different code or a
different protocol is refused. Arms written `arm@TAG` are compiled with the compiler
bound to TAG (e.g. `--compiler GCC161=...`), in the same rounds as the default arms.

    python campaign.py preflight --gxx PATH [--compiler TAG=PATH]
        Run (or confirm) the preflight of every compiler for the current code.

Before timing, a session pins itself to the performance cores, records the machine
(env.json), runs the preflight for every compiler (or reuses one that passed for the same
checked code and compiler, Data/Preflight/), generates every corpus and resolves every
compiler command line (cmds.json). A citable session requires the High performance power
plan. Each job then runs one warm-up round plus ROUNDS measured rounds; each round
compiles every cell once in a seeded random order between two sentinel compiles. Rounds
are never repeated and the machine's load does not gate anything: the load during each
compile is recorded with it, and the median over rounds absorbs a disturbed compile. A
job whose compile fails is logged and skipped, the other jobs continue, and the run exits
with code 5. Stopping (Ctrl+C) loses at most the current round; re-running resumes.
"""
from __future__ import annotations
import argparse
import csv
import datetime
import gzip
import hashlib
import json
import os
import pathlib
import random
import sys
import tempfile
import time
import zipfile

import psutil

import arms
import compiler
import generate
import machine
import overload
import plan
import preflight

PROJECT = pathlib.Path(__file__).resolve().parent.parent
SESSIONS = pathlib.Path(os.environ.get("RB_SESSIONS", PROJECT / "Data" / "Sessions"))
OTHER_CORE_BUSY_PCT = 50.0    # a performance CPU other than the compiler's above this is "busy"
HIGH_PERFORMANCE = "8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c"   # Windows' High performance plan
PREFLIGHTS = PROJECT / "Data" / "Preflight"   # passed preflights, by code fingerprint and cc1plus

TIMER_COLS = [f"ft_{c}_s" for c in compiler.TIMERS.values()]
GGC_COLS = [f"ggc_{c}_mb" for c in compiler.TIMERS.values()]
OS_COLS = [f"os_{c}" for c in compiler.OS_COUNTERS]
# attempt/accepted are always 1 (one pass per round); kept so the analysis reads every session.
COLUMNS = ["session", "compiler_tag", "compiler", "job", "round", "attempt", "accepted", "warmup",
           "seq", "kind", "arm", "mode", "corpus", "dim", "x", "n", "m", "k", "c",
           *TIMER_COLS, *GGC_COLS, "wall_s", *OS_COLS, "load_pct", "pcore_busy", "utc"]


def utc() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


class Workspace:
    """Generated sources for every cell (deterministic, regenerated on resume)."""

    def __init__(self, root: pathlib.Path):
        self.root = root
        self.done: set[pathlib.Path] = set()

    def tu(self, job: plan.Job, arm_name: str, x: int) -> tuple[pathlib.Path, list[pathlib.Path]]:
        d = job.dims(x)
        arm = arms.get(arm_name)
        if arm.family == "overload":
            variant = arm_name.partition("@")[0]
            out = self.root / f"ovl_{variant}_k{d['k']}_c{d['c']}_m{d['m']}{'_prime' if job.prime else ''}"
            if out not in self.done:
                overload.generate(out, variant, d["k"], d["c"], d["m"], prime=job.prime)
                self.done.add(out)
            return out / arm.tu, [out]
        out = self.root / f"{job.corpus}_n{d['n']}_m{d['m']}"
        if out not in self.done:
            generate.generate(out, d["n"], d["m"], job.corpus)
            self.done.add(out)
        return out / arm.tu, [out]


class Session:
    def __init__(self, name: str, compilers: dict[str, str], protocol: dict):
        self.name = name
        self.dir = SESSIONS / name
        self.compilers = compilers          # tag -> driver path ("default" = protocol compiler)
        self.protocol = protocol
        self.ws = Workspace(pathlib.Path(tempfile.gettempdir()) / f"rb_session_{name}")
        self.cmds: dict[str, list[str]] = {}
        self.versions = {tag: compiler.version(g) for tag, g in compilers.items()}

    def gxx(self, arm_name: str) -> tuple[str, str]:
        tag = arms.compiler_tag(arm_name) or "default"
        if tag not in self.compilers:
            raise SystemExit(f"arm {arm_name} needs compiler tag {tag!r}: pass --compiler {tag}=PATH")
        return tag, self.compilers[tag]

    def command(self, job: plan.Job, arm_name: str, x: int) -> list[str]:
        key = f"{job.name}|{arm_name}|{x}"
        if key not in self.cmds:
            tu, dirs = self.ws.tu(job, arm_name, x)
            arm = arms.get(arm_name)
            self.cmds[key] = compiler.cc1plus_command(tu, job.mode, arm.flags, dirs, self.gxx(arm_name)[1], arm.report)
        return self.cmds[key]


def _load_sample(pinned: list[int]) -> tuple[float, int]:
    """System CPU % since the previous call, and the number of pinned CPUs other than the
    busiest one (assumed to be the compiler's) that were above OTHER_CORE_BUSY_PCT."""
    per = psutil.cpu_percent(interval=None, percpu=True)
    total = sum(per) / len(per)
    pins = sorted((per[c] for c in pinned if c < len(per)), reverse=True)
    busy = sum(1 for v in pins[1:] if v > OTHER_CORE_BUSY_PCT)
    return round(total, 1), busy


def _memory() -> dict:
    return {"available_mb": round(psutil.virtual_memory().available / 2**20),
            "swap_used_mb": round(psutil.swap_memory().used / 2**20)}


def measure(s: Session, job: plan.Job, arm_name: str, x: int, pinned: list[int]) -> dict:
    cmd = s.command(job, arm_name, x)
    arm = arms.get(arm_name)
    tag, gxx = s.gxx(arm_name)
    _load_sample(pinned)
    rep = compiler.compile_once(cmd, gxx=gxx, report=arm.report)
    load, busy = _load_sample(pinned)          # the machine's load during this compile
    return {"arm": arm_name, "compiler_tag": tag, "compiler": s.versions[tag], "mode": job.mode,
            "corpus": job.corpus, "dim": job.dim, "x": x, **job.dims(x), **rep,
            "load_pct": load, "pcore_busy": busy, "utc": utc()}


def round_sequence(session: str, job: plan.Job, rnd: int) -> list[tuple[str, str, int]]:
    cells = job.cells()
    random.Random(f"{session}|{job.name}|{rnd}").shuffle(cells)
    s_arm, s_x = job.sentinel
    return [("sentinel_start", s_arm, s_x), *(("cell", a, x) for a, x in cells),
            ("sentinel_end", s_arm, s_x)]


def run_job(s: Session, job: plan.Job, pinned: list[int], log) -> None:
    raw, progress, reports = s.dir / "raw.csv", s.dir / "rounds.json", s.dir / "reports.jsonl.gz"
    done = json.loads(progress.read_text()) if progress.is_file() else {}
    warm, rounds = s.protocol["warmup"], s.protocol["rounds"]
    total = warm + rounds
    for rnd in range(total):
        if str(rnd) in done.get(job.name, {}):
            continue
        t0 = time.perf_counter()
        # One pass per round, never repeated. Each compile's machine load is recorded with it;
        # the median over rounds absorbs an occasional disturbed compile.
        rows = []
        for seq, (kind, arm, x) in enumerate(round_sequence(s.name, job, rnd)):
            r = measure(s, job, arm, x, pinned)
            rows.append({"session": s.name, "job": job.name, "round": rnd, "attempt": 1, "accepted": 1,
                         "warmup": int(rnd < warm), "seq": seq, "kind": kind, **r})
        new = not raw.is_file()
        with raw.open("a", newline="") as f, gzip.open(reports, "at", encoding="utf-8") as g:
            w = csv.DictWriter(f, fieldnames=COLUMNS, extrasaction="ignore")
            if new:
                w.writeheader()
            for r in rows:
                w.writerow(r)
                g.write(json.dumps({k: r[k] for k in ("job", "round", "attempt", "seq", "arm", "x")}
                                   | {"stderr": r["_stderr"]}) + "\n")
        loads = [r["load_pct"] for r in rows]
        done.setdefault(job.name, {})[str(rnd)] = {
            "seconds": round(time.perf_counter() - t0, 1),
            "load_median_pct": sorted(loads)[len(loads) // 2], "load_max_pct": max(loads),
            **_memory(), "end_utc": utc()}
        progress.write_text(json.dumps(done, indent=1))
        sent = [r["ft_total_s"] for r in rows if r["kind"] != "cell"]
        log(f"  {job.name} round {rnd + 1}/{total} ({'warm-up' if rnd < warm else 'measured'}): "
            f"{len(rows)} compiles, {time.perf_counter() - t0:.0f} s, sentinel {sent[0]:.2f}->{sent[-1]:.2f} s, "
            f"load median {sorted(loads)[len(loads) // 2]:.0f}% max {max(loads):.0f}%")


def _compilers(args) -> dict[str, str]:
    out = {"default": args.gxx}
    for spec in args.compiler or []:
        tag, _, path = spec.partition("=")
        if not tag or not path:
            raise SystemExit(f"--compiler expects TAG=PATH, got {spec!r}")
        out[tag] = path
    return out


def _jobs(args, compilers) -> list[plan.Job]:
    jobs = [plan.by_name(n) for n in args.jobs.split(",")] if args.jobs else list(plan.JOBS)
    usable = []
    for j in jobs:
        missing = {arms.compiler_tag(a) for a in j.arms} - {None} - set(compilers)
        if missing:
            print(f"skipping job {j.name}: needs --compiler {', '.join(sorted(missing))}=PATH")
            continue
        usable.append(j)
    return usable


def cmd_estimate(args) -> int:
    pinned = machine.pin_to_performance_cores()
    compilers = _compilers(args)
    s = Session("estimate", compilers, {"warmup": plan.WARMUP_ROUNDS, "rounds": plan.ROUNDS,
                                        "round_attempts": 1})
    total = 0.0
    out = {"utc": utc(), "compilers": s.versions, "jobs": {}}
    for job in _jobs(args, compilers):
        seq = round_sequence("estimate", job, 0)
        for _, arm, x in seq:
            s.command(job, arm, x)          # generation and -### outside the timing
        t0 = time.perf_counter()
        for _, arm, x in seq:
            measure(s, job, arm, x, pinned)
        per_round = time.perf_counter() - t0
        job_s = per_round * (plan.WARMUP_ROUNDS + plan.ROUNDS)
        total += job_s
        out["jobs"][job.name] = {"round_s": round(per_round, 1), "job_s": round(job_s)}
        print(f"  {job.name:<14} one round {per_round:6.0f} s  -> job {job_s / 60:6.1f} min "
              f"({len(job.cells())} cells x {plan.WARMUP_ROUNDS + plan.ROUNDS} rounds)", flush=True)
    out["session_s"] = round(total)
    print(f"\npredicted session: {total / 3600:.2f} h without repeated rounds, plus the preflight "
          f"(about 15 min per compiler)")
    (PROJECT / "Data").mkdir(exist_ok=True)
    (PROJECT / "Data" / "Estimate.json").write_text(json.dumps(out, indent=1))
    return 0


def _bind(sdir: pathlib.Path, compilers: dict, protocol: dict, pilot: bool, log) -> dict:
    """Create the session file, or check that a resume matches it exactly."""
    path = sdir / "session.json"
    now = {"compilers": {t: {"path": g, **{k: v for k, v in machine.compiler_record(g).items()
                                            if k in ("version", "cc1plus_sha256", "driver_sha256")}}
                         for t, g in compilers.items()},
           "fingerprint": machine.fingerprint()["digest"], "protocol": protocol}
    if not path.is_file():
        state = {**now, "created_utc": utc(), "pilot": pilot, "preflight": {}}
        # The measured code itself, not only its hashes (it may not be committed yet).
        with zipfile.ZipFile(sdir / "code.zip", "w", zipfile.ZIP_DEFLATED) as z:
            for rel in machine.fingerprint()["files"]:
                z.write(PROJECT / rel, rel)
        path.write_text(json.dumps(state, indent=1))
        return state
    state = json.loads(path.read_text())
    problems = []
    for key in ("fingerprint", "protocol"):
        if state[key] != now[key]:
            problems.append(f"{key} differs from the session's")
    for tag, rec in state["compilers"].items():
        if tag in now["compilers"] and now["compilers"][tag] != rec:
            problems.append(f"compiler {tag} differs from the session's ({rec['version']}, {rec['path']})")
    new_tags = set(now["compilers"]) - set(state["compilers"])
    if problems:
        for p in problems:
            log(f"REFUSED: {p}")
        raise SystemExit(4)
    if new_tags:
        state["compilers"].update({t: now["compilers"][t] for t in new_tags})
    if pilot and not state.get("pilot"):
        log("REFUSED: --skip-preflight on a session that ran with the preflight")
        raise SystemExit(4)
    path.write_text(json.dumps(state, indent=1))
    return state


def preflight_fingerprint() -> str:
    """The code a preflight checks: the session fingerprint without the session runner itself
    (campaign.py schedules and records compiles; it generates and checks nothing)."""
    files = {k: v for k, v in machine.fingerprint()["files"].items() if k != "Harness/campaign.py"}
    return hashlib.sha256("".join(f"{k}={v}\n" for k, v in files.items()).encode()).hexdigest()


def _preflight(gxx: str, rec: dict, fingerprint: str, log) -> dict:
    """The preflight for this checked code and this compiler. It checks correctness, not
    timing, so one that passed is reused (Data/Preflight/)."""
    path = PREFLIGHTS / f"{fingerprint[:16]}-{rec['cc1plus_sha256'][:16]}.json"
    if path.is_file():
        rep = json.loads(path.read_text())
        if rep.get("ok") and rep.get("fingerprint") == fingerprint \
                and rep.get("cc1plus_sha256") == rec["cc1plus_sha256"]:
            log(f"preflight on {rec['version']}: passed on {rep.get('utc')} for this code and compiler, reused")
            return rep
    log(f"preflight on {rec['version']} ...")
    rep = preflight.run(gxx)
    rep.update(fingerprint=fingerprint, cc1plus_sha256=rec["cc1plus_sha256"], utc=utc())
    PREFLIGHTS.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rep, indent=1))
    return rep


def cmd_preflight(args) -> int:
    """Run (or confirm) the preflight of every compiler for the current code, without a session."""
    fingerprint = preflight_fingerprint()
    ok = True
    for tag, gxx in _compilers(args).items():
        rec = {k: v for k, v in machine.compiler_record(gxx).items() if k in ("version", "cc1plus_sha256")}
        rep = _preflight(gxx, rec, fingerprint, lambda m: print(m, flush=True))
        if not rep["ok"]:
            preflight.print_report(rep)
        print(f"{tag}: preflight {'passed' if rep['ok'] else 'FAILED'}", flush=True)
        ok = ok and rep["ok"]
    return 0 if ok else 3


def cmd_run(args) -> int:
    sdir = SESSIONS / args.session
    sdir.mkdir(parents=True, exist_ok=True)
    logf = (sdir / "log.txt").open("a")

    def log(msg):
        line = f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {msg}"
        print(line, flush=True)
        logf.write(line + "\n")
        logf.flush()

    compilers = _compilers(args)
    protocol = {"warmup": args.warmup, "rounds": args.rounds, "passes_per_round": 1,
                "load": "recorded per compile, no gate", "other_core_busy_pct": OTHER_CORE_BUSY_PCT,
                "power_plan": HIGH_PERFORMANCE}
    standard = (args.warmup, args.rounds) == (plan.WARMUP_ROUNDS, plan.ROUNDS)
    pilot = args.skip_preflight or not standard
    state = _bind(sdir, compilers, protocol, pilot, log)
    pinned = machine.pin_to_performance_cores()
    log(f"session {args.session}: {', '.join(f'{t}={v}' for t, v in compilers.items())}; "
        f"pinned to performance CPUs {pinned or 'n/a (not hybrid)'}"
        + ("; PILOT (not citable)" if state.get("pilot") else ""))
    snap = machine.snapshot(sorted(set(compilers.values())))
    snap["pinned_cpus"] = pinned
    env_path = sdir / "env.json"
    envs = json.loads(env_path.read_text()) if env_path.is_file() else []
    envs.append(snap)
    env_path.write_text(json.dumps(envs, indent=1))
    log(f"machine load before start: {snap['load_total_pct']}% (busiest: "
        + ", ".join(f"{p['name']} {p['cpu_pct']}%" for p in snap["busiest_processes"][:4]) + ")")
    if HIGH_PERFORMANCE not in snap["power_plan"]:
        if not state.get("pilot"):
            log("ABORT: the power plan is not High performance (RunBook step 0; overnight.sh selects it)")
            return 6
        log("note: power plan is not High performance (pilot session; recorded in env.json)")

    if args.skip_preflight:
        log("WARNING: preflight skipped (pilot session, not citable)")
    else:
        for tag, gxx in compilers.items():
            rec = state["compilers"][tag]
            rep = _preflight(gxx, rec, preflight_fingerprint(), log)
            (sdir / f"preflight_{tag}.json").write_text(json.dumps(rep, indent=1))
            state["preflight"][tag] = {"ok": rep["ok"], "utc": utc(), "fingerprint": state["fingerprint"],
                                       "cc1plus_sha256": rec["cc1plus_sha256"]}
            (sdir / "session.json").write_text(json.dumps(state, indent=1))
            if not rep["ok"]:
                preflight.print_report(rep)
                log("ABORT: preflight failed")
                return 3
            log("preflight passed")

    jobs = _jobs(args, compilers)
    s = Session(args.session, compilers, protocol)
    log("generating corpora and resolving compiler command lines ...")
    for job in jobs:
        for arm, x in job.cells() + [job.sentinel]:
            s.command(job, arm, x)
    (sdir / "cmds.json").write_text(json.dumps(s.cmds, indent=0))
    failed = []
    try:
        for job in jobs:
            log(f"job {job.name}: {len(job.cells())} cells x {args.warmup + args.rounds} rounds")
            try:
                run_job(s, job, pinned, log)
            except (RuntimeError, OSError) as exc:
                # A failing compile is a defect to fix, not noise: the job stops at the round
                # it reached (its finished rounds are kept), the other jobs still run.
                failed.append(job.name)
                log(f"JOB FAILED {job.name}: {str(exc)[:3000]}")
    except KeyboardInterrupt:
        log("stopped by user; re-run the same command to resume")
        return 130
    if failed:
        log(f"session incomplete: failed jobs {', '.join(failed)}; fix them, then re-run the same command")
        return 5
    log("session complete")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("estimate")
    r = sub.add_parser("run")
    f = sub.add_parser("preflight")
    for p in (e, r, f):
        p.add_argument("--jobs", default="")
        p.add_argument("--gxx", required=True, help="the protocol compiler's g++ driver")
        p.add_argument("--compiler", action="append", metavar="TAG=PATH",
                       help="an extra compiler for arms written arm@TAG (e.g. GCC161=...)")
    r.add_argument("--session", required=True)
    r.add_argument("--rounds", type=int, default=plan.ROUNDS,
                   help="measured rounds per job; anything but the plan's value marks a pilot")
    r.add_argument("--warmup", type=int, default=plan.WARMUP_ROUNDS)
    r.add_argument("--skip-preflight", action="store_true", help="pilot sessions only")
    args = ap.parse_args()
    return {"estimate": cmd_estimate, "run": cmd_run, "preflight": cmd_preflight}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
