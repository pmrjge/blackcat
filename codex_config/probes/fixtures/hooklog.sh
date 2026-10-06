#!/bin/sh
# Probe hook: appends one "#meta" line and one "<event>\t<stdin JSON>" line to the probe log.
# Rendered by run.sh (@ROOT@, @CODEX_HOME@). Never prints to stdout, always exits 0.
ev=${1:-unknown}
log=@ROOT@/logs/hooks.jsonl
mkdir -p @ROOT@/logs @ROOT@/outside 2>/dev/null
wo=fail; ( : > @ROOT@/outside/hook-wrote-$ev ) 2>/dev/null && wo=ok
ra=fail; ( head -c 1 @CODEX_HOME@/auth.json >/dev/null ) 2>/dev/null && ra=ok
printf '#meta event=%s argc=%s arg2=%s write_outside=%s read_auth=%s\n' "$ev" "$#" "${2:-}" "$wo" "$ra" >> "$log"
{ printf '%s\t' "$ev"; tr '\n' ' '; printf '\n'; } >> "$log"
exit 0
