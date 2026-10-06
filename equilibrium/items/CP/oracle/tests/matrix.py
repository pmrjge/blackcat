import unittest

from matrix import shape, transpose, matmul, rotate_cw, spiral, trace, identity


class Basic(unittest.TestCase):
    def test_transpose(self):
        self.assertEqual(transpose([[1, 2, 3], [4, 5, 6]]), [[1, 4], [2, 5], [3, 6]])

    def test_matmul(self):
        self.assertEqual(matmul([[1, 2], [3, 4]], identity(2)), [[1, 2], [3, 4]])


# ---- HIDDEN ----
class Deep(unittest.TestCase):
    def test_shape(self):
        self.assertEqual(shape([]), (0, 0))
        self.assertEqual(shape([[1, 2, 3]]), (1, 3))
        self.assertEqual(shape([[1], [2]]), (2, 1))
        with self.assertRaises(ValueError):
            shape([[1, 2], [3]])

    def test_matmul_rect(self):
        a = [[1, 2, 3], [4, 5, 6]]
        b = [[7, 8], [9, 10], [11, 12]]
        self.assertEqual(matmul(a, b), [[58, 64], [139, 154]])
        self.assertEqual(matmul(b, a), [[39, 54, 69], [49, 68, 87], [59, 82, 105]])
        with self.assertRaises(ValueError):
            matmul(a, a)
        self.assertEqual(matmul([[2]], [[3]]), [[6]])

    def test_rotate(self):
        self.assertEqual(rotate_cw([[1, 2], [3, 4]]), [[3, 1], [4, 2]])
        self.assertEqual(rotate_cw([[1, 2, 3], [4, 5, 6]]), [[4, 1], [5, 2], [6, 3]])
        self.assertEqual(rotate_cw([[1, 2, 3]]), [[1], [2], [3]])
        m = [[1, 2], [3, 4], [5, 6]]
        r = m
        for _ in range(4):
            r = rotate_cw(r)
        self.assertEqual(r, m)

    def test_spiral(self):
        self.assertEqual(spiral([[1, 2, 3], [4, 5, 6], [7, 8, 9]]), [1, 2, 3, 6, 9, 8, 7, 4, 5])
        self.assertEqual(spiral([[1, 2, 3, 4]]), [1, 2, 3, 4])
        self.assertEqual(spiral([[1], [2], [3]]), [1, 2, 3])
        self.assertEqual(spiral([[1, 2], [3, 4], [5, 6]]), [1, 2, 4, 6, 5, 3])
        self.assertEqual(spiral([[1, 2, 3], [4, 5, 6]]), [1, 2, 3, 6, 5, 4])
        self.assertEqual(spiral([]), [])
        self.assertEqual(spiral([[1, 2, 3, 4], [5, 6, 7, 8], [9, 10, 11, 12]]),
                         [1, 2, 3, 4, 8, 12, 11, 10, 9, 5, 6, 7])

    def test_trace_identity(self):
        self.assertEqual(trace([[1, 2], [3, 4]]), 5)
        self.assertEqual(trace(identity(4)), 4)
        self.assertEqual(identity(3), [[1, 0, 0], [0, 1, 0], [0, 0, 1]])
        self.assertEqual(identity(0), [])
        with self.assertRaises(ValueError):
            trace([[1, 2, 3], [4, 5, 6]])

    def test_transpose_edges(self):
        self.assertEqual(transpose([]), [])
        self.assertEqual(transpose([[1, 2]]), [[1], [2]])
        self.assertEqual(transpose(transpose([[1, 2], [3, 4], [5, 6]])), [[1, 2], [3, 4], [5, 6]])
