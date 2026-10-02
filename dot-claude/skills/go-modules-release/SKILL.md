---
name: go-modules-release
description: Use for Go modules and releases — go.mod directives, toolchains, supply chain and govulncheck, cross builds.
---
# Go modules, toolchains and releases

Part of `go-engineering` (baseline, layout). Version claims: Verified 2026-10-02 https://go.dev/doc/go1.21, https://go.dev/doc/go1.23, https://go.dev/doc/go1.24, https://go.dev/doc/go1.25, https://go.dev/doc/go1.27, https://go.dev/doc/toolchain; goreleaser details: unverified.

## go.mod
- `go 1.26` = the minimum Go version and the language version of the module's files. `toolchain go1.27.1` (1.21) suggests a newer toolchain and takes precedence over the `go` line when choosing one; without it the implicit toolchain is the `go` version.
- Toolchain switching: the default `GOTOOLCHAIN=auto` runs or downloads a newer toolchain when the `go`/`toolchain` line requires it (and prints `switching to go …`); `GOTOOLCHAIN=local` always uses the bundled one; `<name>+path` disables the download fallback.
- Tools as dependencies: `go get -tool golang.org/x/tools/cmd/stringer` adds a `tool` directive (1.24); run with `go tool stringer`. Replaces the `tools.go` blank-import pattern.
- `ignore` directive (1.25) lists directories the go command skips (`node_modules`, generated trees).
- `go mod tidy -diff` (1.23) prints the needed changes without writing — use it in CI. With `go 1.27`+, `go mod tidy` merges duplicate require blocks into at most two (direct, indirect).
- `godebug` entries in go.mod and `//go:debug` lines: since 1.27 a removed setting is accepted only at its final default value.
- Private modules: `GOPRIVATE=example.com/*` skips the proxy and checksum database for them.
- Major versions ≥ 2 change the module path (`module example.com/lib/v2`) and every import; `retract` withdraws a broken release.
- Multi-module development: `go work init ./a ./b`, `go work use ./c`.
- Docs for a specific version: `go doc example.com/pkg@v1.2.3` (1.27).

## Supply chain
- `govulncheck ./...` (golang.org/x/vuln v1.8.0, Verified 2026-10-02 https://proxy.golang.org/golang.org/x/vuln/@latest) reports vulnerabilities whose affected symbols the code can reach; also run it on built binaries (`govulncheck -mode=binary ./bin/x`).
- `go mod verify` checks the module cache against `go.sum`; `go version -m <binary>` prints the embedded module versions and build settings (VCS revision, flags).
- Before adding a module: maintenance, license, transitive count (`go mod graph | wc -l` before/after), and whether the standard library covers it (`slices`, `maps`, `log/slog`, `net/http` routing, `encoding/json/v2`).

## Builds and release
- Reproducible release binary: `go build -trimpath -ldflags="-s -w -X main.version=$(git describe --tags)" -o bin/ ./cmd/...`; `debug.ReadBuildInfo()` exposes `vcs.revision`/`vcs.time` without ldflags.
- Pure-Go cross-compiling is `GOOS`/`GOARCH`: `CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build ...` gives a static Linux binary; with cgo a cross C toolchain is needed. macOS universal binary: build `darwin/arm64` and `darwin/amd64`, then `lipo -create` (signing: `macos-app-distribution`). Go 1.27 binaries need macOS 13+.
- Profile-guided optimization: a CPU profile saved as `default.pgo` in the main package's directory is used automatically (1.21).
- `go install example.com/cmd/x@v1.2.3` installs a tool outside any module.
- Release automation: goreleaser builds archives, checksums and SBOMs from a tag; publishing a release is the user's step.

## Verify
```sh
go mod tidy -diff && go mod verify
govulncheck ./...
CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build -trimpath -o bin/ ./cmd/...
go version -m bin/<name>               # embedded versions and VCS revision are right
```
