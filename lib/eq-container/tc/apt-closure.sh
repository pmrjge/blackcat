#!/bin/bash
# apt-closure.sh TOOL PACKAGE...   (runs in a builder stage of Dockerfile.toolchains; never at run time)
# Installs PACKAGE... from the pinned Debian snapshot (the stage's apt sources) and records, in /opt/eq-pkgs/TOOL.list, every
# package this install ADDED (the closure: dpkg's package list after minus before). tc/mkrootfs-tc.sh copies exactly those
# packages' files into the image for a TOOLS.toml tool with provenance distro-package (docs, man pages, info and locales left
# out). USER decision 2026-10-05: a cc linker in the Rust and Haskell images (tools cc and ghc-link-libs). UNVERIFIED until a
# build passes.
set -euo pipefail
tool=${1:?tool name}; shift
[ $# -gt 0 ] || { echo "apt-closure: no package given for $tool" >&2; exit 2; }
mkdir -p /opt/eq-pkgs
before=$(mktemp); after=$(mktemp)
dpkg-query -W -f='${Package}\n' | LC_ALL=C sort -u > "$before"
apt-get update
apt-get install -y --no-install-recommends "$@"
rm -rf /var/lib/apt/lists/*
dpkg-query -W -f='${Package}\n' | LC_ALL=C sort -u > "$after"
# the named packages always belong to the tool, even when an earlier closure already installed them
{ LC_ALL=C comm -13 "$before" "$after"; printf '%s\n' "$@"; } | LC_ALL=C sort -u > "/opt/eq-pkgs/$tool.list"
[ -s "/opt/eq-pkgs/$tool.list" ] || { echo "apt-closure: empty package closure for $tool" >&2; exit 1; }
echo "apt-closure $tool: $(wc -l < "/opt/eq-pkgs/$tool.list") packages: $(tr '\n' ' ' < "/opt/eq-pkgs/$tool.list")"
rm -f "$before" "$after"
