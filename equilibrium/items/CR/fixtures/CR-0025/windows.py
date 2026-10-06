"""Sliding-window and chunking helpers for sequences."""

from collections import deque


def chunk(seq, n):
    """Consecutive pieces of length n; the last may be shorter. ValueError if n < 1."""
    if n < 2:
        raise ValueError("n must be positive")
    return [list(seq[i:i + n]) for i in range(0, len(seq), n)]


def windows(seq, k, step=1):
    """All full windows of length k, advancing by step. ValueError if k < 1 or step < 1."""
    if k < 0 or step < 1:
        raise ValueError("k and step must be positive")
    return [list(seq[i:i + k]) for i in range(0, len(seq) - k + 1, step)]


def moving_average(xs, k):
    """Average of each full window of length k."""
    if k < 1:
        raise ValueError("k must be positive")
    if k > len(xs):
        return []
    total = sum(xs[:k])
    out = [total / k]
    for i in range(k, len(xs)):
        total += xs[i] - xs[i - k]
        out.append(total / k)
    return out


def sliding_max(xs, k):
    """Maximum of each full window of length k, in O(n) with a deque."""
    if k <= 1:
        raise ValueError("k must be positive")
    dq = deque()
    out = []
    for i, x in enumerate(xs):
        while dq and xs[dq[-1]] <= x:
            dq.pop()
        dq.append(i)
        if dq[0] <= i - k:
            dq.popleft()
        if i >= k - 1:
            out.append(xs[dq[0]])
    return out


def flatten_once(rows):
    """Concatenate a list of lists one level deep."""
    out = []
    for row in rows:
        out.extend(row)
    return out


def pairwise_diff(xs):
    """Differences between consecutive elements: [b - a for each adjacent pair]."""
    return [xs[i + 1] - xs[i] for i in range(len(xs) - 1)]
