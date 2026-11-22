# Run book

The procedure that produced sessions S1, S2 and S3 (2026-11-17 to 2026-11-21) on one
Windows 11 desktop. A session can be stopped at any time (Ctrl+C) and resumed with the same
command; at most the current round is lost.

**Placeholders.** `<project>` is this folder (in Git Bash, e.g. `/c/work/CPP26FieldEnumerationCompileCostArtifact`).
`$PY` is a Windows Python 3.13 with `psutil`, `numpy` and `matplotlib`
(`pip install -r requirements.txt` plus `psutil`); MSYS2's own `python` lacks those
packages. The compilers, as Windows paths:

```sh
G162=C:/msys64/home/<user>/gcc-16.2.0-install/bin/g++.exe   # GCC 16.2.0, the protocol compiler
G161=C:/msys64/home/<user>/gcc-16-install/bin/g++.exe       # GCC 16.1.0, the cross-check compiler
G152=C:/msys64/ucrt64/bin/g++.exe                           # MSYS2's GCC 15.2.0 (Boost.PFR probe only)
```

**Machine-specific settings in the code.** The paths at the top of `Harness/overnight.sh`
(`PY`, which the environment variable `PY` overrides, `G162`, `G161`, `G152`, `PROVENANCE`,
`BUILD_STATUS`) and the defaults at the top of `Harness/build_gcc.sh` (`ROOT`, `PREFIX`,
`REFERENCE`, which environment variables of those names override) are those of the
measuring machine; set them to yours. So are the compiler paths in `CMakePresets.json`.
The harness expects MSYS2 under `C:/msys64` (`RB_UCRT_BIN` overrides
`C:/msys64/ucrt64/bin`). Each session records `sys.executable` and every path it used in
`env.json`.

**Shells.** Step 1 runs in an MSYS2 **UCRT64** shell (it builds GCC). Every other step
runs in **Git Bash** (or PowerShell) with `$PY`.

## 0. Before each session: an unused machine

- Applications may stay open; only do not use the PC while a session runs. Nothing gates
  on load and no round is repeated: the harness records the machine's load with every
  compile (`load_pct`, `pcore_busy`) and the busiest processes in `env.json`, and the
  medians absorb a disturbed compile (§3.5 of the paper reports the sensitivity check).
- Nothing else compiles while a session runs.
- Close any tool that periodically empties the working sets of processes (a "memory
  cleaner"): it disturbs both the timing and the peak working set.
- Pause Windows Update for the days of the sessions; no `pacman` update between sessions.
- Power plan **High performance**: `overnight.sh` selects it and restores the previous
  one; a citable session refuses any other plan (exit 6).

## Unattended: one command per session

Steps 1–4b below can all run unattended, started once in Git Bash:

```sh
bash <project>/Harness/overnight.sh S1         # S2 on another day
bash <project>/Harness/overnight.sh S2 sleep   # the same, then put the PC to sleep
bash <project>/Harness/overnight.sh S3 sleep   # supplementary session: job FrontendIdiom only
```

With `sleep`, the PC goes to sleep (ACPI sleep, not hibernation) when the run ends,
completed or stopped; not after Ctrl+C. A session that completed is never run again
(`overnight.sh` refuses it before writing anything).

`overnight.sh`:

1. builds GCC 16.2.0 unless it is installed (a build already running is waited for);
   build it yourself first (step 1) on a new machine, since its fallback build call uses
   the measuring machine's path;
2. runs CMake + CTest with GCC 16.2.0 and `deps.py verify`;
3. selects the High performance power plan (and restores the previous one at exit) and
   keeps the machine awake;
4. runs the Boost.PFR probe once (skipped while `Data/PfrProbe.json` holds a non-pilot
   result), then a few-minute smoke test of the session runner in a scratch directory;
5. runs the session, resuming it after a crash.

Nothing waits for a quiet machine and no round is repeated; the load is recorded with
every compile. A passed preflight is reused for the same checked code and compilers
(`Data/Preflight/`), so a run is measurement only. A failed check, a failed preflight, a
refused resume, a failed job or Ctrl+C stops the run. Log: `Data/Overnight/<session>.log`;
current state: `Data/Overnight/<session>.status` (these logs are not part of the archive).
Ctrl+C in its window stops it; the same command resumes. **Resume a session only this
way**, never with `campaign.py run` directly: `overnight.sh` selects the power plan the
session requires.

**Between S1 and S2:** no `pacman` update of MSYS2 (both compilers load gmp/mpfr/isl
DLLs from `/ucrt64/bin`), no change to the working tree, no edit of the measurement code
(`machine.MEASUREMENT_MODULES`, `Include/RB/*`, `Deps.json`): a resume or a second session
with different code is refused or no longer comparable.

## 1. Build GCC 16.2.0 (once; about 1.5 hours, the machine can be in use)

In an MSYS2 UCRT64 shell, **without running `pacman -Syu` first** (the build must use the
same host compiler as GCC 16.1.0, MSYS2's GCC 15.2.0 Rev11, which the script checks):

```sh
bash <project>/Harness/build_gcc.sh
```

It needs the GCC 16.1.0 install it must match (`REFERENCE`). That compiler was built
earlier on the same machine, non-bootstrapped, by the same host compiler, with the same
configure options (its `Configured with:` line is in every `env.json`); the checksum of its
source tarball was not recorded. The script:

1. downloads the official tarball and checks it against the pinned SHA-512, the published
   `sha512.sum` and the release signature (`gpg`);
2. applies the two `/mingw/include` header-path patches (match counts checked) and puts the
   MinGW CRT into the prefix before `make`;
3. configures with exactly the options of GCC 16.1.0, builds with `make -j4 MAKEINFO=true`
   and installs through a staging directory to `$PREFIX`;
4. gives the prefix the same layout as 16.1.0's: a copy of `/ucrt64/include`, and the 13
   launch executables stripped with a `.gnu_debuglink`;
5. checks the version, the UTF-8 manifest, `<meta>`, a reflection test, and that every
   MinGW header resolves to the same prefix-relative file as under 16.1.0;
6. writes `$PREFIX/PROVENANCE.txt` (checksums, signature status, `g++ -v`, host compiler and
   packages, binary hashes). Progress: `$ROOT/16.2.0.status.log`.

Then, in Git Bash, in the project (after `python Harness/deps.py fetch`, which downloads
and verifies the pinned libraries into `ThirdParty/`):

```sh
cmake --preset gcc16.2-local && cmake --build --preset gcc16.2-local && ctest --preset gcc16.2-local
```

## 2. Check everything (about 30 minutes per compiler)

```sh
cd <project>/Harness
$PY deps.py verify
$PY preflight.py --gxx $G162
$PY campaign.py estimate --gxx $G162 --compiler GCC161=$G161   # optional: duration
```

`campaign.py estimate` times one round of each job and writes `Data/Estimate.json`.

## 3. Session S1 (unused machine; about 5.7 hours of compiles)

```sh
$PY campaign.py run --session S1 --gxx $G162 --compiler GCC161=$G161
```

(Through `overnight.sh S1` in practice, see above.) A session runs the 17 jobs of
`plan.JOBS`, 12 rounds each (1 warm-up + 11 measured), one compile at a time: 8,484
compiles. S1 and S2 each took about 5.7 hours of compiling. The session can be split
across several sittings with Ctrl+C and the same command.

What happens on the first run:

- the session binds GCC 16.2.0 as its protocol compiler and GCC 16.1.0 as `GCC161` for
  the paired cross-check jobs;
- it records the compiler hashes and a fingerprint of the measurement code in
  `session.json`, and a copy of that code in `code.zip`.

What happens on a resume:

- re-running the same command resumes the session;
- a resume with a different compiler, edited code or other protocol settings is refused.

## 4. Session S2 (a different day, unused machine)

```sh
$PY campaign.py run --session S2 --gxx $G162 --compiler GCC161=$G161
```

Two sessions on different days give the between-session spread that the paper reports
next to every within-session interval.

## 4a. Supplementary session S3 (GCC 16.2.0 only)

One job, `FrontendIdiom` (`plan.SUPPLEMENTARY`): four native formulations of the same member
query, `reflect_plain` (expansion statement over the `std::span` of
`define_static_array`, which GCC 16.2.0 lowers by iterating), `reflect_array` (the same
expansion statement over a constant array, lowered by destructuring), `reflect_index` (a
P1061 index pack through the tuple protocol of `integer_sequence`, reflect-cpp's C++26
form) and `reflect_seq` (an index-sequence helper), with `p1061`, `pfr` and
`manual_unique`, over the FrontendN sweep (M = 16). Order:

1. **Preflight** (correctness, not time; the machine may be in use; about 80 minutes):
   `$PY campaign.py preflight --gxx $G162` must end with `default: preflight passed`. From
   then until S3 is complete, do not edit
   `Harness/{arms,compiler,deps,generate,machine,overload,plan,preflight}.py`,
   `Include/RB/*` or `Deps.json`: any edit forces a new preflight.
2. **Rehearsal** (a few minutes; it switches the power plan for a moment):
   `bash <project>/Harness/overnight.sh S3 rehearse` must end with `REHEARSAL DONE` in
   `Data/Overnight/S3-rehearse.status` (CMake/CTest rebuilds ArmsDemo with the new arms).
3. **Smoke test of the job** (about 2 minutes; scratch directory, never `Data/Sessions`):
   `SMOKE=$(mktemp -d); RB_SESSIONS=$(cygpath -w "$SMOKE") $PY campaign.py run --session Smoke --gxx $G162 --jobs FrontendIdiom --rounds 1 --warmup 0 --skip-preflight`.
   Its log must say `session complete`; its round time × 12 is S3's measurement time.
   The GGC totals of `reflect_plain`, `p1061`, `pfr` and `manual_unique` must equal S1's
   (identical compiles).
4. **S3** (about 16 minutes of compiles with the preflight reused; the PC unused,
   applications may stay open): `bash <project>/Harness/overnight.sh S3 sleep`. Do not use
   `campaign.py estimate` for the duration: it overwrites `Data/Estimate.json`.

S3 is not bound to GCC 16.1.0. Its ratios are formed within its own job and are
single-session numbers; `papernumbers.py` never pools S3 with S1/S2 (it refuses a session
that holds both kinds of job) and warns on every S3 key if the session stopped early.
Analysis takes it as a third session (its keys start with `FrontendIdiom.` and `S3.`); run
`stats.py` on S1 S2 and on S3 separately (its pooled tables cover only jobs common to all
sessions given).

## 4b. Boost.PFR probe (unused machine, about 40 minutes; any day)

Locates the quadratic term of Boost.PFR's C++17 path (paper §4.3) on GCC 16.2.0 and on
MSYS2's GCC 15.2.0 (`/ucrt64/bin/g++`; it must be 15.2.0):

```sh
$PY pfrprobe.py --gxx GCC162=$G162 --gxx GCC152=$G152
```

It writes `Data/PfrProbe.json`. The tags must be exactly `GCC162` and `GCC152`, because
the paper's keys name them.

## 5. Analysis

```sh
$PY stats.py ../Data/Sessions/S1 ../Data/Sessions/S2
$PY stats.py ../Data/Sessions/S3
$PY papernumbers.py ../Data/Sessions/S1 ../Data/Sessions/S2 ../Data/Sessions/S3   # every number the paper cites (reads Data/PfrProbe.json too)
$PY paperlint.py --fix                                       # rewrite the paper's tagged numbers from new data
$PY figures.py ../Data/Sessions/S1 ../Data/Sessions/S3       # S3 adds FigureIdiom
$PY tolatex.py                                               # Latex/Paper.tex from Paper.md
```

With new data, `paperlint.py --fix` updates the tagged numbers; the prose around them, in
particular every statement that compares numbers, must then be re-checked by hand.
