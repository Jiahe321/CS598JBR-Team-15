#include <stdio.h>
#include "bigint.h"

static void pr(const char *label, bigint *b) {
    printf("%s = ", label);
    bigint_print(b);
    printf("\n");
}

int main(void) {
    // from_int edge cases
    bigint a = bigint_from_int(0);
    pr("from_int(0)", &a);
    bigint b = bigint_from_int(-12345);
    pr("from_int(-12345)", &b);
    bigint c = bigint_from_int(999999999);
    pr("from_int(999999999)", &c);

    // from_str with leading zeros
    bigint d = bigint_from_string("000123");
    pr("from_str(000123)", &d);
    bigint e = bigint_from_string("-000");
    pr("from_str(-000)", &e);
    printf("is_zero(-000) = %d\n", bigint_eqzero(&e));
    printf("lt_zero(-000) = %d\n", bigint_ltzero(&e));

    // add/sub with negatives
    bigint x = bigint_from_int(-50);
    bigint y = bigint_from_int(30);
    bigint z = bigint_add(&x, &y);
    pr("-50 + 30", &z);
    z = bigint_sub(&x, &y);
    pr("-50 - 30", &z);
    z = bigint_sub(&y, &x);
    pr("30 - (-50)", &z);
    bigint n1 = bigint_from_int(-7);
    bigint n2 = bigint_from_int(-3);
    z = bigint_add(&n1, &n2);
    pr("-7 + -3", &z);
    z = bigint_sub(&n1, &n2);
    pr("-7 - -3", &z);

    // mul with negatives
    bigint m1 = bigint_from_int(-12);
    bigint m2 = bigint_from_int(11);
    z = bigint_mul(&m1, &m2);
    pr("-12 * 11", &z);
    z = bigint_mul(&m1, &m1);
    pr("-12 * -12", &z);

    // div/mod with negatives (fast path)
    bigint p = bigint_from_int(-100);
    bigint q = bigint_from_int(7);
    z = bigint_div(&p, &q);
    pr("-100 / 7", &z);
    z = bigint_mod(&p, &q);
    pr("-100 % 7", &z);
    z = bigint_div(&q, &p);
    pr("7 / -100", &z);
    z = bigint_mod(&q, &p);
    pr("7 % -100", &z);

    // large div/mod (slow path)
    bigint big1 = bigint_from_string("123456789012345678901234567890");
    bigint big2 = bigint_from_string("9876543210");
    z = bigint_div(&big1, &big2);
    pr("big1 / big2", &z);
    z = bigint_mod(&big1, &big2);
    pr("big1 % big2", &z);

    // pow
    bigint base = bigint_from_int(3);
    bigint exp = bigint_from_int(0);
    z = bigint_pow(&base, &exp);
    pr("3^0", &z);
    exp = bigint_from_int(5);
    z = bigint_pow(&base, &exp);
    pr("3^5", &z);
    bigint negexp = bigint_from_int(-2);
    z = bigint_pow(&base, &negexp);
    pr("3^-2", &z);

    // sqrt
    bigint s = bigint_from_int(0);
    z = bigint_sqrt(&s);
    pr("sqrt(0)", &z);
    s = bigint_from_int(1);
    z = bigint_sqrt(&s);
    pr("sqrt(1)", &z);
    s = bigint_from_int(2);
    z = bigint_sqrt(&s);
    pr("sqrt(2)", &z);
    s = bigint_from_int(15);
    z = bigint_sqrt(&s);
    pr("sqrt(15)", &z);
    s = bigint_from_int(16);
    z = bigint_sqrt(&s);
    pr("sqrt(16)", &z);
    s = bigint_from_int(17);
    z = bigint_sqrt(&s);
    pr("sqrt(17)", &z);

    // is_prime
    int primes[] = {1, 2, 3, 5, 7, 9, 11, 13, 17, 19, 23, 25, 49, 97, 121, 169};
    for (int i = 0; i < 16; i++) {
        bigint t = bigint_from_int(primes[i]);
        printf("is_prime(%d) = %d\n", primes[i], bigint_is_prime(&t));
    }

    // modinv
    bigint mi_a = bigint_from_int(3);
    bigint mi_m = bigint_from_int(11);
    z = bigint_modinv(&mi_a, &mi_m);
    pr("modinv(3,11)", &z);
    mi_a = bigint_from_int(10);
    mi_m = bigint_from_int(17);
    z = bigint_modinv(&mi_a, &mi_m);
    pr("modinv(10,17)", &z);
    mi_a = bigint_from_int(4);
    mi_m = bigint_from_int(8);
    z = bigint_modinv(&mi_a, &mi_m);
    pr("modinv(4,8)", &z);

    // fast_pow slow path (large modulo)
    bigint fp_a = bigint_from_string("123456789012345678901234567890");
    bigint fp_b = bigint_from_string("123456789012345678901234567890");
    bigint fp_m = bigint_from_string("987654321098765432109876543210");
    z = bigint_fast_pow(&fp_a, &fp_b, &fp_m);
    pr("fast_pow big", &z);

    // is_even/is_odd
    bigint ev = bigint_from_int(0);
    printf("is_even(0)=%d is_odd(0)=%d\n", bigint_is_even(&ev), bigint_is_odd(&ev));

    // comparisons
    bigint c1 = bigint_from_int(-5);
    bigint c2 = bigint_from_int(5);
    printf("-5 > 5 = %d\n", bigint_gt(&c1, &c2));
    printf("-5 < 5 = %d\n", bigint_lt(&c1, &c2));
    printf("-5 == 5 = %d\n", bigint_eq(&c1, &c2));
    bigint c3 = bigint_from_int(-5);
    printf("-5 == -5 = %d\n", bigint_eq(&c1, &c3));

    return 0;
}
</action>
