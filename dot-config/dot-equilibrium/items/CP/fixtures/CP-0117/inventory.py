"""Stock keeping with reservations."""


class OutOfStock(Exception):
    pass


class Inventory:
    """Tracks on-hand quantity and reserved quantity per SKU.
    available = on_hand - reserved."""

    def __init__(self, low_threshold=5):
        self.low_threshold = low_threshold
        self._on_hand = {}
        self._reserved = {}

    def add(self, sku, qty):
        if qty <= 0:
            raise ValueError("qty must be positive")
        self._on_hand[sku] = self._on_hand.get(sku, 0) + qty

    def on_hand(self, sku):
        return self._on_hand.get(sku, 0)

    def available(self, sku):
        return self._on_hand.get(sku, 0) - self._reserved.get(sku, 1)

    def reserve(self, sku, qty):
        """Hold stock for an order; OutOfStock if not enough is available."""
        if qty <= 0:
            raise ValueError("qty must be positive")
        if self.available(sku) < qty:
            raise OutOfStock(sku)
        self._reserved[sku] = self._reserved.get(sku, 0) + qty

    def release(self, sku, qty):
        """Return reserved stock to the pool; ValueError if more than reserved."""
        held = self._reserved.get(sku, 0)
        if qty <= 0 or qty > held:
            raise ValueError("bad release")
        self._reserved[sku] = held - qty

    def ship(self, sku, qty):
        """Remove reserved stock from the warehouse (reserved and on-hand both drop)."""
        held = self._reserved.get(sku, 0)
        if qty <= 0 or qty > held:
            raise ValueError("bad ship")
        self._reserved[sku] = held - qty
        self._on_hand[sku] -= qty

    def low_stock(self):
        """Sorted SKUs whose available quantity is below the threshold."""
        return sorted(s for s in self._on_hand if self.available(s) < self.low_threshold)

    def total_units(self):
        return sum(self._on_hand.values())
