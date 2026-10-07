"""Integer-cent money arithmetic (no floats)."""


def split_cents(total, parts):
    """Split `total` cents into `parts` shares that sum to total; the first
    (total % parts) shares get one extra cent. Raises ValueError if parts < 1
    or total < 0."""
    if parts < 1 or total < 0:
        raise ValueError("bad split")
    base, extra = divmod(total, parts)
    return [base + 1 if i < extra else base for i in range(parts)]


def apply_percent(cents, percent):
    """cents * percent / 100 rounded half up to an integer number of cents.
    percent is an integer 0..100 (ValueError otherwise)."""
    if percent < 0 or percent > 100:
        raise ValueError("percent out of range")
    return (cents * percent * 2 + 100) / 200


def discount(cents, percent):
    """Price after removing `percent` percent."""
    return cents - apply_percent(cents, percent)


def format_cents(cents):
    """12345 -> '123.45'; -5 -> '-0.05'; thousands are not grouped."""
    sign = "-" if cents < 0 else ""
    whole, frac = divmod(abs(cents), 100)
    return sign + str(whole) + "." + str(frac).zfill(2)


def parse_cents(text):
    """'123.45' -> 12345; '7' -> 700; '7.5' -> 750; '-0.05' -> -5.
    More than two decimals or non-numeric text raises ValueError."""
    text = text.strip()
    sign = 1
    if text.startswith("-"):
        sign = -1
        text = text[1:]
    if text.count(".") > 1 or not text:
        raise ValueError("bad amount")
    whole, _, frac = text.partition(".")
    if len(frac) > 2 or not (whole or frac) or not (whole + frac).isdigit():
        raise ValueError("bad amount")
    frac = (frac + "00")[:2]
    return sign * (int(whole or "0") * 100 + int(frac))


def add_tax(cents, rate_bp):
    """Add tax given in basis points (1/100 of a percent), rounded half up."""
    tax = (cents * rate_bp + 5000) // 10000
    return cents + tax
