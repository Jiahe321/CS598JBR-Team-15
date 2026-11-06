use std::cmp::Ordering;
use std::fmt;

#[derive(Clone, Debug)]
pub struct BigInt {
    negative: bool,
    digits: Vec<u8>,  // base-10 digits, most-significant first
}

impl BigInt {
    pub fn zero() -> Self {
        BigInt {
            negative: false,
            digits: vec![0],
        }
    }

    pub fn is_64_bit(&self) -> bool {
        if self.negative {
            if self.digits.len() > 10 {
                return false;
            }
            if self.digits.len() < 10 {
                return true;
            }
        } else {
            if self.digits.len() > 10 {
                return false;
            }
            if self.digits.len() < 10 {
                return true;
            }
        }
        false
    }

    pub fn remove_leading_zeros(&mut self) {
        let mut leading_zeros = 0;
        for &digit in &self.digits {
            if digit == 0 {
                leading_zeros += 1;
            } else {
                break;
            }
        }

        if leading_zeros > 0 {
            if leading_zeros >= self.digits.len() {
                self.digits = vec![0];
                self.negative = false;
            } else {
                self.digits.drain(0..leading_zeros);
            }
        }
    }

    pub fn from_int(n: i64) -> Self {
        let mut result = BigInt::zero();
        
        if n < 0 {
            result.negative = true;
            // Handle i64::MIN specially since -i64::MIN overflows
            if n == i64::MIN {
                // i64::MIN = -9223372036854775808
                // We'll build it digit by digit
                result.digits = vec![9,2,2,3,3,7,2,0,3,6,8,5,4,7,7,5,8,0,8];
                result.remove_leading_zeros();
                return result;
            }
        } else {
            result.negative = false;
        }
        
        let mut m = n.abs();
        
        if m == 0 {
            return BigInt::zero();
        }
        
        let mut digits = Vec::new();
        while m > 0 {
            digits.push((m % 10) as u8);
            m /= 10;
        }
        digits.reverse();
        result.digits = digits;
        result.remove_leading_zeros();
        result
    }

    pub fn to_int(&self) -> i64 {
        let mut result: i64 = 0;
        for &digit in &self.digits {
            result = result.wrapping_mul(10).wrapping_add(digit as i64);
        }
        if self.negative {
            result = result.wrapping_neg();
        }
        result
    }

    pub fn from_str(s: &str) -> Self {
        let mut result = BigInt::zero();
        let mut chars = s.chars().peekable();
        
        if let Some(&'-') = chars.peek() {
            result.negative = true;
            chars.next();
        } else {
            result.negative = false;
        }
        
        let digits: Vec<u8> = chars.map(|c| (c as u8) - b'0').collect();
        result.digits = digits;
        // Note: C does NOT call remove_leading_zeros here
        result
    }

    pub fn copy(&self) -> BigInt {
        self.clone()
    }

    pub fn print(&self) {
        println!("{}", self);
    }

    pub fn is_zero(&self) -> bool {
        let mut temp = self.clone();
        temp.remove_leading_zeros();
        temp.digits.len() == 1 && temp.digits[0] == 0
    }

    pub fn lt_zero(&self) -> bool {
        let mut temp = self.clone();
        temp.remove_leading_zeros();
        temp.negative && !(temp.digits.len() == 1 && temp.digits[0] == 0)
    }

    pub fn gt_zero(&self) -> bool {
        let mut temp = self.clone();
        temp.remove_leading_zeros();
        !temp.negative && !(temp.digits.len() == 1 && temp.digits[0] == 0)
    }

    pub fn lezero(&self) -> bool {
        let mut temp = self.clone();
        temp.remove_leading_zeros();
        temp.negative || (temp.digits.len() == 1 && temp.digits[0] == 0)
    }

    pub fn gezero(&self) -> bool {
        let mut temp = self.clone();
        temp.remove_leading_zeros();
        !temp.negative || (temp.digits.len() == 1 && temp.digits[0] == 0)
    }

    pub fn abs(&self) -> Self {
        let mut result = self.clone();
        result.negative = false;
        result
    }

    // Helper: compare absolute values (ignoring sign)
    fn cmp_abs(&self, other: &Self) -> Ordering {
        let mut a = self.clone();
        let mut b = other.clone();
        a.remove_leading_zeros();
        b.remove_leading_zeros();
        
        if a.digits.len() != b.digits.len() {
            return a.digits.len().cmp(&b.digits.len());
        }
        
        for (da, db) in a.digits.iter().zip(b.digits.iter()) {
            if da != db {
                return da.cmp(db);
            }
        }
        Ordering::Equal
    }

    pub fn add(&self, other: &Self) -> Self {
        // Fast path for 64-bit integers
        if self.is_64_bit() && other.is_64_bit() {
            let a = self.to_int();
            let b = other.to_int();
            return BigInt::from_int(a.wrapping_add(b));
        }

        let mut a = self.clone();
        let mut b = other.clone();
        a.remove_leading_zeros();
        b.remove_leading_zeros();

        // If signs are the same, add absolute values and keep sign
        if a.negative == b.negative {
            let mut result = BigInt::zero();
            result.negative = a.negative;
            
            let mut carry = 0u8;
            let mut i = a.digits.len();
            let mut j = b.digits.len();
            
            while i > 0 || j > 0 || carry > 0 {
                let da = if i > 0 { a.digits[i - 1] } else { 0 };
                let db = if j > 0 { b.digits[j - 1] } else { 0 };
                
                let sum = da + db + carry;
                result.digits.insert(0, sum % 10);
                carry = sum / 10;
                
                if i > 0 { i -= 1; }
                if j > 0 { j -= 1; }
            }
            
            result.remove_leading_zeros();
            result
        } else {
            // Signs differ: subtract smaller absolute value from larger
            match a.cmp_abs(&b) {
                Ordering::Equal => BigInt::zero(),
                Ordering::Greater => {
                    // |a| > |b|, result has sign of a
                    let mut result = BigInt::zero();
                    result.negative = a.negative;
                    
                    let mut borrow = 0i8;
                    let mut i = a.digits.len();
                    let mut j = b.digits.len();
                    
                    while i > 0 {
                        let da = a.digits[i - 1] as i8;
                        let db = if j > 0 { b.digits[j - 1] as i8 } else { 0 };
                        
                        let mut diff = da - db - borrow;
                        if diff < 0 {
                            diff += 10;
                            borrow = 1;
                        } else {
                            borrow = 0;
                        }
                        
                        result.digits.insert(0, diff as u8);
                        
                        i -= 1;
                        if j > 0 { j -= 1; }
                    }
                    
                    result.remove_leading_zeros();
                    result
                }
                Ordering::Less => {
                    // |b| > |a|, result has sign of b
                    let mut result = BigInt::zero();
                    result.negative = b.negative;
                    
                    let mut borrow = 0i8;
                    let mut i = a.digits.len();
                    let mut j = b.digits.len();
                    
                    while j > 0 {
                        let da = if i > 0 { a.digits[i - 1] as i8 } else { 0 };
                        let db = b.digits[j - 1] as i8;
                        
                        let mut diff = db - da - borrow;
                        if diff < 0 {
                            diff += 10;
                            borrow = 1;
                        } else {
                            borrow = 0;
                        }
                        
                        result.digits.insert(0, diff as u8);
                        
                        if i > 0 { i -= 1; }
                        j -= 1;
                    }
                    
                    result.remove_leading_zeros();
                    result
                }
            }
        }
    }

    pub fn sub(&self, other: &Self) -> Self {
        // a - b = a + (-b)
        let mut neg_other = other.clone();
        neg_other.negative = !other.negative;
        self.add(&neg_other)
    }

    pub fn inc(&mut self) {
        let one = BigInt::from_int(1);
        *self = self.add(&one);
    }

    pub fn dec(&mut self) {
        let one = BigInt::from_int(1);
        *self = self.sub(&one);
    }

    pub fn mul(&self, other: &Self) -> Self {
        // Fast path for 64-bit integers
        if self.is_64_bit() && other.is_64_bit() {
            let a = self.to_int();
            let b = other.to_int();
            return BigInt::from_int(a.wrapping_mul(b));
        }

        let mut a = self.clone();
        let mut b = other.clone();
        a.remove_leading_zeros();
        b.remove_leading_zeros();

        if a.is_zero() || b.is_zero() {
            return BigInt::zero();
        }

        let mut result = BigInt::zero();
        result.negative = a.negative != b.negative;

        // Grade-school multiplication
        let mut temp_results: Vec<BigInt> = Vec::new();
        
        for (i, &db) in b.digits.iter().rev().enumerate() {
            if db == 0 {
                continue;
            }
            
            let mut carry = 0u8;
            let mut partial = BigInt::zero();
            partial.digits = vec![0; i]; // Shift by i positions (add zeros at end)
            
            for &da in a.digits.iter().rev() {
                let prod = da * db + carry;
                partial.digits.push(prod % 10);
                carry = prod / 10;
            }
            
            if carry > 0 {
                partial.digits.push(carry);
            }
            
            partial.digits.reverse();
            partial.remove_leading_zeros();
            temp_results.push(partial);
        }

        // Sum all partial results
        for partial in temp_results {
            result = result.add(&partial);
        }

        result.remove_leading_zeros();
        result
    }

    pub fn divmod(&self, other: &Self) -> (Self, Self) {
        let mut a = self.clone();
        let mut b = other.clone();
        a.remove_leading_zeros();
        b.remove_leading_zeros();

        if b.is_zero() {
            panic!("Division by zero");
        }

        // Fast path for 64-bit integers
        if a.is_64_bit() && b.is_64_bit() {
            let dividend = a.to_int();
            let divisor = b.to_int();
            let quot = BigInt::from_int(dividend.wrapping_div(divisor));
            let rem = BigInt::from_int(dividend.wrapping_rem(divisor));
            return (quot, rem);
        }

        // Handle signs
        let result_negative = a.negative != b.negative;
        a.negative = false;
        b.negative = false;

        // If |a| < |b|, quotient is 0, remainder is a
        if a.cmp_abs(&b) == Ordering::Less {
            let mut quotient = BigInt::zero();
            let mut remainder = a;
            remainder.negative = self.negative;
            return (quotient, remainder);
        }

        // Long division
        let mut quotient = BigInt::zero();
        quotient.digits = vec![0; a.digits.len()];
        
        let mut remainder = BigInt::zero();
        remainder.digits = Vec::new();

        for &digit in &a.digits {
            remainder.digits.push(digit);
            remainder.remove_leading_zeros();
            
            let mut count = 0u8;
            while remainder.cmp_abs(&b) != Ordering::Less {
                remainder = remainder.sub(&b);
                count += 1;
            }
            
            quotient.digits[a.digits.len() - remainder.digits.len() - 1 + count as usize] = count;
        }

        quotient.remove_leading_zeros();
        quotient.negative = result_negative;
        
        remainder.negative = self.negative;
        if remainder.is_zero() {
            remainder.negative = false;
        }

        (quotient, remainder)
    }

    pub fn div(&self, other: &Self) -> Self {
        self.divmod(other).0
    }

    pub fn r#mod(&self, other: &Self) -> Self {
        self.divmod(other).1
    }

    pub fn pow(&self, exponent: &Self) -> Self {
        // Fast path for 64-bit integers
        if self.is_64_bit() && exponent.is_64_bit() {
            let base = self.to_int();
            let exp = exponent.to_int();
            if exp < 0 {
                return BigInt::zero();
            }
            let mut result = 1i64;
            let mut base = base;
            let mut exp = exp as u64;
            while exp > 0 {
                if exp & 1 == 1 {
                    result = result.wrapping_mul(base);
                }
                base = base.wrapping_mul(base);
                exp >>= 1;
            }
            return BigInt::from_int(result);
        }

        let mut base = self.clone();
        let mut exp = exponent.clone();
        exp.remove_leading_zeros();
        
        if exp.is_zero() {
            return BigInt::from_int(1);
        }
        
        let mut result = BigInt::from_int(1);
        
        while !exp.is_zero() {
            if exp.is_odd() {
                result = result.mul(&base);
            }
            exp = exp.div(&BigInt::from_int(2));
            if !exp.is_zero() {
                base = base.mul(&base);
            }
        }
        
        result
    }

    pub fn fast_pow(&self, exponent: &Self, modulo: &Self) -> Self {
        // Fast path for 64-bit integers
        if self.is_64_bit() && exponent.is_64_bit() && modulo.is_64_bit() {
            let base = self.to_int();
            let exp = exponent.to_int();
            let mod_val = modulo.to_int();
            
            if mod_val == 0 {
                return BigInt::zero();
            }
            
            let mut result = 1i64;
            let mut base = base.wrapping_rem(mod_val);
            let mut exp = exp as u64;
            
            while exp > 0 {
                if exp & 1 == 1 {
                    result = (result.wrapping_mul(base)).wrapping_rem(mod_val);
                }
                base = (base.wrapping_mul(base)).wrapping_rem(mod_val);
                exp >>= 1;
            }
            return BigInt::from_int(result);
        }

        let mut base = self.r#mod(modulo);
        let mut exp = exponent.clone();
        exp.remove_leading_zeros();
        
        if modulo.is_zero() {
            return BigInt::zero();
        }
        
        let mut result = BigInt::from_int(1);
        
        while !exp.is_zero() {
            if exp.is_odd() {
                result = result.mul(&base).r#mod(modulo);
            }
            exp = exp.div(&BigInt::from_int(2));
            if !exp.is_zero() {
                base = base.mul(&base).r#mod(modulo);
            }
        }
        
        result
    }

    pub fn modinv(&self, modulo: &Self) -> Self {
        // Extended Euclidean Algorithm
        let mut a = self.clone();
        let mut m = modulo.clone();
        a.remove_leading_zeros();
        m.remove_leading_zeros();
        
        if m.is_zero() {
            return BigInt::zero();
        }
        
        let mut t = BigInt::zero();
        let mut new_t = BigInt::from_int(1);
        let mut r = m.clone();
        let mut new_r = a.r#mod(&m);
        
        while !new_r.is_zero() {
            let quotient = r.div(&new_r);
            
            let temp_t = t.sub(&quotient.mul(&new_t));
            t = new_t;
            new_t = temp_t;
            
            let temp_r = r.sub(&quotient.mul(&new_r));
            r = new_r;
            new_r = temp_r;
        }
        
        if r.gt(&BigInt::from_int(1)) {
            return BigInt::zero(); // Not invertible
        }
        
        if t.lt_zero() {
            t = t.add(&m);
        }
        
        t
    }

    pub fn sqrt(&self) -> Self {
        let mut n = self.clone();
        n.remove_leading_zeros();
        
        if n.lt_zero() {
            return BigInt::zero();
        }
        
        if n.is_zero() {
            return BigInt::zero();
        }
        
        // Binary search for sqrt
        let mut low = BigInt::from_int(1);
        let mut high = n.clone();
        
        while low.le(&high) {
            let mid = low.add(&high).div(&BigInt::from_int(2));
            let mid_sq = mid.mul(&mid);
            
            match mid_sq.cmp_abs(&n) {
                Ordering::Equal => return mid,
                Ordering::Less => {
                    low = mid.add(&BigInt::from_int(1));
                }
                Ordering::Greater => {
                    if mid.gt(&BigInt::from_int(1)) {
                        high = mid.sub(&BigInt::from_int(1));
                    } else {
                        high = BigInt::zero();
                    }
                }
            }
        }
        
        high
    }

    pub fn is_even(&self) -> bool {
        let mut temp = self.clone();
        temp.remove_leading_zeros();
        temp.digits.last().map_or(true, |&d| d % 2 == 0)
    }

    pub fn is_odd(&self) -> bool {
        !self.is_even()
    }

    pub fn is_prime(&self) -> bool {
        let mut n = self.clone();
        n.remove_leading_zeros();
        
        if n.le(&BigInt::from_int(1)) {
            return false;
        }
        
        if n.eq(&BigInt::from_int(2)) || n.eq(&BigInt::from_int(3)) {
            return true;
        }
        
        if n.is_even() {
            return false;
        }
        
        // Check if ends in 5
        if n.digits.last() == Some(&5) {
            return false;
        }
        
        // Check divisibility by 3
        let sum: u32 = n.digits.iter().map(|&d| d as u32).sum();
        if sum % 3 == 0 {
            return false;
        }
        
        // Trial division up to sqrt(n)
        let sqrt_n = n.sqrt();
        let mut i = BigInt::from_int(5);
        
        while i.le(&sqrt_n) {
            if n.r#mod(&i).is_zero() {
                return false;
            }
            i = i.add(&BigInt::from_int(2));
            if n.r#mod(&i).is_zero() {
                return false;
            }
            i = i.add(&BigInt::from_int(4));
        }
        
        true
    }
}

pub fn gt(a: &BigInt, b: &BigInt) -> bool {
    let mut a = a.clone();
    let mut b = b.clone();
    a.remove_leading_zeros();
    b.remove_leading_zeros();
    
    if a.negative != b.negative {
        return !a.negative && b.negative;
    }
    
    if a.negative {
        // Both negative: larger absolute value is smaller
        a.cmp_abs(&b) == Ordering::Less
    } else {
        // Both positive: larger absolute value is larger
        a.cmp_abs(&b) == Ordering::Greater
    }
}

pub fn lt(a: &BigInt, b: &BigInt) -> bool {
    gt(b, a)
}

pub fn ge(a: &BigInt, b: &BigInt) -> bool {
    !lt(a, b)
}

pub fn le(a: &BigInt, b: &BigInt) -> bool {
    !gt(a, b)
}

pub fn delete(_a: &mut BigInt) {
    // No-op in Rust (RAII)
}

impl std::ops::Neg for BigInt {
    type Output = BigInt;
    fn neg(self) -> BigInt {
        let mut result = self;
        if !result.is_zero() {
            result.negative = !result.negative;
        }
        result
    }
}

impl PartialEq for BigInt {
    fn eq(&self, other: &Self) -> bool {
        let mut a = self.clone();
        let mut b = other.clone();
        a.remove_leading_zeros();
        b.remove_leading_zeros();
        
        a.negative == b.negative && a.digits == b.digits
    }
}

impl Eq for BigInt {}

impl PartialOrd for BigInt {
    fn partial_cmp(&self, other: &Self) -> Option<Ordering> {
        Some(self.cmp(other))
    }
}

impl Ord for BigInt {
    fn cmp(&self, other: &Self) -> Ordering {
        let mut a = self.clone();
        let mut b = other.clone();
        a.remove_leading_zeros();
        b.remove_leading_zeros();
        
        if a.negative != b.negative {
            if a.negative {
                return Ordering::Less;
            } else {
                return Ordering::Greater;
            }
        }
        
        if a.negative {
            // Both negative: reverse order
            a.cmp_abs(&b).reverse()
        } else {
            a.cmp_abs(&b)
        }
    }
}

impl fmt::Display for BigInt {
    fn fmt(&self, f: &mut fmt::Formatter) -> fmt::Result {
        let mut temp = self.clone();
        temp.remove_leading_zeros();
        
        if temp.negative {
            write!(f, "-")?;
        }
        for &digit in &temp.digits {
            write!(f, "{}", digit)?;
        }
        Ok(())
    }
}
