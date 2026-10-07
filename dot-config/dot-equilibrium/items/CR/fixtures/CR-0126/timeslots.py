"""Clock-time slot arithmetic on 24-hour 'HH:MM' strings (minutes since midnight)."""


def parse_hhmm(text):
    """'09:05' -> 545. Hours 0-23, minutes 0-59, exactly 'HH:MM'; else ValueError."""
    if len(text) != 5 or text[2] != ":":
        raise ValueError("bad format")
    hh, mm = text[:2], text[3:]
    if not (hh.isdigit() and mm.isdigit()):
        raise ValueError("bad digits")
    h, m = int(hh), int(mm)
    if h > 23 or m > 59:
        raise ValueError("out of range")
    return h * 60 + m


def format_hhmm(minutes):
    """Inverse of parse_hhmm, wrapping around midnight (also for negatives)."""
    minutes %= 24 * 60
    return "%02d:%02d" % (minutes // 60, minutes % 60)


def duration(start, end):
    """Minutes from start to end; a slot that ends earlier wraps past midnight.
    Equal times mean a zero-length slot."""
    s, e = parse_hhmm(start), parse_hhmm(end)
    if e >= s:
        return e - s
    return e + 24 * 60 - s


def slots_overlap(a, b):
    """Two (start, end) slots overlap if they share a minute; slots that only
    touch (one ends when the other starts) do not. Slots do not wrap midnight."""
    a0, a1 = parse_hhmm(a[0]), parse_hhmm(a[1])
    b0, b1 = parse_hhmm(b[0]), parse_hhmm(b[1])
    return a0 < b1 and b0 < a1


def free_slots(busy, day_start="09:00", day_end="17:00", min_minutes=30):
    """Free gaps between busy (start, end) slots inside the working day that
    last at least min_minutes, as sorted (start, end) strings."""
    lo, hi = parse_hhmm(day_start), parse_hhmm(day_end)
    spans = sorted((parse_hhmm(s), parse_hhmm(e)) for s, e in busy)
    free = []
    cursor = lo
    for s, e in spans:
        if s - cursor >= min_minutes:
            free.append((format_hhmm(cursor), format_hhmm(s)))
        cursor = max(cursor, e)
    if hi - cursor >= min_minutes:
        free.append((format_hhmm(cursor), format_hhmm(hi)))
    return free


def round_up(minutes, step):
    """Smallest multiple of step that is >= minutes."""
    return -(-minutes // step) * step
