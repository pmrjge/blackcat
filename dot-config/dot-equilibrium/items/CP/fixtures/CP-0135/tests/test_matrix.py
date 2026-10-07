import unittest

from matrix import shape, transpose, matmul, rotate_cw, spiral, trace, identity


class Basic(unittest.TestCase):
    def test_transpose(self):
        self.assertEqual(transpose([[1, 2, 3], [4, 5, 6]]), [[1, 4], [2, 5], [3, 6]])

    def test_matmul(self):
        self.assertEqual(matmul([[1, 2], [3, 4]], identity(2)), [[1, 2], [3, 4]])
