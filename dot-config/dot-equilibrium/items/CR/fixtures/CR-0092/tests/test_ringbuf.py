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
