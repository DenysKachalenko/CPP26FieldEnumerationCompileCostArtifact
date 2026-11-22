# SPDX-License-Identifier: MIT
"""Check (or rewrite) every tagged number in the draft against Data/PaperNumbers.json
(written by papernumbers.py).

In the draft a computed number is written as `1.93<!--n:FrontendN.reflect_plain.slope-->`
and its interval as `[1.92, 1.94]<!--ci:FrontendN.reflect_plain.slope-->`; the comments
are invisible when the Markdown is rendered.

    python paperlint.py [--fix] [--strict] [--paper Paper.md] [--numbers Data/PaperNumbers.json]

Exit status 1 if any tag is malformed, unknown or uncomputed, or (without --fix) any
tagged number disagrees with the data; --fix rewrites the disagreeing numbers and still
fails on what it cannot rewrite. Warnings: cited numbers that papernumbers.py flagged
(e.g. a slope of a curve that is not linear), and untagged measurement-like literals (a
number followed by ×, x, ms, s, %, KB, MB or -fold); --strict makes them fail too. Tags
inside `code spans` are examples, not citations.
"""
from __future__ import annotations
import argparse
import json
import pathlib
import re
import sys

PROJECT = pathlib.Path(__file__).resolve().parent.parent
NUM = r"[-+−]?\d[\d,]*(?:\.\d+)?%?"
TAG = re.compile(rf"(?P<text>\[[^\[\]]*?\]|{NUM})<!--(?P<kind>n|ci):(?P<key>[^>]+?)-->")
ANY_TAG = re.compile(r"<!--(?:n|ci):[^>]+?-->")
UNTAGGED = re.compile(r"(?<![\w.\[\-])(\d+(?:\.\d+)?)\s?(×|x\b|ms\b|s\b|%|KB\b|MB\b|-fold)")
CODE = re.compile(r"`[^`\n]*`")


def check(paper: str, numbers: dict, fix: bool) -> tuple[str, list[str], int, list[str]]:
    problems, flagged, rewrites = [], {}, 0

    def repl(m):
        nonlocal rewrites
        key, kind, text = m["key"], m["kind"], m["text"]
        entry = numbers.get(key)
        if entry is None or "error" in entry:
            problems.append(f"unknown or uncomputed key: {key}"
                            + (f" ({entry['error']})" if entry and "error" in entry else ""))
            return m.group(0)
        if "warning" in entry:
            flagged[key] = f"cited {key}: {entry['warning']}"
        want = entry["text"] if kind == "n" else entry.get("ci_text")
        if want is None:
            problems.append(f"no interval for key: {key}")
            return m.group(0)
        if text != want:
            if fix:
                rewrites += 1
                return f"{want}<!--{kind}:{key}-->"
            problems.append(f"{key} ({kind}): draft says {text}, data says {want}")
        return m.group(0)

    text = TAG.sub(repl, paper)
    for no, line in enumerate(paper.splitlines(), 1):
        for t in ANY_TAG.finditer(TAG.sub("", CODE.sub("", line))):
            problems.append(f"line {no}: malformed tag {t.group(0)} (must follow a bare number or [lo, hi])")
    return text, problems, rewrites, list(flagged.values())


def untagged(paper: str) -> list[str]:
    out = []
    for no, line in enumerate(paper.splitlines(), 1):
        for m in UNTAGGED.finditer(TAG.sub("", CODE.sub("", line))):
            out.append(f"line {no}: untagged '{m.group(0)}'")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--paper", default=str(PROJECT / "Paper.md"))
    ap.add_argument("--numbers", default=str(PROJECT / "Data" / "PaperNumbers.json"))
    ap.add_argument("--fix", action="store_true")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args()
    paper_path = pathlib.Path(args.paper)
    source = paper_path.read_text(encoding="utf-8")
    numbers = json.loads(pathlib.Path(args.numbers).read_text())["numbers"]
    text, problems, rewrites, flagged = check(source, numbers, args.fix)
    warnings = flagged + untagged(source)
    for p in problems:
        print(" ", p)
    for w in warnings:
        print("  warning:", w)
    if args.fix and rewrites:
        paper_path.write_text(text, encoding="utf-8")
        print(f"rewrote {rewrites} number(s) in {paper_path.name}")
    review = source.count("⟦")
    print(f"{len(TAG.findall(source))} tagged numbers, {len(problems)} problem(s), "
          f"{len(flagged)} flagged cited number(s), {len(warnings) - len(flagged)} untagged "
          f"measurement-like literal(s), {review} ⟦review⟧ marker(s)")
    return 1 if problems or (args.strict and warnings) else 0


if __name__ == "__main__":
    sys.exit(main())
