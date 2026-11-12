# Spec: Adam's Big Integer Library → Rust `bigint` module

## Module map
- `c/src/bigint.h` (header-only implementation) → `src/bigint.rs` (module `bigint::bigint`).
- `c/tests/test1.c` → `src/bin/test1.rs` (factorial of 100).
- `c/tests/test2.c` → `src/bin/test2.rs` (basic ops).
- `c/tests/test3.c` → `src/bin/test3.rs` (smoke tests, no assertions).

## Data structure
C: `typedef struct { bool is_negative; int64_t *digits; size_t size; } bigint;`
- `digits` is a **big-endian** array of decimal digits (each 0..9). `digits[0]` is most significant.
- `size` = number of digits (>= 1). Zero is `{false, [0], 1}`.
- Sign is a separate flag; zero is never negative in canonical form (but C code sometimes leaves `is_negative` set on zero — see notes).

Rust: `pub struct BigInt { negative: bool, digits: Vec<u8> }` — same layout, `Vec<u8>` replaces malloc'd array. Keep big-endian decimal digits, `digits.len() >= 1`, zero = `{false, vec![0]}`.

## Global/static state
None.

## Implementation order
1. Constructors / basics: `zero`, `from_int`, `from_str`, `copy`, `remove_leading_zeros`, `to_int`, `is_64_bit`.
2. Predicates: `is_zero`, `lt_zero`, `gt_zero`, `lezero`, `gezero`, `is_even`, `is_odd`, `abs`.
3. Comparison: `gt`, `lt`, `ge`, `le`, `PartialEq`, `PartialOrd`, `Neg`.
4. Arithmetic: `add`, `sub`, `inc`, `dec`, `mul`.
5. Division: `divmod`, `div`, `mod`.
6. `pow`, `fast_pow`, `modinv`, `sqrt`, `is_prime`.
7. `print`, `Display`, `delete`.

## Safe-Rust design notes
- `malloc`ed digit array → `Vec<u8>`.
- `bigint_delete(bigint n)` (frees memory) → `delete(a: &mut BigInt)` resets to zero (`digits = vec![0]`, `negative = false`). No-op semantically; must exist for API.
- `bigint_divmod(a,b,&rem)` returning quotient + out-param → `divmod(&self,&other) -> (Self, Self)`.
- `bigint_inc/dec(bigint*)` → `inc(&mut self)` / `dec(&mut self)` mutating in place.
- `bigint_print` → `print(&self)` (stdout) and `Display`.
- `bigint_from_string(const char*)` → `from_str(&str)`.
- `bigint_to_int` → `to_int() -> i64`.
- `bigint_abs` returns a copy with sign cleared.
- `bigint_is_64_bit` is a heuristic (see module spec); replicate exactly since `mul`/`div`/`mod`/`fast_pow` branch on it.

## Critical cross-cutting behaviours (from C)
- **Big-endian decimal digits**, arithmetic done digit-by-digit from the least-significant end (`digits[size-1-i]`).
- `remove_leading_zeros` strips leading zero digits; if all zero → `{size=1, digits[0]=0}` (sign untouched).
- Comparison `gt`/`eq` first call `remove_leading_zeros` on copies, then compare size, then sign, then digits.
- `mul`, `div`, `mod`, `fast_pow` have a **64-bit fast path** guarded by `is_64_bit`; otherwise use the general algorithm. The general algorithms must produce the same results as the fast path for the graded tests.
- `divmod` general path is repeated subtraction (slow); Rust should use a correct long-division but must match C's sign/remainder conventions (see module spec).
- `pow` with negative exponent returns 0; `pow(x,0)=1`.
- `fast_pow` with negative exponent returns 0; `fast_pow(x,0)=1`; result is `a^b mod m` in `[0,m)`.
- `modinv` returns `x` with `a*x ≡ 1 (mod m)`; returns 0 if no inverse (gcd≠1).
- `sqrt` is integer floor sqrt via binary search (C returns `low` = ceil-ish; see module spec — for 100→10, 101→11).
- `is_prime`: even → false; last digit 5/0 with size>1 → false; digit-sum divisible by 3 → false; then trial division 2..=sqrt(n).

See `notes/spec_bigint.md` for per-function detail.
