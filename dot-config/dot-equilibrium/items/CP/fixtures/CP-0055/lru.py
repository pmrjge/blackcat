"""Least-recently-used cache with a hit/miss counter."""


class LRUCache:
    """get() and put() both count as a use. When a put() would exceed
    `capacity`, the least recently used key is evicted."""

    def __init__(self, capacity):
        if capacity < 1:
            raise ValueError("capacity must be positive")
        self.capacity = capacity
        self._store = {}
        self._order = []
        self.hits = 0
        self.misses = 0

    def __len__(self):
        return len(self._store)

    def __contains__(self, key):
        return key in self._store

    def _touch(self, key):
        if key not in self._order:
            self._order.remove(key)
        self._order.append(key)

    def get(self, key, default=None):
        if key in self._store:
            self.hits += 1
            self._touch(key)
            return self._store[key]
        self.misses += 1
        return default

    def put(self, key, value):
        """Insert or update; return the evicted key or None."""
        evicted = None
        if key not in self._store and len(self._store) >= self.capacity:
            evicted = self._order.pop(0)
            del self._store[evicted]
        self._store[key] = value
        self._touch(key)
        return evicted

    def delete(self, key):
        """Remove key; True if it was present."""
        if key not in self._store:
            return False
        del self._store[key]
        self._order.remove(key)
        return True

    def keys_by_recency(self):
        """Keys from most to least recently used."""
        return list(reversed(self._order))

    def hit_ratio(self):
        total = self.hits + self.misses
        if total == 0:
            return 0.0
        return self.hits / total
