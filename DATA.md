# Data dictionary

Everything under `Data/` was written by the harness in `Harness/`; nothing was edited by
hand except where this page says so. Times are UTC unless marked local. Sizes in MB are
MiB (2^20 bytes).

| Path | What it is | Written by |
|------|------------|------------|
| `Data/Sessions/S1/`, `S2/`, `S3/` | One measurement session each (below) | `campaign.py run` |
| `Data/Preflight/*.json` | The passed correctness and manipulation checks, by checked code and compiler | `campaign.py` (`preflight.py`) |
| `Data/PfrProbe.json` | The Boost.PFR probe of §4.3 of the paper | `pfrprobe.py` |
| `Data/PaperNumbers.json` | Every number the paper cites | `papernumbers.py` |

## Sessions

| Session | Ran (UTC) | Jobs | Compilers | Compiles |
|---------|-----------|------|-----------|----------|
| S1 | 2026-11-18 21:02 to 2026-11-19 02:43 | the full plan: the 17 jobs of `plan.JOBS` | GCC 16.2.0 (`default`), GCC 16.1.0 (`GCC161`) | 8,484 |
| S2 | 2026-11-19 22:20 to 2026-11-20 04:02 | the same 17 jobs | the same two | 8,484 |
| S3 | 2026-11-21 08:19 to 08:35 | `FrontendIdiom` only (`plan.SUPPLEMENTARY`) | GCC 16.2.0 (`default`) | 444 |

Every job ran one warm-up round and eleven measured rounds; none of the compiles failed
(each log ends with `session complete`). S1 and S2 measured the same code (fingerprint
`503f8c0a…`); S3 measured the same code plus the three arms `reflect_array`,
`reflect_index` and `reflect_seq` (fingerprint `6f227640…`). The paper takes single-session
numbers from S1 (S3 for `FrontendIdiom`), compares S2 with S1 slope by slope, and never
pools S3 with S1 and S2.

An earlier attempt at S1 (called S1a, the night of 2026-11-17/18) ran under an earlier
protocol that gated rounds on the machine's load and repeated them; it was stopped and S1
was measured again from scratch. S1a is not used by the paper and is not published; S1
and S2 reused the two preflight records that passed during it (see below).

## Files of a session folder

| File | Contents |
|------|----------|
| `session.json` | What the session is bound to; a resume that differs is refused |
| `env.json` | The machine and toolchain record, one entry per start or resume |
| `cmds.json` | The exact `cc1plus` command line of every cell and sentinel |
| `code.zip` | A copy of the measured code (the files of the fingerprint) |
| `preflight_<tag>.json` | The preflight report the session used, per compiler tag |
| `raw.csv` | One row per compile |
| `reports.jsonl.gz` | The full `-ftime-report` text of every compile |
| `rounds.json` | Progress: one record per finished round |
| `log.txt` | The runner's console log |

### `session.json`

| Field | Meaning |
|-------|---------|
| `compilers.<tag>` | `path` (the `g++` driver), `version` (first line of `g++ --version`), `driver_sha256`, `cc1plus_sha256`. Tag `default` is the protocol compiler; `GCC161` the cross-check compiler of the `arm@GCC161` arms |
| `fingerprint` | sha256 over the sha256 of every measured file (`Harness/{arms,campaign,compiler,deps,generate,machine,overload,plan,preflight}.py`, `Include/RB/*`, `Deps.json`; `machine.FINGERPRINT_GLOBS`), as lines `path=sha256` |
| `protocol` | `warmup` (1), `rounds` (11), `passes_per_round` (1), `load` (recorded per compile, no gate), `other_core_busy_pct` (50.0, the threshold of `pcore_busy`), `power_plan` (the GUID of Windows' High performance plan, required) |
| `created_utc` | When the session was created |
| `pilot` | `false` for all three: preflight run and standard rounds. The analysis refuses pilot sessions |
| `preflight.<tag>` | `ok`, `utc` (when the session accepted it), `fingerprint` (the session's), `cc1plus_sha256` |

### `env.json`

A list with one snapshot per start or resume of `campaign.py run` (one entry in each of
S1, S2 and S3: none was resumed). Fields (`machine.snapshot`):

| Field | Meaning |
|-------|---------|
| `utc` | When the snapshot was taken |
| `os` | `platform`, `version` (Python's `platform`) |
| `cpu` | `name`, `logical`, `physical`; `cores` (one record per physical core: `efficiency_class`, `smt`, `cpus`); `performance_cpus` (the logical CPUs of the highest efficiency class) |
| `memory_gb`, `memory_available_gb`, `swap_used_gb` | Physical memory, available memory and swap in use (GiB) |
| `power_plan` | Output of `powercfg /getactivescheme` |
| `defender_realtime` | Microsoft Defender real-time protection on (`True`) or off |
| `load_percpu_pct`, `load_total_pct` | CPU load per logical CPU and in total over a 5 s sample before the start (%) |
| `busiest_processes` | The 8 processes using the most CPU in that sample: `name`, `cpu_pct` (% of the whole machine) |
| `compilers.<driver path>` | `driver`, `version`, `configure` (the `Configured with:` line of `g++ -v`), `driver_sha256`, `cc1plus` (path), `cc1plus_sha256`, `cc1plus_bytes` |
| `assembler` | First line of `as --version` (MSYS2 UCRT64) |
| `base_flags` | Flags of every timed compile: `-std=c++26 -freflection -B<UCRT64 bin>/` |
| `host_dll_packages` | Versions of the MSYS2 packages whose DLLs `cc1plus` loads (gmp, mpfr, mpc, isl, zstd, zlib, libiconv, libwinpthread, binutils) |
| `deps.<library>` | `ref`, `commit`, `tree_sha256` of each pinned library tree |
| `fingerprint` | `digest` (the session fingerprint) and `files` (sha256 per measured file) |
| `python` | `version`, `executable`, `numpy`, `psutil` |
| `project_git_head`, `project_dirty_files` | `git rev-parse HEAD` and `git status --porcelain` of the private development repository |
| `pinned_cpus` | The CPUs the runner and every compile were restricted to |

### `cmds.json`

An object from `"<job>|<arm>|<x>"` to the argument list of the `cc1plus` process timed for
that cell (the sentinel cell included), exactly as the `g++` driver produced it with `-###`,
except that for `-O2` compiles the assembly output goes to `NUL`. The generated sources it
names lived in a temporary directory and are not archived: `generate.py` and
`overload.py` regenerate them deterministically.

### `code.zip`

The files of the fingerprint, as they were when the session was created: 24 files for S1
and S2, 27 for S3. The measured code was never committed to git: every session records
the git HEAD of the private development repository (`1336526…`) together with its list of
modified and untracked files, so `code.zip` is the authoritative copy of the code that
measured each session. The measurement code at the top of this archive is the S3 state:
its fingerprint equals S3's (`6f227640…`). The analysis scripts (`stats.py`,
`papernumbers.py`, `paperlint.py`, `figures.py`, `tolatex.py`), `pfrprobe.py`,
`overnight.sh` and `build_gcc.sh` are not part of the fingerprint and are in their final
state; `overnight.sh` was last edited on 2026-11-20, after S2, to add S3.

### `preflight_<tag>.json` and `Data/Preflight/`

The report of `preflight.py` for one compiler, a byte-identical copy of the record in
`Data/Preflight/` that the session used. A record is named
`<checked-code fingerprint, 16 hex>-<cc1plus sha256, 16 hex>.json`; the checked-code
fingerprint is the session fingerprint without `Harness/campaign.py` (which schedules and
records compiles but generates and checks nothing), so a passed check is reused for the
same checked code and compiler.

| Field | Meaning |
|-------|---------|
| `compiler` | Version string |
| `deps_ok` | Every library tree matches its pin |
| `flags` | Per arm: `arm`, `ok`, `problems`. Every arm's flags reach the exact `cc1plus` command, and `-fno-reflection` removes `__cpp_impl_reflection` |
| `oracles` | Per corpus and flag set: `corpus`, `n`, `m`, `flags`, `ok`, `problems`, `output` (the oracle's last line, e.g. `OK: 11 arms == manual_unique on 5 of 5 scalar structs, 16 fields (...; reversed control detected)`) |
| `manipulation` | Per arm pair: `a`, `b`, `expect` (`differs` or `identical`), `isolates`, `functions` (defined functions per side), `only_a`, `only_b`, `ok`, `problems`; overload idioms by their source shape |
| `o2_profile` | Per `FullN` arm: `functions`, `text_bytes` at `-O2` (recorded, not pass/fail) |
| `ok` | Overall result |
| `fingerprint`, `cc1plus_sha256`, `utc` | What was checked, and when |
| `source` | Only in the two records of S1 and S2 (below) |

| Record | Compiler | Checked code | Passed | Used by |
|--------|----------|--------------|--------|---------|
| `3f3ceb8f2c935303-dd36b16379f8edfc.json` | GCC 16.2.0 | S1/S2 | 2026-11-17 23:40 | S1, S2 |
| `3f3ceb8f2c935303-ae327cf651771285.json` | GCC 16.1.0 | S1/S2 | 2026-11-18 00:57 | S1, S2 |
| `527201307efb795e-dd36b16379f8edfc.json` | GCC 16.2.0 | S3 | 2026-11-20 16:33 | S3 |

The two S1/S2 records were produced during S1a. Their `source` field says so: "checked
code identical except Harness/campaign.py, cc1plus identical". No code in this archive or
in any `code.zip` writes that field; it is the one hand-written note in `Data/`.

### `raw.csv`

One row per compile, in the order compiled; the analysis (`stats.load_rows`) keeps the rows
of finished rounds (`rounds.json`) and drops the warm-up round. 49 columns:

| Column | Unit | Meaning |
|--------|------|---------|
| `session` | | Session name |
| `compiler_tag` | | `default` (the protocol compiler, GCC 16.2.0) or `GCC161` |
| `compiler` | | First line of `g++ --version` of the compiler used |
| `job` | | Job name (`Harness/plan.py`) |
| `round` | | Round index from 0; round 0 is the warm-up |
| `attempt` | | Always 1: one pass per round, never repeated (kept so that the analysis reads sessions of the earlier protocol) |
| `accepted` | | Always 1 (as `attempt`) |
| `warmup` | 0/1 | 1 in the warm-up round, which the analysis drops |
| `seq` | | Position in the round's compile order, from 0. The order of the cells is shuffled with `random.Random("<session>\|<job>\|<round>")` |
| `kind` | | `sentinel_start` (first compile of the round), `cell`, `sentinel_end` (last). The sentinel is a fixed cell of the job (`plan.Job.sentinel`), compiled to track drift |
| `arm` | | Arm name (`Harness/arms.py`; `ovl_*` from `Harness/overload.py`); `arm@GCC161` is compiled by GCC 16.1.0 |
| `mode` | | `syntax` (`-fsyntax-only`, the front end) or `full` (`-O2 -c`, assembly discarded) |
| `corpus` | | `scalar`, `rich` or `hetero` (`Harness/generate.py`) |
| `dim` | | The swept dimension: `N` structs, `M` fields per struct, `K` overload candidates, `C` call sites |
| `x` | | The swept value |
| `n` | structs | Number of structs in the translation unit |
| `m` | fields | Fields per struct (`hetero`: the median of a log-normal distribution) |
| `k` | | Overload candidates (overload jobs). In the other jobs set by the same rule but unused: `k = c = n` |
| `c` | | Call sites (overload jobs; see `k`) |
| `ft_setup_s`, `ft_parsing_s`, `ft_deferred_s`, `ft_optgen_s` | s | Wall time of GCC's phase timers `phase setup`, `phase parsing`, `phase lang. deferred`, `phase opt and generate`; together they make up TOTAL (to within 0.02 s of rounding in every row of S1, S2 and S3) |
| `ft_tmpl_inst_s` | s | Timer `template instantiation`; its time is part of the phase times, not added to them |
| `ft_consteval_s` | s | Timer `constant expression evaluation`; part of the phase times, like `ft_tmpl_inst_s` |
| `ft_name_lookup_s`, `ft_overload_s` | s | Timers `\|name lookup` and `\|overload resolution`, which GCC prints with a leading `\|`: they run concurrently with the other timers, and their time is already inside a phase |
| `ft_total_s` | s | `-ftime-report` TOTAL: wall time measured inside `cc1plus`, the paper's metric |
| `ggc_<timer>_mb` (9 columns, same timers) | MiB | Garbage-collected (GGC) memory allocated under that timer, as `-ftime-report` prints it (k, M, G suffixes converted with factor 1024) |
| `wall_s` | s | External wall time of the `cc1plus` process, measured by the harness from launch to exit |
| `os_user_s`, `os_kernel_s` | s | User and kernel CPU time of the process (`GetProcessTimes`; Windows counts it in 15.6 ms ticks) |
| `os_cycles` | cycles | CPU cycles of the process (`QueryProcessCycleTime`) |
| `os_peak_ws_mb` | MiB | Peak working set (`PeakWorkingSetSize`) |
| `os_peak_commit_mb` | MiB | Peak private commit (`PeakPagefileUsage`) |
| `os_page_faults` | | Page faults (`PageFaultCount`) |
| `load_pct` | % | Whole-machine CPU load during this compile: the mean over all logical CPUs of `psutil.cpu_percent`, from just before to just after the compile. The single-threaded compiler alone accounts for up to 5% on this 20-CPU machine |
| `pcore_busy` | CPUs | Pinned performance CPUs, other than the busiest one (taken to be the compiler's), above 50% load during the compile |
| `utc` | | When the compile ended (ISO 8601, seconds) |

Precision and missing values:

- `-ftime-report` prints wall times in 10 ms steps. GCC omits a timer row below its print
  threshold (about 5 ms of wall time and under 1 MiB of GGC, see the comment in
  `Harness/compiler.py`); such a row is recorded as 0.0 in both its `ft_` and `ggc_`
  columns, not as missing.
- The `*_noreport` arms (job `ReportOverhead`) compile without `-ftime-report`: their
  `ft_*` and `ggc_*` columns are empty and they are compared on `wall_s`. No other value in
  S1, S2 or S3 is empty.

### `reports.jsonl.gz`

Gzip-compressed JSON Lines, one line per compile in the same order as `raw.csv`, with the
fields `job`, `round`, `attempt`, `seq`, `arm`, `x` (they identify the `raw.csv` row) and
`stderr`, the compiler's complete standard error: the `-ftime-report` table (empty for the
`*_noreport` arms).

### `rounds.json`

`{job: {round: record}}` with one record per finished round (a round counts only once it
is here): `seconds` (duration of the round), `load_median_pct` and `load_max_pct` (over
its compiles), `available_mb` and `swap_used_mb` (MiB, at its end), `end_utc`.

### `log.txt`

The runner's console log. Timestamps are local time (UTC+2), `HH:MM:SS`. Per round: the
number of compiles, the duration, the two sentinel TOTALs and the load median and maximum.

## `Data/PfrProbe.json`

The Boost.PFR probe (`Harness/pfrprobe.py`, run on 2026-11-17 22:02 UTC): it locates the
quadratic term of Boost.PFR's C++17 path. Compiles ran one at a time on the performance
cores at high priority, in 3 rounds of shuffled order (seed 20261030).

| Field | Meaning |
|-------|---------|
| `pilot` | `false`: the standard number of repeats |
| `repeats` | 3 |
| `performance_cpus` | The CPUs the probe was pinned to |
| `machine` | A machine snapshot, with the fields of an `env.json` entry |
| `compilers` | `GCC162` (GCC 16.2.0) and `GCC152` (MSYS2's GCC 15.2.0) |
| `result.A.<TAG>.<mode>.<N>` | Part A: the `pfr_classic` translation unit (`-DBOOST_PFR_USE_CPP26=0`) at N = 1,000, 2,000 and 4,000 structs of 16 fields; `<mode>` is `cxx20` (`-std=c++20`), `cxx26` (`-std=c++26`) or `cxx26_refl` (`-std=c++26 -freflection`), the last two on GCC 16.2.0 only |
| `result.B.<variant>.<N>` | Part B, on GCC 16.2.0 with `-std=c++20`: one piece of the library called for every struct, at N = 500, 1,000 and 2,000. Variants: `binding`, `fields_count`, `tie_given_count`, `for_each_field`, `probe` (one aggregate-initialization probe), and `copy`, `no_add_pointer`, `bare` (a copy of that probe with parts removed) |

Each result entry: `total_s` and `overload_s` (medians of TOTAL and of the
overload-resolution timer, s), `runs_total_s` and `runs_overload_s` (the three runs),
`runs` (every run in full: the `ft_*`, `ggc_*`, `wall_s` and `os_*` values of `raw.csv`,
`load_pct` as the whole-machine load since the previous sample, `utc`, and `stderr`), and
`cmd` (the `cc1plus` argument list).

## `Data/PaperNumbers.json`

`{"sessions": ["S1", "S2", "S3"], "numbers": {key: entry}}` (753 entries in this version),
written by
`python papernumbers.py ../Data/Sessions/S1 ../Data/Sessions/S2 ../Data/Sessions/S3`
(it also reads `Data/PfrProbe.json`). In `Paper.md` a number is written
`1.72<!--n:FrontendN.reflect_plain.slope-->` and its interval
`[1.70, 1.73]<!--ci:FrontendN.reflect_plain.slope-->`; `paperlint.py` checks both
against this file.

Entry fields: `est` (the estimate, full precision), `text` (as the paper prints it), `ci`
and `ci_text` (95% percentile interval of the round bootstrap, 4,000 resamples, when the
number has one), and, where present, `warning` (e.g. a linearity warning), `note`,
`undefined_share` (share of resamples in which a crossover is undefined) or `error`
(not computable; there is none in this version).

Keys (the registry is in `Harness/papernumbers.py`):

| Key form | Meaning |
|----------|---------|
| `<Job>.<arm>.slope` | Per-unit cost: OLS slope of the cell medians over the job's sweep (ms per struct, field, candidate or call site) |
| `<Job>.<a>/<b>.ratio` | Ratio of two arms' slopes in the same job |
| `<Job>.<a>/<b>.point<N>`, `.M<M>` | Ratio of two arms' marginal costs at one sweep value (cell median there minus the cell median at 0) |
| `<Job>.<a>/<b>.total<N>` | Ratio of two arms' cell medians at N: the whole translation unit, fixed costs included |
| `<Job>.<a>-<b>.diff_ms` | Difference of two slopes (ms) |
| `<Job>.<arm>.<statistic>` | Other single-arm statistics: `halves` (upper-half over lower-half slope), `per_struct<N>` (marginal cost at N), `slope<a>_<b>` (slope over a part of the sweep), timer shares, memory, `doubling` (growth per doubling) and others |
| `FrontendIdiom.*` | Job `FrontendIdiom`, from S3 |
| `S1.*`, `S2.*`, `S3.*` | Per session: `compiles`, `load.*` (load quantiles), `sens15.*` (slopes with the compiles above 15% load dropped), `total_cpu.*` (TOTAL against CPU time), `sentinel.max_dev` |
| `pooled.<Job>.<a>/<b>.ratio` | S1 and S2 pooled with a two-level bootstrap |
| `between.<Job>.<arm>` | S2's slope over S1's; `between.all.*` and `between.headline.min/max` summarize them |
| `last.*` | A headline number recomputed in S2 alone |
| `corpus.*`, `loc.*` | Computed from the generator, not measured: the shape of the heterogeneous corpus, lines of source per arm |
| `probe.*` | From `Data/PfrProbe.json` |

Single-session numbers come from the first session given that ran the job: S1 for the
full plan, S3 for `FrontendIdiom`.

## Machine-specific and personal fields

These values describe the measuring machine and are kept as recorded; none of them
affects the analysis:

- absolute paths, which contain the Windows user name and the local folder of the private
  development repository: compiler paths and `configure --prefix` lines (`session.json`,
  `env.json`, `PfrProbe.json`), every `cmds.json` entry and every PfrProbe `cmd`, include
  and temporary-directory paths, `python.executable`, `base_flags` (`-B` path) and the
  first lines of `log.txt`;
- the hardware and system state: `cpu`, `memory_*`, `swap_used_gb`, `power_plan`,
  `defender_realtime`, `load_*`, `busiest_processes` (process names only), `host_dll_packages`,
  `assembler`;
- `project_git_head` and `project_dirty_files`: the state of the private development
  repository, whose history is not published; the list also names working files of that
  repository (notes, superseded scripts and data) that are not part of this archive;
- `-mtune=alderlake` in `cmds.json`: both compilers were configured `--with-tune=native`,
  which the driver resolved on this CPU;
- local times in `log.txt` (UTC+2).

## Reading the data

```python
import pathlib, sys
sys.path.insert(0, "Harness")
import stats                                   # needs NumPy only

rows = stats.load_rows(pathlib.Path("Data/Sessions/S1"))   # finished rounds; refuses pilots
jobs = stats.job_data(rows)                    # {(session, job): JobData}, warm-up dropped
jd = jobs[("S1", "FrontendN")]
a = jd.array("ft_total_s")                     # shape (arms, sweep values, measured rounds)
print(jd.arms, jd.xs, a.shape)
```

## Toolchain provenance

`Data/Toolchain/Gcc16.2.0Provenance.txt` is the record that `Harness/build_gcc.sh` wrote when it built GCC 16.2.0: the source tarball's URL, SHA-512 and SHA-256, the GPG verification of its signature (GOODSIG by the release manager's key), the configure line, the include search list and the host compiler. Paths in it are those of the build machine.
