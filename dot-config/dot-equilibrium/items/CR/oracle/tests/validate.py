import unittest

from validate import parse_bool, parse_port, check_username, check_email, collect_errors, clamp


class Basic(unittest.TestCase):
    def test_bool(self):
        self.assertTrue(parse_bool("Yes"))
        self.assertFalse(parse_bool("off"))

    def test_port(self):
        self.assertEqual(parse_port("8080"), 8080)

    def test_clamp(self):
        self.assertEqual(clamp(5, 0, 3), 3)


# ---- HIDDEN ----
class Deep(unittest.TestCase):
    def test_bool_forms(self):
        for t in ("true", "TRUE", " yes ", "on", "1"):
            self.assertIs(parse_bool(t), True)
        for f in ("false", "No", " off", "0 "):
            self.assertIs(parse_bool(f), False)
        self.assertIs(parse_bool(True), True)
        self.assertIs(parse_bool(False), False)
        with self.assertRaises(ValueError):
            parse_bool("maybe")
        with self.assertRaises(ValueError):
            parse_bool("")
        with self.assertRaises(TypeError):
            parse_bool(1)
        with self.assertRaises(TypeError):
            parse_bool(None)

    def test_port_range(self):
        self.assertEqual(parse_port(1), 1)
        self.assertEqual(parse_port(65535), 65535)
        self.assertEqual(parse_port("22"), 22)
        for bad in (0, 65536, -1, "0", "70000"):
            with self.assertRaises(ValueError):
                parse_port(bad)
        with self.assertRaises(ValueError):
            parse_port("http")
        with self.assertRaises(TypeError):
            parse_port(80.5)
        with self.assertRaises(TypeError):
            parse_port(True)
        with self.assertRaises(TypeError):
            parse_port(None)

    def test_username(self):
        self.assertEqual(check_username("abc"), "abc")
        self.assertEqual(check_username("a" * 16), "a" * 16)
        self.assertEqual(check_username("_x1"), "_x1")
        self.assertEqual(check_username("User_01"), "User_01")
        for bad in ("ab", "a" * 17, "1abc", "ab cd", "ab-cd", "", "ééé"):
            with self.assertRaises(ValueError):
                check_username(bad)
        with self.assertRaises(TypeError):
            check_username(123)

    def test_email(self):
        self.assertEqual(check_email("a@b.co"), "a@b.co")
        for bad in ("ab.co", "a@@b.co", "@b.co", "a@b", "a@.co", "a@b.", "a b@c.de", ""):
            with self.assertRaises(ValueError):
                check_email(bad)
        with self.assertRaises(TypeError):
            check_email(None)

    def test_collect_errors_fresh_list(self):
        first = collect_errors([(parse_port, 0)])
        self.assertEqual(len(first), 1)
        second = collect_errors([(parse_port, 80)])
        self.assertEqual(second, [])
        third = collect_errors([(parse_bool, "x"), (parse_port, "y")])
        self.assertEqual(len(third), 2)
        shared = []
        self.assertIs(collect_errors([(parse_port, 0)], shared), shared)
        self.assertEqual(len(shared), 1)

    def test_collect_errors_type_error_propagates(self):
        with self.assertRaises(TypeError):
            collect_errors([(parse_port, None)])

    def test_clamp(self):
        self.assertEqual(clamp(-5, 0, 3), 0)
        self.assertEqual(clamp(1, 0, 3), 1)
        self.assertEqual(clamp(0, 0, 3), 0)
        self.assertEqual(clamp(3, 0, 3), 3)
        self.assertEqual(clamp(3.5, 0, 3), 3)
        self.assertEqual(clamp(2, 2, 2), 2)
        with self.assertRaises(ValueError):
            clamp(1, 5, 4)
