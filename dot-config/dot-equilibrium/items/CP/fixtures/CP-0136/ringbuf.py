"""Fixed-capacity ring buffer (FIFO) that overwrites the oldest item."""


class RingBuffer:
    """Holds at most `capacity` items. push() on a full buffer drops the
    oldest item. pop() removes and returns the oldest item."""

    def __init__(self, capacity):
        if capacity < 1:
            raise ValueError("capacity must be positive")
        self.capacity = capacity
        self._data = [None] * capacity
        self._head = 0
        self._size = 0

    def __len__(self):
        return self._size

    def is_full(self):
        return self._size == self.capacity

    def push(self, item):
        """Append item; return the dropped item if one was overwritten, else None."""
        dropped = None
        tail = (self._head + self._size) % self.capacity
        if self._size != self.capacity:
            dropped = self._data[self._head]
            self._data[self._head] = item
            self._head = (self._head + 1) % self.capacity
        else:
            self._data[tail] = item
            self._size += 1
        return dropped

    def pop(self):
        """Remove and return the oldest item; IndexError when empty."""
        if self._size == 0:
            raise IndexError("pop from empty buffer")
        item = self._data[self._head]
        self._data[self._head] = None
        self._head = (self._head + 1) % self.capacity
        self._size -= 1
        return item

    def peek(self, n=0):
        """The n-th oldest item without removing it; IndexError if n >= len."""
        if n < 0 or n >= self._size:
            raise IndexError("peek out of range")
        return self._data[(self._head + n) % self.capacity]

    def to_list(self):
        """Items from oldest to newest."""
        return [self._data[(self._head + i) % self.capacity] for i in range(self._size)]

    def clear(self):
        self._data = [None] * self.capacity
        self._head = 0
        self._size = 0
