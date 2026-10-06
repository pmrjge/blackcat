import unittest

from rpn import tokenize, to_postfix, eval_postfix, evaluate


class Basic(unittest.TestCase):
    def test_eval(self):
        self.assertEqual(evaluate("1 + 2 * 3"), 7)

    def test_parens(self):
        self.assertEqual(evaluate("(1 + 2) * 3"), 9)

    def test_tokenize(self):
        self.assertEqual(tokenize("12+3"), ["12", "+", "3"])
