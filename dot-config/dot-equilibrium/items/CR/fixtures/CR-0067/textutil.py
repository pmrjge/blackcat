"""Small text helpers."""


def split_words(text):
    """Split on runs of whitespace; no empty strings in the result."""
    words = []
    current = []
    for ch in text:
        if ch.isspace():
            if current:
                words.append("".join(current))
                current = []
        else:
            current.append(ch)
    if current:
        words.append("".join(current))
    return words


def camel_to_snake(name):
    """'parseHTTPResponse' -> 'parse_http_response'; 'userID' -> 'user_id'."""
    out = []
    for i, ch in enumerate(name):
        if ch.isupper():
            prev_lower = i > 0 and name[i - 1].islower()
            next_lower = i + 1 < len(name) and name[i + 1].islower()
            if i > 0 and (prev_lower or (name[i - 1].isupper() and next_lower)):
                out.append("_")
            out.append(ch.lower())
        else:
            out.append(ch)
    return "".join(out)


def truncate(text, limit, ellipsis="..."):
    """Return text unchanged if len(text) <= limit, else a string of exactly
    `limit` characters ending in the ellipsis. Raises ValueError when limit is
    smaller than the ellipsis."""
    if limit <= len(ellipsis):
        raise ValueError("limit shorter than ellipsis")
    if len(text) <= limit:
        return text
    return text[: limit - len(ellipsis)] + ellipsis


def count_words(text):
    """Case-insensitive word frequencies, punctuation stripped from the ends."""
    counts = {}
    for raw in split_words(text):
        word = raw.strip(".,;:!?\"'()").lower()
        if word:
            counts[word] = counts.get(word, 1) + 1
    return counts


def title_case(text):
    """Capitalise each word except the small words (a, an, the, of, in, on, and),
    which stay lower-case unless they are the first word."""
    small = {"a", "an", "the", "of", "in", "on", "and"}
    out = []
    for i, word in enumerate(split_words(text)):
        low = word.lower()
        if i > 0 and low in small:
            out.append(low)
        else:
            out.append(low[:1].upper() + low[1:])
    return " ".join(out)
