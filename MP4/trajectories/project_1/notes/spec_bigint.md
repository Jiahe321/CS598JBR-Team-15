# spec_bigint.md — per-function behaviour (C `bigint.h` → Rust `src/bigint.rs`)

Digits are big-endian decimal (`digits[0]` most significant, `digits[len-1]` least significant). `size`/`digits.len()` ≥ 1.

## Constructors / basics

### `zero()`
C `bigint_zero`: `{is_negative=false, size=1, digits=[0]}`. Rust: `BigInt{negative:false, digits:vec![0]}`.

### `is_64_bit(&self) -> bool`
C: if `size > 10` → false; if `size < 10` → true; if `size == 10` → false (both sign branches identical). So **true iff `digits.len() < 10`**. (Note: this is a heuristic, not a true range check; replicate exactly because mul/div/mod/fast_pow branch on it.)

### `remove_leading_zeros(&mut self)`
Count leading zero digits. If count ≥ len → set `digits = vec![0]` (len 1), return. Else drop `count` leading digits. Sign unchanged. (Zero stays possibly-negative if it was; canonical code sets sign false for zero elsewhere.)

### `from_int(n: i64) -> Self`
C: sign = n<0; take abs; build decimal digits big-endian; then `remove_leading_zeros`. For n=0 → `{false,[0]}`. Note C computes `size` as 1 + number of divisions, then fills; effectively produces the decimal digits of |n| with no leading zeros after cleanup. Rust: handle `i64::MIN` carefully (use `unsigned_abs` or `i128`). Result: decimal digits of |n|, sign = n<0 (zero → non-negative).

### `to_int(&self) -> i64`
C: `result = 0; for each digit: result = result*10 + digit; if negative: result = -result`. Overflow wraps in C (UB technically); Rust: use `wrapping` arithmetic to mirror, or `i64` accumulation. Tests only use small values. Recommend: accumulate in `i128` then cast, or wrapping_mul/add to match C's two's-complement wrap.

### `from_str(s: &str) -> Self`
C `bigint_from_string`: if first char `'-'` → negative, skip it. size = strlen(rest). digits[i] = char - '0'. **No validation, no leading-zero removal.** So `from_str("007")` → digits `[0,0,7]`, size 3. Equality/comparison call remove_leading_zeros so it still compares equal to 7. Rust: parse optional leading '-', map each remaining char to `c as u8 - b'0'`. Empty string after sign → unclear (C would size 0; avoid). Recommend: if empty, treat as zero `[0]`.

### `copy(&self) -> BigInt`
Clone (sign + digits).

### `print(&self)`
C: if negative print "-"; then print each digit with no separators (asserts each 0..9). No newline. Rust: `print!` to stdout.

### `is_zero`, `lt_zero`, `gt_zero`, `lezero`, `gezero`
All first `remove_leading_zeros` on a copy, then:
- `is_zero`: `len==1 && digits[0]==0`.
- `lt_zero`: false if zero, else `negative`.
- `gt_zero`: false if zero, else `!negative`.
- `lezero`: true if zero, else `negative`.
- `gezero`: true if zero, else `!negative`.

### `abs(&self) -> Self`
Copy with `negative=false`.

### `is_even` / `is_odd`
C: `digits[size-1] % 2 == 0` / `== 1`. Uses last (least-significant) digit. Rust: `self.digits.last() % 2`.

## Comparison

### `gt(a,b) -> bool` (free fn `gt`)
C `bigint_gt`: remove leading zeros on copies. If `a.len > b.len` → return `!a.negative`. If `a.len < b.len` → return `a.negative`. Else compare digits left-to-right: first differing digit → return `!a.negative` if a's digit larger, else `a.negative`. If all equal → false.
(Assumes both same sign when sizes equal; sign handled via `!a.negative`.)

### `lt(a,b)` = `!ge(a,b)`; `ge(a,b)` = `gt(a,b) || eq(a,b)`; `le(a,b)` = `!gt(a,b)`.
C defines exactly these in terms of gt/eq. Replicate.

### `PartialEq::eq`
C `bigint_eq`: remove leading zeros on copies; if len differ → false; if sign differ → false; compare digits. (Zero with negative flag vs positive zero: signs differ → false in C. But canonical zero is non-negative; ensure constructors produce non-negative zero so `from_int(0)==from_str("0")`.)

### `PartialOrd::partial_cmp`
Return `Some(Equal)` if eq, `Some(Greater)` if gt, `Some(Less)` if lt, else `Some(Equal)`.

### `Neg`
Flip sign. (C has no explicit neg; `-x` = copy with sign toggled. For zero, toggling gives negative zero — recommend: if zero, keep non-negative.)

## Arithmetic

### `add(&self, other) -> Self`
C `bigint_add`:
- both negative → result negative, add magnitudes.
- a negative, b positive → `sub(b, |a|)` i.e. `bigint_sub(b, a_with_sign_cleared)`.
- b negative, a positive → `sub(a, |b|)`.
- else positive add.
Magnitude add: result len = max(len); add from least-significant with carry; if final carry>0 prepend it; remove leading zeros. Sign set accordingly.

### `sub(&self, other) -> Self`
C `bigint_sub`:
- both negative: clear signs, `add(b,a)` (magnitudes), set result negative. (i.e. -a - -b = -(a+b)? — note C does `add(b,a)` then negative; since both were negative, -a-(-b) = b-a, but C computes -(a+b). This is a **C quirk/bug** for both-negative. For graded tests only positive operands used in sub. Recommend implementing mathematically correct subtraction: `a - b = a + (-b)`.)
- a negative: `-(|a| + b)`.
- b negative: `a + |b|`.
- both positive: result len = max; subtract smaller from larger digit-wise with borrow; sign = `lt(a,b)`; remove leading zeros.
**Recommendation:** implement `sub` as `add(a, neg(b))` for correctness; verify against graded tests (200-100=100, big positive subtractions). The both-negative C quirk is not exercised by tests; correct math is safer.

### `inc(&mut self)` / `dec(&mut self)`
C: `*n = add(*n, 1)` / `*n = sub(*n, 1)`. Rust: `*self = self.add(&from_int(1))` / `sub`.

### `mul(&self, other) -> Self`
C `bigint_mul`:
- If both `is_64_bit` (len<10): return `from_int(to_int(a) * to_int(b))` (i64 multiply, may overflow for len 9*9 — but tests use small).
- Else: result len = a.len+b.len, zeroed. For each i,j: `result[len-1-i-j] += a[a.len-1-i]*b[b.len-1-j]`. Normalize with carry from least significant; if carry>0 prepend. remove leading zeros. Sign = `a.negative != b.negative`.
Rust: implement schoolbook on decimal digits (u32/u64 accumulators), sign = xor. Must handle 100! (158 digits) — fine.

### `divmod(&self, other) -> (Self, Self)`
C `bigint_divmod(numerator, denominator, &rem)`:
- If both `is_64_bit`: `q = to_int(a)/to_int(b)`, `r = to_int(a)%to_int(b)` (C truncation toward zero), return `(from_int(q), from_int(r))`.
- Else: `negative = a.neg != b.neg`; clear signs; repeated subtraction of denominator from numerator while numerator>0, counting quotient; if goes negative, add back denominator once; remainder = numerator; quotient sign = negative; remainder sign = negative (if negative). remove leading zeros on quotient.
**Rust recommendation:** implement long division on decimal digits producing truncated-toward-zero quotient and remainder with sign of dividend (matching C's `%`/`/` for the 64-bit path). For the general path C sets remainder negative when quotient negative (sign of dividend = sign of numerator since negative = a.neg!=b.neg and remainder sign follows numerator sign). Ensure `div` and `mod` consistent: `div` returns quotient, `mod` returns remainder. Tests: 200/100=2, 200%100=0, 201%100=1, big a/b smoke only.

### `div(&self, other) -> Self`
Quotient from divmod.

### `r#mod(&self, other) -> Self`
Remainder from divmod. C 64-bit path uses `%` (sign of dividend). General path remainder sign = negative flag (sign of dividend). Match: remainder has sign of dividend.

## Power / number theory

### `pow(&self, exponent) -> Self`
C `bigint_pow`: if exponent negative → return 0. result=1; if exp zero → 1. Loop: result *= a; exp -= 1. (Repeated multiplication.) Rust: same semantics; can use fast exponentiation but must yield identical value. `pow(2,10)=1024`.

### `fast_pow(&self, exponent, modulo) -> Self`
C `bigint_fast_pow(a,b,m)`:
- If all three `is_64_bit`: i64 modular exponentiation: `base=a%m; exp=b; result=1; while exp>0 { if exp odd result=result*base%m; exp>>=1; base=base*base%m } return from_int(result)`. (Note: for negative exp this loop doesn't run → returns 1, but the general path returns 0 for negative exp. Tests use positive exp.)
- General path: if b negative → 0; if b zero → 1; `a = a mod m`; result = a; then a halving-squares algorithm with correction; returns `a^b mod m`.
**Rust recommendation:** implement standard modular exponentiation `result = a^b mod m` with `b` as BigInt (square-and-multiply using divmod/mod). For b=0 → 1; b negative → 0. Must give `745232^67121 mod 1022117 = 97` and `2^1234 mod 10007`. Ensure result in `[0,m)`.

### `modinv(&self, modulo) -> Self`
C `bigint_modinv(a,m)`: extended Euclid. m0=m; y=0;x=1; while a!=0 { q=m/a; t=m-q*a; m=a; a=t; t=y-q*x; y=x; x=t }. If m<0: m+=m0. If m==1: result = y mod m0; if result<0 result+=m0; return result. Else return 0.
Rust: extended Euclid; return x such that `a*x ≡ 1 (mod m)`, normalized to `[0,m)`. Return 0 if gcd≠1. Test: modinv(17,43) → 38 (17*38=646=15*43+1).

### `sqrt(&self) -> Self`
C `bigint_sqrt`: binary search. low=0, high=n, mid=0. while low<high: mid=(low+high)/2; if mid*mid < n: low=mid+1 else high=mid. return low.
This returns **ceil(sqrt(n))** when n is not a perfect square? Check: n=100 → returns 10 (perfect). n=101 → low converges to 11 (since 10*10=100<101 → low=11; 11*11=121≥101 → high=11; low==high=11). So returns smallest integer whose square ≥ n = ceil(sqrt(n)). For perfect squares returns exact sqrt. **Replicate exactly**: return ceil(sqrt(n)). Tests: sqrt(100)=10, sqrt(101)=11, sqrt(123412341) smoke.

### `is_prime(&self) -> bool`
C `bigint_is_prime`:
1. if even → false.
2. if len>1 and last digit is 5 or 0 → false.
3. digit sum divisible by 3 → false.
4. for i from 2 to sqrt(n) (inclusive, using `bigint_sqrt` = ceil sqrt): if n % i == 0 → false.
5. else true.
Note: this returns false for 2 (even) and for 3? 3 is odd, last digit 3, digit sum 3 divisible by 3 → false! So C's is_prime(3)=false, is_prime(2)=false. **Replicate exactly** (tests only check 17→true, 18→false, and big number smoke). 17: odd, last digit 7, sum 8 not div 3, trial division 2..5 (ceil sqrt 17=5) none divide → true. 18 even → false.

## Misc

### `delete(a: &mut BigInt)`
C frees digits. Rust: reset to zero (`*a = BigInt::zero()`). No observable effect needed.

### `Display`
C `bigint_print`: "-" if negative then digits concatenated. Rust: write sign then each digit char. No leading zeros (canonical). For zero → "0".

## Tests exercised
- test1: `from_int`, `mul`, `add`, `le` (via `<=`), `from_str`, `eq`, `Display` (println). 100! exact.
- test2: from_int/from_str eq, comparisons, add/sub/mul/div/mod, pow, modinv, sqrt, is_prime, fast_pow.
- test3: from_str big, add/sub/mul/div/mod, comparisons, fast_pow, is_prime, sqrt — smoke (no asserts) but must not panic/hang. **Note:** test3 test2 does `a.div(&b)` and `a.mod(&b)` with a<b (a=1.23e29, b=9.87e29) → quotient 0, remainder a. General path must handle a<b (repeated subtraction loop: numerator>0, subtract b → negative, break, add back → remainder=a, quotient=0). Long division must give q=0,r=a.
