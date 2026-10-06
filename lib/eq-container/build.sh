#!/usr/bin/env bash
# build.sh: build, check or remove the eq-container images, built locally with Apple `container build` (BuildKit) from the
# Dockerfiles in this directory. Never pushes, never pulls an eq image (only the digest-pinned bases, inside the builder).
#   ./build.sh [--profiles core,jvm | --set min|all] [--only NAME] [--keep-profile conservative|noprivate|slim] [--yes]
#              [--dry-run] [--force] [--no-cache]
#              --profiles: the images of TOOLS.toml profiles (default: core, the minimum the item classes PF, CP, CR need;
#              `all` = every profile neither explicit nor deferred; a deferred profile (rust, haskell) is refused: exit 10)
#              --set min (= all): Dockerfile.minimal's min-lean min-py min-both
#   ./build.sh --check     [--profiles ..|--set ..]   verify images, records and pins WITHOUT building (0 ok, 11 not ok, 10 no container)
#   ./build.sh --uninstall [--profiles ..|--set ..] [--yes]   container image delete the recorded tags, drop their records (--set all
#                                                 also removes the records of images no longer built: full, tc-rust, tc-haskell)
#   ./build.sh --resolve-tools [--write-pin]      build the bash-report stage (--no-cache): GNU bash's tarball and patches are
#                                                 GPG-verified against BASH_GPG_FPR, then their hashes and the built binary's are
#                                                 printed (`PIN KEY VALUE pinned: ...`); --write-pin writes them into PINS, the
#                                                 Dockerfile.minimal ARGs and TOOLS.toml (trust on first use AFTER the signature check)
# Bases (USER decision 2026-10-06, DESIGN_DISTROLESS.md): final images FROM the pinned distroless cc image or FROM scratch; the
# builders are pinned by digest; no Debian snapshot, apt or dpkg (the former --set full and --no-snapshot are refused: exit 2).
# Every image's check stage (check-<target>: minimal/check.sh, or the tool's version for the toolchains) is built first, from
# the same cache; a failing check is exit 12 and nothing is recorded.
# Identity: each image's record holds its tag (under eq.invalid/, which no registry resolves) and the digest `container image
# inspect` reports right after the build; every run re-checks that digest (lib.sh eq_require_image).
# Idempotent: an image is skipped when its record matches the present digest and the hash of its inputs (Dockerfile, minimal/,
# project/, tc/, base/, TOOLS.toml, target, keep profile). --force rebuilds.
# Results: $EQ_STATE_DIR/images/NAME.env, $EQ_STATE_DIR/image.env (summary: EQ_IMAGE, EQ_CONTAINER_IMAGE_PF/CP/CR = TAG@sha256:..).
# Builder size: EQ_BUILD_MEMORY (default 8G), EQ_BUILD_CPUS (default 4): the Mathlib stage needs more than the CLI's 2 GB default.
# Exit codes: see lib.sh (0 ok, 2 usage, 10 no container or a deferred profile, 11 image missing/stale, 12 build or check failed,
# 13 unresolved pin).
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd -P)
for a in "$@"; do case "$a" in --dry-run|--check) export EQ_NO_STATE_WRITE=1;; esac; done
# shellcheck disable=SC1091
. "$here/lib.sh"
# shellcheck disable=SC1091
. "$here/tools.sh"
cd "$here"

SET=""; SET_GIVEN=0; PROFILES=""; ONLY=""; PROFILE=conservative; YES=0; DRY=0; FORCE=0; NOCACHE=0
ACTION=build; WRITEPIN=0
need() { [ $# -ge 2 ] && [ -n "$2" ] || { echo "build.sh: $1 needs a value" >&2; exit 2; }; }
while [ $# -gt 0 ]; do
  case "$1" in
    --set) need "$@"; SET=$2; SET_GIVEN=1; shift;;
    --profiles) need "$@"; PROFILES=$2; shift;;
    --only) need "$@"; ONLY=$2; shift;;
    --keep-profile) need "$@"; PROFILE=$2; shift;;
    --yes|-y) YES=1;;
    --dry-run) DRY=1;;
    --force) FORCE=1;;
    --no-cache) NOCACHE=1;;
    --no-snapshot) echo "build.sh: --no-snapshot was removed with the Debian snapshot: no stage reads snapshot.debian.org or runs apt since 2026-10-06 (DESIGN_DISTROLESS.md)" >&2; exit 2;;
    --check) ACTION=check;;
    --uninstall) ACTION=uninstall;;
    --resolve-tools) ACTION=tools;;
    --write-pin) WRITEPIN=1;;
    -h|--help) awk 'NR == 1 { next } /^#/ { print; next } { exit }' "$0"; exit 0;;
    *) echo "build.sh: unknown argument: $1" >&2; exit 2;;
  esac
  shift
done
EQ_BUILD_MEMORY=${EQ_BUILD_MEMORY:-8G}; EQ_BUILD_CPUS=${EQ_BUILD_CPUS:-4}

[ "$WRITEPIN" = 0 ] || [ "$ACTION" = tools ] || { echo "build.sh: --write-pin works only with --resolve-tools" >&2; exit 2; }
case "$SET" in
  full) echo "build.sh: --set full was removed: the Debian image 'full' is gone (USER decision 2026-10-06, DESIGN_DISTROLESS.md); use --profiles core (the default) or --set min" >&2; exit 2;;
  ""|min|all) ;;
  *) echo "build.sh: --set must be min or all" >&2; exit 2;;
esac
tm_load "$here/TOOLS.toml" || { echo "TOOLS.toml is unreadable (see above)" >&2; exit 2; }
[ "$SET_GIVEN" = 1 ] || [ -n "$PROFILES" ] || PROFILES=core
if [ -n "$PROFILES" ]; then
  [ "$SET_GIVEN" = 0 ] || { echo "--set and --profiles exclude each other" >&2; exit 2; }
  pl=$(tm_expand_profiles "$PROFILES") || exit 2
  PROFILES=$(printf '%s' "$pl" | tr '\n' ' ' | sed 's/ *$//')
  tm_refuse_deferred "$PROFILES" || exit 10
  NAMES=$(tm_profile_images "$PROFILES" | tr '\n' ' ' | sed 's/ *$//')
else
  NAMES="min-lean min-py min-both"
fi
if [ -n "$ONLY" ]; then
  case " $EQ_IMAGE_NAMES " in *" $ONLY "*) NAMES=$ONLY;; *) echo "--only: unknown image $ONLY" >&2; exit 2;; esac
fi
case "$PROFILE" in
  conservative) KEEP="olean olean.private olean.server ir ir.sig"; SUFFIX="";;
  noprivate)    KEEP="olean olean.server ir ir.sig"; SUFFIX="-noprivate";;
  slim)         KEEP="olean ir ir.sig"; SUFFIX="-slim";;
  *) echo "--keep-profile must be conservative, noprivate or slim" >&2; exit 2;;
esac

# the record of an image: ONE per image (images/NAME.env, read by image.env, --check, verify-tools.sh and lib.sh); a keep-profile
# build replaces it, its tag carrying the suffix and its EQ_KEEP_SUFFIX/EQ_KEEP_EXTS the profile
rn() { echo "$1"; }
img_file() { case "$1" in tc-*) echo Dockerfile.toolchains;; *) echo Dockerfile.minimal;; esac; }
img_target() {
  case "$1" in
    min-lean) echo eq-lean-min;; min-py) echo eq-py-min;; min-both) echo eq-min;;
    tc-*) tm_get image "$1" target;;
  esac
}
img_tag() { local base; base=$(eq_img_default_tag "$1"); case "$1" in min-lean|min-both) echo "${base}${SUFFIX}";; *) echo "$base";; esac; }
img_keep() { case "$1" in min-lean|min-both) echo "$KEEP";; *) echo "";; esac; }
in_manifest() { tm_has image "$1"; }
inputs_hash() { # name: the Dockerfile (its ARGs are the pins), the scripts and files it copies, the manifest, the base manifests
  local f df files
  df=$(img_file "$1")
  case "$1" in
    tc-*) files="$df TOOLS.toml tools.sh $(find tc -type f | LC_ALL=C sort) $(find base -type f | LC_ALL=C sort)";;
    *) files="$df project/SHA256SUMS project/lakefile.toml project/lake-manifest.json project/lean-toolchain project/StackMathlib.lean project/StackMathlib/Basic.lean $(find minimal -type f | LC_ALL=C sort) TOOLS.toml tools.sh tc/build-bash.sh $(find base -type f | LC_ALL=C sort)";;
  esac
  {
    for f in $files; do printf 'FILE %s\n' "$f"; cat "$f"; done
    printf 'TARGET %s\nKEEP %s\nBACKEND container\n' "$(img_target "$1")" "$(img_keep "$1")"
  } | tm_sha256_stdin
}
pin_value() { sed -n "s/^$1=//p" PINS | head -n 1; }
hexn() { tm_only "$1" "$TM_HEX" && [ "${#1}" = "$2" ]; }
is_placeholder() { case "$1" in ""|UNSET|*TODO*) return 0;; esac; return 1; }
image_ref() { # VALUE: NAME[:TAG]@sha256:<64 hex>; never a tag alone, never the tag latest, never a debug variant
  local v=$1 name last
  case "$v" in *@sha256:*) ;; *) return 1;; esac
  hexn "${v#*@sha256:}" 64 || return 1
  name=${v%%@sha256:*}
  tm_only "$name" "$TM_LOWER$TM_DIGITS./:_-" || return 1
  case "$name" in *debug*|*/|*:|/*) return 1;; esac
  last=${name##*/}
  case "$last" in *:*) [ "${last#*:}" != latest ] || return 1;; esac
}
image_repo() { local name=${1%%@sha256:*} last; last=${name##*/}; case "$last" in *:*) echo "${name%:*}";; *) echo "$name";; esac; }
pin_format() { # KEY VALUE: 0 when VALUE has the shape KEY needs (a malformed pin is refused before any build, never passed on).
  # Literal character lists only (tools.sh tm_only): a bracket range follows the locale's collation in bash 3.2.
  local repo mid
  case "$1" in
    DISTROLESS_CC_ARM64) case "$2" in sha256:*) hexn "${2#sha256:}" 64;; *) return 1;; esac;;
    DISTROLESS_*)        # gcr.io/distroless/<name>-debian13[:tag]@sha256:<64 hex>
                         image_ref "$2" || return 1
                         repo=$(image_repo "$2")
                         case "$repo" in gcr.io/distroless/*-debian13) ;; *) return 1;; esac
                         mid=${repo#gcr.io/distroless/}; mid=${mid%-debian13}
                         tm_only "$mid" "$TM_LOWER$TM_DIGITS-";;
    *_IMAGE) image_ref "$2";;
    *_URL) case "$2" in https://*) ;; *) return 1;; esac
           case "$2" in *@*) return 1;; esac
           tm_only "$2" "$TM_LOWER$TM_UPPER$TM_DIGITS._~:/%+-";;
    *_SHA256) hexn "$2" 64;;
    MATHLIB_REV) hexn "$2" 40;;
    BASH_GPG_FPR) tm_only "$2" "0123456789ABCDEF" && [ "${#2}" = 40 ];;
    BASH_PATCHLEVEL) case "$2" in 0?*) return 1;; esac; tm_only "$2" "$TM_DIGITS" && [ "${#2}" -le 3 ];;
    BASH_BASELINE) case "$2" in *.*.*|.*|*.) return 1;; *.*) tm_only "${2%.*}" "$TM_DIGITS" && tm_only "${2#*.}" "$TM_DIGITS";; *) return 1;; esac;;
    *) tm_only "$2" "$TM_LOWER$TM_UPPER$TM_DIGITS.+~_-";;
  esac
}
BASH_PINS="BASH_SRC_SHA256 BASH_PATCHES_SHA256 BASH_BIN_SHA256"
needed_pins() {
  case "$1" in
    tc-*) echo "BUILDER_IMAGE DISTROLESS_CC DISTROLESS_CC_ARM64";;
    *) echo "BUILDER_IMAGE MUSL_BUILDER_IMAGE DISTROLESS_CC DISTROLESS_CC_ARM64 LEAN_VERSION LEAN_SHA256 UV_VERSION UV_SHA256" \
            "PYTHON_VERSION PBS_TAG PYTHON_SHA256 MATHLIB_REV BUSYBOX_ROOTFS_URL BUSYBOX_ROOTFS_SHA256 BUSYBOX_SHA256 JQ_VERSION" \
            "JQ_SHA256 BASH_BASELINE BASH_PATCHLEVEL BASH_GPG_FPR $BASH_PINS";;
  esac
}
global_arg() { # DOCKERFILE KEY: the value of every `ARG KEY=` line, one per line, prefixed G (before the first FROM) or S (a stage)
  awk -v k="ARG $2=" 'BEGIN { g = "G" } /^FROM / { g = "S" } index($0, k) == 1 { print g substr($0, length(k) + 1) }' "$1"
}
PIN_PLACEHOLDER=0
pins_check() { # NAME [KEYS]: one line per problem; 0 when PINS and the Dockerfile agree and no pin is a placeholder
  local name=$1 df k pv dv bad=0 n
  df=$(img_file "$name")
  for k in ${2:-$(needed_pins "$name")}; do
    n=$(grep -c "^$k=" PINS || true)
    [ "$n" = 1 ] || { echo "pin $k: PINS holds $n '$k=' lines, want exactly one"; bad=1; continue; }
    pv=$(pin_value "$k")
    if is_placeholder "$pv"; then echo "pin $k is a placeholder in PINS"; PIN_PLACEHOLDER=1; bad=1; continue; fi
    pin_format "$k" "$pv" || { echo "pin $k is malformed in PINS: $pv"; bad=1; continue; }
    dv=$(global_arg "$df" "$k")
    case "$dv" in
      G*) case "$dv" in *"
"*) echo "pin $k: $df holds more than one 'ARG $k=' line, want exactly one (global, before the first FROM)"; bad=1; continue;; esac;;
      "") echo "pin $k: $df has no global 'ARG $k=' line"; bad=1; continue;;
      *) echo "pin $k: $df sets 'ARG $k=' inside a stage, want exactly one global line before the first FROM"; bad=1; continue;;
    esac
    dv=${dv#G}
    if is_placeholder "$dv"; then echo "pin $k is a placeholder in $df"; PIN_PLACEHOLDER=1; bad=1; continue; fi
    [ "$pv" = "$dv" ] || { echo "pin $k differs: PINS=$pv $df=$dv"; bad=1; }
  done
  return $bad
}
manifest_check() { # NAME: verify-tools.sh --manifest for one image (0 ok, 2 invalid, 13 a selected value is a placeholder)
  local out rc=0
  in_manifest "$1" || return 0
  out=$(bash "$here/verify-tools.sh" --select "$1" --manifest 2>&1) || rc=$?
  [ "$rc" = 0 ] || printf '%s\n' "$out" | grep -E '^(PENDING|PROBLEM|TOOLS:)' || true
  return "$rc"
}

# ------------------------------------------------------------------ --resolve-tools
# The bash-report stage (Dockerfile.minimal) runs tc/build-bash.sh resolve: the key is fetched by fingerprint, the keyring must
# hold exactly the pinned primary key, and the tarball and every patch must carry a good signature from it BEFORE anything is
# hashed or built; it then prints `SIGNATURES OK ...` and one `PIN KEY VALUE pinned: same|DIFFERS (old)|PLACEHOLDER` line per pin.
if [ "$ACTION" = tools ]; then
  rbad=0
  for k in MUSL_BUILDER_IMAGE BASH_BASELINE BASH_PATCHLEVEL BASH_GPG_FPR; do
    out=$(pins_check min-both "$k") || { printf '%s\n' "$out" >&2; rbad=1; }
  done
  for k in $BASH_PINS; do   # placeholders are expected here; a set value must be well-formed and agree with the ARG
    pv=$(pin_value "$k"); dv=$(global_arg Dockerfile.minimal "$k"); dv=${dv#G}
    if is_placeholder "$pv" && is_placeholder "$dv"; then continue; fi
    out=$(pins_check min-both "$k") || { printf '%s\n' "$out" >&2; rbad=1; }
  done
  [ "$rbad" = 0 ] || { echo "PINS and the Dockerfile.minimal ARGs must be well-formed and agree before --resolve-tools" >&2; exit 2; }
  eq_need_container
  log="$EQ_STATE_DIR/tools-report.log"
  echo "== bash-report: GNU bash $(pin_value BASH_BASELINE) patch level $(pin_value BASH_PATCHLEVEL), key $(pin_value BASH_GPG_FPR) (log $log)"
  set +e
  eqc build --progress plain --no-cache --platform linux/arm64 -m "$EQ_BUILD_MEMORY" -c "$EQ_BUILD_CPUS" \
    -f Dockerfile.minimal --target bash-report -t "eq.invalid/eq-report:$$" . > "$log" 2>&1
  rc=$?
  set -e
  eqc image delete "eq.invalid/eq-report:$$" >/dev/null 2>&1 || true
  [ "$rc" = 0 ] || { tail -n 30 "$log" >&2; echo "the bash-report stage failed (rc $rc): a download, a signature or the build failed; nothing is pinned (see $log)" >&2; exit 12; }
  sig=$(LC_ALL=C grep -o 'SIGNATURES OK: .*' "$log" | head -n 1 || true)
  [ -n "$sig" ] || { echo "no 'SIGNATURES OK' line in $log: nothing is pinned" >&2; exit 12; }
  lines=$(LC_ALL=C grep -o 'PIN BASH_[A-Z0-9_]* [0-9a-f]\{64\} pinned: [A-Za-z]*' "$log" | LC_ALL=C sort -u || true)
  for k in $BASH_PINS; do
    n=$(printf '%s\n' "$lines" | awk -v k="$k" '$2 == k' | wc -l | tr -d ' ')
    [ "$n" = 1 ] || { echo "the report holds $n values for $k (want exactly one): nothing is pinned (see $log)" >&2; exit 12; }
  done
  echo "$sig"
  printf '%s\n' "$lines"
  if [ "$WRITEPIN" = 1 ]; then
    for k in $BASH_PINS; do
      v=$(printf '%s\n' "$lines" | awk -v k="$k" '$2 == k { print $3 }')
      tm_is_hex64 "$v" || { echo "the value for $k is not 64 lowercase hex: nothing more is pinned" >&2; exit 12; }
      for f in PINS Dockerfile.minimal; do
        if [ "$f" = PINS ]; then sed "s/^$k=.*/$k=$v/" "$f" > "$f.tmp.$$"; else sed "s/^ARG $k=.*/ARG $k=$v/" "$f" > "$f.tmp.$$"; fi
        mv "$f.tmp.$$" "$f"
      done
      case "$k" in
        BASH_SRC_SHA256) tm_set TOOLS.toml tool bash sha256 "$v";;
        BASH_BIN_SHA256) tm_set TOOLS.toml tool bash file_sha256 "$v";;
      esac
    done
    tm_set TOOLS.toml tool bash checksum_source "GNU bash-$(pin_value BASH_BASELINE).tar.gz and patches 001-$(printf '%03d' "$(pin_value BASH_PATCHLEVEL)") GPG-verified against the primary key $(pin_value BASH_GPG_FPR) in the bash-report stage, then hashed (build.sh --resolve-tools --write-pin, $(date -u +%F)); the binary hash is trust on first use after that check"
    echo "pinned BASH_SRC_SHA256, BASH_PATCHES_SHA256 and BASH_BIN_SHA256 in PINS and Dockerfile.minimal, and the bash entry of TOOLS.toml (sha256, file_sha256, checksum_source); review the diff, then commit it"
  else
    echo "to pin: re-run with --write-pin (PINS, the Dockerfile.minimal ARGs and the bash entry of TOOLS.toml)"
  fi
  exit 0
fi

# ------------------------------------------------------------------ --check
if [ "$ACTION" = check ]; then
  eqc_state
  [ "$EQC_OK" = 1 ] || { echo "CHECK: SKIP ($EQC_WHY)"; exit 10; }
  rc=0
  for n in $NAMES; do
    tag=$(eq_img_tag "$n"); rec=$(eq_img_get "$n" EQ_IMAGE_DIGEST)
    dig=$(eqc_image_digest "$tag" || true)
    st=ok; why=""
    if [ -z "$rec" ]; then st=MISSING; why="no record in $EQ_STATE_DIR/images/$n.env (never built here)"
    elif [ -z "$dig" ]; then st=MISSING; why="image $tag not present"
    elif [ "$dig" != "$rec" ]; then st=MISMATCH; why="digest $dig != recorded $rec"
    else
      recin=$(eq_img_get "$n" EQ_INPUTS_SHA256)
      SUFFIX_SAVE=$SUFFIX; SUFFIX=$(eq_img_get "$n" EQ_KEEP_SUFFIX); KEEP_SAVE=$KEEP; KEEP=$(eq_img_get "$n" EQ_KEEP_EXTS)
      cur=$(inputs_hash "$n"); SUFFIX=$SUFFIX_SAVE; KEEP=$KEEP_SAVE
      [ "$recin" = "$cur" ] || { st=STALE; why="Dockerfile/minimal/project/tc/base/manifest changed since the build (inputs hash differs)"; }
    fi
    PIN_PLACEHOLDER=0
    pc=$(pins_check "$n" || true)
    [ -z "$pc" ] || { [ "$st" = ok ] && st=PINS; why="$why $(printf '%s' "$pc" | tr '\n' ';')"; }
    mrc=0; mc=$(manifest_check "$n" 2>&1) || mrc=$?
    [ "$mrc" = 0 ] || { [ "$st" = ok ] && st=PINS; why="$why tools manifest: $(printf '%s' "$mc" | tr '\n' ';')"; }
    printf 'CHECK %-9s %-8s %s %s\n' "$n" "$st" "${dig:-none}" "$why"
    [ "$st" = ok ] || rc=11
  done
  [ $rc = 0 ] && echo "CHECK: OK" || echo "CHECK: NOT OK"
  exit $rc
fi

# ------------------------------------------------------------------ --uninstall
if [ "$ACTION" = uninstall ]; then
  [ "$SET" != all ] || [ -n "$PROFILES" ] || [ -n "$ONLY" ] || NAMES="$EQ_IMAGE_NAMES $EQ_LEGACY_IMAGE_NAMES"
  eqc_state
  [ "$EQC_OK" = 1 ] || { echo "UNINSTALL: SKIP ($EQC_WHY); records kept"; exit 10; }
  if [ "$YES" != 1 ]; then
    if [ -t 0 ]; then printf 'Remove images %s and their records? [y/N] ' "$NAMES"; read -r ans; case "$ans" in y|Y|yes) ;; *) echo "aborted"; exit 2;; esac
    else echo "refusing to remove images without --yes" >&2; exit 2; fi
  fi
  for n in $NAMES; do
    for f in "$EQ_STATE_DIR/images/$n.env" "$EQ_STATE_DIR/images/$n"-*.env; do
      [ -f "$f" ] || continue
      [ "$(sed -n 's/^EQ_IMAGE_NAME=//p' "$f" | head -n 1)" = "$n" ] || continue
      xt=$(sed -n 's/^EQ_IMAGE_TAG=//p' "$f" | head -n 1)
      if [ "$DRY" = 1 ]; then echo "would: container image delete $xt; rm $f"; continue; fi
      if eqc_image_digest "$xt" >/dev/null; then eqc image delete "$xt" >/dev/null && echo "removed $xt" || echo "could not remove $xt (in use?)" >&2
      else echo "not present: $xt"; fi
      rm -f "$f"
    done
  done
  [ "$DRY" = 1 ] || rm -f "$EQ_STATE_DIR/image.env"
  echo "UNINSTALL: done"
  exit 0
fi

# ------------------------------------------------------------------ build
eqc_state
echo "== plan (state dir $EQ_STATE_DIR${PROFILES:+; profiles: $PROFILES})"
PLAN=""
for n in $NAMES; do
  tag=$(img_tag "$n"); rec=$(eq_img_get "$(rn "$n")" EQ_IMAGE_DIGEST); recin=$(eq_img_get "$(rn "$n")" EQ_INPUTS_SHA256); cur=$(inputs_hash "$n")
  dig=""; [ "$EQC_OK" = 1 ] && dig=$(eqc_image_digest "$tag" || true)
  if [ "$FORCE" != 1 ] && [ -n "$rec" ] && [ "$rec" = "$dig" ] && [ "$recin" = "$cur" ] && [ "$(eq_img_get "$(rn "$n")" EQ_IMAGE_TAG)" = "$tag" ]; then act=skip; else act=build; fi
  printf '  %-9s %-40s %-5s inputs %s\n' "$n" "$tag" "$act" "$(printf '%s' "$cur" | cut -c1-12)"
  PLAN="$PLAN $n:$act"
done
if [ "$EQC_OK" != 1 ]; then echo "container unavailable: $EQC_WHY"; [ "$DRY" = 1 ] && exit 0; exit 10; fi
for n in $NAMES; do
  PIN_PLACEHOLDER=0
  msg=$(pins_check "$n" || true)
  if [ -n "$msg" ]; then
    echo "$msg" >&2
    case "$msg" in *placeholder*) PIN_PLACEHOLDER=1;; esac
    if [ "$PIN_PLACEHOLDER" = 1 ]; then
      echo "unresolved pin: BASH_SRC_SHA256, BASH_PATCHES_SHA256 and BASH_BIN_SHA256 come from the GPG-checked bash build: from a normal terminal run bash lib/eq-container/build.sh --resolve-tools, review the printed values, then re-run it with --write-pin (checklist D2); any other key: see the comment above it in PINS" >&2
      [ "$DRY" = 1 ] && continue
      exit 13
    fi
    [ "$DRY" = 1 ] || { echo "PINS and the Dockerfile ARGs must be well-formed and agree; fix before building" >&2; exit 2; }
  fi
  mrc=0; manifest_check "$n" >&2 || mrc=$?
  if [ "$mrc" = 13 ]; then
    echo "unresolved tool pin in TOOLS.toml for $n: bash (sha256, file_sha256): bash lib/eq-container/build.sh --resolve-tools, review, then --write-pin; any other tool: its upstream checksum file (TOOLS.toml header)" >&2
    [ "$DRY" = 1 ] && continue
    exit 13
  elif [ "$mrc" != 0 ]; then
    echo "TOOLS.toml is invalid for $n (see above)" >&2
    [ "$DRY" = 1 ] && continue
    exit 2
  fi
done
[ "$DRY" = 1 ] && { echo "dry run: nothing built"; exit 0; }
NOBUILD=0
case "$PLAN" in *:build*) ;; *) echo "all images up to date (use --force to rebuild)"; NOBUILD=1;; esac
if [ "$NOBUILD" = 0 ] && [ "$YES" != 1 ]; then
  if [ -t 0 ]; then
    printf 'Build %s now? 10-40 min per cold build, several GB of disk, network for the build only. [y/N] ' "$NAMES"
    read -r ans; case "$ans" in y|Y|yes) ;; *) echo "aborted"; exit 2;; esac
  else echo "refusing to start a long build non-interactively without --yes" >&2; exit 2; fi
fi

extra=(); [ "$NOCACHE" = 1 ] && extra=(--no-cache)
for n in $NAMES; do
  case "$PLAN" in *" $n:build"*) ;; *) echo "== $n: up to date, skipped"; continue;; esac
  tag=$(img_tag "$n"); df=$(img_file "$n"); tg=$(img_target "$n"); keep=$(img_keep "$n")
  log="$EQ_STATE_DIR/build-$n.log"
  targs=(); [ -n "$tg" ] && targs=(--target "$tg")
  kargs=(); [ -n "$keep" ] && kargs=(--build-arg "KEEP_EXTS=$keep")
  largs=(); tsha=""
  if in_manifest "$n"; then tsha=$(tm_image_hash "$n"); largs=(--label "eq.tools.sha256=$tsha"); fi
  case "$(tm_get image "$n" base)" in
    distroless-cc) bref=$(pin_value DISTROLESS_CC); barm=$(pin_value DISTROLESS_CC_ARM64);;
    *) bref=scratch; barm="";;
  esac
  [ -n "$tg" ] || { echo "no target for $n" >&2; exit 2; }
  echo "== check $n (stage check-$tg, then the image from the same cache) -> $tag (log $log)"
  tb=$SECONDS
  set +e
  # base image digests in the Dockerfiles (FROM ...@sha256:) are verified by the builder itself; nothing else is pulled.
  # 1. the check stage FROM the final target (never recorded; its tag is deleted at once)
  eqc build --progress plain --platform linux/arm64 -m "$EQ_BUILD_MEMORY" -c "$EQ_BUILD_CPUS" \
    ${extra[@]+"${extra[@]}"} --target "check-$tg" ${kargs[@]+"${kargs[@]}"} \
    -t "eq.invalid/eq-check-$n:$$" -f "$df" . > "$log" 2>&1
  rc=$?
  eqc image delete "eq.invalid/eq-check-$n:$$" >/dev/null 2>&1
  if [ "$rc" = 0 ]; then
    # 2. the final target: the stages the check ran on come from the cache, so the image recorded is the one that was checked
    eqc build --progress plain --platform linux/arm64 -m "$EQ_BUILD_MEMORY" -c "$EQ_BUILD_CPUS" \
      ${targs[@]+"${targs[@]}"} ${kargs[@]+"${kargs[@]}"} ${largs[@]+"${largs[@]}"} \
      -t "$tag" -f "$df" . >> "$log" 2>&1
    rc=$?
    [ "$rc" = 0 ] || rc=-$rc
  fi
  set -e
  tail -n 5 "$log"
  case "$rc" in
    0) ;;
    -*) echo "BUILD FAILED for $n (rc ${rc#-}); see $log" >&2; exit 12;;
    *) echo "CHECK FAILED for $n (stage check-$tg, rc $rc): the image is not built or recorded; see $log" >&2; exit 12;;
  esac
  bsec=$((SECONDS - tb))
  dig=$(eqc_image_digest "$tag") || { echo "BUILD of $n produced no readable digest for $tag (container image inspect)" >&2; exit 12; }
  {
    echo "EQ_IMAGE_NAME=$n"
    echo "EQ_RECORD_NAME=$(rn "$n")"
    echo "EQ_IMAGE_TAG=$tag"
    echo "EQ_IMAGE_DIGEST=$dig"
    echo "EQ_INPUTS_SHA256=$(inputs_hash "$n")"
    echo "EQ_TOOLS_SHA256=$tsha"
    echo "EQ_KEEP_EXTS=$keep"
    echo "EQ_KEEP_SUFFIX=$( [ -n "$keep" ] && echo "$SUFFIX" || true )"
    echo "EQ_BASE_REF=$bref"
    echo "EQ_BASE_ARM64=$barm"
    echo "EQ_BUILD_SECONDS=$bsec"
    echo "EQ_BUILD_NOCACHE=$NOCACHE"
    echo "EQ_BACKEND=container"
    echo "EQ_LIMITS=cpus=$EQ_CPUS memory=$EQ_MEMORY nproc=$EQ_NPROC user=$EQ_USER"
    echo "EQ_BUILT_AT=$(date -u +%FT%TZ)"
    echo "EQ_CONTAINER_VERSION=$(eqc --version 2>/dev/null | head -n 1)"
  } > "$EQ_STATE_DIR/images/$(rn "$n").env.tmp"
  mv "$EQ_STATE_DIR/images/$(rn "$n").env.tmp" "$EQ_STATE_DIR/images/$(rn "$n").env"
  echo "   digest $dig  build ${bsec}s"
done

# summary for the installer, doctor and the harness flags: which built image serves PF (Lean and, since the harness runs the PF
# oracle with `uv run`, Python: min-both; min-lean, which has no Python, only as the last resort) and CP/CR (min-py, else min-both).
# The images this run built come first, then older records. Values are TAG@sha256:DIGEST.
pick() { # candidates in order -> the first one this run built that has a record, else the first with a record
  local c
  for c in "$@"; do case " $NAMES " in *" $c "*) [ -f "$EQ_STATE_DIR/images/$c.env" ] && { echo "$c"; return 0; };; esac; done
  for c in "$@"; do [ -f "$EQ_STATE_DIR/images/$c.env" ] && { echo "$c"; return 0; }; done
  return 0
}
sel_lean=${EQ_SELECT_LEAN:-}; sel_py=${EQ_SELECT_PY:-}
[ -n "$sel_lean" ] || sel_lean=$(pick min-both min-lean)
[ -n "$sel_py" ] || sel_py=$(pick min-py min-both)
{
  echo "EQ_BACKEND=container"
  echo "EQ_ISOLATION=container"
  [ -z "$PROFILES" ] || echo "EQ_CONTAINER_PROFILES=$(printf '%s' "$PROFILES" | tr ' ' ',')"
  for n in $EQ_IMAGE_NAMES; do
    [ -f "$EQ_STATE_DIR/images/$n.env" ] || continue
    up=$(printf '%s' "$n" | tr '[:lower:]-' '[:upper:]_')
    echo "EQ_${up}_TAG=$(eq_img_get "$n" EQ_IMAGE_TAG)"
    echo "EQ_${up}_DIGEST=$(eq_img_get "$n" EQ_IMAGE_DIGEST)"
  done
  if [ -n "$sel_lean" ] && [ -f "$EQ_STATE_DIR/images/$sel_lean.env" ]; then
    echo "EQ_SELECT_LEAN=$sel_lean"
    echo "EQ_IMAGE=$(eq_pinned_ref "$sel_lean")"
    echo "EQ_CONTAINER_IMAGE_PF=$(eq_pinned_ref "$sel_lean")"
  fi
  if [ -n "$sel_py" ] && [ -f "$EQ_STATE_DIR/images/$sel_py.env" ]; then
    echo "EQ_SELECT_PY=$sel_py"
    echo "EQ_CONTAINER_IMAGE_CP=$(eq_pinned_ref "$sel_py")"
    echo "EQ_CONTAINER_IMAGE_CR=$(eq_pinned_ref "$sel_py")"
  fi
} > "$EQ_STATE_DIR/image.env.tmp" && chmod 600 "$EQ_STATE_DIR/image.env.tmp" && mv "$EQ_STATE_DIR/image.env.tmp" "$EQ_STATE_DIR/image.env"
echo
echo "BUILD: OK  (records: $EQ_STATE_DIR/images/*.env, summary: $EQ_STATE_DIR/image.env)"
exit 0
