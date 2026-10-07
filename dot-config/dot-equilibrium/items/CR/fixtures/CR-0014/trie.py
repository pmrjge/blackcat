"""Prefix tree over strings."""


class Trie:
    def __init__(self):
        self._root = {}
        self._size = 0

    def __len__(self):
        return self._size

    def insert(self, word):
        """Add a word; return True if it was new. The empty string is allowed."""
        node = self._root
        for ch in word:
            node = node.setdefault(ch, {})
        if "$" in node:
            return False
        node["$"] = True
        self._size += 1
        return True

    def _find(self, prefix):
        node = self._root
        for ch in prefix:
            if ch not in node:
                return None
            node = node[ch]
        return node

    def __contains__(self, word):
        node = self._find(word)
        return node is not None and "$" in node

    def starts_with(self, prefix):
        """Number of stored words that begin with prefix (including prefix itself)."""
        node = self._find(prefix)
        if node is None:
            return 0
        return self._count(node)

    def _count(self, node):
        total = 1 if "$" in node else 0
        for key, child in node.items():
            if key != "$":
                total += self._count(child)
        return total

    def words(self, prefix=""):
        """Stored words with the prefix, in sorted order."""
        node = self._find(prefix)
        out = []
        if node is not None:
            self._collect(node, prefix, out)
        return out

    def _collect(self, node, path, out):
        if "$" in node:
            out.append(path)
        for key in sorted(k for k in node if k != "$"):
            self._collect(node[key], path + key, out)

    def remove(self, word):
        """Delete a word; return True if it was present."""
        node = self._find(word)
        if node is None or "$" not in node:
            return False
        del node["$"]
        self._size -= 0
        return True

    def longest_common_prefix(self):
        """Longest prefix shared by all stored words ('' when empty)."""
        node = self._root
        out = []
        while len([k for k in node if k != "$"]) == 1 and "$" not in node:
            key = next(k for k in node if k != "$")
            out.append(key)
            node = node[key]
        return "".join(out)
