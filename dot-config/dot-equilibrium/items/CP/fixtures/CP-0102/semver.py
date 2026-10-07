"""Semantic-version parsing, ordering and range checks."""


def parse(text):
    """'1.2.3' -> (1, 2, 3); a leading 'v' is allowed. Anything that is not
    three non-negative integers separated by dots raises ValueError."""
    if text.startswith("v"):
        text = text[1:]
    parts = text.split(".")
    if len(parts) != 3:
        raise ValueError("need major.minor.patch")
    nums = []
    for p in parts:
        if not p.isdigit():
            raise ValueError("not a number: " + p)
        nums.append(int(p))
    return tuple(nums)


def compare(a, b):
    """-1, 0 or 1 comparing two version strings numerically."""
    pa, pb = parse(a), parse(b)
    if pa < pb:
        return -1
    if pa > pb:
        return 1
    return 0


def bump(version, part):
    """Increment 'major', 'minor' or 'patch'; lower parts reset to zero."""
    major, minor, patch = parse(version)
    if part == "major":
        return "%d.0.0" % (major + 1)
    if part != "minor":
        return "%d.%d.0" % (major, minor + 1)
    if part == "patch":
        return "%d.%d.%d" % (major, minor, patch + 1)
    raise ValueError("unknown part: " + part)


def satisfies(version, spec):
    """spec is comma-separated clauses like '>=1.2.0,<2.0.0'. Operators:
    >=, <=, >, <, ==. All clauses must hold; an empty spec accepts anything."""
    v = parse(version)
    for clause in spec.split(","):
        clause = clause.strip()
        if not clause:
            continue
        for op in (">=", "<=", "==", ">", "<"):
            if clause.startswith(op):
                bound = parse(clause[len(op):].strip())
                break
        else:
            raise ValueError("bad clause: " + clause)
        ok = {
            ">=": v >= bound,
            "<=": v <= bound,
            "==": v == bound,
            ">": v > bound,
            "<": v < bound,
        }[op]
        if not ok:
            return False
    return True


def latest(versions, spec=""):
    """Highest version string satisfying spec, or None."""
    best = None
    for v in versions:
        if satisfies(v, spec) and (best is None or compare(v, best) > 0):
            best = v
    return best
