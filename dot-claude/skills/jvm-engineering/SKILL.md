---
name: jvm-engineering
description: Use for JVM code — Java 21+, Scala 3, Gradle/Maven/sbt, JUnit, JMH, GC tuning, GraalVM.
---
# JVM engineering (Java 21+, Scala 3)

## Scope and baseline
- Covers Java (21 and newer only), Scala 3 and the JVM toolchain; Kotlin appears where it meets these. Profiling method in `cpu-performance`; IDEs in `ide-workflows`.
- JDK versions (endoflife.date, Sep 2026): **25 is the current LTS** (Sep 2025), 21 the previous LTS, 27 the current feature release (Sep 2026), 26 before it. New projects: 25 unless a platform pins 21. Re-check before choosing.
- Scala (endoflife.date): **3.9 is the new LTS** (Sep 2026); 3.3 LTS is still widespread; 3.8 the last Next release. sbt 2.0.9 (Sep 2026), Mill 1.1.x, scala-cli (it is the `scala` command since Scala 3.5).
- Build tools: Gradle 9.x (9.8 in Sep 2026), Maven 3.9.x (check Maven 4's status before adopting). Kotlin 2.4.

## JDK management
- SDKMAN (`sdk list java`, `sdk install java 25-tem`, `sdk env` with `.sdkmanrc`), or mise/asdf, or Homebrew (`brew install openjdk@21`, then link it per the caveats). Distributions: Temurin, Zulu, Corretto, Liberica, Oracle, GraalVM — all have Apple Silicon (aarch64) builds.
- macOS: `/usr/libexec/java_home -V` lists JDKs; `export JAVA_HOME=$(/usr/libexec/java_home -v 21)`.
- Prefer build-tool **toolchains** over whatever `JAVA_HOME` happens to be: Gradle `java { toolchain { languageVersion = JavaLanguageVersion.of(21) } }` (with the foojay resolver plugin to auto-provision); Maven `maven.compiler.release=21` plus the enforcer plugin's `requireJavaVersion`.

## Modern Java you should write (21 → 25)
- Records for data carriers; sealed interfaces + records for sum types; `switch` pattern matching with record deconstruction and exhaustiveness (no `default` on a sealed hierarchy, so new cases fail compilation).
- Virtual threads (21): `Executors.newVirtualThreadPerTaskExecutor()` for blocking I/O concurrency; don't pool them; avoid long `synchronized` blocks around blocking I/O on JDK 21–23 (pinning; fixed by JEP 491 in 24). CPU-bound work still wants a bounded platform pool.
- Sequenced collections (21: `getFirst`, `reversed`), unnamed variables `_` (22), the FFM API for native interop (22, replaces most JNI), stream gatherers (24), and in 25: scoped values, flexible constructor bodies, module import declarations, compact source files with instance `main`. Structured concurrency is still a preview API through 25 — needs `--enable-preview`; check your JDK before using it.
- Text blocks, `var` for obvious local types, `Optional` for return values only (never fields/parameters), immutable collections (`List.of`, `Map.copyOf`).
- Nullness: annotate with JSpecify (`@NullMarked`) and enforce with NullAway (Error Prone plugin).

## Gradle
- Wrapper always (`./gradlew`), Kotlin DSL (`build.gradle.kts`), version catalog `gradle/libs.versions.toml`, convention plugins in `build-logic/` for multi-module builds.
- Speed: `org.gradle.configuration-cache=true`, `org.gradle.caching=true`, `org.gradle.parallel=true` in `gradle.properties`; `./gradlew build --scan` or `--profile` to find slow tasks.
- Dependencies: `implementation` vs `api` (java-library plugin), platforms/BOMs (`implementation(platform(libs.spring.boot.bom))`), `./gradlew dependencies --configuration runtimeClasspath`, `dependencyInsight --dependency x`. Lock with `dependencyLocking { lockAllConfigurations() }` when reproducibility matters.
- Upgrade: `./gradlew wrapper --gradle-version <v>`; fix deprecations shown by `--warning-mode all` first.

## Maven
- `mvn -q -B verify` in CI; `./mvnw` wrapper; `-T 1C` parallel; `dependency:tree`, `versions:display-dependency-updates`, enforcer (`dependencyConvergence`, `requireMavenVersion`). Pin plugin versions — unpinned plugins drift.
- `<maven.compiler.release>21</maven.compiler.release>` (not source/target). Surefire for unit tests, Failsafe for `*IT` integration tests.

## Scala 3
- Quick scripts and small projects: `scala-cli` with `//> using scala 3.9`, `//> using dep org.typelevel::cats-effect:…` directives; `scala-cli test .`, `scala-cli package --assembly`.
- sbt 2 (`project/build.properties`: `sbt.version=2.0.9`) or Mill (`build.mill`) for larger builds — follow the repo; many ecosystems still run sbt 1.x. Coursier (`cs setup`) installs the tools.
- Idioms: `enum` and ADTs, `given`/`using`, extension methods, opaque types, union types, optional braces (pick one style repo-wide; scalafmt enforces it). `-Wunused:all`, `-Wvalue-discard`, `-Xfatal-warnings` in CI; `-release 21` to target a JDK.
- Effects and libraries: cats-effect 3 + fs2 + http4s, or ZIO 2 — never both in one codebase; tapir for endpoints; circe or jsoniter-scala for JSON; munit, ScalaCheck, weaver for tests. Apache Spark still builds on Scala 2.13 — check before mixing Spark with Scala 3.
- Tooling: Metals LSP, scalafmt (`.scalafmt.conf` with `runner.dialect = scala3`), scalafix for refactors and migrations (Scala 2 → 3 via `-source:3.0-migration`).

## Testing and quality
- JUnit Jupiter (`@ParameterizedTest`, `@Nested`), AssertJ, Mockito (mock at boundaries only), Testcontainers for real Postgres/Mongo/Kafka in tests, jqwik for properties, ArchUnit for architecture rules, WireMock for HTTP.
- Static analysis: Error Prone (+ NullAway), SpotBugs, PMD or Checkstyle as the repo uses; formatting via Spotless with google-java-format or palantir-java-format.
- Coverage: JaCoCo; mutation testing: PIT for critical code.

## Performance and runtime
- Microbenchmarks only with JMH (warmup, forks, `Blackhole`); never `System.nanoTime` loops.
- Profiling: JFR (`-XX:StartFlightRecording=duration=60s,filename=rec.jfr`, `jcmd <pid> JFR.start`), JDK Mission Control, async-profiler (flame graphs, alloc and lock modes). `jcmd <pid> Thread.print`, `GC.heap_info`, `VM.native_memory`.
- GC: G1 is the default; generational ZGC for low pause on big heaps (`-XX:+UseZGC`; generational is the only ZGC mode since 24); Parallel for batch throughput. Containers: size with `-XX:MaxRAMPercentage=75`, not fixed `-Xmx` guesses. Compact object headers (`-XX:+UseCompactObjectHeaders`, product in 25) cut heap use — measure.
- Startup: AppCDS/AOT cache (JDK 24+ `-XX:AOTCache`), CRaC where supported, GraalVM `native-image` (reflection config via the tracing agent; test the native binary, not just the JVM build).

## Pitfalls
- `equals`/`hashCode` on mutable fields; `BigDecimal.equals` compares scale (`compareTo` for value); floating money → `BigDecimal` or long cents.
- Checked exceptions swallowed in lambdas; `ExecutorService` not shut down (use try-with-resources on executors, 19+).
- `ThreadLocal` with virtual threads: millions of copies — use scoped values.
- Time: `Instant` for timestamps, `ZonedDateTime` only at the edges; never `java.util.Date`.
- Dependency conflicts: two versions of a library on the classpath — `dependencyInsight`/`dependency:tree` and a BOM.
- Scala: implicit conversions and given ambiguity; `==` on Java boxed types; Scala 2 cross-builds need `-Xsource:3`.

## Verify
Toolchain pinned (JDK and build tool wrapper) · builds with warnings as errors in CI · tests incl. Testcontainers where DB logic changed · nullness annotated · no new blocking in virtual-thread pinning spots · JMH/JFR evidence for any performance claim · versions reported.
