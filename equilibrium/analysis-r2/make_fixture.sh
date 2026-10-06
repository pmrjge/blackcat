#!/bin/sh
# Zero-spend fixture for analysis route 2: a dev-stage ledger written by the harness with stub_claude on PATH as
# `claude` (no docker, no API: isolation "off" flags built from the harness's own fake pool), plus synthetic
# grading_results (the stub arms all answer alike, so real oracle files would be flat), plus route 2's output.
#
#   sh analysis-r2/make_fixture.sh [dest]      (default dest: analysis-r2/fixture)
#
# Layout of dest: eq/runs/d/ledger.jsonl and grading_results/ (the "run dir" to pass as --ledger), raw/ (raw call
# outputs and the mediator.jsonl files, pass raw as --mediator-root), out/ (results.csv, quantities.txt, meta.json).
# The ledger content (timestamps, session ids) differs between runs: compare routes on one generated copy.
set -eu
EQ=$(cd "$(dirname "$0")/.." && pwd)
DEST=${1:-$EQ/analysis-r2/fixture}
mkdir -p "$DEST/bin"
ln -sf "$EQ/harness/stub_claude" "$DEST/bin/claude"
printf '#!/bin/sh\n:\n' > "$DEST/bin/pgrep"
chmod +x "$DEST/bin/pgrep"
export PATH="$DEST/bin:$PATH" EQ_STUB_STATE="$DEST/stub_state" EQ_STUB_LOG="$DEST/stub_log.jsonl"
H="$EQ/harness/eq_harness.py"
IT="$EQ/harness/tests/fixtures/items"
rm -rf "$DEST/eq" "$DEST/raw" "$DEST/stub_state" "$DEST/out" "$DEST/stub_log.jsonl"
uv run --script --quiet "$H" flags --items "$IT" --isolation off --out "$DEST/flags.json"
uv run --script --quiet "$H" schedule --items "$IT" --stage d --out "$DEST/schedule.tsv"
uv run --script --quiet "$H" run --stage d --eq-root "$DEST/eq" --raw-root "$DEST/raw" --items "$IT" \
  --flags "$DEST/flags.json" --schedule "$DEST/schedule.tsv" --no-check
uv run --script --quiet "$EQ/analysis-r2/synth_grading.py" "$DEST/eq/runs/d"
uv run --script --quiet "$EQ/harness/eq_route2.py" --ledger "$DEST/eq/runs/d" --out "$DEST/out" --mediator-root "$DEST/raw"
