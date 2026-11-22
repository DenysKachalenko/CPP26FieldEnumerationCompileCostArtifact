# SPDX-License-Identifier: MIT
"""Synthetic corpora, per-arm benchmark translation units, and the value-level oracle.

    python generate.py <out_dir> <n_structs> <n_fields> [scalar|rich|hetero]

Corpora:
- scalar: N structs of M fields drawn cyclically from eight integer, floating-point
  and bool types (every struct has the same member list).
- rich: the same with strings, vectors and optionals.
- hetero: a heterogeneous type graph. Field counts vary per struct (log-normal,
  median M); fields include enums, nested structs (up to MAX_LEVEL deep), and vectors
  and optionals of structs. The corpus is prefix-stable: the first k types are the
  same for every N, so the marginal cost of added types is well defined.
"""
from __future__ import annotations
import math
import pathlib
import random

HERE = pathlib.Path(__file__).resolve().parent
INCLUDE = HERE.parent / "Include" / "RB"

PALETTE = [
    "std::int32_t", "std::int64_t", "float", "double",
    "std::uint8_t", "bool", "std::uint16_t", "std::uint64_t",
]
RICH_PALETTE = [
    "std::int32_t", "std::string", "std::vector<std::int32_t>",
    "std::optional<std::int32_t>", "float", "std::optional<std::string>",
    "std::vector<double>", "std::uint8_t",
]
PALETTES = {"scalar": PALETTE, "rich": RICH_PALETTE}

# Distinct, non-zero value per (struct seed, field index), so that a serializer that
# drops, duplicates or reorders fields produces different bytes.
FILL = {
    "std::int32_t": "static_cast<std::int32_t>(Seed * 1009 + {i} + 1)",
    "std::int64_t": "static_cast<std::int64_t>(Seed) * 4294967311LL + {i} + 1",
    "float": "static_cast<float>(Seed * 1009 + {i}) + 0.25f",
    "double": "static_cast<double>(Seed * 1009 + {i}) + 0.5",
    "std::uint8_t": "static_cast<std::uint8_t>(Seed * 37 + {i} + 1)",
    # Bool fields sit at indices 5, 13, 21, ... of the palette: alternate them by i / 8.
    "bool": "((Seed + {i} / 8) % 2) == 0",
    "std::uint16_t": "static_cast<std::uint16_t>(Seed * 1009 + {i} + 1)",
    "std::uint64_t": "0x0102030405060708ull * static_cast<std::uint64_t>(Seed + 1) + {i}",
    "std::string": 'std::string("s") + std::to_string(Seed) + "_" + std::to_string({i})',
    "std::vector<std::int32_t>": "std::vector<std::int32_t>{Seed, {i}, Seed + {i} + 1}",
    "std::optional<std::int32_t>":
        "((Seed + {i}) % 3 != 0) ? std::optional<std::int32_t>{Seed * 7 + {i}} : std::nullopt",
    "std::optional<std::string>":
        '((Seed + {i}) % 3 != 1) ? std::optional<std::string>{"o" + std::to_string(Seed + {i})}'
        " : std::nullopt",
    "std::vector<double>": "std::vector<double>{Seed + 0.5, {i} + 0.25}",
}

# Hetero corpus: enums (name, underlying type, enumerator count) and field-kind weights.
ENUMS = [("E0", "std::uint8_t", 3), ("E1", "std::int32_t", 5), ("E2", "std::uint16_t", 4),
         ("E3", "std::uint8_t", 7), ("E4", "std::int64_t", 2), ("E5", "std::uint32_t", 6)]
HETERO_KINDS = [("leaf", 62), ("enum", 10), ("struct", 14), ("vec_struct", 8), ("opt_struct", 6)]
HETERO_LEAVES = PALETTE + RICH_PALETTE[1:4] + RICH_PALETTE[5:7]
MAX_LEVEL = 6
TARGET_WINDOW = 40

HEADER_TYPES = ("#pragma once\n#include <cstdint>\n#include <optional>\n"
                "#include <string>\n#include <vector>\n")


# ---- Layout: the member list of every struct ------------------------------------------

def _field_types(m, palette):
    return [palette[i % len(palette)] for i in range(m)]


def _uniform_layout(n, m, palette):
    fields = [{"kind": "leaf", "type": t} for t in _field_types(m, palette)]
    return [fields for _ in range(n)]


def _hetero_layout(n, median_fields):
    median_fields = max(1, median_fields)
    layout, level = [], []
    kinds, weights = zip(*HETERO_KINDS)
    for i in range(n):
        rng = random.Random(f"hetero|{median_fields}|{i}")
        m = max(1, min(4 * median_fields,
                       round(rng.lognormvariate(math.log(median_fields), 0.6))))
        targets = [t for t in range(max(0, i - TARGET_WINDOW), i) if level[t] < MAX_LEVEL]
        fields, lvl = [], 1
        for _ in range(m):
            kind = rng.choices(kinds, weights)[0]
            if kind in ("struct", "vec_struct", "opt_struct") and not targets:
                kind = "leaf"
            if kind == "leaf":
                fields.append({"kind": "leaf", "type": rng.choice(HETERO_LEAVES)})
            elif kind == "enum":
                e = rng.choice(ENUMS)
                fields.append({"kind": "enum", "type": e[0], "count": e[2]})
            else:
                t = rng.choice(targets)
                lvl = max(lvl, level[t] + 1)
                fields.append({"kind": kind, "target": f"S{t}"})
        layout.append(fields)
        level.append(lvl)
    return layout


def layout(n, m, corpus):
    if corpus == "hetero":
        return _hetero_layout(n, m)
    return _uniform_layout(n, m, PALETTES[corpus])


def _ctype(f):
    k = f["kind"]
    if k in ("leaf", "enum"):
        return f["type"]
    if k == "struct":
        return f["target"]
    if k == "vec_struct":
        return f"std::vector<{f['target']}>"
    return f"std::optional<{f['target']}>"


# ---- Emitters ---------------------------------------------------------------------------

def _names(n):
    return [f"S{k}" for k in range(n)]


def _struct(name, fields):
    body = "\n".join(f"\t{_ctype(f)} M{i};" for i, f in enumerate(fields))
    return f"struct {name}\n{{\n{body}\n}};"


def _manual_stmt(i, f, callee):
    k, v = f["kind"], f"V.M{i}"
    if k in ("leaf", "enum"):
        return f"\tRB::Enc::Value(Writer, {v});"
    fn = callee(f["target"])
    if k == "struct":
        return f"\t{fn}(Writer, {v});"
    if k == "vec_struct":
        return (f"\tWriter.PutU64({v}.size());\n\tfor (const auto& E : {v})\n\t{{\n"
                f"\t\t{fn}(Writer, E);\n\t}}")
    return f"\tWriter.PutU8({v} ? 1 : 0);\n\tif ({v})\n\t{{\n\t\t{fn}(Writer, *{v});\n\t}}"


def _manual(name, m_or_fields, fn="WriteManual", order=None, callee=None):
    fields = (m_or_fields if isinstance(m_or_fields, list)
              else [{"kind": "leaf", "type": "int"}] * m_or_fields)
    callee = callee or (lambda target: "WriteManual")
    order = range(len(fields)) if order is None else order
    body = "\n".join(_manual_stmt(i, fields[i], callee) for i in order)
    return f"inline void {fn}(RB::FByteWriter& Writer, const {name}& V)\n{{\n{body}\n}}"


def _xmacro(name, m_or_fields, macro="RB_XM_SERIALIZER({name}, {name}_FIELDS)"):
    # One field per line: the canonical formatting, so LOC compares with hand-written code.
    m = len(m_or_fields) if isinstance(m_or_fields, list) else m_or_fields
    flist = " \\\n".join(f"\tX(M{i})" for i in range(m))
    return f"#define {name}_FIELDS(X) \\\n{flist}\n{macro.format(name=name)}"


def _namespace_file(includes, blocks):
    return (f"#pragma once\n{includes}\n\nnamespace Synth\n{{\n\n"
            + "\n\n".join(blocks) + "\n\n} // namespace Synth\n")


def _fill_stmt(i, f):
    k, v = f["kind"], f"V.M{i}"
    if k == "leaf":
        return f"\t{v} = {FILL[f['type']].replace('{i}', str(i))};"
    if k == "enum":
        return f"\t{v} = static_cast<{f['type']}>((Seed + {i}) % {f['count']});"
    # Child seeds stay bounded, so the int arithmetic in FILL cannot overflow.
    if k == "struct":
        return f"\tFill({v}, (Seed * 7 + {i}) % 9973);"
    if k == "vec_struct":
        return (f"\t{v}.resize(static_cast<std::size_t>((Seed + {i}) % 3 + 1));\n"
                f"\tfor (std::size_t I = 0; I < {v}.size(); ++I)\n\t{{\n"
                f"\t\tFill({v}[I], (Seed * 11 + {i} + static_cast<int>(I)) % 9973);\n\t}}")
    return (f"\tif ((Seed + {i}) % 2 == 0)\n\t{{\n\t\t{v}.emplace();\n"
            f"\t\tFill(*{v}, (Seed * 13 + {i}) % 9973);\n\t}}")


def _fill(name, fields):
    body = "\n".join(_fill_stmt(i, f) for i, f in enumerate(fields))
    return f"inline void Fill({name}& V, int Seed)\n{{\n{body}\n}}"


def _enums():
    return "\n\n".join(
        f"enum class {e} : {u}\n{{\n" + ",\n".join(f"\tV{k}" for k in range(c)) + "\n};"
        for e, u, c in ENUMS)


# Benchmark TUs: (file, include block, call). "{n}" in a call is the struct name.
BENCH_TUS = {
    "bench_manual.cpp": ('#include "manual.hpp"', "Synth::WriteManual"),
    "bench_manual_unique.cpp": ('#include "manual_unique.hpp"', "Synth::WriteManual{n}"),
    "bench_xmacro.cpp": ('#include "xmacro_defs.hpp"', "Synth::WriteXMacro"),
    "bench_xmacro_unique.cpp": ('#include "xmacro_unique_defs.hpp"', "Synth::WriteXMacro{n}"),
    "bench_reflect.cpp": ('#include "RB/Reflect.hpp"\n#include "types.hpp"', "RB::Reflect::Write"),
    "bench_reflect_plain.cpp": ('#include "RB/ReflectPlain.hpp"\n#include "types.hpp"',
                                "RB::ReflectPlain::Write"),
    "bench_reflect_visit.cpp": ('#include "RB/ReflectVisit.hpp"\n#include "types.hpp"',
                                "RB::ReflectVisit::Write"),
    "bench_reflect_array.cpp": ('#include "RB/ReflectArray.hpp"\n#include "types.hpp"',
                                "RB::ReflectArray::Write"),
    "bench_reflect_index.cpp": ('#include "RB/ReflectIndex.hpp"\n#include "types.hpp"',
                                "RB::ReflectIndex::Write"),
    "bench_reflect_seq.cpp": ('#include "RB/ReflectSeq.hpp"\n#include "types.hpp"',
                              "RB::ReflectSeq::Write"),
    "bench_p1061.cpp": ('#include "RB/P1061.hpp"\n#include "types.hpp"', "RB::P1061::Write"),
    "bench_p1061_visit.cpp": ('#include "RB/P1061Visit.hpp"\n#include "types.hpp"',
                              "RB::P1061Visit::Write"),
    "bench_pfr.cpp": ('#include "RB/PfrArm.hpp"\n#include "types.hpp"', "RB::Pfr::Write"),
    "bench_rflcpp.cpp": ('#include "RB/RflArm.hpp"\n#include "types.hpp"', "RB::Rfl::Write"),
    "bench_glaze.cpp": ('#include "RB/GlazeArm.hpp"\n#include "types.hpp"', "RB::Glaze::Write"),
}
# Same calls, one function per call site (the -O2 layout control).
SPLIT_TUS = {
    "bench_reflect_split.cpp": ('#include "RB/Reflect.hpp"\n#include "types.hpp"',
                                "RB::Reflect::Write"),
    "bench_pfr_split.cpp": ('#include "RB/PfrArm.hpp"\n#include "types.hpp"', "RB::Pfr::Write"),
}
# A uniquely named X-macro serializer cannot recurse into nested structs.
NOT_IN_HETERO = {"bench_xmacro_unique.cpp", "xmacro_unique"}

# Oracle: every arm callable from one TU; flag variants (Boost.PFR, reflect-cpp and
# Glaze backends) are covered by building the same TU with each variant's flags.
ORACLE_ARMS = [
    ("reflect", "RB::Reflect::Write(W, V)"),
    ("reflect_plain", "RB::ReflectPlain::Write(W, V)"),
    ("reflect_visit", "RB::ReflectVisit::Write(W, V)"),
    ("reflect_array", "RB::ReflectArray::Write(W, V)"),
    ("reflect_index", "RB::ReflectIndex::Write(W, V)"),
    ("reflect_seq", "RB::ReflectSeq::Write(W, V)"),
    ("p1061", "RB::P1061::Write(W, V)"),
    ("p1061_visit", "RB::P1061Visit::Write(W, V)"),
    ("manual", "Synth::WriteManual(W, V)"),
    ("xmacro", "Synth::WriteXMacro(W, V)"),
    ("xmacro_unique", "Synth::WriteXMacro{n}(W, V)"),
    ("pfr", "RB::Pfr::Write(W, V)"),
    ("rflcpp", "RB::Rfl::Write(W, V)"),
    ("glaze", "RB::Glaze::Write(W, V)"),
]
ORACLE_INCLUDES = ['"RB/Reflect.hpp"', '"RB/ReflectPlain.hpp"', '"RB/ReflectVisit.hpp"',
                   '"RB/ReflectArray.hpp"', '"RB/ReflectIndex.hpp"', '"RB/ReflectSeq.hpp"',
                   '"RB/P1061.hpp"', '"RB/P1061Visit.hpp"', '"RB/PfrArm.hpp"',
                   '"RB/RflArm.hpp"', '"RB/GlazeArm.hpp"', '"manual.hpp"',
                   '"manual_unique.hpp"', '"xmacro_defs.hpp"', '"xmacro_unique_defs.hpp"',
                   '"oracle_fill.hpp"']

ORACLE_PRELUDE = r'''
#include <cstdio>
#include <cstddef>
#include <string>

namespace
{
	int Failures = 0;
	std::size_t RefBytes = 0;
	std::size_t RefNonZero = 0;

	template<typename WriteFn>
	void Same(const char* Arm, const char* Type, const RB::FByteWriter& Ref, WriteFn&& Write)
	{
		RB::FByteWriter W;
		Write(W);
		if (W.Buffer != Ref.Buffer)
		{
			std::printf("MISMATCH %s on %s (%zu vs %zu bytes)\n", Arm, Type, W.Buffer.size(), Ref.Buffer.size());
			++Failures;
		}
	}

	template<typename WriteFn>
	void MustDiffer(const char* Control, const char* Type, const RB::FByteWriter& Ref, WriteFn&& Write)
	{
		RB::FByteWriter W;
		Write(W);
		if (W.Buffer == Ref.Buffer)
		{
			std::printf("BLIND ORACLE: control %s on %s matches the reference\n", Control, Type);
			++Failures;
		}
	}

	void Account(const RB::FByteWriter& Ref)
	{
		RefBytes += Ref.Buffer.size();
		for (std::byte B : Ref.Buffer)
		{
			RefNonZero += B != std::byte{0};
		}
	}

	const char* Flag(int Value)
	{
		return Value ? "1" : "0";
	}
}
'''


REFLECTION_ORACLE = {"reflect", "reflect_plain", "reflect_visit", "reflect_array", "reflect_index",
                     "reflect_seq"}
REFLECTION_INCLUDES = {'"RB/Reflect.hpp"', '"RB/ReflectPlain.hpp"', '"RB/ReflectVisit.hpp"',
                       '"RB/ReflectArray.hpp"', '"RB/ReflectIndex.hpp"', '"RB/ReflectSeq.hpp"'}


def _levels(lay):
    level = []
    for fields in lay:
        deps_ = [level[int(f["target"][1:])] for f in fields if "target" in f]
        level.append(1 + max(deps_, default=0))
    return level


def oracle_sample(lay, cap: int = 60) -> list[int]:
    """Indices the oracle checks: every struct when there are at most `cap`, otherwise one
    of every shape class (1 field, nested-only, most fields, deepest, each field kind)
    plus an even stride. Every type stays defined; only the checked ones are serialized."""
    n = len(lay)
    if n <= cap:
        return list(range(n))
    level = _levels(lay)
    picks = set()
    first = lambda pred: next((i for i in range(n) if pred(i)), None)
    for pred in (lambda i: len(lay[i]) == 1,
                 lambda i: all("target" in f for f in lay[i]),
                 lambda i: any(f["kind"] == "enum" for f in lay[i]),
                 lambda i: any(f["kind"] == "vec_struct" for f in lay[i]),
                 lambda i: any(f["kind"] == "opt_struct" for f in lay[i])):
        i = first(pred)
        if i is not None:
            picks.add(i)
    picks.update(sorted(range(n), key=lambda i: -len(lay[i]))[:3])
    picks.update(sorted(range(n), key=lambda i: -level[i])[:3])
    picks.add(n - 1)
    step = max(1, n // max(1, cap - len(picks)))
    picks.update(range(0, n, step))
    return sorted(picks)[:max(cap, len(picks))]


def _oracle(names, lay, corpus, reflection: bool = True, check: list[int] | None = None):
    oracle_arms = [(a, c) for a, c in ORACLE_ARMS
                   if not (corpus == "hetero" and a in NOT_IN_HETERO)
                   and (reflection or a not in REFLECTION_ORACLE)]
    includes = [i for i in ORACLE_INCLUDES
                if not (corpus == "hetero" and i == '"xmacro_unique_defs.hpp"')
                and (reflection or i not in REFLECTION_INCLUDES)]
    check = list(range(len(names))) if check is None else check
    blocks = []
    for k in check:
        n, fields = names[k], lay[k]
        calls = "\n".join(
            f'\t\tSame("{arm}", "{n}", Ref, [&](RB::FByteWriter& W) {{ {call.replace("{n}", n)}; }});'
            for arm, call in oracle_arms)
        control = (f'\t\tMustDiffer("reversed", "{n}", Ref, [&](RB::FByteWriter& W) '
                   f'{{ Synth::WriteReversed{n}(W, V); }});') if len(fields) >= 2 else ""
        blocks.append(
            f"\t{{\n\t\tSynth::{n} V{{}};\n\t\tSynth::Fill(V, {k + 1});\n"
            f"\t\tRB::FByteWriter Ref;\n\t\tSynth::WriteManual{n}(Ref, V);\n\t\tAccount(Ref);\n"
            f"{calls}\n{control}\n\t}}")
    config = (
        '\tstd::printf("config: BOOST_PFR_USE_CPP26=%s BOOST_PFR_USE_CPP26_REFLECTION=%s '
        'GLZ_REFLECTION26=%s REFLECTCPP_USE_CPP26_REFLECTION=%s\\n",\n'
        "\t\tFlag(BOOST_PFR_USE_CPP26), Flag(BOOST_PFR_USE_CPP26_REFLECTION), Flag(GLZ_REFLECTION26),\n"
        "#ifdef REFLECTCPP_USE_CPP26_REFLECTION\n\t\t\"1\");\n#else\n\t\t\"0\");\n#endif\n")
    fields_desc = (f"{len(lay[0]) if lay else 0} fields" if corpus != "hetero"
                   else f"{sum(len(lay[k]) for k in check)} fields in total, nested")
    summary = (
        "\tif (Failures != 0)\n\t{\n"
        '\t\tstd::printf("FAIL: %d failure(s)\\n", Failures);\n\t\treturn 1;\n\t}\n'
        f'\tstd::printf("OK: {len(oracle_arms)} arms == manual_unique on {len(check)} of {len(names)} {corpus} structs, '
        f'{fields_desc} (%zu bytes, %zu non-zero; reversed control detected)\\n", RefBytes, RefNonZero);\n')
    return ("\n".join(f"#include {i}" for i in includes) + f"\n{ORACLE_PRELUDE}\nint main()\n{{\n{config}"
            + "\n".join(blocks) + f"\n{summary}\treturn 0;\n}}\n")


def generate(out_dir: pathlib.Path, n_structs: int, n_fields: int,
             corpus: str = "scalar") -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    names = _names(n_structs)
    lay = layout(n_structs, n_fields, corpus)
    hetero = corpus == "hetero"

    def write(name, text):
        path = out_dir / name
        if not path.is_file() or path.read_text() != text:
            path.write_text(text)

    enums = (_enums() + "\n\n") if hetero else ""
    write("types.hpp", HEADER_TYPES + "\nnamespace Synth\n{\n\n" + enums
          + "\n\n".join(_struct(n, f) for n, f in zip(names, lay)) + "\n\n} // namespace Synth\n")
    enc = '#include "RB/Enc.hpp"\n#include "types.hpp"'
    write("manual.hpp", _namespace_file(enc, [_manual(n, f) for n, f in zip(names, lay)]))
    unique = lambda target: f"WriteManual{target}"
    write("manual_unique.hpp", _namespace_file(
        enc, [_manual(n, f, fn=f"WriteManual{n}", callee=unique) for n, f in zip(names, lay)]))
    xm = '#include "RB/XMacro.hpp"\n#include "types.hpp"'
    write("xmacro_defs.hpp", _namespace_file(xm, [_xmacro(n, f) for n, f in zip(names, lay)]))
    if not hetero:
        write("xmacro_unique_defs.hpp", _namespace_file(xm, [
            _xmacro(n, f, macro="RB_XM_SERIALIZER_NAMED({name}, WriteXMacro{name}, {name}_FIELDS)")
            for n, f in zip(names, lay)]))
    write("oracle_fill.hpp", _namespace_file(enc + '\n#include "manual_unique.hpp"', [
        _fill(n, f) + "\n\n" + _manual(n, f, fn=f"WriteReversed{n}",
                                       order=range(len(f) - 1, -1, -1), callee=unique)
        for n, f in zip(names, lay)]))

    # Each payload is an object defined elsewhere, so at -O2 the optimizer serializes values it
    # cannot see (a local `V{}` would let it fold the all-zero fields; Audit.md, the -O2
    # constant-folding item). Timed compiles never link.
    externs = "\n".join(f"extern Synth::{n} Payload{n};" for n in names)
    for tu, (include, call) in BENCH_TUS.items():
        if hetero and tu in NOT_IN_HETERO:
            continue
        calls = "\n".join(f"\t{call.replace('{n}', n)}(Sink, Payload{n});" for n in names)
        write(tu, f"{include}\n\nRB::FByteWriter Sink;\n{externs}\n\nvoid Bench()\n{{\n{calls}\n}}\n")
    for tu, (include, call) in SPLIT_TUS.items():
        fns = "\n\n".join(f"void Bench{n}()\n{{\n\t{call}(Sink, Payload{n});\n}}" for n in names)
        write(tu, f"{include}\n\nRB::FByteWriter Sink;\n{externs}\n\n{fns}\n")
    sample = oracle_sample(lay)
    write("correctness_synth.cpp", _oracle(names, lay, corpus, True, sample))
    # The same check without the reflection arms, for builds with -fno-reflection.
    write("correctness_noreflect.cpp", _oracle(names, lay, corpus, False, sample))


def describe(n, m, corpus) -> dict:
    """Shape statistics of a corpus (for the paper's corpus description)."""
    lay = layout(n, m, corpus)
    counts = sorted(len(f) for f in lay)
    kinds = {}
    for fields in lay:
        for f in fields:
            kinds[f["kind"]] = kinds.get(f["kind"], 0) + 1
    total = sum(counts)
    return {"structs": n, "fields_total": total, "fields_median": counts[len(counts) // 2] if counts else 0,
            "fields_min": counts[0] if counts else 0, "fields_max": counts[-1] if counts else 0,
            "kind_share": {k: round(v / total, 3) for k, v in sorted(kinds.items())} if total else {}}


# ---- Maintainability (analytic, not measured) --------------------------------------

def _source_lines(text):
    """Non-blank lines that are not pure comments."""
    out = 0
    for ln in text.splitlines():
        s = ln.strip()
        if s and not s.startswith("//"):
            out += 1
    return out


ARM_HEADERS = {
    "reflect": ["Reflect.hpp", "Annotations.hpp"],
    "reflect_plain": ["ReflectPlain.hpp"],
    "reflect_visit": ["ReflectVisit.hpp"],
    "reflect_array": ["ReflectArray.hpp"],
    "reflect_index": ["ReflectIndex.hpp"],
    "reflect_seq": ["ReflectSeq.hpp"],
    "p1061": ["P1061.hpp"],
    "p1061_visit": ["P1061Visit.hpp"],
    "pfr": ["PfrArm.hpp"],
    "rflcpp": ["RflArm.hpp"],
    "glaze": ["GlazeArm.hpp"],
    "xmacro": ["XMacro.hpp"],
}


def fixed_loc(arm_family: str) -> int:
    """Lines of the arm's generic serializer header(s) — written once, for all types."""
    return sum(_source_lines((INCLUDE / h).read_text()) for h in ARM_HEADERS.get(arm_family, []))


def per_type_cost(n_fields: int) -> dict:
    """Source a user writes per added type, by mechanism family: lines and field mentions."""
    manual = _source_lines(_manual("S0", n_fields))
    xmacro = _source_lines(_xmacro("S0", n_fields))
    return {
        "manual": {"lines": manual, "field_mentions": n_fields},
        "xmacro": {"lines": xmacro, "field_mentions": n_fields},
        "reflection": {"lines": 0, "field_mentions": 0},
    }


if __name__ == "__main__":
    import sys
    corpus = sys.argv[4] if len(sys.argv) > 4 else "scalar"
    generate(pathlib.Path(sys.argv[1]), int(sys.argv[2]), int(sys.argv[3]), corpus)
