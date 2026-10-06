#!/usr/bin/env bash
# shellcheck disable=SC2034  # EQ_RUN_* are read by eq_run in lib.sh
# verify-tools.sh: check TOOLS.toml and the images built from it. Never builds, never writes outside $EQ_STATE_DIR. Bash 3.2 ok.
#   ./verify-tools.sh [--file TOOLS.toml] [--profiles core,db | --select min-both,tc-go] [MODE...]
#   --select     image names instead of profiles (build.sh checks exactly the images it is about to build)
#   --manifest   (default) static checks of the manifest, no container: structure and enumerations, unique names, class/profile
#                allowlists of every image, https-only urls, in-repo files hash to their sha256, PINS agree for lean uv python
#                busybox jq bash. Bases (USER decision 2026-10-06, DESIGN_DISTROLESS.md): an image's base is scratch or
#                distroless-cc; a scratch image's tools must be static; no tool may be a distribution package (apt: urls and
#                provenance distro-package are refused); built-from-source needs file_sha256 (the output pin). The distroless
#                base is re-checked offline: base/*.json hash to DISTROLESS_CC and DISTROLESS_CC_ARM64, and the index lists that
#                linux/arm64 manifest (consistency; authenticity is base-pins.sh's cosign check). A PLACEHOLDER in a selected
#                profile's tools (version url sha256 file_sha256 checksum_source linkage provenance archive: a pin is resolved
#                only with its source) is "pending" (exit 13), never an invented value.
#   --images     container (read-only): per image of the profiles: build record, digest, label eq.tools.sha256 equal to the hash of
#                the CURRENT manifest entries (a changed entry = stale image), /opt/eq/TOOLS.lock read from the image saved with
#                `container image save` (nothing is started) equal to the manifest (every listed tool, no undeclared one).
#   --deep       with --images: also re-hash every installed tool file from that saved image (host side), so a tampered in-image
#                sha256sum cannot lie. Run it before a run / a freeze; the per-run proof is the digest the harness pins.
#   --inspect    container (no container started): the saved image's config: unprivileged user, no EXPOSE/VOLUME/ENTRYPOINT/
#                HEALTHCHECK, no secret-like ENV name, PATH in /opt,/usr; its layers: a distroless-cc image's bottom layers are
#                exactly the pinned base manifest's (base/*.arm64.manifest.json), a scratch image has at most 3 layers
#                ([unverified] that `container image save` keeps the base's compressed blobs: checklist D5)
#   --deep       also re-hashes /opt/eq/BASE_EXECUTABLES.txt (the base's executables, recorded by the assemble stage)
#   --smoke      container: run each tool's smoke argv in its image under the hardened flags of lib.sh eq_run.
#   --allow-placeholder   report pending values but exit 0 for them (listing mode)
# Exit: 0 ok | 2 usage or invalid manifest | 10 container missing/down | 11 an image is missing, stale or does not match | 13 pending.
set -u
here=$(cd "$(dirname "$0")" && pwd -P)
# shellcheck disable=SC1091
. "$here/tools.sh"

FILE=""; PROFILES=core; SELECT=""; M_IMAGES=0; M_SMOKE=0; M_INSPECT=0; M_DEEP=0; ALLOWPH=0
while [ $# -gt 0 ]; do
  case "$1" in
    --file) FILE=${2:?--file needs a path}; shift;;
    --profiles) PROFILES=${2:?--profiles needs a list}; shift;;
    --select) SELECT=$(printf '%s' "${2:?--select needs image names}" | tr ',' ' '); shift;;
    --manifest) ;;                      # the manifest check always runs; the flag only states the intent
    --images) M_IMAGES=1;;
    --smoke) M_SMOKE=1;;
    --inspect) M_INSPECT=1;;
    --deep) M_DEEP=1;;
    --allow-placeholder) ALLOWPH=1;;
    -h|--help) awk 'NR == 1 { next } /^#/ { print; next } { exit }' "$0"; exit 0;;
    *) echo "verify-tools: unknown argument: $1" >&2; exit 2;;
  esac
  shift
done
[ "$M_DEEP" = 0 ] || [ "$M_IMAGES" = 1 ] || { echo "verify-tools: --deep needs --images" >&2; exit 2; }
PROFILES=$(printf '%s' "$PROFILES" | tr ',' ' ')
tm_load "${FILE:-$here/TOOLS.toml}" || exit 2
exp=$(tm_expand_profiles "$PROFILES") || exit 2
PROFILES=$(printf '%s' "$exp" | tr '\n' ' ')
FILE_DIR=$(cd "$(dirname "$TM_FILE")" && pwd -P)

PROBLEMS=0; PENDING=0
problem() { echo "PROBLEM $*"; PROBLEMS=$((PROBLEMS + 1)); }
pending() { echo "PENDING $*"; PENDING=$((PENDING + 1)); }
note() { echo "NOTE $*"; }
is_hex64() { tm_is_hex64 "$1"; }   # tools.sh: literal character lists, never a locale-dependent range
in_list() { case " $2 " in *" $1 "*) return 0;; esac; return 1; }   # word list membership

KNOWN_CLASSES="PF CP CR ES RS DS OE EXT"
KNOWN_LINKAGE="static dynamic"
KNOWN_PROV="prebuilt-upstream built-from-source in-repo"
KNOWN_BASE="scratch distroless-cc"
BASE_INDEX=base/distroless-cc-debian13-nonroot.index.json
BASE_MANIFEST=base/distroless-cc-debian13-nonroot.arm64.manifest.json
KNOWN_ROLE="runtime probe selftest server build-only"
KNOWN_KIND="check lang server"
KNOWN_ARCHIVE="tar.gz tar.xz tar.bz2 tar.zst zip binary"

# ---------------------------------------------------------------------------------------------------------------- manifest
check_manifest() {
  local t k v p c i s fs dup sel_images sel_tools pv names=""
  # unique names are guaranteed per table by the reader (duplicate key = error is per name, so check duplicates of name itself)
  for k in tool image profile; do
    dup=$(tm_names "$k" | sort | uniq -d | head -n 1)
    [ -z "$dup" ] || problem "duplicate $k name: $dup"
  done
  for t in $(tm_names tool); do
    for k in version url sha256 checksum_source linkage provenance role classes profiles licence; do
      [ -n "$(tm_get tool "$t" "$k")" ] || problem "tool $t: missing key $k"
    done
    v=$(tm_get tool "$t" provenance)
    if [ "$v" = distro-package ]; then problem "tool $t: provenance distro-package is refused (no distribution package in any image: USER decision 2026-10-06)"
    else [ "$v" = PLACEHOLDER ] || in_list "$v" "$KNOWN_PROV" || problem "tool $t: provenance '$v' is not one of: $KNOWN_PROV"; fi
    v=$(tm_get tool "$t" linkage)
    [ "$v" = PLACEHOLDER ] || in_list "$v" "$KNOWN_LINKAGE" || problem "tool $t: linkage '$v' is not static or dynamic"
    v=$(tm_get tool "$t" role)
    in_list "$v" "$KNOWN_ROLE" || problem "tool $t: role '$v' is not one of: $KNOWN_ROLE"
    for c in $(tm_get tool "$t" classes); do in_list "$c" "$KNOWN_CLASSES" || problem "tool $t: unknown class $c"; done
    for p in $(tm_get tool "$t" profiles); do tm_has profile "$p" || problem "tool $t: unknown profile $p"; done
    s=$(tm_get tool "$t" sha256)
    case "$s" in
      PLACEHOLDER) ;;
      n/a) [ "$(tm_get tool "$t" role)" = build-only ] || problem "tool $t: sha256 n/a is only for role build-only";;
      *) is_hex64 "$s" || problem "tool $t: sha256 is not 64 lowercase hex, PLACEHOLDER or n/a";;
    esac
    fs=$(tm_get tool "$t" file_sha256)
    case "$fs" in
      ""|PLACEHOLDER) ;;
      *) is_hex64 "$fs" || problem "tool $t: file_sha256 is not 64 lowercase hex or PLACEHOLDER";;
    esac
    if [ "$(tm_get tool "$t" provenance)" = built-from-source ] && [ -z "$fs" ]; then
      problem "tool $t: built-from-source needs file_sha256 (the built output is what is pinned: the builder's compiler floats)"
    fi
    v=$(tm_get tool "$t" url)
    case "$v" in
      PLACEHOLDER|https://*|file:*) ;;
      apt:*) problem "tool $t: an apt: url (a distribution package) is refused (USER decision 2026-10-06)";;
      *) problem "tool $t: url must be https://, file:<path> or PLACEHOLDER (got '$v')";;
    esac
    case "$v" in https://*@*) problem "tool $t: credentials in url";; esac
    case "$v" in
      https://*) case "$(tm_get tool "$t" provenance)" in prebuilt-upstream|built-from-source|PLACEHOLDER) ;; *) problem "tool $t: an https url needs provenance prebuilt-upstream or built-from-source";; esac;;
      file:*)
        [ "$(tm_get tool "$t" provenance)" = in-repo ] || problem "tool $t: a file: url needs provenance in-repo"
        if [ -f "$FILE_DIR/${v#file:}" ]; then
          if is_hex64 "$s" && [ "$(tm_sha256_stdin < "$FILE_DIR/${v#file:}")" != "$s" ]; then problem "tool $t: ${v#file:} does not hash to the sha256 in the manifest (edited without re-pinning)"; fi
        else problem "tool $t: in-repo file ${v#file:} not found"; fi;;
    esac
    case "$(tm_get tool "$t" provenance)" in built-from-source)
      [ -n "$(tm_get tool "$t" recipe)" ] || problem "tool $t: built-from-source needs a recipe (tc/build-<name>.sh)";;
    esac
    # any recipe (built-from-source, or an installer tree such as rust and ghc): a file of tc/ whose sha256 the entry pins
    v=$(tm_get tool "$t" recipe)
    if [ -n "$v" ]; then
      case "$v" in tc/*.sh) ;; *) problem "tool $t: recipe must be tc/<file>.sh (got '$v')";; esac
      is_hex64 "$(tm_get tool "$t" recipe_sha256)" || problem "tool $t: a recipe needs recipe_sha256 (64 lowercase hex)"
      if [ -f "$FILE_DIR/$v" ]; then
        if is_hex64 "$(tm_get tool "$t" recipe_sha256)" && [ "$(tm_sha256_stdin < "$FILE_DIR/$v")" != "$(tm_get tool "$t" recipe_sha256)" ]; then problem "tool $t: recipe $v does not hash to recipe_sha256 (edited without re-pinning)"; fi
      else problem "tool $t: recipe file $v not found"; fi
    fi
    if [ "$(tm_get tool "$t" role)" != build-only ]; then
      v=$(tm_get tool "$t" archive)
      [ -z "$v" ] || [ "$v" = PLACEHOLDER ] || in_list "$v" "$KNOWN_ARCHIVE" || problem "tool $t: archive '$v' unknown"
      [ -n "$(tm_get tool "$t" dest)" ] || problem "tool $t: missing dest"
      [ -n "$(tm_get tool "$t" files)" ] || problem "tool $t: missing files"
      case "$(tm_get tool "$t" dest)" in /*) ;; *) problem "tool $t: dest must be absolute";; esac
    fi
  done
  for i in $(tm_names image); do
    for k in dockerfile target kind base profile classes tools; do
      [ -n "$(tm_get image "$i" "$k")" ] || problem "image $i: missing key $k"
    done
    in_list "$(tm_get image "$i" kind)" "$KNOWN_KIND" || problem "image $i: kind must be one of: $KNOWN_KIND"
    in_list "$(tm_get image "$i" base)" "$KNOWN_BASE" || problem "image $i: base '$(tm_get image "$i" base)' is not one of: $KNOWN_BASE"
    tm_has profile "$(tm_get image "$i" profile)" || problem "image $i: unknown profile $(tm_get image "$i" profile)"
    for c in $(tm_get image "$i" classes); do in_list "$c" "$KNOWN_CLASSES" || problem "image $i: unknown class $c"; done
    for t in $(tm_get image "$i" tools); do
      if ! tm_has tool "$t"; then problem "image $i: lists unknown tool $t"; continue; fi
      [ "$(tm_get tool "$t" role)" != build-only ] || problem "image $i: lists build-only tool $t (builder stages only)"
      if [ "$(tm_get image "$i" base)" = scratch ] && [ "$(tm_get tool "$t" linkage)" != static ]; then
        problem "image $i: tool $t is not static (linkage '$(tm_get tool "$t" linkage)') but the image is FROM scratch (no loader, no libraries)"
      fi
      in_list "$(tm_get image "$i" profile)" "$(tm_get tool "$t" profiles)" || problem "image $i: tool $t is not allowed in profile $(tm_get image "$i" profile)"
      for c in $(tm_get image "$i" classes); do
        in_list "$c" "$(tm_get tool "$t" classes)" || problem "image $i: class $c may not have tool $t (tool classes: $(tm_get tool "$t" classes))"
      done
    done
  done
  for p in $(tm_names profile); do
    for i in $(tm_get profile "$p" images); do tm_has image "$i" || problem "profile $p: unknown image $i"; done
    if [ -n "$(tm_get profile "$p" deferred)" ] && [ -n "$(tm_get profile "$p" images)" ]; then problem "profile $p: deferred but lists images"; fi
    if [ -z "$(tm_get profile "$p" deferred)" ] && [ -z "$(tm_get profile "$p" images)" ]; then problem "profile $p: no images and no deferred reason"; fi
  done
  # PINS (when beside the manifest) must say the same as the manifest for the four tools both describe
  if [ -f "$FILE_DIR/PINS" ]; then
    pin() { sed -n "s/^$1=//p" "$FILE_DIR/PINS" | head -n 1; }
    ph() { case "$1" in ""|UNSET|*TODO*) echo PLACEHOLDER;; *) echo "$1";; esac; }   # PINS placeholder = manifest PLACEHOLDER
    pair() { # tool KEY-version KEY-sha [KEY-tag]
      local mv ms pvv pvs
      tm_has tool "$1" || return 0
      mv=$(tm_get tool "$1" version); ms=$(tm_get tool "$1" sha256)
      if [ -n "$2" ]; then pvv=$(pin "$2"); [ "$mv" = "$pvv" ] || problem "tool $1: version $mv differs from PINS $2=$pvv"; fi
      pvs=$(ph "$(pin "$3")")
      [ "$ms" = "$pvs" ] || problem "tool $1: sha256 differs from PINS $3 (manifest $ms, PINS $pvs)"
      if [ -n "${4:-}" ]; then [ "$(tm_get tool "$1" tag)" = "$(pin "$4")" ] || problem "tool $1: tag differs from PINS $4"; fi
    }
    pair_file() { # tool KEY: the installed-file pin
      local mf pf
      tm_has tool "$1" || return 0
      mf=$(tm_get tool "$1" file_sha256); pf=$(ph "$(pin "$2")")
      [ "$mf" = "$pf" ] || problem "tool $1: file_sha256 differs from PINS $2 (manifest ${mf:-absent}, PINS $pf)"
    }
    pair lean LEAN_VERSION LEAN_SHA256
    pair uv UV_VERSION UV_SHA256
    pair python PYTHON_VERSION PYTHON_SHA256 PBS_TAG
    pair busybox "" BUSYBOX_ROOTFS_SHA256
    pair_file busybox BUSYBOX_SHA256
    if tm_has tool busybox && [ "$(tm_get tool busybox url)" != "$(pin BUSYBOX_ROOTFS_URL)" ]; then problem "tool busybox: url differs from PINS BUSYBOX_ROOTFS_URL"; fi
    pair jq JQ_VERSION JQ_SHA256
    pair bash "" BASH_SRC_SHA256
    pair_file bash BASH_BIN_SHA256
    if tm_has tool bash && [ "$(tm_get tool bash version)" != "$(pin BASH_BASELINE).$(pin BASH_PATCHLEVEL)" ]; then
      problem "tool bash: version $(tm_get tool bash version) differs from PINS BASH_BASELINE.BASH_PATCHLEVEL=$(pin BASH_BASELINE).$(pin BASH_PATCHLEVEL)"
    fi
  fi
  # pending values in the selected scope
  if [ -n "$SELECT" ]; then
    for i in $SELECT; do tm_has image "$i" || { problem "unknown image in --select: $i"; return 0; }; done
    # shellcheck disable=SC2086
    sel_images=$(printf '%s\n' $SELECT)
  else
    sel_images=$(tm_profile_images "$PROFILES") || { problem "unknown profile in: $PROFILES"; return 0; }
  fi
  sel_tools=""
  for i in $sel_images; do sel_tools="$sel_tools $(tm_get image "$i" tools)"; done
  for t in $sel_tools; do
    case " $names " in *" $t "*) continue;; esac
    names="$names $t"
    for k in version url sha256 file_sha256 checksum_source linkage provenance archive; do
      pv=$(tm_get tool "$t" "$k")
      if [ "$pv" = PLACEHOLDER ]; then
        if [ "$t" = bash ]; then pending "tool $t: $k is PLACEHOLDER (from a normal terminal: bash lib/eq-container/build.sh --resolve-tools, review, then --write-pin)"
        else pending "tool $t: $k is PLACEHOLDER (pending its upstream checksum file: TOOLS.toml header)"; fi
      fi
    done
    [ "$(tm_get tool "$t" licence)" != PLACEHOLDER ] || note "tool $t: licence not recorded yet"
  done
  SEL_IMAGES=$sel_images
  # the distroless base (offline): the kept index and arm64 manifest hash to the pins, and the index lists that manifest
  BASE_LAYERS=""
  for i in $sel_images; do
    [ "$(tm_get image "$i" base)" = distroless-cc ] || continue
    if [ ! -f "$FILE_DIR/PINS" ]; then note "no PINS beside the manifest: the distroless base is not checked"; break; fi
    if BASE_LAYERS=$(python3 -I "$here/eqc_json.py" base-verify "$FILE_DIR/$BASE_INDEX" "$FILE_DIR/$BASE_MANIFEST" \
                      "$(pin DISTROLESS_CC | sed 's/^.*@//')" "$(pin DISTROLESS_CC_ARM64)" 2>/dev/null) && [ -n "$BASE_LAYERS" ]; then
      note "distroless base: $BASE_INDEX and $BASE_MANIFEST hash to DISTROLESS_CC and DISTROLESS_CC_ARM64, $(printf '%s\n' "$BASE_LAYERS" | wc -l | tr -d ' ') layers"
    else
      BASE_LAYERS=""
      problem "distroless base: $BASE_INDEX / $BASE_MANIFEST do not hash to DISTROLESS_CC / DISTROLESS_CC_ARM64 in PINS, or the index does not list that linux/arm64 manifest (re-pin both together: README.md)"
    fi
    break
  done
}

run_manifest() {
  check_manifest
  if [ "$PROBLEMS" -gt 0 ]; then echo "TOOLS: INVALID ($PROBLEMS problems)"; return 2; fi
  if [ "$PENDING" -gt 0 ]; then
    echo "TOOLS: PENDING ($PENDING values are placeholders in the selected images: $(printf '%s' "$SEL_IMAGES" | tr '\n' ' '))"
    [ "$ALLOWPH" = 1 ] || return 13
    return 0
  fi
  echo "TOOLS: manifest OK (images: $(printf '%s' "$SEL_IMAGES" | tr '\n' ' '))"
  return 0
}

# ---------------------------------------------------------------------------------------------------------------- container
# Each image is saved ONCE per run (`container image save`, nothing started) into a private temp dir; the lock, the tool files and
# the config are read from that archive by eqc_json.py (layers applied in order, whiteouts honoured, blobs re-hashed). The readers
# run inside $(...) subshells, which cannot set SAVE_ROOT here nor run this shell's EXIT trap: run_images and run_inspect call
# `saved` once in this shell first (save_here), so every subshell finds the archive and the trap removes it.
SAVE_ROOT=""
saved() { # tag -> path of the saved archive (cached); 1 when the save failed
  local tag=$1 key d
  [ -n "$SAVE_ROOT" ] || { SAVE_ROOT=$(mktemp -d "${TMPDIR:-/tmp}/eqc-save.XXXXXX") || return 1; chmod 700 "$SAVE_ROOT"; }
  key=$(printf '%s' "$tag" | tm_sha256_stdin | cut -c1-16)
  d="$SAVE_ROOT/$key"
  if [ ! -s "$d/image.tar" ]; then mkdir -p "$d" && eq_save_image "$tag" "$d" >/dev/null || return 1; fi
  echo "$d/image.tar"
}
cleanup_saves() { [ -z "$SAVE_ROOT" ] || rm -rf "$SAVE_ROOT"; }
trap cleanup_saves EXIT
save_here() { saved "$1" >/dev/null 2>&1 || true; }   # tag: fill the cache in THIS shell (a failure is seen by the readers)
fetch_lock() { # tag -> prints TOOLS.lock on stdout; returns 1 when the image has none
  local a out
  a=$(saved "$1") || return 1
  out=$(eqc_json oci-cat "$a" /opt/eq/TOOLS.lock 2>/dev/null) || out=""
  [ -n "$out" ] || return 1
  printf '%s\n' "$out"
}
image_config() { # tag -> the image config JSON (User, Env, Entrypoint, ExposedPorts, Volumes, Labels, Healthcheck)
  local a
  a=$(saved "$1") || return 1
  eqc_json oci-config "$a"
}
cfg_get() { # JSON KEY -> a one-line rendering of config[KEY] (labels: KEY=Labels.NAME)
  printf '%s' "$1" | python3 -I -c '
import json, sys
c = json.load(sys.stdin); k = sys.argv[1]
if k.startswith("Labels."):
    print((c.get("Labels") or {}).get(k[7:], ""))
elif k in ("ExposedPorts", "Volumes"):
    print(len(c.get(k) or {}))
elif k in ("Entrypoint",):
    print(" ".join(c.get(k) or []))
elif k == "Healthcheck":
    print(" ".join((c.get(k) or {}).get("Test") or []))
elif k == "Env":
    print("\n".join(c.get(k) or []))
else:
    print(c.get(k) or "")' "$2"
}

run_images() {
  local n tag rec dig st why lock label want t row mver msha lsha f bad=0 listed extra nm cfg a bex got diffs
  local -a paths
  eq_need_container
  for n in $SEL_IMAGES; do
    tag=$(eq_img_tag "$n"); rec=$(eq_img_get "$n" EQ_IMAGE_DIGEST)
    dig=$(eqc_image_digest "$tag" || true)
    st=ok; why=""
    if [ -z "$rec" ]; then st=MISSING; why="no build record for $n (never built here)"
    elif [ -z "$dig" ]; then st=MISSING; why="image $tag not present"
    elif [ "$dig" != "$rec" ]; then st=MISMATCH; why="digest $dig differs from the record $rec"; fi
    if [ "$st" = ok ]; then
      save_here "$tag"
      want=$(tm_image_hash "$n")
      if cfg=$(image_config "$tag"); then label=$(cfg_get "$cfg" Labels.eq.tools.sha256); else label=""; fi
      if [ "$label" != "$want" ]; then st=STALE; why="label eq.tools.sha256 '${label:-none}' is not the hash of the current manifest entries ($want): rebuild"; fi
    fi
    if [ "$st" = ok ]; then
      if ! lock=$(fetch_lock "$tag"); then st=LOCK; why="no /opt/eq/TOOLS.lock in the image"; fi
    fi
    if [ "$st" = ok ]; then
      listed=" "
      for t in $(tm_get image "$n" tools); do
        mver=$(tm_get tool "$t" version); msha=$(tm_get tool "$t" sha256)
        row=$(printf '%s\n' "$lock" | awk -F'\t' -v n="$t" '$1 == n { print; exit }')
        listed="$listed$t "
        if [ -z "$row" ]; then st=LOCK; why="$why tool $t is in the manifest but not in the lock;"; continue; fi
        lsha=$(printf '%s' "$row" | cut -f3)
        if [ "$msha" = PLACEHOLDER ]; then st=LOCK; why="$why tool $t is unpinned (PLACEHOLDER in the manifest);"
        elif [ "$lsha" != "$msha" ]; then st=LOCK; why="$why tool $t lock sha256 $lsha differs from the manifest $msha;"; fi
        [ "$(printf '%s' "$row" | cut -f2)" = "$mver" ] || { st=LOCK; why="$why tool $t version differs;"; }
      done
      extra=""
      for nm in $(printf '%s\n' "$lock" | cut -f1 | sort -u); do
        in_list "$nm" "$listed" || extra="$extra$nm "
      done
      [ -z "$extra" ] || { st=UNDECLARED; why="the lock lists tools the manifest does not give this image: $extra"; }
    fi
    if [ "$st" = ok ] && [ "$M_DEEP" = 1 ]; then
      # one pass over the saved image: every tool file of the lock, and (distroless images) every base executable the assemble
      # stage recorded in /opt/eq/BASE_EXECUTABLES.txt, re-hashed host side and compared with the recorded `<sha256>  <path>`
      want=$(printf '%s\n' "$lock" | awk -F'\t' 'NF >= 5 && $4 != "" { print $5 "  " $4 }')
      a=$(saved "$tag") || a=""
      if [ "$(tm_get image "$n" base)" = distroless-cc ]; then
        if [ -n "$a" ] && bex=$(eqc_json oci-cat "$a" /opt/eq/BASE_EXECUTABLES.txt 2>/dev/null); then
          [ -z "$bex" ] || want=$(printf '%s\n%s\n' "$want" "$bex")
        else st=DEEP; why="$why no /opt/eq/BASE_EXECUTABLES.txt in the image;"; fi
      fi
      paths=()
      while read -r _ f; do [ -n "$f" ] && paths[${#paths[@]}]=$f; done <<EOF
$want
EOF
      got=""
      [ -z "$a" ] || [ "${#paths[@]}" = 0 ] || got=$(eqc_json oci-sha256 "$a" "${paths[@]}" 2>/dev/null) || got=""
      diffs=$(LC_ALL=C comm -23 <(printf '%s\n' "$want" | sed '/^$/d' | LC_ALL=C sort -u) <(printf '%s\n' "$got" | LC_ALL=C sort -u) | awk '{ print $2 }' | tr '\n' ' ')
      [ -z "$diffs" ] || { st=DEEP; why="$why files differ from the lock or BASE_EXECUTABLES.txt: $diffs;"; }
    fi
    printf 'IMAGE %-10s %-9s %s %s\n' "$n" "$st" "${dig:-none}" "$why"
    [ "$st" = ok ] || bad=1
  done
  if [ "$bad" = 0 ]; then echo "TOOLS: images OK"; return 0; fi
  echo "TOOLS: images NOT OK"
  return 11
}

# --inspect: the saved image's config, no container started, so it also covers the images that have no shell to probe from inside:
# an unprivileged user, no EXPOSEd port, no VOLUME, no ENTRYPOINT or HEALTHCHECK baked in, no secret-like variable name, PATH inside
# /opt and /usr only.
run_inspect() {
  local n tag v bad=0 st why cfg pth layers nl nb
  eq_need_container
  for n in $SEL_IMAGES; do
    tag=$(eq_img_tag "$n")
    save_here "$tag"
    cfg=$(image_config "$tag") || { printf 'INSPECT %-10s MISSING image %s not present or not saveable\n' "$n" "$tag"; bad=1; continue; }
    st=ok; why=""
    v=$(cfg_get "$cfg" User); case "$v" in ""|0|0:*|root|root:*) st=FAIL; why="$why user '$v' is not unprivileged;";; esac
    v=$(cfg_get "$cfg" ExposedPorts); [ "${v:-0}" = 0 ] || { st=FAIL; why="$why $v EXPOSEd port(s);"; }
    v=$(cfg_get "$cfg" Volumes); [ "${v:-0}" = 0 ] || { st=FAIL; why="$why $v VOLUME(s);"; }
    v=$(cfg_get "$cfg" Entrypoint); [ -z "$v" ] || { st=FAIL; why="$why ENTRYPOINT $v baked in;"; }
    v=$(cfg_get "$cfg" Healthcheck); [ -z "$v" ] || { st=FAIL; why="$why HEALTHCHECK baked in;"; }
    v=$(cfg_get "$cfg" Env)
    if printf '%s\n' "$v" | cut -d= -f1 | grep -qiE 'token|secret|passw|credential|api_?key|anthropic|aws_|github'; then st=FAIL; why="$why secret-like variable name in ENV;"; fi
    pth=$(printf '%s\n' "$v" | sed -n 's/^PATH=//p' | head -n 1)
    [ -z "$pth" ] || tm_only "$pth" "$TM_LOWER$TM_UPPER$TM_DIGITS/_.:-" || { st=FAIL; why="$why odd characters in PATH;"; }
    if printf '%s\n' "$v" | sed -n 's/^PATH=//p' | tr ':' '\n' | grep -vE '^/(opt|usr)(/|$)' | grep -q .; then st=FAIL; why="$why PATH leaves /opt and /usr;"; fi
    # the layers: a distroless image starts with exactly the pinned base manifest's layers; a scratch image is our layer(s) only
    if layers=$(eqc_json oci-layers "$(saved "$tag")" 2>/dev/null) && [ -n "$layers" ]; then
      nl=$(printf '%s\n' "$layers" | wc -l | tr -d ' ')
      case "$(tm_get image "$n" base)" in
        distroless-cc)
          if [ -z "$BASE_LAYERS" ]; then st=FAIL; why="$why the pinned base layers are unknown (manifest check failed);"
          else
            nb=$(printf '%s\n' "$BASE_LAYERS" | wc -l | tr -d ' ')
            if [ "$(printf '%s\n' "$layers" | head -n "$nb")" != "$BASE_LAYERS" ]; then st=FAIL; why="$why the bottom $nb layers are not the pinned distroless base's;"
            elif [ "$nl" -le "$nb" ]; then st=FAIL; why="$why no layer above the base;"; fi
          fi;;
        scratch) [ "$nl" -le 3 ] || { st=FAIL; why="$why $nl layers on a scratch image (want at most 3);"; };;
        *) st=FAIL; why="$why unknown base;";;
      esac
    else st=FAIL; why="$why the layer list is unreadable;"; fi
    printf 'INSPECT %-10s %-7s %s\n' "$n" "$st" "$why"
    [ "$st" = ok ] || bad=1
  done
  if [ "$bad" = 0 ]; then echo "TOOLS: inspect OK"; return 0; fi
  echo "TOOLS: inspect NOT OK"; return 11
}

run_smoke() {
  local n tag t argv rc bad=0 any=0
  eq_need_container
  trap 'eq_sweep; cleanup_saves' EXIT INT TERM
  for n in $SEL_IMAGES; do
    tag=$(eq_img_tag "$n")
    EQ_RUN_MOUNTS=(); EQ_RUN_STDIN=""; EQ_RUN_IMAGE=$tag
    for t in $(tm_get image "$n" tools); do
      argv=$(tm_get tool "$t" smoke)
      [ -n "$argv" ] || continue
      any=1
      # no globbing: a smoke argv may hold a java classpath wildcard (/opt/scala3/lib/*)
      set -f
      # shellcheck disable=SC2086
      ( eq_run "eq-$EQ_RUN_ID-smoke-$n-$t" 120 $argv >/dev/null 2>&1 ); rc=$?
      set +f
      if [ "$rc" = 0 ]; then printf 'SMOKE %-10s %-12s PASS %s\n' "$n" "$t" "$argv"; else printf 'SMOKE %-10s %-12s FAIL rc=%s %s\n' "$n" "$t" "$rc" "$argv"; bad=1; fi
    done
  done
  [ "$any" = 1 ] || echo "SMOKE: no smoke commands in scope"
  if [ "$bad" = 0 ]; then echo "TOOLS: smoke OK"; return 0; fi
  echo "TOOLS: smoke FAILED"; return 11
}

# ------------------------------------------------------------------------------------------------------------------- driver
worst=0
note_rc() { [ "$1" = 0 ] || { [ "$worst" = 0 ] && worst=$1; }; return 0; }
rc=0; run_manifest || rc=$?
note_rc "$rc"
if [ "$M_IMAGES$M_SMOKE$M_INSPECT" != 000 ] && [ "$rc" != 2 ]; then
  [ "$M_SMOKE" = 1 ] || export EQ_NO_STATE_WRITE=1
  # shellcheck disable=SC1091
  . "$here/lib.sh"
  if [ "$M_IMAGES" = 1 ]; then rc=0; run_images || rc=$?; note_rc "$rc"; fi
  if [ "$M_INSPECT" = 1 ]; then rc=0; run_inspect || rc=$?; note_rc "$rc"; fi
  if [ "$M_SMOKE" = 1 ]; then rc=0; run_smoke || rc=$?; note_rc "$rc"; fi
fi
exit "$worst"
