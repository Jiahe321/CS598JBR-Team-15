# BigInt Module Detailed Specification

## Struct Definition
```rust
#[derive(Clone, Debug)]
pub struct BigInt {
    negative: bool,
    digits: Vec<u8>,  // base-10, most-significant first, no leading zeros (except zero itself)
}
```

**Invariants:**
- `digits` is never empty
- If `digits == [0]`, then `negative == false`
- All digits are in range 0..=9
- No leading zeros (except the single zero digit)

---

## Constructor & Basic Methods

### `pub fn zero() -> Self`
**C:** `bigint_zero()`
**Returns:** BigInt representing 0 (negative=false, digits=[0])
**Tests:** Implicit in all tests

### `pub fn is_64_bit(&self) -> bool`
**C:** `bigint_is_64_bit(bigint n)`
**Purpose:** Check if value fits in i64 (for fast-path optimizations)
**Algorithm:** 
- If negative and size > 10 → false
- If negative and size < 10 → true
- If positive and size > 10 → false
- If positive and size < 10 → true
- If size == 10 → false (conservative)
**Returns:** `true` if fits in i64, `false` otherwise
**Note:** C version has a bug - it returns false for size==10 even if value fits. Replicate exactly.

### `pub fn remove_leading_zeros(&mut self)`
**C:** `bigint_remove_leading_zeros(bigint *n)`
**Purpose:** Normalize by removing leading zero digits
**Algorithm:**
- Count leading zeros from most-significant digit
- If all digits are zero → set size=1, digits[0]=0
- Else memmove remaining digits to front, update size
**Edge case:** Zero becomes `digits=[0], size=1, negative=false`

### `pub fn from_int(n: i64) -> Self`
**C:** `bigint_from_int(int64_t n)`
**Purpose:** Create BigInt from i64
**Algorithm:**
- Set negative = n < 0
- Work with absolute value
- Count digits by repeated division by 10
- Allocate digits array, fill from least-significant (n % 10)
- Call `remove_leading_zeros`
**Edge cases:** 
- n = 0 → digits=[0], negative=false
- n = i64::MIN → special handling (absolute value overflows i64)
  - C: `n = -n` on negative, but `-i64::MIN` is UB in C. In Rust, handle explicitly.

### `pub fn to_int(&self) -> i64`
**C:** `bigint_to_int(bigint n)`
**Purpose:** Convert to i64 (truncates if too large)
**Algorithm:** Iterate digits: `result = result * 10 + digit`, apply sign
**Note:** No overflow checking in C. Rust should match behavior (wrapping or panic? C has UB). Use `wrapping_mul`/`wrapping_add` to match.

### `pub fn from_str(s: &str) -> Self`
**C:** `bigint_from_string(const char *n)`
**Purpose:** Parse decimal string
**Algorithm:**
- Check leading '-' for negative
- Size = string length (after sign)
- Each char - '0' → digit
- No validation in C (assumes valid digits)
- No `remove_leading_zeros` called in C constructor!
**Edge cases:**
- Empty string? C: strlen=0 → size=0 → malloc(0) → UB
- Leading zeros preserved initially (e.g., "00123" → digits=[0,0,1,2,3])
- Caller must call `remove_leading_zeros` if needed
- Rust: Should we validate? Tests use valid strings. Keep simple, assume valid input.

### `pub fn copy(&self) -> BigInt`
**C:** `bigint_copy(bigint n)`
**Purpose:** Deep copy
**Algorithm:** Clone negative, size, allocate new digits array, memcpy
**Rust:** Just `self.clone()` (derives Clone)

### `pub fn print(&self)`
**C:** `bigint_print(bigint n)`
**Purpose:** Print to stdout
**Algorithm:** Print '-' if negative, then each digit
**Rust:** Implement `Display` trait; `print()` can call `println!("{}", self)`

---

## Query Methods

### `pub fn is_zero(&self) -> bool`
**C:** `bigint_eqzero(bigint n)`
**Algorithm:** Call `remove_leading_zeros`, check `size==1 && digits[0]==0`

### `pub fn lt_zero(&self) -> bool`
**C:** `bigint_ltzero(bigint n)`
**Algorithm:** Call `remove_leading_zeros`, return `negative && !(size==1 && digits[0]==0)`

### `pub fn gt_zero(&self) -> bool`
**C:** `bigint_gtzero(bigint n)`
**Algorithm:** Call `remove_leading_zeros`, return `!negative && !(size==1 && digits[0]==0)`

### `pub fn lezero(&self) -> bool`
**C:** `bigint_lezero(bigint n)`
**Algorithm:** Call `remove_leading_zeros`, return `negative || (size==1 && digits[0]==0)`

### `pub fn gezero(&self) -> bool`
**C:** `bigint_gezero(bigint n)`
**Algorithm:** Call `remove_leading_zeros`, return `!negative || (size==1 && digits[0]==0)`

### `pub fn abs(&self) -> Self`
**C:** `bigint_abs(bigint n)`
**Returns:** Copy with `negative = false`

---

## Comparison Functions (standalone + traits)

### `pub fn gt(a: &BigInt, b: &BigInt) -> bool`
**C:** `bigint_gt(bigint a, bigint b)`
**Algorithm:**
- Remove leading zeros from both
- If sizes differ: larger size wins (unless negative flips)
- If same size: compare digits lexicographically (most-significant first)
- Negative numbers: reverse comparison result

### `pub fn lt(a: &BigInt, b: &BigInt) -> bool`
**C:** `bigint_lt(a, b)` → `!bigint_ge(a, b)`

### `pub fn ge(a: &BigInt, b: &BigInt) -> bool`
**C:** `bigint_ge(a, b)` → `bigint_gt(a, b) || bigint_eq(a, b)`

### `pub fn le(a: &BigInt, b: &BigInt) -> bool`
**C:** `bigint_le(a, b)` → `!bigint_gt(a, b)`

### `impl PartialEq for BigInt`
**C:** `bigint_eq(bigint a, bigint b)`
**Algorithm:** Remove leading zeros, compare size, sign, then all digits

### `impl Eq for BigInt` (marker)

### `impl PartialOrd for BigInt`
**Returns:** `Some(Ordering)` using `gt`/`lt`/`eq`

---

## Arithmetic Operations

### `pub fn add(&self, other: &Self) -> Self`
**C:** `bigint_add(bigint a, bigint b)`
**Algorithm:**
- Handle signs:
  - Both positive: add magnitudes
  - Both negative: add magnitudes, result negative
  - Mixed: subtract smaller magnitude from larger, sign of larger
- Magnitude addition: iterate from least-significant digit, carry propagation
- Result size = max(a.size, b.size) + 1 (for carry)
- Normalize (remove leading zeros)

### `pub fn sub(&self, other: &Self) -> Self`
**C:** `bigint_sub(bigint a, bigint b)`
**Algorithm:** Delegates to add with sign manipulation:
- (-a) - (-b) = b - a = -(a - b) → add(b, a), negate
- (-a) - b = -(a + b) → add(a, b), negate
- a - (-b) = a + b → add(a, b)
- a - b (both positive): compare magnitudes, subtract smaller from larger, sign = a < b

### `pub fn inc(&mut self)`
**C:** `bigint_inc(bigint *n)`
**Algorithm:** `*n = add(*n, 1)`
**Rust:** `*self = self.add(&BigInt::from_int(1))`

### `pub fn dec(&mut self)`
**C:** `bigint_dec(bigint *n)`
**Algorithm:** `*n = sub(*n, 1)`

### `pub fn mul(&self, other: &Self) -> Self`
**C:** `bigint_mul(bigint a, bigint b)`
**Algorithm:**
- Fast path: if both `is_64_bit()`, convert to i64, multiply, `from_int`
- Slow path: grade-school multiplication (O(n²))
  - Result size = a.size + b.size
  - Initialize all digits to 0
  - For each digit pair: `result[i+j] += a[i] * b[j]` (from right)
  - Normalize carries (base 10)
  - Handle final carry
  - Remove leading zeros
  - Sign = a.negative != b.negative

### `pub fn divmod(&self, other: &Self) -> (Self, Self)`
**C:** `bigint_divmod(bigint numerator, bigint denominator, bigint *remainder)`
**Returns:** (quotient, remainder)
**Algorithm:**
- Fast path: both fit in i64 → use i64 division
- Slow path: repeated subtraction (very slow!)
  - Make both positive, track sign
  - Copy numerator
  - While numerator > 0: numerator -= denominator, quotient++
  - If numerator < 0: add denominator back
  - Remainder = final numerator
  - Apply sign to quotient and remainder (C makes both negative if signs differed)
- Remove leading zeros from quotient

**Note:** C's algorithm is extremely slow (O(n) subtractions). Tests use small numbers. Replicate exactly for compatibility.

### `pub fn div(&self, other: &Self) -> Self`
**C:** `bigint_div(bigint a, bigint b)`
**Returns:** Quotient only
**Algorithm:** Call `divmod`, discard remainder

### `pub fn r#mod(&self, other: &Self) -> Self`
**C:** `bigint_mod(bigint a, bigint b)`
**Returns:** Remainder only
**Algorithm:** Call `divmod`, return remainder

---

## Power Operations

### `pub fn pow(&self, exponent: &Self) -> Self`
**C:** `bigint_pow(bigint a, bigint b)`
**Algorithm:**
- If exponent negative → return 0 (C behavior)
- Result = 1
- While exponent > 0:
  - If exponent odd: result *= base
  - base *= base
  - exponent /= 2 (integer division)
- Uses `bigint_divmod` for division by 2

### `pub fn fast_pow(&self, exponent: &Self, modulo: &Self) -> Self`
**C:** `bigint_fast_pow(bigint a, bigint b, bigint m)`
**Algorithm:** Modular exponentiation with complex optimization:
- Fast path: all fit in i64 → use i64 modular exponentiation
- Slow path: recursive halving with precomputed powers
- Handles large exponents by breaking into powers of 2
- Very complex; replicate C logic exactly

**Note:** This is the most complex function. The C code has a specific algorithm with `pow` tracking powers of 2, `b_save` for remaining exponent, and recursive call for subpart.

---

## Advanced Operations

### `pub fn modinv(&self, modulo: &Self) -> Self`
**C:** `bigint_modinv(bigint a, bigint m)`
**Algorithm:** Extended Euclidean Algorithm
- Returns modular inverse of a modulo m (a * x ≡ 1 (mod m))
- If no inverse exists (gcd != 1), returns 0
- Tracks x, y such that a*x + m*y = gcd
- At end, if m == 1, return x mod m0 (original modulo)
- Else return 0

### `pub fn sqrt(&self) -> Self`
**C:** `bigint_sqrt(bigint n)`
**Algorithm:** Binary search for floor(sqrt(n))
- low = 0, high = n
- While low < high:
  - mid = (low + high) / 2
  - If mid² < n: low = mid + 1
  - Else: high = mid
- Return low

### `pub fn is_even(&self) -> bool`
**C:** `bigint_is_even(bigint n)`
**Returns:** Last digit (least significant) % 2 == 0

### `pub fn is_odd(&self) -> bool`
**C:** `bigint_is_odd(bigint n)`
**Returns:** Last digit % 2 == 1

### `pub fn is_prime(&self) -> bool`
**C:** `bigint_is_prime(bigint n)`
**Algorithm:**
- Even → false
- Ends in 5 or 0 (and size > 1) → false
- Sum of digits divisible by 3 → false
- Trial division from 2 to sqrt(n):
  - If n % i == 0 → false
- Return true

**Note:** Very slow for large numbers. Tests use small primes.

---

## Cleanup

### `pub fn delete(a: &mut BigInt)`
**C:** `bigint_delete(bigint n)`
**Purpose:** Free memory
**Rust:** No-op (RAII handles it). But keep for API compatibility.
**Implementation:** Clear digits, set negative=false (or just do nothing)

---

## Trait Implementations

### `impl Neg for BigInt`
**Returns:** `-self` (flip negative flag, unless zero)

### `impl fmt::Display for BigInt`
**Format:** Same as `bigint_print`: '-' if negative, then digits

---

## Test Coverage Summary

| Test File | Exercises |
|-----------|-----------|
| test1.rs | factorial (mul, add, from_int, from_str, comparisons, Display) |
| test2.rs | All basic ops, pow, modinv, sqrt, is_prime, fast_pow |
| test3.rs | Large numbers, clone, add/sub/mul/div/mod, fast_pow, is_prime, sqrt |

---

## Implementation Notes for Writer

1. **Digit storage**: Use `Vec<u8>` with most-significant digit at index 0 (matching C)
2. **Leading zeros**: Call `remove_leading_zeros` in constructors and after operations that may produce them
3. **Zero normalization**: Ensure zero is always `negative=false, digits=[0]`
4. **Performance**: The C algorithms are intentionally naive (repeated subtraction for division). Replicate exactly for test compatibility.
5. **i64::MIN handling**: In `from_int`, handle `i64::MIN` specially since `-i64::MIN` overflows.
6. **Division by zero**: C has UB. In Rust, panic with clear message.
7. **Clone vs Copy**: `BigInt` derives `Clone` but not `Copy` (has Vec). The `copy()` method should return `self.clone()`.
8. **delete()**: No-op but keep signature for API compatibility.
