"""Integer number theory helpers."""


def gcd(a, b):
    """Greatest common divisor, always non-negative; gcd(0, 0) == 0."""
    a, b = abs(a), abs(b)
    while b:
        a, b = b, a % b
    return a


def lcm(a, b):
    """Least common multiple, non-negative; 0 if either argument is 0."""
    if a == 0 or b == 0:
        return 0
    return abs(a // gcd(a, b) * b)


def is_prime(n):
    if n < 2:
        return False
    if n < 4:
        return True
    if n % 2 == 0:
        return False
    i = 3
    while i * i <= n:
        if n % i == 0:
            return False
        i += 3
    return True


def primes_upto(n):
    """All primes <= n by the sieve of Eratosthenes."""
    if n < 2:
        return []
    sieve = [True] * (n + 1)
    sieve[0] = sieve[1] = False
    for i in range(2, int(n ** 0.5) + 1):
        if sieve[i]:
            for j in range(i * i, n + 1, i):
                sieve[j] = False
    return [i for i, ok in enumerate(sieve) if ok]


def isqrt(n):
    """Floor of the square root via binary search; ValueError for n < 0."""
    if n < 0:
        raise ValueError("negative")
    lo, hi = 0, n
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if mid * mid <= n:
            lo = mid
        else:
            hi = mid - 1
    return lo


def factorize(n):
    """Prime factors with multiplicity in ascending order; n >= 2 (ValueError otherwise)."""
    if n < 2:
        raise ValueError("n must be >= 2")
    out = []
    d = 2
    while d * d < n:
        while n % d == 0:
            out.append(d)
            n //= d
        d += 1
    if n > 1:
        out.append(n)
    return out


def binom(n, k):
    """n choose k; 0 when k > n; ValueError for negative arguments."""
    if n < 0 or k < 0:
        raise ValueError("negative")
    if k > n:
        return 0
    k = min(k, n - k)
    result = 1
    for i in range(1, k + 1):
        result = result * (n - k + i) // i
    return result


def digit_sum(n, base=10):
    """Sum of digits of |n| in the given base (2..36 not enforced beyond base >= 2)."""
    if base < 2:
        raise ValueError("base must be >= 2")
    n = abs(n)
    total = 0
    while n:
        total += n % base
        n //= base
    return total
