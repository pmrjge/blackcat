---
name: go-engineering
description: Use for any Go work — modules, errors, context, generics, slog, linters, tests.
---
# Go engineering

## Scope and baseline
- Go services, CLIs and libraries: layout, errors, context, generics, logging, lint, review. Not here: container images (`container-images`), CI (`ci-cd-pipelines`), profiling method (`cpu-performance`), security review (`secure-coding`).
- Baseline: Go 1.27 (1.27.0 released 2026-08-19, 1.27.1 on 2026-09-01). Each major release is supported until two newer majors exist, so 1.26 and 1.27 get fixes. Go 1.27 needs macOS 13 or later. Verified 2026-10-02 https://go.dev/doc/devel/release, https://go.dev/doc/go1.27.
- Feature versions named in the Go skills: Verified 2026-10-02 against the release notes https://go.dev/doc/go1.21 through https://go.dev/doc/go1.27, unless marked unverified.
- The `go` line in go.mod sets the language version per module (per-file with build constraints): features and vet checks follow it. Check APIs on pkg.go.dev or with `mcp__libdocs` before writing version-specific code.

## Modules (load the one the task touches)
| Module | Load for |
|---|---|
| `go-concurrency` | goroutine lifecycles, cancellation, errgroup, channels, sync, timers, leaks |
| `go-testing` | table tests, subtests, fuzzing, `b.Loop` benchmarks, synctest, golden files, coverage |
| `go-modules-release` | go.mod (`go`, `toolchain`, `tool`, `ignore`), workspaces, major versions, govulncheck, builds, cross-compiling |

## Layout
- `go.mod` at the repo root; `cmd/<name>/main.go` per binary; `internal/` for packages other modules must not import; one package per responsibility, named by what it provides (`store`, not `util`). Small modules stay flat — no `pkg/` by reflex.
- `main` builds dependencies and calls `run(ctx, args, stdout, stderr) error`, then maps the error to an exit code: the program is testable without a process.

## Language baseline
- Loop variables are per iteration in modules at `go 1.22`+ (no `v := v` copies); `for i := range n` ranges over integers (1.22).
- Generics when a type parameter links inputs and outputs; `cmp.Ordered`, the `slices`, `maps`, `cmp` packages and the `min`/`max`/`clear` built-ins (1.21). Go 1.27 adds generic methods (not on interfaces, and generic methods can't implement interface methods) and struct-literal keys that are any field selector. `new(expr)` allocates with an initial value (1.26).
- Iterators: range-over-func (`func(yield func(K, V) bool)`) with `iter.Seq`/`iter.Seq2` (1.23); `slices.All`, `slices.Collect`, `slices.Sorted`, `maps.Keys`. An iterator stops as soon as `yield` returns false.
- Errors: wrap with `fmt.Errorf("reading %s: %w", path, err)`; match with `errors.Is`, `errors.As` or the generic `errors.AsType` (1.26); sentinel errors (`var ErrNotFound = errors.New("not found")`) or typed errors where callers branch; `errors.Join` for several. Handle an error once (log or return, not both); `panic` only for programmer bugs.
- Context: first parameter `ctx context.Context`, never stored in a struct; `context.WithoutCancel` and `context.AfterFunc` (1.21) for work that must outlive or follow a cancelled request.
- JSON: in 1.27 `encoding/json` runs on the v2 implementation (same behaviour, error text may differ; `GOEXPERIMENT=nojsonv2` opts out); `encoding/json/v2` rejects invalid UTF-8 and duplicate names; `omitzero` tag option (1.24).
- Logging: `log/slog` (1.21) — `slog.New(slog.NewJSONHandler(os.Stderr, nil))`, key-value attributes, `logger.With(...)` per request; libraries take a `*slog.Logger` instead of logging globally. Never log secrets.
- Paths from untrusted input: `os.Root` (1.24) confines file operations to one directory.
- HTTP: `ServeMux` patterns take methods and wildcards (1.22): `mux.HandleFunc("GET /items/{id}", h)`, `r.PathValue("id")`; set server timeouts (at least `ReadHeaderTimeout`).

## Lint and format
- `gofmt -l .` must print nothing (`goimports`/`gofumpt` if the repo uses them); `go vet ./...` always — `go test` runs a vet subset, including `stdversion` from 1.27.
- golangci-lint v2 (2.14.0, Verified 2026-10-02 https://proxy.golang.org/github.com/golangci/golangci-lint/v2/@latest): `.golangci.yml` starts with `version: "2"`, `linters.default: standard`, formatters under `formatters.enable` (https://golangci-lint.run/docs/configuration/file/). Services add `gosec`, `errorlint`, `bodyclose`, `contextcheck`.
- `go fix ./...` runs the modernizers (rewritten in 1.26, more in 1.27); review its diff like any change.

## Review checklist
- [ ] gofmt, `go vet` and golangci-lint clean; `go mod tidy -diff` empty.
- [ ] Every error checked, wrapped with context, handled once; exported API minimal and documented, the rest in `internal/`.
- [ ] Context passed through every blocking call; no goroutine without an owner (`go-concurrency`).
- [ ] Each loaded module's Verify items hold.

## Verify
```sh
test -z "$(gofmt -l .)" && go vet ./...
golangci-lint run
go test ./...
```
Plus the Verify block of every module the change touched (race and leaks: `go-concurrency`; fuzz, bench, coverage: `go-testing`; vulnerabilities and builds: `go-modules-release`).

## Deliverables / Report
- Files changed; commands run with decisive output (tests passed, lint count, race result).
- `go` and `toolchain` lines, new dependencies (version, license, reason), govulncheck result.
- For performance work: benchstat before/after with `-count` ≥ 10.
- Residual risks: code paths without race coverage, untested GOOS/GOARCH targets, cgo dependencies.
