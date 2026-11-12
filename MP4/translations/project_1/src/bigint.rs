use std::cmp::Ordering;
use std::fmt;

#[derive(Clone, Debug)]
pub struct BigInt {
    negative: bool,
    digits: Vec<u8>,
}

impl BigInt {
    pub fn zero() -> Self {
        BigInt {
            negative: false,
            digits: vec![0],
        }
    }

    pub fn is_64_bit(&self) -> bool {
        self.digits.len() < 10
    }

    pub fn remove_leading_zeros(&mut self) {
        let count = self.digits.iter().take_while(|&&d| d == 0).count();
        if count >= self.digits.len() {
            self.digits = vec![0];
        } else if count > 0 {
            self.digits.drain(0..count);
        }
    }

    pub fn from_int(n: i64) -> Self {
        if n == 0 {
            return BigInt::zero();
        }
        let negative = n < 0;
        let mut mag = n.unsigned_abs();
        let mut digits = Vec::new();
        while mag > 0 {
            digits.push((mag % 10) as u8);
            mag /= 10;
        }
        digits.reverse();
        let mut result = BigInt { negative, digits };
        result.remove_leading_zeros();
        result
    }

    pub fn to_int(&self) -> i64 {
        let mut result: i64 = 0;
        for &d in &self.digits {
            result = result.wrapping_mul(10).wrapping_add(d as i64);
        }
        if self.negative {
            result = result.wrapping_neg();
        }
        result
    }

    pub fn from_str(s: &str) -> Self {
        let (negative, rest) = match s.strip_prefix('-') {
            Some(r) => (true, r),
            None => (false, s),
        };
        if rest.is_empty() {
            return BigInt::zero();
        }
        let digits: Vec<u8> = rest.bytes().map(|b| b - b'0').collect();
        BigInt { negative, digits }
    }

    pub fn copy(&self) -> BigInt {
        self.clone()
    }

    pub fn print(&self) {
        print!("{}", self);
    }

    pub fn is_zero(&self) -> bool {
        let mut c = self.clone();
        c.remove_leading_zeros();
        c.digits.len() == 1 && c.digits[0] == 0
    }

    pub fn lt_zero(&self) -> bool {
        if self.is_zero() {
            false
        } else {
            self.negative
        }
    }

    pub fn gt_zero(&self) -> bool {
        if self.is_zero() {
            false
        } else {
            !self.negative
        }
    }

    pub fn lezero(&self) -> bool {
        if self.is_zero() {
            true
        } else {
            self.negative
        }
    }

    pub fn gezero(&self) -> bool {
        if self.is_zero() {
            true
        } else {
            !self.negative
        }
    }

    pub fn abs(&self) -> Self {
        let mut c = self.clone();
        c.negative = false;
        c
    }

    pub fn add(&self, other: &Self) -> Self {
        if self.negative == other.negative {
            let mut r = add_magnitude(&self.digits, &other.digits);
            r.negative = self.negative;
            r.remove_leading_zeros();
            if r.is_zero() {
                r.negative = false;
            }
            r
        } else if self.negative {
            // self negative, other positive: other - |self|
            sub_magnitude(&other.digits, &self.digits)
        } else {
            // self positive, other negative: self - |other|
            sub_magnitude(&self.digits, &other.digits)
        }
    }

    pub fn sub(&self, other: &Self) -> Self {
        let neg_other = BigInt {
            negative: !other.negative,
            digits: other.digits.clone(),
        };
        self.add(&neg_other)
    }

    pub fn inc(&mut self) {
        *self = self.add(&BigInt::from_int(1));
    }

    pub fn dec(&mut self) {
        *self = self.sub(&BigInt::from_int(1));
    }

    pub fn mul(&self, other: &Self) -> Self {
        let negative = self.negative != other.negative;
        let a = &self.digits;
        let b = &other.digits;
        let mut acc = vec![0u32; a.len() + b.len()];
        for (i, &da) in a.iter().rev().enumerate() {
            for (j, &db) in b.iter().rev().enumerate() {
                acc[i + j] += (da as u32) * (db as u32);
            }
        }
        // normalize
        let mut carry = 0u32;
        for slot in acc.iter_mut() {
            let v = *slot + carry;
            *slot = v % 10;
            carry = v / 10;
        }
        while carry > 0 {
            acc.push(carry % 10);
            carry /= 10;
        }
        let mut digits: Vec<u8> = acc.into_iter().rev().map(|d| d as u8).collect();
        if digits.is_empty() {
            digits.push(0);
        }
        let mut result = BigInt { negative, digits };
        result.remove_leading_zeros();
        if result.is_zero() {
            result.negative = false;
        }
        result
    }

    pub fn divmod(&self, other: &Self) -> (Self, Self) {
        let negative_q = self.negative != other.negative;
        let a = self.abs();
        let b = other.abs();
        let (q_digits, r_digits) = long_division(&a.digits, &b.digits);
        let mut q = BigInt {
            negative: negative_q,
            digits: q_digits,
        };
        q.remove_leading_zeros();
        if q.is_zero() {
            q.negative = false;
        }
        let mut r = BigInt {
            negative: self.negative,
            digits: r_digits,
        };
        r.remove_leading_zeros();
        if r.is_zero() {
            r.negative = false;
        }
        (q, r)
    }

    pub fn div(&self, other: &Self) -> Self {
        self.divmod(other).0
    }

    pub fn r#mod(&self, other: &Self) -> Self {
        self.divmod(other).1
    }

    pub fn pow(&self, exponent: &Self) -> Self {
        if exponent.negative {
            return BigInt::zero();
        }
        let mut exp = exponent.clone();
        exp.remove_leading_zeros();
        let mut result = BigInt::from_int(1);
        let one = BigInt::from_int(1);
        let mut e = BigInt::zero();
        while e < exp {
            result = result.mul(self);
            e = e.add(&one);
        }
        result
    }

    pub fn fast_pow(&self, exponent: &Self, modulo: &Self) -> Self {
        if exponent.negative {
            return BigInt::zero();
        }
        let mut exp = exponent.clone();
        exp.remove_leading_zeros();
        if exp.is_zero() {
            return BigInt::from_int(1);
        }
        let two = BigInt::from_int(2);
        let mut base = self.r#mod(modulo);
        if base.negative {
            base = base.add(modulo);
        }
        let mut result = BigInt::from_int(1);
        while !exp.is_zero() {
            if exp.is_odd() {
                result = result.mul(&base).r#mod(modulo);
            }
            exp = exp.div(&two);
            if !exp.is_zero() {
                base = base.mul(&base).r#mod(modulo);
            }
        }
        if result.negative {
            result = result.add(modulo);
        }
        result
    }

    pub fn modinv(&self, modulo: &Self) -> Self {
        let m0 = modulo.clone();
        let mut a = self.r#mod(modulo);
        if a.negative {
            a = a.add(modulo);
        }
        let mut m = modulo.clone();
        let mut y = BigInt::zero();
        let mut x = BigInt::from_int(1);
        while !a.is_zero() {
            let (q, _) = m.divmod(&a);
            let t = m.sub(&q.mul(&a));
            m = a;
            a = t;
            let t2 = y.sub(&q.mul(&x));
            y = x;
            x = t2;
        }
        if m.lt_zero() {
            m = m.add(&m0);
        }
        if m == BigInt::from_int(1) {
            let mut result = y.r#mod(&m0);
            if result.negative {
                result = result.add(&m0);
            }
            result
        } else {
            BigInt::zero()
        }
    }

    pub fn sqrt(&self) -> Self {
        // ceil(sqrt(n)) via binary search, matching C.
        let mut low = BigInt::zero();
        let mut high = self.clone();
        let two = BigInt::from_int(2);
        while low < high {
            let mid = low.add(&high).div(&two);
            let sq = mid.mul(&mid);
            if sq < *self {
                low = mid.add(&BigInt::from_int(1));
            } else {
                high = mid;
            }
        }
        low
    }

    pub fn is_even(&self) -> bool {
        self.digits.last().map_or(true, |&d| d % 2 == 0)
    }

    pub fn is_odd(&self) -> bool {
        self.digits.last().map_or(false, |&d| d % 2 == 1)
    }

    pub fn is_prime(&self) -> bool {
        if self.is_even() {
            return false;
        }
        if self.digits.len() > 1 {
            if let Some(&last) = self.digits.last() {
                if last == 5 || last == 0 {
                    return false;
                }
            }
        }
        let digit_sum: u32 = self.digits.iter().map(|&d| d as u32).sum();
        if digit_sum % 3 == 0 {
            return false;
        }
        let limit = self.sqrt();
        let mut i = BigInt::from_int(2);
        let one = BigInt::from_int(1);
        while i <= limit {
            if self.r#mod(&i).is_zero() {
                return false;
            }
            i = i.add(&one);
        }
        true
    }
}

fn add_magnitude(a: &[u8], b: &[u8]) -> BigInt {
    let mut result = Vec::new();
    let mut carry = 0u8;
    let mut i = a.len();
    let mut j = b.len();
    while i > 0 || j > 0 || carry > 0 {
        let da = if i > 0 {
            i -= 1;
            a[i]
        } else {
            0
        };
        let db = if j > 0 {
            j -= 1;
            b[j]
        } else {
            0
        };
        let s = da + db + carry;
        result.push(s % 10);
        carry = s / 10;
    }
    result.reverse();
    if result.is_empty() {
        result.push(0);
    }
    BigInt {
        negative: false,
        digits: result,
    }
}

/// Compute |a| - |b| assuming |a| >= |b|. Result sign determined by comparison.
fn sub_magnitude(a: &[u8], b: &[u8]) -> BigInt {
    // Compare magnitudes
    let a_trim = trim(a);
    let b_trim = trim(b);
    let a_ge_b = if a_trim.len() != b_trim.len() {
        a_trim.len() > b_trim.len()
    } else {
        a_trim >= b_trim
    };
    let (big, small, negative) = if a_ge_b {
        (a_trim, b_trim, false)
    } else {
        (b_trim, a_trim, true)
    };
    let mut result = Vec::new();
    let mut borrow = 0i32;
    let mut i = big.len();
    let mut j = small.len();
    while i > 0 {
        i -= 1;
        let db = if j > 0 {
            j -= 1;
            small[j] as i32
        } else {
            0
        };
        let mut diff = big[i] as i32 - db - borrow;
        if diff < 0 {
            diff += 10;
            borrow = 1;
        } else {
            borrow = 0;
        }
        result.push(diff as u8);
    }
    result.reverse();
    let mut r = BigInt {
        negative,
        digits: result,
    };
    r.remove_leading_zeros();
    if r.is_zero() {
        r.negative = false;
    }
    r
}

fn trim(a: &[u8]) -> &[u8] {
    let count = a.iter().take_while(|&&d| d == 0).count();
    if count >= a.len() {
        &a[a.len() - 1..]
    } else {
        &a[count..]
    }
}

/// Long division on decimal digit slices. Returns (quotient_digits, remainder_digits).
fn long_division(a: &[u8], b: &[u8]) -> (Vec<u8>, Vec<u8>) {
    let a = trim(a);
    let b = trim(b);
    // If divisor is zero, avoid infinite loop; return zero.
    if b.len() == 1 && b[0] == 0 {
        return (vec![0], vec![0]);
    }
    let mut quotient = Vec::new();
    let mut remainder: Vec<u8> = Vec::new();
    for &digit in a {
        // remainder = remainder * 10 + digit
        remainder.push(digit);
        // trim leading zeros of remainder
        let count = remainder.iter().take_while(|&&d| d == 0).count();
        if count > 0 && count < remainder.len() {
            remainder.drain(0..count);
        } else if count >= remainder.len() {
            remainder = vec![0];
        }
        // find how many times b fits into remainder (0..9)
        let mut q = 0u8;
        while cmp_mag(&remainder, b) != Ordering::Less {
            remainder = sub_mag_vec(&remainder, b);
            q += 1;
        }
        quotient.push(q);
    }
    if quotient.is_empty() {
        quotient.push(0);
    }
    // trim quotient
    let count = quotient.iter().take_while(|&&d| d == 0).count();
    if count >= quotient.len() {
        quotient = vec![0];
    } else if count > 0 {
        quotient.drain(0..count);
    }
    if remainder.is_empty() {
        remainder.push(0);
    }
    (quotient, remainder)
}

fn cmp_mag(a: &[u8], b: &[u8]) -> Ordering {
    let a = trim(a);
    let b = trim(b);
    if a.len() != b.len() {
        return a.len().cmp(&b.len());
    }
    a.cmp(b)
}

fn sub_mag_vec(a: &[u8], b: &[u8]) -> Vec<u8> {
    let a = trim(a);
    let b = trim(b);
    let mut result = Vec::new();
    let mut borrow = 0i32;
    let mut i = a.len();
    let mut j = b.len();
    while i > 0 {
        i -= 1;
        let db = if j > 0 {
            j -= 1;
            b[j] as i32
        } else {
            0
        };
        let mut diff = a[i] as i32 - db - borrow;
        if diff < 0 {
            diff += 10;
            borrow = 1;
        } else {
            borrow = 0;
        }
        result.push(diff as u8);
    }
    result.reverse();
    let count = result.iter().take_while(|&&d| d == 0).count();
    if count >= result.len() {
        vec![0]
    } else if count > 0 {
        result.drain(0..count);
        result
    } else {
        result
    }
}

pub fn gt(a: &BigInt, b: &BigInt) -> bool {
    let mut a = a.clone();
    let mut b = b.clone();
    a.remove_leading_zeros();
    b.remove_leading_zeros();
    if a.digits.len() > b.digits.len() {
        return !a.negative;
    }
    if a.digits.len() < b.digits.len() {
        return a.negative;
    }
    for (da, db) in a.digits.iter().zip(b.digits.iter()) {
        if da != db {
            return if da > db { !a.negative } else { a.negative };
        }
    }
    false
}

pub fn lt(a: &BigInt, b: &BigInt) -> bool {
    !ge(a, b)
}

pub fn ge(a: &BigInt, b: &BigInt) -> bool {
    gt(a, b) || a == b
}

pub fn le(a: &BigInt, b: &BigInt) -> bool {
    !gt(a, b)
}

pub fn delete(a: &mut BigInt) {
    *a = BigInt::zero();
}

impl std::ops::Neg for BigInt {
    type Output = BigInt;
    fn neg(self) -> BigInt {
        if self.is_zero() {
            BigInt::zero()
        } else {
            BigInt {
                negative: !self.negative,
                digits: self.digits,
            }
        }
    }
}

impl PartialEq for BigInt {
    fn eq(&self, other: &Self) -> bool {
        let mut a = self.clone();
        let mut b = other.clone();
        a.remove_leading_zeros();
        b.remove_leading_zeros();
        if a.digits.len() != b.digits.len() {
            return false;
        }
        if a.negative != b.negative {
            return false;
        }
        a.digits == b.digits
    }
}

impl Eq for BigInt {}

impl PartialOrd for BigInt {
    fn partial_cmp(&self, other: &Self) -> Option<Ordering> {
        if self == other {
            Some(Ordering::Equal)
        } else if gt(self, other) {
            Some(Ordering::Greater)
        } else if lt(self, other) {
            Some(Ordering::Less)
        } else {
            Some(Ordering::Equal)
        }
    }
}

impl fmt::Display for BigInt {
    fn fmt(&self, f: &mut fmt::Formatter) -> fmt::Result {
        if self.negative {
            write!(f, "-")?;
        }
        for &d in &self.digits {
            write!(f, "{}", d)?;
        }
        Ok(())
    }
}
