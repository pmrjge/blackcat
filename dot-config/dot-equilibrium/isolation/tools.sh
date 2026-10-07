# shellcheck shell=bash
# tools.sh: reader for TOOLS.toml, the declarative tool manifest of the eq-docker images (source it; do not run it).
# Bash 3.2 (macOS) and the Debian builder's bash/mawk. No side effects at source time.
#
# TOOLS.toml uses a deliberately small TOML subset, so that this awk reader and a real TOML parser (python tomllib, in the
# tests) must agree on every table:  [[tool]] [[image]] [[profile]] tables; the first key of a table is  name = "..." ;
# every other key is  key = "string"  or  key = ["a", "b"]  (one line; no escapes, no quotes or spaces inside an array item).
# Anything else is a parse error (exit 3). The reader prints one TSV row per key:  table<TAB>name<TAB>key<TAB>value  where an
# array value is its items joined by one space.
#
# Functions (all read $TM_TSV, filled by tm_load):
#   tm_load [FILE]                    parse FILE (default: TOOLS.toml next to this file); 0 ok, 3 parse error (message on stderr)
#   tm_names TABLE                    names of the tables, file order
#   tm_get TABLE NAME KEY             value (empty when absent)
#   tm_has TABLE NAME                 exit 0 when the table exists
#   tm_keys TABLE NAME                keys of one table
#   tm_profile_images "p1 p2"         image names of the profiles, union, order of the profile list then of the images
#   tm_expand_profiles "a,b all"      validated profile names (`all` = every profile not marked explicit = "yes"), once each
#   tm_set FILE TABLE NAME KEY VALUE  rewrite one string value in place (build.sh --resolve-tools --write-pin uses it)
#   tm_image_hash IMAGE               sha256 of the canonical text of the image row and of every tool row it lists (the label
#                                     eq.tools.sha256 build.sh puts on the image; verify-tools.sh compares it)
#   tm_sha256_stdin                   sha256 of stdin
TM_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)
TM_FILE=""
TM_TSV=""

tm_sha256_stdin() {
  if command -v shasum >/dev/null 2>&1; then shasum -a 256 | cut -d' ' -f1
  elif command -v sha256sum >/dev/null 2>&1; then sha256sum | cut -d' ' -f1
  else echo "tools.sh: neither shasum nor sha256sum found" >&2; return 1; fi
}

tm_awk_program() {
  cat <<'AWK'
function fail(msg) { printf "%s:%d: %s\n", FILENAME, NR, msg > "/dev/stderr"; bad = 1; exit 3 }
function strip(s) { sub(/^[ \t\r]+/, "", s); sub(/[ \t\r]+$/, "", s); return s }
# cut a trailing comment that starts outside quotes
function uncomment(s,    i, c, q, out) {
  q = 0; out = ""
  for (i = 1; i <= length(s); i++) {
    c = substr(s, i, 1)
    if (c == "\"") q = !q
    if (c == "#" && !q) break
    out = out c
  }
  return out
}
function str_value(s) {            # "..." with no quote or backslash inside
  if (substr(s, 1, 1) != "\"" || substr(s, length(s), 1) != "\"" || length(s) < 2) fail("value is not a quoted string: " s)
  s = substr(s, 2, length(s) - 2)
  if (index(s, "\"") || index(s, "\\")) fail("quote or backslash inside a string")
  if (index(s, "\t")) fail("tab inside a string")
  return s
}
function arr_value(s,    inner, n, parts, i, item, out) {
  inner = strip(substr(s, 2, length(s) - 2))
  if (inner == "") return ""
  n = split(inner, parts, ",")
  out = ""
  for (i = 1; i <= n; i++) {
    item = strip(parts[i])
    if (item == "" && i == n) continue            # trailing comma
    item = str_value(item)
    if (index(item, " ")) fail("space inside an array item: " item)
    out = out (out == "" ? "" : " ") item
  }
  return out
}
BEGIN { table = ""; name = "" }
{
  line = strip(uncomment($0))
  if (line == "") next
  if (line ~ /^\[\[[a-z]+\]\]$/) { table = substr(line, 3, length(line) - 4); name = ""; next }
  if (line ~ /^\[/) fail("only [[table]] arrays of tables are supported")
  if (table == "") fail("key outside a [[table]]")
  eq = index(line, "=")
  if (eq == 0) fail("not a key = value line")
  key = strip(substr(line, 1, eq - 1)); rest = strip(substr(line, eq + 1))
  if (key !~ /^[a-z_][a-z0-9_]*$/) fail("bad key: " key)
  if (substr(rest, 1, 1) == "[") {
    if (substr(rest, length(rest), 1) != "]") fail("array must close on the same line")
    val = arr_value(rest)
  } else val = str_value(rest)
  if (name == "") {
    if (key != "name") fail("the first key of a table must be name")
    name = val
    if (name !~ /^[a-z0-9][a-z0-9_.-]*$/) fail("bad table name: " name)
  } else if (key == "name") fail("duplicate name key")
  seen = table SUBSEP name SUBSEP key
  if (seen in have) fail("duplicate key " key " in " table " " name)
  have[seen] = 1
  printf "%s\t%s\t%s\t%s\n", table, name, key, val
}
AWK
}

tm_load() {
  TM_FILE=${1:-$TM_DIR/TOOLS.toml}
  [ -f "$TM_FILE" ] || { echo "tools.sh: $TM_FILE not found" >&2; return 3; }
  TM_TSV=$(awk "$(tm_awk_program)" "$TM_FILE") || return 3
}

tm_names() { printf '%s\n' "$TM_TSV" | awk -F'\t' -v t="$1" '$1 == t && $3 == "name" { print $2 }'; }
tm_get() { printf '%s\n' "$TM_TSV" | awk -F'\t' -v t="$1" -v n="$2" -v k="$3" '$1 == t && $2 == n && $3 == k { print $4; exit }'; }
tm_has() { [ -n "$(printf '%s\n' "$TM_TSV" | awk -F'\t' -v t="$1" -v n="$2" '$1 == t && $2 == n && $3 == "name" { print "y"; exit }')" ]; }
tm_keys() { printf '%s\n' "$TM_TSV" | awk -F'\t' -v t="$1" -v n="$2" '$1 == t && $2 == n { print $3 }'; }

tm_profile_images() {
  local p out="" i
  for p in $1; do
    tm_has profile "$p" || { echo "tools.sh: unknown profile: $p" >&2; return 2; }
    for i in $(tm_get profile "$p" images); do
      case " $out " in *" $i "*) ;; *) out="$out $i";; esac
    done
  done
  # shellcheck disable=SC2086
  printf '%s\n' $out
}

tm_expand_profiles() { # "core,db all" -> profile names, once each; `all` = every profile whose explicit key is not "yes"
  local out="" p q res=""
  for p in $(printf '%s' "$1" | tr ',' ' '); do
    if [ "$p" = all ]; then
      for q in $(tm_names profile); do [ "$(tm_get profile "$q" explicit)" = yes ] || out="$out $q"; done
    else
      tm_has profile "$p" || { echo "unknown profile: $p (known: $(tm_names profile | tr '\n' ' ')and all)" >&2; return 2; }
      out="$out $p"
    fi
  done
  for p in $out; do case " $res " in *" $p "*) ;; *) res="$res $p";; esac; done
  # shellcheck disable=SC2086
  printf '%s\n' $res
}

tm_set() { # FILE TABLE NAME KEY VALUE: rewrite one string value of one table in place (temp file + rename); 1 when the key is absent
  local f=$1 tmp
  tmp="$f.tmp.$$"
  awk -v tb="$2" -v nm="$3" -v ky="$4" -v val="$5" '
    /^\[\[[a-z]+\]\]$/ { cur = substr($0, 3, length($0) - 4); name = ""; print; next }
    cur == tb && name == "" && $0 ~ /^name = "/ { s = $0; sub(/^name = "/, "", s); sub(/".*$/, "", s); name = s }
    cur == tb && name == nm && $0 ~ ("^" ky " = ") { print ky " = \"" val "\""; hit = 1; next }
    { print }
    END { exit hit ? 0 : 1 }' "$f" > "$tmp" || { rm -f "$tmp"; return 1; }
  mv "$tmp" "$f"
}

tm_image_hash() {
  local img=$1 t
  tm_has image "$img" || return 2
  {
    printf '%s\n' "$TM_TSV" | awk -F'\t' -v n="$img" '$1 == "image" && $2 == n'
    for t in $(tm_get image "$img" tools); do
      printf '%s\n' "$TM_TSV" | awk -F'\t' -v n="$t" '$1 == "tool" && $2 == n'
    done
  } | LC_ALL=C sort | tm_sha256_stdin
}
