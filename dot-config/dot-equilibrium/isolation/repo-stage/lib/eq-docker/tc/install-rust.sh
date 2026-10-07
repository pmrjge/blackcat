#!/bin/bash
# install-rust.sh: recipe for the manifest entry `rust` (provenance prebuilt-upstream). The standalone Rust tarball is an installer
# tree (install.sh + one directory per component), not a ready /opt/rust/bin layout, so tc/fetch-tool.sh runs this recipe with SRC
# (the extracted, sha256-verified tarball) and DEST (the install prefix) in the discarded builder stage. No binary is compiled here.
# UNVERIFIED: never run; the component names follow the rust-installer convention and may need adjusting to the pinned version.
set -euo pipefail
: "${SRC:?}" "${DEST:?}"
cd "$SRC"
sh ./install.sh --prefix="$DEST" --components=rustc,cargo,rust-std-aarch64-unknown-linux-gnu --disable-ldconfig
