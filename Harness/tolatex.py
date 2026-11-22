# SPDX-License-Identifier: MIT
"""Paper.md -> Latex/Paper.tex (ACM acmart, sigplan), the arXiv version.

Paper.md stays the single source: its number tags are checked by paperlint.py, and this
script only translates. Citations are placed by the CITES table below: every source phrase
must occur in Paper.md exactly once (otherwise the script stops), so a reworded sentence
cannot silently lose its citation. Figures are copied to Latex/Figures/.

    python tolatex.py [--paper ../Paper.md] [--out ../Latex]
"""
from __future__ import annotations
import argparse
import pathlib
import re
import shutil

PROJECT = pathlib.Path(__file__).resolve().parent.parent

# (phrase in Paper.md after joining each paragraph into one line, LaTeX that replaces it).
# "{c:keys}" in the replacement becomes a \cite; the rest is escaped like normal text.
CITES: list[tuple[str, str]] = [
    # 1. Introduction
    ("Romeo (2026a) times native reflection alone", "Romeo{c:romeo2026a} times native reflection alone"),
    ("mp-units (Pusz, 2026) runs", "mp-units{c:pusz2026} runs"),
    ("whole build with reflection enabled; and", "whole build with reflection enabled{c:lemire2025cppcon}; and"),
    ("the field-reflection library (Matsuda, 2026) lists", "the field-reflection library{c:matsuda2026} lists"),
    ("A tooling vendor's blog calls", "A tooling vendor's blog{c:wholetomato2026} calls"),
    ("\"the biggest open question\" (Whole Tomato, 2026)", "\"the biggest open question\""),
    # 2. Background
    ("(P1061R10 allows such a pack", "(P1061R10{c:wg21p1061} allows such a pack"),
    ("GCC 16 implements P2996R13, P3394R4, P3491R3, P1306R5 and P1061R10",
     "GCC 16 implements P2996R13{c:wg21p2996}, P3394R4{c:wg21p3394}, P3491R3, P1306R5 and P1061R10"),
    ("iterate those fields with an expansion statement (`template for`, P1306)",
     "iterate those fields with an expansion statement (`template for`, P1306{c:wg21p1306})"),
    ("over `std::define_static_array` (P3491)", "over `std::define_static_array` (P3491{c:wg21p3491})"),
    ("**Boost.PFR**'s classic path", "**Boost.PFR**'s classic path{c:boostpfr}"),
    ("one form, used in several of P2996R13's own examples", "one form, used in several of P2996R13's own examples{c:wg21p2996}"),
    ("**reflect-cpp** has a C++20 path", "**reflect-cpp**{c:reflectcpp} has a C++20 path"),
    ("\"considerably cheaper\" to compile, without measurements", "\"considerably cheaper\" to compile, without measurements{c:reflectcppdocs}"),
    ("**Glaze** has a traditional backend", "**Glaze**{c:glaze} has a traditional backend"),
    ("Glaze's documentation calls the count a structured-binding probe", "Glaze's documentation calls the count a structured-binding probe{c:glazedocs}"),
    # 4. Results
    ("on `<bits/stdc++.h>` (PR124925), and GCC 16.2.0", "on `<bits/stdc++.h>` (PR124925{c:gccpr124925}), and GCC 16.2.0"),
    ("another case (PR125179).", "another case (PR125179{c:gccpr125179})."),
    ("this code (PR #3112, after v9.1.0)", "this code (PR #3112{c:glazepr3112}, after v9.1.0)"),
    ("between the releases, PR125179 and PR125280.", "between the releases, PR125179 and PR125280{c:gccpr125280}."),
    ("not a property of P2996, reported as PR128928 (reproducers",
     "not a property of P2996, reported as PR128928{c:gccpr128928} (reproducers"),
    # 5. Related work
    ("**Native reflection alone.** Romeo (2026a) times", "**Native reflection alone.** Romeo{c:romeo2026a} times"),
    ("His follow-up (2026b) compares", "His follow-up{c:romeo2026b} compares"),
    ("The field-reflection library (Matsuda, 2026; table in its README since 2026-10-12)", "The field-reflection library{c:matsuda2026} (table in its README since 2026-10-12)"),
    ("mp-units (Pusz 2026) reports", "mp-units{c:pusz2026} reports"),
    ("reflect-moc's measurements of a moc replacement", "reflect-moc's measurements of a moc replacement{c:reflectmoc}"),
    ("enabled (CppCon 2025, clang-p2996)", "enabled (CppCon 2025{c:lemire2025cppcon}, clang-p2996)"),
    ("by changing what every TU instantiates.", "by changing what every TU instantiates{c:simdjsonpr2894}."),
    ("Kolpackov (GCC PR125329)", "Kolpackov (GCC PR125329{c:gccpr125329})"),
    ("Matek (Boost mailing list, 2025)", "Matek{c:matek2025}"),
    ("PR124925 (19% on", "PR124925{c:gccpr124925} (19% on"),
    ("PR125179 (a 40-fold", "PR125179{c:gccpr125179} (a 40-fold"),
    ("Sajdak (PR128900–PR128902, November 2026)", "Sajdak (PR128900–PR128902{c:gccpr128900,gccpr128901,gccpr128902}, November 2026)"),
    ("reflect-cpp's maintainer found, with Clang's `-ftime-trace`,", "reflect-cpp's maintainer found{c:reflectcpppr537}, with Clang's `-ftime-trace`,"),
    ("in the v7.7.0 release notes)", "in the v7.7.0 release notes{c:glazev770})"),
    ("enumerates members (PR #3112).", "enumerates members (PR #3112{c:glazepr3112})."),
    ("documentation claims its C++26 path is cheaper to compile without data", "documentation claims its C++26 path is cheaper to compile without data{c:reflectcppdocs}"),
    ("Glaze PR #2848 (merged", "Glaze PR #2848{c:glazepr2848} (merged"),
    ("Webber (CppCon 2026), Piper (CppCon 2026), Chen (CHEP 2026), simdjson 5.0.",
     "Webber{c:webber2026}, Piper{c:piper2026}, Chen{c:chen2026}, simdjson 5.0{c:lemire2026simdjson5}."),
    ("Metabench (Dionne) isolates", "Metabench{c:metabench} isolates"),
    ("Chochlík (P2560R0, 2022) compared", "Chochlík (P2560R0{c:wg21p2560}) compared"),
    ("ctbench (Penuchot and Falcou 2023) measures", "ctbench{c:ctbench2023} measures"),
    ("Templight (Porkoláb et al. 2006), a debugger of template instantiation, was later used to profile it",
     "Templight{c:porkolab2006}, a debugger of template instantiation, was later used to profile it{c:porkolab2009}"),
    ("Gregor and Järvi (2008) measured", "Gregor and Järvi{c:gregor2008} measured"),
    ("randomized interleaved trials (Abedi and Brecht 2017)", "randomized interleaved trials{c:abedi2017}"),
    ("awareness of setup bias (Mytkowicz et al. 2009)", "awareness of setup bias{c:mytkowicz2009}"),
    ("confidence intervals (Kalibera and Jones 2013)", "confidence intervals{c:kalibera2013}"),
    ("bootstrap intervals (Efron and Tibshirani 1993; Barrett et al. 2017)", "bootstrap intervals{c:efron1993,barrett2017}"),
    ("documented factors (Hoefler and Belli 2015)", "documented factors{c:hoefler2015}"),
    # 6. Threats
    ("Bloomberg's clang-p2996 is a self-described experimental fork", "Bloomberg's clang-p2996{c:clangp2996} is a self-described experimental fork"),
    ("the length of the name (PR128900)", "the length of the name (PR128900{c:gccpr128900})"),
    ("block-scope statics (§4.2, PR128928)", "block-scope statics (§4.2, PR128928{c:gccpr128928})"),
    ("Clang's upstream support covers primitive types only;",
     "Clang's upstream support covers primitive types only{c:llvmpr190356};"),
    ("EDG 7.0 (open source since September 2026)", "EDG 7.0{c:edg70} (open source since September 2026)"),
    ("a specifier that CWG3044 removed", "a specifier that CWG3044{c:cwg3044} removed"),
    ("posted to gcc-patches on 2026-11-16", "posted to gcc-patches on 2026-11-16{c:jelinek2026}"),
    # 3.7 pins
    ("Boost.PFR from Boost 1.92.0 (401385c), reflect-cpp v0.27.1 (e0ee3f6), Glaze v9.1.0 (43b175e)",
     "Boost.PFR from Boost 1.92.0 (401385c){c:boostpfr}, reflect-cpp v0.27.1 (e0ee3f6){c:reflectcpp}, Glaze v9.1.0 (43b175e){c:glaze}"),
]

# Tables without a "**Table N.**" caption in Paper.md, by their first header cell.
UNCAPTIONED = {"Arm": ("The serializer arms: how each enumerates the fields, and the source it needs per type.",
                       "tab:arms"),
               "Job": ("The jobs of a session (§3.5).", "tab:jobs")}

UNICODE = {"§": r"\S{}", "±": r"$\pm$", "²": r"\textsuperscript{2}", "·": r"$\cdot$", "×": r"$\times$",
           "÷": r"$\div$", "ᵃ": r"\textsuperscript{a}", "–": "--", "—": "---", "…": r"\ldots{}",
           "→": r"$\rightarrow$", "∈": r"$\in$", "−": r"$-$", "≤": r"$\leq$", "≥": r"$\geq$",
           "≈": r"$\approx$", "\u00a0": "~",
           # an unfilled placeholder (DOI, PR number) stays visible in the PDF
           "⟦": r"\textbf{[[}", "⟧": r"\textbf{]]}"}
SPECIAL = {"\\": r"\textbackslash{}", "#": r"\#", "$": r"\$", "%": r"\%", "&": r"\&", "_": r"\_",
           "{": r"\{", "}": r"\}", "~": r"\textasciitilde{}", "^": r"\textasciicircum{}",
           "<": r"\textless{}", ">": r"\textgreater{}", "|": r"\textbar{}"}


def escape(s: str) -> str:
    out = []
    for ch in s:
        out.append(SPECIAL.get(ch) or UNICODE.get(ch) or ch)
    return "".join(out)


def code(s: str) -> str:
    """Inline code: monospace, breakable after :: , and _."""
    e = escape(s).replace("...", "\x01")          # keep an ellipsis whole
    e = e.replace("::", r"::\allowbreak{}").replace(r"\_", r"\_\allowbreak{}").replace(",", r",\allowbreak{}")
    e = e.replace("/", r"/\allowbreak{}").replace(".", r".\allowbreak{}").replace("(", r"(\allowbreak{}")
    e = e.replace("=", r"=\allowbreak{}")
    # "--" in a typewriter font would print as an en dash (e.g. --enable-checking).
    e = e.replace("\x01", "...").replace("--", "-{}-")
    return r"\texttt{" + e + "}"


class Inline:
    """Inline Markdown -> LaTeX with placeholders for code, citations and cross-references."""

    def __init__(self):
        self.store: list[str] = []

    def _hold(self, latex: str) -> str:
        self.store.append(latex)
        return f"\x00{len(self.store) - 1}\x00"

    def convert(self, text: str) -> str:
        text = re.sub(r"\{c:([\w,]+)\}", lambda m: self._hold(r"~\cite{" + m.group(1) + "}"), text)
        # Bare URLs (the Artifact section): \url breaks them at slashes.
        text = re.sub(r"https?://[^\s)<>⟦]+[^\s)<>.,;:⟦]",
                      lambda m: self._hold(r"\url{" + m.group(0).replace("%", r"\%").replace("#", r"\#") + "}"), text)
        text = re.sub(r"`([^`]+)`", lambda m: self._hold(code(m.group(1))), text)
        text = re.sub(r"\b(Table|Figure|Listing) (\d+)\b",
                      lambda m: self._hold(f"{m.group(1)}~\\ref{{{m.group(1)[:3].lower()}:{m.group(2)}}}"), text)
        text = re.sub(r"\"([^\"\n]+)\"", lambda m: self._hold("``" + escape(m.group(1)) + "''"), text)
        text = escape(text)
        text = re.sub(r"\*\*(.+?)\*\*", r"\\textbf{\1}", text)
        text = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"\\emph{\1}", text)
        while "\x00" in text:
            text = re.sub(r"\x00(\d+)\x00", lambda m: self.store[int(m.group(1))], text)
        return text


def strip_tags(t: str) -> str:
    return re.sub(r"<!--.*?-->", "", t)


def apply_cites(blocks: list[str]) -> list[str]:
    blocks = list(blocks)
    for src, dst in CITES:
        n = sum(b.count(src) for b in blocks)
        if n != 1:
            raise SystemExit(f"citation phrase found {n} times (must be 1): {src!r}")
        blocks = [b.replace(src, dst) for b in blocks]
    return blocks


def table(lines: list[str], caption: str | None, label: str | None, note: str | None) -> str:
    rows = [[c.strip() for c in l.strip().strip("|").split("|")] for l in lines]
    head, align, body = rows[0], rows[1], rows[2:]
    ncol = len(head)
    widths = [max(len(strip_tags(r[i])) for r in [head] + body) for i in range(ncol)]
    wide = sum(widths) > 70
    spec = []
    for i, a in enumerate(align):
        if a.endswith(":"):
            spec.append("r")
        elif widths[i] > (28 if wide else 22):
            spec.append(r">{\raggedright\arraybackslash}X")
        else:
            spec.append("l")
    if not any("X" in s for s in spec):     # tabularx needs a column it can shrink
        spec[0] = r">{\raggedright\arraybackslash}X"
    inl = Inline()
    def cells(r):
        return " & ".join(inl.convert(c) for c in r) + r" \\"
    env = "table*" if wide else "table"
    out = [rf"\begin{{{env}}}[t]", r"\small"]
    if caption:
        out.append(rf"\caption{{{caption}}}")
    if label:
        out.append(rf"\label{{{label}}}")
    out += [rf"\begin{{tabularx}}{{\{'textwidth' if wide else 'columnwidth'}}}{{{''.join(spec)}}}", r"\toprule",
            cells(head), r"\midrule", *[cells(r) for r in body], r"\bottomrule", r"\end{tabularx}"]
    if note:
        out.append(r"\par\smallskip\footnotesize " + note)
    out.append(rf"\end{{{env}}}")
    return "\n".join(out)


def convert(md: str, out_dir: pathlib.Path) -> str:
    md = strip_tags(md)
    md = md[: md.index("## TODO before submission")] if "## TODO before submission" in md else md
    lines = md.splitlines()
    title = lines[0].lstrip("# ").strip()
    # Blocks: fenced code stays whole; other blocks are blank-line separated.
    blocks, cur, fence = [], [], False
    for ln in lines[1:]:
        if ln.startswith("```"):
            if fence:
                cur.append(ln)
                blocks.append("\n".join(cur))
                cur, fence = [], False
            else:
                if cur:
                    blocks.append("\n".join(cur))
                cur, fence = [ln], True
            continue
        if fence:
            cur.append(ln)
        elif ln.strip() == "":
            if cur:
                blocks.append("\n".join(cur))
            cur = []
        else:
            cur.append(ln)
    if cur:
        blocks.append("\n".join(cur))
    # Join prose paragraphs into one line, and each list item into one line (tables and code
    # keep their lines).
    def is_list(b):
        return re.match(r"^(\s*- |\s*\d+\. )", b)

    def join_items(b):
        items = []
        for ln in b.splitlines():
            if re.match(r"^\s*(- |\d+\. )", ln) or not items:
                items.append(ln.rstrip())
            else:
                items[-1] += " " + ln.strip()
        return "\n".join(items)

    blocks = [b if b.startswith(("```", "|", "#")) else join_items(b) if is_list(b)
              else " ".join(x.strip() for x in b.splitlines()) for b in blocks]
    blocks = apply_cites(blocks)

    body, abstract, acks = [], [], []
    mode = "pre"
    i = 0
    tabno = 0
    while i < len(blocks):
        b = blocks[i]
        inl = Inline()
        if b.startswith("## Abstract"):
            mode = "abstract"
        elif b.startswith("## Acknowledgments"):
            mode = "acks"
        elif m := re.match(r"^## (\d+)\. (.+)$", b):
            mode = "body"
            body.append(rf"\section{{{inl.convert(m.group(2))}}}" + rf"\label{{sec:{m.group(1)}}}")
        elif m := re.match(r"^### (\d+)\.(\d+) (.+)$", b):
            body.append(rf"\subsection{{{inl.convert(m.group(3))}}}" + rf"\label{{sec:{m.group(1)}.{m.group(2)}}}")
        elif b.startswith("## "):
            mode = "body"
            body.append(rf"\section*{{{inl.convert(b[3:].strip())}}}")
        elif mode == "pre":
            pass  # the working-draft banner
        elif mode == "abstract":
            abstract.append(inl.convert(b))
        elif mode == "acks":
            acks.append(inl.convert(b))
        elif b.startswith("|"):
            head = b.split("|")[1].strip()
            cap, lab = UNCAPTIONED.get(head, (None, None))
            body.append(table(b.splitlines(), Inline().convert(cap) if cap else None, lab, None))
        elif m := re.match(r"^\*\*Table (\d+)\.\*\* (.+)$", b):
            # caption, then the table, then an optional note starting with a superscript letter
            cap = inl.convert(m.group(2))
            tb = blocks[i + 1]
            note = None
            if i + 2 < len(blocks) and blocks[i + 2].startswith("ᵃ"):
                note = Inline().convert(blocks[i + 2])
                i += 1
            body.append(table(tb.splitlines(), cap, f"tab:{m.group(1)}", note))
            i += 1
        elif m := re.match(r"^\*\*Figure (\d+)\*\* \(`Figures/(\w+)\.pdf`\)\. (.+)$", b):
            body.append("\n".join([r"\begin{figure*}[t]", r"\centering",
                                   rf"\includegraphics[width=\textwidth]{{Figures/{m.group(2)}.pdf}}",
                                   rf"\Description{{{Inline().convert(m.group(3).split('. ')[0])}}}",
                                   rf"\caption{{{inl.convert(m.group(3))}}}", rf"\label{{fig:{m.group(1)}}}",
                                   r"\end{figure*}"]))
        elif m := re.match(r"^\*\*Listing (\d+)\.\*\* (.+)$", b):
            src = blocks[i + 1].splitlines()
            lang = src[0].strip("`").strip() or "C++"
            code_text = "\n".join(src[1:-1])
            # The listings C++ dialect predates constexpr; a per-listing language= resets
            # \lstset's keywords, so they are given here.
            body.append("\n".join([rf"\begin{{lstlisting}}[language=C++, morekeywords={{constexpr,consteval,requires}}, "
                                   rf"float=*t, label=lis:{m.group(1)}, "
                                   rf"caption={{{inl.convert(m.group(2))}}}]", code_text, r"\end{lstlisting}"]))
            i += 1
        elif re.match(r"^\s*(- |\d+\. )", b):
            body.append(lists(b))
        else:
            body.append(inl.convert(b))
        i += 1

    fig_dir = out_dir / "Figures"
    fig_dir.mkdir(parents=True, exist_ok=True)
    for pdf in (PROJECT / "Figures").glob("*.pdf"):
        shutil.copy2(pdf, fig_dir / pdf.name)

    return PREAMBLE.replace("@TITLE@", Inline().convert(title)) + "\n\\begin{abstract}\n" + \
        "\n\n".join(abstract) + "\n\\end{abstract}\n\n\\maketitle\n" + \
        "\n" + "\n\n".join(body) + \
        ("\n\n\\begin{acks}\n" + "\n\n".join(acks) + "\n\\end{acks}\n" if acks else "") + POSTAMBLE


def lists(block: str) -> str:
    out, stack = [], []
    for ln in block.splitlines():   # one item per line (convert() joined continuations)
        m = re.match(r"^(\s*)(- |\d+\. )(.*)$", ln)
        depth = len(m.group(1)) // 2
        kind = "enumerate" if m.group(2)[0].isdigit() else "itemize"
        while len(stack) > depth + 1 or (len(stack) == depth + 1 and stack[-1] != kind):
            out.append(rf"\end{{{stack.pop()}}}")
        while len(stack) < depth + 1:
            stack.append(kind)
            out.append(rf"\begin{{{kind}}}")
        out.append(r"\item " + Inline().convert(m.group(3)))
    while stack:
        out.append(rf"\end{{{stack.pop()}}}")
    return "\n".join(out)


PREAMBLE = r"""% Generated by Harness/tolatex.py from Paper.md -- do not edit; edit Paper.md instead.
\documentclass[sigplan,screen,nonacm]{acmart}
\usepackage{tabularx}
\usepackage{booktabs}
\usepackage{listings}
\lstset{basicstyle=\ttfamily\footnotesize, columns=fullflexible, keepspaces=true,
  morekeywords={template,for,constexpr,consteval,auto,inline,void,const,typename,
  std,meta}, xleftmargin=0pt, frame=none}
\setlength{\emergencystretch}{3em}
\raggedbottom
\settopmatter{printacmref=false}
\renewcommand\footnotetextcopyrightpermission[1]{}

\title[What Field Enumeration Costs to Compile in C++26]{@TITLE@}
\author{Denys Kachalenko}
\orcid{0009-0003-8597-329X}
\affiliation{\institution{Independent researcher}\country{Ukraine}}
\email{denys.kachalenko@gmail.com}
"""

POSTAMBLE = r"""

\bibliographystyle{ACM-Reference-Format}
\bibliography{References}

\end{document}
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--paper", default=str(PROJECT / "Paper.md"))
    ap.add_argument("--out", default=str(PROJECT / "Latex"))
    args = ap.parse_args()
    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    tex = convert(pathlib.Path(args.paper).read_text(encoding="utf-8"), out)
    (out / "Paper.tex").write_text(tex.replace("\\begin{abstract}", "\\begin{document}\n\n\\begin{abstract}", 1),
                                   encoding="utf-8", newline="\n")
    keys = sorted({k for m in re.finditer(r"\\cite\{([^}]+)\}", tex) for k in m.group(1).split(",")})
    print(f"wrote {out / 'Paper.tex'}; {len(keys)} citation keys: {', '.join(keys)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
