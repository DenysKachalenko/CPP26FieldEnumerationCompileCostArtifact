# SPDX-License-Identifier: MIT
"""The overload matrix: how the per-type serializer idiom drives overload resolution.

K types each get one serializer (K candidates where the idiom puts them in one
lookup set); C call sites each serialize one type (type i % K). K and C vary
separately, so the cost model T(K, C) can be identified rather than assumed. With
`prime`, a Prime() function calls every type once, so every serializer body is
instantiated however many swept call sites there are, and only lookup grows with C.

    python overload.py <out_dir> <variant> <K> <C> [M]
"""
from __future__ import annotations
import pathlib
import re

from arms import Arm
from generate import PALETTE, _field_types

# variant -> label: how the serializer is declared, and how it is called.
VARIANTS = {
    "ovl_flat": "free function per type, one name; qualified call from user code",
    "ovl_adl": "free function per type, one name, one namespace (declared like nlohmann "
               "to_json, Boost.JSON tag_invoke, fmt format_as); unqualified call from user code",
    "ovl_adl_template": "the same overloads, reached by an unqualified dependent call inside a "
                        "library dispatch template (the libraries' own call shape)",
    "ovl_constrained": "constrained function template per type, one name, ADL "
                       "(nlohmann::json v3.12 NON_INTRUSIVE declaration form)",
    "ovl_archive": "function template serialize(Archive&, T&, const unsigned int) per type, ADL "
                   "(Boost.Serialization non-intrusive / cereal external form)",
    "ovl_adl_per_ns": "free function per type, one name, one namespace per type, ADL",
    "ovl_hidden_friend": "hidden friend per type, one name, ADL",
    "ovl_member": "member function",
    "ovl_specialization": "explicit specialization of a Serializer<T> class template "
                          "(glz::meta / fmt::formatter form)",
    "ovl_unique": "free function per type, distinct name per type",
}

# A pattern each variant's generated TU must contain (checked by the preflight), so a
# variant cannot silently drift from the idiom its label names.
SHAPES = {
    "ovl_flat": r"Synth::WriteManual\(Sink, V\)",
    "ovl_adl": r"\{ Synth::S\d+ V\{\}; WriteManual\(Sink, V\); \}",
    "ovl_adl_template": r"Lib::Dispatch\(Sink, V\)",
    "ovl_constrained": r"std::enable_if_t<bIsWriter<WriterType>, int> = 0",
    "ovl_archive": r"template<class Archive>\nvoid serialize\(Archive& Ar, S\d+& V, const unsigned int Version\)",
    "ovl_adl_per_ns": r"\{ N\d+::S V\{\}; WriteManual\(Sink, V\); \}",
    "ovl_hidden_friend": r"friend void WriteManual\(RB::FByteWriter& Writer, const S\d+& V\)",
    "ovl_member": r"V\.Write\(Sink\)",
    "ovl_specialization": r"Synth::Serializer<Synth::S\d+>::Write\(Sink, V\)",
    "ovl_unique": r"Synth::WriteManualS\d+\(Sink, V\)",
}

# A minimal library-side dispatcher: the unqualified call is dependent, so ADL runs
# when Dispatch<T> is instantiated — once per type, however many call sites there are.
DISPATCH = ("namespace Lib\n{\ntemplate<class Type>\nvoid Dispatch(RB::FByteWriter& Writer, const Type& V)\n"
            "{\n\tWriteManual(Writer, V);\n}\n}\n\n")
# The constraint nlohmann::json v3.12 puts on its generated to_json templates.
IS_WRITER = ("namespace Synth\n{\ntemplate<class Type>\ninline constexpr bool bIsWriter = "
             "std::is_same_v<Type, RB::FByteWriter>;\n}\n\n")


def arm(name: str) -> Arm:
    if name not in VARIANTS:
        raise KeyError(f"unknown arm {name!r}")
    return Arm(name, f"bench_{name}.cpp", "overload", VARIANTS[name], loc_family="manual")


def _fields(m):
    return "\n".join(f"\t{t} M{i};" for i, t in enumerate(_field_types(m, PALETTE)))


def _body(m, writer="Writer", obj="V", indent="\t"):
    return "\n".join(f"{indent}RB::Enc::Value({writer}, {obj}M{i});" for i in range(m))


def _decls(variant: str, k: int, m: int) -> str:
    if variant in ("ovl_flat", "ovl_adl", "ovl_unique", "ovl_adl_template"):
        out = []
        for i in range(k):
            fn = f"WriteManualS{i}" if variant == "ovl_unique" else "WriteManual"
            out.append(f"struct S{i}\n{{\n{_fields(m)}\n}};\n\n"
                       f"inline void {fn}(RB::FByteWriter& Writer, const S{i}& V)\n{{\n"
                       f"{_body(m, obj='V.')}\n}}")
        lib = DISPATCH if variant == "ovl_adl_template" else ""
        return "namespace Synth\n{\n\n" + "\n\n".join(out) + "\n\n}\n\n" + lib
    if variant == "ovl_constrained":
        out = [f"struct S{i}\n{{\n{_fields(m)}\n}};\n\n"
               f"template<typename WriterType, std::enable_if_t<bIsWriter<WriterType>, int> = 0>\n"
               f"void WriteManual(WriterType& Writer, const S{i}& V)\n{{\n{_body(m, obj='V.')}\n}}"
               for i in range(k)]
        return IS_WRITER + "namespace Synth\n{\n\n" + "\n\n".join(out) + "\n\n}\n\n"
    if variant == "ovl_specialization":
        out = [f"struct S{i}\n{{\n{_fields(m)}\n}};\n\n"
               f"template<>\nstruct Serializer<S{i}>\n{{\n"
               f"\tstatic void Write(RB::FByteWriter& Writer, const S{i}& V)\n\t{{\n"
               f"{_body(m, obj='V.', indent=chr(9) * 2)}\n\t}}\n}};" for i in range(k)]
        return ("namespace Synth\n{\n\ntemplate<class Type>\nstruct Serializer;\n\n"
                + "\n\n".join(out) + "\n\n}\n\n")
    if variant == "ovl_adl_per_ns":
        return "\n\n".join(
            f"namespace N{i}\n{{\nstruct S\n{{\n{_fields(m)}\n}};\n\n"
            f"inline void WriteManual(RB::FByteWriter& Writer, const S& V)\n{{\n"
            f"{_body(m, obj='V.')}\n}}\n}}" for i in range(k)) + "\n\n"
    if variant == "ovl_hidden_friend":
        out = [f"struct S{i}\n{{\n{_fields(m)}\n\n"
               f"\tfriend void WriteManual(RB::FByteWriter& Writer, const S{i}& V)\n\t{{\n"
               f"{_body(m, obj='V.', indent=chr(9) * 2)}\n\t}}\n}};" for i in range(k)]
        return "namespace Synth\n{\n\n" + "\n\n".join(out) + "\n\n}\n\n"
    if variant == "ovl_member":
        out = [f"struct S{i}\n{{\n{_fields(m)}\n\n"
               f"\tvoid Write(RB::FByteWriter& Writer) const\n\t{{\n"
               f"{_body(m, obj='', indent=chr(9) * 2)}\n\t}}\n}};" for i in range(k)]
        return "namespace Synth\n{\n\n" + "\n\n".join(out) + "\n\n}\n\n"
    if variant == "ovl_archive":
        out = [f"struct S{i}\n{{\n{_fields(m)}\n}};\n\n"
               f"template<class Archive>\nvoid serialize(Archive& Ar, S{i}& V, const unsigned int Version)\n{{\n"
               f"{_body(m, writer='Ar', obj='V.')}\n}}" for i in range(k)]
        return "namespace Synth\n{\n\n" + "\n\n".join(out) + "\n\n}\n\n"
    raise KeyError(f"unknown overload variant {variant!r}")


def _call(variant: str, t: int, writer: str = "Sink", ns: str = "") -> str:
    """One call site serializing type t (ns: a namespace prefix for the oracle)."""
    typ = f"{ns}N{t}::S" if variant == "ovl_adl_per_ns" else f"{ns}Synth::S{t}"
    call = {
        "ovl_flat": f"{ns}Synth::WriteManual({writer}, V);",
        "ovl_adl": f"WriteManual({writer}, V);",
        "ovl_adl_template": f"{ns}Lib::Dispatch({writer}, V);",
        "ovl_constrained": f"WriteManual({writer}, V);",
        "ovl_archive": f"serialize({writer}, V, 0u);",
        "ovl_adl_per_ns": f"WriteManual({writer}, V);",
        "ovl_hidden_friend": f"WriteManual({writer}, V);",
        "ovl_member": f"V.Write({writer});",
        "ovl_specialization": f"{ns}Synth::Serializer<{ns}Synth::S{t}>::Write({writer}, V);",
        "ovl_unique": f"{ns}Synth::WriteManualS{t}({writer}, V);",
    }[variant]
    return f"{{ {typ} V{{}}; {call} }}"


def source(variant: str, k: int, c: int, m: int, prime: bool = False) -> str:
    head = '#include <cstdint>\n#include <type_traits>\n#include "RB/Enc.hpp"\n\n'
    targets = [i % k for i in range(c)] if k else []
    body = "RB::FByteWriter Sink;\n"
    if prime:
        body += "void Prime()\n{\n" + "\n".join(f"\t{_call(variant, t)}" for t in range(k)) + "\n}\n"
    body += "void Bench()\n{\n" + "\n".join(f"\t{_call(variant, t)}" for t in targets) + "\n}\n"
    return head + _decls(variant, k, m) + body


def generate(out_dir: pathlib.Path, variant: str, k: int, c: int, m: int = 16,
             prime: bool = False) -> pathlib.Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"bench_{variant}.cpp"
    text = source(variant, k, c, m, prime)
    if not path.is_file() or path.read_text() != text:
        path.write_text(text)
    return path


def shape_ok(variant: str, k: int = 3, m: int = 4) -> bool:
    return re.search(SHAPES[variant], source(variant, k, k, m)) is not None


def oracle(out_dir: pathlib.Path, k: int, m: int = 16) -> pathlib.Path:
    """Every variant writes the same bytes as the distinct-name serializer for the same
    types (each variant's declarations compiled in its own namespace)."""
    from generate import FILL
    out_dir.mkdir(parents=True, exist_ok=True)
    parts = ['#include <cstdint>\n#include <cstdio>\n#include <map>\n#include <optional>\n'
             '#include <string>\n#include <type_traits>\n#include <vector>\n#include "RB/Enc.hpp"\n']
    for v in VARIANTS:
        parts.append(f"namespace V_{v}\n{{\n{_decls(v, k, m)}\n}}\n")
    fills = []
    for v in VARIANTS:
        for i in range(k):
            assign = "\n".join(f"\t\tV.M{j} = {FILL[t].replace('{i}', str(j))};"
                               for j, t in enumerate(_field_types(m, PALETTE)))
            typ = f"V_{v}::N{i}::S" if v == "ovl_adl_per_ns" else f"V_{v}::Synth::S{i}"
            call = _call(v, i, "W", ns=f"V_{v}::").split("V{}; ", 1)[1].rstrip(" }")
            fills.append(f"\t{{\n\t\tconst int Seed = {i + 1};\n\t\t{typ} V{{}};\n{assign}\n"
                         f"\t\tRB::FByteWriter W;\n\t\t{call}\n"
                         f"\t\tOut[\"{v}\"].push_back(W.Buffer);\n\t}}")
    parts.append("int main()\n{\n\tstd::map<std::string, std::vector<std::vector<std::byte>>> Out;\n"
                 + "\n".join(fills) +
                 '\n\tint Bad = 0;\n\tfor (auto& [Name, Bufs] : Out)\n\t{\n'
                 '\t\tif (Bufs != Out["ovl_unique"])\n\t\t{\n'
                 '\t\t\tstd::printf("MISMATCH %s\\n", Name.c_str());\n\t\t\t++Bad;\n\t\t}\n\t}\n'
                 f'\tif (Bad == 0)\n\t{{\n\t\tstd::printf("OK: {len(VARIANTS)} overload variants agree on {k} '
                 f'types x {m} fields\\n");\n\t}}\n\treturn Bad;\n}}\n')
    path = out_dir / "correctness_overload.cpp"
    path.write_text("".join(parts))
    return path


if __name__ == "__main__":
    import sys
    out = pathlib.Path(sys.argv[1])
    m = int(sys.argv[5]) if len(sys.argv) > 5 else 16
    print(generate(out, sys.argv[2], int(sys.argv[3]), int(sys.argv[4]), m))
