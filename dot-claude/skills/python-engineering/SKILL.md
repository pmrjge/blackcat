---
name: python-engineering
description: Use for any Python work — uv, PEP 723 scripts, typing, ruff, pytest, asyncio, profiling, wheels.
---
# Python engineering

## Scope and baseline
- Covers modern Python projects and scripts end to end. Data analysis method lives in `data-analysis`; ML experiment protocol in `ml-experiment`; native-extension internals in `rust-engineering`; profiling method in `cpu-performance`.
- Baseline: Python 3.14 is current (bugfix); 3.15 is in prerelease (3.15.0rc2 tagged; first release scheduled Oct 2026); 3.10 reached end of life on 2026-10-01. New projects: `requires-python = ">=3.12"` unless deployment dictates otherwise (numpy 2.5 already needs ≥ 3.12). Tools: uv 0.12.x, ruff 0.16.x, pytest 9.x, mypy 2.x, pyright 1.1.41x, basedpyright 1.40.x, pyrefly 1.x, ty (beta, 0.0.x). Re-check versions with `uv tree --outdated` or PyPI before pinning.
- Verified 2026-10-02 https://devguide.python.org/versions/, `git ls-remote --tags https://github.com/python/cpython`, https://pypi.org/pypi/<pkg>/json (uv 0.12.22, ruff 0.16.10, pytest 9.1.1, mypy 2.4.0, pyright 1.1.414, basedpyright 1.40.1, pyrefly 1.3.2, ty 0.0.84, numpy 2.5.3 requires ≥ 3.12). Feature-since claims in the modules (3.12–3.14, PEP numbers, uv 0.12 behaviour): unverified (checked when written, Sep 2026).
- Projects use their own uv-managed `.venv`. The shared venvs (`__CLAUDE_DIR__/venvs/sci/bin/python`, `__CLAUDE_DIR__/venvs/ml/bin/python`) are for ad-hoc analysis — never install project dependencies into them.
- Check library APIs against current docs (`mcp__libdocs`, official docs) before writing version-specific code.

## Modules (load the one the task touches)
| Module | Load for |
|---|---|
| `py-uv-packaging` | uv projects, lockfiles, PEP 723 scripts, pyproject layout, builds, MLX/PyTorch wheels |
| `py-typing` | type checkers, typing features, data containers, ruff lint/format config |
| `py-testing` | pytest config and fixtures, hypothesis, snapshots, coverage, xdist, async tests |
| `py-async` | asyncio TaskGroup, cancellation, timeouts, anyio, free-threaded 3.14t |
| `py-perf` | the optimization ladder, profilers, numba, PyO3/maturin extensions |

## CLIs, logging, configuration
- CLI: `argparse` (stdlib; 3.14 colors help by default and offers `suggest_on_error=True` for mistyped choices) for scripts and small tools; `typer` (type-hint driven) for larger apps. Entry points via `[project.scripts]`; data to stdout, diagnostics to stderr; `sys.exit(code)`.
- Logging: libraries call `logging.getLogger(__name__)` and add no handlers; the application configures once (`logging.basicConfig` or `dictConfig`); lazy formatting `log.info("loaded %s rows", n)` (ruff `G`); `structlog` for structured JSON logs. Never log secrets or tokens.
- Config: TOML via stdlib `tomllib`; typed env settings with `pydantic-settings`; `.env` only for local development; secrets from the environment or a secret manager, never committed.

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
- [ ] Inputs validated at boundaries; timezone-aware datetimes; explicit encodings; no secrets in code or logs.
- [ ] Subprocess calls use argument lists; no pitfall from the table above.
- [ ] Each loaded module's Verify items hold (lockfile, types, tests, async, performance).

## Verify
Run the Verify block of every module the change touched — at least lock and sync (`py-uv-packaging`), lint and types (`py-typing`) and tests (`py-testing`).

## Deliverables / Report
- Files changed; commands run with decisive output (test counts, coverage %, type-check error count).
- Python version range, new dependencies (version, license, why), lockfile updated.
- For performance work: profile summary (top functions) and a before/after table with identical inputs.
- Residual risks: platform-specific wheels not tested, untyped third-party APIs, skipped tests.
