# SPDX-License-Identifier: MIT
"""Every number the paper cites, computed from raw session data.

Each entry is registered with a key and a format; `compute()` evaluates all of them on
the first session given (and, with several sessions, the pooled and between-session
numbers) and writes Data/PaperNumbers.json. The draft refers to a number as
`<text><!--n:key-->` (or `<!--ci:key-->` for its interval), and paperlint.py checks or
rewrites the text against this file. A number that is not finite, or a crossover that
is undefined in more than 5% of bootstrap resamples, is recorded as an error.

    python papernumbers.py Data/Sessions/S1 [Data/Sessions/S2 ...] [--allow-pilot] [--out ...]
"""
from __future__ import annotations
import argparse
import json
import math
import pathlib
from typing import Callable

import numpy as np

import plan
import stats

PROJECT = pathlib.Path(__file__).resolve().parent.parent

Registry = dict[str, tuple[Callable[[dict], dict], str]]
NUMBERS: Registry = {}
POOLED: Registry = {}   # evaluated on stats.Pooled objects, when several sessions are given
SUPPLEMENTARY: Registry = {}   # job FrontendIdiom, evaluated only when a session has it (S3)


def number(key: str, fmt: str = "{:.2f}", registry: Registry | None = None):
    reg = NUMBERS if registry is None else registry
    def wrap(fn):
        if key in reg:
            raise KeyError(f"duplicate number key {key!r}")
        reg[key] = (fn, fmt)
        return fn
    return wrap


def _fmt(fmt: str, v) -> str:
    return fmt.format(v)


def _finite(v) -> bool:
    return isinstance(v, (int, float)) and math.isfinite(v)


def _entry(r: dict, fmt: str) -> dict:
    if not _finite(r["est"]):
        return {"error": f"not finite: {r['est']}"}
    if r.get("undefined_share", 0) > 0.05:
        return {"error": f"undefined in {r['undefined_share']:.0%} of resamples"}
    entry = {"est": r["est"], "text": _fmt(fmt, r["est"])}
    if "ci" in r:
        if not all(_finite(c) for c in r["ci"]):
            return {"error": f"interval not finite: {r['ci']}"}
        entry["ci"] = r["ci"]
        entry["ci_text"] = f"[{_fmt(fmt, r['ci'][0])}, {_fmt(fmt, r['ci'][1])}]"
    # Warnings include stats' linearity check: the paper reports slopes only for linear
    # curves (§3.6).
    for k in ("warning", "undefined_share", "note"):
        if k in r:
            entry[k] = r[k]
    return entry


def _evaluate(reg: Registry, arg) -> dict:
    out = {}
    for key, (fn, fmt) in sorted(reg.items()):
        try:
            out[key] = _entry(fn(arg), fmt)
        except (KeyError, ValueError, IndexError, ZeroDivisionError) as exc:
            out[key] = {"error": f"{type(exc).__name__}: {exc}"}
    return out


def compute(session_dirs: list[pathlib.Path], allow_pilot: bool = False) -> dict:
    all_rows = [stats.load_rows(d, allow_pilot) for d in session_dirs]
    per = [stats.job_data(rows, d) for rows, d in zip(all_rows, session_dirs)]
    # Single-session numbers come from the first session that ran the job: S1 for the full
    # plan, the supplementary session for a job only it ran (FrontendIdiom, S3).
    an = {}
    for p in per:
        for (_, job), jd in p.items():
            if job not in an:
                an[job] = stats.Analysis(jd, stats.metric_for(jd))
    out = {"sessions": [d.name for d in session_dirs], "numbers": _evaluate(NUMBERS, an)}
    if "FrontendIdiom" in an:
        out["numbers"].update(_evaluate(SUPPLEMENTARY, an))
        _mark_incomplete(out["numbers"], "FrontendIdiom.",
                         next(d for d, p in zip(session_dirs, per) if any(j == "FrontendIdiom" for (_, j) in p)))
    for rows, d in zip(all_rows, session_dirs):
        for key, r in session_numbers(d, rows).items():
            out["numbers"][key] = _entry(r, SESSION_FORMATS[key.split(".", 1)[1]])
    if len(per) > 1:
        # Pooled and between-session numbers over the full-plan sessions only (S1, S2). A
        # supplementary session (S3) runs only jobs of plan.SUPPLEMENTARY; one that also holds
        # a full-plan job was resumed without --jobs and must not enter the S1/S2 pool.
        supplementary = {j.name for j in plan.SUPPLEMENTARY}
        full = []
        for d, p in zip(session_dirs, per):
            jobs = {j for (_, j) in p}
            if jobs & supplementary:
                if jobs - supplementary:
                    raise ValueError(f"{d.name} holds both supplementary and full-plan jobs "
                                     f"({sorted(jobs - supplementary)}); refusing to pool it")
                continue
            full.append(p)
        pooled = {}
        for job in set().union(*[{j for (_, j) in p} for p in full]) if full else ():
            parts = [v for p in full for (_, j), v in p.items() if j == job]
            if len(parts) > 1:
                pooled[job] = stats.Pooled(parts, stats.metric_for(parts[0]))
        out["numbers"].update(_evaluate(POOLED, pooled))
    return out


def _mark_incomplete(numbers: dict, prefix: str, session_dir: pathlib.Path) -> None:
    """Warn on every key of a job whose session did not finish its protocol rounds (a night
    that stopped early): its numbers rest on fewer rounds than the paper states."""
    state = json.loads((session_dir / "session.json").read_text())
    want = state["protocol"]["warmup"] + state["protocol"]["rounds"]
    done = json.loads((session_dir / "rounds.json").read_text())
    job = prefix.rstrip(".")
    got = len(done.get(job, []))
    if got < want:
        for k, v in numbers.items():
            if k.startswith(prefix):
                v["warning"] = (v.get("warning", "") + "; " if v.get("warning") else "") + \
                    f"incomplete: {got} of {want} rounds in {session_dir.name}"


# ---- Registered numbers -------------------------------------------------------------
# Slopes (ms per unit) and same-job ratios. Keys: <job>.<arm>.slope, <job>.<a>/<b>.ratio.

def _slope(job, arm):
    return lambda an: an[job].slope(arm)


def _ratio(job, a, b):
    return lambda an: an[job].ratio(a, b)


for _job, _arms in {
    "FrontendN": ("manual_unique", "xmacro_unique", "reflect", "reflect_plain", "reflect_visit",
                  "p1061", "p1061_visit", "pfr", "pfr_classic", "pfr_native"),
    "FrontendHeavy": ("rflcpp", "rflcpp_native", "glaze_native", "glaze_classic",
                      "reflect_plain", "p1061_visit", "pfr"),
    "FrontendM": ("reflect", "reflect_plain", "reflect_visit", "p1061", "p1061_visit", "pfr",
                  "pfr_classic", "manual_unique", "xmacro_unique", "rflcpp", "rflcpp_native",
                  "glaze_native", "glaze_classic"),
    "FullN": ("manual_unique", "reflect", "reflect_plain", "reflect_visit", "p1061",
              "p1061_visit", "pfr", "pfr_classic", "xmacro_unique"),
    "FullHeavy": ("rflcpp", "rflcpp_native", "glaze_native", "glaze_classic", "reflect_plain", "pfr"),
    "HeteroN": ("manual_unique", "reflect", "reflect_plain", "reflect_visit", "p1061",
                "p1061_visit", "pfr", "pfr_classic"),
    "HeteroHeavy": ("rflcpp", "rflcpp_native", "glaze_native", "glaze_classic", "reflect_plain", "pfr"),
    "RichN": ("manual_unique", "reflect", "reflect_plain", "p1061", "pfr", "pfr_classic",
              "rflcpp", "rflcpp_native", "glaze_native", "glaze_classic"),
}.items():
    for _a in _arms:
        number(f"{_job}.{_a}.slope", "{:.2f}")(_slope(_job, _a))

for _job, _pairs in {
    "FrontendN": [("reflect", "reflect_plain"), ("reflect_plain", "pfr"), ("reflect_plain", "p1061"),
                  ("reflect_visit", "p1061_visit"), ("reflect_visit", "reflect_plain"),
                  ("p1061_visit", "p1061"), ("pfr", "p1061_visit"), ("pfr_classic", "pfr"),
                  ("pfr_native", "pfr"), ("reflect", "manual_unique"), ("reflect_plain", "manual_unique"),
                  ("xmacro_unique", "manual_unique"), ("p1061", "manual_unique"),
                  # Native against Boost.PFR with the API shape matched (both callbacks).
                  ("reflect_visit", "pfr")],
    "FrontendHeavy": [("rflcpp", "rflcpp_native"), ("glaze_classic", "glaze_native"),
                      ("rflcpp_native", "reflect_plain"), ("glaze_native", "reflect_plain")],
    "FullN": [("reflect_plain", "pfr"), ("reflect", "manual_unique"), ("pfr_classic", "pfr"),
              ("reflect_split", "pfr_split"), ("reflect", "pfr")],
    "FullHeavy": [("rflcpp", "rflcpp_native"), ("glaze_classic", "glaze_native")],
    "FrontendM": [("glaze_classic", "glaze_native"), ("rflcpp", "rflcpp_native"), ("pfr_classic", "pfr")],
    "HeteroN": [("reflect_plain", "pfr"), ("reflect_plain", "p1061"), ("pfr_classic", "pfr"),
                ("reflect", "manual_unique"), ("reflect_visit", "pfr")],
    "HeteroHeavy": [("rflcpp", "rflcpp_native"), ("glaze_classic", "glaze_native"), ("reflect_plain", "pfr")],
    "RichN": [("reflect_plain", "pfr"), ("glaze_classic", "glaze_native"), ("rflcpp", "rflcpp_native"),
              ("pfr_classic", "pfr"), ("reflect", "manual_unique"), ("reflect_visit", "pfr")],
}.items():
    for _a, _b in _pairs:
        number(f"{_job}.{_a}/{_b}.ratio", "{:.2f}")(_ratio(_job, _a, _b))


# ---- Points, differences, shares, overload shapes -------------------------------------

def _xi(a, x):
    return int(np.where(a.jd.xs == x)[0][0])


def _point_diff_ms(job, a, b, x, metric="ft_total_s"):
    """(a - b) at sweep value x, in ms, e.g. a fixed cost at x = 0."""
    def fn(an):
        t = an[job] if metric == "ft_total_s" else stats.Analysis(an[job].jd, metric)
        ia, ib, j = t.ai(a), t.ai(b), _xi(t, x)
        return {"est": float(t.med[ia, j] - t.med[ib, j]) * 1000,
                "ci": stats._ci((t.boot[ia, j] - t.boot[ib, j]) * 1000)}
    return fn


def _point_ratio(job, a, b, x, marginal=True, metric="ft_total_s"):
    def fn(an):
        t = an[job] if metric == "ft_total_s" else stats.Analysis(an[job].jd, metric)
        return t.point_ratio(a, b, x, marginal)
    return fn


def _marginal_s(job, arm, x):
    return lambda an: an[job].marginal(arm, x)


def _share(job, arm, timer):
    return lambda an: an[job].share(arm, timer)


def _point_share(job, arm, timer, x):
    return lambda an: an[job].point_share(arm, timer, x)


def _crossover(job, quad_arm, lin_arm):
    return lambda an: an[job].crossover(quad_arm, lin_arm)


def _metric_slope(job, arm, metric, unit):
    return lambda an: stats.Analysis(an[job].jd, metric).slope(arm, unit)


def _doubling(job, arm, x):
    """Marginal cost at x over marginal cost at x/2: about 2 if linear, 4 if quadratic."""
    def fn(an):
        a, j, h, j0 = an[job], _xi(an[job], x), _xi(an[job], x // 2), _xi(an[job], 0)
        i = a.ai(arm)
        return {"est": float((a.med[i, j] - a.med[i, j0]) / (a.med[i, h] - a.med[i, j0])),
                "ci": stats._ci((a.boot[i, j] - a.boot[i, j0]) / (a.boot[i, h] - a.boot[i, j0]))}
    return fn


# Fixed costs (x = 0), in ms.
number("FrontendN.fixed.meta_ms", "{:.0f}")(_point_diff_ms("FrontendN", "reflect_plain", "p1061", 0))
for _a in ("rflcpp", "rflcpp_native", "glaze_native", "glaze_classic"):
    number(f"FrontendHeavy.{_a}.fixed_over_pfr_ms", "{:.0f}")(_point_diff_ms("FrontendHeavy", _a, "pfr", 0))

# The -freflection flag on code that does not use reflection.
for _job, _arms in {"FlagCost": ("manual_unique", "p1061", "pfr"),
                    "FlagCostHeavy": ("rflcpp", "glaze_classic")}.items():
    for _a in _arms:
        number(f"{_job}.{_a}.flag_slope_ratio", "{:.3f}")(_ratio(_job, _a, f"{_a}_noflag"))
        number(f"{_job}.{_a}.flag_fixed_ms", "{:.0f}")(_point_diff_ms(_job, _a, f"{_a}_noflag", 0))

# -ftime-report overhead: external wall time with / without the report, at the largest N.
for _a in ("reflect_plain", "pfr", "manual_unique"):
    number(f"ReportOverhead.{_a}.wall_ratio", "{:.3f}")(
        _point_ratio("ReportOverhead", _a, f"{_a}_noreport", 2000, marginal=False, metric="wall_s"))

# Phase shares and memory per struct.
for _a in ("reflect", "reflect_plain", "p1061", "pfr", "pfr_classic", "manual_unique"):
    for _t, _k in (("ft_consteval_s", "consteval"), ("ft_tmpl_inst_s", "tmpl_inst"),
                   ("ft_overload_s", "overload"), ("ft_parsing_s", "parsing")):
        number(f"FrontendN.{_a}.share.{_k}", "{:.0%}")(_share("FrontendN", _a, _t))
    number(f"FrontendN.{_a}.ggc_kb", "{:.0f}")(_metric_slope("FrontendN", _a, "ggc_total_mb", 1024.0))

# Overloaded names in FrontendN: growth per doubling, overload share, crossovers.
for _a in ("manual", "xmacro"):
    number(f"FrontendN.{_a}.doubling", "{:.1f}")(_doubling("FrontendN", _a, 4000))
    number(f"FrontendN.{_a}.marginal4000_s", "{:.1f}")(_marginal_s("FrontendN", _a, 4000))
    # Not linear in N, so the share is taken of the marginal cost at N = 4000, not of a slope.
    number(f"FrontendN.{_a}.share4000.overload", "{:.0%}")(
        _point_share("FrontendN", _a, "ft_overload_s", 4000))
for _a in ("reflect", "reflect_plain"):
    number(f"FrontendN.manual/{_a}.crossover", "{:,.0f}")(_crossover("FrontendN", "manual", _a))
    # The quadratic model is misspecified when growth per doubling exceeds 4, so the
    # crossing is bracketed by measured marginal-cost ratios as well.
    for _n in (1000, 2000):
        number(f"FrontendN.manual/{_a}.point{_n}", "{:.2f}")(_point_ratio("FrontendN", "manual", _a, _n))
number("FrontendN.manual_unique.doubling", "{:.1f}")(_doubling("FrontendN", "manual_unique", 4000))

# Boost.PFR's C++17 path is not linear in N either (pilot 2026-10-30): its growth, and its
# ratio to the C++26 path as marginal costs at fixed N instead of a ratio of slopes.
number("FrontendN.pfr_classic.doubling", "{:.1f}")(_doubling("FrontendN", "pfr_classic", 4000))
number("FrontendN.pfr.doubling", "{:.1f}")(_doubling("FrontendN", "pfr", 4000))
number("FrontendN.pfr_classic.marginal4000_s", "{:.0f}")(_marginal_s("FrontendN", "pfr_classic", 4000))
number("FrontendN.pfr_classic.share4000.overload", "{:.0%}")(
    _point_share("FrontendN", "pfr_classic", "ft_overload_s", 4000))
def _per_struct_at(job, arm, x):
    """Marginal cost per struct at x, (cost(x) - cost(0)) / x, in ms."""
    def fn(an):
        m = an[job].marginal(arm, x)
        return {"est": m["est"] / x * 1000, "ci": [c / x * 1000 for c in m["ci"]]}
    return fn


for _n in (500, 4000):
    number(f"FrontendN.pfr_classic/pfr.point{_n}", "{:.1f}")(_point_ratio("FrontendN", "pfr_classic", "pfr", _n))
    for _a in ("pfr_classic", "pfr"):
        number(f"FrontendN.{_a}.per_struct{_n}", "{:.2f}")(_per_struct_at("FrontendN", _a, _n))
number("RichN.pfr_classic.doubling", "{:.1f}")(_doubling("RichN", "pfr_classic", 200))
number("HeteroN.pfr_classic.doubling", "{:.1f}")(_doubling("HeteroN", "pfr_classic", 1600))

# Overload matrix.
for _v in ("ovl_flat", "ovl_adl", "ovl_adl_template", "ovl_constrained", "ovl_archive",
           "ovl_adl_per_ns", "ovl_hidden_friend", "ovl_member", "ovl_specialization", "ovl_unique"):
    number(f"OverloadN.{_v}.marginal1000_s", "{:.2f}")(_marginal_s("OverloadN", _v, 1000))
    number(f"OverloadN.{_v}.doubling", "{:.1f}")(_doubling("OverloadN", _v, 1000))
    number(f"OverloadN.{_v}/ovl_unique.ratio1000", "{:.2f}")(
        _point_ratio("OverloadN", _v, "ovl_unique", 1000))
def _segment_slope(job, arm, x0, x1, unit=1000.0):
    """Slope between two sweep values, (cost(x1) - cost(x0)) / (x1 - x0), for a curve that
    is not linear."""
    def fn(an):
        a = an[job]
        i, j0, j1 = a.ai(arm), a.xi(x0), a.xi(x1)
        return {"est": float(a.med[i, j1] - a.med[i, j0]) / (x1 - x0) * unit,
                "ci": stats._ci((a.boot[i, j1] - a.boot[i, j0]) / (x1 - x0) * unit)}
    return fn


number("OverloadC.ovl_adl_template.slope", "{:.2f}")(_slope("OverloadC", "ovl_adl_template"))
for _v in ("ovl_flat", "ovl_archive", "ovl_unique"):
    number(f"OverloadC.{_v}.slope", "{:.2f}")(_slope("OverloadC", _v))
    number(f"OverloadK.{_v}.slope", "{:.3f}")(_slope("OverloadK", _v))
    # Cost per candidate rises with K (pilot: upper/lower-half slope 1.35), so per segment.
    number(f"OverloadK.{_v}.slope500_1000", "{:.2f}")(_segment_slope("OverloadK", _v, 500, 1000))
    number(f"OverloadK.{_v}.slope2000_4000", "{:.2f}")(_segment_slope("OverloadK", _v, 2000, 4000))

# -O2: point ratios of marginal cost at the largest N.
for _a, _b in (("reflect_plain", "pfr"), ("reflect", "pfr"), ("reflect", "manual_unique"),
               ("reflect_plain", "p1061"), ("pfr_classic", "pfr"), ("reflect_split", "pfr_split"),
               ("manual", "manual_unique"), ("reflect_visit", "pfr"), ("reflect_visit", "reflect_plain")):
    number(f"FullN.{_a}/{_b}.point400", "{:.2f}")(_point_ratio("FullN", _a, _b, 400))
for _a, _b in (("glaze_classic", "glaze_native"), ("rflcpp", "rflcpp_native")):
    number(f"FullHeavy.{_a}/{_b}.point100", "{:.2f}")(_point_ratio("FullHeavy", _a, _b, 100))

# Backend A/B ratio as fields grow (marginal point ratios across M).
# (P1061's marginal cost at N = 50 is under ten timer steps up to M = 64 in the pilot, so
# it is no denominator here; FrontendN compares it with the native arm.)
for _a, _b in (("glaze_classic", "glaze_native"), ("rflcpp", "rflcpp_native"), ("pfr_classic", "pfr"),
               ("reflect_plain", "pfr")):
    for _m in (8, 16, 32, 64, 128):
        number(f"FrontendM.{_a}/{_b}.M{_m}", "{:.2f}")(_point_ratio("FrontendM", _a, _b, _m))


# FrontendM: the slope is the cost of one field added to each of the job's N structs;
# per struct-field = slope / N.
def _per_struct_field(arm):
    def fn(an):
        a = an["FrontendM"]
        n = a.jd.cells[0]["n"]
        s = a.slope(arm)
        return {"est": s["est"] / n, "ci": [c / n for c in s["ci"]],
                **({"warning": s["warning"]} if "warning" in s else {})}
    return fn


for _a in ("reflect", "reflect_plain", "p1061", "pfr", "pfr_classic", "manual_unique",
           "rflcpp", "rflcpp_native", "glaze_native", "glaze_classic"):
    number(f"FrontendM.{_a}.per_struct_field", "{:.3f}")(_per_struct_field(_a))

# Rounds sufficiency: relative 95% CI width of a headline slope with 5 and with 11 rounds.
def _ci_width(arm, rounds):
    def fn(an):
        widths = an["FrontendN"].ci_width_vs_rounds(arm)
        if rounds not in widths:
            raise ValueError(f"needs {rounds} rounds; the session has {an['FrontendN'].y.shape[2]}")
        return {"est": widths[rounds]}
    return fn


for _a in ("reflect_plain", "p1061", "pfr"):
    for _r in (5, 11):
        number(f"FrontendN.{_a}.ciw{_r}", "{:.1%}")(_ci_width(_a, _r))

# Several sessions: pooled headline ratios, and each headline slope's last/first session ratio.
HEADLINE = {
    "FrontendN": [("reflect_plain", "pfr"), ("reflect_plain", "p1061"), ("reflect", "reflect_plain"),
                  ("pfr_classic", "pfr"), ("reflect", "manual_unique"), ("reflect_visit", "pfr"),
                  ("p1061", "manual_unique")],
    "FrontendHeavy": [("glaze_classic", "glaze_native"), ("rflcpp", "rflcpp_native")],
    "FlagCost": [("pfr", "pfr_noflag"), ("p1061", "p1061_noflag"), ("manual_unique", "manual_unique_noflag")],
    "FlagCostHeavy": [("rflcpp", "rflcpp_noflag"), ("glaze_classic", "glaze_classic_noflag")],
    "CompilerFlag": [("p1061@GCC161", "p1061_noflag@GCC161"), ("p1061", "p1061_noflag"),
                     ("pfr@GCC161", "pfr_noflag@GCC161"), ("pfr", "pfr_noflag")],
    "HeteroN": [("reflect_plain", "p1061"), ("reflect_plain", "pfr"), ("reflect_plain", "manual_unique")],
    "HeteroHeavy": [("rflcpp", "rflcpp_native"), ("glaze_classic", "glaze_native"), ("reflect_plain", "pfr")],
    "RichN": [("reflect_plain", "manual_unique")],
    "CompilerN": [("reflect_plain@GCC161", "reflect_plain"), ("pfr@GCC161", "pfr"),
                  ("p1061@GCC161", "p1061"), ("manual_unique@GCC161", "manual_unique")],
    "CompilerHeavy": [("glaze_native@GCC161", "glaze_native"), ("glaze_classic@GCC161", "glaze_classic"),
                      ("rflcpp_native@GCC161", "rflcpp_native"), ("rflcpp@GCC161", "rflcpp")],
}
for _job, _pairs in HEADLINE.items():
    for _a, _b in _pairs:
        number(f"pooled.{_job}.{_a}/{_b}.ratio", "{:.2f}", POOLED)(
            lambda p, j=_job, a=_a, b=_b: p[j].ratio(a, b))
    for _arm in sorted({x for pair in _pairs for x in pair}):
        number(f"between.{_job}.{_arm}", "{:.3f}", POOLED)(lambda p, j=_job, a=_arm: p[j].between(a))
# GCC 16.1.0 vs 16.2.0 within one session (paired arms in the same rounds).
for _job, _pairs in (("CompilerN", HEADLINE["CompilerN"]), ("CompilerHeavy", HEADLINE["CompilerHeavy"])):
    for _a, _b in _pairs:
        number(f"{_job}.{_a}/{_b}.ratio", "{:.3f}")(_ratio(_job, _a, _b))
for _a in ("p1061", "pfr"):
    number(f"CompilerFlag.{_a}@GCC161.flag_slope_ratio", "{:.3f}")(
        _ratio("CompilerFlag", f"{_a}@GCC161", f"{_a}_noflag@GCC161"))
    # The same flag cost on GCC 16.2.0, from the same job and rounds (paired with the above).
    number(f"CompilerFlag.{_a}.flag_slope_ratio", "{:.3f}")(_ratio("CompilerFlag", _a, f"{_a}_noflag"))

# Peak working set of the compiler process per struct (KB), read from the exited process.
for _job, _arms in (("FrontendN", ("manual_unique", "p1061", "reflect_plain", "reflect", "pfr")),
                    ("FrontendHeavy", ("glaze_classic", "glaze_native", "rflcpp", "rflcpp_native"))):
    for _a in _arms:
        number(f"{_job}.{_a}.peak_ws_kb", "{:,.0f}")(_metric_slope(_job, _a, "os_peak_ws_mb", 1024.0))


# ---- Added for the final draft (2026-11-20 review) -------------------------------------

def _halves(job, arm):
    """Upper-half over lower-half slope of one curve (1 = straight line), with its interval."""
    def fn(an):
        lin = an[job].slope(arm)["linearity"]
        if lin["halves"] is None:
            raise ValueError(f"{job}.{arm}: halves not judged (flat curve)")
        return {"est": lin["halves"], "ci": lin["halves_ci"]}
    return fn


def _segment_ratio(job, a, b, x0, x1):
    """Ratio of two arms' slopes over the same segment [x0, x1]."""
    def fn(an):
        t = an[job]
        ia, ib, j0, j1 = t.ai(a), t.ai(b), t.xi(x0), t.xi(x1)
        na, nb = t.med[ia, j1] - t.med[ia, j0], t.med[ib, j1] - t.med[ib, j0]
        ba, bb = t.boot[ia, j1] - t.boot[ia, j0], t.boot[ib, j1] - t.boot[ib, j0]
        return {"est": float(na / nb), "ci": stats._ci(ba / bb)}
    return fn


def _slope_diff_ms(job, a, b):
    """Per-struct slope of a minus that of b (ms), with the paired bootstrap interval."""
    def fn(an):
        sa, sb = an[job].slope(a), an[job].slope(b)
        return {"est": sa["est"] - sb["est"], "ci": stats._ci(sa["_boot"] - sb["_boot"]),
                **stats._warnings((a, sa), (b, sb))}
    return fn


def _metric_ratio(job, a, b, metric):
    return lambda an: stats.Analysis(an[job].jd, metric).ratio(a, b)


def _metric_marginal(job, arm, x, metric, scale=1.0):
    def fn(an):
        m = stats.Analysis(an[job].jd, metric).marginal(arm, x)
        return {"est": m["est"] * scale, "ci": [c * scale for c in m["ci"]]}
    return fn


def _metric_point(job, arm, x, metric, scale=1.0):
    """Cell median at x (a whole translation unit), with its bootstrap interval."""
    def fn(an):
        p = stats.Analysis(an[job].jd, metric).point(arm, x)
        return {"est": p["median_s"] * scale, "ci": [c * scale for c in p["ci"]]}
    return fn


# Per-struct cost as N grows (FrontendN): first and last segment of the sweep, and the
# upper-half / lower-half slope ratio the linearity rule judges.
for _a in ("reflect_plain", "reflect", "reflect_visit", "p1061", "p1061_visit", "pfr", "pfr_native",
           "manual_unique", "xmacro_unique"):
    number(f"FrontendN.{_a}.slope0_500", "{:.2f}")(_segment_slope("FrontendN", _a, 0, 500))
    number(f"FrontendN.{_a}.slope2000_4000", "{:.2f}")(_segment_slope("FrontendN", _a, 2000, 4000))
    number(f"FrontendN.{_a}.halves", "{:.2f}")(_halves("FrontendN", _a))
for _a, _b in (("reflect_plain", "pfr"), ("reflect_plain", "p1061"), ("pfr_native", "pfr")):
    number(f"FrontendN.{_a}/{_b}.seg0_500", "{:.2f}")(_segment_ratio("FrontendN", _a, _b, 0, 500))
    number(f"FrontendN.{_a}/{_b}.seg2000_4000", "{:.2f}")(_segment_ratio("FrontendN", _a, _b, 2000, 4000))

# Ratios between mechanisms within CompilerN (N <= 2,000), on each compiler.
for _a, _b in (("reflect_plain", "pfr"), ("reflect_plain", "p1061"), ("reflect_plain", "manual_unique"),
               ("reflect", "reflect_plain")):
    number(f"CompilerN.{_a}/{_b}.ratio", "{:.2f}")(_ratio("CompilerN", _a, _b))
    number(f"CompilerN.{_a}@GCC161/{_b}@GCC161.ratio", "{:.2f}")(
        _ratio("CompilerN", f"{_a}@GCC161", f"{_b}@GCC161"))
# Without -freflection both compilers cost the same (CompilerFlag, same rounds).
for _a in ("p1061_noflag", "pfr_noflag"):
    number(f"CompilerFlag.{_a}@GCC161/{_a}.ratio", "{:.3f}")(_ratio("CompilerFlag", f"{_a}@GCC161", _a))

# Header context: the same object code with more headers, on every corpus.
for _job in ("RichN", "HeteroN"):
    number(f"{_job}.pfr_native/pfr.ratio", "{:.2f}")(_ratio(_job, "pfr_native", "pfr"))

# Native enumeration against hand-written code across corpora: ratio and absolute increment.
for _job in ("FrontendN", "RichN", "HeteroN"):
    number(f"{_job}.reflect_plain-manual_unique.diff_ms", "{:.2f}")(
        _slope_diff_ms(_job, "reflect_plain", "manual_unique"))
for _job in ("RichN", "HeteroN"):
    number(f"{_job}.reflect_plain/manual_unique.ratio", "{:.2f}")(_ratio(_job, "reflect_plain", "manual_unique"))
    number(f"{_job}.p1061/manual_unique.ratio", "{:.2f}")(_ratio(_job, "p1061", "manual_unique"))
number("RichN.reflect_plain/p1061.ratio", "{:.2f}")(_ratio("RichN", "reflect_plain", "p1061"))

# -ftime-report overhead per struct (external wall time, report / no report) and its effect
# on a ratio against hand-written code.
for _a in ("manual_unique", "reflect_plain", "pfr"):
    number(f"ReportOverhead.{_a}.wall_slope_ratio", "{:.3f}")(
        _metric_ratio("ReportOverhead", _a, f"{_a}_noreport", "wall_s"))
number("ReportOverhead.reflect_plain/manual_unique.wall_ratio", "{:.2f}")(
    _metric_ratio("ReportOverhead", "reflect_plain", "manual_unique", "wall_s"))
number("ReportOverhead.reflect_plain_noreport/manual_unique_noreport.wall_ratio", "{:.2f}")(
    _metric_ratio("ReportOverhead", "reflect_plain_noreport", "manual_unique_noreport", "wall_s"))
number("ReportOverhead.reflect_plain/pfr.wall_ratio", "{:.2f}")(
    _metric_ratio("ReportOverhead", "reflect_plain", "pfr", "wall_s"))
number("ReportOverhead.reflect_plain_noreport/pfr_noreport.wall_ratio", "{:.2f}")(
    _metric_ratio("ReportOverhead", "reflect_plain_noreport", "pfr_noreport", "wall_s"))


def _report_bias(an):
    """How much larger the native/hand-written per-struct ratio is without -ftime-report
    (external wall time): (ratio without / ratio with) - 1, paired bootstrap."""
    t = stats.Analysis(an["ReportOverhead"].jd, "wall_s")
    s = {a: t.slope(a)["_boot"] for a in ("reflect_plain", "manual_unique", "reflect_plain_noreport",
                                          "manual_unique_noreport")}
    e = {a: t.slope(a)["est"] for a in s}
    est = (e["reflect_plain_noreport"] / e["manual_unique_noreport"]) / (e["reflect_plain"] / e["manual_unique"]) - 1
    boot = (s["reflect_plain_noreport"] / s["manual_unique_noreport"]) / (s["reflect_plain"] / s["manual_unique"]) - 1
    return {"est": est, "ci": stats._ci(boot)}


number("ReportOverhead.reflect_plain/manual_unique.report_bias", "{:.0%}")(_report_bias)

# -O2: optimizer time (marginal, s) at N = 400, and the point ratios across N.
for _a in ("manual_unique", "xmacro_unique", "p1061", "reflect_plain", "reflect", "p1061_visit",
           "reflect_visit", "pfr", "pfr_classic"):
    number(f"FullN.{_a}.optgen400_s", "{:.2f}")(_metric_marginal("FullN", _a, 400, "ft_optgen_s"))
    number(f"FullN.{_a}.frontend400_s", "{:.2f}")(_metric_marginal("FullN", _a, 400, "ft_parsing_s"))
for _a, _b in (("reflect_plain", "pfr"), ("reflect_plain", "p1061"), ("reflect", "manual_unique"),
               ("pfr_classic", "pfr")):
    for _n in (50, 100, 200):
        number(f"FullN.{_a}/{_b}.point{_n}", "{:.2f}")(_point_ratio("FullN", _a, _b, _n))
for _a, _b in (("glaze_classic", "glaze_native"), ("rflcpp", "rflcpp_native")):
    for _n in (25, 50):
        number(f"FullHeavy.{_a}/{_b}.point{_n}", "{:.2f}")(_point_ratio("FullHeavy", _a, _b, _n))

# Whole translation units (fixed costs included): front-end TOTAL and peak working set.
for _a, _b in (("glaze_classic", "glaze_native"), ("rflcpp", "rflcpp_native")):
    for _n in (50, 200):
        number(f"FrontendHeavy.{_a}/{_b}.total{_n}", "{:.2f}")(
            _point_ratio("FrontendHeavy", _a, _b, _n, marginal=False))
for _a in ("reflect_plain", "pfr", "p1061_visit", "glaze_classic", "glaze_native", "rflcpp", "rflcpp_native"):
    for _n in (0, 200):
        number(f"FrontendHeavy.{_a}.total{_n}_s", "{:.2f}")(_metric_point("FrontendHeavy", _a, _n, "ft_total_s"))
        number(f"FrontendHeavy.{_a}.peak{_n}_mb", "{:.0f}")(_metric_point("FrontendHeavy", _a, _n, "os_peak_ws_mb"))
for _job, _arm, _x in (("FrontendM", "rflcpp", 128), ("FrontendM", "rflcpp_native", 128),
                       ("FrontendM", "glaze_native", 128), ("FrontendM", "glaze_classic", 128),
                       ("FrontendM", "reflect_plain", 128), ("FrontendN", "pfr_classic", 4000),
                       ("FrontendN", "pfr", 4000), ("FrontendN", "reflect_plain", 4000)):
    number(f"{_job}.{_arm}.peak{_x}_gb", "{:.1f}")(_metric_point(_job, _arm, _x, "os_peak_ws_mb", 1 / 1024))

# Field sweep: growth of the added cost from M = 64 to 128 (2 = linear in M).
for _a in ("glaze_native", "glaze_classic", "rflcpp_native", "rflcpp", "reflect_plain", "pfr"):
    number(f"FrontendM.{_a}.doubling", "{:.2f}")(_doubling("FrontendM", _a, 128))


def _between_all(p):
    """S2/S1 ratio of every per-unit slope that passes the linearity rule and rises by at
    least ten timer steps over its sweep: count, median and 90th percentile of |ratio - 1|,
    and how many within-session intervals exclude 1."""
    est, excl = [], 0
    for job, pooled in p.items():
        for arm in pooled.arms:
            try:
                b = pooled.between(arm)
                s0 = pooled.parts[0].slope(arm)
            except (ValueError, IndexError, ZeroDivisionError):
                continue
            rise = s0["est"] / 1000 * (pooled.xs[-1] - pooled.xs[0])
            if "warning" in b or not np.isfinite(b["est"]) or rise < 10 * stats.QUANTUM_S:
                continue
            est.append(b["est"])
            excl += int(not (b["ci"][0] <= 1 <= b["ci"][1]))
    dev = np.abs(np.array(est) - 1)
    return {"n": len(est), "median_dev": float(np.median(dev)), "p90_dev": float(np.percentile(dev, 90)),
            "max_dev": float(dev.max()), "excl1": excl}


for _f, _spec in (("n", "{:.0f}"), ("median_dev", "{:.1%}"), ("p90_dev", "{:.1%}"), ("max_dev", "{:.1%}"),
                  ("excl1", "{:.0f}")):
    number(f"between.all.{_f}", _spec, POOLED)(lambda p, f=_f: {"est": _between_all(p)[f]})
number("between.FrontendM.reflect_plain", "{:.3f}", POOLED)(lambda p: p["FrontendM"].between("reflect_plain"))
number("pooled.FrontendN.pfr_native/pfr.ratio", "{:.2f}", POOLED)(lambda p: p["FrontendN"].ratio("pfr_native", "pfr"))


def _last_point_ratio(job, a, b, x):
    """A point ratio in the last session (S2), to show that a non-slope headline reproduces."""
    return lambda p: p[job].parts[-1].point_ratio(a, b, x)


for _key, _args in (("FrontendN.pfr_classic/pfr.point500", ("FrontendN", "pfr_classic", "pfr", 500)),
                    ("FrontendN.pfr_classic/pfr.point4000", ("FrontendN", "pfr_classic", "pfr", 4000)),
                    ("FrontendM.glaze_classic/glaze_native.M128", ("FrontendM", "glaze_classic", "glaze_native", 128)),
                    ("FrontendM.reflect_plain/pfr.M128", ("FrontendM", "reflect_plain", "pfr", 128)),
                    ("FullN.reflect_plain/pfr.point400", ("FullN", "reflect_plain", "pfr", 400)),
                    ("FullN.reflect_plain/p1061.point400", ("FullN", "reflect_plain", "p1061", 400))):
    number(f"last.{_key}", "{:.2f}" if "M128" in _key or "FullN" in _key else "{:.1f}", POOLED)(
        _last_point_ratio(*_args))

# Native against Boost.PFR at fixed N (FrontendN), native's marginal cost per struct, and
# the remaining keys the final text uses.
for _n in (500, 1000, 2000, 4000):
    number(f"FrontendN.reflect_plain/pfr.point{_n}", "{:.2f}")(_point_ratio("FrontendN", "reflect_plain", "pfr", _n))
for _n in (500, 4000):
    number(f"FrontendN.reflect_plain.per_struct{_n}", "{:.2f}")(_per_struct_at("FrontendN", "reflect_plain", _n))
# Added in review round 3 (2026-11-21): the span form's concurrent name-lookup timer, whole
# translation unit (cell median), where its per-struct cost rises with N.
for _n in (1000, 4000):
    number(f"FrontendN.reflect_plain.name_lookup{_n}_s", "{:.2f}")(
        _metric_point("FrontendN", "reflect_plain", _n, "ft_name_lookup_s"))
number("FrontendN.pfr_native.ggc_kb", "{:.0f}")(_metric_slope("FrontendN", "pfr_native", "ggc_total_mb", 1024.0))
number("HeteroN.pfr_classic.halves", "{:.2f}")(_halves("HeteroN", "pfr_classic"))
number("RichN.pfr_classic.halves", "{:.2f}")(_halves("RichN", "pfr_classic"))
for _a, _b in (("glaze_classic", "glaze_native"), ("rflcpp", "rflcpp_native")):
    for _n in (50, 200):
        number(f"FrontendHeavy.{_a}/{_b}.point{_n}", "{:.2f}")(_point_ratio("FrontendHeavy", _a, _b, _n))
for _a in ("rflcpp_native", "glaze_native", "rflcpp", "glaze_classic"):
    number(f"FrontendHeavy.{_a}.halves", "{:.2f}")(_halves("FrontendHeavy", _a))
number("OverloadN.ovl_hidden_friend.halves", "{:.2f}")(_halves("OverloadN", "ovl_hidden_friend"))
# Backend A/Bs within each compiler version, and the native arm's version ratio, in CompilerHeavy.
for _a, _b in (("glaze_classic", "glaze_native"), ("rflcpp", "rflcpp_native")):
    for _t in ("", "@GCC161"):
        number(f"CompilerHeavy.{_a}{_t}/{_b}{_t}.ratio", "{:.2f}")(_ratio("CompilerHeavy", f"{_a}{_t}", f"{_b}{_t}"))
number("CompilerHeavy.reflect_plain@GCC161/reflect_plain.ratio", "{:.3f}")(
    _ratio("CompilerHeavy", "reflect_plain@GCC161", "reflect_plain"))
number("HeteroN.pfr_classic/pfr.point1600", "{:.2f}")(_point_ratio("HeteroN", "pfr_classic", "pfr", 1600))


# ---- Added for the second review round (2026-11-20) ------------------------------------

def _nonopt_marginal(job, arm, x):
    """Marginal cost at x outside GCC's optimization-and-generation phase (TOTAL minus
    `phase opt and generate`), in s; paired bootstrap (both metrics share the round draws)."""
    def fn(an):
        t = an[job]
        o = stats.Analysis(t.jd, "ft_optgen_s", t.seed)
        i, j, j0 = t.ai(arm), t.xi(x), t.xi(0)
        est = (t.med[i, j] - t.med[i, j0]) - (o.med[i, j] - o.med[i, j0])
        boot = (t.boot[i, j] - t.boot[i, j0]) - (o.boot[i, j] - o.boot[i, j0])
        return {"est": float(est), "ci": stats._ci(boot)}
    return fn


# -O2: the time outside the optimizer, to locate the native / Boost.PFR difference.
for _a in ("manual_unique", "p1061", "p1061_visit", "reflect_plain", "reflect_visit", "pfr"):
    number(f"FullN.{_a}.nonopt400_s", "{:.2f}")(_nonopt_marginal("FullN", _a, 400))

# The SFINAE-guarded template idiom against plain free functions: where its time goes, and
# its GGC memory, at N = 1,000 (OverloadN is not linear, so shares of marginal cost).
for _v in ("ovl_constrained", "ovl_flat"):
    for _t, _k in (("ft_overload_s", "overload"), ("ft_tmpl_inst_s", "tmpl_inst"),
                   ("ft_consteval_s", "consteval")):
        number(f"OverloadN.{_v}.share1000.{_k}", "{:.0%}")(_point_share("OverloadN", _v, _t, 1000))
    number(f"OverloadN.{_v}.ggc1000_mb", "{:,.0f}")(_metric_marginal("OverloadN", _v, 1000, "ggc_total_mb"))

# S2 values of the new headline comparisons.
number("last.FrontendN.reflect_visit/pfr.ratio", "{:.2f}", POOLED)(
    lambda p: p["FrontendN"].parts[-1].ratio("reflect_visit", "pfr"))
number("last.FullN.reflect_visit/pfr.point400", "{:.2f}", POOLED)(
    _last_point_ratio("FullN", "reflect_visit", "pfr", 400))
number("last.CompilerFlag.p1061@GCC161.flag_slope_ratio", "{:.2f}", POOLED)(
    lambda p: p["CompilerFlag"].parts[-1].ratio("p1061@GCC161", "p1061_noflag@GCC161"))


def _between_headline(pick):
    """Smallest or largest S2/S1 ratio over the slopes behind the headline numbers (every arm
    of HEADLINE whose curve is linear; the non-linear ones, Boost.PFR's C++17 path, enter
    the headlines as point ratios, whose S2 values are the last.* keys); the note names the
    slope."""
    def fn(p):
        vals, skipped = [], []
        for job, pairs in HEADLINE.items():
            for arm in sorted({x for pair in pairs for x in pair}):
                b = p[job].between(arm)
                if "warning" in b:
                    skipped.append(f"{job}.{arm}")
                    continue
                vals.append((b["est"], f"{job}.{arm}", b["ci"]))
        est, name, ci = pick(vals)
        return {"est": est, "ci": ci, "note": f"{name}; {len(vals)} slopes; not linear: {', '.join(skipped)}"}
    return fn


number("between.headline.min", "{:.3f}", POOLED)(_between_headline(min))
number("between.headline.max", "{:.3f}", POOLED)(_between_headline(max))


# ---- Supplementary session S3: native formulations (job FrontendIdiom) -------------------

# Registered before S3's data exist (2026-11-20). Primary numbers: the slope ratios between
# formulations; if a slope carries a linearity warning, the marginal-cost ratios at N = 1,000
# and 4,000 and the marginal cost per struct at N = 500 and 4,000 are reported instead.
_NATIVE = ("reflect_plain", "reflect_array", "reflect_index", "reflect_seq")
_IDIOM = _NATIVE + ("p1061", "pfr", "manual_unique")
for _a in _IDIOM:
    number(f"FrontendIdiom.{_a}.slope", "{:.2f}", SUPPLEMENTARY)(_slope("FrontendIdiom", _a))
_IDIOM_PAIRS = [(a, "reflect_plain") for a in _NATIVE[1:]] + [
    ("reflect_index", "reflect_seq"), ("reflect_array", "reflect_seq"), ("reflect_index", "reflect_array")] + [
    (a, b) for a in _NATIVE for b in ("p1061", "pfr", "manual_unique")] + [("p1061", "manual_unique")]
for _a, _b in _IDIOM_PAIRS:
    number(f"FrontendIdiom.{_a}/{_b}.ratio", "{:.2f}", SUPPLEMENTARY)(_ratio("FrontendIdiom", _a, _b))
for _a, _b in _IDIOM_PAIRS:
    for _n in (1000, 4000):
        number(f"FrontendIdiom.{_a}/{_b}.point{_n}", "{:.2f}", SUPPLEMENTARY)(
            _point_ratio("FrontendIdiom", _a, _b, _n))
for _a in _NATIVE:
    number(f"FrontendIdiom.{_a}.halves", "{:.2f}", SUPPLEMENTARY)(_halves("FrontendIdiom", _a))
    for _n in (500, 4000):
        number(f"FrontendIdiom.{_a}.per_struct{_n}", "{:.2f}", SUPPLEMENTARY)(
            _per_struct_at("FrontendIdiom", _a, _n))
    for _t, _k in (("ft_consteval_s", "consteval"), ("ft_tmpl_inst_s", "tmpl_inst"),
                   ("ft_overload_s", "overload")):
        number(f"FrontendIdiom.{_a}.share.{_k}", "{:.0%}", SUPPLEMENTARY)(_share("FrontendIdiom", _a, _t))
    number(f"FrontendIdiom.{_a}-manual_unique.diff_ms", "{:.2f}", SUPPLEMENTARY)(
        _slope_diff_ms("FrontendIdiom", _a, "manual_unique"))
for _a in _NATIVE + ("p1061",):
    number(f"FrontendIdiom.{_a}.ggc_kb", "{:.0f}", SUPPLEMENTARY)(
        _metric_slope("FrontendIdiom", _a, "ggc_total_mb", 1024.0))
# Sentinel (reflect_plain, N = 1,000): the same compile as S1/S2's FrontendN sentinel.
number("FrontendIdiom.reflect_plain.n1000_s", "{:.2f}", SUPPLEMENTARY)(
    _metric_point("FrontendIdiom", "reflect_plain", 1000, "ft_total_s"))
# Added after S3 (review round 3, 2026-11-21): whole translation units, fixed costs included.
for _n in (1000, 4000):
    number(f"FrontendIdiom.reflect_array/reflect_plain.total{_n}", "{:.2f}", SUPPLEMENTARY)(
        _point_ratio("FrontendIdiom", "reflect_array", "reflect_plain", _n, marginal=False))


def session_numbers(session_dir: pathlib.Path, rows: list[dict]) -> dict:
    """Per session: compiles, the machine load during measured compiles, and how much the
    per-arm slopes move when every compile that ran above 15% load is dropped."""
    name = session_dir.name
    measured = [r for r in rows if not r["warmup"] and np.isfinite(r.get("load_pct", np.nan))]
    load = np.array([r["load_pct"] for r in measured])
    out = {f"{name}.compiles": {"est": float(len(rows))},
           f"{name}.load.median_pct": {"est": float(np.median(load))},
           f"{name}.load.p99_pct": {"est": float(np.percentile(load, 99))},
           f"{name}.load.above15_share": {"est": float(np.mean(load > 15))}}
    full = stats.job_data(rows, session_dir)
    quiet = stats.job_data([r for r in rows if not (r.get("load_pct", 0) > 15)], session_dir)
    changes = []
    for key, jd in full.items():
        if key not in quiet or jd.report_less():
            continue
        a, b = stats.Analysis(jd), stats.Analysis(quiet[key])
        for arm in jd.arms:
            try:
                sa, sb = a.slope(arm), b.slope(arm)
            except (ValueError, IndexError):
                continue
            rise = sa["est"] / 1000 * (jd.xs[-1] - jd.xs[0])
            if "warning" in sa or rise < 10 * stats.QUANTUM_S or not np.isfinite(sb["est"]):
                continue
            changes.append(abs(sb["est"] / sa["est"] - 1))
    ch = np.array(changes)
    out.update({f"{name}.sens15.n": {"est": float(len(ch))},
                f"{name}.sens15.within1pct": {"est": float(np.sum(ch <= 0.01))},
                f"{name}.sens15.max_change": {"est": float(ch.max()) if ch.size else float("nan")}})
    # Off-CPU time: for compiles over 2 s, TOTAL against the process's CPU time (user + kernel,
    # which also covers process start-up).
    long = [r for r in measured if r.get("ft_total_s", 0) > 2 and np.isfinite(r.get("os_user_s", np.nan))]
    dev = np.array([abs(r["ft_total_s"] / (r["os_user_s"] + r["os_kernel_s"]) - 1) for r in long])
    out[f"{name}.total_cpu.within3pct"] = {"est": float(np.mean(dev <= 0.03))}
    out[f"{name}.total_cpu.n"] = {"est": float(len(dev))}
    # Drift: the largest deviation of a sentinel compile from its job's median.
    out[f"{name}.sentinel.max_dev"] = {"est": max(stats.sentinel_summary(jd)["max_rel_dev"]
                                                   for jd in full.values() if jd.sentinel)}
    return out


SESSION_FORMATS = {"compiles": "{:,.0f}", "load.median_pct": "{:.1f}", "load.p99_pct": "{:.0f}",
                   "load.above15_share": "{:.1%}", "sens15.n": "{:.0f}", "sens15.within1pct": "{:.0f}",
                   "sens15.max_change": "{:.1%}", "total_cpu.within3pct": "{:.1%}", "total_cpu.n": "{:,.0f}",
                   "sentinel.max_dev": "{:.1%}"}


# ---- Static numbers: corpus shape and maintainability (computed, not measured) --------

def _static(value):
    return lambda an: {"est": value}


import generate as _gen  # noqa: E402

_hd = _gen.describe(1600, 8, "hetero")
number("corpus.hetero.fields_total", "{:,}")(_static(_hd["fields_total"]))
number("corpus.hetero.fields_median", "{:d}")(_static(_hd["fields_median"]))
number("corpus.hetero.fields_max", "{:d}")(_static(_hd["fields_max"]))
for _k, _v in _hd["kind_share"].items():
    number(f"corpus.hetero.share.{_k}", "{:.0%}")(_static(_v))
_pt = _gen.per_type_cost(16)
number("loc.manual.per_type_lines", "{:d}")(_static(_pt["manual"]["lines"]))
number("loc.xmacro.per_type_lines", "{:d}")(_static(_pt["xmacro"]["lines"]))
for _fam in ("reflect", "reflect_plain", "reflect_visit", "reflect_array", "reflect_index", "reflect_seq",
             "p1061", "p1061_visit", "pfr", "rflcpp",
             "glaze", "xmacro"):
    number(f"loc.{_fam}.fixed_lines", "{:d}")(_static(_gen.fixed_loc(_fam)))


# ---- Probe numbers: Boost.PFR's C++17 path (pfrprobe.py -> Data/PfrProbe.json, §4.3) ----

PROBE = {"path": PROJECT / "Data" / "PfrProbe.json", "allow_pilot": False}


def _probe_result() -> dict:
    path = pathlib.Path(PROBE["path"])
    if not path.is_file():
        raise ValueError(f"{path.name} missing: run pfrprobe.py")
    data = json.loads(path.read_text())
    if data.get("pilot") and not PROBE["allow_pilot"]:
        raise ValueError(f"{path.name} is a pilot probe (not citable)")
    return data["result"]


def _probe(part, config, n, field):
    return lambda an: {"est": _probe_result()[part][config][str(n)][field]}


def _probe_overload_share(pick, n=4000):
    """Smallest or largest share of TOTAL that overload resolution takes, over part A."""
    def fn(an):
        a = _probe_result()["A"]
        return {"est": pick(c[str(n)]["overload_s"] / c[str(n)]["total_s"] for c in a.values())}
    return fn


for _n in (1000, 2000, 4000):
    number(f"probe.A.GCC152.cxx20.n{_n}.total_s", "{:.0f}")(_probe("A", "GCC152.cxx20", _n, "total_s"))
number("probe.A.overload_share4000.min", "{:.0%}")(_probe_overload_share(min))
number("probe.A.overload_share4000.max", "{:.0%}")(_probe_overload_share(max))
for _n in (500, 1000, 2000):
    for _v in ("fields_count", "probe"):
        number(f"probe.B.{_v}.n{_n}.overload_s", "{:.2f}")(_probe("B", _v, _n, "overload_s"))
for _v in ("for_each_field", "tie_given_count", "copy", "no_add_pointer", "bare", "binding"):
    number(f"probe.B.{_v}.n2000.overload_s", "{:.2f}")(_probe("B", _v, 2000, "overload_s"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("sessions", nargs="+")
    ap.add_argument("--allow-pilot", action="store_true")
    ap.add_argument("--out", default=str(PROJECT / "Data" / "PaperNumbers.json"))
    ap.add_argument("--probe", default=str(PROBE["path"]), help="pfrprobe.py output")
    args = ap.parse_args()
    PROBE.update(path=pathlib.Path(args.probe), allow_pilot=args.allow_pilot)
    res = compute([pathlib.Path(s) for s in args.sessions], args.allow_pilot)
    pathlib.Path(args.out).write_text(json.dumps(res, indent=1))
    errors = [k for k, v in res["numbers"].items() if "error" in v]
    warnings = [k for k, v in res["numbers"].items() if "warning" in v]
    print(f"{len(res['numbers'])} numbers -> {args.out}; {len(errors)} errors, {len(warnings)} warnings")
    for k in errors:
        print(f"  error   {k}: {res['numbers'][k]['error']}")
    for k in warnings:
        print(f"  warning {k}: {res['numbers'][k]['warning']}")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
