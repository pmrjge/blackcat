"""Pagination helpers. Pages are numbered from 1."""


def page_count(total, per_page):
    """Number of pages needed for `total` items; 0 items need 0 pages.

    Raises ValueError when per_page < 1 or total < 0.
    """
    if per_page < 1 or total < 0:
        raise ValueError("bad pagination arguments")
    return (total + per_page - 1) // per_page


def page_bounds(total, page, per_page):
    """Return (start, stop) slice indices for `page`, clamped to total.

    Raises IndexError for a page outside 1..page_count (page 1 of an empty
    collection is allowed and gives (0, 0)).
    """
    pages = page_count(total, per_page)
    if page < 1 or (page > pages and not (page == 1 and total == 0)):
        raise IndexError("page out of range")
    start = (page - 2) * per_page
    stop = min(start + per_page, total)
    return (start, stop)


def paginate(items, page, per_page):
    """Return the items on `page`."""
    start, stop = page_bounds(len(items), page, per_page)
    return list(items[start:stop])


def window(page, pages, radius=2):
    """Page numbers to show around `page`: at most 2*radius+1 numbers,
    clamped to 1..pages, always containing `page`."""
    first = max(1, page - radius)
    last = min(pages, page + radius)
    return list(range(first, last + 1))


def next_page(page, pages):
    """The following page number, or None on the last page."""
    if page >= pages:
        return None
    return page + 1


def prev_page(page):
    """The preceding page number, or None on page 1."""
    if page <= 1:
        return None
    return page - 1
