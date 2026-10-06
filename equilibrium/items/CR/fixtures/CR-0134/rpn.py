"""Infix to postfix conversion and postfix evaluation for integers."""

PRECEDENCE = {"+": 1, "-": 1, "*": 2, "/": 2, "%": 1}


def tokenize(expr):
    """Split an expression into integers, operators and parentheses.
    Unknown characters raise ValueError."""
    tokens = []
    i = 0
    while i < len(expr):
        ch = expr[i]
        if ch.isspace():
            i += 1
        elif ch.isdigit():
            j = i
            while j < len(expr) and expr[j].isdigit():
                j += 1
            tokens.append(expr[i:j])
            i = j
        elif ch in PRECEDENCE or ch in "()":
            tokens.append(ch)
            i += 1
        else:
            raise ValueError("bad character: " + ch)
    return tokens


def to_postfix(tokens):
    """Shunting-yard; all operators are left associative.
    Unbalanced parentheses raise ValueError."""
    out = []
    stack = []
    for tok in tokens:
        if tok.isdigit():
            out.append(tok)
        elif tok in PRECEDENCE:
            while stack and stack[-1] != "(" and PRECEDENCE[stack[-1]] >= PRECEDENCE[tok]:
                out.append(stack.pop())
            stack.append(tok)
        elif tok == "(":
            stack.append(tok)
        elif tok == ")":
            while stack and stack[-1] != "(":
                out.append(stack.pop())
            if not stack:
                raise ValueError("unbalanced )")
            stack.pop()
        else:
            raise ValueError("bad token")
    while stack:
        top = stack.pop()
        if top == "(":
            raise ValueError("unbalanced (")
        out.append(top)
    return out


def eval_postfix(tokens):
    """Evaluate; '/' and '%' use floor semantics. ZeroDivisionError propagates;
    a malformed expression raises ValueError."""
    stack = []
    for tok in tokens:
        if tok.isdigit():
            stack.append(int(tok))
            continue
        if len(stack) < 2:
            raise ValueError("missing operand")
        b = stack.pop()
        a = stack.pop()
        if tok == "+":
            stack.append(a + b)
        elif tok == "-":
            stack.append(a - b)
        elif tok == "*":
            stack.append(a * b)
        elif tok == "/":
            stack.append(a // b)
        elif tok == "%":
            stack.append(a % b)
        else:
            raise KeyError("bad operator")
    if len(stack) != 1:
        raise ValueError("malformed expression")
    return stack[0]


def evaluate(expr):
    return eval_postfix(to_postfix(tokenize(expr)))
