# SPDX-License-Identifier: MIT
"""Statistics from raw session data.

Per cell (arm x sweep value) the estimate is the median over measured rounds. Only the
accepted attempt of each round is used (campaign.py stores every attempt). Uncertainty
comes from a round bootstrap: rounds are resampled with replacement and every statistic
(cell medians, slopes, ratios, shares, crossovers) is recomputed on the same resample.
A round contains every cell of its job once, in random order, so the bootstrap keeps the
within-round correlation between arms. -ftime-report prints wall time in 10 ms steps;
each resampled value gets independent uniform jitter of one step (a smoothed
bootstrap), so intervals of small, mostly identical values do not collapse to zero
width. Intervals are 95% percentile intervals within one session; `Pooled` combines
sessions with a two-level bootstrap and reports the ratio between sessions.

    python stats.py Data/Sessions/S1 [Data/Sessions/S2 ...] [--allow-pilot]
"""
from __future__ import annotations
import csv
import json
import pathlib
import sys
from dataclasses import dataclass, field

import numpy as np

B = 4000
SEED = 20261030
QUANTUM_S = 0.01  # -ftime-report prints wall time in 10 ms steps
NUMERIC = {"round", "attempt", "accepted", "warmup", "seq", "x", "n", "m", "k", "c"}


class NotCitable(Exception):
    pass


def session_state(session_dir: pathlib.Path) -> dict:
    path = session_dir / "session.json"
    return json.loads(path.read_text()) if path.is_file() else {}


def load_rows(session_dir: pathlib.Path, allow_pilot: bool = False) -> list[dict]:
    """Rows of the accepted attempt of every completed round. A pilot session (preflight
    skipped or non-protocol rounds) is refused unless allow_pilot."""
    state = session_state(session_dir)
    if not allow_pilot:
        if not state:
            raise NotCitable(f"{session_dir}: no session.json")
        if state.get("pilot"):
            raise NotCitable(f"{session_dir}: pilot session (not citable); pass --allow-pilot")
        failed = [t for t in state.get("compilers", {}) if not state.get("preflight", {}).get(t, {}).get("ok")]
        if failed:
            raise NotCitable(f"{session_dir}: no passing preflight for {failed}")
    done = json.loads((session_dir / "rounds.json").read_text())
    rows = {}
    with open(session_dir / "raw.csv", newline="") as f:
        for r in csv.DictReader(f):
            if str(r["round"]) not in done.get(r["job"], {}):
                continue
            if r.get("accepted", "1") not in ("1", 1):
                continue
            row = {}
            for k, v in r.items():
                if k in NUMERIC:
                    row[k] = int(v)
                elif k.startswith(("ft_", "ggc_", "wall_", "os_", "load_", "pcore_")):
                    row[k] = float(v) if v not in ("", None) else np.nan
                else:
                    row[k] = v
            # A round written twice (crash between data and progress file): keep the last.
            rows[(row["job"], row["round"], row["kind"], row["arm"], row["x"], row["seq"])] = row
    return list(rows.values())


@dataclass
class JobData:
    session: str
    job: str
    dim: str
    mode: str
    corpus: str
    arms: list[str]
    xs: np.ndarray
    rounds: list[int]
    cells: list[dict] = field(repr=False, default_factory=list)
    sentinel: list[dict] = field(repr=False, default_factory=list)
    flagged_rounds: int = 0

    def array(self, metric: str = "ft_total_s") -> np.ndarray:
        """Shape (arms, xs, rounds)."""
        a = np.full((len(self.arms), len(self.xs), len(self.rounds)), np.nan)
        ai = {arm: i for i, arm in enumerate(self.arms)}
        xi = {int(x): i for i, x in enumerate(self.xs)}
        ri = {r: i for i, r in enumerate(self.rounds)}
        for row in self.cells:
            a[ai[row["arm"]], xi[row["x"]], ri[row["round"]]] = row.get(metric, np.nan)
        return a

    def report_less(self) -> bool:
        """True when some arm has no -ftime-report (compare on external wall time)."""
        return any(np.isnan(r.get("ft_total_s", np.nan)) for r in self.cells)


def job_data(rows: list[dict], session_dir: pathlib.Path | None = None) -> dict[tuple[str, str], JobData]:
    out = {}
    for row in rows:
        if row["warmup"]:
            continue
        key = (row["session"], row["job"])
        jd = out.get(key)
        if jd is None:
            jd = out[key] = JobData(row["session"], row["job"], row["dim"], row["mode"],
                                    row["corpus"], [], np.array([]), [])
        (jd.cells if row["kind"] == "cell" else jd.sentinel).append(row)
    done = json.loads((session_dir / "rounds.json").read_text()) if session_dir else {}
    for jd in out.values():
        jd.arms = sorted({r["arm"] for r in jd.cells})
        jd.xs = np.array(sorted({r["x"] for r in jd.cells}), dtype=float)
        jd.rounds = sorted({r["round"] for r in jd.cells})
        jd.flagged_rounds = sum(1 for r, v in done.get(jd.job, {}).items()
                                if v.get("load_flagged") and int(r) in jd.rounds)
        compilers = {}
        for r in jd.cells:
            compilers.setdefault(r.get("compiler_tag", "default"), set()).add(r.get("compiler", ""))
        mixed = {t: c for t, c in compilers.items() if len(c) > 1}
        if mixed:
            raise ValueError(f"{jd.session}/{jd.job}: more than one compiler under one tag: {mixed}")
    return out


def _slopes(med: np.ndarray, xs: np.ndarray) -> np.ndarray:
    """OLS slope along the x axis (axis 1) of an array shaped (arms, xs, ...)."""
    xc = xs - xs.mean()
    shape = (1, len(xs)) + (1,) * (med.ndim - 2)
    xr = xc.reshape(shape)
    return (xr * (med - med.mean(axis=1, keepdims=True))).sum(axis=1) / (xc ** 2).sum()


def _quad(med: np.ndarray, xs: np.ndarray) -> np.ndarray:
    """Least-squares (c0, c1, c2) of y = c0 + c1 x + c2 x^2 along axis 1."""
    d = np.vstack([np.ones_like(xs), xs, xs ** 2]).T
    pinv = np.linalg.pinv(d)                       # (3, X)
    return np.tensordot(pinv, med, axes=([1], [1]))  # (3, arms, ...)


def _ci(samples: np.ndarray) -> list[float]:
    samples = np.asarray(samples, dtype=float)
    if samples.size == 0 or np.all(np.isnan(samples)):
        return [float("nan"), float("nan")]
    lo, hi = np.nanpercentile(samples, [2.5, 97.5], axis=-1)
    return [float(lo), float(hi)]


R2_WARN = 0.98
HALVES_LINEAR = (0.8, 1.25)  # upper-half over lower-half slope still read as a line


def _linearity(med: np.ndarray, boot: np.ndarray, xs: np.ndarray) -> dict:
    """Linearity of one curve (med shaped (X,), boot (X, B)). `halves` is the slope over
    the upper half of the sweep over the slope over the lower half: 1 for a line, 3 for a
    parabola through the origin. It is judged only when both halves rise by at least 10
    timer steps; a flatter curve cannot show curvature above the timer resolution. `r2`
    and the largest residual come from the linear fit of the medians."""
    out = {"r2": None, "max_resid_s": None, "halves": None, "halves_ci": None}
    if np.any(np.isnan(med)):
        return out
    fit = np.polyval(np.polyfit(xs, med, 1), xs)
    sst = ((med - med.mean()) ** 2).sum()
    out["r2"] = float(1 - ((med - fit) ** 2).sum() / sst) if sst else None
    out["max_resid_s"] = float(np.max(np.abs(med - fit)))
    mid = np.where(xs == xs[-1] / 2)[0]
    if len(mid) and xs[-1] / 2 > xs[0]:
        j = mid[0]
        if min(med[j] - med[0], med[-1] - med[j]) >= 10 * QUANTUM_S:
            def halves(m):
                return ((m[-1] - m[j]) / (xs[-1] - xs[j])) / ((m[j] - m[0]) / (xs[j] - xs[0]))
            out["halves"] = float(halves(med))
            with np.errstate(divide="ignore", invalid="ignore"):
                out["halves_ci"] = _ci(halves(boot))
    return out


def _nonlinear(lin: dict) -> str | None:
    """A warning when the curve bends by more than HALVES_LINEAR allows and its interval
    excludes a line, or when the linear fit misses by more than three timer steps."""
    h, ci = lin["halves"], lin["halves_ci"]
    if h is not None and not HALVES_LINEAR[0] <= h <= HALVES_LINEAR[1] and not ci[0] <= 1 <= ci[1]:
        return f"not linear: upper/lower-half slope {h:.2f} [{ci[0]:.2f}, {ci[1]:.2f}] (line = 1)"
    if lin["r2"] is not None and lin["r2"] < R2_WARN and lin["max_resid_s"] > 3 * QUANTUM_S:
        return f"not linear: R2 = {lin['r2']:.3f}, largest residual {lin['max_resid_s'] * 1000:.0f} ms"
    return None


def _warnings(*parts: tuple[str, dict]) -> dict:
    """{'warning': ...} naming the arm of every part that carries one, else {}."""
    ws = [f"{name}: {r['warning']}" for name, r in parts if r.get("warning")]
    return {"warning": "; ".join(ws)} if ws else {}


class Analysis:
    """Point estimates and round-bootstrap distributions for one session's job."""

    def __init__(self, jd: JobData, metric: str = "ft_total_s", seed: int = SEED):
        # One seed per session: every metric of one session shares its round draws (so
        # metrics and arms stay paired), and different sessions draw independently.
        self.jd = jd
        self.metric = metric
        self.seed = seed
        self.y = jd.array(metric)                    # (A, X, R)
        r = self.y.shape[2]
        rng = np.random.default_rng(seed)
        self.idx = rng.integers(0, r, size=(B, r))
        self.med = np.nanmedian(self.y, axis=2)       # (A, X)
        draw = self.y[:, :, self.idx]                 # (A, X, B, R)
        if metric.startswith("ft_"):
            # GCC rounds each timer separately, so each metric gets its own jitter stream;
            # the round draws (self.idx) stay shared, which keeps metrics paired.
            jitter = np.random.default_rng([seed, *metric.encode()])
            draw = draw + jitter.uniform(-QUANTUM_S / 2, QUANTUM_S / 2, size=draw.shape)
        self.boot = np.nanmedian(draw, axis=3)        # (A, X, B)

    def ai(self, arm: str) -> int:
        return self.jd.arms.index(arm)

    def xi(self, x: float) -> int:
        return int(np.where(self.jd.xs == x)[0][0])

    def slope(self, arm: str, unit: float = 1000.0) -> dict:
        i = self.ai(arm)
        est = _slopes(self.med[i:i + 1], self.jd.xs)[0] * unit
        bs = _slopes(self.boot[i:i + 1], self.jd.xs)[0] * unit
        lin = _linearity(self.med[i], self.boot[i], self.jd.xs)
        out = {"est": float(est), "ci": _ci(bs), "r2": lin["r2"], "linearity": lin, "_boot": bs}
        if (w := _nonlinear(lin)):
            out["warning"] = w
        return out

    def ratio(self, a: str, b: str) -> dict:
        sa, sb = self.slope(a), self.slope(b)
        return {"est": sa["est"] / sb["est"], "ci": _ci(sa["_boot"] / sb["_boot"]),
                **_warnings((a, sa), (b, sb))}

    def point(self, arm: str, x: float) -> dict:
        i, j = self.ai(arm), self.xi(x)
        vals = self.y[i, j]
        med = float(np.nanmedian(vals))
        mad = float(np.nanmedian(np.abs(vals - med)))
        return {"median_s": med, "ci": _ci(self.boot[i, j]), "mad_s": mad,
                "runs": int(np.sum(~np.isnan(vals))), "distinct": int(len(set(vals[~np.isnan(vals)])))}

    def marginal(self, arm: str, x: float) -> dict:
        i, j, j0 = self.ai(arm), self.xi(x), self.xi(0)
        return {"est": float(self.med[i, j] - self.med[i, j0]),
                "ci": _ci(self.boot[i, j] - self.boot[i, j0])}

    def point_ratio(self, a: str, b: str, x: float, marginal: bool = True) -> dict:
        ia, ib, j = self.ai(a), self.ai(b), self.xi(x)
        if marginal:
            j0 = self.xi(0)
            na, nb = self.med[ia, j] - self.med[ia, j0], self.med[ib, j] - self.med[ib, j0]
            ba, bb = self.boot[ia, j] - self.boot[ia, j0], self.boot[ib, j] - self.boot[ib, j0]
        else:
            na, nb, ba, bb = self.med[ia, j], self.med[ib, j], self.boot[ia, j], self.boot[ib, j]
        if self.metric.startswith("ft_") and abs(nb) < QUANTUM_S / 2:
            raise ValueError(f"{b} at {x:g}: denominator below the timer resolution")
        with np.errstate(divide="ignore", invalid="ignore"):
            out = {"est": float(na / nb), "ci": _ci(ba / bb)}
        if self.metric.startswith("ft_") and min(abs(na), abs(nb)) < 10 * QUANTUM_S:
            out["warning"] = "denominator or numerator under 10 timer steps"
        return out

    def quadratic(self, arm: str) -> dict:
        i = self.ai(arm)
        est = _quad(self.med[i:i + 1], self.jd.xs)[:, 0]
        bs = _quad(self.boot[i:i + 1], self.jd.xs)[:, 0]
        return {"c": [float(v) for v in est], "c2_ci": _ci(bs[2]), "_boot": bs}

    def crossover(self, quad_arm: str, lin_arm: str) -> dict:
        """x where the quadratic fit of one arm meets the linear fit of another, inside the
        measured range's domain (x >= max(0, min x)); NaN where the curves do not cross."""
        q, l = self.quadratic(quad_arm), self.ai(lin_arm)
        lin_est = np.polyfit(self.jd.xs, self.med[l], 1)
        lb_slope = _slopes(self.boot[l:l + 1], self.jd.xs)[0]
        lb_icpt = self.boot[l].mean(axis=0) - lb_slope * self.jd.xs.mean()
        lo = max(0.0, float(self.jd.xs.min()))

        def root(c0, c1, c2, s, i0):
            a, b, c = np.asarray(c2), np.asarray(c1 - s), np.asarray(c0 - i0)
            disc = b * b - 4 * a * c
            with np.errstate(invalid="ignore", divide="ignore"):
                r = (-b + np.sqrt(disc)) / (2 * a)
            return np.where((disc >= 0) & (a > 0) & (r >= lo), r, np.nan)

        est = root(*q["c"], lin_est[0], lin_est[1])
        bs = root(q["_boot"][0], q["_boot"][1], q["_boot"][2], lb_slope, lb_icpt)
        return {"est": float(est), "ci": _ci(bs), "undefined_share": float(np.mean(np.isnan(bs)))}

    def share(self, arm: str, timer: str) -> dict:
        """Share of the arm's per-unit cost that one -ftime-report timer accounts for."""
        t = Analysis(self.jd, timer, self.seed)
        st, s = t.slope(arm), self.slope(arm)
        # A share of slopes means something only when the arm's total is linear.
        return {"est": st["est"] / s["est"], "ci": _ci(st["_boot"] / s["_boot"]),
                "timer_slope": {"est": st["est"], "ci": st["ci"]}, **_warnings((arm, s))}

    def point_share(self, arm: str, timer: str, x: float) -> dict:
        """Share of the arm's marginal cost at x (cost at x minus cost at 0) that one
        -ftime-report timer accounts for. For curves that are not linear, where a share
        of slopes would average over the sweep."""
        t = Analysis(self.jd, timer, self.seed)
        i, j, j0 = self.ai(arm), self.xi(x), self.xi(0)
        num, den = t.med[i, j] - t.med[i, j0], self.med[i, j] - self.med[i, j0]
        bn, bd = t.boot[i, j] - t.boot[i, j0], self.boot[i, j] - self.boot[i, j0]
        return {"est": float(num / den), "ci": _ci(bn / bd)}

    def monotonic(self, arm: str):
        m = self.med[self.ai(arm)]
        if np.any(np.isnan(m)):
            return None
        return bool(np.all(np.diff(m) >= -2 * QUANTUM_S))

    def ci_width_vs_rounds(self, arm: str, counts=(3, 5, 7, 9, 11)) -> dict:
        """Relative 95% CI width of the arm's slope when only r rounds are used: shows
        whether the number of rounds suffices (Barrett et al. 2017 check their run
        count the same way)."""
        i, r_all = self.ai(arm), self.y.shape[2]
        rng = np.random.default_rng(self.seed + 1)
        out = {}
        for r in (c for c in counts if c <= r_all):
            idx = rng.integers(0, r_all, size=(B // 4, r))
            draw = self.y[i:i + 1][:, :, idx]
            if self.metric.startswith("ft_"):
                draw = draw + rng.uniform(-QUANTUM_S / 2, QUANTUM_S / 2, size=draw.shape)
            s = _slopes(np.nanmedian(draw, axis=3), self.jd.xs)[0]
            lo, hi = np.nanpercentile(s, [2.5, 97.5])
            out[r] = float((hi - lo) / abs(np.nanmedian(s))) if np.nanmedian(s) else float("nan")
        return out


class Pooled:
    """One job measured in several sessions with the same compilers. Point estimate: the
    mean over sessions of each session's cell medians. Interval: two-level bootstrap
    (sessions, then rounds within each session; Kalibera & Jones 2012/2020, Field & Welsh
    2007). With few sessions the session level is coarse, so the between-session ratio is
    reported too."""

    def __init__(self, parts: list[JobData], metric: str = "ft_total_s"):
        # Independent round draws per session (the first keeps SEED, so its numbers equal
        # a single-session Analysis); a shared seed would pair the sessions' bootstrap
        # distributions and narrow the between-session intervals.
        self.parts = [Analysis(jd, metric, SEED + i) for i, jd in enumerate(parts)]
        self.xs = parts[0].xs
        comps = [{(r.get("compiler_tag"), r.get("compiler")) for r in jd.cells} for jd in parts]
        if any(c != comps[0] for c in comps):
            raise ValueError(f"{parts[0].job}: sessions used different compilers: {comps}")
        for p in self.parts:
            if not np.array_equal(p.jd.xs, self.xs):
                raise ValueError(f"{p.jd.job}: sessions use different sweeps")
        self.arms = sorted(set.intersection(*[set(jd.arms) for jd in parts]))
        rng = np.random.default_rng(SEED + 2)
        s = len(self.parts)
        pick = rng.integers(0, s, size=(B, s))
        # A session drawn twice in one resample uses two different round resamples.
        cols = (np.arange(B)[:, None] + 7919 * np.arange(s)[None, :]) % B
        self._boot = {}
        for arm in self.arms:
            per = np.stack([p.boot[p.ai(arm)] for p in self.parts])   # (S, X, B)
            chosen = per[pick, :, cols]                                # (B, S, X)
            self._boot[arm] = chosen.mean(axis=1).T                    # (X, B)

    def _med(self, arm):
        return np.mean([p.med[p.ai(arm)] for p in self.parts], axis=0)

    def slope(self, arm: str, unit: float = 1000.0) -> dict:
        est = _slopes(self._med(arm)[None], self.xs)[0] * unit
        bs = _slopes(self._boot[arm][None], self.xs)[0] * unit
        out = {"est": float(est), "ci": _ci(bs), "_boot": bs}
        if (w := _nonlinear(_linearity(self._med(arm), self._boot[arm], self.xs))):
            out["warning"] = w
        return out

    def ratio(self, a: str, b: str) -> dict:
        sa, sb = self.slope(a), self.slope(b)
        return {"est": sa["est"] / sb["est"], "ci": _ci(sa["_boot"] / sb["_boot"]),
                **_warnings((a, sa), (b, sb))}

    def between(self, arm: str) -> dict:
        """Last session's slope over the first's, with the within-session intervals."""
        a, b = self.parts[-1].slope(arm), self.parts[0].slope(arm)
        return {"est": a["est"] / b["est"], "ci": _ci(a["_boot"] / b["_boot"]),
                "sessions": [p.jd.session for p in self.parts],
                **_warnings((f"{arm} ({self.parts[-1].jd.session})", a),
                            (f"{arm} ({self.parts[0].jd.session})", b))}


def sentinel_summary(jd: JobData) -> dict:
    rows = sorted(jd.sentinel, key=lambda r: (r["round"], r["seq"]))
    if not rows:
        return {}
    per_round = len(jd.cells) // max(1, len(jd.rounds)) + 2
    t = np.array([r["round"] * per_round + r["seq"] for r in rows], dtype=float)
    vals = np.array([r["ft_total_s"] for r in rows])
    med = float(np.median(vals))
    trend = np.polyfit(t, vals, 1)[0] * 1000 if len(vals) > 2 else 0.0
    return {"median_s": med, "max_rel_dev": float(np.max(np.abs(vals - med)) / med),
            "trend_ms_per_compile": float(trend), "n": int(len(vals))}


def load_summary(jd: JobData) -> dict:
    # load_pct: during the compile itself (sessions from 2026-11-18); load_prev_pct: during the
    # previous compile (earlier sessions).
    v = np.array([r.get("load_pct", r.get("load_prev_pct", np.nan)) for r in jd.cells + jd.sentinel
                  if "load_pct" in r or r["seq"] > 0], dtype=float)
    v = v[~np.isnan(v)]
    out = {"flagged_rounds": jd.flagged_rounds}
    if len(v):
        out.update({"median_pct": float(np.median(v)), "p95_pct": float(np.percentile(v, 95)),
                    "max_pct": float(np.max(v))})
    return out


def metric_for(jd: JobData) -> str:
    return "wall_s" if jd.report_less() else "ft_total_s"


def summarize(session_dirs: list[pathlib.Path], allow_pilot: bool = False) -> dict:
    out = {}
    for d in session_dirs:
        for (session, job), jd in job_data(load_rows(d, allow_pilot), d).items():
            an = Analysis(jd, metric_for(jd))
            arms_ = {}
            for arm in jd.arms:
                s = an.slope(arm)
                arms_[arm] = {"slope_ms": s["est"], "slope_ci": s["ci"], "r2": s["r2"],
                              "monotonic": an.monotonic(arm),
                              "points": {int(x): an.point(arm, x) for x in jd.xs}}
            out.setdefault(session, {})[job] = {
                "dim": jd.dim, "mode": jd.mode, "corpus": jd.corpus, "rounds": len(jd.rounds),
                "metric": an.metric, "fixed_n": int(jd.cells[0]["n"]) if jd.dim == "M" else None,
                "arms": arms_, "sentinel": sentinel_summary(jd), "load": load_summary(jd)}
    return out


def _fmt(v, spec):
    return "n/a" if v is None or (isinstance(v, float) and np.isnan(v)) else format(v, spec)


def main(argv: list[str]) -> int:
    allow = "--allow-pilot" in argv
    dirs = [pathlib.Path(a) for a in argv if not a.startswith("--")]
    res = summarize(dirs, allow)
    for session, jobs in res.items():
        for job, j in jobs.items():
            unit = {"N": "struct", "M": f"field (added to each of {j['fixed_n']} structs)",
                    "K": "candidate", "C": "call site"}[j["dim"]]
            s = j["sentinel"]
            print(f"\n{session} / {job}  ({j['mode']}, {j['corpus']}, {j['rounds']} rounds, metric {j['metric']}; "
                  f"sentinel dev {_fmt(s.get('max_rel_dev'), '.1%')}, load p95 {_fmt(j['load'].get('p95_pct'), '.0f')}%, "
                  f"flagged rounds {j['load']['flagged_rounds']})")
            for arm, a in sorted(j["arms"].items(), key=lambda kv: (np.nan_to_num(kv[1]["slope_ms"], nan=1e9))):
                print(f"  {arm:<26} {_fmt(a['slope_ms'], '9.3f')} ms/{unit}  [{_fmt(a['slope_ci'][0], '8.3f')}, "
                      f"{_fmt(a['slope_ci'][1], '8.3f')}]  R2 {_fmt(a['r2'], '.3f')}"
                      f"{'  NON-MONOTONIC' if a['monotonic'] is False else ''}")
    if len(dirs) > 1:
        per = [job_data(load_rows(d, allow), d) for d in dirs]
        common = set.intersection(*[{j for (_, j) in p} for p in per])
        for job in sorted(common):
            parts = [next(v for (_, j), v in p.items() if j == job) for p in per]
            pooled = Pooled(parts, metric_for(parts[0]))
            print(f"\npooled {job} over {len(parts)} sessions")
            for arm in pooled.arms:
                s, b = pooled.slope(arm), pooled.between(arm)
                print(f"  {arm:<26} {s['est']:9.3f} [{s['ci'][0]:8.3f}, {s['ci'][1]:8.3f}]   "
                      f"last/first session {b['est']:.3f} [{b['ci'][0]:.3f}, {b['ci'][1]:.3f}]")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
