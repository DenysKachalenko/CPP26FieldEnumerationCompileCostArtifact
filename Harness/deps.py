# SPDX-License-Identifier: MIT
"""Pinned third-party libraries.

`Deps.json` is the single pin file: CMakeLists.txt reads it for FetchContent, and
this module reads it for the measurement harness. Each library is the GitHub
tarball of its pinned commit, verified by sha256 and unpacked into
`ThirdParty/<name>-<commit[:12]>/`, so no git operation is involved.

    python deps.py fetch     # download, verify and unpack every pin (idempotent)
    python deps.py verify    # check every pin is unpacked and its tree is unmodified
"""
from __future__ import annotations
import hashlib
import json
import pathlib
import shutil
import sys
import tarfile
import tempfile
import urllib.request

HERE = pathlib.Path(__file__).resolve().parent
PROJECT = HERE.parent
PIN_FILE = PROJECT / "Deps.json"
THIRD_PARTY = PROJECT / "ThirdParty"
MARKER = ".pin.json"


def load() -> dict:
    return json.loads(PIN_FILE.read_text())["deps"]


def source_dir(name: str, pin: dict) -> pathlib.Path:
    return THIRD_PARTY / f"{name}-{pin['commit'][:12]}"


def include_dirs() -> list[pathlib.Path]:
    return [source_dir(name, pin) / pin["include"] for name, pin in load().items()]


def tree_sha256(root: pathlib.Path) -> str:
    """One digest over every file of an unpacked library (paths and contents)."""
    h = hashlib.sha256()
    for f in sorted(p for p in root.rglob("*") if p.is_file() and p.name != MARKER):
        h.update(str(f.relative_to(root)).replace("\\", "/").encode())
        h.update(hashlib.sha256(f.read_bytes()).digest())
    return h.hexdigest()


def _marker_ok(name: str, pin: dict, deep: bool = False) -> bool:
    """The marker matches the pin; with deep=True the tree also still matches the digest
    recorded at unpack time (no local edits)."""
    marker = source_dir(name, pin) / MARKER
    if not marker.is_file():
        return False
    got = json.loads(marker.read_text())
    if got.get("commit") != pin["commit"] or got.get("sha256") != pin["sha256"]:
        return False
    return not deep or got.get("tree_sha256") == tree_sha256(source_dir(name, pin))


def _fetch_one(name: str, pin: dict) -> None:
    dest = source_dir(name, pin)
    if _marker_ok(name, pin, deep=True):
        print(f"  {name}: ok ({dest.name})")
        return
    print(f"  {name}: downloading {pin['url']}")
    data = urllib.request.urlopen(pin["url"], timeout=300).read()
    digest = hashlib.sha256(data).hexdigest()
    if digest != pin["sha256"]:
        raise SystemExit(f"{name}: sha256 mismatch: got {digest}, pinned {pin['sha256']}")
    with tempfile.TemporaryDirectory(dir=THIRD_PARTY) as tmp:
        archive = pathlib.Path(tmp) / "src.tar.gz"
        archive.write_bytes(data)
        with tarfile.open(archive) as tar:
            tops = {m.name.split("/")[0] for m in tar.getmembers()}
            if len(tops) != 1:
                raise SystemExit(f"{name}: unexpected archive layout {sorted(tops)}")
            tar.extractall(tmp, filter="data")
        if dest.exists():
            shutil.rmtree(dest)
        shutil.move(str(pathlib.Path(tmp) / tops.pop()), dest)
    (dest / MARKER).write_text(json.dumps(
        {"commit": pin["commit"], "ref": pin["ref"], "sha256": pin["sha256"],
         "tree_sha256": tree_sha256(dest)}, indent=2))
    print(f"  {name}: unpacked into {dest.name}")


def fetch() -> None:
    THIRD_PARTY.mkdir(exist_ok=True)
    for name, pin in load().items():
        _fetch_one(name, pin)


def verify() -> bool:
    ok = True
    for name, pin in load().items():
        good = _marker_ok(name, pin, deep=True) and (source_dir(name, pin) / pin["include"]).is_dir()
        print(f"  {name}: {'ok' if good else 'MISSING or stale'} ({source_dir(name, pin).name})")
        ok &= good
    return ok


def pins_summary() -> dict:
    out = {}
    for name, pin in load().items():
        marker = source_dir(name, pin) / MARKER
        tree = json.loads(marker.read_text()).get("tree_sha256") if marker.is_file() else None
        out[name] = {"ref": pin["ref"], "commit": pin["commit"], "tree_sha256": tree}
    return out


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "verify"
    if cmd == "fetch":
        fetch()
    elif cmd == "verify":
        sys.exit(0 if verify() else 1)
    else:
        raise SystemExit(f"unknown command {cmd!r}; use fetch or verify")
