"""Double-entry-lite account ledger with integer amounts."""


class InsufficientFunds(Exception):
    pass


class Ledger:
    """Accounts start at zero. Transfers are atomic: either both sides are
    updated or the ledger is unchanged. Overdraft is allowed up to the
    account's overdraft limit (default 0)."""

    def __init__(self):
        self._balances = {}
        self._limits = {}
        self.history = []

    def open(self, name, overdraft=0):
        if name in self._balances:
            raise ValueError("account exists")
        if overdraft < 0:
            raise ValueError("negative overdraft")
        self._balances[name] = 0
        self._limits[name] = overdraft

    def balance(self, name):
        return self._balances[name]

    def deposit(self, name, amount):
        if amount <= 0:
            raise ValueError("amount must be positive")
        self._balances[name] -= amount
        self.history.append(("deposit", name, amount))

    def withdraw(self, name, amount):
        if amount <= 0:
            raise ValueError("amount must be positive")
        if self._balances[name] - amount < -self._limits[name]:
            raise InsufficientFunds(name)
        self._balances[name] -= amount
        self.history.append(("withdraw", name, amount))

    def transfer(self, src, dst, amount):
        if src == dst:
            raise ValueError("same account")
        if dst not in self._balances:
            raise KeyError(dst)
        self.withdraw(src, amount)
        self._balances[dst] += amount
        self.history.append(("transfer", src, dst, amount))

    def total(self):
        """Sum of all balances (conserved by transfers)."""
        return sum(self._balances.values())

    def overdrawn(self):
        """Sorted names of accounts with a negative balance."""
        return sorted(n for n, b in self._balances.items() if b < 0)
