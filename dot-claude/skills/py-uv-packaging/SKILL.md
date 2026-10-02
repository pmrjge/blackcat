---
name: py-uv-packaging
description: Use for uv projects and Python packaging — uv workflow, lockfiles, PEP 723 scripts, pyproject layout, building wheels.
---
# uv projects and Python packaging

Part of `python-engineering` (baseline versions, pitfalls). Read `references/platform-wheels.md` when installing MLX or PyTorch, or when a wheel is missing on Apple silicon or CUDA Linux.

## uv workflow (verified with uv 0.12.19; 0.12.22 is current — Verified 2026-10-02 https://pypi.org/pypi/uv/json)
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

## PEP 723 scripts
Single-file tools with inline dependencies:
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
```
Tool tables go in the same file: `[tool.ruff]` and `[tool.basedpyright]` (`py-typing`), `[tool.pytest]` (`py-testing`).
- src layout prevents tests from importing the working tree by accident; the project is installed editable by `uv sync`.

## Verify
- [ ] `uv lock --check` passes; new dependencies justified (maintenance, license, wheel availability on macOS arm64 and Linux x86_64).
```sh
uv lock --check && uv sync --locked
uv build && uv run --isolated --with dist/*.whl myapp --help   # the built wheel installs and runs
```
