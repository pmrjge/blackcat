---
name: py-testing
description: Use for Python tests — pytest config and fixtures, hypothesis property tests, snapshots, coverage, parallel runs with xdist.
---
# Python testing

Part of `python-engineering` (baseline versions, pitfalls). Property and stateful testing across languages: `formal-methods`.

## pytest config (pyproject.toml)
```toml
[tool.pytest]                      # native TOML table (pytest >= 9); older: [tool.pytest.ini_options]
minversion = "9.0"
addopts = ["-ra", "--strict-markers", "--strict-config"]
testpaths = ["tests"]
xfail_strict = true
```

## Practice
- Fixtures (`yield` for teardown, scopes, factory fixtures), `tmp_path`, `monkeypatch` (env/attrs), `capsys`, `caplog`; `@pytest.mark.parametrize(("a", "b"), [...], ids=...)`; `pytest.approx` for floats; `pytest.raises(ValueError, match="...")`.
- hypothesis for invariants (round-trip, idempotence, ordering): `@given(st.lists(st.integers()))`, `@settings(max_examples=...)`, stateful tests; it shrinks failures and stores examples in `.hypothesis/` (gitignore it).
- Snapshots: syrupy (`snapshot` fixture, `pytest --snapshot-update`) or inline-snapshot (`snapshot()` values rewritten in the test source by its pytest options). Review snapshot diffs like code.
- Coverage: `pytest --cov=src/myapp --cov-branch --cov-report=term-missing` (pytest-cov). Parallel: pytest-xdist `-n auto`. Async tests: pytest-asyncio (`asyncio_mode = "auto"`) or anyio's plugin (`@pytest.mark.anyio`).

## Verify
- [ ] Tests cover new behavior and bug fixes; hypothesis for parsers/invariants; snapshots reviewed.
```sh
uv run pytest -q --cov=src/myapp --cov-branch
```
