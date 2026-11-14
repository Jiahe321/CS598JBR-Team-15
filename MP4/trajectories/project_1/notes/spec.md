# BigInt translation spec — module map & overview

## Source of truth
- C implementation: `c/src/bigint.h` (header-only, all functions inline). Line ranges cited below.
- C tests: `c/tests/test1.c`, `c/tests/test2.c`, `c/tests/test3.c`.
- Rust interface: `src/bigint.rs` (stubs), `src/lib.rs` (`pub mod bigint;`).
- Graded Rust tests: `src/bin/test1.rs`, `src/bin/test2.rs`, `src/bin/test3.rs`.

## Module map
| C | Rust |
|---|---|
| `bigint` struct (`c/src/bigint.h:15-19`) | `struct BigInt { negative: bool, digits: Vec<u8> }` (`src/bigint.rs:3-7`) |
| all functions in `bigint.h` | methods/free fns in `src/bigint.rs` |

There is exactly one Rust module: `bigint`. Detailed per-function spec is in `notes/spec_bigint.md`.

## Data structure
C: `{ bool is_negative; int64_t *digits; size_t size; }` — digits are **base-10**, most-significant first, each in `0..=9`. `size` is the number of digits (may include leading zeros until `remove_leading_zeros` is called).

Rust: `negative: bool`, `digits: Vec<u8>` (base-10, MSB first, each `0..=9`). `digits.len()` plays the role of `size`. The Rust struct has **no separate size field**; length is `digits.len()`.

## Global/static state
None. All functions are pure except the in-place mutators `inc`, `dec`, `remove_leading_zeros`, and `delete`.

## Memory model translation
- `malloc`/`realloc`/`free` → `Vec<u8>` (grow with `push`/`insert`, no manual free).
- `bigint_delete(n)` frees digits and zeroes the struct. In Rust `delete(a: &mut BigInt)` should reset `a` to the zero value (see spec_bigint.md). Ownership is by value/clone; no leaks possible.
- `bigint_copy` → `Clone`/`copy()`.
- Functions taking `bigint` by value in C take `&self`/`&Self` in Rust; results are new `BigInt`s.

## Implementation order
1. Constructors & basics: `zero`, `from_int`, `to_int`, `from_str`, `copy`, `remove_leading_zeros`, `is_64_bit`, `print`, `Display`.
2. Predicates: `is_zero`, `lt_zero`, `gt_zero`, `lezero`, `gezero`, `is_even`, `is_odd`.
3. Comparisons: `gt`, `lt`, `ge`, `le`, `PartialEq`, `PartialOrd`, `Neg`.
4. Arithmetic: `abs`, `add`, `sub`, `inc`, `dec`, `mul`.
5. Division: `divmod`, `div`, `mod`.
6. Powers: `pow`, `fast_pow`.
7. Number theory: `modinv`, `sqrt`, `is_prime`.
8. `delete`.

## Key cross-cutting notes
- All arithmetic is base-10 digit-vector arithmetic, MSB-first.
- `remove_leading_zeros` is called defensively inside comparisons and after arithmetic; the Rust code must keep `digits` normalized (no leading zeros, zero == `[0]`) wherever C would.
- `is_64_bit` is a *heuristic* (size < 10 → true, size > 10 → false, size == 10 → false) used to pick a fast `i64` path in `mul`/`div`/`mod`/`fast_pow`. See spec_bigint.md for exact semantics and the caveat that size==10 always returns false.
- Negative zero: C can produce `is_negative=true` with value 0 in some paths; predicates (`eqzero`, `ltzero`, etc.) treat value 0 as non-negative. Rust `PartialEq` must treat `-0 == 0` (see spec).
