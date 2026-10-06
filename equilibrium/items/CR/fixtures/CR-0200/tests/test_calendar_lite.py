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
