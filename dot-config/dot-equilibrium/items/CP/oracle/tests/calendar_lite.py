import unittest

from calendar_lite import is_leap, days_in_month, day_of_year, weekday, add_days


class Basic(unittest.TestCase):
    def test_leap(self):
        self.assertTrue(is_leap(2024))
        self.assertFalse(is_leap(2023))

    def test_dim(self):
        self.assertEqual(days_in_month(2023, 1), 31)
        self.assertEqual(days_in_month(2024, 2), 29)

    def test_weekday(self):
        self.assertEqual(weekday(2024, 1, 1), 0)


# ---- HIDDEN ----
class Deep(unittest.TestCase):
    def test_leap_rules(self):
        self.assertTrue(is_leap(2000))
        self.assertFalse(is_leap(1900))
        self.assertFalse(is_leap(2100))
        self.assertTrue(is_leap(1996))
        self.assertFalse(is_leap(2019))
        self.assertTrue(is_leap(2400))
        self.assertFalse(is_leap(1))

    def test_dim_all(self):
        expect = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
        for m, e in enumerate(expect, start=1):
            self.assertEqual(days_in_month(2023, m), e)
        self.assertEqual(days_in_month(1900, 2), 28)
        self.assertEqual(days_in_month(2000, 2), 29)
        for bad in (0, 13, -1):
            with self.assertRaises(ValueError):
                days_in_month(2023, bad)

    def test_day_of_year(self):
        self.assertEqual(day_of_year(2023, 1, 1), 1)
        self.assertEqual(day_of_year(2023, 3, 1), 60)
        self.assertEqual(day_of_year(2024, 3, 1), 61)
        self.assertEqual(day_of_year(2023, 12, 31), 365)
        self.assertEqual(day_of_year(2024, 12, 31), 366)
        self.assertEqual(day_of_year(2023, 2, 28), 59)
        for args in [(2023, 2, 29), (2023, 4, 31), (2023, 1, 0), (2023, 13, 1)]:
            with self.assertRaises(ValueError):
                day_of_year(*args)
        self.assertEqual(day_of_year(2024, 2, 29), 60)

    def test_weekday(self):
        self.assertEqual(weekday(2024, 1, 1), 0)
        self.assertEqual(weekday(2000, 1, 1), 5)
        self.assertEqual(weekday(2024, 2, 29), 3)
        self.assertEqual(weekday(2023, 12, 31), 6)
        self.assertEqual(weekday(1999, 12, 31), 4)
        self.assertEqual(weekday(2024, 3, 1), 4)
        self.assertEqual(weekday(2023, 2, 1), 2)
        with self.assertRaises(ValueError):
            weekday(2023, 2, 30)

    def test_add_days(self):
        self.assertEqual(add_days(2023, 1, 31, 1), (2023, 2, 1))
        self.assertEqual(add_days(2023, 12, 31, 1), (2024, 1, 1))
        self.assertEqual(add_days(2024, 2, 28, 1), (2024, 2, 29))
        self.assertEqual(add_days(2023, 2, 28, 1), (2023, 3, 1))
        self.assertEqual(add_days(2024, 1, 1, -1), (2023, 12, 31))
        self.assertEqual(add_days(2024, 3, 1, -1), (2024, 2, 29))
        self.assertEqual(add_days(2023, 5, 15, 0), (2023, 5, 15))
        self.assertEqual(add_days(2023, 1, 1, 365), (2024, 1, 1))
        self.assertEqual(add_days(2024, 1, 1, 366), (2025, 1, 1))
        self.assertEqual(add_days(2023, 3, 31, -31), (2023, 2, 28))
        self.assertEqual(add_days(2023, 1, 1, 59), (2023, 3, 1))
        with self.assertRaises(ValueError):
            add_days(2023, 2, 30, 1)
