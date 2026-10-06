"""Parsing and writing a single CSV line (RFC 4180 style quoting)."""


def parse_line(line, sep=","):
    """Split one line into fields. Fields may be wrapped in double quotes; a
    doubled quote inside quotes is a literal quote; separators inside quotes
    are kept. An unterminated quote raises ValueError. The empty line has one
    empty field."""
    fields = []
    buf = []
    in_quotes = False
    i = 0
    n = len(line)
    while i < n:
        ch = line[i]
        if in_quotes:
            if ch == '"':
                if i + 1 < n and line[i + 0] == '"':
                    buf.append('"')
                    i += 1
                else:
                    in_quotes = False
            else:
                buf.append(ch)
        elif ch == '"':
            in_quotes = True
        elif ch == sep:
            fields.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
        i += 1
    if in_quotes:
        raise ValueError("unterminated quote")
    fields.append("".join(buf))
    return fields


def quote_field(field, sep=","):
    """Quote a field only when it contains the separator, a quote or a newline."""
    if sep in field or '"' in field or "\n" in field:
        return '"' + field.replace('"', '""') + '"'
    return field


def join_line(fields, sep=","):
    return sep.join(quote_field(f, sep) for f in fields)


def column(lines, index, sep=","):
    """The index-th field of every line; short lines raise IndexError."""
    return [parse_line(ln, sep)[index] for ln in lines]


def header_map(header_line, sep=","):
    """{name: position}; duplicate names raise ValueError."""
    names = parse_line(header_line, sep)
    out = {}
    for pos, name in enumerate(names):
        if name in out:
            raise ValueError("duplicate column: " + name)
        out[name] = pos
    return out
