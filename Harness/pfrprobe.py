# SPDX-License-Identifier: MIT
"""Locate the quadratic term in Boost.PFR's C++17 path (paper §4.3).

Part A compiles the `pfr_classic` benchmark TU (`bench_pfr.cpp`, -DBOOST_PFR_USE_CPP26=0)
at N = 1,000, 2,000 and 4,000 under several compilers and modes: is the growth a GCC 16
or `-freflection` effect? Part B, on the first compiler with -std=c++20 (where the C++17
path is the default), calls one piece of the library for every struct: field counting,
binding with the count given, the whole visitor, one aggregate-initialization probe, and
copies of that probe with parts removed.

Compiles run one at a time on the performance cores at high priority, as in the sessions,
in REPEATS rounds of shuffled order; the medians of -ftime-report TOTAL and of the
overload-resolution timer go to Data/PfrProbe.json, which papernumbers.py reads (keys
probe.*).

    python pfrprobe.py --gxx GCC162=<g++ 16.2> --gxx GCC152=<g++ 15.2> [--repeats 3] [--pilot]
"""
from __future__ import annotations
import argparse
import datetime
import json
import random
import statistics
import sys
import tempfile
import pathlib

import psutil

import compiler
import generate
import machine

PROJECT = pathlib.Path(__file__).resolve().parent.parent
OUT = PROJECT / "Data" / "PfrProbe.json"
REPEATS = 3
SEED = 20261030
A_SIZES = (1000, 2000, 4000)
B_SIZES = (500, 1000, 2000)
CLASSIC = ["-DBOOST_PFR_USE_CPP26=0"]

# Part B: a copy of Boost.PFR's enable_if_initializable_helper and its converters
# (detail/fields_count.hpp at the pinned commit), then the same probe with parts removed.
PRELUDE = r"""
namespace Probe {
void Report() noexcept;
template <class T> constexpr T UnsafeDeclval() noexcept { Report(); using F = T (*)(); F p = nullptr; return p(); }
struct Lref { std::size_t ignore;
  template <class X> constexpr operator X&() const&& noexcept { return UnsafeDeclval<X&>(); }
  template <class X> constexpr operator X&() const& noexcept { return UnsafeDeclval<X&>(); } };
struct Rref { std::size_t ignore; template <class X> operator X() const&& noexcept { return UnsafeDeclval<X>(); } };
struct Lref1 { std::size_t ignore;
  template <class X> constexpr operator X&() const&& noexcept { return UnsafeDeclval<X&>(); } };
#define PROBE_COPYABLE(T) class = std::enable_if_t<std::is_copy_constructible<T>::value>
#define PROBE_NOT_COPYABLE(T) class = std::enable_if_t<!std::is_copy_constructible<T>::value>
// the copy
template <class T, std::size_t... I, PROBE_COPYABLE(T)>
constexpr auto Copy(std::index_sequence<I...>) noexcept -> std::add_pointer_t<decltype(T{Lref{I}...})>;
template <class T, std::size_t... I, PROBE_NOT_COPYABLE(T)>
constexpr auto Copy(std::index_sequence<I...>) noexcept -> std::add_pointer_t<decltype(T{Rref{I}...})>;
// without std::add_pointer_t
template <class T, std::size_t... I, PROBE_COPYABLE(T)>
constexpr auto NoAddPointer(std::index_sequence<I...>) noexcept -> decltype(T{Lref{I}...});
template <class T, std::size_t... I, PROBE_NOT_COPYABLE(T)>
constexpr auto NoAddPointer(std::index_sequence<I...>) noexcept -> decltype(T{Rref{I}...});
// without std::add_pointer_t, the rvalue overload and the guard
template <class T, std::size_t... I>
constexpr auto Bare(std::index_sequence<I...>) noexcept -> decltype(T{Lref1{I}...});
}
"""
D = "boost::pfr::detail::"
B_VARIANTS = {
    "binding": "{{ Synth::S{i} v{{}}; auto& [a,b,c,d,e,f,g,h,j,k,l,m,o,p,q,r] = v; (void)a; }}",
    "fields_count": f"static_assert({D}fields_count<Synth::S{{i}}>() == 16);",
    "tie_given_count": f"{{{{ Synth::S{{i}} v{{{{}}}}; auto t = {D}tie_as_tuple(v, {D}size_t_<16>{{{{}}}}); (void)t; }}}}",
    "for_each_field": "{{ Synth::S{i} v{{}}; boost::pfr::for_each_field(v, [](auto&) {{}}); }}",
    "probe": f"using P{{i}} = decltype({D}enable_if_initializable_helper<Synth::S{{i}}>(std::make_index_sequence<16>{{{{}}}}));",
    "copy": "using P{i} = decltype(Probe::Copy<Synth::S{i}>(std::make_index_sequence<16>{{}}));",
    "no_add_pointer": "using P{i} = decltype(Probe::NoAddPointer<Synth::S{i}>(std::make_index_sequence<16>{{}}));",
    "bare": "using P{i} = decltype(Probe::Bare<Synth::S{i}>(std::make_index_sequence<16>{{}}));",
}


def _b_source(variant: str, n: int) -> str:
    body = "\n".join(B_VARIANTS[variant].format(i=i) for i in range(n))
    return ('#include <boost/pfr.hpp>\n#include <type_traits>\n#include <utility>\n#include "types.hpp"\n'
            + PRELUDE + f"void Bench()\n{{\n{body}\n}}\n")


def _modes(gxx: str) -> list[tuple[str, list[str]]]:
    """(name, base flags) per mode: C++20 everywhere; C++26 with and without the flag where
    the compiler has reflection."""
    out = [("cxx20", ["-std=c++20"])]
    if " 16." in compiler.version(gxx):
        out += [("cxx26", ["-std=c++26"]), ("cxx26_refl", ["-std=c++26", "-freflection"])]
    return [(name, [*base, f"-B{compiler.UCRT_BIN}/"]) for name, base in out]


def cells(compilers: dict[str, str], work: pathlib.Path) -> list[dict]:
    out = []
    for tag, gxx in compilers.items():
        for mode, base in _modes(gxx):
            for n in A_SIZES:
                d = work / f"scalar_n{n}_m16"
                out.append({"part": "A", "config": f"{tag}.{mode}", "n": n, "gxx": gxx,
                            "cmd": compiler.cc1plus_command(d / "bench_pfr.cpp", "syntax", CLASSIC, [d],
                                                            gxx, base=base)})
    tag, gxx = next(iter(compilers.items()))
    base = ["-std=c++20", f"-B{compiler.UCRT_BIN}/"]
    for variant in B_VARIANTS:
        for n in B_SIZES:
            d = work / f"scalar_n{n}_m16"
            tu = d / f"probe_{variant}.cpp"
            tu.write_text(_b_source(variant, n))
            out.append({"part": "B", "config": variant, "n": n, "gxx": gxx,
                        "cmd": compiler.cc1plus_command(tu, "syntax", (), [d], gxx, base=base)})
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gxx", action="append", required=True, metavar="TAG=PATH",
                    help="compilers; the first one also runs part B")
    ap.add_argument("--repeats", type=int, default=REPEATS)
    ap.add_argument("--pilot", action="store_true", help="mark the result as not citable")
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args()
    compilers = dict(g.split("=", 1) for g in args.gxx)
    pilot = args.pilot or args.repeats != REPEATS
    work = pathlib.Path(tempfile.gettempdir()) / "rb_pfrprobe"
    for n in sorted({*A_SIZES, *B_SIZES}):
        generate.generate(work / f"scalar_n{n}_m16", n, 16, "scalar")
    cpus = machine.pin_to_performance_cores()
    state = {"pilot": pilot, "repeats": args.repeats, "performance_cpus": cpus,
             "machine": machine.snapshot(list(compilers.values())),
             "compilers": {t: compiler.version(g) for t, g in compilers.items()}}
    todo = cells(compilers, work)
    runs: dict[tuple, list[dict]] = {}
    cmds: dict[tuple, list[str]] = {}
    psutil.cpu_percent(interval=None)
    for r in range(args.repeats):
        order = list(todo)
        random.Random(f"{SEED}|{r}").shuffle(order)
        for i, c in enumerate(order, 1):
            rep = compiler.compile_once(c["cmd"], gxx=c["gxx"])
            # Whole-machine load during this compile, and when it ended.
            rep["load_pct"] = psutil.cpu_percent(interval=None)
            rep["utc"] = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
            runs.setdefault((c["part"], c["config"], c["n"]), []).append(rep)
            cmds[(c["part"], c["config"], c["n"])] = c["cmd"]
            print(f"round {r + 1}/{args.repeats} {i}/{len(order)} {c['part']} {c['config']} N={c['n']}: "
                  f"{rep['ft_total_s']:.2f} s (overload {rep['ft_overload_s']:.2f})", flush=True)
    result = {}
    for (part, config, n), reps in sorted(runs.items()):
        result.setdefault(part, {}).setdefault(config, {})[str(n)] = {
            "total_s": statistics.median(r["ft_total_s"] for r in reps),
            "overload_s": statistics.median(r["ft_overload_s"] for r in reps),
            "runs_total_s": [r["ft_total_s"] for r in reps],
            "runs_overload_s": [r["ft_overload_s"] for r in reps],
            # Every run in full: all timers and GGC, wall and OS counters, load, the report text.
            "runs": [{("stderr" if k == "_stderr" else k): v for k, v in r.items()} for r in reps],
            "cmd": cmds[(part, config, n)]}
    state["result"] = result
    pathlib.Path(args.out).write_text(json.dumps(state, indent=1))
    print(f"wrote {args.out}" + (" (PILOT, not citable)" if pilot else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
