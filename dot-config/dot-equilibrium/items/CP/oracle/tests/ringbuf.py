import unittest

from ringbuf import RingBuffer


class Basic(unittest.TestCase):
    def test_fifo(self):
        r = RingBuffer(3)
        r.push(1)
        r.push(2)
        self.assertEqual(r.pop(), 1)
        self.assertEqual(len(r), 1)

    def test_empty_pop(self):
        with self.assertRaises(IndexError):
            RingBuffer(2).pop()


# ---- HIDDEN ----
class Deep(unittest.TestCase):
    def test_capacity_validation(self):
        with self.assertRaises(ValueError):
            RingBuffer(0)
        RingBuffer(1)

    def test_overwrite(self):
        r = RingBuffer(3)
        self.assertIsNone(r.push("a"))
        self.assertIsNone(r.push("b"))
        self.assertIsNone(r.push("c"))
        self.assertTrue(r.is_full())
        self.assertEqual(r.push("d"), "a")
        self.assertEqual(r.to_list(), ["b", "c", "d"])
        self.assertEqual(r.push("e"), "b")
        self.assertEqual(r.to_list(), ["c", "d", "e"])
        self.assertEqual(len(r), 3)

    def test_wraparound(self):
        r = RingBuffer(3)
        for i in range(3):
            r.push(i)
        self.assertEqual(r.pop(), 0)
        self.assertFalse(r.is_full())
        r.push(3)
        self.assertEqual(r.to_list(), [1, 2, 3])
        self.assertEqual(r.pop(), 1)
        self.assertEqual(r.pop(), 2)
        r.push(4)
        r.push(5)
        self.assertEqual(r.to_list(), [3, 4, 5])
        self.assertEqual(r.peek(), 3)
        self.assertEqual(r.peek(2), 5)

    def test_peek_errors(self):
        r = RingBuffer(3)
        with self.assertRaises(IndexError):
            r.peek()
        r.push(1)
        self.assertEqual(r.peek(0), 1)
        with self.assertRaises(IndexError):
            r.peek(1)
        with self.assertRaises(IndexError):
            r.peek(-1)

    def test_len_and_pop_to_empty(self):
        r = RingBuffer(2)
        self.assertEqual(len(r), 0)
        r.push(1)
        self.assertEqual(len(r), 1)
        r.push(2)
        self.assertEqual(len(r), 2)
        r.push(3)
        self.assertEqual(len(r), 2)
        r.pop()
        r.pop()
        self.assertEqual(len(r), 0)
        with self.assertRaises(IndexError):
            r.pop()

    def test_capacity_one(self):
        r = RingBuffer(1)
        self.assertIsNone(r.push(1))
        self.assertTrue(r.is_full())
        self.assertEqual(r.push(2), 1)
        self.assertEqual(r.to_list(), [2])
        self.assertEqual(r.pop(), 2)

    def test_clear(self):
        r = RingBuffer(3)
        for i in range(5):
            r.push(i)
        r.clear()
        self.assertEqual(len(r), 0)
        self.assertEqual(r.to_list(), [])
        r.push(9)
        self.assertEqual(r.to_list(), [9])
        self.assertFalse(r.is_full())
