# spec_bigint.md — `bigint` module

All C line refs are `c/src/bigint.h`. Rust signatures are fixed by `src/bigint.rs`.

Convention: digits are base-10, MSB-first, each `0..=9`. "normalized" = no leading zeros and zero is `[0]`.

---

## Constructors / conversion

### `zero() -> BigInt`  (C `bigint_zero`, 23-30)
Returns value 0: `negative=false`, `digits=[0]`. C sets size=1, digits[0]=0.

### `from_int(n: i64) -> BigInt`  (C `bigint_from_int`, 75-97)
- If `n < 0`: `negative=true`, `n = -n`. Else `negative=false`.
- Builds base-10 digits of `|n|` MSB-first, then `remove_leading_zeros`.
- `from_int(0)` → `negative=false`, `digits=[0]` (loop `while m>0` doesn't run, size stays 1, digit 0).
- Note: C `-n` on `i64::MIN` overflows (UB); Rust should use `n.unsigned_abs()` or `wrapping_neg` to avoid panic. Tests only use small positives.
- Tests: test1 (from_int(1), from_int(100)), test2 (many), test3.

### `to_int(&self) -> i64`  (C `bigint_to_int`, 99-109)
- Accumulate `result = result*10 + digit` over all digits, then negate if `negative`.
- No overflow check (C wraps/UB); Rust may use `wrapping` arithmetic to mirror. Only used on small values in tests.

### `from_str(s: &str) -> BigInt`  (C `bigint_from_string`, 115-138)
- If first char `'-'`: `negative=true`, skip it. Else `negative=false`.
- Each remaining char `c` → digit `c - '0'` (assumes ASCII digits; no validation in C).
- **Does NOT call remove_leading_zeros** — leading zeros are preserved as given. (Comparisons normalize anyway.)
- Empty string after sign → size 0 in C (edge case, not tested). Rust: produce `digits=[]`? Safer to mirror: empty digits vec. Not exercised by tests.
- Tests: test1 (huge factorial string), test2 ("100"), test3 (large strings, "2","1234","10007","123412341").

### `copy(&self) -> BigInt`  (C `bigint_copy`, 141-148)
Deep copy: same `negative`, same `digits`. Equivalent to `self.clone()`.

### `remove_leading_zeros(&mut self)`  (C 53-73)
- Count leading zero digits. If all digits are zero (count >= len): set `digits=[0]` (size 1, digit 0). **Does not change `negative`.**
- Else drop the leading zeros (memmove). 
- Rust: while `digits.len()>1 && digits[0]==0` remove front; if empty set `[0]`. (C keeps size≥1.)

### `is_64_bit(&self) -> bool`  (C `bigint_is_64_bit`, 34-51)
- If `size > 10` → false. If `size < 10` → true. If `size == 10` → **false** (both branches fall through to `return false`).
- The `is_negative` branches are identical, so sign is irrelevant.
- So: returns `digits.len() < 10`. (size==10 → false, size>10 → false.)
- Used by `mul`, `div`, `mod`, `fast_pow` to choose i64 fast path. **Caveat:** a 10-digit number that fits in i64 still takes the slow path; and a value with size<10 always fits i64. This is a heuristic, not a true fit test.

### `print(&self)`  (C `bigint_print`, 153-161)
- Print `-` if negative, then each digit with no separators (no newline). C asserts each digit in 0..=9.
- Rust: `print!("{}", self)` using Display.

### `Display`  (C `bigint_print` semantics)
- Format: optional `-` then concatenated digits. No padding, no newline.
- Tests: test1 prints `{}! = {}`; test3 prints messages.

---

## Predicates

### `is_zero(&self) -> bool`  (C `bigint_eqzero`, 201-207)
- Normalize a copy; true iff value is 0 (size==1 && digit==0). Sign ignored (so `-0` is zero).

### `lt_zero(&self) -> bool`  (C `bigint_ltzero`, 209-215)
- Normalize; if value is 0 → false; else return `negative`.

### `gt_zero(&self) -> bool`  (C `bigint_gtzero`, 216-222)
- Normalize; if value is 0 → false; else return `!negative`.

### `lezero(&self) -> bool`  (C 224-230)
- Normalize; if value 0 → true; else return `negative`.

### `gezero(&self) -> bool`  (C 232-238)
- Normalize; if value 0 → true; else return `!negative`.

### `is_even(&self) -> bool`  (C 766-768)
- `digits[last] % 2 == 0`. (Last digit parity.) Assumes non-empty digits.

### `is_odd(&self) -> bool`  (C 770-772)
- `digits[last] % 2 == 1`.

---

## Comparisons

### `gt(a,b) -> bool`  (C `bigint_gt`, 164-182)
Normalize both copies. Then:
- If `a.size > b.size` → return `!a.negative`.
- If `a.size < b.size` → return `a.negative`.
- Else compare digits MSB→LSB: first differing digit: if `a.digit > b.digit` → `!a.negative`; if `<` → `a.negative`.
- Equal → false.
(Assumes both normalized so equal size ⇒ same sign comparison is consistent.)

### `lt(a,b)`  (C `bigint_lt`, 249-251) = `!ge(a,b)`.
### `ge(a,b)`  (C `bigint_ge`, 245-247) = `gt(a,b) || eq(a,b)`.
### `le(a,b)`  (C `bigint_le`, 253-255) = `!gt(a,b)`.

### `PartialEq::eq`  (C `bigint_eq`, 184-199)
Normalize both copies. False if sizes differ, false if signs differ, else all digits equal. (So `-0 == 0` because both normalize to size 1 digit 0 and... note: signs may differ but value 0 — C checks `is_negative != is_negative` → would return false for `-0` vs `0`! See caveat.)

**Caveat / conflict:** C `bigint_eq` compares `is_negative` directly (line 190) *after* normalizing digits but does NOT clear sign for zero. So `-0` and `0` would compare unequal in C. However `bigint_from_int(0)` and `bigint_zero` produce `negative=false`, and `remove_leading_zeros` never sets sign. In practice tests never compare a `-0` against `0`. Rust `PartialEq` should follow C: normalize digits, compare size, compare `negative`, compare digits. To be safe and match test expectations (all test values are non-negative or consistent), implement exactly as C.

### `PartialOrd::partial_cmp`  (C via gt/lt/eq)
Return `Some(Equal)` if `eq`, `Some(Greater)` if `gt`, `Some(Less)` if `lt`, else `None`. Since gt/lt/eq are total over normalized values, always `Some`. Tests use `<=,>=,<,>` (test2, test3).

### `Neg`  (no direct C fn; C flips `is_negative`)
Return copy with `negative = !negative`. (C never has a standalone neg; `abs` sets false.) For zero, C would produce `-0`; acceptable.

### `abs(&self) -> BigInt`  (C `bigint_abs`, 240-243)
Copy with `negative=false`. Digits unchanged.

---

## Arithmetic

### `add(&self, other) -> BigInt`  (C `bigint_add`, 329-375)
Sign handling:
- both negative → result negative, add magnitudes.
- a negative, b not → `sub(b, |a|)` i.e. `bigint_sub(b, a_with_sign_cleared)` (C clears a's sign then `sub(b,a)`).
- b negative, a not → `sub(a, |b|)`.
- else positive add.
Magnitude add: result size = max(a.size,b.size); add digit-by-digit from LSB with carry; `sum%10` stored, `carry=sum/10`. If final carry>0, prepend it (size++). Then `remove_leading_zeros`.
- Tests: test2 (100+200=300), test1 (i+1 loop), test3.

### `sub(&self, other) -> BigInt`  (C `bigint_sub`, 265-322)
Sign handling:
- both negative → `add(|b|,|a|)` then set negative (i.e. `-(|a|+|b|)`).
- a negative only → `add(a, -b)` (b sign set true) → `-(|a|+|b|)`.
- b negative only → `add(a, |b|)`.
- else both non-negative: compute `is_negative = lt(a,b)`; larger = gt(a,b)?a:b; smaller = other; subtract digit-by-digit with borrow (diff<0 → +10, carry=-1). Then remove_leading_zeros, set sign = is_negative.
- Tests: test2 (200-100=100), test3.

### `inc(&mut self)`  (C `bigint_inc`, 378-385)
`*self = self.add(&one)` where one = from_str("1"). In-place.

### `dec(&mut self)`  (C `bigint_dec`, 387-394)
`*self = self.sub(&one)`.

### `mul(&self, other) -> BigInt`  (C `bigint_mul`, 396-440)
- **Fast path:** if `is_64_bit(a) && is_64_bit(b)` → `from_int(to_int(a) * to_int(b))`. (i64 multiply; may overflow for large 9-digit products — C UB, tests use small.)
- Else schoolbook: result size = a.size+b.size, init 0. For each i,j: `result[size-i-j-1] += a[a.size-i-1]*b[b.size-j-1]`. Normalize with carry (sum%10, carry=sum/10). If carry>0 prepend. remove_leading_zeros. Sign = `a.negative != b.negative`.
- Tests: test1 (factorial 100 — huge, uses slow path), test2 (100*200=20000 fast path), test3.

### `divmod(&self, other) -> (Self, Self)`  (C `bigint_divmod`, 443-491)
Returns `(quotient, remainder)`.
- **Fast path:** if both is_64_bit → `q = to_int(a)/to_int(b)`, `r = to_int(a)%to_int(b)` (C truncating division), return `(from_int(q), from_int(r))`.
- Slow path: quotient=0. `negative = a.neg != b.neg`. Clear both signs. Repeatedly subtract denominator from numerator while numerator>0; count subtractions in quotient; if numerator goes negative, add denominator back once. remainder = numerator (non-negative magnitude). remove_leading_zeros(quotient). If negative: quotient.neg=true AND remainder.neg=true.
- Note: C truncates toward zero for fast path; slow path sets remainder sign = negative (same sign as quotient). For positive operands remainder non-negative.
- Division by zero: C UB (fast path divides by 0). Not tested.

### `div(&self, other)`  (C `bigint_div`, 493-502)
- Fast path: `from_int(to_int(a)/to_int(b))`.
- Else `divmod(a,b).0`.

### `mod(&self, other)`  (C `bigint_mod`, 504-514)
- Fast path: `from_int(to_int(a)%to_int(b))`.
- Else `divmod(a,b).1`.

---

## Powers

### `pow(&self, exponent) -> BigInt`  (C `bigint_pow`, 516-535)
- If exponent negative → return 0.
- result=1; if exponent zero → return 1.
- Loop: result = result * base; exponent -= 1; until exponent zero. (Naive repeated multiply.)
- Tests: test2 (2^10=1024).

### `fast_pow(&self, exponent, modulo) -> BigInt`  (C `bigint_fast_pow`, 540-654)
Modular exponentiation `a^b mod m`.
- **Fast path:** if a,b,m all is_64_bit → i64 loop: `base=a%m; result=1; while exp>0 { if exp&1 result=result*base%m; exp>>=1; base=base*base%m }` return from_int(result). (i64 overflow possible; tests: 745232^67121 mod 1022117 = 97, all fit is_64_bit since <10 digits.)
- Slow path: if b negative → 0. If b zero → 1. `a = a mod m`; result = a; b_save = b; b -= 1; pow=1. Loop: while b/2 > 0: result = result*result mod m; b = b/2; pow = pow+pow. Then b_save = b_save - pow. If b_save odd: result = result*a mod m; b_save -=1; pow+=1. If b_save < 5: while b_save != 0: result=result*a mod m; b_save-=1; pow+=1; return result. Else recurse: subpart = fast_pow(a, b_save, m); result = result*subpart mod m; return result.
- Tests: test2 (fast path), test3 test4 (2^1234 mod 10007, slow path since 1234 is 4 digits but... 2,1234,10007 all <10 digits → fast path actually. 10007 is 5 digits <10 → is_64_bit true. So fast path.)

---

## Number theory

### `modinv(&self, modulo) -> BigInt`  (C `bigint_modinv`, 656-731)
Extended Euclidean. m0=m; y=0; x=1; q=0; t=0; a=copy(a); m=copy(m).
Loop while a != 0:
- q = m / a
- t = m - q*a
- m = a; a = t
- t = y - q*x
- y = x; x = t
After loop: if m < 0: m += m0. If m == 1: result = y mod m0; if result<0: result += m0; return result. Else return 0.
- Tests: test2 (17 modinv 43; check 17*z mod 43 == 1).

### `sqrt(&self) -> BigInt`  (C `bigint_sqrt`, 733-764)
Integer sqrt via binary search. one=1,two=2,low=0,high=copy(n),mid=0.
While low<high: mid=(low+high)/2; if mid*mid < n: low=mid+1 else high=mid. Return low.
- This is **ceil-ish**: for n=100 returns 10; for n=101 returns 11 (test2 asserts sqrt(101)==11). So it returns the smallest integer whose square >= n? Let's verify: binary search for first `low` with `low*low >= n`? Condition `mid*mid < n → low=mid+1` else `high=mid`. Terminates with low = smallest x with x*x >= n. For 100: x=10 (100>=100) → 10. For 101: x=11 (121>=101) → 11. Yes: **ceiling sqrt**.
- Tests: test2 (100→10, 101→11), test3 test6 (sqrt(123412341), result unused).

### `is_prime(&self) -> bool`  (C `bigint_is_prime`, 774-822)
- If even → false. (So 2 → false! even check first.)
- If size>1 and last digit is 5 or 0 → false.
- Sum digits; if sum mod 3 == 0 → false.
- sqrt_n = sqrt(n). For i from 2 to sqrt_n inclusive: if n mod i == 0 → false.
- Else true.
- Note: 2 returns false (even), 3: odd, sum=3 mod3=0 → false. So small primes 2,3 return false. 17: odd, not 5/0, sum=8 not div3, sqrt=5 (ceil sqrt of 17 = 5), check 2..5: 17%2,17%3,17%5 none zero → true. 18 even → false.
- Tests: test2 (17 true, 18 false), test3 test5 (large number, result printed only).

---

## Misc

### `delete(a: &mut BigInt)`  (C `bigint_delete`, 828-833)
C frees digits, sets digits=NULL, is_negative=false, size=0. In Rust there is no free; reset `a` to a zero value: `a.negative=false; a.digits=vec![0]` (or clear). Since Rust owns memory, `delete` is essentially a no-op reset. No test calls it directly (Rust tests rely on Drop). Implement as reset to zero for API completeness.

---

## Test coverage summary
- test1: from_int, mul (huge), from_str, Display, PartialEq.
- test2: from_int, from_str, eq, le/ge/lt/gt, add, sub, mul, div, mod, pow, modinv, sqrt, is_prime, fast_pow.
- test3: from_str, clone, add/sub/mul/div/mod, comparisons, fast_pow, is_prime, sqrt.
