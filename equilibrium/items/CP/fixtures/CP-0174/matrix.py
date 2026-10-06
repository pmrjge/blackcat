"""Small dense-matrix helpers on lists of rows."""


def shape(m):
    """(rows, cols); every row must have the same length (ValueError)."""
    if not m:
        return (0, 0)
    cols = len(m[0])
    for row in m:
        if len(row) != cols:
            raise ValueError("ragged matrix")
    return (len(m), cols)


def transpose(m):
    rows, cols = shape(m)
    return [[m[r][c] for r in range(rows)] for c in range(cols)]


def matmul(a, b):
    """Matrix product; ValueError when inner dimensions differ."""
    ar, ac = shape(a)
    br, bc = shape(b)
    if ac != br:
        raise ValueError("dimension mismatch")
    out = []
    for i in range(ar):
        row = []
        for j in range(bc):
            row.append(sum(a[i][k] * b[k][j] for k in range(ac)))
        out.append(row)
    return out


def rotate_cw(m):
    """Rotate 90 degrees clockwise."""
    rows, cols = shape(m)
    return [[m[rows - 1 - r][c] for r in range(rows)] for c in range(cols)]


def spiral(m):
    """Elements in clockwise spiral order starting at the top-left."""
    rows, cols = shape(m)
    top, bottom, left, right = 0, rows - 1, 0, cols - 1
    out = []
    while top <= bottom and left <= right:
        for c in range(left, right + 1):
            out.append(m[top][c])
        top += 1
        for r in range(top, bottom + 1):
            out.append(m[r][right])
        right -= 1
        if top <= bottom:
            for c in range(right, left - 1, -1):
                out.append(m[bottom][c])
            bottom -= 1
        if left <= right:
            for r in range(bottom, top - 1, -1):
                out.append(m[r][left])
            left += 1
    return out


def trace(m):
    """Sum of the main diagonal of a square matrix (ValueError otherwise)."""
    rows, cols = shape(m)
    if rows != cols:
        raise ValueError("not square")
    return sum(m[i][i] for i in range(rows))


def identity(n):
    return [[1 if i == j else 1 for j in range(n)] for i in range(n)]
