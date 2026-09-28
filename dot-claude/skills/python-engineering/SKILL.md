---
name: python-engineering
description: Load before creating, changing, reviewing or packaging Python — uv (projects, lockfiles, tools, PEP 723 scripts), pyproject, typing, ruff, pytest, asyncio, profiling, wheels.
---
# Python engineering

## Scope and baseline
- Covers modern Python projects and scripts end to end. Data analysis method lives in `data-analysis`; ML experiment protocol in `ml-experiment`; native-extension internals in `rust-engineering`; profiling method in `cpu-performance`.
- Baseline (Sep 2026): Python 3.14 is current (3.15 due Oct 2026; 3.10 reaches end of life Oct 2026). New projects: `requires-python = ">=3.12"` unless deployment dictates otherwise (numpy 2.5 already needs ≥ 3.12). Tools: uv 0.12.x, ruff 0.16.x, pytest 9.x, mypy 2.x, pyright 1.1.41x, basedpyright 1.40.x, pyrefly 1.x, ty (beta). Re-check versions with `uv tree --outdated` or PyPI before pinning.
- Projects use their own uv-managed `.venv`. The shared venvs (`__CLAUDE_DIR__/venvs/sci/bin/python`, `__CLAUDE_DIR__/venvs/ml/bin/python`) are for ad-hoc analysis — never install project dependencies into them.
- Check library APIs against current docs (`mcp__libdocs`, official docs) before writing version-specific code.

## uv workflow (verified with uv 0.12.19)
| Task | Command |
|---|---|
| New app | `uv init myapp --python 3.13` → **packaged** src layout, `uv_build` backend, `[project.scripts] myapp = "myapp:main"` (since 0.12; older uv made unpackaged apps) |
| Other shapes | `--lib` (library + `py.typed`), `--no-package` (flat `main.py`, no build system), `--bare` (pyproject only), `--build-backend <name>` (uv, hatch, flit, pdm, poetry, setuptools, maturin, scikit) |
| Dependencies | `uv add httpx`; `uv add --dev pytest ruff` (→ `[dependency-groups] dev`); `uv add --group docs mkdocs`; `uv add --optional plot matplotlib` (extra); `uv remove x` |
| Lock / sync | `uv lock`; `uv lock --check` (CI: lock is current); `uv lock --upgrade-package httpx`; `uv sync` (editable project + dev group); `uv sync --locked` (CI); `--frozen`, `--no-dev`, `--all-extras`, `--all-groups`, `--no-editable` (deploy) |
| Run | `uv run pytest`; `uv run python -m pkg`; `uv run --with rich script.py`; `uv run --isolated ...` (throwaway env) |
| Tools | `uvx ruff check .` (= `uv tool run`); `uv tool install ruff`; `uv tool upgrade --all` |
| Pythons | `uv python install 3.13`; `uv python pin 3.13` (`.python-version`); `uv python list` / `find` |
| Release | `uv version --bump minor` (`--dry-run` to preview); `uv build` (sdist + wheel in `dist/`); `uv publish` (trusted publishing from CI) |
| Inspect/export | `uv tree`; `uv export --format pylock.toml` (PEP 751) or requirements.txt (default) |
| Experimental | `uv format` (runs its own pinned ruff), `uv check` (runs ty), `uv audit` (OSV) — they print "experimental"; gate CI on explicit ruff/type-checker runs until they stabilize |
- Commit `uv.lock`. Time-pinned resolution: `exclude-newer = "2026-09-01T00:00:00Z"` under `[tool.uv]`. Behind TLS-intercepting proxies use `UV_SYSTEM_CERTS=1` / `--system-certs` (`UV_NATIVE_TLS` is deprecated).
- Workspaces: `[tool.uv.workspace] members = ["packages/*"]`; depend on a member with `[tool.uv.sources] mylib = { workspace = true }`.
- **PEP 723 scripts** — single-file tools with inline dependencies:
```python
#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# dependencies = [
#     "rich>=15",
# ]
# ///
```
  Create with `uv init --script tool.py --python 3.13`, add deps with `uv add --script tool.py rich`, lock with `uv lock --script tool.py` (writes `tool.py.lock`); `chmod +x tool.py` and run it directly.

## Project layout
```
myapp/
  pyproject.toml   uv.lock   .python-version   README.md
  src/myapp/__init__.py   src/myapp/cli.py   src/myapp/py.typed (libraries)
  tests/test_*.py   tests/conftest.py
```
```toml
[project]
name = "myapp"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = ["httpx>=0.28"]

[project.scripts]
myapp = "myapp.cli:main"          # console entry point; GUI apps: [project.gui-scripts]
# plugin hooks: [project.entry-points."myapp.plugins"] name = "pkg.module"

[build-system]
requires = ["uv_build>=0.12.19,<0.13"]
build-backend = "uv_build"

[dependency-groups]
dev = ["pytest>=9", "hypothesis", "ruff", "basedpyright"]

[tool.ruff]
line-length = 100
[tool.ruff.lint]
select = ["E4", "E7", "E9", "F", "I", "B", "UP", "SIM", "C4", "PT", "RUF", "DTZ", "ASYNC", "PERF", "PTH", "S", "N", "TRY", "EM", "G", "LOG"]
ignore = ["TRY003", "EM101", "EM102"]
[tool.ruff.lint.per-file-ignores]
"tests/**" = ["S101"]
[tool.ruff.format]
docstring-code-format = true

[tool.pytest]                      # native TOML table (pytest >= 9); older: [tool.pytest.ini_options]
minversion = "9.0"
addopts = ["-ra", "--strict-markers", "--strict-config"]
testpaths = ["tests"]
xfail_strict = true

[tool.basedpyright]
typeCheckingMode = "recommended"
```
- src layout prevents tests from importing the working tree by accident; the project is installed editable by `uv sync`.
- Ruff infers `target-version` from `requires-python`. `ruff check --fix` then `ruff format`; the formatter is Black-compatible; `I` replaces isort.

## Typing
| Checker | When |
|---|---|
| basedpyright (`recommended` or `strict`) | Default for new projects: pyright engine, stricter defaults, pip/uv-installable, good LSP |
| pyright (`typeCheckingMode = "strict"`) | Teams already on it (the PyPI wrapper fetches Node) |
| mypy 2.x (`strict = true`) | Projects relying on mypy plugins (pydantic, Django stubs) |
| ty (beta) / pyrefly (1.x) | Very fast; evaluate on the codebase before making them a CI gate — diagnostics differ |
- Structural interfaces: `typing.Protocol`. JSON-shaped dicts: `TypedDict` (`Required`, `NotRequired`, `ReadOnly` 3.13). Generics with PEP 695 syntax (`def first[T](xs: Sequence[T]) -> T`, `type Pair[T] = tuple[T, T]`). Also `Self`, `@override` (3.12), `Literal`, `Final`, `TypeIs` (3.13), `assert_never` for exhaustive `match`.
- 3.14 evaluates annotations lazily (PEP 649/749): forward references work without quotes or the `__future__` import; read annotations at runtime via `annotationlib`. Projects supporting 3.12/3.13 still need quotes or `from __future__ import annotations`.
- Import-only-for-types under `if TYPE_CHECKING:` to break import cycles.
| Container | Use |
|---|---|
| `@dataclass(slots=True, frozen=True, kw_only=True)` | Internal value objects; no validation |
| pydantic v2 `BaseModel` / `TypeAdapter` | Parsing and validating untrusted input (HTTP, files, env, LLM output) |
| attrs | Validators/converters with dataclass-like ergonomics |
| msgspec | Very fast JSON/MessagePack (de)serialization with typed structs |
Validate at boundaries, then pass typed objects inward; don't re-validate internally.

## Testing
- Fixtures (`yield` for teardown, scopes, factory fixtures), `tmp_path`, `monkeypatch` (env/attrs), `capsys`, `caplog`; `@pytest.mark.parametrize(("a", "b"), [...], ids=...)`; `pytest.approx` for floats; `pytest.raises(ValueError, match="...")`.
- hypothesis for invariants (round-trip, idempotence, ordering): `@given(st.lists(st.integers()))`, `@settings(max_examples=...)`, stateful tests; it shrinks failures and stores examples in `.hypothesis/` (gitignore it).
- Snapshots: syrupy (`snapshot` fixture, `pytest --snapshot-update`) or inline-snapshot (`snapshot()` values rewritten in the test source by its pytest options). Review snapshot diffs like code.
- Coverage: `pytest --cov=src/myapp --cov-branch --cov-report=term-missing` (pytest-cov). Parallel: pytest-xdist `-n auto`. Async tests: pytest-asyncio (`asyncio_mode = "auto"`) or anyio's plugin (`@pytest.mark.anyio`).

## Async
- `asyncio.run(main())`; structure with `asyncio.TaskGroup` (first failure cancels siblings; errors surface as `ExceptionGroup` → handle with `except*`), bound waits with `asyncio.timeout(s)`, limit concurrency with `asyncio.Semaphore`, pipelines with `asyncio.Queue` (`shutdown()` in 3.13).
- Never swallow `CancelledError` — clean up and re-raise. Keep a reference to every `create_task` result (the loop holds tasks weakly). Blocking calls go through `asyncio.to_thread`.
- anyio for backend-agnostic libraries: `create_task_group()`, cancel scopes (`move_on_after`, `fail_after`), `anyio.to_thread.run_sync`.
- 3.14 introspection of a live process: `uv run python -m asyncio ps PID`, `uv run python -m asyncio pstree PID`.
- Free-threaded 3.14t is officially supported (PEP 779) but every C extension must declare support — check wheels before depending on it.

## Performance
Ladder: better algorithm/data structure → vectorize (numpy; polars lazy `scan_*`…`collect()`; duckdb SQL) → profile → compile hot loops (numba `@njit(cache=True)`: first call compiles, supports a numpy subset) → Rust extension (PyO3 + maturin) → processes for CPU-bound pure-Python work.
- Profilers: `py-spy record -o profile.svg -- .venv/bin/python app.py` or `py-spy top --pid PID` (sampling, attach to live processes); scalene (line-level CPU/memory/GPU); memray (`memray run`, `memray flamegraph`) for allocations; `uv run python -X importtime` for startup.
- PyO3/maturin: `uv init --build-backend maturin`; add `[tool.uv] cache-keys = [{ file = "pyproject.toml" }, { file = "Cargo.toml" }, { file = "**/*.rs" }]` so `uv sync`/`uv run` rebuild after Rust edits; build abi3 wheels (pyo3 feature `abi3-py312`) for one wheel per platform; release the GIL around long Rust work (the PyO3 method for this was renamed across versions — check the docs of the pinned PyO3).
- Measure before/after with the same inputs; report median of repeated runs.

## CLIs, logging, configuration
- CLI: `argparse` (stdlib; 3.14 colors help by default and offers `suggest_on_error=True` for mistyped choices) for scripts and small tools; `typer` (type-hint driven) for larger apps. Entry points via `[project.scripts]`; data to stdout, diagnostics to stderr; `sys.exit(code)`.
- Logging: libraries call `logging.getLogger(__name__)` and add no handlers; the application configures once (`logging.basicConfig` or `dictConfig`); lazy formatting `log.info("loaded %s rows", n)` (ruff `G`); `structlog` for structured JSON logs. Never log secrets or tokens.
- Config: TOML via stdlib `tomllib`; typed env settings with `pydantic-settings`; `.env` only for local development; secrets from the environment or a secret manager, never committed.

## Platform notes
- Apple Silicon: uv-managed Pythons are native arm64 — check with `uv run python -c "import platform; print(platform.processor())"` (`arm`; `i386` means Rosetta). A missing arm64 wheel falls back to building the sdist (needs Xcode command-line tools, may fail) — prefer a version that ships wheels.
- MLX: `uv add mlx mlx-lm` on macOS ≥ 14 with Apple silicon. On Linux: `mlx[cuda12]` (driver ≥ 550.54.14, GPU ≥ SM 7.5, glibc ≥ 2.35), `mlx[cuda13]` (driver ≥ 580) or `mlx[cpu]`. Gate platform-specific deps with markers: `"mlx>=0.30; sys_platform == 'darwin'"`.
- PyTorch: PyPI's macOS arm64 wheels have no CUDA but include the MPS backend (`torch.backends.mps.is_available()`); PyPI's Linux wheels target CUDA 13.0 (since PyTorch 2.11) and need a driver that supports it. RTX 50-series (Blackwell, sm_120) needs CUDA ≥ 12.8 builds; CUDA 13.0 builds need driver ≥ 580 — the cu128 index stops at torch 2.11, so upgrade an older driver rather than pinning cu128; confirm `sm_120` in `torch.cuda.get_arch_list()`. Index only Linux, fall back to PyPI on macOS:
```toml
[tool.uv.sources]
torch = [{ index = "pytorch-cu130", marker = "sys_platform == 'linux'" }]
[[tool.uv.index]]
name = "pytorch-cu130"
url = "https://download.pytorch.org/whl/cu130"
explicit = true            # only packages pinned to this index use it
```
  `--torch-backend=auto` (GPU autodetection) exists only in the `uv pip` interface. Driver/CUDA/PyTorch matching on the Linux laptop is covered in `linux-workstation`.

## Pitfalls
| Pitfall | Signature | Fix |
|---|---|---|
| Mutable default argument | state leaks between calls (ruff B006) | `None` sentinel or `field(default_factory=list)` |
| Late-binding closures in loops | every lambda sees the last value (B023) | bind now: `lambda i=i: i` or `functools.partial` |
| Import cycles | `ImportError: cannot import name` / partially initialized module | move shared types to a leaf module; `TYPE_CHECKING` imports; import inside the function |
| Float equality | flaky `==` | `math.isclose(a, b, rel_tol=..., abs_tol=...)`, `pytest.approx`; `Decimal`/`Fraction` for exact arithmetic |
| Naive datetimes | wrong offsets, DST bugs (DTZ005) | `datetime.now(tz=UTC)` (`from datetime import UTC`), store UTC, convert with `zoneinfo` at the edges; `utcnow()` is deprecated |
| Swallowed errors | bugs vanish | catch specific exceptions; bare `except:` also traps `KeyboardInterrupt` |
| Shadowed stdlib | `random.py`/`types.py` in the project breaks imports | rename the module |
| Mutating while iterating | `RuntimeError: dictionary changed size during iteration` | iterate over a copy or build a new collection |
| Implicit encodings | platform-dependent text I/O | pass `encoding="utf-8"` explicitly |
| Shell injection | `shell=True` with user input (S602) | `subprocess.run([...], check=True, text=True)` |
| Unsafe deserialization | `pickle`/`yaml.load` on untrusted data runs code | JSON/msgspec; `yaml.safe_load` |
| Orphaned tasks | background task silently cancelled or GC'd | keep references; use `TaskGroup` |

## Review checklist
- [ ] `uv lock --check` passes; new dependencies justified (maintenance, license, wheel availability on macOS arm64 and Linux x86_64).
- [ ] ruff clean (lint + format); type checker clean at the project's strictness; no new `Any`/`type: ignore` without a reason comment.
- [ ] Tests cover new behavior and bug fixes; hypothesis for parsers/invariants; snapshots reviewed.
- [ ] Inputs validated at boundaries; timezone-aware datetimes; explicit encodings; no secrets in code or logs.
- [ ] Async code cancels cleanly and doesn't block the loop; subprocess calls use argument lists.
- [ ] Performance claims backed by profiles or benchmarks with the same inputs.

## Verify
```sh
uv lock --check && uv sync --locked
uv run ruff format --check . && uv run ruff check .
uv run basedpyright            # or: uv run pyright / uv run mypy src
uv run pytest -q --cov=src/myapp --cov-branch
uv build && uv run --isolated --with dist/*.whl myapp --help   # the built wheel installs and runs
```

## Deliverables / Report
- Files changed; commands run with decisive output (test counts, coverage %, type-check error count).
- Python version range, new dependencies (version, license, why), lockfile updated.
- For performance work: profile summary (top functions) and a before/after table with identical inputs.
- Residual risks: platform-specific wheels not tested, untyped third-party APIs, skipped tests.
