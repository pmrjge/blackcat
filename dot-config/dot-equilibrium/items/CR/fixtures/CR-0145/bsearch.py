"""Binary search helpers over sorted lists."""


def lower_bound(a, x):
    """Index of the first element >= x (len(a) if none)."""
    lo, hi = 0, len(a)
    while lo < hi:
        mid = (lo + hi) // 2
        if a[mid] < x:
            lo = mid + 1
        else:
            hi = mid
    return lo


def upper_bound(a, x):
    """Index of the first element > x (len(a) if none)."""
    lo, hi = 0, len(a)
    while lo < hi:
        mid = (lo + hi) // 2
        if a[mid] <= x:
            lo = mid + 1
        else:
            hi = mid
    return lo


def index_of(a, x):
    """Index of the leftmost x, or -1."""
    i = lower_bound(a, x)
    if i < len(a) and a[i] == x:
        return i
    return -1


def count_in_range(a, lo, hi):
    """Number of elements v with lo <= v <= hi."""
    if lo > hi:
        return 0
    return upper_bound(a, hi) - lower_bound(a, lo)


def nearest(a, x):
    """Element closest to x; ties go to the smaller element. ValueError if a is empty."""
    if not a:
        raise ValueError("empty list")
    i = lower_bound(a, x)
    if i == 1:
        return a[0]
    if i == len(a):
        return a[-1]
    before, after = a[i - 1], a[i]
    if x - before <= after - x:
        return before
    return after


def insert_sorted(a, x):
    """Insert x after any equal elements; returns the index used."""
    i = upper_bound(a, x)
    a.insert(i, x)
    return i
