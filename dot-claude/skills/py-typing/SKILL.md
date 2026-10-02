---
name: py-typing
description: Load for Python typing and linting — basedpyright/mypy/ty, typing features, ruff config.
---
# Python typing and linting

Part of `python-engineering` (baseline versions, pitfalls).

## Ruff and type-checker config (pyproject.toml)
```toml
[tool.ruff]
line-length = 100
[tool.ruff.lint]
select = ["E4", "E7", "E9", "F", "I", "B", "UP", "SIM", "C4", "PT", "RUF", "DTZ", "ASYNC", "PERF", "PTH", "S", "N", "TRY", "EM", "G", "LOG"]
ignore = ["TRY003", "EM101", "EM102"]
[tool.ruff.lint.per-file-ignores]
"tests/**" = ["S101"]
[tool.ruff.format]
docstring-code-format = true

[tool.basedpyright]
typeCheckingMode = "recommended"
```
- Ruff infers `target-version` from `requires-python`. `ruff check --fix` then `ruff format`; the formatter is Black-compatible; `I` replaces isort.

## Type checkers
| Checker | When |
|---|---|
| basedpyright (`recommended` or `strict`) | Default for new projects: pyright engine, stricter defaults, pip/uv-installable, good LSP |
| pyright (`typeCheckingMode = "strict"`) | Teams already on it (the PyPI wrapper fetches Node) |
| mypy 2.x (`strict = true`) | Projects relying on mypy plugins (pydantic, Django stubs) |
| ty (beta) / pyrefly (1.x) | Very fast; evaluate on the codebase before making them a CI gate — diagnostics differ |

## Typing features
- Structural interfaces: `typing.Protocol`. JSON-shaped dicts: `TypedDict` (`Required`, `NotRequired`, `ReadOnly` 3.13). Generics with PEP 695 syntax (`def first[T](xs: Sequence[T]) -> T`, `type Pair[T] = tuple[T, T]`). Also `Self`, `@override` (3.12), `Literal`, `Final`, `TypeIs` (3.13), `assert_never` for exhaustive `match`.
- 3.14 evaluates annotations lazily (PEP 649/749): forward references work without quotes or the `__future__` import; read annotations at runtime via `annotationlib`. Projects supporting 3.12/3.13 still need quotes or `from __future__ import annotations`.
- Import-only-for-types under `if TYPE_CHECKING:` to break import cycles.

## Data containers
| Container | Use |
|---|---|
| `@dataclass(slots=True, frozen=True, kw_only=True)` | Internal value objects; no validation |
| pydantic v2 `BaseModel` / `TypeAdapter` | Parsing and validating untrusted input (HTTP, files, env, LLM output) |
| attrs | Validators/converters with dataclass-like ergonomics |
| msgspec | Very fast JSON/MessagePack (de)serialization with typed structs |
Validate at boundaries, then pass typed objects inward; don't re-validate internally.

## Verify
- [ ] ruff clean (lint + format); type checker clean at the project's strictness; no new `Any`/`type: ignore` without a reason comment.
```sh
uv run ruff format --check . && uv run ruff check .
uv run basedpyright            # or: uv run pyright / uv run mypy src
```
