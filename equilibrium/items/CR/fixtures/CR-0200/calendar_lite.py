"""Gregorian calendar arithmetic without the datetime module."""

_DAYS = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]


def is_leap(year):
    """Leap years: divisible by 4, except centuries not divisible by 400."""
    if year % 400 == 0:
        return True
    if year % 100 == 0:
        return False
    return year % 4 == 0


def days_in_month(year, month):
    """Days in the month (1-12); ValueError for a bad month."""
    if month < 1 or month > 12:
        raise ValueError("month out of range")
    if month == 2 and is_leap(year):
        return 29
    return _DAYS[month - 1]


def day_of_year(year, month, day):
    """1-based ordinal of the date within its year; ValueError for a bad day."""
    if day < 1 or day > days_in_month(year, month):
        raise ValueError("day out of range")
    total = day
    for m in range(1, month):
        total += days_in_month(year, m)
    return total


def weekday(year, month, day):
    """0 = Monday ... 6 = Sunday (Zeller-style congruence)."""
    if day < 1 or day > days_in_month(year, month):
        raise ValueError("day out of range")
    y, m = year, month
    if m < 3:
        m += 12
        y -= 1
    k = y % 100
    j = y // 100
    h = (day + (13 * (m + 1)) // 5 + k + k // 4 + j // 4 + 5 * j) % 7
    return (h + 5) % 7


def add_days(year, month, day, n):
    """Date n days later (n may be negative) as (year, month, day)."""
    day_of_year(year, month, day)
    day += n
    while day > days_in_month(year, month):
        day -= days_in_month(year, month)
        month += 1
        if month > 12:
            month = 1
            year += 1
    while day < 1:
        month -= 1
        if month < 1:
            month = 12
            year -= 1
        day += days_in_month(year, month)
    return (year, month, day)
