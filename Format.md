# Binary Wire Format

The format all arms encode to. It is **schema-driven**: the reader knows each
type, so the stream carries *no* type tags — only values. Deterministic and
portable (host-endianness independent).

## Primitives

| Kind | Encoding |
|------|----------|
| `bool` | 1 byte: `0` or `1` |
| integer (`intN`/`uintN`) | `N/8` bytes, **little-endian**, two's complement via unsigned reinterpretation |
| `float` (32-bit) | 4 bytes: IEEE-754 bit pattern, little-endian |
| `double` (64-bit) | 8 bytes: IEEE-754 bit pattern, little-endian |
| `enum` | its underlying integer type, encoded as above |
| `string` | `u64` length (LE) + that many raw bytes |

## Composites

| Kind | Encoding |
|------|----------|
| `vector<T>` | `u64` element count (LE) + each element in order |
| `optional<T>` | `u8` flag (`0`/`1`); if `1`, the value follows |
| `struct` | each **non-transient** nonstatic data member, in declaration order, recursively |

## Rules

- **No padding, no alignment, no type tags** — a pure value stream.
- Members carrying the `Transient` annotation (P3394) are skipped by the
  **annotation-aware** arms (native reflection; the hand-written arm mirrors it).
  Library and macro arms cannot read P3394 annotations — this is a native-only
  capability, so the synthetic corpus carries no `Transient` fields.
- Member order is declaration order (as returned by
  `nonstatic_data_members_of`).

Every arm produces byte-identical output for identical values (write-side,
cross-arm agreement — not a round-trip). This is enforced by the oracle that
`bench.py` compiles and runs before each timing pass, and by `test/` under CTest.
