# SPDX-License-Identifier: MIT
"""Paper figures from one measurement session (every panel = one job of that session).

    python figures.py Data/Sessions/S1 [--out Figures] [--allow-pilot]
"""
from __future__ import annotations
import argparse
import pathlib
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker
import numpy as np
from matplotlib.transforms import offset_copy

import arms
import stats

PROJECT = pathlib.Path(__file__).resolve().parent.parent

# Categorical slots in fixed order (validated: adjacent CVD dE >= 9.1, normal-vision
# dE >= 19.6 on the light surface). Colour = mechanism family, the same in every figure;
# labels carry identity.
FAMILY_COLOR = {
    "native": "#2a78d6",        # slot 1 blue
    "p1061": "#eb6834",         # slot 2 orange
    "library": "#1baf7a",       # slot 3 aqua
    "hand-written": "#eda100",  # slot 4 yellow
    "macro": "#e87ba4",         # slot 5 magenta
}
FAMILY_LABEL = {"native": "P2996 (ours)", "p1061": "P1061 (ours)", "library": "library",
                "hand-written": "hand-written", "macro": "X-macro"}
INK, INK2, GRID, AXIS, GRAY = "#0b0b0b", "#52514e", "#e1e0d9", "#c3c2b7", "#898781"

plt.rcParams.update({
    "font.family": "sans-serif", "font.size": 8, "axes.titlesize": 8, "axes.labelsize": 8,
    "legend.fontsize": 7, "xtick.labelsize": 7, "ytick.labelsize": 7,
    "axes.edgecolor": AXIS, "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK2,
    "axes.spines.top": False, "axes.spines.right": False, "axes.grid": True, "grid.color": GRID,
    "grid.linewidth": 0.5, "grid.linestyle": "-", "lines.linewidth": 1.5, "pdf.fonttype": 42,
    "figure.facecolor": "#ffffff", "axes.facecolor": "#ffffff", "legend.frameon": False,
    "savefig.bbox": "tight", "savefig.pad_inches": 0.05,
})
UNIT = {"N": "struct", "M": "field", "K": "candidate", "C": "call site"}
# Labels that the final data made inaccurate; arms.py (measured code) stays as it was.
LABEL = {"pfr_native": "Boost.PFR, reflection flag set (code-identical to default)",
         # After S3 (2026-11-21) "P2996" alone would read as the cost of P2996 itself: the
         # S1/S2 native arms all iterate the std::span of define_static_array.
         "reflect_plain": "P2996, template for over std::span",
         "reflect_visit": "P2996 (span form) behind a callback API",
         "reflect": "P2996 (span form) + P3394 annotation query",
         "reflect_array": "P2996, template for over a constant array",
         "reflect_index": "P2996 through a P1061 index pack",
         "reflect_seq": "P2996 through an index-sequence helper"}


def _label(arm: str) -> str:
    return LABEL.get(arm, arms.get(arm).label)


def _analyses(session_dir: pathlib.Path, allow_pilot: bool) -> dict[str, stats.Analysis]:
    return {job: stats.Analysis(jd, stats.metric_for(jd)) for (_, job), jd in
            stats.job_data(stats.load_rows(session_dir, allow_pilot), session_dir).items()}


def _end_labels(ax, items, gap=0.07):
    """Labels at the right end of lines, (x, y, text, colour) each, moved apart vertically
    so that no two are closer than `gap` of the y range; a thin leader in the line's
    colour joins each moved label to its line's end."""
    if not items:
        return
    lo, hi = ax.get_ylim()
    step = gap * (hi - lo)
    items = sorted(items, key=lambda t: t[1])
    ys = [items[0][1]]
    for _, y, _, _ in items[1:]:
        ys.append(max(y, ys[-1] + step))
    shift = max(0.0, ys[-1] - hi)
    right = offset_copy(ax.transData, fig=ax.figure, x=10, y=0, units="points")
    for (x, y0, text, colour), y in zip(items, ys):
        ax.annotate(text, xy=(x, y0), xytext=(x, y - shift), textcoords=right, va="center",
                    fontsize=7, color=INK2, annotation_clip=False,
                    arrowprops={"arrowstyle": "-", "color": colour, "linewidth": 0.8,
                                "relpos": (0, 0.5), "shrinkA": 1, "shrinkB": 1})


def _family_legend(fig, families, y=-0.02):
    fams = sorted(set(families), key=list(FAMILY_COLOR).index)
    handles = [plt.Line2D([], [], marker="o", linestyle="", color=FAMILY_COLOR[f]) for f in fams]
    fig.legend(handles, [FAMILY_LABEL[f] for f in fams], loc="lower center", ncol=len(fams),
               bbox_to_anchor=(0.5, y))


def _per_struct_at_top(an: stats.Analysis, arm: str) -> dict:
    """Marginal cost per struct at the sweep's largest N, (cost(N) - cost(0)) / N, in ms:
    defined whether or not the curve is linear."""
    top = an.jd.xs[-1]
    m = an.marginal(arm, top)
    return {"est": m["est"] / top * 1000, "ci": [c / top * 1000 for c in m["ci"]]}


def _ladder(ax, an: stats.Analysis, arm_names, title, mode_word="front-end", stat="slope"):
    """Dots with 95% CI whiskers on a log axis (bar length would depend on the axis limit).
    stat="slope" plots OLS slopes (the paper reports them only for linear curves; an arm
    whose slope carries a linearity warning is reported on stderr); stat="top" plots the
    marginal cost per struct at the largest N, labelled to three significant digits (at
    N = 100 one 10 ms timer step is 0.1 ms per struct)."""
    rows = []
    for a in (x for x in arm_names if x in an.jd.arms):
        r = an.slope(a) if stat == "slope" else _per_struct_at_top(an, a)
        if r.get("warning"):
            print(f"WARNING {an.jd.job}.{a}: {r['warning']} (plotted as a slope)", file=sys.stderr)
        rows.append((r["est"], r["ci"], a))
    rows.sort()
    y = np.arange(len(rows))
    for yi, (est, (lo, hi), a) in zip(y, rows):
        col = FAMILY_COLOR[arms.get(a).family]
        ax.errorbar(est, yi, xerr=[[est - lo], [hi - est]], fmt="o", color=col, ecolor=col,
                    elinewidth=1.0, capsize=2, markersize=4, zorder=3)
        ax.annotate(f"{est:.2f}" if stat == "slope" else f"{est:.3g}", (hi, yi), xytext=(5, 0),
                    textcoords="offset points", va="center", fontsize=6.5, color=INK2)
    ax.set_yticks(y, [_label(a) for _, _, a in rows])
    ax.set_xscale("log")
    # Room below the lowest whisker, so that a labelled tick sits under the cheapest arm.
    ax.set_xlim(left=min(lo for _, (lo, _), _ in rows) / 1.15)
    ax.xaxis.set_major_locator(matplotlib.ticker.LogLocator(base=10, subs=(1.0, 2.0, 3.0, 5.0, 7.0)))
    ax.xaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:g}"))
    ax.xaxis.set_minor_formatter(matplotlib.ticker.NullFormatter())
    ax.grid(axis="y", visible=False)
    what = (f"{mode_word} cost per {UNIT[an.jd.dim]}" if stat == "slope" else
            f"{mode_word} marginal cost per {UNIT[an.jd.dim]} at N = {int(an.jd.xs[-1]):,}")
    ax.set_xlabel(f"{what} (ms, log; 95% CI)")
    ax.set_title(title, loc="left", color=INK)
    return [arms.get(a).family for _, _, a in rows]


# Arms whose front-end cost is not linear in N (§4.3, §4.4): no slope, so not on the ladder.
NONLINEAR_N = ("manual", "xmacro", "pfr_classic")


def figure_ladder(an: dict, out: pathlib.Path):
    light = [a for a in an["FrontendN"].jd.arms if a not in NONLINEAR_N]
    fig, axes = plt.subplots(2, 1, figsize=(6.0, 6.2), gridspec_kw={"height_ratios": [1.4, 1]})
    fams = _ladder(axes[0], an["FrontendN"], light,
                   "(a) light mechanisms that pass the linearity check, N up to 4,000")
    fams += _ladder(axes[1], an["FrontendHeavy"], an["FrontendHeavy"].jd.arms,
                    "(b) library backends with reference arms, N up to 200")
    _family_legend(fig, fams)
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    fig.savefig(out / "FigureLadder.pdf")
    plt.close(fig)


AB = [("Boost.PFR", "FrontendN", "pfr_classic", "pfr", "-"),
      ("reflect-cpp", "FrontendHeavy", "rflcpp", "rflcpp_native", "--"),
      ("Glaze", "FrontendHeavy", "glaze_classic", "glaze_native", ":")]
# Boost.PFR's C++17 path is not linear in N (§4.3): its A/B is the ratio of marginal costs
# at this N, and panel (c) shows how that ratio grows.
PFR_AT_N = 500


def _ratio_row(an: dict, job: str, old: str, new: str) -> dict:
    return an[job].point_ratio(old, new, PFR_AT_N) if old == "pfr_classic" else an[job].ratio(old, new)


def figure_backends(an: dict, out: pathlib.Path):
    fig, axes = plt.subplots(1, 3, figsize=(7.6, 2.6), gridspec_kw={"width_ratios": [1, 1.15, 0.95]})
    col = FAMILY_COLOR["library"]
    ax = axes[0]
    for i, (lib, job, old, new, _) in enumerate(AB):
        r = _ratio_row(an, job, old, new)
        ax.errorbar(r["est"], i, xerr=[[r["est"] - r["ci"][0]], [r["ci"][1] - r["est"]]], fmt="o",
                    color=col, ecolor=col, elinewidth=1.0, capsize=2, markersize=5)
        # The same rounding as the paper's Table 2 (a point ratio to one decimal).
        text = f"{r['est']:.1f}×" if old == "pfr_classic" else f"{r['est']:.2f}×"
        ax.annotate(text, (r["ci"][1], i), xytext=(5, 0), textcoords="offset points",
                    va="center", fontsize=6.5, color=INK2)
    ax.axvline(1.0, color=AXIS, linewidth=0.8, zorder=0)
    ax.set_xlim(left=0.8)
    ax.set_xticks([1, 2, 3, 4])
    ax.set_yticks(range(len(AB)), [f"{lib}{f' (N = {PFR_AT_N})' if old == 'pfr_classic' else ''}\n"
                                   "previous / C++26 path" for lib, _, old, *_ in AB])
    ax.set_xlabel("per-struct cost ratio (95% CI; 1 = no change)")
    ax.set_title("(a) same-source A/Bs, M = 16", loc="left", color=INK)
    ax.grid(axis="y", visible=False)

    ax, m_an = axes[1], an["FrontendM"]
    ms = [m for m in m_an.jd.xs if m > 0]
    ends = []
    for lib, _, old, new, style in AB:
        if old not in m_an.jd.arms or new not in m_an.jd.arms:
            continue
        rs = [m_an.point_ratio(old, new, m) for m in ms]
        est = [r["est"] for r in rs]
        ax.plot(ms, est, color=col, linestyle=style, marker="o", markersize=3.5)
        ax.fill_between(ms, [r["ci"][0] for r in rs], [r["ci"][1] for r in rs], color=col, alpha=0.12,
                        linewidth=0)
        ends.append((ms[-1], est[-1], lib, col))
    ax.axhline(1.0, color=AXIS, linewidth=0.8, zorder=0)
    ax.set_xscale("log", base=2)
    ax.set_xticks(ms, [str(int(m)) for m in ms])
    _end_labels(ax, ends)
    ax.set_xlabel(f"fields per struct M (N = {int(m_an.jd.cells[0]['n'])})")
    ax.set_ylabel("marginal cost ratio,\nprevious / C++26 path")
    ax.set_title("(b) the ratio as fields grow", loc="left", color=INK)

    ax, n_an = axes[2], an["FrontendN"]
    ns = [n for n in n_an.jd.xs if n > 0]
    rs = [n_an.point_ratio("pfr_classic", "pfr", n) for n in ns]
    ax.plot(ns, [r["est"] for r in rs], color=col, linestyle="-", marker="o", markersize=3.5)
    ax.fill_between(ns, [r["ci"][0] for r in rs], [r["ci"][1] for r in rs], color=col, alpha=0.12,
                    linewidth=0)
    ax.set_xscale("log", base=2)
    ax.set_xticks(ns, [f"{int(n):,}" for n in ns])
    ax.set_ylim(bottom=0)
    ax.set_xlabel("structs N (M = 16)")
    ax.set_ylabel("marginal cost ratio,\nC++17 / C++26 path")
    ax.set_title("(c) Boost.PFR as types grow", loc="left", color=INK)
    fig.tight_layout()
    fig.savefig(out / "FigureBackends.pdf")
    plt.close(fig)


# Every idiom is hand-written code, so all share the hand-written colour (colour = family in
# every figure); line style and marker tell the superlinear idioms apart, labels name them.
IDIOM_STYLES = [("-", "o"), ("--", "s"), (":", "^"), ("-.", "D"), ((0, (1, 1)), "v")]
# Short names of the idioms, as in the paper's Table 4.
IDIOM = {"ovl_flat": "free function, qualified call", "ovl_adl": "free function, ADL",
         "ovl_adl_template": "ADL from a dispatch template", "ovl_constrained": "enable_if template, ADL",
         "ovl_archive": "serialize(Archive&, T&, unsigned)", "ovl_adl_per_ns": "one namespace per type",
         "ovl_hidden_friend": "hidden friend", "ovl_member": "member function",
         "ovl_specialization": "class-template specialization", "ovl_unique": "distinct names"}


def _marginals(a: stats.Analysis, arm: str) -> np.ndarray:
    return a.med[a.ai(arm)] - a.med[a.ai(arm), a.xi(0)]


def figure_overload(an: dict, out: pathlib.Path):
    fig, axes = plt.subplots(1, 2, figsize=(7.4, 2.9))
    ax, a = axes[0], an["OverloadN"]
    top, half = a.jd.xs[-1], a.jd.xs[-1] / 2
    # Idioms whose marginal cost at least triples per doubling of N are drawn in colour.
    growth = {arm: (_marginals(a, arm)[a.xi(top)] / _marginals(a, arm)[a.xi(half)]) for arm in a.jd.arms}
    superlinear = [arm for arm in sorted(a.jd.arms, key=lambda x: -_marginals(a, x)[-1]) if growth[arm] >= 3.0]
    if len(superlinear) > len(IDIOM_STYLES):
        raise ValueError(f"{len(superlinear)} superlinear idioms, {len(IDIOM_STYLES)} styles: {superlinear}")
    # Style follows the idiom (fixed order), the same in both panels.
    styles = dict(zip([x for x in IDIOM if x in superlinear], IDIOM_STYLES))
    colour = FAMILY_COLOR["hand-written"]
    ends = []
    for arm in a.jd.arms:
        marg = _marginals(a, arm)
        if arm in styles:
            line, mark = styles[arm]
            ax.plot(a.jd.xs, marg, color=colour, linestyle=line, marker=mark, markersize=3, zorder=3)
            ends.append((top, marg[-1], IDIOM[arm], colour))
        else:
            ax.plot(a.jd.xs, marg, color=GRAY, marker="o", markersize=2.5, linewidth=1.0, zorder=2)
    linear = [x for x in a.jd.arms if x not in styles]
    if linear:
        y = max(_marginals(a, x)[-1] for x in linear)
        ends.append((top, y, f"{len(linear)} near-linear idioms", GRAY))
    _end_labels(ax, ends)
    ax.set_xlabel("types N (K = C = N, 16 fields)")
    ax.set_ylabel("marginal front-end time (s)")
    ax.set_title("(a) per-type serializer idioms", loc="left", color=INK)

    ax, c = axes[1], an["OverloadC"]
    ends = []
    for arm in c.jd.arms:
        marg = _marginals(c, arm)
        line, mark = styles.get(arm, ("-", "o"))
        col = colour if arm in styles else GRAY
        ax.plot(c.jd.xs, marg, color=col, linestyle=line, marker=mark, markersize=3)
        ends.append((c.jd.xs[-1], marg[-1], IDIOM[arm], col))
    _end_labels(ax, ends)
    ax.set_xlabel(f"call sites C (K = {int(c.jd.cells[0]['k']):,} candidates)")
    ax.set_ylabel("time over C = 0 (s)")
    ax.set_title("(b) time added by call sites at a fixed overload set", loc="left", color=INK)
    fig.tight_layout()
    fig.savefig(out / "FigureOverload.pdf")
    plt.close(fig)


def figure_idiom(an: dict, out: pathlib.Path):
    """Session S3: four native formulations of the same member query, with references."""
    fig, ax = plt.subplots(figsize=(6.0, 2.9))
    fams = _ladder(ax, an["FrontendIdiom"], an["FrontendIdiom"].jd.arms,
                   "native formulations and references, N up to 4,000 (session S3)")
    _family_legend(fig, fams, y=-0.06)
    fig.tight_layout(rect=(0, 0.06, 1, 1))
    fig.savefig(out / "FigureIdiom.pdf")
    plt.close(fig)


def figure_full(an: dict, out: pathlib.Path):
    fig, axes = plt.subplots(2, 1, figsize=(6.0, 5.4), gridspec_kw={"height_ratios": [1.4, 1]})
    # §4.5 reports -O2 costs as marginal costs at the largest N, not slopes: several -O2
    # curves bend (the inliner's budgets are per translation unit).
    light = [a for a in an["FullN"].jd.arms if not a.endswith("_split") and a != "manual"]
    fams = _ladder(axes[0], an["FullN"], light, "(a) light mechanisms at -O2", "-O2", stat="top")
    fams += _ladder(axes[1], an["FullHeavy"], an["FullHeavy"].jd.arms,
                    "(b) library backends at -O2", "-O2", stat="top")
    _family_legend(fig, fams)
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    fig.savefig(out / "FigureFull.pdf")
    plt.close(fig)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("session", nargs="+", help="S1, then optionally S3 (its job FrontendIdiom)")
    ap.add_argument("--out", default=str(PROJECT / "Figures"))
    ap.add_argument("--allow-pilot", action="store_true")
    args = ap.parse_args()
    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    an = {}
    for s in args.session:   # each job from the first session given that ran it
        for job, a in _analyses(pathlib.Path(s), args.allow_pilot).items():
            an.setdefault(job, a)
    made = []
    for name, fn, need in [("FigureLadder", figure_ladder, ("FrontendN", "FrontendHeavy")),
                           ("FigureBackends", figure_backends, ("FrontendN", "FrontendHeavy", "FrontendM")),
                           ("FigureOverload", figure_overload, ("OverloadN", "OverloadC")),
                           ("FigureFull", figure_full, ("FullN", "FullHeavy")),
                           ("FigureIdiom", figure_idiom, ("FrontendIdiom",))]:
        if all(j in an for j in need):
            fn(an, out)
            made.append(name)
        else:
            print(f"skip {name}: needs jobs {need}")
    print(f"wrote {', '.join(made) or 'nothing'} to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
