# SPDX-License-Identifier: MIT
"""The arm registry: every timed serialization mechanism, and every comparison pair
with the manipulation check that must pass before the pair is timed.

An arm name may carry a compiler tag, `arm@TAG`: the same arm compiled with the
compiler a session binds to TAG (campaign.py --compiler TAG=PATH)."""
from __future__ import annotations
from dataclasses import dataclass, replace


@dataclass(frozen=True)
class Arm:
    name: str
    tu: str                  # generated translation unit (generate.py / overload.py)
    family: str              # hand-written | macro | native | p1061 | library | overload
    label: str               # human-readable label for tables and figures
    flags: tuple[str, ...] = ()
    loc_family: str = ""     # key into generate.ARM_HEADERS / per_type_cost
    report: bool = True      # compile with -ftime-report (False: external wall time only)


ARMS: dict[str, Arm] = {a.name: a for a in [
    Arm("manual", "bench_manual.cpp", "hand-written",
        "hand-written, one overloaded name", loc_family="manual"),
    Arm("manual_unique", "bench_manual_unique.cpp", "hand-written",
        "hand-written, distinct names", loc_family="manual"),
    Arm("xmacro", "bench_xmacro.cpp", "macro",
        "X-macro, one overloaded name", loc_family="xmacro"),
    Arm("xmacro_unique", "bench_xmacro_unique.cpp", "macro",
        "X-macro, distinct names", loc_family="xmacro"),
    Arm("reflect", "bench_reflect.cpp", "native",
        "P2996 + P3394 annotation query", loc_family="reflect"),
    Arm("reflect_plain", "bench_reflect_plain.cpp", "native",
        "P2996", loc_family="reflect_plain"),
    Arm("reflect_visit", "bench_reflect_visit.cpp", "native",
        "P2996 behind a callback API", loc_family="reflect_visit"),
    # Supplementary session S3 (2026-11-20): other native formulations of the same P2996
    # queries, to separate how the members are iterated from the reflection queries.
    Arm("reflect_array", "bench_reflect_array.cpp", "native",
        "P2996, expansion statement over a constant array (destructuring)", loc_family="reflect_array"),
    Arm("reflect_index", "bench_reflect_index.cpp", "native",
        "P2996 through a P1061 index pack (integer_sequence tuple protocol)", loc_family="reflect_index"),
    Arm("reflect_seq", "bench_reflect_seq.cpp", "native",
        "P2996 through an index-sequence helper", loc_family="reflect_seq"),
    Arm("p1061", "bench_p1061.cpp", "p1061",
        "P1061 structured-binding pack", loc_family="p1061"),
    Arm("p1061_visit", "bench_p1061_visit.cpp", "p1061",
        "P1061 behind a callback API", loc_family="p1061_visit"),
    Arm("pfr", "bench_pfr.cpp", "library",
        "Boost.PFR, default (C++26 P1061 path)", loc_family="pfr"),
    Arm("pfr_classic", "bench_pfr.cpp", "library",
        "Boost.PFR, C++17 path", ("-DBOOST_PFR_USE_CPP26=0",), loc_family="pfr"),
    # Same per-type code as pfr; the flag only adds <meta> and core26_reflection.hpp to the
    # parse (a fixed cost). An A/A control for per-type cost, not for fixed cost.
    Arm("pfr_native", "bench_pfr.cpp", "library",
        "Boost.PFR, reflection flag set (A/A for per-type cost)",
        ("-DBOOST_PFR_USE_CPP26_REFLECTION=1",), loc_family="pfr"),
    Arm("rflcpp", "bench_rflcpp.cpp", "library",
        "reflect-cpp, C++20 path", loc_family="rflcpp"),
    # reflect-cpp tests the macro with #ifdef: never pass =0 to mean "off".
    Arm("rflcpp_native", "bench_rflcpp.cpp", "library",
        "reflect-cpp, C++26 path", ("-DREFLECTCPP_USE_CPP26_REFLECTION",), loc_family="rflcpp"),
    Arm("glaze_native", "bench_glaze.cpp", "library",
        "Glaze, P2996 backend", ("-DGLZ_REFLECTION26=1",), loc_family="glaze"),
    Arm("glaze_classic", "bench_glaze.cpp", "library",
        "Glaze, traditional backend (forced)", ("-DGLZ_REFLECTION26=0",), loc_family="glaze"),
    # The cost of -freflection itself on code that does not use reflection: the same
    # arms with the flag switched off (the last flag wins). Expected: identical code.
    Arm("manual_unique_noflag", "bench_manual_unique.cpp", "hand-written",
        "hand-written, distinct names, -fno-reflection", ("-fno-reflection",), loc_family="manual"),
    Arm("p1061_noflag", "bench_p1061.cpp", "p1061",
        "P1061 structured-binding pack, -fno-reflection", ("-fno-reflection",), loc_family="p1061"),
    Arm("pfr_noflag", "bench_pfr.cpp", "library",
        "Boost.PFR, default, -fno-reflection", ("-fno-reflection",), loc_family="pfr"),
    Arm("rflcpp_noflag", "bench_rflcpp.cpp", "library",
        "reflect-cpp, C++20 path, -fno-reflection", ("-fno-reflection",), loc_family="rflcpp"),
    Arm("glaze_classic_noflag", "bench_glaze.cpp", "library",
        "Glaze, traditional backend, -fno-reflection", ("-DGLZ_REFLECTION26=0", "-fno-reflection"),
        loc_family="glaze"),
    # Does -ftime-report itself inflate compile time? The same compiles without it,
    # compared on external wall time only.
    Arm("reflect_plain_noreport", "bench_reflect_plain.cpp", "native",
        "P2996, without -ftime-report", loc_family="reflect_plain", report=False),
    Arm("pfr_noreport", "bench_pfr.cpp", "library",
        "Boost.PFR, default, without -ftime-report", loc_family="pfr", report=False),
    Arm("manual_unique_noreport", "bench_manual_unique.cpp", "hand-written",
        "hand-written, distinct names, without -ftime-report", loc_family="manual", report=False),
    Arm("reflect_split", "bench_reflect_split.cpp", "native",
        "P2996 + P3394, one function per call", loc_family="reflect"),
    Arm("pfr_split", "bench_pfr_split.cpp", "library",
        "Boost.PFR, one function per call", loc_family="pfr"),
]}


@dataclass(frozen=True)
class Pair:
    a: str
    b: str
    expect: str                      # "identical" (same disassembly) | "differs"
    isolates: str
    # function-name regexes that must be defined in one arm's object and not the other's
    only_in_a: tuple[str, ...] = ()
    only_in_b: tuple[str, ...] = ()
    # regexes that must match one arm's preprocessed TU and not the other's
    src_only_in_a: tuple[str, ...] = ()
    src_only_in_b: tuple[str, ...] = ()


ANNOTATION_QUERY = r"annotations_of_with_type\(Member"
P2996_ENUM = r"nonstatic_data_members_of\(\^\^Type"
P1061_PACK = r"\[\.\.\. Members\]"
CALLBACK = r"ForEachField\(V, \[&\]"
# S3 markers (whitespace-tolerant). define_static_array is itself built on
# reflect_constant_array in <meta>, so the array marker names the expansion statement.
ANY_EXPANSION = r"\btemplate\s+for\s*\("
SPAN_EXPANSION = r"template\s+for\s*\(\s*constexpr\s+auto\s+Member\s*:\s*std::define_static_array"
ARRAY_EXPANSION = r"template\s+for\s*\(\s*constexpr\s+auto\s+Member\s*:\s*\[:\s*std::meta::reflect_constant_array"
INDEX_PACK = r"constexpr\s+auto\s*\[\s*\.\.\.\s*I\s*\]\s*=\s*std::make_index_sequence"
INDEX_HELPER = r"ReflectSeq::WriteMembers\s*\(\s*Writer\s*,\s*V\s*,\s*std::make_index_sequence"
SB_PACK = r"\[\s*\.\.\.\s*\w+\s*\]"   # any structured-binding pack

PAIRS: list[Pair] = [
    Pair("reflect", "reflect_plain", "differs", "the P3394 annotation query",
         src_only_in_a=(ANNOTATION_QUERY,)),
    Pair("reflect_plain", "reflect_visit", "differs", "API shape (inline vs callback), P2996",
         src_only_in_b=(CALLBACK,)),
    Pair("p1061", "p1061_visit", "differs", "API shape (inline vs callback), P1061",
         src_only_in_b=(CALLBACK,)),
    Pair("reflect_plain", "p1061", "differs",
         "enumeration mechanism (P2996 vs P1061), inline; also <meta> in the parse (fixed cost)",
         src_only_in_a=(P2996_ENUM,), src_only_in_b=(P1061_PACK,)),
    Pair("reflect_visit", "p1061_visit", "differs",
         "enumeration mechanism, callback API; also <meta> in the parse (fixed cost)",
         src_only_in_a=(P2996_ENUM,), src_only_in_b=(P1061_PACK,)),
    Pair("reflect_plain", "reflect_array", "differs",
         "expansion-statement lowering: over std::span (iterating) vs over a constant array "
         "(destructuring); the same member query",
         src_only_in_a=(SPAN_EXPANSION,), src_only_in_b=(ARRAY_EXPANSION,)),
    Pair("reflect_plain", "reflect_index", "differs",
         "iteration form: expansion statement vs a P1061 index pack (tuple protocol of "
         "integer_sequence); the same member query",
         src_only_in_a=(ANY_EXPANSION,), src_only_in_b=(INDEX_PACK, SB_PACK)),
    Pair("reflect_plain", "reflect_seq", "differs",
         "iteration form: expansion statement vs an index-sequence helper; the same member query",
         src_only_in_a=(ANY_EXPANSION,), src_only_in_b=(INDEX_HELPER,)),
    Pair("reflect_index", "reflect_seq", "differs",
         "iteration form without an expansion statement: P1061 index pack vs index-sequence helper",
         src_only_in_a=(INDEX_PACK, SB_PACK), src_only_in_b=(INDEX_HELPER,)),
    Pair("reflect_seq", "p1061", "differs",
         "enumeration mechanism (P2996 vs P1061) without an expansion statement; also <meta> in "
         "the parse",
         src_only_in_a=(P2996_ENUM,), src_only_in_b=(P1061_PACK,)),
    Pair("reflect_index", "p1061", "differs",
         "P2996 through a P1061 index pack vs a P1061 pack of the fields; also <meta> in the parse",
         src_only_in_a=(P2996_ENUM, INDEX_PACK), src_only_in_b=(P1061_PACK,)),
    Pair("p1061_visit", "pfr", "differs", "Boost.PFR's machinery around the same P1061 core",
         only_in_b=(r"boost::pfr::detail::for_each_field_impl",)),
    Pair("manual", "manual_unique", "differs", "one overloaded name vs distinct names",
         only_in_a=(r"^Synth::WriteManual\(",), only_in_b=(r"^Synth::WriteManualS\d+\(",)),
    Pair("xmacro", "xmacro_unique", "differs", "one overloaded name vs distinct names",
         only_in_a=(r"^Synth::WriteXMacro\(",), only_in_b=(r"^Synth::WriteXMacroS\d+\(",)),
    Pair("pfr", "pfr_native", "identical",
         "nothing per type: BOOST_PFR_USE_CPP26_REFLECTION does not reach for_each_field; "
         "the flag only adds headers (fixed cost)",
         src_only_in_b=(r"reference_by_index",)),
    Pair("pfr", "pfr_classic", "differs", "Boost.PFR C++26 path vs C++17 path",
         only_in_b=(r"boost::pfr::detail::tie_as_tuple", r"boost::pfr::detail::for_each_field_dispatcher")),
    Pair("rflcpp", "rflcpp_native", "differs", "reflect-cpp C++20 path vs C++26 path",
         only_in_a=(r"rfl::internal::cpp20::bind_to_tuple",),
         only_in_b=(r"rfl::internal::cpp26::bind_to_tuple",)),
    Pair("glaze_classic", "glaze_native", "differs", "Glaze traditional vs P2996 backend",
         only_in_b=(r"glz::detail::get_member_ref", r"glz::detail::to_tie_p2996_impl")),
    Pair("manual_unique", "manual_unique_noflag", "identical", "the -freflection flag only"),
    Pair("p1061", "p1061_noflag", "identical", "the -freflection flag only"),
    Pair("pfr", "pfr_noflag", "identical", "the -freflection flag only"),
    Pair("rflcpp", "rflcpp_noflag", "identical", "the -freflection flag only"),
    Pair("glaze_classic", "glaze_classic_noflag", "identical", "the -freflection flag only"),
    Pair("reflect", "reflect_split", "differs", "call-site layout only (-O2 control)",
         only_in_a=(r"^Bench\(\)$",), only_in_b=(r"^BenchS0\(\)$",)),
    Pair("pfr", "pfr_split", "differs", "call-site layout only (-O2 control)",
         only_in_a=(r"^Bench\(\)$",), only_in_b=(r"^BenchS0\(\)$",)),
]

REFLECTION_ARMS = {"reflect", "reflect_plain", "reflect_visit", "reflect_array", "reflect_index",
                   "reflect_seq", "glaze_native"}


def oracle_variants() -> dict[tuple[str, ...], dict]:
    """Every distinct flag set a timed (non-overload) arm is compiled with, and the
    backend configuration the oracle must report under it."""
    out = {}
    for a in ARMS.values():
        f = a.flags
        if f in out:
            continue
        noref = "-fno-reflection" in f
        out[f] = {
            "reflection": not noref,
            "expect": {
                "BOOST_PFR_USE_CPP26": "0" if "-DBOOST_PFR_USE_CPP26=0" in f else "1",
                "BOOST_PFR_USE_CPP26_REFLECTION": "1" if "-DBOOST_PFR_USE_CPP26_REFLECTION=1" in f else "0",
                "GLZ_REFLECTION26": "0" if ("-DGLZ_REFLECTION26=0" in f or noref) else "1",
                "REFLECTCPP_USE_CPP26_REFLECTION": "1" if "-DREFLECTCPP_USE_CPP26_REFLECTION" in f else "0",
            },
        }
    return out


def compiler_tag(name: str) -> str | None:
    return name.partition("@")[2] or None


def get(name: str) -> Arm:
    base, _, tag = name.partition("@")
    if base in ARMS:
        arm = ARMS[base]
    else:
        import overload
        arm = overload.arm(base)
    return replace(arm, name=name, label=f"{arm.label} [{tag}]") if tag else arm
