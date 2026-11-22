# SPDX-License-Identifier: MIT
"""The measurement plan: every job of a session.

A job is a set of cells (arm x sweep value) timed together: each round runs every
cell once, in a seeded random order, between two sentinel compiles. Ratios are only
formed between arms of the same job, so they share a session and a round structure.
Arms written `arm@GCC161` are compiled by the second compiler bound to the session,
in the same rounds and over the same sweep as their untagged counterparts.
"""
from __future__ import annotations
from dataclasses import dataclass

WARMUP_ROUNDS = 1
ROUNDS = 11
CROSS = "GCC161"  # compiler tag of the cross-check compiler (campaign.py --compiler GCC161=...)

LIGHT = ("manual", "manual_unique", "xmacro", "xmacro_unique",
         "reflect", "reflect_plain", "reflect_visit", "p1061", "p1061_visit",
         "pfr", "pfr_classic", "pfr_native")
LIGHT_LINEAR = ("manual_unique", "xmacro_unique", "reflect", "reflect_plain", "reflect_visit",
                "p1061", "p1061_visit", "pfr", "pfr_classic")
HEAVY = ("rflcpp", "rflcpp_native", "glaze_native", "glaze_classic")
# A uniquely named X-macro serializer cannot recurse into nested structs.
HETERO_LIGHT = tuple(a for a in LIGHT if a != "xmacro_unique")
REFERENCE = ("reflect_plain", "p1061_visit", "pfr")
OVERLOAD = ("ovl_flat", "ovl_adl", "ovl_adl_template", "ovl_constrained", "ovl_archive",
            "ovl_adl_per_ns", "ovl_hidden_friend", "ovl_member", "ovl_specialization", "ovl_unique")
FLAG_LIGHT = ("manual_unique", "manual_unique_noflag", "p1061", "p1061_noflag", "pfr", "pfr_noflag")
FLAG_HEAVY = ("rflcpp", "rflcpp_noflag", "glaze_classic", "glaze_classic_noflag")


def tagged(arms_: tuple[str, ...], tag: str = CROSS) -> tuple[str, ...]:
    """Each arm, then the same arm on the cross-check compiler."""
    return tuple(x for a in arms_ for x in (a, f"{a}@{tag}"))


@dataclass(frozen=True)
class Job:
    name: str
    question: str
    mode: str                  # syntax (front end) | full (-O2 -c)
    dim: str                   # N structs | M fields | K candidates | C call sites
    sweep: tuple[int, ...]
    arms: tuple[str, ...]
    sentinel: tuple[str, int]  # (arm, sweep value) compiled at the start and end of each round
    corpus: str = "scalar"
    n: int = 0                 # fixed struct count (dim M)
    m: int = 16                # fixed field count (dims N, K, C); median field count (hetero)
    k: int = 0                 # fixed candidate count (dim C)
    c: int = 0                 # fixed call-site count (dim K)
    prime: bool = False        # overload TUs: call every type once outside the swept calls

    def dims(self, x: int) -> dict:
        if self.dim == "N":
            return {"n": x, "m": self.m, "k": x, "c": x}
        if self.dim == "M":
            return {"n": self.n, "m": x, "k": self.n, "c": self.n}
        if self.dim == "C":
            return {"n": self.k, "m": self.m, "k": self.k, "c": x}
        if self.dim == "K":
            return {"n": x, "m": self.m, "k": x, "c": self.c}
        raise ValueError(self.dim)

    def cells(self) -> list[tuple[str, int]]:
        return [(arm, x) for arm in self.arms for x in self.sweep]


JOBS: list[Job] = [
    Job("FrontendN",
        "Per-struct front-end cost of every light mechanism at scale; overloaded names vs "
        "distinct names; P2996 vs P1061 x inline vs callback API; Boost.PFR paths; A/A control.",
        "syntax", "N", (0, 500, 1000, 2000, 4000), LIGHT, ("reflect_plain", 1000)),
    Job("FrontendHeavy",
        "Per-struct front-end cost of reflect-cpp and Glaze, each with its two backends, "
        "against same-session reference arms.",
        "syntax", "N", (0, 25, 50, 100, 200), HEAVY + REFERENCE, ("reflect_plain", 100)),
    Job("FrontendM",
        "Per-field cost: how each mechanism, and each backend A/B, scales with fields per struct.",
        "syntax", "M", (0, 8, 16, 32, 64, 128), LIGHT_LINEAR + HEAVY, ("reflect_plain", 32), n=50),
    Job("RichN",
        "Whether the ranking and the controls hold for strings, vectors and optionals.",
        "syntax", "N", (0, 25, 50, 100, 200), LIGHT + HEAVY, ("reflect_plain", 100), corpus="rich"),
    Job("HeteroN",
        "Per-struct cost on a heterogeneous type graph: varied field counts (median 8), "
        "enums, nested structs up to 6 levels, vectors and optionals of structs.",
        "syntax", "N", (0, 200, 400, 800, 1600), HETERO_LIGHT, ("reflect_plain", 400),
        corpus="hetero", m=8),
    Job("HeteroHeavy",
        "The libraries on the heterogeneous type graph.",
        "syntax", "N", (0, 25, 50, 100, 200), HEAVY + REFERENCE, ("reflect_plain", 100),
        corpus="hetero", m=8),
    Job("FullN",
        "Total compile cost at -O2 (front end + optimization + code generation), "
        "with the call-site layout control.",
        "full", "N", (0, 50, 100, 200, 400),
        LIGHT_LINEAR + ("manual", "reflect_split", "pfr_split"), ("reflect_plain", 200)),
    Job("FullHeavy",
        "Total -O2 cost of the library backends.",
        "full", "N", (0, 25, 50, 100), HEAVY + REFERENCE, ("reflect_plain", 50)),
    Job("FlagCost",
        "What -freflection costs code that does not use reflection: the same arms with the "
        "flag on and off (identical generated code, verified).",
        "syntax", "N", (0, 500, 1000, 2000), FLAG_LIGHT, ("pfr", 1000)),
    Job("FlagCostHeavy",
        "The -freflection flag cost on the libraries' pre-C++26 paths.",
        "syntax", "N", (0, 50, 100, 200), FLAG_HEAVY, ("rflcpp", 100)),
    Job("ReportOverhead",
        "Whether -ftime-report inflates compile time: the same compiles with and without it, "
        "compared on external wall time (the only metric both have).",
        "syntax", "N", (0, 1000, 2000),
        ("reflect_plain", "reflect_plain_noreport", "pfr", "pfr_noreport",
         "manual_unique", "manual_unique_noreport"), ("pfr", 1000)),
    Job("OverloadN",
        "How each per-type customization idiom drives overload resolution (K = C = N).",
        "syntax", "N", (0, 250, 500, 1000), OVERLOAD, ("ovl_unique", 500)),
    Job("OverloadC",
        "Cost per call site at a fixed overload set (K = 2000); every type is called once "
        "outside the swept calls, so only lookup grows with C. A library dispatch template "
        "resolves once per type, at instantiation, so it should not grow with C.",
        "syntax", "C", (0, 250, 500, 1000, 2000),
        ("ovl_flat", "ovl_archive", "ovl_adl_template", "ovl_unique"),
        ("ovl_unique", 1000), k=2000, prime=True),
    Job("OverloadK",
        "Cost per candidate at fixed call sites (C = 500).",
        "syntax", "K", (500, 1000, 2000, 4000), ("ovl_flat", "ovl_archive", "ovl_unique"),
        ("ovl_unique", 1000), c=500),
    # GCC 16.1.0 vs 16.2.0, paired: both compilers in the same rounds and sweeps.
    Job("CompilerN",
        "GCC 16.2.0 vs 16.1.0 on the key light arms (PR125179 and other reflection fixes).",
        "syntax", "N", (0, 500, 1000, 2000),
        tagged(("manual_unique", "reflect", "reflect_plain", "p1061", "pfr")), ("reflect_plain", 1000)),
    Job("CompilerHeavy",
        "GCC 16.2.0 vs 16.1.0 on the Glaze and reflect-cpp backend A/Bs.",
        "syntax", "N", (0, 50, 100, 200),
        tagged(("glaze_native", "glaze_classic", "rflcpp_native", "rflcpp", "reflect_plain")),
        ("reflect_plain", 100)),
    Job("CompilerFlag",
        "GCC 16.2.0 vs 16.1.0: the -freflection flag cost.",
        "syntax", "N", (0, 500, 1000, 2000),
        tagged(("p1061", "p1061_noflag", "pfr", "pfr_noflag")), ("pfr", 1000)),
]

# Jobs outside the full plan, run only by name (`campaign.py run --jobs ...`). S1 and S2 ran
# the seventeen jobs of JOBS; the supplementary session S3 runs FrontendIdiom on GCC 16.2.0.
SUPPLEMENTARY: list[Job] = [
    Job("FrontendIdiom",
        "Native formulations of the same member query: the expansion statement over std::span "
        "(reflect_plain) and over a constant array, a P1061 index pack and an index-sequence "
        "helper, against P1061, Boost.PFR and hand-written code, over the FrontendN sweep.",
        "syntax", "N", (0, 500, 1000, 2000, 4000),
        ("reflect_plain", "reflect_array", "reflect_index", "reflect_seq", "p1061", "pfr",
         "manual_unique"),
        ("reflect_plain", 1000)),
]


def by_name(name: str) -> Job:
    for j in JOBS + SUPPLEMENTARY:
        if j.name == name:
            return j
    raise KeyError(name)
