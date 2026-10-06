#!/usr/bin/env bash
# shellcheck disable=SC2034  # EQ_RUN_* are read by eq_run in lib.sh
# verify-tools.sh: check TOOLS.toml and the images built from it. Never builds, never writes outside $EQ_STATE_DIR. Bash 3.2 ok.
#   ./verify-tools.sh [--file TOOLS.toml] [--profiles core,db | --select min-both,tc-go] [MODE...]
#   --select     image names instead of profiles (build.sh checks exactly the images it is about to build)
#   --manifest   (default) static checks of the manifest, no docker: structure and enumerations, unique names, class/profile
#                allowlists of every image, https-only urls, in-repo files hash to their sha256, PINS agree for lean uv python
#                busybox. A PLACEHOLDER in a selected profile's tools is "pending" (exit 13), never an invented value.
#   --images     docker (read-only): per image of the profiles: build record, image ID, label eq.tools.sha256 equal to the hash of the
#                CURRENT manifest entries (a changed entry = stale image), /opt/eq/TOOLS.lock read with `docker create` + `docker cp`
#                (nothing is started) equal to the manifest (every listed tool, no undeclared one).
#   --deep       with --images: also re-hash every installed tool file host-side (docker cp), so a tampered in-image sha256sum
#                cannot lie. Run it before a run / a freeze; the per-container proof is the image ID the harness pins.
#   --inspect    docker (no container started): unprivileged user, no EXPOSE/VOLUME/ENTRYPOINT/HEALTHCHECK, no secret-like ENV name, PATH in /opt,/usr
#   --smoke      docker: run each tool's smoke argv in its image under the hardened flags (network none, read-only, ...).
#   --allow-placeholder   report pending values but exit 0 for them (listing mode)
# Exit: 0 ok | 2 usage or invalid manifest | 10 docker missing/down | 11 an image is missing, stale or does not match | 13 pending value.
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
    -h|--help) sed -n '2,20p' "$0"; exit 0;;
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
is_hex64() { case "$1" in *[!0-9a-f]*|"") return 1;; esac; [ ${#1} = 64 ]; }
in_list() { case " $2 " in *" $1 "*) return 0;; esac; return 1; }   # word list membership

KNOWN_CLASSES="PF CP CR ES RS DS OE EXT"
KNOWN_LINKAGE="static dynamic"
KNOWN_PROV="prebuilt-upstream built-from-source distro-package in-repo"
KNOWN_ROLE="runtime probe selftest server build-only"
KNOWN_KIND="check lang server"
KNOWN_ARCHIVE="tar.gz tar.xz tar.bz2 tar.zst zip binary"

# ---------------------------------------------------------------------------------------------------------------- manifest
check_manifest() {
  local t k v p c i s dup sel_images sel_tools pv names=""
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
    [ "$v" = PLACEHOLDER ] || in_list "$v" "$KNOWN_PROV" || problem "tool $t: provenance '$v' is not one of: $KNOWN_PROV"
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
    v=$(tm_get tool "$t" url)
    case "$v" in
      PLACEHOLDER|https://*|apt:*|file:*) ;;
      *) problem "tool $t: url must be https://, apt:<package>, file:<path> or PLACEHOLDER (got '$v')";;
    esac
    case "$v" in https://*@*) problem "tool $t: credentials in url";; esac
    case "$v" in
      https://*) case "$(tm_get tool "$t" provenance)" in prebuilt-upstream|built-from-source|PLACEHOLDER) ;; *) problem "tool $t: an https url needs provenance prebuilt-upstream or built-from-source";; esac;;
      apt:*) [ "$(tm_get tool "$t" provenance)" = distro-package ] || problem "tool $t: an apt: url needs provenance distro-package";;
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
    for k in dockerfile target kind base profile classes service tools; do
      [ -n "$(tm_get image "$i" "$k")" ] || problem "image $i: missing key $k"
    done
    in_list "$(tm_get image "$i" kind)" "$KNOWN_KIND" || problem "image $i: kind must be one of: $KNOWN_KIND"
    tm_has profile "$(tm_get image "$i" profile)" || problem "image $i: unknown profile $(tm_get image "$i" profile)"
    for c in $(tm_get image "$i" classes); do in_list "$c" "$KNOWN_CLASSES" || problem "image $i: unknown class $c"; done
    for t in $(tm_get image "$i" tools); do
      if ! tm_has tool "$t"; then problem "image $i: lists unknown tool $t"; continue; fi
      [ "$(tm_get tool "$t" role)" != build-only ] || problem "image $i: lists build-only tool $t (builder stages only)"
      in_list "$(tm_get image "$i" profile)" "$(tm_get tool "$t" profiles)" || problem "image $i: tool $t is not allowed in profile $(tm_get image "$i" profile)"
      for c in $(tm_get image "$i" classes); do
        in_list "$c" "$(tm_get tool "$t" classes)" || problem "image $i: class $c may not have tool $t (tool classes: $(tm_get tool "$t" classes))"
      done
    done
  done
  for p in $(tm_names profile); do
    for i in $(tm_get profile "$p" images); do tm_has image "$i" || problem "profile $p: unknown image $i"; done
  done
  # PINS (when beside the manifest) must say the same as the manifest for the four tools both describe
  if [ -f "$FILE_DIR/PINS" ]; then
    pin() { sed -n "s/^$1=//p" "$FILE_DIR/PINS" | head -n 1; }
    pair() { # tool KEY-version KEY-sha [KEY-tag]
      local mv ms pvv pvs
      tm_has tool "$1" || return 0
      mv=$(tm_get tool "$1" version); ms=$(tm_get tool "$1" sha256)
      if [ -n "$2" ]; then pvv=$(pin "$2"); [ "$mv" = "$pvv" ] || problem "tool $1: version $mv differs from PINS $2=$pvv"; fi
      pvs=$(pin "$3"); [ "$pvs" != UNSET ] || pvs=PLACEHOLDER
      [ "$ms" = "$pvs" ] || problem "tool $1: sha256 differs from PINS $3 (manifest $ms, PINS $pvs)"
      if [ -n "${4:-}" ]; then [ "$(tm_get tool "$1" tag)" = "$(pin "$4")" ] || problem "tool $1: tag differs from PINS $4"; fi
    }
    pair lean LEAN_VERSION LEAN_SHA256
    pair uv UV_VERSION UV_SHA256
    pair python PYTHON_VERSION PYTHON_SHA256 PBS_TAG
    pair busybox "" BUSYBOX_SHA256
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
    for k in version url sha256 linkage provenance archive; do
      pv=$(tm_get tool "$t" "$k")
      [ "$pv" != PLACEHOLDER ] || pending "tool $t: $k is PLACEHOLDER (pending TOOLCHAINS.md or a resolve step: build.sh --resolve-tools --write-pin)"
    done
    [ "$(tm_get tool "$t" licence)" != PLACEHOLDER ] || note "tool $t: licence not recorded yet"
  done
  SEL_IMAGES=$sel_images
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

# ------------------------------------------------------------------------------------------------------------------- docker
fetch_lock() { # tag -> prints TOOLS.lock on stdout; returns 1 when the image has none
  local tag=$1 cid out
  cid=$(docker create --pull never --network none "$tag" /nonexistent 2>/dev/null) || return 1
  out=$(docker cp "$cid:/opt/eq/TOOLS.lock" - 2>/dev/null | tar -xOf - 2>/dev/null) || out=""
  docker rm "$cid" >/dev/null 2>&1 || true
  [ -n "$out" ] || return 1
  printf '%s\n' "$out"
}
hash_in_image() { # tag path -> sha256 of the file in the image (host-side; nothing is started)
  local cid h
  cid=$(docker create --pull never --network none "$1" /nonexistent 2>/dev/null) || return 1
  h=$(docker cp -L "$cid:$2" - 2>/dev/null | tar -xOf - 2>/dev/null | tm_sha256_stdin) || h=""
  docker rm "$cid" >/dev/null 2>&1 || true
  printf '%s' "$h"
}

run_images() {
  local n tag rec id st why lock label want t row mver msha lsha f fh bad=0 listed extra nm
  eq_need_docker
  for n in $SEL_IMAGES; do
    tag=$(eq_img_tag "$n"); rec=$(eq_img_get "$n" EQ_IMAGE_ID)
    id=$(docker image inspect --format '{{.Id}}' "$tag" 2>/dev/null || true)
    st=ok; why=""
    if [ -z "$rec" ]; then st=MISSING; why="no build record for $n (never built here)"
    elif [ -z "$id" ]; then st=MISSING; why="image $tag not present"
    elif [ "$id" != "$rec" ]; then st=MISMATCH; why="image id $id differs from the record $rec"; fi
    if [ "$st" = ok ]; then
      want=$(tm_image_hash "$n")
      label=$(docker image inspect --format '{{index .Config.Labels "eq.tools.sha256"}}' "$tag" 2>/dev/null || true)
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
      while IFS="$(printf '\t')" read -r _ _ _ f fh; do
        [ -n "$f" ] || continue
        if [ "$(hash_in_image "$tag" "$f")" != "$fh" ]; then st=DEEP; why="$why $f differs from the lock;"; fi
      done <<EOF
$lock
EOF
    fi
    printf 'IMAGE %-10s %-9s %s %s\n' "$n" "$st" "${id:-none}" "$why"
    [ "$st" = ok ] || bad=1
  done
  if [ "$bad" = 0 ]; then echo "TOOLS: images OK"; return 0; fi
  echo "TOOLS: images NOT OK"
  return 11
}

# --inspect: what `docker image inspect` says about each image, no container started, so it also covers the images that have no shell to
# probe from inside: an unprivileged user, no EXPOSEd port, no VOLUME (an anonymous volume survives the container), no ENTRYPOINT or
# HEALTHCHECK baked in, no secret-like variable name, PATH inside /opt and /usr only.
run_inspect() {
  local n tag v bad=0 st why
  eq_need_docker
  fmt() { docker image inspect --format "$1" "$tag" 2>/dev/null; }
  for n in $SEL_IMAGES; do
    tag=$(eq_img_tag "$n")
    docker image inspect "$tag" >/dev/null 2>&1 || { printf 'INSPECT %-10s MISSING image %s not present\n' "$n" "$tag"; bad=1; continue; }
    st=ok; why=""
    v=$(fmt '{{.Config.User}}'); case "$v" in ""|0|0:*|root|root:*) st=FAIL; why="$why user '$v' is not unprivileged;";; esac
    v=$(fmt '{{len .Config.ExposedPorts}}'); [ "${v:-0}" = 0 ] || { st=FAIL; why="$why $v EXPOSEd port(s);"; }
    v=$(fmt '{{len .Config.Volumes}}'); [ "${v:-0}" = 0 ] || { st=FAIL; why="$why $v VOLUME(s);"; }
    v=$(fmt '{{.Config.Entrypoint}}'); case "$v" in ""|"[]"|"<no value>") ;; *) st=FAIL; why="$why ENTRYPOINT $v baked in;";; esac
    v=$(fmt '{{if .Config.Healthcheck}}{{.Config.Healthcheck.Test}}{{end}}'); case "$v" in ""|"<no value>") ;; *) st=FAIL; why="$why HEALTHCHECK baked in;";; esac
    v=$(fmt '{{range .Config.Env}}{{println .}}{{end}}')
    if printf '%s\n' "$v" | cut -d= -f1 | grep -qiE 'token|secret|passw|credential|api_?key|anthropic|aws_|github'; then st=FAIL; why="$why secret-like variable name in ENV;"; fi
    case "$(printf '%s\n' "$v" | sed -n 's/^PATH=//p' | head -n 1)" in "") ;; *[!a-zA-Z0-9/_.:-]*) st=FAIL; why="$why odd characters in PATH;";; esac
    if printf '%s\n' "$v" | sed -n 's/^PATH=//p' | tr ':' '\n' | grep -vE '^/(opt|usr)(/|$)' | grep -q .; then st=FAIL; why="$why PATH leaves /opt and /usr;"; fi
    printf 'INSPECT %-10s %-7s %s\n' "$n" "$st" "$why"
    [ "$st" = ok ] || bad=1
  done
  if [ "$bad" = 0 ]; then echo "TOOLS: inspect OK"; return 0; fi
  echo "TOOLS: inspect NOT OK"; return 11
}

run_smoke() {
  local n tag t argv rc bad=0 any=0
  eq_need_docker
  trap 'eq_sweep' EXIT INT TERM
  for n in $SEL_IMAGES; do
    tag=$(eq_img_tag "$n")
    eq_require_image "$tag"
    EQ_RUN_MOUNTS=(); EQ_RUN_EXTRA=(); EQ_RUN_STDIN=""; EQ_RUN_IMAGE=$tag
    for t in $(tm_get image "$n" tools); do
      argv=$(tm_get tool "$t" smoke)
      [ -n "$argv" ] || continue
      any=1
      # no globbing: a smoke argv may hold a java classpath wildcard (/opt/scala3/lib/*)
      set -f
      # shellcheck disable=SC2086
      eq_run "eq-$EQ_RUN_ID-smoke-$n-$t" 120 $argv >/dev/null 2>&1; rc=$?
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
