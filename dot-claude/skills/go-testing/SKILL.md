---
name: go-testing
description: Load for Go tests — table tests, subtests, fuzzing, b.Loop benchmarks, synctest, coverage.
---
# Go testing

Part of `go-engineering` (baseline, lint). Version claims: Verified 2026-10-02 https://go.dev/doc/go1.22, https://go.dev/doc/go1.24, https://go.dev/doc/go1.25, https://go.dev/doc/go1.27, https://pkg.go.dev/testing/synctest; the coverage-directory workflow (`GOCOVERDIR`, `go tool covdata`): unverified.

## Tests
- Table-driven tests with `t.Run(tc.name, func(t *testing.T) { ... })`; `t.Parallel()` in independent subtests (per-iteration loop variables since 1.22 make capturing `tc` safe).
- Helpers call `t.Helper()`; cleanup with `t.Cleanup`; `t.TempDir()`; `t.Setenv` (not in parallel tests); `t.Context()` (1.24) is cancelled after the test and before its cleanups. `t.Output()` (1.25) is a writer into the test log; `t.Attr` (1.25) emits attributes.
- Compare with `github.com/google/go-cmp/cmp` (`if d := cmp.Diff(want, got); d != "" { t.Errorf("mismatch (-want +got):\n%s", d) }`); messages say `got X, want Y`.
- Fixtures in `testdata/` (the go tool ignores it); golden files rewritten by a test flag: `var update = flag.Bool("update", false, "rewrite golden files")`, run `go test ./pkg -update`, review the diff.
- Black-box tests in `package foo_test`; `func ExampleX()` with an `// Output:` comment is both a test and documentation.
- Vet's `tests` analyzer (1.24) flags malformed test, fuzz, benchmark and example declarations.

## Time and concurrency
- `testing/synctest` (GA in 1.25): `synctest.Test(t, func(t *testing.T) { ... })` runs the function in a bubble with a fake clock; `synctest.Wait()` blocks until every other goroutine in the bubble is durably blocked; `synctest.Sleep(d)` (1.27) combines `time.Sleep` and `Wait`.
- `httptest.NewTestServer` (1.27) serves over an in-memory fake network that works inside synctest bubbles; `testing/cryptotest.SetGlobalRandom` for deterministic crypto tests.

## Fuzzing
- `func FuzzParse(f *testing.F) { f.Add([]byte("seed")); f.Fuzz(func(t *testing.T, in []byte) { ... }) }`; assert invariants (round-trip, no panic), not exact outputs.
- `go test -run='^$' -fuzz='^FuzzParse$' -fuzztime=30s ./pkg` (one package per run); failing inputs land in `testdata/fuzz/FuzzParse/` — commit them, plain `go test` replays them.

## Benchmarks
- `for b.Loop() { ... }` (1.24) instead of `for range b.N`: setup before the loop is excluded and the body is not optimized away.
- `go test -run='^$' -bench=. -benchmem -count=10 ./pkg > new.txt`, compare with `benchstat old.txt new.txt` (`golang.org/x/perf/cmd/benchstat`); report the benchstat table, not single runs.

## Coverage and CI output
- `go test -coverprofile=cover.out ./... && go tool cover -func=cover.out`; with `-race` use `-covermode=atomic`.
- Binaries and integration tests: `go build -cover`, run with `GOCOVERDIR=<dir>`, then `go tool covdata percent -i=<dir>`.
- `go test -json` for CI tooling; 1.27 adds an optional `OutputType` field.

## Verify
- [ ] Tests cover new behaviour and bug fixes (each fix has a test that fails without it); fuzz targets for parsers and decoders; golden diffs reviewed.
```sh
go test -race -count=1 ./...
go test -run='^$' -fuzz='^FuzzX$' -fuzztime=30s ./pkg      # parsers, decoders
go test -coverprofile=cover.out ./... && go tool cover -func=cover.out
```
