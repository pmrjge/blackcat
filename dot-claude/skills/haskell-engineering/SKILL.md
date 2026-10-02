---
name: haskell-engineering
description: Load for Haskell — GHCup, cabal/stack, extensions, hspec/QuickCheck, laziness and space leaks, profiling, STM, common libraries.
---
# Haskell engineering

## Scope and baseline
- Covers Haskell applications and libraries. Category-theoretic reasoning lives in `category-theory`; machine-checked proofs in `lean-formalization`; property-based testing method in `test-property-based`; fuzzing in `test-fuzzing`.
- Versions (Sep 2026): GHC 9.14 (Dec 2025) is the first release GHC designates LTS; 9.12 and 9.10 are still common. cabal-install 3.18.1 (Jul 2026), stack 3.11.1 (Jun 2026). Stackage LTS snapshots pin a GHC. Re-check with `ghcup list` and https://www.stackage.org before choosing.
- Toolchain via **GHCup**: `ghcup tui`, or `ghcup install ghc recommended --set`, `ghcup install cabal recommended`, `ghcup install hls recommended`, `ghcup install stack`. HLS must be built for the exact GHC the project uses — `ghcup list -t hls` shows which.

## Project workflow (cabal first)
| Task | Command |
|---|---|
| New | `cabal init --non-interactive --lib --exe --tests` (or write the `.cabal` by hand) |
| Build / run | `cabal build all`, `cabal run exe:myapp -- args`, `cabal repl` (`:r`, `:t`, `:i`, `:set -Wall`) |
| Test | `cabal test --test-show-details=direct` |
| Pin | `cabal freeze` (→ `cabal.project.freeze`) and `index-state: 2026-09-01T00:00:00Z` in `cabal.project` for reproducible solves |
| Update index | `cabal update` |
| Outdated | `cabal outdated` |
| Docs | `cabal haddock --haddock-all` |
- Multi-package repos: `cabal.project` with `packages: ./*/`. Stack projects (`stack.yaml` with `snapshot: lts-…`): `stack build --test --fast`. Don't switch a repo between cabal and stack unasked.
- Nix (haskell.nix, nixpkgs haskellPackages) only when the repo already uses it.
- Fast feedback: `ghcid --command "cabal repl"`, or HLS in the editor.

## Language settings
- `default-language: GHC2021` (or `GHC2024`, available since GHC 9.10) gives the modern extension set (ScopedTypeVariables, TypeApplications, DerivingStrategies, …).
- Commonly added: `OverloadedStrings`, `OverloadedRecordDot`, `DuplicateRecordFields`, `LambdaCase`, `DerivingVia`, `DataKinds` — enable per module or in `default-extensions`, following the repo.
- Warnings: `ghc-options: -Wall -Wcompat -Widentities -Wincomplete-uni-patterns -Wincomplete-record-updates -Wredundant-constraints -Wmissing-deriving-strategies`; `-Werror` only in CI. Partial functions (`head`, `tail`, `fromJust`, `!!`, `read`) warn under `-Wx-partial` (9.8+): use `NonEmpty`, pattern matching, `readMaybe`.
- Format with fourmolu or ormolu (match the repo), lint with hlint (`.hlint.yaml`), `cabal-fmt` for .cabal files, weeder for dead code.

## Testing
- hspec (with `hspec-discover`) or tasty (tasty-hunit, tasty-quickcheck, tasty-hedgehog). Golden tests: tasty-golden / hspec-golden.
- Properties: QuickCheck (`Arbitrary`, `shrink`) or hedgehog (integrated shrinking, generators as values). Test laws of your instances (quickcheck-classes, hedgehog-classes). doctest / cabal-docspec for examples in Haddock.

## Laziness, strictness, space
- Space leaks come from thunks piling up: `foldl` → `foldl'`; lazy accumulators in `State`/records → strict fields (`StrictData` or `!`), `modify'`, `Data.Map.Strict`, `IORef` with `atomicModifyIORef'`.
- Use `BangPatterns` on loop accumulators; `seq`/`deepseq` (`force`) at boundaries where you need values evaluated (before timing, before sending to another thread).
- Lazy I/O (`readFile`, `getContents`) holds handles and memory unpredictably: use strict `Data.Text.IO` / `Data.ByteString` reads, or streaming (conduit, streaming, streamly).
- Strings: `String` is a linked list of `Char` — use `Text` for text (text ≥ 2 is UTF-8) and `ByteString` for bytes; decode explicitly (`decodeUtf8'`).

## Profiling and performance
- Build: `-O2` for releases (cabal defaults to `-O1`); `cabal build --enable-profiling --profiling-detail=late` then run with `+RTS -p -s -hT -l -RTS`; visualize heap with eventlog2html, time with profiteur or speedscope (`ghc-prof-flamegraph`).
- `+RTS -s` shows GC share: > 20–30 % GC time → reduce allocation or raise `-A` (nursery), e.g. `+RTS -A64m`.
- Data structures: `vector` (unboxed/storable) for arrays, `containers` (Map/Set/IntMap/Seq), `unordered-containers` (HashMap), `primitive`, `massiv` for multidimensional numerics. Benchmarks: tasty-bench or criterion with `nf`/`whnf` chosen correctly.
- Check specialization and inlining (`-ddump-simpl -dsuppress-all` or `inspection-testing`) only when a profile points there.

## Concurrency and effects
- `-threaded` and `+RTS -N`; `async` (`concurrently`, `race`, `mapConcurrently`, `withAsync` — never bare `forkIO` for work you wait on); STM (`TVar`, `retry`) for shared state; `bracket`/`finally` for resources; `unliftio` or `safe-exceptions` for exception-safe IO. Async exceptions: don't catch `SomeException` without rethrowing async ones.
- Effects: plain `ReaderT Env IO` is the default; mtl classes are fine; effectful or bluefin when the repo uses them. Don't introduce a second effect system.
- Errors: `Either`/`ExceptT` for expected failures, exceptions for exceptional IO failures; no `error` in library code paths.

## Common libraries
aeson (JSON; derive with `Generic` or `deriving via`), optparse-applicative (CLIs), text, bytestring, containers, vector, time, http-client/req, servant/warp/scotty (web), postgresql-simple/hasql/persistent (Postgres), lens/optics (only when the repo already uses them), megaparsec (parsers), QuickCheck/hedgehog.

## Pitfalls
- `Int` overflows silently; use `Integer` or `Natural` where it matters. `fromIntegral` hides truncation — check ranges.
- Orphan instances; overlapping instances; `-XUndecidableInstances` without need.
- Records: field selectors are partial on multi-constructor types; `-Wpartial-fields` flags them.
- Show/Read are for debugging, not serialization.
- Upper bounds: libraries need PVP bounds on dependencies; applications rely on freeze files.

## Review checklist
Builds warning-free with the repo's flags · tests and properties pass · no new partial functions · strictness at accumulators and data boundaries · Text/ByteString at I/O · resource safety (bracket) · freeze/index-state updated when deps changed · GHC version reported.
