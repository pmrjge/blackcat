# Rust CLIs, serialization and logging

## Logging and tracing
- Libraries emit `tracing` events/spans and never install a subscriber. Binaries: `tracing_subscriber::fmt().with_env_filter(EnvFilter::from_default_env()).init()` (feature `env-filter`), `RUST_LOG=info,my_crate=debug`; `.json()` needs feature `json`; file rotation via `tracing-appender`.
- `#[tracing::instrument(skip(large_arg), fields(user = %id), err)]` on I/O boundaries; structured fields (`%` Display, `?` Debug). Never log secrets or full request bodies.

## CLI and serialization
- clap 4 derive: `#[derive(Parser)] #[command(version, about)]`, doc comments become help, `#[arg(short, long, env = "APP_X")]` (feature `env`), `#[derive(Subcommand)]`, `#[derive(ValueEnum)]`; completions via `clap_complete`. Data to stdout, logs to stderr; return `std::process::ExitCode`; decide colors with `std::io::IsTerminal`. Rust ignores SIGPIPE, so `println!` panics when piped into `head` — write through a locked `stdout` and treat `ErrorKind::BrokenPipe` as success.
- serde: `#[serde(rename_all = "camelCase")]`, `deny_unknown_fields` for config, `default`, `skip_serializing_if = "Option::is_none"`, `#[serde(tag = "type")]` for tagged enums (`untagged` gives poor errors). Version persisted formats explicitly.
- Formats: `serde_json`, `toml`, `csv`, `postcard` (compact, stable wire format), `rkyv` (zero-copy). Avoid: `bincode` 3.0 (a deliberate `compile_error!` tombstone — the project stopped), `serde_yaml` (deprecated; if YAML is unavoidable, check the currently maintained option — `serde-saphyr` is the active one at the time of writing). Verified 2026-10-02 https://crates.io/api/v1/crates/bincode (3.0.0 is the latest), https://crates.io/api/v1/crates/serde_yaml (0.9.34+deprecated), https://crates.io/api/v1/crates/serde-saphyr (1.3.0, 2026-09-16), https://crates.io/api/v1/crates/clap (4.6.7).
