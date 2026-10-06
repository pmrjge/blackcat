#!/bin/bash
# install-ghc.sh: recipe for the manifest entry `ghc` (provenance prebuilt-upstream). The GHC binary distribution is installed with
# its own `./configure && make install` (upstream's documented procedure), which needs make and a C compiler: it runs in the discarded
# builder stage `tools-build` of Dockerfile.toolchains with SRC (the extracted, sha256-verified bindist) and DEST (the install prefix).
# UNVERIFIED: never run. GHC itself calls a C compiler and linker when it compiles a program: INSTALLER_SPEC.md section 12, conflict C6.
set -euo pipefail
: "${SRC:?}" "${DEST:?}"
cd "$SRC"
./configure --prefix="$DEST"
make install
