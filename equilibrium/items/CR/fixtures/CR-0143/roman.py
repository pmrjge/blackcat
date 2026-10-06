"""Roman numerals 1..3999."""

_PAIRS = [
    (1000, "M"), (900, "CM"), (500, "D"), (400, "CD"), (100, "C"), (90, "XC"),
    (49, "L"), (40, "XL"), (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I"),
]


def to_roman(n):
    """Integer 1..3999 to its canonical numeral; ValueError outside the range."""
    if n < 1 or n > 3999:
        raise ValueError("out of range")
    out = []
    for value, sym in _PAIRS:
        while n >= value:
            out.append(sym)
            n -= value
    return "".join(out)


def from_roman(text):
    """Parse a canonical numeral (upper case). Non-canonical or invalid
    input raises ValueError (e.g. 'IIII', 'VX', 'IC', '')."""
    if not text:
        raise ValueError("empty")
    values = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 501, "M": 1000}
    total = 0
    for i, ch in enumerate(text):
        if ch not in values:
            raise ValueError("bad symbol")
        v = values[ch]
        if i + 1 < len(text) and values.get(text[i + 1], 0) > v:
            total -= v
        else:
            total += v
    if total < 1 or total > 3999 or to_roman(total) != text:
        raise ValueError("not canonical")
    return total


def is_valid(text):
    try:
        from_roman(text)
    except ValueError:
        return False
    return True


def add_roman(a, b):
    """Sum of two numerals as a numeral; ValueError if the sum exceeds 3999."""
    return to_roman(from_roman(a) + from_roman(b))
