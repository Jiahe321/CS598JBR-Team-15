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
        let mut leading = 0usize;
        for &d in &self.digits {
            if d == 0 {
                leading += 1;
            } else {
                break;
            }
        }
        if leading > 0 {
            if leading >= self.digits.len() {
                self.digits = vec![0];
                return;
            }
            self.digits.drain(0..leading);
        }
    }

    pub fn from_int(n: i64) -> Self {
        let negative = n < 0;
        let mut m = n.unsigned_abs();
        let mut digits = Vec::new();
        if m == 0 {
            digits.push(0);
        } else {
            while m > 0 {
                digits.push((m % 10) as u8);
                m /= 10;
            }
            digits.reverse();
        }
        let mut result = BigInt { negative, digits };
        result.remove_leading_zeros();
        result
    }

    pub fn to_int(&self) -> i64 {
        let mut result: i64 = 0;
        for &d in &self.digits {
            result = result.wrapping_mul(10);
            result = result.wrapping_add(d as i64);
        }
        if self.negative {
            result = result.wrapping_neg();
        }
        result
    }

    #[allow(clippy::should_implement_trait)]
    pub fn from_str(s: &str) -> Self {
        let mut negative = false;
        let mut chars = s.chars();
        let mut rest = s;
        if let Some(first) = chars.next() {
            if first == '-' {
                negative = true;
                rest = &s[first.len_utf8()..];
            }
        }
        let digits: Vec<u8> = rest
            .chars()
            .map(|c| (c as u32).wrapping_sub('0' as u32) as u8)
            .collect();
        BigInt { negative, digits }
    }

    pub fn copy(&self) -> BigInt {
        self.clone()
    }

    pub fn print(&self) {
        print!("{self}");
    }

    pub fn is_zero(&self) -> bool {
        let mut n = self.clone();
        n.remove_leading_zeros();
        n.digits.len() == 1 && n.digits[0] == 0
    }

    pub fn lt_zero(&self) -> bool {
        let mut n = self.clone();
        n.remove_leading_zeros();
        if n.digits.len() == 1 && n.digits[0] == 0 {
            return false;
        }
        n.negative
    }

    pub fn gt_zero(&self) -> bool {
        let mut n = self.clone();
        n.remove_leading_zeros();
        if n.digits.len() == 1 && n.digits[0] == 0 {
            return false;
        }
        !n.negative
    }

    pub fn lezero(&self) -> bool {
        let mut n = self.clone();
        n.remove_leading_zeros();
        if n.digits.len() == 1 && n.digits[0] == 0 {
            return true;
        }
        n.negative
    }

    pub fn gezero(&self) -> bool {
        let mut n = self.clone();
        n.remove_leading_zeros();
        if n.digits.len() == 1 && n.digits[0] == 0 {
            return true;
        }
        !n.negative
    }

    pub fn abs(&self) -> Self {
        let mut r = self.clone();
        r.negative = false;
        r
    }

    pub fn add(&self, other: &Self) -> Self {
        if self.negative && other.negative {
            let mut r = add_magnitudes(self, other);
            r.negative = true;
            return r;
        }
        if self.negative {
            let a = self.abs();
            return other.sub(&a);
        }
        if other.negative {
            let b = other.abs();
            return self.sub(&b);
        }
        add_magnitudes(self, other)
    }

    pub fn sub(&self, other: &Self) -> Self {
        if self.negative && other.negative {
            let a = self.abs();
            let b = other.abs();
            let mut r = add_magnitudes(&b, &a);
            r.negative = true;
            return r;
        }
        if self.negative {
            let mut b = other.clone();
            b.negative = true;
            return self.add(&b);
        }
        if other.negative {
            let b = other.abs();
            return self.add(&b);
        }
        // both non-negative
        let is_negative = lt(self, other);
        let a_gt = gt(self, other);
        let larger = if a_gt { self } else { other };
        let smaller = if a_gt { other } else { self };
        let size = larger.digits.len().max(smaller.digits.len());
        let mut digits = vec![0u8; size];
        let mut carry: i64 = 0;
        for i in 0..size {
            let mut diff = carry;
            if i < larger.digits.len() {
                diff += larger.digits[larger.digits.len() - i - 1] as i64;
            }
            if i < smaller.digits.len() {
                diff -= smaller.digits[smaller.digits.len() - i - 1] as i64;
            }
            if diff < 0 {
                diff += 10;
                carry = -1;
            } else {
                carry = 0;
            }
            digits[size - i - 1] = diff as u8;
        }
        let mut result = BigInt {
            negative: false,
            digits,
        };
        result.remove_leading_zeros();
        result.negative = is_negative;
        result
    }

    pub fn inc(&mut self) {
        let one = BigInt::from_str("1");
        *self = self.add(&one);
    }

    pub fn dec(&mut self) {
        let one = BigInt::from_str("1");
        *self = self.sub(&one);
    }

    pub fn mul(&self, other: &Self) -> Self {
        if self.is_64_bit() && other.is_64_bit() {
            return BigInt::from_int(self.to_int().wrapping_mul(other.to_int()));
        }
        let a = &self.digits;
        let b = &other.digits;
        let size = a.len() + b.len();
        let mut acc = vec![0i64; size];
        for i in 0..a.len() {
            for j in 0..b.len() {
                acc[size - i - j - 1] += (a[a.len() - i - 1] as i64) * (b[b.len() - j - 1] as i64);
            }
        }
        let mut carry: i64 = 0;
        for i in 0..size {
            let sum = acc[size - i - 1] + carry;
            acc[size - i - 1] = sum % 10;
            carry = sum / 10;
        }
        let mut digits: Vec<u8> = acc.iter().map(|&x| x as u8).collect();
        if carry > 0 {
            digits.insert(0, carry as u8);
        }
        let mut result = BigInt {
            negative: self.negative != other.negative,
            digits,
        };
        result.remove_leading_zeros();
        result
    }

    pub fn divmod(&self, other: &Self) -> (Self, Self) {
        if self.is_64_bit() && other.is_64_bit() {
            let a = self.to_int();
            let b = other.to_int();
            let q = a / b;
            let r = a % b;
            return (BigInt::from_int(q), BigInt::from_int(r));
        }
        let mut quotient = BigInt::from_str("0");
        let negative = self.negative != other.negative;
        let mut numerator = self.clone();
        numerator.negative = false;
        let mut denominator = other.clone();
        denominator.negative = false;

        while numerator.gt_zero() {
            numerator = numerator.sub(&denominator);
            if numerator.lt_zero() {
                break;
            }
            quotient.inc();
        }
        if numerator.lt_zero() {
            numerator = numerator.add(&denominator);
        }
        let mut remainder = numerator;
        quotient.remove_leading_zeros();
        if negative {
            quotient.negative = true;
            remainder.negative = true;
        }
        (quotient, remainder)
    }

    pub fn div(&self, other: &Self) -> Self {
        if self.is_64_bit() && other.is_64_bit() {
            return BigInt::from_int(self.to_int() / other.to_int());
        }
        self.divmod(other).0
    }

    pub fn r#mod(&self, other: &Self) -> Self {
        if self.is_64_bit() && other.is_64_bit() {
            return BigInt::from_int(self.to_int() % other.to_int());
        }
        self.divmod(other).1
    }

    pub fn pow(&self, exponent: &Self) -> Self {
        if exponent.negative {
            return BigInt::from_str("0");
        }
        let mut result = BigInt::from_str("1");
        if exponent.is_zero() {
            return result;
        }
        let mut b = exponent.clone();
        while !b.is_zero() {
            result = result.mul(self);
            b.dec();
        }
        result
    }

    pub fn fast_pow(&self, exponent: &Self, modulo: &Self) -> Self {
        if self.is_64_bit() && exponent.is_64_bit() && modulo.is_64_bit() {
            let mut result: i64 = 1;
            let mut base = self.to_int();
            let mut exp = exponent.to_int();
            let m = modulo.to_int();
            base %= m;
            while exp > 0 {
                if exp % 2 == 1 {
                    result = (result.wrapping_mul(base)) % m;
                }
                exp >>= 1;
                base = (base.wrapping_mul(base)) % m;
            }
            return BigInt::from_int(result);
        }

        if exponent.negative {
            return BigInt::from_str("0");
        }
        if exponent.is_zero() {
            return BigInt::from_str("1");
        }

        let mut b = exponent.clone();
        let a = self.r#mod(modulo);
        let mut result = a.clone();
        let mut b_save = b.clone();
        b.dec();

        let mut pow = BigInt::from_str("1");
        loop {
            let two = BigInt::from_str("2");
            let tmp2 = b.div(&two);
            if !tmp2.gt_zero() {
                break;
            }
            result = result.mul(&result).r#mod(modulo);
            b = b.div(&two);
            pow = pow.add(&pow);
        }

        b_save = b_save.sub(&pow);

        if b_save.is_odd() {
            result = result.mul(&a).r#mod(modulo);
            b_save.dec();
            pow.inc();
        }

        if lt(&b_save, &BigInt::from_int(5)) {
            while !b_save.is_zero() {
                result = result.mul(&a).r#mod(modulo);
                b_save.dec();
                pow.inc();
            }
            return result;
        }

        let subpart = a.fast_pow(&b_save, modulo);
        result = result.mul(&subpart);
        result = result.r#mod(modulo);
        result
    }

    pub fn modinv(&self, modulo: &Self) -> Self {
        let m0 = modulo.clone();
        let mut y = BigInt::from_str("0");
        let mut x = BigInt::from_str("1");
        let mut q = BigInt::from_str("0");
        let mut t = BigInt::from_str("0");
        let mut a = self.clone();
        let mut m = modulo.clone();

        while !a.is_zero() {
            q = m.div(&a);
            t = m.sub(&q.mul(&a));
            m = a.clone();
            a = t.clone();
            t = y.sub(&q.mul(&x));
            y = x.clone();
            x = t.clone();
        }
        if m.lt_zero() {
            m = m.add(&m0);
        }
        let one = BigInt::from_str("1");
        if m == one {
            let mut result = y.r#mod(&m0);
            if result.lt_zero() {
                result = result.add(&m0);
            }
            return result;
        }
        BigInt::from_int(0)
    }

    pub fn sqrt(&self) -> Self {
        let one = BigInt::from_str("1");
        let two = BigInt::from_str("2");
        let mut low = BigInt::from_str("0");
        let mut high = self.clone();
        while lt(&low, &high) {
            let tmp1 = low.add(&high);
            let mid = tmp1.div(&two);
            let sq = mid.mul(&mid);
            if lt(&sq, self) {
                low = mid.add(&one);
            } else {
                high = mid;
            }
        }
        low
    }

    pub fn is_even(&self) -> bool {
        self.digits[self.digits.len() - 1] % 2 == 0
    }

    pub fn is_odd(&self) -> bool {
        self.digits[self.digits.len() - 1] % 2 == 1
    }

    pub fn is_prime(&self) -> bool {
        if self.is_even() {
            return false;
        }
        let last = self.digits[self.digits.len() - 1];
        if self.digits.len() > 1 && (last == 5 || last == 0) {
            return false;
        }
        let mut sum = BigInt::from_str("0");
        for &d in &self.digits {
            sum = sum.add(&BigInt::from_int(d as i64));
        }
        let three = BigInt::from_str("3");
        if sum.r#mod(&three).is_zero() {
            return false;
        }
        let sqrt_n = self.sqrt();
        let mut i = BigInt::from_str("2");
        while le(&i, &sqrt_n) {
            if self.r#mod(&i).is_zero() {
                return false;
            }
            i.inc();
        }
        true
    }
}

fn add_magnitudes(a: &BigInt, b: &BigInt) -> BigInt {
    let size = a.digits.len().max(b.digits.len());
    let mut digits = vec![0u8; size];
    let mut carry: i64 = 0;
    for i in 0..size {
        let mut sum = carry;
        if i < a.digits.len() {
            sum += a.digits[a.digits.len() - i - 1] as i64;
        }
        if i < b.digits.len() {
            sum += b.digits[b.digits.len() - i - 1] as i64;
        }
        digits[size - i - 1] = (sum % 10) as u8;
        carry = sum / 10;
    }
    if carry > 0 {
        digits.insert(0, carry as u8);
    }
    let mut result = BigInt {
        negative: false,
        digits,
    };
    result.remove_leading_zeros();
    result
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
    for i in 0..a.digits.len() {
        if a.digits[i] > b.digits[i] {
            return !a.negative;
        }
        if a.digits[i] < b.digits[i] {
            return a.negative;
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
    a.negative = false;
    a.digits = vec![0];
}

impl std::ops::Neg for BigInt {
    type Output = BigInt;
    fn neg(self) -> BigInt {
        let mut r = self;
        r.negative = !r.negative;
        r
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
            None
        }
    }
}

impl fmt::Display for BigInt {
    fn fmt(&self, f: &mut fmt::Formatter) -> fmt::Result {
        if self.negative {
            write!(f, "-")?;
        }
        for &d in &self.digits {
            write!(f, "{d}")?;
        }
        Ok(())
    }
}
