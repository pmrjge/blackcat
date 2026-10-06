import unittest

from timeslots import parse_hhmm, format_hhmm, duration, slots_overlap, free_slots, round_up


class Basic(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(parse_hhmm("09:05"), 545)

    def test_format(self):
        self.assertEqual(format_hhmm(545), "09:05")

    def test_duration(self):
        self.assertEqual(duration("09:00", "10:30"), 90)


class Deep(unittest.TestCase):
    def test_parse_edges(self):
        self.assertEqual(parse_hhmm("00:00"), 0)
        self.assertEqual(parse_hhmm("23:59"), 1439)
        self.assertEqual(parse_hhmm("12:00"), 720)
        for bad in ["24:00", "12:60", "9:05", "09-05", "ab:cd", "", "09:5", "09:050", "-1:00"]:
            with self.assertRaises(ValueError):
                parse_hhmm(bad)

    def test_format_wrap(self):
        self.assertEqual(format_hhmm(0), "00:00")
        self.assertEqual(format_hhmm(1439), "23:59")
        self.assertEqual(format_hhmm(1440), "00:00")
        self.assertEqual(format_hhmm(1500), "01:00")
        self.assertEqual(format_hhmm(-1), "23:59")
        self.assertEqual(format_hhmm(-60), "23:00")
        self.assertEqual(format_hhmm(61), "01:01")

    def test_duration_wrap(self):
        self.assertEqual(duration("22:00", "02:00"), 240)
        self.assertEqual(duration("10:00", "10:00"), 0)
        self.assertEqual(duration("23:59", "00:00"), 1)
        self.assertEqual(duration("00:00", "23:59"), 1439)
        self.assertEqual(duration("10:00", "09:59"), 1439)

    def test_overlap(self):
        self.assertTrue(slots_overlap(("09:00", "10:00"), ("09:30", "11:00")))
        self.assertTrue(slots_overlap(("09:30", "11:00"), ("09:00", "10:00")))
        self.assertFalse(slots_overlap(("09:00", "10:00"), ("10:00", "11:00")))
        self.assertFalse(slots_overlap(("10:00", "11:00"), ("09:00", "10:00")))
        self.assertTrue(slots_overlap(("09:00", "12:00"), ("10:00", "11:00")))
        self.assertTrue(slots_overlap(("10:00", "11:00"), ("09:00", "12:00")))
        self.assertFalse(slots_overlap(("09:00", "10:00"), ("11:00", "12:00")))

    def test_free_slots(self):
        busy = [("10:00", "11:00"), ("13:00", "14:00")]
        self.assertEqual(free_slots(busy), [("09:00", "10:00"), ("11:00", "13:00"), ("14:00", "17:00")])
        self.assertEqual(free_slots([]), [("09:00", "17:00")])
        self.assertEqual(free_slots([("09:00", "17:00")]), [])
        self.assertEqual(free_slots([("09:30", "10:00")]), [("09:00", "09:30"), ("10:00", "17:00")])
        self.assertEqual(free_slots([("09:20", "16:50")]), [])
        self.assertEqual(free_slots([("09:00", "12:00"), ("10:00", "11:00")]), [("12:00", "17:00")])
        self.assertEqual(free_slots([("13:00", "14:00"), ("10:00", "11:00")], min_minutes=120),
                         [("11:00", "13:00"), ("14:00", "17:00")])
        self.assertEqual(free_slots([("09:00", "16:30")]), [("16:30", "17:00")])
        self.assertEqual(free_slots([("09:00", "16:31")]), [])
        self.assertEqual(free_slots([("09:00", "16:29")]), [("16:29", "17:00")])
        self.assertEqual(free_slots([], day_start="08:00", day_end="08:45", min_minutes=45),
                         [("08:00", "08:45")])

    def test_round_up(self):
        self.assertEqual(round_up(61, 15), 75)
        self.assertEqual(round_up(60, 15), 60)
        self.assertEqual(round_up(0, 15), 0)
        self.assertEqual(round_up(1, 5), 5)
        self.assertEqual(round_up(14, 15), 15)
