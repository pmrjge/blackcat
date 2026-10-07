---
name: kotlin-coroutines
description: Use for Kotlin coroutines and Flow — scopes, dispatchers, cancellation, StateFlow, runTest.
---
# Kotlin coroutines and Flow

Baseline: `android-engineering` (Android) or `jvm-engineering` (server/JVM).
- kotlinx.coroutines 1.11.0 — Verified 2026-10-02 https://github.com/Kotlin/kotlinx.coroutines/releases/latest

## Structured concurrency
- Every coroutine has an owner scope: `viewModelScope`, `lifecycleScope`, a scope injected into a repository/service, or `coroutineScope {}` inside a suspend function. `GlobalScope` never; a hand-made `CoroutineScope(Job())` only with a documented `cancel()` owner.
- Suspend functions are main-safe: they switch with `withContext(Dispatchers.IO / Default)` internally; callers don't wrap them.
- Inject dispatchers (constructor parameter) so tests can replace them.
- `coroutineScope` fails all children when one fails; `supervisorScope`/`SupervisorJob` when siblings are independent.
- `launch` for fire-and-forget within a scope, `async`/`await` for parallel results (always awaited inside the same scope).

## Cancellation
- Cancellation is cooperative: long CPU loops call `ensureActive()` or `yield()`; blocking I/O needs `runInterruptible` or a cancellable API.
- Never swallow `CancellationException`: `catch (e: Exception)` around suspend calls must rethrow it (or catch narrower types). `runCatching` around suspend code catches it too — avoid it there.
- Cleanup in `finally`; suspend calls inside `finally` need `withContext(NonCancellable)`.
- Timeouts: `withTimeout` throws `TimeoutCancellationException`; `withTimeoutOrNull` returns null.

## Exceptions
- Uncaught exceptions in `launch` propagate to the parent and its `CoroutineExceptionHandler` (only effective on root coroutines); in `async` they surface at `await()`.
- Map errors to UI state at the ViewModel boundary; don't let them crash the scope silently.

## Flow
- Cold `Flow` for streams computed on collection; `StateFlow` for observable state (always has a value, conflated, distinct); `SharedFlow` for events with explicit replay/buffer policy. One-off UI events are better modelled as state the UI consumes and acknowledges.
- Operators: `map`, `filter`, `combine`, `flatMapLatest` (cancel previous), `debounce`, `distinctUntilChanged`, `catch` (upstream only), `onEach`, `flowOn` (changes the upstream dispatcher only).
- Expose hot state from ViewModels with `stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), initial)`.
- Collect on Android with `repeatOnLifecycle(Lifecycle.State.STARTED)` or Compose `collectAsStateWithLifecycle()` — never a bare `lifecycleScope.launch { flow.collect }` that keeps collecting in the background.
- `callbackFlow` for callback APIs with `awaitClose { unregister() }`; `channelFlow` for concurrent emission.
- Backpressure: `buffer`, `conflate`, `collectLatest` — choose deliberately.

## Testing
```kotlin
@Test fun loads() = runTest {                       // virtual time; delays skip
    val dispatcher = StandardTestDispatcher(testScheduler)
    val vm = MyViewModel(repo = FakeRepo(), io = dispatcher)
    vm.load()
    advanceUntilIdle()
    assertEquals(UiState.Loaded(items), vm.state.value)
}
```
- `Dispatchers.setMain(StandardTestDispatcher())` in a test rule for code that uses `Dispatchers.Main`; reset after.
- Flows: Turbine (`flow.test { assertEquals(x, awaitItem()) }`) or `toList` with `backgroundScope` for hot flows.
- `UnconfinedTestDispatcher` only when eager execution is the point of the test.

## Pitfalls
Blocking calls (`Thread.sleep`, JDBC, file I/O) on `Dispatchers.Main/Default`; `runBlocking` in production Android code; leaking scopes in singletons; `catch` placed before the operator that throws; `StateFlow` with mutable collections (no emission on in-place change); collecting the same cold flow twice and doing the work twice (`shareIn`).

## Verify
Tests use `runTest` with injected dispatchers and cover cancellation and error paths · no `GlobalScope`/`runBlocking` in app code (`rg`) · lifecycle-aware collection in UI · StrictMode or Android lint shows no main-thread I/O for the changed path.
