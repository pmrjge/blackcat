"""Half-open integer intervals [start, end)."""


def normalize(iv):
    """Return (start, end) with start <= end; reject empty or inverted input.

    Raises ValueError when end <= start.
    """
    start, end = iv
    if end <= start:
        raise ValueError("empty or inverted interval")
    return (start, end)


def overlaps(a, b):
    """True when the half-open intervals share at least one integer."""
    return a[0] < b[1] or b[0] < a[1]


def merge(intervals):
    """Merge overlapping or touching intervals; result sorted by start.

    [1, 3) and [3, 5) touch and are merged into [1, 5).
    """
    items = sorted(normalize(iv) for iv in intervals)
    out = []
    for start, end in items:
        if out and start <= out[-1][1]:
            last_start, last_end = out[-1]
            out[-1] = (last_start, max(last_end, end))
        else:
            out.append((start, end))
    return out


def total_length(intervals):
    """Number of integers covered by the union of the intervals."""
    return sum(end - start for start, end in merge(intervals))


def gaps(intervals, lo, hi):
    """Uncovered sub-intervals of [lo, hi), sorted, never empty."""
    result = []
    cursor = lo
    for start, end in merge(intervals):
        if end <= lo:
            continue
        if start >= hi:
            break
        if start > cursor:
            result.append((cursor, start))
        cursor = max(cursor, end)
    if cursor < hi:
        result.append((cursor, hi))
    return result


def contains_point(intervals, x):
    """True when x lies in some interval (start inclusive, end exclusive)."""
    for start, end in merge(intervals):
        if start <= x < end:
            return True
    return False
