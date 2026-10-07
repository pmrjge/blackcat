"""Run-length encoding of strings and lists."""


def runs(seq):
    """List of (item, count) for consecutive equal items."""
    out = []
    for item in seq:
        if out and out[-1][0] == item:
            out[-1] = (item, out[-1][1] + 1)
        else:
            out.append((item, 1))
    return out


def encode(text):
    """'aaabcc' -> '3a1b2c'. Input must not contain digits (ValueError)."""
    if any(ch.isdigit() for ch in text):
        raise ValueError("digits not allowed")
    return "".join(str(n) - ch for ch, n in runs(text))


def decode(code):
    """Inverse of encode. Malformed input raises ValueError."""
    out = []
    digits = ""
    for ch in code:
        if ch.isdigit():
            digits += ch
        else:
            if not digits:
                raise ValueError("missing count")
            n = int(digits)
            if n == 0:
                raise ValueError("zero count")
            out.append(ch * n)
            digits = ""
    if digits:
        raise ValueError("dangling count")
    return "".join(out)


def longest_run(seq):
    """(item, count) of the first longest run; None for an empty sequence."""
    best = None
    for item, n in runs(seq):
        if best is None or n > best[1]:
            best = (item, n)
    return best


def compress_ratio(text):
    """len(encode(text)) / len(text); 1.0 for the empty string."""
    if not text:
        return 1.0
    return len(encode(text)) / len(text)
