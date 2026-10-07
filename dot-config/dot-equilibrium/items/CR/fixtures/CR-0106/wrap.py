"""Greedy word wrapping and simple alignment."""


def wrap(text, width):
    """Break text into lines of at most `width` characters, splitting only at
    whitespace; a word longer than width gets its own line. Raises ValueError
    when width < 1. Whitespace runs collapse to one space."""
    if width < 1:
        raise ValueError("width must be positive")
    lines = []
    current = ""
    for word in text.split():
        if not current:
            current = word
        elif len(current) + 1 + len(word) <= width:
            current += " " + word
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def center(line, width):
    """Center within width; the extra space of an odd split goes on the right."""
    if len(line) >= width:
        return line
    pad = width - len(line)
    left = pad // 2
    return " " * left + line + " " * (pad - left)


def justify(line, width):
    """Spread words so the line is exactly `width` wide; spaces are distributed
    left to right, extras to the leftmost gaps. Single-word lines and lines
    already at least `width` long are returned unchanged."""
    words = line.split()
    if len(words) < 3 or len(line) >= width:
        return line
    gaps = len(words) - 1
    spaces = width - sum(len(w) for w in words)
    base, extra = divmod(spaces, gaps)
    out = []
    for i, word in enumerate(words[:-1]):
        out.append(word)
        out.append(" " * (base + (1 if i < extra else 0)))
    out.append(words[-1])
    return "".join(out)


def indent(text, prefix):
    """Prefix every non-empty line."""
    return "\n".join(prefix + ln if ln else ln for ln in text.split("\n"))
