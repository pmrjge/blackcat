---
name: py-async
description: Use for async Python — asyncio TaskGroup, cancellation and timeouts, anyio, free-threaded CPython.
---
# Async Python

Part of `python-engineering` (baseline versions, pitfalls). Async tests: `py-testing`.

## asyncio
- `asyncio.run(main())`; structure with `asyncio.TaskGroup` (first failure cancels siblings; errors surface as `ExceptionGroup` → handle with `except*`), bound waits with `asyncio.timeout(s)`, limit concurrency with `asyncio.Semaphore`, pipelines with `asyncio.Queue` (`shutdown()` in 3.13).
- Never swallow `CancelledError` — clean up and re-raise. Keep a reference to every `create_task` result (the loop holds tasks weakly). Blocking calls go through `asyncio.to_thread`.
- 3.14 introspection of a live process: `uv run python -m asyncio ps PID`, `uv run python -m asyncio pstree PID`.

## anyio and free-threading
- anyio for backend-agnostic libraries: `create_task_group()`, cancel scopes (`move_on_after`, `fail_after`), `anyio.to_thread.run_sync`.
- Free-threaded 3.14t is officially supported (PEP 779) but every C extension must declare support — check wheels before depending on it.

## Verify
- [ ] Async code cancels cleanly and doesn't block the loop; every task is owned by a TaskGroup or kept referenced; ruff `ASYNC` rules clean.
- [ ] A test exercises the failure/cancellation path (one task raises, siblings are cancelled, resources released).
