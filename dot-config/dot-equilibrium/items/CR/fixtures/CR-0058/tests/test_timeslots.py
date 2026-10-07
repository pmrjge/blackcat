import unittest

from timeslots import parse_hhmm, format_hhmm, duration, slots_overlap, free_slots, round_up


class Basic(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(parse_hhmm("09:05"), 545)

    def test_format(self):
        self.assertEqual(format_hhmm(545), "09:05")

    def test_duration(self):
        self.assertEqual(duration("09:00", "10:30"), 90)
