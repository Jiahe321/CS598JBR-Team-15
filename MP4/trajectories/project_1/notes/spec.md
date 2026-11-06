# BigInt Specification

## Module Map
- **C source**: `c/src/bigint.h` (header-only, all implementations inline)
- **Rust module**: `src/bigint.rs` (single module `bigint`)

## Data Structures

### C: `bigint` struct
```c
typedef struct {
    bool is_negative;
    int64_t *digits;  // base-10 digits, most-significant first
    size_t size;      // number of digits
} bigint;
```

### Rust: `BigInt` struct
```rust
pub struct BigInt {
    negative: bool,
    digits: Vec<u8>,  // base-10 digits, most-significant first
}
```

## Global/Static State
None. All state is contained in the struct instances.

## Implementation Order (dependencies)
1. **Core constructors & memory**: `zero()`, `from_int()`, `from_str()`, `copy()`, `remove_leading_zeros()`, `is_64_bit()`
2. **Display & basic queries**: `print()` / `Display`, `is_zero()`, `lt_zero()`, `gt_zero()`, `lezero()`, `gezero()`, `to_int()`
3. **Comparison**: `gt()`, `lt()`, `ge()`, `le()`, `PartialEq`, `Eq`, `PartialOrd`
4. **Unary ops**: `abs()`, `Neg`
5. **Basic arithmetic**: `add()`, `sub()`, `inc()`, `dec()`
6. **Multiplication**: `mul()`
7. **Division**: `divmod()`, `div()`, `mod()`
8. **Power operations**: `pow()`, `fast_pow()`
9. **Advanced**: `modinv()`, `sqrt()`, `is_even()`, `is_odd()`, `is_prime()`
10. **Cleanup**: `delete()` (no-op in Rust, but kept for API compatibility)

## Key Design Decisions (C → Rust)

| C Construct | Rust Translation |
|-------------|------------------|
| `int64_t* digits` + `size` | `Vec<u8>` (base-10, 0-9 each) |
| `malloc`/`free`/`realloc` | `Vec` automatic memory management |
| `bigint_delete()` | No-op (RAII), but keep function for API compat |
| Pass/return by value (shallow copy) | `Clone` for explicit copies; methods take `&self` |
| `bigint_remove_leading_zeros(&mut)` | `remove_leading_zeros(&mut self)` |
| `bool` returns | `bool` |
| `int64_t` for single digits | `u8` (values 0-9) |
| Output parameters (`*remainder`) | Return tuple `(quotient, remainder)` |
| `const char*` strings | `&str` |
| `assert(digit 0-9)` | Debug assertions or rely on invariants |

## Edge Cases from C Code
- **Zero representation**: size=1, digits[0]=0, is_negative=false
- **Leading zeros**: Removed by `bigint_remove_leading_zeros` before most operations
- **Negative zero**: Not possible after `remove_leading_zeros` (zero is never negative)
- **64-bit fast path**: Used for mul, div, mod, pow when both operands fit in 64 bits
- **Division by zero**: Not explicitly handled in C (UB); Rust should panic or handle gracefully
- **Modular inverse**: Returns 0 if no inverse exists (when gcd != 1)
- **Prime test**: Returns false for even numbers, numbers ending in 5, and numbers divisible by 3; then trial division up to sqrt(n)
- **Square root**: Binary search, returns floor(sqrt(n))
- **fast_pow**: Complex recursive algorithm with halving optimization

## Tests Mapping
- `src/bin/test1.rs` → factorial (tests mul, add, comparisons, from_int, from_str, Display)
- `src/bin/test2.rs` → basic operations (all core arithmetic, comparisons, pow, modinv, sqrt, is_prime, fast_pow)
- `src/bin/test3.rs` → large number operations (add, sub, mul, div, mod, fast_pow, is_prime, sqrt, clone)
