#!/bin/bash
# build-postgresql.sh: recipe for the manifest entry `postgresql` IF its provenance is built-from-source (recipe and recipe_sha256
# keys of the entry; used only when TOOLCHAINS.md finds no official Linux/arm64 binary). Runs in the discarded builder stage
# `tools-build` of Dockerfile.toolchains with SRC (the extracted, sha256-verified source tree) and DEST (the install prefix).
# Server core only: no readline, zlib, ICU, NLS, docs, contrib. UNVERIFIED: never run; flags may need adjusting to the pinned version.
set -euo pipefail
: "${SRC:?}" "${DEST:?}"
cd "$SRC"
./configure --prefix="$DEST" --without-readline --without-zlib --without-icu --disable-nls --without-openssl
make -j"$(nproc)"
make install
rm -rf "$DEST/include" "$DEST/share/doc" "$DEST/share/man" "$DEST/lib/pkgconfig" "$DEST/lib/postgresql/pgxs"
find "$DEST" -name '*.a' -delete
