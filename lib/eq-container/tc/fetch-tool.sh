#!/bin/bash
# fetch-tool.sh NAME   (runs in a DISCARDED builder stage of Dockerfile.toolchains, never at run time)
# Installs the tool NAME of /opt/eq-tools/TOOLS.toml into its `dest`: download over https, sha256 verified BEFORE anything is
# extracted, extract, prune (docs, man pages, headers, tests as listed in the entry), assert the listed files exist, run the smoke
# argv. A PLACEHOLDER in version, url, sha256, archive or provenance stops the build (exit 13) and names the value; nothing is guessed.
#   prebuilt-upstream   the archive at url (sha256 pinned in the manifest; upstream checksum/signature noted in checksum_source);
#                       when the entry has a `recipe` (rust, ghc: the upstream tarball is an installer tree) the same recipe rules as
#                       built-from-source apply, but the provenance stays prebuilt-upstream because nothing is compiled
#   built-from-source   the SOURCE tarball at url (sha256 pinned), then the in-repo recipe tc/build-<name>.sh (its own sha256
#                       pinned in the manifest as recipe_sha256) installs into dest; only dest is copied to the final image
#   in-repo             a file of this repository (hash checked by verify-tools.sh and again here)
#   (distro-package is refused everywhere: USER decision 2026-10-06, no distribution package in any image)
# Env: EQ_TOOLS_DIR (default /opt/eq-tools: TOOLS.toml, tools.sh and the tc/ scripts).
set -euo pipefail
name=${1:?tool name}
T=${EQ_TOOLS_DIR:-/opt/eq-tools}
# shellcheck disable=SC1091
. "$T/tools.sh"
tm_load "$T/TOOLS.toml"
tm_has tool "$name" || { echo "fetch-tool: $name is not in TOOLS.toml" >&2; exit 2; }
g() { tm_get tool "$name" "$1"; }
for k in version url sha256 archive provenance; do
  [ "$(g "$k")" != PLACEHOLDER ] || { echo "fetch-tool: $name: $k is PLACEHOLDER in TOOLS.toml (pending TOOLCHAINS.md): refusing to guess it" >&2; exit 13; }
done
prov=$(g provenance); dest=$(g dest); ver=$(g version); tag=$(g tag); sha=$(g sha256); arch=$(g archive); strip=$(g strip)
url=$(g url); url=${url//\{version\}/$ver}; url=${url//\{tag\}/$tag}
case "$dest" in /opt/*|/usr/*) ;; *) echo "fetch-tool: $name: dest $dest must be under /opt or /usr" >&2; exit 2;; esac
dl=$(mktemp -d "${TMPDIR:-/tmp}/eqfetch.XXXXXX"); trap 'rm -rf "$dl"' EXIT
case "$prov" in
  prebuilt-upstream|built-from-source)
    case "$url" in https://*) ;; *) echo "fetch-tool: $name: url must be https" >&2; exit 2;; esac
    curl --proto '=https' --proto-redir '=https' --tlsv1.2 -fsSL --retry 5 -o "$dl/archive" "$url"
    echo "$sha  $dl/archive" | sha256sum -c - >&2 || { echo "fetch-tool: $name: sha256 of $url differs from TOOLS.toml" >&2; exit 1; }
    target=$dl/x
    recipe=$(g recipe)
    if [ "$prov" = built-from-source ] && [ -z "$recipe" ]; then echo "fetch-tool: $name: built-from-source needs a recipe" >&2; exit 2; fi
    if [ -n "$recipe" ]; then
      rsha=$(g recipe_sha256)
      case "$recipe" in tc/*.sh) ;; *) echo "fetch-tool: $name: recipe must be tc/<file>.sh" >&2; exit 2;; esac
      echo "$rsha  $T/$recipe" | sha256sum -c - >&2 || { echo "fetch-tool: $name: recipe $recipe differs from recipe_sha256" >&2; exit 1; }
      target=$dl/src
    fi
    mkdir -p "$target"
    case "$arch" in
      tar.gz) tar -xzf "$dl/archive" -C "$target" --strip-components="${strip:-0}";;
      tar.xz) tar -xJf "$dl/archive" -C "$target" --strip-components="${strip:-0}";;
      tar.bz2) tar -xjf "$dl/archive" -C "$target" --strip-components="${strip:-0}";;
      tar.zst) tar --zstd -xf "$dl/archive" -C "$target" --strip-components="${strip:-0}";;
      zip) unzip -q "$dl/archive" -d "$dl/zip"
           if [ "${strip:-0}" = 1 ]; then mv "$dl/zip"/*/* "$target"/; else mv "$dl/zip"/* "$target"/; fi;;
      binary) first=$(g files); first=${first%% *}; install -D -m 0755 "$dl/archive" "$target/$(basename "$first")";;
      *) echo "fetch-tool: $name: unknown archive kind $arch" >&2; exit 2;;
    esac
    mkdir -p "$(dirname "$dest")"
    if [ -n "$recipe" ]; then
      SRC=$target DEST=$dest bash "$T/$recipe"
    else
      rm -rf "$dest"; mv "$target" "$dest"
    fi;;
  in-repo)
    f=$(g url); f=${f#file:}
    echo "$sha  $T/$f" | sha256sum -c - >&2
    first=$(g files); first=${first%% *}
    install -D -m 0755 "$T/$f" "$first";;
  *) echo "fetch-tool: $name: provenance $prov is not fetched here" >&2; exit 2;;
esac
for p in $(g prune); do
  case "$p" in /*|*..*) echo "fetch-tool: $name: bad prune path $p" >&2; exit 2;; esac
  rm -rf "${dest:?}/$p"
done
for f in $(g files); do [ -e "$f" ] || { echo "fetch-tool: $name: $f missing after install" >&2; exit 1; }; done
smoke=$(g smoke)
if [ -n "$smoke" ]; then
  bins=""; for b in $(g bins); do bins="$bins:$dest/$b"; done
  # no globbing: a smoke argv may contain a java classpath wildcard such as /opt/scala3/lib/*
  set -f
  # shellcheck disable=SC2086
  PATH="${bins#:}:$PATH" $smoke >/dev/null || { echo "fetch-tool: $name: smoke command failed: $smoke" >&2; exit 1; }
fi
echo "fetch-tool: $name $ver installed in $dest ($prov)"
