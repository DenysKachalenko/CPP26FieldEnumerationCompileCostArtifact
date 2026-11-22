# What Field Enumeration Costs to Compile in C++26: Native Reflection, Structured-Binding Packs, Reflection Libraries and Hand-Written Serializers on GCC 16

## Abstract

C++26 adds standard ways to enumerate a struct's fields, among them static reflection
(P2996, with P3394 annotations) and structured-binding packs (P1061), alongside hand-written
code, X-macros and libraries (Boost.PFR, reflect-cpp, Glaze) that now ship pre-C++26 and
C++26 paths. We time each in a struct serializer with byte-identical output on
GCC 16.2.0, at the front end and at `-O2`, in randomized interleaved rounds with code-level
checks of every single-factor contrast. At the front end, inline native enumeration in the
form used in several of P2996's own examples, an expansion statement over the `std::span`
of `define_static_array`, costs about as much per struct of 16 scalar fields as Boost.PFR
and 7.96<!--n:FrontendN.reflect_plain/p1061.ratio-->× a P1061 pack, itself about as cheap
as hand-written code.
The same loop over a constant array costs
0.47<!--n:FrontendIdiom.reflect_array/reflect_plain.ratio-->× as much: about half of the
span form's cost comes with the span. The ratio to P1061 shrinks on a heterogeneous type
graph and at `-O2`. In a whole translation unit at the front end the library outweighs the
mechanism: 200 structs take 0.59<!--n:FrontendHeavy.reflect_plain.total200_s--> s
with inline native enumeration, 0.56<!--n:FrontendHeavy.pfr.total200_s--> s with Boost.PFR
and 3.86<!--n:FrontendHeavy.rflcpp_native.total200_s-->–4.13<!--n:FrontendHeavy.glaze_native.total200_s--> s
with the C++26 paths of reflect-cpp and Glaze, whose visitors also compute field names.
Per type, each library's C++26 path is cheaper than its pre-C++26 path at 16 fields, but
Glaze's gain reverses at 128 fields (pinned release v9.1.0); Boost.PFR's C++17 path grows
almost quadratically with the number of types. Hand-written serializers sharing one
overloaded name grow superlinearly with the number of types. The `-freflection` flag
alone makes reflection-free code up to 1.264<!--n:CompilerFlag.p1061.flag_slope_ratio-->×
costlier per type on
GCC 16.2.0 and up to 2.578<!--n:CompilerFlag.p1061@GCC161.flag_slope_ratio-->× on 16.1.0,
so comparisons between mechanisms depend on the point release. Part of the span form's
cost grows with the number of structs, which we trace to GCC registering block-scope
statics in quadratic time (reported as GCC PR128928).

## 1. Introduction

Serialization is boilerplate: for every type, code that visits every field. C++ has
attacked it with the preprocessor (X-macros), with library "reflection" built on
aggregate-initialization probing, structured bindings and parsing of compiler-generated
function names (Boost.PFR, reflect-cpp, Glaze), and now with C++26 language features:
static reflection (P2996) with annotations (P3394), structured bindings that introduce a
pack (P1061), and expansion statements (P1306), which iterate over reflected members and
can also destructure a struct directly. For a practitioner the question is concrete: *what does
each of these cost to compile, and what does each save in source?*

Native P2996 compile time has only begun to be measured. Romeo (2026a) times native
reflection alone on single translation units; mp-units (Pusz, 2026) runs an in-repo A/B
whose author considers the sign of the effect reliable but not its magnitude; simdjson
reports, on clang-p2996, a 6% slowdown of its whole build with reflection enabled; and the
field-reflection library (Matsuda, 2026) lists in its README the per-type cost of its
`std::meta` backend next to Boost.PFR's, as best-of-three
numbers. We found no published measurement, as of November 2026, that compares native
reflection with each library's two paths, with P1061, or with hand-written and macro
baselines on one serialization task (§5). A tooling vendor's blog calls compile-time impact
"the biggest open question" (Whole Tomato, 2026).

**Research questions.**

- **RQ1 — mechanisms.** Per type, what does field enumeration cost to compile with P2996,
  with P1061, through a library's callback API, and by hand; and what does a P3394
  annotation query add?
- **RQ2 — library backends.** Each of Boost.PFR, reflect-cpp and Glaze can be built on
  its pre-C++26 path or its C++26 path from the same source. Does switching change its
  compile cost, and how does that change scale with the number of fields per struct?
- **RQ3 — per-type serializer idioms.** Which documented customization idioms make
  hand-written serialization grow faster than linearly with the number of types, and
  why?
- **RQ4 — what the numbers depend on.** How large are the fixed costs (`<meta>`, library
  headers, the `-freflection` flag itself), how do the results change at `-O2`, on
  richer corpora and a heterogeneous type graph, between sessions, and between GCC
  16.1.0 and 16.2.0?
- **RQ5 — maintainability.** How much per-type source does each approach need?

**Contributions.**

1. A head-to-head compile-time comparison of field enumeration for serialization:
   P2996, P1061, hand-written code, X-macros and three libraries, each library on both
   of its paths (three same-source backend A/Bs), on GCC 16.2.0, with key arms
   (configurations, §3.1) also compiled by GCC 16.1.0 in the same rounds.
2. A factorial decomposition of native and library enumeration cost: enumeration
   mechanism (P2996 or P1061) × API shape (inline or callback), the annotation query, and
   the library machinery around the same primitive. Native enumeration here means the
   form timed throughout, an expansion statement over the `std::span` of
   `define_static_array` (Listing 1); the decomposition shows that, at the front end, this
   form matches Boost.PFR only when written inline, not behind the same callback API. A
   supplementary session times four formulations of the same member query. On GCC 16.2.0,
   about half of the span form's front-end cost comes with the span, which we attribute
   mainly to GCC's evaluation of the iterating expansion statement that C++26 specifies
   over it. Over a constant array, inline native
   enumeration costs 0.49<!--n:FrontendIdiom.reflect_array/pfr.ratio-->× Boost.PFR's
   callback `for_each_field`.
3. A comparison of ten customization idioms for per-type serializers, with the number of
   call sites and the number of candidates varied separately; serializers that share one
   overloaded name grow superlinearly with the number of types.
4. Controls that bound the measurement itself: a code-identical pair that differs only in
   what a library flag adds to the parse, the cost of the `-freflection` flag on both
   compiler versions, the overhead of `-ftime-report`, a value-level correctness oracle
   with a negative control, and code-level manipulation checks on every pair of arms
   meant to differ in a single factor.
5. An open artifact: generator, harness, raw per-run data and environment records.

## 2. Background

**Enumerating fields in C++26.** P2996 reflects an entity with `^^` to a
`std::meta::info`; `std::meta::nonstatic_data_members_of` returns a type's fields, and a
splice `v.[:m:]` accesses one. Our native serializers iterate those fields with an
expansion statement (`template for`, P1306) over `std::define_static_array` (P3491)
(Listing 1). This is one of several ways to write native enumeration; every job of S1 and
S2 with a native arm times it, and a supplementary session times three others (§4.2).
P3394 attaches values to declarations (`[[=RB::FTransient{}]]`), which reflection can
query, e.g. to skip a field. P1061 lets a structured binding introduce a pack: inside a
template, `const auto& [... m] = v;` binds every field of a struct such as ours (all
non-static data members accessible and declared in one class), so a fold expression
visits them all — enumeration without names or annotations (P1061R10 allows such a pack
only in a templated entity). An expansion statement can also destructure the struct
itself, `template for (const auto& f : v)`, with the same limits (no names, no
annotations) but outside templates too; we did not time this form. GCC 16 implements
P2996R13, P3394R4, P3491R3, P1306R5 and P1061R10; reflection needs `-freflection`, which
GCC labels experimental.

**Pre-C++26 library techniques.** Libraries count an aggregate's fields by probing
aggregate initialization with an object convertible to any type, bind them through a
generated ladder of structured bindings (one case per field count), and recover names by
parsing `__PRETTY_FUNCTION__` or `std::source_location::function_name()` of a template
instantiated on the address of a member of an `extern` object that is never defined.
**Boost.PFR**'s classic
path works this way; under `-std=c++26` on GCC 16 it switches by itself to a path built
on P1061 packs. Its P2996 engine (`BOOST_PFR_USE_CPP26_REFLECTION`) is not reached by
`for_each_field` (§3.3), and on its own it cannot serialize runtime objects at the pinned
release, because its member access (`detail::reference_by_index`) is `consteval`.
**reflect-cpp** has a C++20 path and, since v0.26.0 (2026-10-18), an opt-in C++26 path;
its documentation states that the latter is "considerably cheaper" to compile, without
measurements. **Glaze** has a traditional backend and a P2996 backend. At the pinned
release the traditional backend counts members with a recursive chain of
aggregate-initialization probes (`V{Args{}..., any_t{}}`), binds them through a generated
ladder of structured bindings, parses names from `__PRETTY_FUNCTION__` and accepts at
most 128 members per struct; Glaze's documentation calls the count a structured-binding
probe. Glaze selects its P2996 backend by itself when the compiler defines
`__cpp_impl_reflection`, as GCC 16 does under `-freflection`.

**Per-type customization idioms.** Many serialization and formatting libraries let users
write one function per type under one name and find it by name lookup: nlohmann::json's
`to_json` and its `NLOHMANN_DEFINE_TYPE_NON_INTRUSIVE` macro, Boost.JSON's `tag_invoke`,
`BOOST_DESCRIBE_STRUCT`, {fmt}'s `format_as`, cereal's external `serialize`, and
Boost.Serialization's non-intrusive `serialize`. When N user types live in one namespace,
each resolution of such a name considers N candidates. nlohmann::json, Boost.JSON and
{fmt} make the unqualified call inside their own dispatch template, so it is resolved
once per serialized type; code that calls the name directly resolves it once per call
site. Hidden friends (nlohmann's `_INTRUSIVE` macro, `BOOST_DESCRIBE_CLASS`), member
functions (cereal's preferred form, protobuf) and class-template specializations
(`glz::meta`, `fmt::formatter`) do not create that set.

## 3. Methodology

### 3.1 Arms

Every arm writes the same little-endian binary format through one shared value encoder,
so outputs are byte-identical; arms differ only in how they enumerate fields.

| Arm | Field enumeration | Per-type source |
|-----|-------------------|-----------------|
| `manual` / `manual_unique` | hand-written; one overloaded name / a distinct name per type | every field |
| `xmacro` / `xmacro_unique` | X-macro field list; one overloaded name / distinct names | every field |
| `reflect` | P2996, plus a P3394 annotation query per member | none |
| `reflect_plain` | P2996 | none |
| `reflect_visit` | P2996 behind a callback API shaped like `boost::pfr::for_each_field` | none |
| `reflect_array` / `reflect_index` / `reflect_seq` (S3 only) | P2996, the same member query: the expansion statement over a constant array (`[:reflect_constant_array(...):]`) / a P1061 index pack bound from `make_index_sequence` (reflect-cpp's C++26 form) / an index-sequence helper | none |
| `p1061` / `p1061_visit` | P1061 pack, inline / behind the same callback API | none |
| `pfr` | Boost.PFR, default under `-std=c++26` (its P1061 path) | none |
| `pfr_classic` | Boost.PFR, C++17 path (`-DBOOST_PFR_USE_CPP26=0`) | none |
| `pfr_native` | Boost.PFR with `-DBOOST_PFR_USE_CPP26_REFLECTION=1`: compiles to the same code as `pfr` (identical disassembly, §3.3); the flag only adds headers to the parse (code-identical control, §4.2) | none |
| `rflcpp` / `rflcpp_native` | reflect-cpp, C++20 path / C++26 path | none |
| `glaze_classic` / `glaze_native` | Glaze, traditional backend (forced) / P2996 backend | none |

We call the arms of S1 and S2 other than those of reflect-cpp and Glaze *light*; the
three S3 arms run only in FrontendIdiom. The four arms of
those two libraries, which we call *heavy*, cost 12.75<!--n:FrontendHeavy.glaze_native.slope-->
to 30.56<!--n:FrontendHeavy.rflcpp.slope--> ms per struct at the front end (Table 2), so the
jobs that time them stop at N = 200 or earlier. In the job table of §3.5 and in §4.1, §4.5
and §4.6, "the libraries" means these heavy arms; the Boost.PFR arms are light.

**Listing 1.** The core of the arms (from `Include/RB` and the generator). `Enc::Any` is
the shared value encoder; it hands nested structs back to the arm through `FSelf`.

```cpp
// reflect_plain: P2996 queries, P1306 expansion statement, P3491 static array
template<typename Type>
void Write(FByteWriter& Writer, const Type& V)
{
    constexpr auto Context = std::meta::access_context::unchecked();
    template for (constexpr auto Member :
        std::define_static_array(std::meta::nonstatic_data_members_of(^^Type, Context)))
    {
        Enc::Any<FSelf>(Writer, V.[:Member:]);
    }
}

// reflect_array (S3): the same loop over a constant array instead of the std::span
//     template for (constexpr auto Member :
//         [:std::meta::reflect_constant_array(std::meta::nonstatic_data_members_of(^^Type, Context)):])

// p1061: structured-binding pack and fold expression
template<typename Type>
void Write(FByteWriter& Writer, const Type& V)
{
    const auto& [... Members] = V;
    (Enc::Any<FSelf>(Writer, Members), ...);
}

// manual_unique: generated, one non-template function per type
inline void WriteManualS0(RB::FByteWriter& Writer, const S0& V)
{
    RB::Enc::Value(Writer, V.M0);
    // ... one statement per field
}
```

The callback arms (`reflect_visit`, `p1061_visit`) move the same loop or fold into a
function template `ForEachField(V, Func)` and pass it
`[&](const auto& Field) { Enc::Any<FSelf>(Writer, Field); }`, the lambda that the `pfr`
arm passes to `boost::pfr::for_each_field`. `reflect` wraps the call in
`if constexpr (!IsTransient(Member))`, where `IsTransient` tests
`annotations_of_with_type(Member, ^^RB::FTransient)`.

Library arms call the libraries' field visitors (`boost::pfr::for_each_field`,
`rfl::to_view(v).apply`, `glz::for_each_field`), not their own serializers, so every arm
emits the same bytes; each includes the narrowest library header that provides its
visitor. Nested structs, also inside vectors and optionals, go back to the arm's own
enumeration. Further arms serve as controls: `*_split` (one function per call site, for
`-O2`), `*_noflag` (compiled with `-fno-reflection`), `*_noreport` (compiled without
`-ftime-report`), `arm@GCC161` (the same arm compiled by GCC 16.1.0 in the same rounds),
and ten overload-matrix variants (§4.4).

### 3.2 Corpora

A generator emits N structs and one benchmark translation unit per arm that serializes
each struct once. *Scalar*: M fields per struct, cyclically from eight integer,
floating-point and `bool` types; every struct has the same member list. *Rich*: the
same with strings, vectors and optionals. *Hetero*: a type graph whose field counts
vary per struct (log-normal, median 8<!--n:corpus.hetero.fields_median-->, at most
32<!--n:corpus.hetero.fields_max--> at N = 1,600), with enums
(10%<!--n:corpus.hetero.share.enum--> of fields), nested structs
(14%<!--n:corpus.hetero.share.struct-->), and vectors
(8%<!--n:corpus.hetero.share.vec_struct-->) and optionals
(6%<!--n:corpus.hetero.share.opt_struct-->) of structs, at most six levels deep. It is
prefix-stable — the first k types are the same for every N — so the marginal cost of
added types is well defined. Every benchmark file serializes objects declared `extern`,
so at `-O2` the optimizer cannot fold known field values into the generated code.

### 3.3 Correctness and manipulation checks

**Value-level oracle.** Integer, floating-point and string fields receive values that
are distinct and non-zero per field; bool fields alternate; strings and vectors are
non-empty and optionals mixed. Each arm's output must equal the hand-written reference
byte for byte, and a serializer that writes the fields in reverse order must be rejected
— otherwise the oracle reports itself blind. The oracle is built for every flag set a
timed arm uses (reflection-free arms without `-freflection`), and each build must report
the expected library-backend configuration; it runs on the scalar and rich corpora at
M = 16 and M = 128 and on the heterogeneous corpus at the largest N timed (1,600 types,
on a sample that includes every shape class). Further oracles cover the ten overload
variants and the P3394 path (a `Transient` member must be skipped). A CTest suite runs
every arm that can nest (all but `xmacro_unique`) on a nested record with containers,
under each library backend.

**Manipulation checks.** For every pair of arms meant to differ in a single factor (the
backend A/Bs, the annotation query, API shape, mechanism, the native formulations of S3,
Boost.PFR's machinery,
overloaded against distinct names, the flag-only controls and the split controls), the
harness compiles both arms and checks, in three ways, that the intended difference is
present on one side only. In the object files, a marker function must exist on one side only for each
backend A/B (for example `glz::detail::get_member_ref` only in the P2996 build of Glaze,
`tie_as_tuple` only in Boost.PFR's C++17 path, `rfl::internal::cpp26::bind_to_tuple`
only in reflect-cpp's C++26 path). In the preprocessed source, the intended difference
must appear on one side only (the annotation query only in `reflect`; the
`nonstatic_data_members_of` call only in the P2996 arm and the structured-binding pack
only in the P1061 arm). A pair meant to be identical — `pfr`/`pfr_native` and every
`-fno-reflection` control — must have the same disassembly. Every arm's flags must reach
the exact compiler command that is timed, and `-fno-reflection` must remove
`__cpp_impl_reflection`. The checks for a differing pair do not exclude other
differences: the P2996 and P1061 arms also differ in parsing `<meta>` and in the expansion
statement, and the span and array forms of S3 in the calls that `define_static_array`
adds (§4.2, §6). These checks exist because a flag documented as a backend
switch can fail to reach the code being called: `BOOST_PFR_USE_CPP26_REFLECTION=1`
changes nothing in `boost::pfr::for_each_field` under `-std=c++26` on GCC 16 — the
object files define the same functions, with identical disassembly, with and without it.
Pairs that differ in many factors at once (native against Boost.PFR, a library against
the native arm) have no single expected difference and are checked only through the
oracle. The checks ran once for each compiler and are bound to the measurement code (a
fingerprint of the harness modules, `Include/RB` and the library pins) and to each
compiler's `cc1plus` hash: a session starts only when each of its compilers has a passing
check for exactly that code: S1 and S2 had one on both compilers, and S3, which uses GCC
16.2.0 only, had one for its own code, which adds the three arms. Before each session the library pins are
verified again and the CTest suite is re-run with GCC 16.2.0.

**Code provenance.** The code of this study was written with an AI assistant under the
author's direction (Acknowledgments); it is verified by the checks above and by
regenerating every number in the paper from the archived raw data and checking it against
the text (Artifact).

### 3.4 What is measured

The metric is the compiler's own `-ftime-report` TOTAL: wall time measured inside the
compiler proper (GCC 16 reports wall time and garbage-collected memory, not CPU time),
together with its phase and sub-phase timers and its garbage-collected (GGC) memory.
For every compile the harness also stores the external wall time and, read from the
exited process, its user and kernel CPU time, CPU cycles, peak working set, peak commit
and page faults. The harness runs `cc1plus` directly with exactly the command line the
`g++` driver generates (`-###`), at high process priority, restricted to the performance
cores of the hybrid CPU. Running `cc1plus` directly matters: a child of a high-priority
driver runs at normal priority on Windows, so launching through the driver would leave the
timed process unprotected. Two modes:
`-fsyntax-only` (front end: parsing, template instantiation, constant evaluation) and
`-O2 -c` (adds optimization and code generation; the assembly is written to the null
device, so the assembler is not run). Per-type numbers exclude fixed costs: they are
slopes over N (§3.6) or marginal costs, the cost at N structs minus the cost at N = 0.

### 3.5 Protocol

A session runs the jobs below. In each job, one warm-up round and eleven measured rounds
each compile every cell (arm × sweep value) once, in a seeded random order, between two
compiles of a fixed sentinel cell that tracks drift. Arms compared in a ratio always
come from the same job and so share rounds. Before timing, the harness records the
machine (CPU and core layout, power plan, antivirus state, per-CPU load and busiest
processes), every compiler's hashes and configure line, the library pins and a
fingerprint of the measurement code, of which it keeps a copy; it binds the session to
its compilers, code and protocol, so a resumed session cannot silently mix them. It runs
under the High performance power plan. Rounds are not repeated: the machine's CPU load
during each compile is recorded with that compile, and every estimate is a median or a
fit over the eleven measured rounds. Two sessions on different days measure the full
plan on GCC 16.2.0; the comparison jobs compile their arms with GCC 16.2.0 and GCC 16.1.0
side by side in the same rounds. A third, short session (S3, 2026-11-21) ran one
supplementary job, FrontendIdiom, on GCC 16.2.0 with the same protocol; it was added after
the review of the first two to time other native formulations, and its preflight checked
the three new arms as it checks all others. Before the session, six of its seven arms
(all but the array form, added later) were compiled once each informally and, with the
array form added, a one-round smoke test of the whole job ran; neither is used
here. Its analysis rules were fixed before the session: formulations are compared only
within the job, an effect is attributed to the expansion statement's lowering only
through the array/span pair, and the arms shared with S1 are compared with S1
descriptively. Those shared arms allocate the same GGC memory as in S1 at every N.

S1 and S2 each ran 8,484<!--n:S1.compiles--> compiles, none of which failed. During the
measured compiles the machine's total CPU load (over all 20 logical CPUs, of which the
single-threaded compiler alone accounts for up to 5%) had a median of
8.0<!--n:S1.load.median_pct-->% in S1 and 7.3<!--n:S2.load.median_pct-->% in S2, and
exceeded 15% for 5.1%<!--n:S1.load.above15_share--> and
2.0%<!--n:S2.load.above15_share--> of compiles. Dropping those compiles before taking the
cell medians changes 90<!--n:S1.sens15.within1pct--> of S1's
96<!--n:S1.sens15.n--> per-arm slopes that pass the linearity check and rise by at least
ten timer steps (in every job but ReportOverhead, which is compared on external wall time)
by no more than 1% (the largest change is 2.1%<!--n:S1.sens15.max_change-->), and all
97<!--n:S2.sens15.n--> of S2 by no more than 0.6%<!--n:S2.sens15.max_change-->. For compiles longer than 2 s, TOTAL lies within 3% of the
process's CPU time (user + kernel) in 99.3%<!--n:S1.total_cpu.within3pct--> of cases in S1
and 99.2%<!--n:S2.total_cpu.within3pct--> in S2, so these compiles spent almost no time
waiting off the CPU; the sentinel cell stayed within 4.7%<!--n:S1.sentinel.max_dev--> (S1)
and 5.2%<!--n:S2.sentinel.max_dev--> (S2) of its median in every job. S3 ran
444<!--n:S3.compiles--> compiles, none of which failed, at a median load of
8.0<!--n:S3.load.median_pct-->% (2.9%<!--n:S3.load.above15_share--> of compiles above
15%). Dropping its compiles above 15% load changes none of its slopes by more than
0.3%<!--n:S3.sens15.max_change-->. TOTAL lies within 3% of CPU time in
95.5%<!--n:S3.total_cpu.within3pct--> of its 111<!--n:S3.total_cpu.n--> compiles longer
than 2 s, fewer than in S1 and S2; no cell holds more than one of the others, so the cell
medians absorb them. Its sentinel stayed within 4.8%<!--n:S3.sentinel.max_dev--> of its
median.

| Job | Mode | Corpus | Sweep | Arms |
|-----|------|--------|-------|------|
| FrontendN | front end | scalar, M = 16 | N ∈ {0, 500, 1,000, 2,000, 4,000} | all light arms, incl. `manual`, `xmacro` and `pfr_native` |
| FrontendHeavy | front end | scalar, M = 16 | N ∈ {0, 25, 50, 100, 200} | reflect-cpp and Glaze, both paths, + `reflect_plain`, `p1061_visit`, `pfr` |
| FrontendM | front end | scalar, N = 50 | M ∈ {0, 8, 16, 32, 64, 128} | light arms except `manual`, `xmacro` and `pfr_native`, + heavy arms |
| RichN | front end | rich, M = 16 | N ∈ {0, 25, 50, 100, 200} | every serializer arm of S1 and S2 |
| HeteroN | front end | hetero | N ∈ {0, 200, 400, 800, 1,600} | light arms except `xmacro_unique`, which cannot nest |
| HeteroHeavy | front end | hetero | N ∈ {0, 25, 50, 100, 200} | heavy arms + `reflect_plain`, `p1061_visit`, `pfr` |
| FullN | `-O2` | scalar, M = 16 | N ∈ {0, 50, 100, 200, 400} | light arms except `xmacro` and `pfr_native`, + split controls |
| FullHeavy | `-O2` | scalar, M = 16 | N ∈ {0, 25, 50, 100} | heavy arms + `reflect_plain`, `p1061_visit`, `pfr` |
| OverloadN | front end | scalar, M = 16 | K = C = N ∈ {0, 250, 500, 1,000} | ten idioms |
| OverloadC | front end | scalar, M = 16 | C ∈ {0, 250, 500, 1,000, 2,000} at K = 2,000 (every type also called once) | free function, `serialize` template, dispatch template, distinct names |
| OverloadK | front end | scalar, M = 16 | K ∈ {500, 1,000, 2,000, 4,000} at C = 500 | free function, `serialize` template, distinct names |
| CompilerN, CompilerFlag | front end | scalar, M = 16 | N ∈ {0, 500, 1,000, 2,000} | key arms on GCC 16.2.0 and 16.1.0, paired; CompilerFlag with and without `-freflection` |
| CompilerHeavy | front end | scalar, M = 16 | N ∈ {0, 50, 100, 200} | both paths of Glaze and reflect-cpp + `reflect_plain`, on both compilers, paired |
| FlagCost, FlagCostHeavy | front end | scalar, M = 16 | N ∈ {0, 500, 1,000, 2,000} / {0, 50, 100, 200} | non-reflection arms with and without `-freflection` |
| FrontendIdiom (S3 only) | front end | scalar, M = 16 | N ∈ {0, 500, 1,000, 2,000, 4,000} | `reflect_plain`, `reflect_array`, `reflect_index`, `reflect_seq`, `p1061`, `pfr`, `manual_unique` |
| ReportOverhead | front end | scalar, M = 16 | N ∈ {0, 1,000, 2,000} | `reflect_plain`, `pfr`, `manual_unique` with and without `-ftime-report` (external wall time) |

### 3.6 Statistics

For each cell the estimate is the median over measured rounds. Per-type costs are
ordinary least-squares slopes of the cell medians against N (or M, K, C), for curves
that pass the linearity check below. Uncertainty comes from a bootstrap over rounds
(4,000 resamples): rounds are drawn with replacement and every statistic — cell medians,
slopes, ratios, shares and crossovers — is recomputed on the same draw, which keeps the
within-round pairing of arms. Because `-ftime-report` prints wall time in 10 ms steps
(GCC 16 can write the same report at finer resolution into SARIF output, which we did not
use), each resampled value receives uniform jitter of one step (a smoothed bootstrap), so
near-constant cells do not yield zero-width intervals; timer rows GCC omits (under about
5 ms) count as zero. Point estimates use the unsmoothed medians, so an estimate can sit
just outside its smoothed interval; this happens for two cited numbers, both by less than
0.01. Intervals are 95% percentile intervals within one session.

Where a curve is not linear we report point values or a fitted quadratic, not a slope.
A curve counts as not linear when the slope over the upper half of its sweep differs
from the slope over the lower half by more than a factor of 1.25 and the 95% interval
of that ratio excludes 1, or when its linear fit has R² < 0.98 and misses some cell by
more than three timer steps. The half test is skipped for a curve that rises by less
than ten timer steps over either half, where the timer cannot show curvature; the R²
test still applies. A curve that passes can still bend, so a slope is an average over
its job's sweep and depends on that sweep: `reflect_plain` costs
1.72<!--n:FrontendN.reflect_plain.slope--> ms per struct over N ≤ 4,000 (FrontendN) and
1.39<!--n:FrontendHeavy.reflect_plain.slope--> ms over N ≤ 200 (FrontendHeavy), `pfr`
1.66<!--n:FrontendN.pfr.slope--> and 1.39<!--n:FrontendHeavy.pfr.slope--> ms. This is a
further reason why ratios are formed only within one job.

Unless marked otherwise, every measured number in §4 comes from session S1; the native
formulations of §4.2 come from S3 (job FrontendIdiom), and the Boost.PFR probe of §4.3 is a
separate run. Session S2 repeats the full plan on another day with the
same compilers, code and protocol. Two sessions cannot estimate between-session variance,
so we do not pool intervals across sessions; §4.6 instead compares the sessions arm by
arm, as the ratio of each per-type slope in S2 to its value in S1, and gives the pooled
point estimates of the main ratios. The number of rounds is checked afterwards by
resampling fewer rounds: with five rounds per cell instead of eleven, the 95% interval of
the FrontendN slope widens from 1.5%<!--n:FrontendN.reflect_plain.ciw11--> to
2.1%<!--n:FrontendN.reflect_plain.ciw5--> of the estimate for `reflect_plain`, from
2.2%<!--n:FrontendN.p1061.ciw11--> to 3.3%<!--n:FrontendN.p1061.ciw5--> for `p1061` and from
1.4%<!--n:FrontendN.pfr.ciw11--> to 2.0%<!--n:FrontendN.pfr.ciw5--> for `pfr`.

### 3.7 Toolchain, libraries, machine

GCC 16.2.0 built from the release tarball (SHA-512 checked against the published sum,
signature checked) with the configure options of the GCC 16.1.0 used for comparison,
both non-bootstrapped and built by the same host compiler (MSYS2 GCC 15.2.0), with the
same install layout (the MinGW headers in the prefix, the compiler executables stripped
of debug information), `--enable-checking=release`, flags `-std=c++26 -freflection`. Both
compilers are configured with `--with-tune=native`, which the driver resolves to
`-mtune=alderlake` on this machine. Libraries were pinned by commit to their latest
releases at the time (2026-11-17) and fetched as sha256-verified archives: Boost.PFR from
Boost 1.92.0 (401385c), reflect-cpp v0.27.1 (e0ee3f6), Glaze v9.1.0 (43b175e). Machine:
Intel Core i5-14600KF (6 performance + 8 efficiency cores; the harness and the compiler
run on the 12 logical CPUs of the performance cores), 32 GB, Windows 11 (build 26300)
with Microsoft Defender real-time protection on, MinGW-w64 UCRT.

## 4. Results

### 4.1 Fixed costs (RQ4)

Including `<meta>` and the native arm's headers adds
30<!--n:FrontendN.fixed.meta_ms--> ms [23, 37]<!--ci:FrontendN.fixed.meta_ms--> to a
translation unit that already includes `<string>`, `<vector>` and `<optional>`
(`reflect_plain` against `p1061` at N = 0, same job). The libraries' headers (the
narrowest that provide each visitor, §3.1) cost far more. Over Boost.PFR at N = 0,
reflect-cpp adds 620<!--n:FrontendHeavy.rflcpp.fixed_over_pfr_ms--> ms on its C++20 path
and 550<!--n:FrontendHeavy.rflcpp_native.fixed_over_pfr_ms--> ms on its C++26 path; Glaze
adds 1260<!--n:FrontendHeavy.glaze_classic.fixed_over_pfr_ms--> ms with its traditional
backend and 1270<!--n:FrontendHeavy.glaze_native.fixed_over_pfr_ms--> ms with its P2996
backend. These fixed costs are excluded from every per-type number below by
construction. Whether added headers also change per-type cost is what the code-identical
control measures (§4.2).

**The `-freflection` flag.** On code that does not use reflection, enabling the flag
raises per-type front-end cost by a factor of
1.188<!--n:FlagCost.manual_unique.flag_slope_ratio--> for hand-written code,
1.239<!--n:FlagCost.p1061.flag_slope_ratio--> for P1061 and
1.082<!--n:FlagCost.pfr.flag_slope_ratio--> for Boost.PFR, and by
1.039<!--n:FlagCostHeavy.glaze_classic.flag_slope_ratio--> and
1.017<!--n:FlagCostHeavy.rflcpp.flag_slope_ratio--> for the pre-C++26 paths of Glaze and
reflect-cpp. It raises fixed cost by one to three 10 ms timer steps (Boost.PFR
10<!--n:FlagCost.pfr.flag_fixed_ms--> ms [1, 16]<!--ci:FlagCost.pfr.flag_fixed_ms-->, Glaze
30<!--n:FlagCostHeavy.glaze_classic.flag_fixed_ms--> ms
[22, 51]<!--ci:FlagCostHeavy.glaze_classic.flag_fixed_ms-->). The compiled code is
identical with and without it (§3.3). On GCC 16.1.0 the flag costs far more (§4.6). GCC
16.0 had a 19% flag cost on `<bits/stdc++.h>` (PR124925), and GCC 16.2.0 contains, among
other reflection changes, a rewrite of the check responsible for a 40-fold slowdown in
another case (PR125179). Every serializer arm in this study is compiled with the flag
(only the `*_noflag` controls are not), so the native arms carry no flag-only handicap in
the comparisons below; a project that turns the flag on to use reflection also pays its
cost on the code that does not use it.

**The instrument.** Compiling with `-ftime-report` raises the per-struct slope of external
wall time by 1.028<!--n:ReportOverhead.reflect_plain.wall_slope_ratio-->× for the native
arm, 1.041<!--n:ReportOverhead.pfr.wall_slope_ratio-->× for Boost.PFR and
1.123<!--n:ReportOverhead.manual_unique.wall_slope_ratio-->×
[1.094, 1.150]<!--ci:ReportOverhead.manual_unique.wall_slope_ratio--> for hand-written
code (whole translation units at N = 2,000:
1.031<!--n:ReportOverhead.reflect_plain.wall_ratio-->,
1.042<!--n:ReportOverhead.pfr.wall_ratio--> and
1.086<!--n:ReportOverhead.manual_unique.wall_ratio-->). Relative to its cost, hand-written
code pays the most, so ratios against it read lower with the report: on external wall
time the native arm costs 6.92<!--n:ReportOverhead.reflect_plain/manual_unique.wall_ratio-->×
hand-written code per struct with the report and
7.56<!--n:ReportOverhead.reflect_plain_noreport/manual_unique_noreport.wall_ratio-->×
without it, while its ratio to Boost.PFR is the same either way
(1.00<!--n:ReportOverhead.reflect_plain/pfr.wall_ratio--> and
1.01<!--n:ReportOverhead.reflect_plain_noreport/pfr_noreport.wall_ratio-->).

### 4.2 Per-type cost of the mechanisms (RQ1)

**Table 1.** Front-end cost per struct (scalar corpus, M = 16, FrontendN, N up to 4,000;
session S1).

| Arm | ms per struct | 95% CI |
|-----|--------------:|--------|
| `manual_unique` | 0.23<!--n:FrontendN.manual_unique.slope--> | [0.23, 0.23]<!--ci:FrontendN.manual_unique.slope--> |
| `xmacro_unique` | 0.24<!--n:FrontendN.xmacro_unique.slope--> | [0.24, 0.25]<!--ci:FrontendN.xmacro_unique.slope--> |
| `p1061` | 0.22<!--n:FrontendN.p1061.slope--> | [0.21, 0.22]<!--ci:FrontendN.p1061.slope--> |
| `p1061_visit` | 0.45<!--n:FrontendN.p1061_visit.slope--> | [0.45, 0.46]<!--ci:FrontendN.p1061_visit.slope--> |
| `reflect_plain` | 1.72<!--n:FrontendN.reflect_plain.slope--> | [1.70, 1.73]<!--ci:FrontendN.reflect_plain.slope--> |
| `reflect_visit` | 2.01<!--n:FrontendN.reflect_visit.slope--> | [2.00, 2.02]<!--ci:FrontendN.reflect_visit.slope--> |
| `reflect` | 2.36<!--n:FrontendN.reflect.slope--> | [2.32, 2.37]<!--ci:FrontendN.reflect.slope--> |
| `pfr` | 1.66<!--n:FrontendN.pfr.slope--> | [1.65, 1.67]<!--ci:FrontendN.pfr.slope--> |
| `pfr_native` (code-identical to `pfr`) | 1.77<!--n:FrontendN.pfr_native.slope--> | [1.75, 1.78]<!--ci:FrontendN.pfr_native.slope--> |

Boost.PFR's C++17 path (`pfr_classic`) has no row: its cost is not linear in N (§4.3).
Neither are `manual` and `xmacro`, which share one overloaded name (§4.4). The other rows
pass the linearity check of §3.6. Still, the per-struct cost of the P2996 arms (all in the
span form; the other forms of S3 do not rise, below), of `p1061_visit` and of Boost.PFR
rises with N, so their slopes are averages over the sweep. Inline P1061 and hand-written
code stay flat: 0.20<!--n:FrontendN.p1061.slope0_500--> and
0.21<!--n:FrontendN.p1061.slope2000_4000--> ms per struct over the first 500 and the last
2,000 structs, and 0.22<!--n:FrontendN.manual_unique.slope0_500--> and
0.23<!--n:FrontendN.manual_unique.slope2000_4000--> ms. The native arm's marginal cost
per struct, (cost at N − cost at N = 0) / N, is
1.44<!--n:FrontendN.reflect_plain.per_struct500--> ms at N = 500 and
1.71<!--n:FrontendN.reflect_plain.per_struct4000--> ms at N = 4,000. For Boost.PFR it is
1.44<!--n:FrontendN.pfr.per_struct500--> and 1.65<!--n:FrontendN.pfr.per_struct4000--> ms.
The rise is not specific to P2996: the native arm's upper-half slope is
1.14<!--n:FrontendN.reflect_plain.halves-->× [1.12, 1.17]<!--ci:FrontendN.reflect_plain.halves-->
its lower-half slope, and that of `p1061_visit`
1.23<!--n:FrontendN.p1061_visit.halves-->×. In the span form, the concurrent name-lookup
timer of a whole translation unit grows from
0.12<!--n:FrontendN.reflect_plain.name_lookup1000_s--> s at N = 1,000 to
0.98<!--n:FrontendN.reflect_plain.name_lookup4000_s--> s at 4,000. That is about as much
as the native arm's rise above a constant per-struct cost. GCC 16.2.0 declares the range,
begin and per-element iterator variables of a constant iterating expansion statement
`static` (2 + n of them per expansion over n elements). It registers every block-scope
`static` by a linear scan of one list for the whole translation unit
(`determine_local_discriminator` in `cp/decl.cc`). Each expansion therefore pays for all
those compiled before it. Ordinary block-scope statics show the same quadratic growth
without any reflection, on every GCC release from 11.5 to the current development
branch. This is a GCC compile-time issue, not a property of P2996, reported as PR128928
(reproducers in `Repro/GccLocalStatics`). In S2 the slopes of Table 1 are
1.000<!--n:between.FrontendN.manual_unique-->× (`manual_unique`),
1.009<!--n:between.FrontendN.p1061-->× (`p1061`), 1.002<!--n:between.FrontendN.pfr-->×
(`pfr`), 0.990<!--n:between.FrontendN.reflect_plain-->× (`reflect_plain`) and
0.995<!--n:between.FrontendN.reflect-->× (`reflect`) their S1 values.

**Figure 1** (`Figures/FigureLadder.pdf`). Front-end cost per struct, scalar corpus,
M = 16, session S1, log scale. The P2996 arms use the span form of Listing 1. Each dot is
the least-squares slope of the cell medians
(eleven measured rounds) against N; whiskers are 95% bootstrap intervals and are mostly
narrower than the dot. (a) Job FrontendN, N = 0–4,000: the arms of Table 1, all of which
pass the linearity check of §3.6; `manual`, `xmacro` and Boost.PFR's C++17 path are not
linear in N and are omitted. (b) Job FrontendHeavy, N = 0–200: both paths of reflect-cpp
and Glaze, with the native arm, Boost.PFR and `p1061_visit` as references. The reference
arms cost less per struct in (b) than in (a) because their per-struct cost rises with
the number of types already in the translation unit; ratios are therefore taken within
one panel only.

**Mechanism × API shape.** Here, as in every job but FrontendIdiom, P2996 enumeration
means the span form of Listing 1, and its formulation alone moves its cost by a factor of
about two (S3, below). With the serializer written inline, P2996 enumeration costs
7.96<!--n:FrontendN.reflect_plain/p1061.ratio-->×
[7.83, 8.04]<!--ci:FrontendN.reflect_plain/p1061.ratio--> as much per struct as a P1061
pack (7.20<!--n:FrontendN.reflect_plain/p1061.seg0_500-->× over the first 500 structs,
8.47<!--n:FrontendN.reflect_plain/p1061.seg2000_4000-->× over the last 2,000). Behind a
callback API the ratio is 4.44<!--n:FrontendN.reflect_visit/p1061_visit.ratio-->×
[4.40, 4.48]<!--ci:FrontendN.reflect_visit/p1061_visit.ratio-->. The callback shape itself
costs 1.17<!--n:FrontendN.reflect_visit/reflect_plain.ratio-->× with P2996 and
2.10<!--n:FrontendN.p1061_visit/p1061.ratio-->× with P1061. Boost.PFR builds on the same
P1061 primitive behind the same callback shape, and its own machinery puts it at
3.66<!--n:FrontendN.pfr/p1061_visit.ratio-->×
[3.63, 3.70]<!--ci:FrontendN.pfr/p1061_visit.ratio--> of `p1061_visit`: under
`-std=c++26` its `for_each_field` binds the pack, builds an index sequence of the field
count, binds the pack again and calls, for every field, a dispatcher
(`for_each_field_impl_apply`) that receives the field index as a type (`size_t_<I>`) and
first tests by SFINAE whether the callback also accepts that index.

**Native enumeration against Boost.PFR.** Written inline in the span form, native
enumeration costs about as much per struct as Boost.PFR's `for_each_field`. This parity
describes the choice between an inline native serializer in the span form and Boost.PFR's
visitor, not the two enumeration mechanisms. The slope ratio is
1.04<!--n:FrontendN.reflect_plain/pfr.ratio-->×
[1.02, 1.04]<!--ci:FrontendN.reflect_plain/pfr.ratio-->. The ratio of marginal costs
depends on N, and so does which arm is cheaper:
0.95<!--n:FrontendN.reflect_plain/pfr.point1000-->×
[0.94, 0.97]<!--ci:FrontendN.reflect_plain/pfr.point1000--> at N = 1,000,
0.99<!--n:FrontendN.reflect_plain/pfr.point2000-->×
[0.98, 1.01]<!--ci:FrontendN.reflect_plain/pfr.point2000--> at 2,000 and
1.03<!--n:FrontendN.reflect_plain/pfr.point4000-->×
[1.02, 1.04]<!--ci:FrontendN.reflect_plain/pfr.point4000--> at 4,000. The slope ratio is
0.99<!--n:CompilerN.reflect_plain/pfr.ratio-->× in the CompilerN job (N ≤ 2,000),
0.96<!--n:RichN.reflect_plain/pfr.ratio-->× on the rich corpus and
0.99<!--n:HeteroN.reflect_plain/pfr.ratio-->× on the heterogeneous one
(1.07<!--n:HeteroHeavy.reflect_plain/pfr.ratio-->×
[1.05, 1.09]<!--ci:HeteroHeavy.reflect_plain/pfr.ratio--> over N ≤ 200, HeteroHeavy; §4.6).
All of these differences are about as large as the code-identical pair's below
(1.03<!--n:HeteroN.pfr_native/pfr.ratio-->–1.06<!--n:FrontendN.pfr_native/pfr.ratio-->×)
or smaller. With the API shape matched, native enumeration behind the same callback
(`reflect_visit`) costs 1.21<!--n:FrontendN.reflect_visit/pfr.ratio-->×
[1.20, 1.22]<!--ci:FrontendN.reflect_visit/pfr.ratio--> as much as Boost.PFR per struct
(S2: 1.21<!--n:last.FrontendN.reflect_visit/pfr.ratio-->),
1.14<!--n:RichN.reflect_visit/pfr.ratio-->× on the rich corpus and
1.08<!--n:HeteroN.reflect_visit/pfr.ratio-->× on the heterogeneous graph. On every corpus
this exceeds the code-identical pair's difference, although the native arm also parses
`<meta>`, which that pair suggests is worth a few percent. The 1.21 is the quotient of the
two decompositions above. Behind a callback, P2996 enumeration costs
4.44<!--n:FrontendN.reflect_visit/p1061_visit.ratio-->× P1061's, while Boost.PFR's
machinery costs 3.66<!--n:FrontendN.pfr/p1061_visit.ratio-->× the same primitive. Native
enumeration matches Boost.PFR by being written inline, which avoids the callback shape's
factor of 1.17<!--n:FrontendN.reflect_visit/reflect_plain.ratio-->. Written inline over a
constant array instead of the span, it costs about half as much as Boost.PFR's
`for_each_field` (below), again without matching the API shape.

**Native formulation (S3).** The native arms above enumerate with one form, used in
several of P2996R13's own examples (e.g. its universal formatter): an expansion statement
over the `std::span` that `define_static_array` returns. C++26 makes this an iterating
expansion statement, defined element by element through the span's iterator, and GCC
16.2.0 evaluates it that way. The compiler constant-evaluates a loop over the range to
count its elements, then for each field resolves `begin + i` and its dereference on
`std::span`'s class-type iterator, deduces `auto` and constant-initializes a
`static constexpr` iterator and the member. Over an array, C++26 expands by
destructuring. Session
S3 times the same member query in three other forms, in one job with the span form
(FrontendIdiom, N ≤ 4,000; Figure 2). Per struct, the same expansion statement over a constant array
(`[:reflect_constant_array(...):]`) costs 0.82<!--n:FrontendIdiom.reflect_array.slope-->
against 1.73<!--n:FrontendIdiom.reflect_plain.slope--> ms over the span,
0.47<!--n:FrontendIdiom.reflect_array/reflect_plain.ratio-->×
[0.47, 0.48]<!--ci:FrontendIdiom.reflect_array/reflect_plain.ratio--> (as marginal costs,
0.53<!--n:FrontendIdiom.reflect_array/reflect_plain.point1000-->× at N = 1,000 and
0.48<!--n:FrontendIdiom.reflect_array/reflect_plain.point4000-->× at 4,000, since only the
span form bends). With fixed costs included, a whole translation unit with the array form
takes 0.61<!--n:FrontendIdiom.reflect_array/reflect_plain.total1000-->× the span form's
front-end time at N = 1,000 and
0.50<!--n:FrontendIdiom.reflect_array/reflect_plain.total4000-->× at 4,000. An
index-sequence helper costs
0.93<!--n:FrontendIdiom.reflect_seq.slope--> ms
(0.54<!--n:FrontendIdiom.reflect_seq/reflect_plain.ratio-->×), and reflect-cpp's form, a
`constexpr` P1061 index pack bound through the tuple protocol that C++26 gives
`std::integer_sequence` (P1789R3), 2.02<!--n:FrontendIdiom.reflect_index.slope--> ms
(1.17<!--n:FrontendIdiom.reflect_index/reflect_plain.ratio-->×). That form's
overload-resolution timer covers 54%<!--n:FrontendIdiom.reflect_index.share.overload-->
of its time, consistent with one `get<j>` resolved by argument-dependent lookup per element.

About half of the span form's per-struct cost therefore comes with the span, not the
member query. The contrast also removes the calls that `define_static_array` makes around
`reflect_constant_array` (`type_of`, `is_array_type`, `extract`, `extent` and the `span`
constructor), which we did not time separately. They run once per struct, whereas the
iterating expansion's per-element steps run once per field, so we attribute the difference
mainly to the iterating expansion. The expansion statement as such is not shown to be
costly: the two forms without it differ in direction, and the cheapest of the four forms
is itself an expansion statement, the one over the array
(0.88<!--n:FrontendIdiom.reflect_array/reflect_seq.ratio-->× the helper). With the array
form, inline native enumeration costs 3.77<!--n:FrontendIdiom.reflect_array/p1061.ratio-->×
inline P1061 and 0.49<!--n:FrontendIdiom.reflect_array/pfr.ratio-->× Boost.PFR's callback
`for_each_field` per struct (S3 has no callback-shaped array arm). It adds
0.59<!--n:FrontendIdiom.reflect_array-manual_unique.diff_ms--> ms over hand-written code
and does not rise with N (upper-half / lower-half slope
0.99<!--n:FrontendIdiom.reflect_array.halves-->, against
1.15<!--n:FrontendIdiom.reflect_plain.halves--> over the span), nor do the other two forms
(0.97<!--n:FrontendIdiom.reflect_index.halves--> for the P1061 index pack,
0.98<!--n:FrontendIdiom.reflect_seq.halves--> for the index-sequence helper). The arms
that also run in
FrontendN reproduce their S1 values: 1.73<!--n:FrontendIdiom.reflect_plain.slope--> against
1.72<!--n:FrontendN.reflect_plain.slope--> ms for the span form,
1.68<!--n:FrontendIdiom.pfr.slope--> against 1.66<!--n:FrontendN.pfr.slope--> ms for
Boost.PFR, 0.22<!--n:FrontendIdiom.p1061.slope--> against
0.22<!--n:FrontendN.p1061.slope--> ms for P1061,
0.23<!--n:FrontendIdiom.manual_unique.slope--> against
0.23<!--n:FrontendN.manual_unique.slope--> ms for hand-written code, and
7.97<!--n:FrontendIdiom.reflect_plain/p1061.ratio-->× against
7.96<!--n:FrontendN.reflect_plain/p1061.ratio-->× for native / P1061. S3 is a single
session, so its intervals understate day-to-day variation, which for the slopes timed in
both S1 and S2 had a median of 0.7%<!--n:between.all.median_dev--> and at most
8.8%<!--n:between.all.max_dev--> (§4.6), far below the factor of two between the span and
array forms. S3 timed the formulations at the front end only, on the scalar corpus at
M = 16; every other native number in this paper uses the span form.

**Figure 2** (`Figures/FigureIdiom.pdf`). Front-end cost per struct of four native formulations of the same member query and three reference arms, scalar corpus, M = 16, session S3 (job FrontendIdiom, N = 0–4,000), log scale. Each dot is the least-squares slope of the cell medians (eleven measured rounds) against N; whiskers are 95% bootstrap intervals. The span form is the native arm of every other job.

**The annotation query.** Querying `annotations_of_with_type` on every member makes the
native serializer 1.37<!--n:FrontendN.reflect/reflect_plain.ratio-->×
[1.36, 1.38]<!--ci:FrontendN.reflect/reflect_plain.ratio--> as costly per struct of 16
scalar fields. In this corpus no member is annotated, so the query is pure overhead that
buys the ability to skip annotated fields.

**Where the time goes.** GCC 16 has three kinds of timer. Phases (`phase parsing`,
`phase lang. deferred`, `phase opt and generate`) partition the run. `template
instantiation` and `constant expression evaluation` are stack timers that exclude each
other. `|name lookup` and `|overload resolution` are concurrent timers: they keep running
through the deduction, substitution and instantiation that a lookup or a call triggers,
and so overlap all others. Constant evaluation accounts for
43%<!--n:FrontendN.reflect_plain.share.consteval--> of the native arm's per-struct time and
template instantiation for 46%<!--n:FrontendN.reflect_plain.share.tmpl_inst-->, together
most of it. For Boost.PFR the shares are
1%<!--n:FrontendN.pfr.share.consteval--> and 84%<!--n:FrontendN.pfr.share.tmpl_inst-->,
and for P1061 1%<!--n:FrontendN.p1061.share.consteval--> and
79%<!--n:FrontendN.p1061.share.tmpl_inst-->. Both native shares include the expansion
statement's per-element steps, not only the reflection queries. In S3 the span form spends
46%<!--n:FrontendIdiom.reflect_plain.share.tmpl_inst--> of its
1.73<!--n:FrontendIdiom.reflect_plain.slope--> ms in template instantiation and
43%<!--n:FrontendIdiom.reflect_plain.share.consteval--> in constant evaluation; the array
form spends 35%<!--n:FrontendIdiom.reflect_array.share.tmpl_inst--> and
53%<!--n:FrontendIdiom.reflect_array.share.consteval--> of its
0.82<!--n:FrontendIdiom.reflect_array.slope--> ms. More than half of the difference
between the two forms therefore lies in template instantiation. We did not time the P2996
operations separately.

**Memory** ranks the arms differently from time. Per struct, the compiler allocates
266<!--n:FrontendN.reflect_plain.ggc_kb--> KB of GGC memory for the native arm and its peak
working set grows by 235<!--n:FrontendN.reflect_plain.peak_ws_kb--> KB; for Boost.PFR, at
about the same time per struct, 426<!--n:FrontendN.pfr.ggc_kb--> and
408<!--n:FrontendN.pfr.peak_ws_kb--> KB; for P1061 60<!--n:FrontendN.p1061.ggc_kb--> and
50<!--n:FrontendN.p1061.peak_ws_kb--> KB; and for hand-written code
73<!--n:FrontendN.manual_unique.ggc_kb--> and 60<!--n:FrontendN.manual_unique.peak_ws_kb--> KB.
The annotation query raises the native arm's to 382<!--n:FrontendN.reflect.ggc_kb--> and
333<!--n:FrontendN.reflect.peak_ws_kb--> KB. GGC memory is identical in every round of a
cell, and the medians of the peak working set nearly so: the per-struct intervals of both
are narrower than 0.1 KB.

**Hand-written code** with a distinct name per type is one of the three cheapest arms,
with the P1061 pack and the X-macro with distinct names (Table 1). Per struct, P1061 costs
0.94<!--n:FrontendN.p1061/manual_unique.ratio-->×
[0.92, 0.94]<!--ci:FrontendN.p1061/manual_unique.ratio--> and the X-macro
1.06<!--n:FrontendN.xmacro_unique/manual_unique.ratio-->×
[1.04, 1.06]<!--ci:FrontendN.xmacro_unique/manual_unique.ratio--> as much as the
hand-written arm. We did not measure the instrument's overhead for these two arms; on the
hand-written arm it raises the per-struct wall time by
1.123<!--n:ReportOverhead.manual_unique.wall_slope_ratio-->× (§4.1), more than these
differences, so we read the three arms as level rather than ranked. On the scalar corpus,
native enumeration costs 7.46<!--n:FrontendN.reflect_plain/manual_unique.ratio-->× as much
per struct as hand-written code, a ratio that would be about
9%<!--n:ReportOverhead.reflect_plain/manual_unique.report_bias--> larger without
`-ftime-report` (§4.1), and 10.22<!--n:FrontendN.reflect/manual_unique.ratio-->× with the
annotation query, for which we did not measure the instrument's overhead.

**The code-identical control.** `pfr_native` compiles to the same code as `pfr` (§3.3)
and allocates the same GGC memory per struct (426<!--n:FrontendN.pfr_native.ggc_kb--> KB);
its flag only switches Boost.PFR to reflection-based definitions that `for_each_field`
never instantiates, in headers that include `<meta>`. Yet its per-struct time is
1.06<!--n:FrontendN.pfr_native/pfr.ratio-->×
[1.05, 1.07]<!--ci:FrontendN.pfr_native/pfr.ratio--> that of `pfr`, over the first 500
structs (1.04<!--n:FrontendN.pfr_native/pfr.seg0_500-->×) as over the last 2,000
(1.07<!--n:FrontendN.pfr_native/pfr.seg2000_4000-->×), and the same pooled over both
sessions (1.06<!--n:pooled.FrontendN.pfr_native/pfr.ratio-->×). On the heterogeneous corpus
it is 1.03<!--n:HeteroN.pfr_native/pfr.ratio-->×
[1.01, 1.04]<!--ci:HeteroN.pfr_native/pfr.ratio-->; on the rich corpus, at N ≤ 200, it is
not resolved (0.97<!--n:RichN.pfr_native/pfr.ratio-->×
[0.95, 1.02]<!--ci:RichN.pfr_native/pfr.ratio-->). So what a translation unit parses can
change the per-type cost of unchanged code by a few percent, not only its fixed cost.
The native arms parse `<meta>`; the P1061, hand-written and Boost.PFR arms do not.
Differences of a few percent between them therefore cannot be attributed to the
enumeration mechanism. We did not test whether `<meta>` alone causes the effect.

### 4.3 Library backends (RQ2)

**Table 2.** Same-source backend A/Bs: per-struct front-end cost in ms, previous path /
C++26 path (scalar corpus, M = 16). reflect-cpp and Glaze rows: slopes over N = 0–200
(FrontendHeavy); Boost.PFR rows: marginal cost per struct at the stated N (FrontendN)ᵃ.

| Library | previous path | C++26 path | ratio | 95% CI |
|---------|--------------:|-----------:|------:|--------|
| reflect-cpp | 30.56<!--n:FrontendHeavy.rflcpp.slope--> | 14.66<!--n:FrontendHeavy.rflcpp_native.slope--> | 2.08<!--n:FrontendHeavy.rflcpp/rflcpp_native.ratio--> | [2.06, 2.10]<!--ci:FrontendHeavy.rflcpp/rflcpp_native.ratio--> |
| Glaze | 25.46<!--n:FrontendHeavy.glaze_classic.slope--> | 12.75<!--n:FrontendHeavy.glaze_native.slope--> | 2.00<!--n:FrontendHeavy.glaze_classic/glaze_native.ratio--> | [1.96, 2.01]<!--ci:FrontendHeavy.glaze_classic/glaze_native.ratio--> |
| Boost.PFR, N = 500 | 6.32<!--n:FrontendN.pfr_classic.per_struct500--> | 1.44<!--n:FrontendN.pfr.per_struct500--> | 4.4<!--n:FrontendN.pfr_classic/pfr.point500--> | [4.3, 4.5]<!--ci:FrontendN.pfr_classic/pfr.point500--> |
| Boost.PFR, N = 4,000 | 21.07<!--n:FrontendN.pfr_classic.per_struct4000--> | 1.65<!--n:FrontendN.pfr.per_struct4000--> | 12.8<!--n:FrontendN.pfr_classic/pfr.point4000--> | [12.7, 12.9]<!--ci:FrontendN.pfr_classic/pfr.point4000--> |

ᵃ Boost.PFR's C++17 path is not linear in N, so it has no per-struct slope. Its rows give
the marginal cost per struct at the stated N, (cost at N − cost at N = 0) / N, for both
paths, and their ratio.

**Figure 3** (`Figures/FigureBackends.pdf`). Previous path / C++26 path for each library,
scalar corpus, session S1. (a) M = 16: for reflect-cpp and Glaze the ratio of per-struct
slopes over N = 0–200 (FrontendHeavy, Table 2), for Boost.PFR the ratio of marginal costs
at N = 500 (FrontendN); whiskers are 95% bootstrap intervals and the vertical line marks
a ratio of 1. (b) Field sweep at N = 50 (FrontendM): the ratio of the cost the fields
add, cost at M minus cost at M = 0, with 95% bands; Boost.PFR's C++26 path adds fewer than
ten timer steps at M = 8 and 16, hence its wide band there. Because the field-independent
cost is excluded and N is fixed at 50, the values at M = 16 differ from (a). (c) Boost.PFR's ratio
of marginal costs against N (FrontendN, M = 16).

**Boost.PFR's C++17 path is quadratic in the number of types.** From N = 2,000 to 4,000
its marginal front-end cost multiplies by 3.7<!--n:FrontendN.pfr_classic.doubling-->
(C++26 path: 2.0<!--n:FrontendN.pfr.doubling-->), reaching
84<!--n:FrontendN.pfr_classic.marginal4000_s--> s at N = 4,000, of which the
overload-resolution timer accounts for 87%<!--n:FrontendN.pfr_classic.share4000.overload-->;
its GGC memory grows linearly (1262<!--n:FrontendN.pfr_classic.ggc_kb--> KB per struct), and
the whole translation unit peaks at 5.0<!--n:FrontendN.pfr_classic.peak4000_gb--> GB of
working set at N = 4,000 (C++26 path: 1.6<!--n:FrontendN.pfr.peak4000_gb--> GB). On the rich
corpus, whose sweep ends at N = 200, the curve is still close to a line
(×2.2<!--n:RichN.pfr_classic.doubling--> from N = 100 to 200); on the heterogeneous corpus it
already bends within the sweep (×2.6<!--n:HeteroN.pfr_classic.doubling--> from N = 800 to
1,600; upper-half slope 1.59<!--n:HeteroN.pfr_classic.halves-->×
[1.55, 1.64]<!--ci:HeteroN.pfr_classic.halves--> the lower-half slope, not linear by §3.6).
The quadratic term therefore matters for translation units that reflect many types. A
separate probe (`Harness/pfrprobe.py`; compiles one at a time on the performance cores,
medians of three runs) locates it.

- *Not GCC 16 and not the flag.* The path grows alike on GCC 15.2.0 with `-std=c++20`
  (7<!--n:probe.A.GCC152.cxx20.n1000.total_s-->,
  21<!--n:probe.A.GCC152.cxx20.n2000.total_s--> and
  78<!--n:probe.A.GCC152.cxx20.n4000.total_s--> s at N = 1,000, 2,000 and 4,000), and on
  GCC 16.2.0 with `-std=c++20` and with `-std=c++26`, with and without `-freflection`.
  The overload-resolution timer, which also runs through the deduction and substitution
  that resolution triggers, covers 87%<!--n:probe.A.overload_share4000.min--> to
  89%<!--n:probe.A.overload_share4000.max--> of the time at N = 4,000 in every case.
- *Field counting.* On GCC 16.2.0 with `-std=c++20`, each test calls one piece of the
  library for every struct. Field counting alone (`detail::fields_count`) reproduces the
  growth: its overload-resolution time is
  1.47<!--n:probe.B.fields_count.n500.overload_s-->,
  4.42<!--n:probe.B.fields_count.n1000.overload_s--> and
  15.83<!--n:probe.B.fields_count.n2000.overload_s--> s at N = 500, 1,000 and 2,000,
  against 18.01<!--n:probe.B.for_each_field.n2000.overload_s--> s for the whole
  `for_each_field` at N = 2,000. Binding the fields with the count given
  (`detail::tie_as_tuple`) takes 0.91<!--n:probe.B.tie_given_count.n2000.overload_s--> s at
  N = 2,000.

The library counts the 16 fields with about ten aggregate-initialization probes per type
(§2). Each probe is a function template whose return type is
`std::add_pointer_t<decltype(T{ubiq{I}...})>`, guarded by SFINAE and overloaded with an
rvalue variant. One such probe per type already grows quadratically:
0.30<!--n:probe.B.probe.n500.overload_s-->, 1.05<!--n:probe.B.probe.n1000.overload_s--> and
4.21<!--n:probe.B.probe.n2000.overload_s--> s at N = 500, 1,000 and 2,000; a copy of it
takes 4.15<!--n:probe.B.copy.n2000.overload_s--> s at N = 2,000. Dropping the
`std::add_pointer_t` wrapper from the copy cuts that to
0.97<!--n:probe.B.no_add_pointer.n2000.overload_s--> s, and dropping the rvalue overload and
the guard as well leaves 0.33<!--n:probe.B.bare.n2000.overload_s--> s; both reduced probes
still grow faster than linearly from N = 1,000 to 2,000. We did not identify the cause
inside GCC, and we did not test Clang.

**As fields grow.** The ratio is not a constant of the library. In the field sweep
(N = 50), Glaze's traditional / P2996 ratio is
1.84<!--n:FrontendM.glaze_classic/glaze_native.M8--> at M = 8,
1.85<!--n:FrontendM.glaze_classic/glaze_native.M16--> at 16,
1.49<!--n:FrontendM.glaze_classic/glaze_native.M32--> at 32,
1.05<!--n:FrontendM.glaze_classic/glaze_native.M64--> at 64 and
0.70<!--n:FrontendM.glaze_classic/glaze_native.M128--> at 128 (S2:
0.70<!--n:last.FrontendM.glaze_classic/glaze_native.M128-->); reflect-cpp's is
1.91<!--n:FrontendM.rflcpp/rflcpp_native.M16--> at 16 and
2.51<!--n:FrontendM.rflcpp/rflcpp_native.M128--> at 128; Boost.PFR's lies between
2.86<!--n:FrontendM.pfr_classic/pfr.M64--> (M = 64) and
3.28<!--n:FrontendM.pfr_classic/pfr.M128--> (M = 128) from M = 32 on, with
2.90<!--n:FrontendM.pfr_classic/pfr.M32--> at 32. From M = 64 to 128, the cost the fields
add grows 3.46<!--n:FrontendM.glaze_native.doubling-->× for Glaze's P2996 backend against
2.31<!--n:FrontendM.glaze_classic.doubling-->× for its traditional backend. At M = 128
the P2996 backend's whole translation unit (50 structs) peaks at
5.0<!--n:FrontendM.glaze_native.peak128_gb--> GB of working set against
3.0<!--n:FrontendM.glaze_classic.peak128_gb--> GB, so memory reverses with time. A mechanism
consistent with Glaze's trend (a hypothesis we did not isolate): at v9.1.0 its P2996
backend calls `nonstatic_data_members_of` once per member index, both for access
(`member_info_at<T, I>`) and for names (`get_member_name_p2996<T, I>`), so its per-struct
reflection work grows faster than linearly in M. Glaze's main branch has since changed
this code (PR #3112, after v9.1.0), so the trend is a property of the pinned release.
The traditional backend is superlinear in M as well, because its member count probes
aggregate initialization with 1, 2, …, M + 1 initializers (§2). The hypothesis therefore
concerns why the P2996 backend's curve bends more. reflect-cpp's C++20 path reaches
8.4<!--n:FrontendM.rflcpp.peak128_gb--> GB at M = 128
(C++26 path: 3.1<!--n:FrontendM.rflcpp_native.peak128_gb--> GB). At M = 16 the field-sweep
ratios lie below Table 2's, which are ratios of slopes over N ≤ 200. The backend ratio
also depends on N: in FrontendHeavy the ratio of marginal costs is
1.86<!--n:FrontendHeavy.glaze_classic/glaze_native.point50--> at N = 50 and
1.98<!--n:FrontendHeavy.glaze_classic/glaze_native.point200--> at N = 200 for Glaze, and
1.81<!--n:FrontendHeavy.rflcpp/rflcpp_native.point50--> and
2.05<!--n:FrontendHeavy.rflcpp/rflcpp_native.point200--> for reflect-cpp.

**Libraries against native enumeration.** In the same job (FrontendHeavy, N ≤ 200, where
the native arm costs 1.39<!--n:FrontendHeavy.reflect_plain.slope--> ms per struct against
Table 1's 1.72<!--n:FrontendN.reflect_plain.slope--> ms over N ≤ 4,000), reflect-cpp's C++26
path costs 10.55<!--n:FrontendHeavy.rflcpp_native/reflect_plain.ratio-->× and Glaze's P2996
backend 9.17<!--n:FrontendHeavy.glaze_native/reflect_plain.ratio-->× the native arm per
struct. Both libraries compute field names on the path we call although our serializer
ignores them — Glaze's `for_each_field` reads `reflect<T>::size`, which is the size of
`member_names<T>`, and reflect-cpp's `to_view` builds a named tuple — so these ratios
measure each library's per-type work for its field visitor, not an intrinsic cost of
library-based reflection. Per struct, the C++26 paths of Glaze and reflect-cpp also
roughly halve the growth of the compiler's peak working set:
2,494<!--n:FrontendHeavy.glaze_native.peak_ws_kb-->
against 4,287<!--n:FrontendHeavy.glaze_classic.peak_ws_kb--> KB for Glaze and
2,846<!--n:FrontendHeavy.rflcpp_native.peak_ws_kb--> against
6,228<!--n:FrontendHeavy.rflcpp.peak_ws_kb--> KB for reflect-cpp.

**Whole translation units.** Per-type ratios exclude fixed costs. In a whole translation
unit, switching to the C++26 path saves less, because the headers of Glaze and reflect-cpp
are paid once: 1.26<!--n:FrontendHeavy.glaze_classic/glaze_native.total50-->× (Glaze) and
1.47<!--n:FrontendHeavy.rflcpp/rflcpp_native.total50-->× (reflect-cpp) of the front-end time
with 50 types, and 1.61<!--n:FrontendHeavy.glaze_classic/glaze_native.total200-->× and
1.84<!--n:FrontendHeavy.rflcpp/rflcpp_native.total200-->× with 200 types (Table 3).

**Table 3.** Whole translation unit at the front end (scalar corpus, M = 16, FrontendHeavy,
session S1): the compiler's TOTAL and its peak working set, without structs and with 200.

| Arm | TOTAL, N = 0 (s) | TOTAL, N = 200 (s) | peak, N = 0 (MB) | peak, N = 200 (MB) |
|-----|-----:|-----:|-----:|-----:|
| `reflect_plain` | 0.31<!--n:FrontendHeavy.reflect_plain.total0_s--> | 0.59<!--n:FrontendHeavy.reflect_plain.total200_s--> | 93<!--n:FrontendHeavy.reflect_plain.peak0_mb--> | 140<!--n:FrontendHeavy.reflect_plain.peak200_mb--> |
| `pfr` | 0.28<!--n:FrontendHeavy.pfr.total0_s--> | 0.56<!--n:FrontendHeavy.pfr.total200_s--> | 86<!--n:FrontendHeavy.pfr.peak0_mb--> | 163<!--n:FrontendHeavy.pfr.peak200_mb--> |
| `rflcpp` | 0.90<!--n:FrontendHeavy.rflcpp.total0_s--> | 7.10<!--n:FrontendHeavy.rflcpp.total200_s--> | 252<!--n:FrontendHeavy.rflcpp.peak0_mb--> | 1480<!--n:FrontendHeavy.rflcpp.peak200_mb--> |
| `rflcpp_native` | 0.83<!--n:FrontendHeavy.rflcpp_native.total0_s--> | 3.86<!--n:FrontendHeavy.rflcpp_native.total200_s--> | 209<!--n:FrontendHeavy.rflcpp_native.peak0_mb--> | 783<!--n:FrontendHeavy.rflcpp_native.peak200_mb--> |
| `glaze_classic` | 1.54<!--n:FrontendHeavy.glaze_classic.total0_s--> | 6.65<!--n:FrontendHeavy.glaze_classic.total200_s--> | 473<!--n:FrontendHeavy.glaze_classic.peak0_mb--> | 1301<!--n:FrontendHeavy.glaze_classic.peak200_mb--> |
| `glaze_native` | 1.55<!--n:FrontendHeavy.glaze_native.total0_s--> | 4.13<!--n:FrontendHeavy.glaze_native.total200_s--> | 483<!--n:FrontendHeavy.glaze_native.peak0_mb--> | 962<!--n:FrontendHeavy.glaze_native.peak200_mb--> |

### 4.4 Per-type serializer idioms and overload sets (RQ3)

With one overloaded name per type, hand-written serializers stop being linear: from
N = 2,000 to 4,000 the marginal cost of `manual` multiplies by
4.7<!--n:FrontendN.manual.doubling--> (distinct names:
2.0<!--n:FrontendN.manual_unique.doubling-->), reaching
26.6<!--n:FrontendN.manual.marginal4000_s--> s at N = 4,000, of which the compiler's
overload-resolution timer accounts for 94%<!--n:FrontendN.manual.share4000.overload-->.
Its marginal cost is 0.68<!--n:FrontendN.manual/reflect.point1000-->× native reflection's at
N = 1,000 and 1.33<!--n:FrontendN.manual/reflect.point2000-->× at N = 2,000 (against P2996
without the annotation query: 0.92<!--n:FrontendN.manual/reflect_plain.point1000-->× and
1.79<!--n:FrontendN.manual/reflect_plain.point2000-->×), so it overtakes native reflection
in the span form between N = 1,000 and 2,000. We do not narrow the crossing further: the measured growth
exceeds a quadratic, so a quadratic model would misplace it. The X-macro with one overloaded name behaves alike
(×4.7<!--n:FrontendN.xmacro.doubling--> per doubling).

**Table 4.** Ten customization idioms, K = C = N (OverloadN): marginal front-end time at
N = 1,000, its growth from N = 500 to 1,000 (2 = linear, 4 = quadratic), and its ratio to
distinct names at N = 1,000 (for the idioms that share one lookup set, that ratio itself
grows with N).

| Idiom | Form documented by | s at N = 1,000 | × per doubling | ÷ distinct names at N = 1,000 |
|-------|--------------------|---------------:|---------------:|-----------------:|
| free function, qualified call | — | 1.42<!--n:OverloadN.ovl_flat.marginal1000_s--> | 3.5<!--n:OverloadN.ovl_flat.doubling--> | 5.92<!--n:OverloadN.ovl_flat/ovl_unique.ratio1000--> |
| free function, ADL, called directly | declared like nlohmann `to_json`, Boost.JSON `tag_invoke`, fmt `format_as` | 1.41<!--n:OverloadN.ovl_adl.marginal1000_s--> | 3.5<!--n:OverloadN.ovl_adl.doubling--> | 5.88<!--n:OverloadN.ovl_adl/ovl_unique.ratio1000--> |
| free function, ADL from a library dispatch template | the call shape of nlohmann, Boost.JSON, fmt | 1.48<!--n:OverloadN.ovl_adl_template.marginal1000_s--> | 3.5<!--n:OverloadN.ovl_adl_template.doubling--> | 6.17<!--n:OverloadN.ovl_adl_template/ovl_unique.ratio1000--> |
| function template guarded by `enable_if` (SFINAE), ADL | nlohmann v3.12 `NON_INTRUSIVE` | 4.97<!--n:OverloadN.ovl_constrained.marginal1000_s--> | 4.0<!--n:OverloadN.ovl_constrained.doubling--> | 20.71<!--n:OverloadN.ovl_constrained/ovl_unique.ratio1000--> |
| `serialize(Archive&, T&, unsigned)` template | Boost.Serialization, cereal external | 1.80<!--n:OverloadN.ovl_archive.marginal1000_s--> | 3.6<!--n:OverloadN.ovl_archive.doubling--> | 7.50<!--n:OverloadN.ovl_archive/ovl_unique.ratio1000--> |
| one namespace per type, ADL | — | 0.25<!--n:OverloadN.ovl_adl_per_ns.marginal1000_s--> | 2.1<!--n:OverloadN.ovl_adl_per_ns.doubling--> | 1.04<!--n:OverloadN.ovl_adl_per_ns/ovl_unique.ratio1000--> |
| hidden friend (non-template) | `BOOST_DESCRIBE_CLASS`; nlohmann v3.12 `INTRUSIVE` declares an `enable_if`-guarded friend template | 0.29<!--n:OverloadN.ovl_hidden_friend.marginal1000_s--> | 2.2<!--n:OverloadN.ovl_hidden_friend.doubling--> | 1.21<!--n:OverloadN.ovl_hidden_friend/ovl_unique.ratio1000--> |
| member function | cereal internal, protobuf | 0.26<!--n:OverloadN.ovl_member.marginal1000_s--> | 2.0<!--n:OverloadN.ovl_member.doubling--> | 1.08<!--n:OverloadN.ovl_member/ovl_unique.ratio1000--> |
| class-template specialization | `glz::meta`, `fmt::formatter` | 0.26<!--n:OverloadN.ovl_specialization.marginal1000_s--> | 2.2<!--n:OverloadN.ovl_specialization.doubling--> | 1.08<!--n:OverloadN.ovl_specialization/ovl_unique.ratio1000--> |
| distinct names | — | 0.24<!--n:OverloadN.ovl_unique.marginal1000_s--> | 2.0<!--n:OverloadN.ovl_unique.doubling--> | 1 |

Of the idioms that avoid a shared lookup set, only the hidden friend has a growth per
doubling whose interval excludes 2 (2.2<!--n:OverloadN.ovl_hidden_friend.doubling-->
[2.1, 2.3]<!--ci:OverloadN.ovl_hidden_friend.doubling-->); at N = 1,000 it costs
1.21<!--n:OverloadN.ovl_hidden_friend/ovl_unique.ratio1000-->×
[1.16, 1.27]<!--ci:OverloadN.ovl_hidden_friend/ovl_unique.ratio1000--> as much as distinct
names, far below the idioms that share one set.

The costliest idiom is the function template guarded by `enable_if`, the declaration
form of nlohmann::json v3.12's `NON_INTRUSIVE` macro. It costs far more than the
`serialize` template, which is a function template as well but has no guard (Table 4).
At N = 1,000 the overload-resolution timer, which also runs through the template argument
deduction and substitution that resolution triggers, covers
93%<!--n:OverloadN.ovl_constrained.share1000.overload--> of its marginal time, template
instantiation 26%<!--n:OverloadN.ovl_constrained.share1000.tmpl_inst--> and constant
evaluation 10%<!--n:OverloadN.ovl_constrained.share1000.consteval--> (plain free
functions: 82%<!--n:OverloadN.ovl_flat.share1000.overload-->,
1%<!--n:OverloadN.ovl_flat.share1000.tmpl_inst--> and
0%<!--n:OverloadN.ovl_flat.share1000.consteval-->), and its GGC memory grows by
815<!--n:OverloadN.ovl_constrained.ggc1000_mb--> MB against
135<!--n:OverloadN.ovl_flat.ggc1000_mb--> MB for plain free functions. We did not isolate
which step of resolving a guarded candidate costs the most.

**Figure 4** (`Figures/FigureOverload.pdf`). Front-end time of the per-type serializer
idioms, scalar corpus, M = 16, session S1; medians over eleven measured rounds, no
intervals drawn. (a) OverloadN, K = C = N: marginal time, cost at N minus cost at N = 0,
for the ten idioms of Table 4. The five idioms whose marginal time at least triples from
N = 500 to 1,000 are drawn in color; the qualified free-function call, the direct ADL
call and ADL from a dispatch template lie within one 10 ms timer step of each other at
N = 250 and within 5% at N = 500 and 1,000, and overlap. The other
five idioms are gray. (b) OverloadC, K = 2,000 overloads, every type already called once:
the time added by call sites, cost at C minus cost at C = 0.

**Call sites and candidates.** At a fixed set of K = 2,000 overloads, with every type
already called once outside the swept calls (so serializer bodies are instantiated
regardless of C), each further call site costs 2.58<!--n:OverloadC.ovl_flat.slope--> ms
with free functions and 3.56<!--n:OverloadC.ovl_archive.slope--> ms with `serialize`
templates, against 0.02<!--n:OverloadC.ovl_unique.slope--> ms with distinct names. At a
fixed C = 500 call sites the cost per further overload rises with K: from
0.84<!--n:OverloadK.ovl_flat.slope500_1000--> ms (K = 500–1,000) to
1.46<!--n:OverloadK.ovl_flat.slope2000_4000--> ms (K = 2,000–4,000) with free functions and
from 0.96<!--n:OverloadK.ovl_archive.slope500_1000--> to
1.67<!--n:OverloadK.ovl_archive.slope2000_4000--> ms with `serialize` templates, against
0.22<!--n:OverloadK.ovl_unique.slope500_1000--> and
0.23<!--n:OverloadK.ovl_unique.slope2000_4000--> ms with distinct names. The cost therefore
grows in proportion to call sites and faster than linearly with the number of candidates
in one lookup set; it is not a property of hand-written code or of the number of types
alone. A library that makes the unqualified call inside its own dispatch template
resolves it once per type, when the template is instantiated, so it pays per type, not
per call site: with every type already instantiated, each further call site costs
0.03<!--n:OverloadC.ovl_adl_template.slope--> ms
[0.01, 0.06]<!--ci:OverloadC.ovl_adl_template.slope-->, about as little as with distinct
names.

### 4.5 Totals at -O2 (RQ4)

With optimization and code generation, several totals are not linear in N (§3.6), so we
compare marginal costs at fixed N. At N = 400 native enumeration's marginal cost is
0.61<!--n:FullN.reflect_plain/pfr.point400-->×
[0.60, 0.61]<!--ci:FullN.reflect_plain/pfr.point400--> Boost.PFR's (S2:
0.61<!--n:last.FullN.reflect_plain/pfr.point400-->) and
1.21<!--n:FullN.reflect_plain/p1061.point400-->× P1061's (S2:
1.22<!--n:last.FullN.reflect_plain/p1061.point400-->), against
7.96<!--n:FrontendN.reflect_plain/p1061.ratio-->× P1061's at the front end. Between the
inline mechanisms the back end dilutes the front-end difference, because GCC's
optimization-and-generation phase takes the same time for every inline arm. Over N = 0 at
N = 400 it takes 2.16<!--n:FullN.manual_unique.optgen400_s--> s for hand-written code,
2.19<!--n:FullN.xmacro_unique.optgen400_s--> for the X-macro,
2.19<!--n:FullN.p1061.optgen400_s--> for P1061, and
2.18<!--n:FullN.reflect_plain.optgen400_s--> and 2.16<!--n:FullN.reflect.optgen400_s--> s
for native enumeration without and with the annotation query. The two callback arms match
each other: 3.12<!--n:FullN.p1061_visit.optgen400_s--> and
3.14<!--n:FullN.reflect_visit.optgen400_s--> s. Boost.PFR takes
3.97<!--n:FullN.pfr.optgen400_s--> s and its C++17 path
5.36<!--n:FullN.pfr_classic.optgen400_s--> s. Equal optimizer time is what one would expect
if the inlined code is equivalent; we did not compare the intermediate code. Against
Boost.PFR the back end creates a difference instead. Outside the optimizer the two cost
about the same, 0.58<!--n:FullN.reflect_plain.nonopt400_s--> and
0.54<!--n:FullN.pfr.nonopt400_s--> s over N = 0 at N = 400, but the optimizer spends
3.97<!--n:FullN.pfr.optgen400_s--> s on Boost.PFR against
2.18<!--n:FullN.reflect_plain.optgen400_s--> s on the native arm. About half of that
optimizer difference comes with the callback shape, which costs the optimizer the same with
P2996 and with P1061 (3.14<!--n:FullN.reflect_visit.optgen400_s--> and
3.12<!--n:FullN.p1061_visit.optgen400_s--> s). Behind the same callback API native
enumeration costs 0.85<!--n:FullN.reflect_visit/pfr.point400-->×
[0.83, 0.85]<!--ci:FullN.reflect_visit/pfr.point400--> Boost.PFR's (S2:
0.84<!--n:last.FullN.reflect_visit/pfr.point400-->). The callback shape alone multiplies the
native arm's marginal cost by 1.38<!--n:FullN.reflect_visit/reflect_plain.point400-->. Most
of the inline native arm's advantage at `-O2` therefore comes from its API shape, not from
the enumeration mechanism. The rest is consistent with Boost.PFR's per-field dispatcher
(§4.2), one specialization per field index for the optimizer to inline. This is an
inference from the source, as we did not inspect the intermediate code.

These ratios move with N, because the optimizer's cost per struct is not constant: in
both sessions, the cell at N = 100 of every light arm in FullN except Boost.PFR's C++17
path lies above the line through the arm's other cells. Native / Boost.PFR is
0.68<!--n:FullN.reflect_plain/pfr.point50-->, 0.79<!--n:FullN.reflect_plain/pfr.point100-->,
0.63<!--n:FullN.reflect_plain/pfr.point200--> and 0.61 at N = 50, 100, 200 and 400 — below
1 at every N — and native / P1061 1.19<!--n:FullN.reflect_plain/p1061.point50-->,
1.12<!--n:FullN.reflect_plain/p1061.point100-->,
1.23<!--n:FullN.reflect_plain/p1061.point200--> and 1.21. Boost.PFR's C++17 path costs
1.73<!--n:FullN.pfr_classic/pfr.point400-->× its C++26 path at N = 400
(1.39<!--n:FullN.pfr_classic/pfr.point100-->–2.45<!--n:FullN.pfr_classic/pfr.point50-->× over
N = 50–400); the annotation-querying native arm costs
1.31<!--n:FullN.reflect/manual_unique.point400-->× hand-written code with distinct names, and
one overloaded name costs 1.08<!--n:FullN.manual/manual_unique.point400-->× distinct names.
With one function per call site the annotation-querying arm's ratio to Boost.PFR is
0.73<!--n:FullN.reflect_split/pfr_split.point400-->× (against
0.65<!--n:FullN.reflect/pfr.point400-->× in one function), so the benchmark's layout lowers
it, in the native arm's favor, but does not change its direction. For the libraries, Glaze's traditional / P2996
ratio is 1.27<!--n:FullHeavy.glaze_classic/glaze_native.point25-->,
1.36<!--n:FullHeavy.glaze_classic/glaze_native.point50--> and
1.48<!--n:FullHeavy.glaze_classic/glaze_native.point100--> at N = 25, 50 and 100, and
reflect-cpp's 1.25<!--n:FullHeavy.rflcpp/rflcpp_native.point25-->,
1.50<!--n:FullHeavy.rflcpp/rflcpp_native.point50--> and
1.64<!--n:FullHeavy.rflcpp/rflcpp_native.point100--> — still rising at the end of the sweep,
against 2.00<!--n:FrontendHeavy.glaze_classic/glaze_native.ratio--> and
2.08<!--n:FrontendHeavy.rflcpp/rflcpp_native.ratio--> at the front end.

**Figure 5** (`Figures/FigureFull.pdf`). Cost per struct at `-O2`, scalar corpus, M = 16,
session S1, log scale: the marginal cost at the largest N divided by N, not a slope,
because several `-O2` curves are not linear (§3.6); whiskers are 95% bootstrap intervals.
The P2996 arms use the span form of Listing 1. (a) FullN at N = 400: the light arms, including Boost.PFR's C++17 path (`manual` and the
`*_split` controls omitted). (b) FullHeavy at N = 100: both paths of reflect-cpp and
Glaze, with the native arm, Boost.PFR and `p1061_visit` as references. At N = 100 the
light arms cost more per struct than at N = 400 (in FullN their cells at N = 100 lie above
the line through their other cells, §4.5), and the libraries' cost per struct still falls
with N.

### 4.6 Richer corpora, sessions and compiler versions (RQ4)

**Richer corpora.** On strings and containers (rich corpus), native enumeration and
Boost.PFR again cost about the same: 0.96<!--n:RichN.reflect_plain/pfr.ratio-->×
[0.95, 1.03]<!--ci:RichN.reflect_plain/pfr.ratio-->. Here each library's C++26 path stays
cheaper than its previous path: Glaze by 2.06<!--n:RichN.glaze_classic/glaze_native.ratio-->×,
reflect-cpp by 2.20<!--n:RichN.rflcpp/rflcpp_native.ratio-->× and Boost.PFR by
4.91<!--n:RichN.pfr_classic/pfr.ratio-->× (its C++17 path is still close to a line over
N ≤ 200, §4.3). On the heterogeneous type graph (varied field counts, enums, nesting,
vectors and optionals of structs), native enumeration costs
0.99<!--n:HeteroN.reflect_plain/pfr.ratio-->× Boost.PFR over N ≤ 1,600 (HeteroN) and
1.07<!--n:HeteroHeavy.reflect_plain/pfr.ratio-->× over N ≤ 200 (HeteroHeavy). Against
P1061 it costs 1.55<!--n:HeteroN.reflect_plain/p1061.ratio-->× (scalar corpus:
7.96<!--n:FrontendN.reflect_plain/p1061.ratio-->×). This ratio falls because the graph
adds a per-struct cost of similar size to every arm. Hand-written code costs
1.98<!--n:HeteroN.manual_unique.slope--> ms per struct, against
0.23<!--n:FrontendN.manual_unique.slope--> ms on the scalar corpus; P1061
2.08<!--n:HeteroN.p1061.slope--> against 0.22<!--n:FrontendN.p1061.slope--> ms; native
enumeration 3.23<!--n:HeteroN.reflect_plain.slope--> against
1.72<!--n:FrontendN.reflect_plain.slope--> ms. The absolute increment of native enumeration
over hand-written code changes little across corpora:
1.49<!--n:FrontendN.reflect_plain-manual_unique.diff_ms--> ms per struct on the scalar
corpus, 1.21<!--n:RichN.reflect_plain-manual_unique.diff_ms--> ms on the rich corpus and
1.25<!--n:HeteroN.reflect_plain-manual_unique.diff_ms--> ms on the heterogeneous graph.
Yet the ratio to hand-written code falls from
7.46<!--n:FrontendN.reflect_plain/manual_unique.ratio-->× to
5.17<!--n:RichN.reflect_plain/manual_unique.ratio-->× and
1.64<!--n:HeteroN.reflect_plain/manual_unique.ratio-->×. The libraries' C++26 paths stay
cheaper on this graph, by different margins: Glaze's backend ratio is
1.82<!--n:HeteroHeavy.glaze_classic/glaze_native.ratio-->, reflect-cpp's only
1.21<!--n:HeteroHeavy.rflcpp/rflcpp_native.ratio-->×
[1.20, 1.22]<!--ci:HeteroHeavy.rflcpp/rflcpp_native.ratio-->. Boost.PFR's C++17 path costs
4.37<!--n:HeteroN.pfr_classic/pfr.point1600-->× its C++26 path at N = 1,600. On this graph
reflect-cpp's C++26 path costs 77.09<!--n:HeteroHeavy.rflcpp_native.slope--> ms per struct,
against 14.66<!--n:FrontendHeavy.rflcpp_native.slope--> ms on the scalar corpus (Glaze's
P2996 backend: 11.17<!--n:HeteroHeavy.glaze_native.slope--> ms). We did not isolate which
feature of the graph drives reflect-cpp's cost.

**GCC 16.1.0 against 16.2.0** (paired, same rounds). GCC 16.2.0 is faster on every arm
that both versions compiled with `-freflection`, but by different factors, so comparisons
between mechanisms depend on the version. In CompilerN (N ≤ 2,000), GCC 16.1.0 costs
1.124<!--n:CompilerN.reflect_plain@GCC161/reflect_plain.ratio-->× GCC 16.2.0 per struct on
the native arm, 1.995<!--n:CompilerN.p1061@GCC161/p1061.ratio-->× on P1061,
1.550<!--n:CompilerN.pfr@GCC161/pfr.ratio-->× on Boost.PFR and
1.748<!--n:CompilerN.manual_unique@GCC161/manual_unique.ratio-->× on hand-written code. On the
libraries (CompilerHeavy, N ≤ 200) the difference is smaller:
1.102<!--n:CompilerHeavy.glaze_native@GCC161/glaze_native.ratio-->× on Glaze's P2996 backend,
1.088<!--n:CompilerHeavy.glaze_classic@GCC161/glaze_classic.ratio-->× on its traditional
backend, 1.065<!--n:CompilerHeavy.rflcpp_native@GCC161/rflcpp_native.ratio-->× on
reflect-cpp's C++26 path and 1.036<!--n:CompilerHeavy.rflcpp@GCC161/rflcpp.ratio-->× on its
C++20 path. In CompilerHeavy, where the libraries and the native arm share rounds, the
native arm's ratio is 1.247<!--n:CompilerHeavy.reflect_plain@GCC161/reflect_plain.ratio-->×
[1.212, 1.304]<!--ci:CompilerHeavy.reflect_plain@GCC161/reflect_plain.ratio-->, above every
library's, against 1.124<!--n:CompilerN.reflect_plain@GCC161/reflect_plain.ratio-->×
(above) in CompilerN, so the native arm's version ratio depends on the sweep. In CompilerN,
native enumeration costs
0.71<!--n:CompilerN.reflect_plain@GCC161/pfr@GCC161.ratio-->× Boost.PFR,
4.16<!--n:CompilerN.reflect_plain@GCC161/p1061@GCC161.ratio-->× P1061 and
4.44<!--n:CompilerN.reflect_plain@GCC161/manual_unique@GCC161.ratio-->× hand-written code per
struct on GCC 16.1.0, against 0.99<!--n:CompilerN.reflect_plain/pfr.ratio-->×,
7.39<!--n:CompilerN.reflect_plain/p1061.ratio-->× and
6.91<!--n:CompilerN.reflect_plain/manual_unique.ratio-->× on GCC 16.2.0. The annotation
factor (1.33<!--n:CompilerN.reflect@GCC161/reflect_plain@GCC161.ratio-->× and
1.33<!--n:CompilerN.reflect/reflect_plain.ratio-->×) and the library backend A/Bs barely
move: Glaze's ratio is
1.93<!--n:CompilerHeavy.glaze_classic@GCC161/glaze_native@GCC161.ratio--> on GCC 16.1.0 and
1.95<!--n:CompilerHeavy.glaze_classic/glaze_native.ratio--> on 16.2.0, reflect-cpp's
1.97<!--n:CompilerHeavy.rflcpp@GCC161/rflcpp_native@GCC161.ratio--> and
2.03<!--n:CompilerHeavy.rflcpp/rflcpp_native.ratio-->. For Boost.PFR and P1061 the
version difference appears only with `-freflection`. Compiled without it, the two versions
cost the same per struct (GCC 16.1.0 / 16.2.0:
1.000<!--n:CompilerFlag.pfr_noflag@GCC161/pfr_noflag.ratio--> and
0.990<!--n:CompilerFlag.p1061_noflag@GCC161/p1061_noflag.ratio-->). In the same rounds the
flag costs 1.703<!--n:CompilerFlag.pfr@GCC161.flag_slope_ratio--> on Boost.PFR and
2.578<!--n:CompilerFlag.p1061@GCC161.flag_slope_ratio--> on P1061 with GCC 16.1.0, against
1.092<!--n:CompilerFlag.pfr.flag_slope_ratio--> and
1.264<!--n:CompilerFlag.p1061.flag_slope_ratio--> with GCC 16.2.0. Hand-written code was not
compiled without the flag on GCC 16.1.0. We did not identify which change in GCC 16.2.0 is
responsible. GCC's C++ front-end ChangeLog lists two changes to the check for
consteval-only types between the releases, PR125179 and PR125280.

**Sessions.** S2 ran the same plan with the same compilers and code on a different day.
For the per-type slopes behind the headline numbers the S2/S1 ratio lies between
0.972<!--n:between.headline.min--> (P1061 on GCC 16.1.0, CompilerFlag) and
1.020<!--n:between.headline.max--> (Boost.PFR, FlagCost); in S2 the flag costs P1061
2.48<!--n:last.CompilerFlag.p1061@GCC161.flag_slope_ratio-->× on GCC 16.1.0, against
2.578<!--n:CompilerFlag.p1061@GCC161.flag_slope_ratio-->× in S1. Across all
102<!--n:between.all.n--> per-arm slopes of the plan that pass the linearity check and rise
by at least ten timer steps (the 96<!--n:S1.sens15.n--> of §3.5 and the six external
wall-time slopes of ReportOverhead), the median difference between the sessions is
0.7%<!--n:between.all.median_dev-->, 90% differ by at most
2.5%<!--n:between.all.p90_dev-->, and the largest is
8.8%<!--n:between.all.max_dev--> (the native arm's per-field slope in the field sweep,
1.088<!--n:between.FrontendM.reflect_plain-->
[1.066, 1.140]<!--ci:between.FrontendM.reflect_plain-->; no headline number uses that
slope). The within-session intervals do not cover the difference between the sessions:
11<!--n:between.all.excl1--> of those 102 S2/S1 ratios have an interval that excludes 1,
where about five would if the intervals covered it. Two sessions cannot tell whether this
is variation between days or under-coverage of percentile intervals from eleven rounds;
either way, differences of a few percent between arms should be read against both
sessions, not against one interval. The
headlines that are not slopes reproduce as well: in S2, Boost.PFR's C++17 / C++26 ratio is
4.5<!--n:last.FrontendN.pfr_classic/pfr.point500--> at N = 500 and
12.8<!--n:last.FrontendN.pfr_classic/pfr.point4000--> at N = 4,000, and Glaze's ratio at
M = 128 is 0.70<!--n:last.FrontendM.glaze_classic/glaze_native.M128-->. Native
enumeration's ratio to Boost.PFR at M = 128 does not reproduce
(0.80<!--n:FrontendM.reflect_plain/pfr.M128--> in S1,
0.89<!--n:last.FrontendM.reflect_plain/pfr.M128--> in S2), and we do not use it. Pooled over
both sessions, the main ratios are 7.88<!--n:pooled.FrontendN.reflect_plain/p1061.ratio-->
(native / P1061), 1.03<!--n:pooled.FrontendN.reflect_plain/pfr.ratio--> (native /
Boost.PFR), 1.37<!--n:pooled.FrontendN.reflect/reflect_plain.ratio--> (the annotation query),
1.99<!--n:pooled.FrontendHeavy.glaze_classic/glaze_native.ratio--> (Glaze) and
2.08<!--n:pooled.FrontendHeavy.rflcpp/rflcpp_native.ratio--> (reflect-cpp).

### 4.7 Maintainability (RQ5)

Per-type source is an analytic count, not a measurement. With 16 fields a hand-written
serializer is 19<!--n:loc.manual.per_type_lines--> lines per type and an X-macro field
list 18<!--n:loc.xmacro.per_type_lines--> (one field per line): both name every field
once per type, so both grow as O(N·M), while the P2996, P1061 and library arms need no
per-type source. Their one-off generic code is 28<!--n:loc.reflect_plain.fixed_lines-->
lines for the native serializer (42<!--n:loc.reflect.fixed_lines--> with the annotation
query and its tag type), 21<!--n:loc.p1061.fixed_lines--> for P1061, and
21<!--n:loc.pfr.fixed_lines--> for each library adapter, excluding the libraries
themselves; the X-macro's shared code is 25<!--n:loc.xmacro.fixed_lines--> lines.

## 5. Related Work

**Native reflection alone.** Romeo (2026a) times native P2996 on GCC 16 (prerelease,
hyperfine, single translation units compiled and linked at `-O0`): including `<meta>`
costs about 155 ms on a release build, and each reflected type 1.1–1.7 ms. His first
numbers came from an assertion-enabled compiler; the release rebuild was about 20–50%
faster depending on the row. His follow-up (2026b) compares reflection with an enum library and
X-macros for enum-to-string on GCC 16.1.1, where `<meta>` dominates. Neither compares
library or hand-written field enumeration, and both include the fixed `<meta>` cost in
the per-TU totals; our per-type numbers exclude it by construction, and our
30<!--n:FrontendN.fixed.meta_ms--> ms for `<meta>` (§4.1) is its cost over a translation unit that already includes `<string>`,
`<vector>` and `<optional>`, not over an empty one.

**Concurrent measurements.** The field-reflection library (Matsuda, 2026; table in its
README since 2026-10-12) switches to a `std::meta` backend on GCC 16 with
`-std=c++26 -freflection` and reports the compile time added per 8-field struct visited
with names (slope between 10 and 200 types in one translation unit, `-c -O0`, best of 3):
20 ms for its C++26 backend against 18 ms for Boost.PFR's `for_each_field_with_name` on
GCC 16, and 23 ms for its C++20 backend against 22 ms for Boost.PFR on GCC 15. Its two
backends are timed on different compilers, without intervals, P1061, hand-written or
macro baselines. mp-units (Pusz 2026) reports about −10% to −12% for its reflection-based
conversion engine on one workload and +8% to +33% for its value-domain expression
operations on one ISQ-heavy translation unit (near-neutral on lean ones), measured on WSL
only, with the author cautioning that "the sign is trustworthy, the magnitude is not".
reflect-moc's measurements of a moc replacement find totals between about 12% below and
6% above moc's, on a loaded machine.
simdjson reports a 6% slowdown with reflection enabled (CppCon 2025, clang-p2996) and
later cut its reflection example's build by 35% by changing what every TU instantiates.
Kolpackov (GCC PR125329) measures `<meta>` across 128 TUs with and without header units.
Matek (Boost mailing list, 2025) finds reflection-based type identity about 4× faster
than template-based identity on a Clang fork. GCC's own reports track the cost of the
flag and of reflection-heavy constant evaluation: PR124925 (19% on `<bits/stdc++.h>` in
GCC 16.0, later closed as fixed), PR125179 (a 40-fold slowdown reduced to 1.1×, in GCC
16.2.0), and Sajdak (PR128900–PR128902, November 2026), who counts the front end's
instructions on 16.2.0: `identifier_of` costs about 35 k instructions per character of
the name, because the returned `string_view` is measured by a `char_traits` loop.
reflect-cpp's maintainer found, with Clang's `-ftime-trace`, that serialization code
generation rather than reflection dominates his build; our library arms time field
visitors, not serializers, so they do not test this.

**Libraries.** Glaze documents its P2996 backend as new capabilities; we found no
published compile-time A/B of it. The one Glaze compile-time datum we found
(`make_keys_info<20>`, 45.1 → 26.0 ms in the v7.7.0 release notes) is unrelated to the
P2996 backend and was measured with `-ftime-trace`; after v9.1.0, Glaze's main
branch changed how its P2996 backend enumerates members (PR #3112). reflect-cpp's
documentation claims its C++26 path is cheaper to compile without data, and its CI does
not build that path. Boost.PFR ships an experimental P2996 engine (since Boost 1.91.0)
that its `for_each_field` does not use under `-std=c++26`. Glaze PR #2848 (merged
2026-08-29) replaced its tuple implementation for licensing reasons and with it an
N-candidate `operator[]` overload set behind `get`; it reports −41% compile time on a tuple
microbenchmark and −1% to −3% on a whole `glaze.hpp` translation unit (Apple clang 21).
That is the closest practitioner evidence we found for the overload-set effect of §4.4,
which we measure across the customization idioms of six serialization and formatting
libraries, with call sites and candidates varied separately.

**Adopted, not measured.** Talks and libraries that use P2996 for serialization or code
generation report capability, not compile cost: Webber (CppCon 2026), Piper (CppCon
2026), Chen (CHEP 2026), simdjson 5.0.

**Measuring compile time.** Metabench (Dionne) isolates a code block by subtracting a
baseline compile, as our marginal costs do; Chochlík (P2560R0, 2022) compared, for SG7,
the compile cost of value-based and type-based reflection APIs by emulating up to a
million metaobjects in generated sources and subtracting a baseline compile, before any
P2996 implementation existed; ctbench (Penuchot and Falcou 2023) measures scaling with
Clang's `-ftime-trace` and notes that there is "no clear cut methodology" to compare
metaprogramming strategies; Templight (Porkoláb et al. 2006), a debugger of template
instantiation, was later used to profile it. Gregor and Järvi (2008) measured a new language feature, variadic
templates, against its preprocessor emulation on GCC, broken down by phase — the closest
precedent to this study. Our protocol follows the benchmarking literature: randomized
interleaved trials (Abedi and Brecht 2017), awareness of setup bias (Mytkowicz et al.
2009), effect sizes with confidence intervals (Kalibera and Jones 2013), the number of
rounds checked by resampling (§3.6), bootstrap intervals (Efron and Tibshirani 1993;
Barrett et al. 2017), and documented factors (Hoefler and Belli 2015).

## 6. Threats to Validity

**Construct validity.** *One native form.* S3 times three other formulations of the member
query (§4.2), but only at the front end, on the scalar corpus with 16 fields, on GCC
16.2.0 and in one session. Every native number from the rich and heterogeneous corpora, the
field sweep, `-O2` and GCC 16.1.0, and every number of the annotation and callback arms
(`reflect`, `reflect_visit`), uses the span form and so includes the cost of iterating over
the span; S3's front-end contrast suggests that, on GCC 16.2.0, these front-end numbers
would be lower over a constant array, which we did not test.

*Instrument and flag.* The `*_noreport` and `*_noflag` controls measure the cost of the
two options that the other arms use, `-ftime-report` and `-freflection` respectively
(§3.1, §4.1).
Without the report, the native arm's ratio to hand-written code would be about
9%<!--n:ReportOverhead.reflect_plain/manual_unique.report_bias--> larger on external wall
time, while its ratio to Boost.PFR would not change (§4.1); we did not measure the
report's overhead for P1061, the X-macro or the other arms, so its effect on the headline
ratio to P1061 is unknown. Because only the phase timers partition a compile, and of the
other timers only the two stack timers exclude each other (§4.2), we report timer shares
one at a time and add up only the two stack timers. The flag, which GCC labels
experimental, also slows the arms that do not use reflection. Compared with those arms
compiled without the flag, as in a project that does not enable reflection, the native
arm's per-struct ratios would be larger by about the flag's factor for each arm (§4.1).

**Internal and conclusion validity.** *Confounds.* The code-identical control shows that
what a translation unit parses can change per-type cost by a few percent (§4.2), so
differences of that size between the native arms, which parse `<meta>`, and the P1061,
hand-written and Boost.PFR arms cannot be attributed to the mechanism. We did not test
whether `<meta>` alone has this effect, nor did we test for setup bias (§5) from the one
extra `-D` on `pfr_native`'s command line. If `<meta>` has it, the native ratios to those
arms are overstated by up to a few percent: enough to matter for the span form's parity
with Boost.PFR, not for the larger ratios. Attributing the span/array gap mainly to the
iterating expansion, rather than to the untimed calls that `define_static_array` adds, is
an inference (§4.2); contribution 2 and §7 state it as one.

*A session added after the main analysis.* S3 was added after the results of S1 and S2
had been analyzed and reviewed (§3.5). Its analysis rules fix which contrast may carry an
attribution, not the outcome. They were set before the session, but after six of its
seven arms (all but the array form, added later) had each been compiled once informally
and, with the array form added, a one-round smoke test of the whole job had run. Neither
is used in the analysis, but the smoke test already pointed to the span/array difference.
The shared arms reproduce S1, and the span/array factor of two far exceeds the variation
between S1 and S2 (§4.2), but because S3 is a single session, its intervals understate
day-to-day variation, and every array-form result rests on it alone.

*Machine and sessions.* A job's arms share rounds, in random order between compiles of a
drift sentinel, on the performance cores at high priority (§3.4, §3.5), so load and drift
add noise rather than, in expectation, a bias between arms. Dropping the compiles above
15% load changes the slopes little, and in S1 and S2 long compiles spent almost no time
off the CPU (S3 somewhat more; §3.5). Still, wall time inside the compiler is
load-sensitive, the machine was an ordinary desktop with its usual applications open and
Microsoft Defender's real-time protection on (§3.7), and frequency changes cannot be ruled
out: the power plan was fixed (High performance) and recorded (§3.5), but core frequency
was not recorded. Within-session intervals do not
cover all variation between S1 and S2 (§4.6).

**External validity.** *One compiler family.* Key arms were also timed on GCC 16.1.0
(§4.6), and Boost.PFR's C++17 path probed on GCC 15.2.0, where its quadratic term appears
as well (§4.3); we did not test Clang. As of November 2026, GCC 16 is the only released
compiler with P2996 that emits object code: Clang's upstream support covers primitive
types only; Bloomberg's clang-p2996 is a self-described experimental fork; EDG 7.0 (open
source since September 2026) runs P2996 code through a C-generating back end, so its
timings would include a C compile, and on Compiler Explorer it rejected a probe with the
expansion statement (`template for`, P1306) that our native arms use. Every number is thus
a property of GCC 16's implementation and can move between point releases: from GCC
16.1.0 to 16.2.0 the mechanism ratios moved far more than the library backend A/Bs (§4.6).
Without `-freflection`, P1061 and Boost.PFR cost the same on GCC 16.1.0 and 16.2.0, so
their version difference lies in the flag,
consistent with GCC 16.2.0's `-freflection` fixes (PR125179 and PR125280 among them),
which we did not bisect; for the native arm, which needs the flag, the causes cannot be
separated.

*Standard and implementation.* The standard specifies that the expansion statement of the
span form iterates element by element and that of the array form destructures the array
(an expression of array type is never expansion-iterable); what each costs is a property
of GCC 16.2.0 and of libstdc++'s `define_static_array`, which another compiler, library or
release need not share. GCC 16.2.0 also declares the span form's artificial variables
`static`, a specifier that CWG3044 removed from the specification; this exposes the span
form to the quadratic registration of block-scope statics (§4.2, PR128928). A patch
posted to gcc-patches on 2026-11-16, not merged by 2026-11-21, drops those statics for
C++26. We expect the patch to remove that part of the span form's cost but did not
measure this.

*Corpora and layout.* The corpora sample a range of type shapes (§3.2) but neither
reproduce nor bound real codebases: no corpus contains base classes, user-defined class
templates or private members, and field names have two to four characters. The native
arms query no names, but the C++26 paths of Glaze and reflect-cpp call `identifier_of`,
whose cost on GCC 16.2.0 grows with the length of the name (PR128900), for every field,
and their pre-C++26 paths parse names out of `__PRETTY_FUNCTION__`; longer names could
change the library arms' costs, and possibly their backend ratios, but not the native
arms'. At `-O2`, serializing every struct
from one function favors the annotation arm against Boost.PFR, though not enough to change
the direction (§4.5); the arms behind the `-O2` ratios of §7 (`reflect_plain`,
`reflect_visit`, `p1061`) have no layout control.

*Build, host and hardware.* Both compilers were built alike (§3.7): non-bootstrapped, with
release checking, by the MSYS2 host GCC 15.2.0, with configure's default flags (`-g -O2`
in the GCC 16.2.0 build log). A three-stage bootstrap (GCC's default), or the profile
feedback or LTO that distributions may add, can make a compiler faster, not necessarily by
the same factor in every phase, so absolute times may differ, and so may the ratios
between arms whose time falls in different phases. The front end is the same
code on every host, but on this Windows host (MinGW-w64) configure finds no anonymous
`mmap` (checked for the GCC 16.2.0 build), so GCC's garbage collector takes its pages from
`malloc` page groups rather than from `mmap`. That, like another microarchitecture or
memory system, could shift the ratios between arms whose working sets differ several-fold
(§4.2, §4.3). We did not repeat the measurements with a bootstrapped compiler, on Linux or
on another machine.

**Scope.** The library arms time each library's field visitor (§3.1), not its serializer,
which does more work per type (keys, formatting). Our native and P1061 arms compute no
field names (the binary format needs none; P1061 cannot provide them), while Glaze's and
reflect-cpp's visitors do (§4.3), so the native arms' ratios to Glaze and reflect-cpp are
not like-for-like in this respect and favor the native arms (Boost.PFR's `for_each_field`
computes no names); a name-keyed format such as JSON would add `identifier_of` to a native
serializer, at a cost we did not measure. Deserialization is neither implemented nor
measured. Two further forms were not timed: a native member list recomputed per index, as
in Glaze's P2996 backend at v9.1.0 (§4.3), and an expansion statement that destructures
the struct itself, without reflection (§2).

## 7. Conclusion

On GCC 16.2.0, native P2996 enumeration of a struct with 16 scalar fields costs the front
end between 0.82<!--n:FrontendIdiom.reflect_array.slope--> and
2.02<!--n:FrontendIdiom.reflect_index.slope--> ms per struct across the four formulations
timed in session S3. The form used in several of P2996R13's own examples is an expansion
statement over the `std::span` that `define_static_array` returns. It costs
1.72<!--n:FrontendN.reflect_plain.slope--> ms per struct over N ≤ 4,000
(S3: 1.73<!--n:FrontendIdiom.reflect_plain.slope-->),
7.96<!--n:FrontendN.reflect_plain/p1061.ratio-->× as much as a P1061 structured-binding
pack, which itself costs about as much as a hand-written serializer with its own name per
type. About half of the span form's cost comes with the span, which we attribute mainly
to GCC's evaluation of the iterating expansion statement that C++26 specifies over it
(§4.2). The same loop over a constant array costs
0.47<!--n:FrontendIdiom.reflect_array/reflect_plain.ratio-->× as much. Written inline, the
span form costs about as much as Boost.PFR's default `for_each_field`, and behind the same
callback API 1.21<!--n:FrontendN.reflect_visit/pfr.ratio-->× as much. Over a constant
array, inline native enumeration costs 0.49<!--n:FrontendIdiom.reflect_array/pfr.ratio-->×
Boost.PFR's `for_each_field`; no callback-shaped array arm was timed. A P3394 annotation
query on every member multiplies the span form's cost by
1.37<!--n:FrontendN.reflect/reflect_plain.ratio-->. The span form adds
1.21<!--n:RichN.reflect_plain-manual_unique.diff_ms-->–1.49<!--n:FrontendN.reflect_plain-manual_unique.diff_ms-->
ms of front-end work per struct over hand-written code on our three corpora. Thus its
ratios depend on everything else a struct costs:
1.55<!--n:HeteroN.reflect_plain/p1061.ratio-->× P1061 on a heterogeneous type graph, and
1.21<!--n:FullN.reflect_plain/p1061.point400-->× at `-O2`, where the optimizer spends about
the same time on every inline mechanism. At `-O2` the inline native serializer costs
0.61<!--n:FullN.reflect_plain/pfr.point400-->× Boost.PFR's, mostly because a callback API
costs the optimizer more. Behind the same callback API the ratio is
0.85<!--n:FullN.reflect_visit/pfr.point400-->.

**What follows for practice, on GCC 16.2.0.** In a whole translation unit the choice of
library outweighs the choice of enumeration mechanism. With 200 structs of 16 scalar
fields the front end takes 0.59<!--n:FrontendHeavy.reflect_plain.total200_s--> s with inline
native enumeration and 0.56<!--n:FrontendHeavy.pfr.total200_s--> s with Boost.PFR. The C++26
paths of reflect-cpp and Glaze, whose visitors also compute field names, take
3.86<!--n:FrontendHeavy.rflcpp_native.total200_s--> and
4.13<!--n:FrontendHeavy.glaze_native.total200_s--> s (Table 3). For an inline
native serializer, an expansion statement over a constant array,
`[:std::meta::reflect_constant_array(...):]` (standard C++26), is the cheaper choice at the
front end (0.47<!--n:FrontendIdiom.reflect_array/reflect_plain.ratio-->× the span form's
cost per struct of 16 scalar fields, S3): with fixed costs included, a whole translation
unit takes 0.61<!--n:FrontendIdiom.reflect_array/reflect_plain.total1000-->× the span
form's front-end time with 1,000 structs and
0.50<!--n:FrontendIdiom.reflect_array/reflect_plain.total4000-->× with 4,000. We did not
time the array form on the other corpora or at `-O2`; at `-O2` the span form already
costs only 1.21<!--n:FullN.reflect_plain/p1061.point400-->× P1061 at 400 structs (§4.5),
so the array form's front-end saving would likely matter less there. Code that needs
neither names nor annotations, such as a binary format, hashing or comparison, can
enumerate with a P1061 pack the fields of a struct that structured bindings can
decompose. For our serializer this costs about as much as hand-written code, with no
per-type source. We did not time a further standard form, an expansion statement that
destructures the struct. A library whose users customize serialization by overloading one
name in one namespace makes every resolution of that name consider all of its overloads
in that namespace, so the cost grows faster than linearly with the number of types
(§4.4). Hidden friends, member functions and
class-template specializations avoid the shared set (Table 4). Every per-type number
excludes fixed costs, which precompiled headers or modules may amortize; we measured
neither. Per-type costs recur in every translation unit that serializes the type.

Per type, each library's C++26 path is cheaper to compile than its pre-C++26 path at 16
fields. Glaze's gain is 2.00<!--n:FrontendHeavy.glaze_classic/glaze_native.ratio-->×,
reflect-cpp's 2.08<!--n:FrontendHeavy.rflcpp/rflcpp_native.ratio-->×, and Boost.PFR's
4.4<!--n:FrontendN.pfr_classic/pfr.point500-->× at 500 types and
12.8<!--n:FrontendN.pfr_classic/pfr.point4000-->× at 4,000, because its C++17 path grows
almost quadratically with the number of types. But the gain is not a constant of the
library. Glaze's is reversed at 128 fields
(0.70<!--n:FrontendM.glaze_classic/glaze_native.M128-->×, pinned release
v9.1.0); reflect-cpp's falls to 1.21<!--n:HeteroHeavy.rflcpp/rflcpp_native.ratio-->× on a
heterogeneous type graph. In a whole translation unit the headers dilute the gain.
Hand-written serializers that share one name grow by
3.5<!--n:OverloadN.ovl_flat.doubling-->–4.0<!--n:OverloadN.ovl_constrained.doubling-->× per
doubling of the number of types from 500 to 1,000 (K = C = N) for the five idioms of
Table 4 that share one lookup set. The hand-written arm with one overloaded name grows
faster still from 2,000 to 4,000 types (§4.4) and overtakes native reflection in the span
form between 1,000 and 2,000 types.

The toolchain also moves the comparisons. The `-freflection` flag makes code that does
not use reflection
1.017<!--n:FlagCostHeavy.rflcpp.flag_slope_ratio-->–1.264<!--n:CompilerFlag.p1061.flag_slope_ratio-->×
costlier per type on GCC 16.2.0 and up to
2.578<!--n:CompilerFlag.p1061@GCC161.flag_slope_ratio-->× on GCC 16.1.0, and between these
two point releases inline native enumeration in the span form moves from
0.71<!--n:CompilerN.reflect_plain@GCC161/pfr@GCC161.ratio-->× to
0.99<!--n:CompilerN.reflect_plain/pfr.ratio-->× Boost.PFR's cost, while the library backend
A/Bs barely change. Comparisons between mechanisms are therefore properties of a compiler
release and of the formulation measured, and should be repeated as GCC's reflection
support matures and other compilers ship it.

## Acknowledgments

The author conceived the study, made its design and methodological decisions, ran the
measurements and checked the results. An AI assistant (Claude, by Anthropic) was used
under the author's direction to write the measurement harness and the analysis scripts,
to draft and edit the text, to search the literature and to review the paper. The harness
is not trusted on its own: a value oracle with a negative control checks every arm's
output against a hand-written reference, the manipulation checks of §3.3 check every
single-factor pair, and the full plan was measured in two sessions. Every measured number
in the paper is generated by the analysis scripts from the archived raw data and checked
against the text automatically (Artifact). The author takes full responsibility for the
content.

## Artifact

The artifact is archived at https://doi.org/10.5281/zenodo.24443567 (the version this paper
reports) and developed at https://github.com/DenysKachalenko/CPP26FieldEnumerationCompileCostArtifact; its
code is released under the MIT license, its data and text under CC BY 4.0. `DATA.md`
documents every file and every column of the raw data. Every number and figure can be
regenerated from the archived raw data without a compiler, with Python, NumPy and
Matplotlib (3.13.1, 2.5.1 and 3.11.0 here; `requirements.txt`), run from `Harness/`:

- `python papernumbers.py ../Data/Sessions/S1 ../Data/Sessions/S2 ../Data/Sessions/S3` writes
  `Data/PaperNumbers.json`;
- `python paperlint.py` checks every tagged number in `Paper.md` against it;
- `python figures.py ../Data/Sessions/S1 ../Data/Sessions/S3` draws `Figures/`.

Re-measuring needs both compilers, built with `Harness/build_gcc.sh`, and one unattended
run per session (`Harness/overnight.sh`, `RunBook.md`); the compiles of S1 and S2 took
about 5.7 hours each, those of S3 about 16 minutes. The archive contains the generator (`Harness/generate.py`,
`Harness/overload.py`), the arm registry and manipulation checks (`Harness/arms.py`,
`Harness/preflight.py`), the harness (`Harness/campaign.py`, `Harness/compiler.py`,
`Harness/machine.py`, `Harness/plan.py`), the unattended run (`Harness/overnight.sh`), the
Boost.PFR probe (`Harness/pfrprobe.py`, `Data/PfrProbe.json`), statistics and paper numbers
(`Harness/stats.py`, `Harness/papernumbers.py`, `Harness/paperlint.py`,
`Harness/figures.py`, `Data/PaperNumbers.json`, `Figures/`), the GCC build script
(`Harness/build_gcc.sh`), pins (`Deps.json`), CMake tests, the reproducers of PR128928 (`Repro/`), raw per-run data, environment
records and a copy of the measured code per session (`Data/Sessions/S1`, `S2`, `S3`), and the
run book (`RunBook.md`).
