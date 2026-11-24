# CPP26FieldEnumerationCompileCostArtifact

Paper: [arXiv:2611.30250](https://arxiv.org/abs/2611.30250) · Archive (this version):
[doi:10.5281/zenodo.24443567](https://doi.org/10.5281/zenodo.24443567)

The artifact of the paper *What Field Enumeration Costs to Compile in C++26: Native
Reflection, Structured-Binding Packs, Reflection Libraries and Hand-Written Serializers on
GCC 16* (Denys Kachalenko, 2026): the generator, the measurement harness, the raw data of
three measurement sessions, the analysis that turns them into every number and figure of
the paper, and the paper sources.

## Results in one paragraph

All numbers below are front-end costs (`-fsyntax-only`) on GCC 16.2.0, per struct of 16
scalar fields (the scalar corpus, M = 16), from session S1 unless marked S3; session S2
repeats the full plan on another day, and for the slopes behind the headline numbers its
ratio to S1 lies between 0.972 and 1.020. Native P2996 enumeration written as an expansion
statement over the `std::span` that `std::define_static_array` returns costs 1.72 ms per
struct, 7.96× a P1061 structured-binding pack (which costs about as much as hand-written
code: 0.22 against 0.23 ms). Inline it costs about as much as Boost.PFR's `for_each_field`
(1.04×); behind the same callback API, 1.21× as much. A P3394 annotation query on every
member multiplies the span form's cost by 1.37. Per type, each library's C++26 path is
cheaper than its pre-C++26 path (Glaze 2.00×, reflect-cpp 2.08×; at 128 fields per struct
Glaze's gain reverses, 0.70), and Boost.PFR's C++17
path grows almost quadratically with the number of types (12.8× its C++26 path at 4,000
structs). Hand-written serializers that share one overloaded name grow 3.5–4.0× per doubling
of the number of types. The `-freflection` flag alone makes code that does not use
reflection 1.017–1.264× costlier per type on GCC 16.2.0, and up to 2.578× on GCC 16.1.0.
The paper ([`Paper.md`](Paper.md)) gives the intervals, the `-O2` results, the rich and
heterogeneous corpora and the limits of each claim.

**Practical tip (GCC 16.2.0, front end).** Write the expansion statement over a constant
array,

```cpp
constexpr auto Context = std::meta::access_context::unchecked();
template for (constexpr auto Member :
    [:std::meta::reflect_constant_array(std::meta::nonstatic_data_members_of(^^Type, Context)):])
{
    // serialize V.[:Member:]
}
```

instead of over the `std::span` of `std::define_static_array(...)`
(`Include/RB/ReflectArray.hpp` against `Include/RB/ReflectPlain.hpp`). In session S3 the array
form costs 0.47× as much per struct (0.82 against 1.73 ms), 0.49× Boost.PFR's
`for_each_field`; with the fixed costs included, a whole translation unit takes 0.61× the
span form's front-end time with 1,000 structs and 0.50× with 4,000. The array form was not
timed at `-O2` or on the other corpora.

**A GCC compile-time issue.** GCC 16.2.0 declares the range, begin and per-element iterator
variables of a constant iterating expansion statement `static` (2 + n of them per expansion
over n elements) and registers every block-scope `static` by a linear scan of one list for
the whole translation unit (`determine_local_discriminator` in `cp/decl.cc`), so each
expansion pays for all those compiled before it. Ordinary block-scope statics show the
same quadratic growth without any reflection, on every GCC release from 11.5 to the
development branch of November 2026; it is a property of GCC, not of P2996, reported as
[GCC PR128928](https://gcc.gnu.org/bugzilla/show_bug.cgi?id=128928). Reproducers,
each with its command line in its first lines: [`Repro/GccLocalStatics`](Repro/GccLocalStatics)
(`Minimal.cc`: one block-scope variable per instantiation, no headers, with and without
`static`; `ExpansionRange.cc`: the same loop over an array, a `std::span` and a pointer
range; `Statics.cc`: block-scope statics; `Locals.cc`: block-scope local classes;
`Autos.cc`: the control with non-static locals).

## Layout

| Path | Contents |
|------|----------|
| [`Paper.md`](Paper.md) | The paper. Every measured number carries a tag `<!--n:key-->` that names its entry in `Data/PaperNumbers.json`. |
| `Latex/` | `Paper.tex` (generated from `Paper.md` by `Harness/tolatex.py`), `References.bib`, `Figures/` |
| `Figures/` | The paper's figures (`Harness/figures.py`) |
| `Data/Sessions/S1`, `S2`, `S3` | Raw data of the three sessions: every compile, its full `-ftime-report`, the machine record and a copy of the measured code |
| `Data/PfrProbe.json` | The Boost.PFR probe (§4.3 of the paper) |
| `Data/PaperNumbers.json` | Every number the paper cites, with its 95% interval |
| `Data/Preflight/` | The correctness and manipulation checks that passed before the sessions |
| [`DATA.md`](DATA.md) | Data dictionary: every file and every column |
| `Harness/` | Generator, arm registry, checks, session runner, statistics, paper numbers, figures, LaTeX export, GCC build script, unattended run |
| `Include/RB/` | The serializer arms and the shared encoder (C++26) |
| `Test/`, `CMakeLists.txt`, `CMakePresets.json` | CTest correctness tests |
| `Deps.json` | Pins of Boost.PFR, reflect-cpp and Glaze (commit, tarball sha256); the libraries are not redistributed |
| `Repro/GccLocalStatics/` | Reproducers of the GCC issue above |
| [`RunBook.md`](RunBook.md) | The measurement procedure used for S1, S2 and S3 |
| [`Format.md`](Format.md) | The binary wire format every arm writes |
| `requirements.txt`, `CITATION.cff`, `LICENSE`, `LICENSE-DATA.md` | Python dependencies, citation, licenses |

## Reproduce every number in three commands (no compiler)

Python 3.13 with NumPy and Matplotlib (the versions in `requirements.txt`):

```sh
pip install -r requirements.txt
cd Harness
python papernumbers.py ../Data/Sessions/S1 ../Data/Sessions/S2 ../Data/Sessions/S3
python paperlint.py
python figures.py ../Data/Sessions/S1 ../Data/Sessions/S3
```

- `papernumbers.py` recomputes every number from the raw data, including the bootstrap
  intervals (fixed seed), and rewrites `Data/PaperNumbers.json`; the file should come out
  identical (byte-identical on Windows, where it was written; elsewhere only the line
  endings differ). It takes under a minute.
- `paperlint.py` checks every tagged number in `Paper.md` against that file. It should
  report `0 problem(s)` and `0 ⟦review⟧ marker(s)`.
- `figures.py` redraws `Figures/`; the PDFs differ from the archived ones only in their
  `CreationDate` metadata.

Optionally, `python tolatex.py` regenerates `Latex/Paper.tex` (and copies the figures to
`Latex/Figures/`), and the PDF builds with `acmart` (pdfLaTeX and BibTeX, tested with
MiKTeX), from `Latex/`:

```sh
mkdir -p Build && cp References.bib Build/
pdflatex -output-directory=Build Paper.tex
(cd Build && bibtex Paper)
pdflatex -output-directory=Build Paper.tex
pdflatex -output-directory=Build Paper.tex
```

`python stats.py ../Data/Sessions/S1 ../Data/Sessions/S2` prints the per-job slopes,
intervals and the pooled and between-session tables (`stats.py ../Data/Sessions/S3` for S3).

## Re-measuring

The sessions ran on one Windows 11 desktop (Intel Core i5-14600KF) with compilers built
under MSYS2 UCRT64; the harness uses Windows APIs for core pinning, process priority and
the process counters. You need:

- GCC 16.2.0 built by [`Harness/build_gcc.sh`](Harness/build_gcc.sh) (from the release
  tarball, checksum and signature checked, the configure options of the GCC 16.1.0 used
  for comparison), and that GCC 16.1.0 for the cross-check jobs; MSYS2's GCC 15.2.0 for the
  Boost.PFR probe;
- CMake ≥ 3.24 and Ninja for the CTest suite; `python Harness/deps.py fetch` downloads
  and verifies the pinned libraries into `ThirdParty/`;
- Python 3.13 with `psutil` as well (see `requirements.txt`).

[`RunBook.md`](RunBook.md) gives the procedure step by step. Each session is one unattended
run of [`Harness/overnight.sh`](Harness/overnight.sh), which builds and tests, runs the
preflight checks (value oracle, manipulation checks), a smoke test, and the session. The
compiles of S1 and S2 took about 5.7 hours each, those of S3 about 16 minutes. The
paths of the compilers and of Python at the top of `overnight.sh`, the defaults at the top
of `build_gcc.sh` and the paths in `CMakePresets.json` are those of the measuring machine;
set them to your own. On MinGW, the object files of large oracle builds exceed the PE/COFF
section limit and need `-Wa,-mbig-obj`; timed compiles never assemble.

## Arms

Every arm writes byte-identical output through one shared value encoder; the arms differ
only in how they enumerate the fields. `Harness/arms.py` is the registry.

| Arm | Field enumeration | Per-type source |
|-----|-------------------|-----------------|
| `manual` / `manual_unique` | hand-written; one overloaded name / a distinct name per type | every field |
| `xmacro` / `xmacro_unique` | X-macro field list; one overloaded name / distinct names | every field |
| `reflect` | P2996, plus a P3394 annotation query per member | none |
| `reflect_plain` | P2996: expansion statement over the `std::span` of `define_static_array` | none |
| `reflect_visit` | P2996 behind a callback API shaped like `boost::pfr::for_each_field` | none |
| `reflect_array` (S3) | P2996, the same member query: expansion statement over a constant array (`[:reflect_constant_array(...):]`) | none |
| `reflect_index` (S3) | P2996, the same member query: a P1061 index pack bound from `make_index_sequence` (reflect-cpp's C++26 form) | none |
| `reflect_seq` (S3) | P2996, the same member query: an index-sequence helper | none |
| `p1061` / `p1061_visit` | C++26 structured-binding pack (P1061), inline / behind the same callback API | none |
| `pfr` | Boost.PFR, default under `-std=c++26` (its P1061 path) | none |
| `pfr_classic` | Boost.PFR, C++17 path (`-DBOOST_PFR_USE_CPP26=0`) | none |
| `pfr_native` | Boost.PFR with `-DBOOST_PFR_USE_CPP26_REFLECTION=1`: the same code as `pfr` (identical disassembly); the flag only adds headers (a code-identical control) | none |
| `rflcpp` / `rflcpp_native` | reflect-cpp, C++20 path / C++26 path (`-DREFLECTCPP_USE_CPP26_REFLECTION`) | none |
| `glaze_classic` / `glaze_native` | Glaze, traditional backend (forced) / P2996 backend (`-DGLZ_REFLECTION26=0/1`) | none |
| `reflect_split`, `pfr_split` | `-O2` layout controls: `reflect` and `pfr` with one function per call site | none |
| `*_noflag` | control: the same arm compiled with `-fno-reflection` | — |
| `*_noreport` | control: the same arm compiled without `-ftime-report` (compared on external wall time) | — |
| `arm@GCC161` | the same arm compiled by GCC 16.1.0, in the same rounds (cross-check) | — |
| `ovl_*` | overload matrix, ten idioms (`Harness/overload.py`): qualified free function; ADL; ADL through a library dispatch template; constrained template; `serialize(Archive&, T&, unsigned)`; one namespace per type; hidden friend; member; class-template specialization; distinct names | every field |

## How to cite

Please cite the paper, and the archive for the code and data:

> Denys Kachalenko. 2026. What Field Enumeration Costs to Compile in C++26: Native
> Reflection, Structured-Binding Packs, Reflection Libraries and Hand-Written Serializers
> on GCC 16. arXiv:2611.30250. https://arxiv.org/abs/2611.30250
>
> Denys Kachalenko. 2026. Artifact of "What Field Enumeration Costs to Compile in C++26"
> (version 1.0.0). Zenodo.
> https://doi.org/10.5281/zenodo.24443567

[`CITATION.cff`](CITATION.cff) holds the same in machine-readable form.

## Licenses

- Code (`Harness/`, `Include/`, `Test/`, `Repro/`, the CMake files, `Deps.json`): MIT, see
  [`LICENSE`](LICENSE).
- Data (`Data/`) and text (`Paper.md`, `Latex/`, `Figures/` and the Markdown
  documentation): CC BY 4.0, see [`LICENSE-DATA.md`](LICENSE-DATA.md).
- The pinned libraries are not part of this archive; each comes under its own license.

## AI assistance

The measurement harness, the analysis scripts and the text were written with an AI
assistant under the author's direction, as the paper's Acknowledgments state.

Author: Denys Kachalenko, independent researcher, Ukraine
(ORCID [0009-0003-8597-329X](https://orcid.org/0009-0003-8597-329X)).
