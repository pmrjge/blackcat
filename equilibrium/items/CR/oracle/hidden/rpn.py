import unittest

from rpn import tokenize, to_postfix, eval_postfix, evaluate


class Basic(unittest.TestCase):
    def test_eval(self):
        self.assertEqual(evaluate("1 + 2 * 3"), 7)

    def test_parens(self):
        self.assertEqual(evaluate("(1 + 2) * 3"), 9)

    def test_tokenize(self):
        self.assertEqual(tokenize("12+3"), ["12", "+", "3"])


class Deep(unittest.TestCase):
    def test_left_assoc(self):
        self.assertEqual(evaluate("10 - 4 - 3"), 3)
        self.assertEqual(evaluate("100 / 10 / 5"), 2)
        self.assertEqual(evaluate("2 * 3 % 4"), 2)
        self.assertEqual(to_postfix(tokenize("1-2-3")), ["1", "2", "-", "3", "-"])

    def test_precedence(self):
        self.assertEqual(evaluate("2 + 3 * 4 - 5"), 9)
        self.assertEqual(evaluate("20 - 6 / 3"), 18)
        self.assertEqual(evaluate("7 + 8 % 5"), 10)
        self.assertEqual(to_postfix(tokenize("1+2*3")), ["1", "2", "3", "*", "+"])
        self.assertEqual(to_postfix(tokenize("1*2+3")), ["1", "2", "*", "3", "+"])
        self.assertEqual(to_postfix(tokenize("1*2/3")), ["1", "2", "*", "3", "/"])

    def test_nested(self):
        self.assertEqual(evaluate("((2 + 3)) * (4 - 1)"), 15)
        self.assertEqual(evaluate("2 * (3 + (4 - 1) * 2)"), 18)
        self.assertEqual(evaluate("42"), 42)

    def test_floor_semantics(self):
        self.assertEqual(evaluate("7 / 2"), 3)
        self.assertEqual(evaluate("0 - 7 / 2"), -3)
        self.assertEqual(eval_postfix(["7", "2", "%"]), 1)

    def test_errors(self):
        for bad in ["1 +", "(1 + 2", "1 + 2)", "", "1 2", "a + 1", "1 + $", "()", "* 2"]:
            with self.assertRaises(ValueError):
                evaluate(bad)
        with self.assertRaises(ZeroDivisionError):
            evaluate("1 / 0")
        with self.assertRaises(ZeroDivisionError):
            evaluate("1 % 0")

    def test_tokenize_more(self):
        self.assertEqual(tokenize(" ( 1 +22 ) * 3 "), ["(", "1", "+", "22", ")", "*", "3"])
        self.assertEqual(tokenize(""), [])
        self.assertEqual(tokenize("100/5%3"), ["100", "/", "5", "%", "3"])
        with self.assertRaises(ValueError):
            tokenize("1.5")

    def test_bad_postfix(self):
        with self.assertRaises(ValueError):
            eval_postfix(["1", "2"])
        with self.assertRaises(ValueError):
            eval_postfix(["1", "2", "^"])
        self.assertEqual(eval_postfix(["3", "4", "+", "2", "*"]), 14)
