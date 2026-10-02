---
name: go-concurrency
description: Use for concurrent Go — goroutine lifecycles, context, errgroup, channels, sync, timers, leaks.
---
# Go concurrency

Part of `go-engineering` (baseline, errors, context rules). Version claims: Verified 2026-10-02 https://go.dev/doc/go1.21, https://go.dev/doc/go1.23, https://go.dev/doc/go1.25, https://go.dev/doc/go1.26, https://go.dev/doc/go1.27.

## Goroutine lifecycle
- Every goroutine has an owner that knows how it stops (a context or done channel) and waits for it (`sync.WaitGroup`, errgroup). Libraries don't leave goroutines running after a call returns.
- `wg.Go(func() { ... })` (1.25) replaces `wg.Add(1)` + `go` + `defer wg.Done()`; vet's `waitgroup` analyzer (1.25) reports a misplaced `wg.Add`.
- errgroup (`golang.org/x/sync/errgroup`): the first error cancels the derived context and `Wait` returns it; `SetLimit(n)` bounds concurrency.
```go
g, ctx := errgroup.WithContext(ctx)
g.SetLimit(8)
for _, u := range urls {
    g.Go(func() error { return fetch(ctx, u) }) // per-iteration u (go 1.22+)
}
if err := g.Wait(); err != nil { return fmt.Errorf("fetching: %w", err) }
```
- Bounded workers (errgroup `SetLimit` or a semaphore `make(chan struct{}, n)`), never one goroutine per item of an unbounded input.

## Context and cancellation
- Every blocking `select` has a `case <-ctx.Done(): return ctx.Err()`; I/O takes the context (`http.NewRequestWithContext`, `db.QueryContext`).
- `ctx, cancel := context.WithTimeout(ctx, d)` is always followed by `defer cancel()` (vet `lostcancel`). `context.WithCancelCause` + `context.Cause(ctx)` record why.

## Channels
- The sender closes, once; receivers use `for v := range ch` or `v, ok := <-ch`. Never close from the receiving side.
- Unbuffered for hand-off; a buffer only with a stated bound and reason. A nil channel blocks forever — set one to nil to disable a `select` case.
- A send that can block needs a `ctx.Done()` alternative, or the sender leaks when the receiver quits.
- Timers (1.23): unreferenced `Timer`s and `Ticker`s are collectable without `Stop`, and their channels are unbuffered; 1.27 removed the `asynctimerchan` setting, so time channels are always synchronous.

## Shared state
- `sync.Mutex`/`RWMutex` declared next to the fields it guards; never copied (vet `copylocks`); short critical sections, no I/O under the lock.
- Typed atomics (`atomic.Int64`, `atomic.Bool`, `atomic.Pointer[T]`); `sync.OnceFunc`/`OnceValue`/`OnceValues` (1.21) for lazy initialization; `sync.Map` only for caches whose keys are written once and read many times.
- Complex state machines: confine the state to one goroutine and send it messages.

## Runtime
- `GOMAXPROCS` follows the cgroup CPU limit on Linux and is updated when it changes (1.25) — `automaxprocs` is no longer needed.
- The Green Tea garbage collector is the default from 1.26.
- Goroutine leak profile: experiment in 1.26, generally available in 1.27 (`goroutineleak` in `runtime/pprof`, `/debug/pprof/goroutineleak`). Tracebacks of 1.27 modules include pprof goroutine labels.

## Verify
- [ ] `go test -race -count=1 ./...` passes on the packages touched.
- [ ] Every goroutine's exit path is visible; no leaks in tests (`go.uber.org/goleak` `goleak.VerifyTestMain(m)`, or the `goroutineleak` profile).
- [ ] Time-dependent concurrency is tested deterministically with `testing/synctest` (`go-testing`).
