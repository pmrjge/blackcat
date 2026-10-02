---
name: rust-async
description: Use for async Rust on tokio — runtimes, blocking work, cancellation, select!, JoinSet, channels.
---
# Async Rust with tokio

Part of `rust-engineering` (baseline, layout, lints). Rayon next to tokio: `rust-engineering` `references/performance.md`.

## Runtime and blocking
- Runtime: `#[tokio::main]` (multi-thread) for servers; `#[tokio::main(flavor = "current_thread")]` for CLIs and simple tools; `#[tokio::test]` is current-thread by default. Enable only the features used (`rt-multi-thread`, `macros`, `sync`, `time`, `io-util`, `net`, `process`, `fs`, `signal`). Never create or `block_on` a runtime inside async code ("Cannot start a runtime from within a runtime").
- Blocking: no blocking I/O, `std::thread::sleep` or long CPU work between `.await`s (rule of thumb: ≤ 10–100 µs). Use `tokio::task::spawn_blocking` (can't be aborted — pass a flag/token into the closure) or rayon + a `oneshot` for CPU-parallel work.

## Cancellation and structured concurrency
- Cancellation: dropping a future cancels it at its current `.await`. `select!` drops the losing branches, so in loops use cancel-safe operations only: `mpsc`/`broadcast` `recv`, `watch::changed`, `AsyncReadExt::read`, `AsyncWriteExt::write`, `StreamExt::next`, `accept`. Not cancel-safe: `read_exact`, `read_to_end`, `read_to_string`, `write_all` (data loss); `Mutex::lock`, `RwLock::read`/`write`, `Semaphore::acquire`, `Notify::notified` (lose their queue position).
- Structured concurrency: `JoinSet` (aborts its tasks on drop), `tokio_util::sync::CancellationToken` (`child_token()` per subtask), `tokio_util::task::TaskTracker` to await shutdown. No fire-and-forget `tokio::spawn` without a handle; surface `JoinError` (panic/abort).
```rust
let cancel = CancellationToken::new();
let mut set = JoinSet::new();
for id in 0..n { set.spawn(job(id, cancel.child_token())); }
let deadline = tokio::time::sleep(Duration::from_secs(30)); // created once, outside the loop
tokio::pin!(deadline);
let ctrl_c = tokio::signal::ctrl_c();
tokio::pin!(ctrl_c);
loop {
    tokio::select! {
        // guards: re-polling a completed future panics ("resumed after completion")
        _ = &mut ctrl_c, if !cancel.is_cancelled() => cancel.cancel(),
        () = &mut deadline, if !cancel.is_cancelled() => cancel.cancel(),
        next = set.join_next() => match next {
            Some(Ok(Ok(id))) => tracing::info!(id, "done"),
            Some(Ok(Err(e))) => tracing::warn!(error = %e, "job failed"),
            Some(Err(join_err)) => return Err(join_err.into()),
            None => break,
        },
    }
}
```

## Channels, locks, traits
- Channels: `mpsc` bounded (backpressure; unbounded only when the producer rate is bounded), `oneshot` (request/reply), `broadcast` (fan-out; slow receivers get `Lagged`), `watch` (latest value), `Semaphore` (concurrency limit), `Notify`.
- Locks: a `std::sync::Mutex` guard must not live across `.await` (clippy `await_holding_lock`); use `tokio::sync::Mutex` only when holding across `.await` is unavoidable. Timeouts: `tokio::time::timeout`.
- `async fn` in traits is stable but not dyn-compatible; for `dyn` use the `async-trait` crate or return boxed futures. "future cannot be sent between threads safely" = a `!Send` value (`Rc`, `RefCell` borrow, std `MutexGuard`) lives across an `.await` — scope it in a block that ends before the await.
- Diagnose stalls with `tokio-console` (`console-subscriber`, build with `RUSTFLAGS="--cfg tokio_unstable"`).

## Verify
- [ ] No blocking between awaits, no std lock guards across awaits (clippy `await_holding_lock` clean), cancel-safe `select!`, every spawned task joined or tracked, shutdown path tested.
