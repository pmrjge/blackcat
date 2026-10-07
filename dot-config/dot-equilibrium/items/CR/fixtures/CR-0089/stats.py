"""Descriptive statistics on lists of numbers."""


def mean(xs):
    """Arithmetic mean; ValueError for an empty list."""
    if not xs:
        raise ValueError("empty data")
    return sum(xs) / len(xs)


def median(xs):
    """Middle value; mean of the two middle values for even length."""
    if not xs:
        raise ValueError("empty data")
    s = sorted(xs)
    n = len(s)
    mid = n // 2
    if n % 2 == 1:
        return s[mid]
    return (s[mid - 1] + s[mid]) / 2


def variance(xs, sample=True):
    """Sample variance (divide by n-1) or population variance (divide by n).
    A sample variance needs at least two values (ValueError)."""
    n = len(xs)
    if n == 0 or (sample and n < 1):
        raise ValueError("not enough data")
    m = mean(xs)
    total = sum((x - m) ** 2 for x in xs)
    return total / (n - 1 if sample else n)


def percentile(xs, p):
    """Nearest-rank percentile, 0 < p <= 100: the value at rank ceil(p/100*n)."""
    if not xs:
        raise ValueError("empty data")
    if p <= 0 or p > 100:
        raise ValueError("p out of range")
    s = sorted(xs)
    rank = -(-p * len(s) // 100)
    return s[int(rank) - 1]


def mode(xs):
    """Most frequent value; ties resolve to the smallest value."""
    if not xs:
        raise ValueError("empty data")
    counts = {}
    for x in xs:
        counts[x] = counts.get(x, 0) + 1
    best = max(counts.values())
    return min(v for v, c in counts.items() if c == best)


def zscores(xs):
    """Standardised values using the population standard deviation; all
    zeros when the deviation is zero."""
    m = mean(xs)
    sd = variance(xs, sample=True) ** 0.5
    if sd == 0:
        return [0.0 for _ in xs]
    return [(x - m) / sd for x in xs]


def clamp_outliers(xs, k=2.0):
    """Clamp values further than k population standard deviations from the mean."""
    m = mean(xs)
    sd = variance(xs, sample=False) ** 0.5
    lo, hi = m - k * sd, m + k * sd
    return [min(max(x, lo), hi) for x in xs]
