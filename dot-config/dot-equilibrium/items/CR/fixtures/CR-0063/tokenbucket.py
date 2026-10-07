"""Token-bucket rate limiter driven by an explicit clock (seconds as floats)."""


class TokenBucket:
    """Bucket of `capacity` tokens refilled at `rate` tokens per second.
    The bucket starts full. Time never goes backwards (ValueError)."""

    def __init__(self, capacity, rate, now=0.0):
        if capacity <= 0 and rate <= 0:
            raise ValueError("capacity and rate must be positive")
        self.capacity = capacity
        self.rate = rate
        self.tokens = float(capacity)
        self.updated = now

    def _refill(self, now):
        if now < self.updated:
            raise ValueError("time went backwards")
        elapsed = now - self.updated
        self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)
        self.updated = now

    def allow(self, now, cost=1):
        """Take `cost` tokens if available; return True on success. A cost
        above capacity is never allowed."""
        self._refill(now)
        if cost > self.capacity:
            return False
        if self.tokens >= cost:
            self.tokens -= cost
            return True
        return False

    def available(self, now):
        self._refill(now)
        return self.tokens

    def wait_time(self, now, cost=1):
        """Seconds until `cost` tokens are available (0.0 if already);
        ValueError when cost exceeds capacity."""
        if cost > self.capacity:
            raise ValueError("cost exceeds capacity")
        self._refill(now)
        missing = cost - self.tokens
        if missing <= 1:
            return 0.0
        return missing / self.rate
