"""The tools manifest and the extension images of lib/eq-docker (X2, X3, X4 of the scope extensions): TOOLS.toml read by a real TOML
parser and by the awk reader the scripts use (they must agree), the static allowlist rules of verify-tools.sh, its --images /
--inspect / --smoke checks against a fake daemon, `build.sh --profiles` (labels, records, placeholders, idempotence, the
--resolve-tools pin workflow), the bounded wait for the Docker daemon, `eq-docker.sh install --profiles`, the probe.d hook
contract of probe.sh and the two hooks this suite can prove (tools manifest, internal network), and Dockerfile.toolchains against the
manifest (ENV, stages, USER, no shell-side instructions in a final stage).

Hermetic: fake `docker` on PATH (tests/fake-docker/docker), see conftest.py. What only a real daemon can prove (that a built image really
contains these files, that the smoke commands run, that the closure resolves) is a user step in RUNBOOK_MINIMAL.md; what is proved here is
that the scripts ask for exactly that, that a missing or mismatching answer is a failure and that nothing is invented or unpinned.

Run: uv run --with pytest --with pyyaml pytest -q -p no:cacheprovider tests/test_eq_docker_toolchains.py
"""
import re
import subprocess
import time

import pytest

from conftest import (BASH, IMAGE_ID_A, IMAGE_ID_B, IMAGE_TAGS, LIB, fake_hex, fixture_lib, image_label, load_manifest, san,
                      set_image, set_tool, tsv_via_bash, vals)

TF = LIB / "TOOLS.toml"
pytestmark = pytest.mark.skipif(not TF.exists(), reason="no TOOLS.toml in the directory under test")

TAG = "eq-lean:4.34.1-arm64"
TAG_PY = "eq-py:test"
ALL_PROFILES = ("core", "node", "rust", "go", "julia", "haskell", "jvm", "db", "mongo", "candidates")


def by_name(entries):
    return {e["name"]: e for e in entries}


def manifest():
    return load_manifest(TF)


def vt(env, lib, *args, **kw):
    return env.run("verify-tools.sh", *args, lib=lib, **kw)


def problems(r):
    return [ln for ln in r.stdout.splitlines() if ln.startswith("PROBLEM")]


def mutated(tmp_path, *, tools=(), images=(), fill_all=False, pin_distro=True):
    """A fixture copy whose manifest is edited: tools = [(name, {key: value})], images likewise."""
    lib = fixture_lib(tmp_path, fill_all=fill_all, pin_distro=pin_distro)
    for name, kv in tools:
        set_tool(lib / "TOOLS.toml", name, **kv)
    for name, kv in images:
        set_image(lib / "TOOLS.toml", name, **kv)
    return lib


# =========================================================================================== the manifest and its two readers
def toml_rows(path):
    rows = []
    for table in ("tool", "image", "profile"):
        for entry in load_manifest(path).get(table, []):
            for k, v in entry.items():
                rows.append((table, entry["name"], k, " ".join(v) if isinstance(v, list) else v))
    return rows


def test_the_awk_reader_and_tomllib_agree_on_the_shipped_manifest():
    assert sorted(tsv_via_bash(LIB, TF)) == sorted(toml_rows(TF))


EDGE = '''# a comment, then a table
[[tool]]
name = "t1"          # trailing comment
version = "1.0"
url = "https://example.invalid/a%2Bb/{version}/x-{version}.tar.gz"
note = "has a # inside the quotes"
empty = []
two = ["a", "b"]
trail = ["x", "y",]
spaced   =   "v"

[[tool]]
name = "t2"
x = "y"
[[image]]
name = "i-1"
tools = ["t1"]
[[profile]]
name = "p.1"
images = ["i-1"]
'''


def test_the_awk_reader_and_tomllib_agree_on_the_edge_cases(tmp_path):
    f = tmp_path / "edge.toml"
    f.write_text(EDGE)
    assert sorted(tsv_via_bash(LIB, f)) == sorted(toml_rows(f))


@pytest.mark.parametrize("text", [
    'a = "b"\n',                                              # key outside a table
    '[[tool]]\nname = bare\n',                                # unquoted value
    '[[tool]]\nname = "x"\nk = ["a b"]\n',                    # space inside an array item
    '[[tool]]\nname = "x"\nk = ["a",\n"b"]\n',                # array not closed on its line
    '[[tool]]\nname = "x"\nk = "1"\nk = "2"\n',               # duplicate key
    '[[tool]]\nk = "1"\n',                                    # the first key must be name
    '[tool]\nname = "x"\n',                                   # only arrays of tables
    '[[tool]]\nname = "x"\nk = "a\\nb"\n',                    # a backslash
    '[[tool]]\nname = "X Y"\n',                               # bad table name
    '[[tool]]\nname = "x"\nk = 5\n',                          # not a string
    '[[tool]]\nname = "x"\nK = "5"\n',                        # bad key
])
def test_the_awk_reader_refuses_what_the_subset_does_not_allow(tmp_path, text):
    f = tmp_path / "bad.toml"
    f.write_text(text)
    r = subprocess.run([BASH, "-c", f'. "{LIB}/tools.sh"; tm_load "{f}"'], capture_output=True, text=True, check=False)
    assert r.returncode == 3, (text, r.stderr)


def test_tm_set_rewrites_one_value_in_place_and_nothing_else(tmp_path):
    f = tmp_path / "t.toml"
    f.write_text(EDGE)
    r = subprocess.run([BASH, "-c", f'. "{LIB}/tools.sh"; tm_set "{f}" tool t1 version 2.5 && tm_set "{f}" tool t2 x z'],
                       capture_output=True, text=True, check=False)
    assert r.returncode == 0, r.stderr
    a, b = toml_rows(f), [x for x in toml_rows(f)]
    d = {(t, n, k): v for t, n, k, v in a}
    assert d[("tool", "t1", "version")] == "2.5" and d[("tool", "t2", "x")] == "z" and d[("tool", "t1", "url")].startswith("https://")
    assert len(a) == len(toml_rows(tmp_path / "t.toml")) == len(b)
    miss = subprocess.run([BASH, "-c", f'. "{LIB}/tools.sh"; tm_set "{f}" tool t1 nokey v'], capture_output=True, text=True, check=False)
    assert miss.returncode == 1


def test_image_hash_covers_the_image_and_each_of_its_tools(tmp_path):
    lib = fixture_lib(tmp_path)
    base = image_label(lib, lib / "TOOLS.toml", "tc-node")
    assert re.fullmatch(r"[0-9a-f]{64}", base)
    set_tool(lib / "TOOLS.toml", "node", sha256="0" * 64)
    assert image_label(lib, lib / "TOOLS.toml", "tc-node") != base
    assert image_label(lib, lib / "TOOLS.toml", "tc-go") == image_label(LIB, TF, "tc-go")      # another image's tools: unchanged
    set_image(lib / "TOOLS.toml", "tc-node", service="node2")
    assert image_label(lib, lib / "TOOLS.toml", "tc-node") != base


# ======================================================================================= what the shipped manifest says (static)
def test_every_pin_is_hex_or_an_explicit_placeholder_and_every_url_is_https_apt_or_in_repo():
    m = manifest()
    for t in m["tool"]:
        assert re.fullmatch(r"[0-9a-f]{64}|PLACEHOLDER|n/a", t["sha256"]), t["name"]
        assert t["sha256"] != "n/a" or t["role"] == "build-only", t["name"]
        assert t["url"] == "PLACEHOLDER" or re.match(r"https://[^@/]+/|apt:[a-z0-9.+-]+$|file:(tc|minimal)/", t["url"]), t["name"]
        assert not t["url"].startswith("http://") and "@" not in t["url"].split("://", 1)[-1].split("/", 1)[0], t["name"]
        assert t["checksum_source"] and t["licence"] and t["linkage"] and t["provenance"], t["name"]


def test_upstream_values_are_the_ones_read_from_upstream_on_2026_10_05():
    # TOOLCHAINS.md (eq-toolchains/): sha256 copied from the checksum file or metadata named in each entry's checksum_source. A drift
    # here is an edit that did not come from upstream; a legitimate re-pin updates this table and the entry together.
    want = {
        "node": ("24.21.0", "6ad1325edbdb5649c379b75a237147a666c95d4f9ae8d340fef2d1575d289ad2"),
        "rust": ("1.99.0", "5a30ce742be0835d9b23fc862db5cbbbc71464e1c9b1fca22917e10e4ba32a92"),
        "go": ("1.27.1", "3450b45a3f9ee8568792736a5c5e70a1f2e9b36c35a8f74958c03e51d7d92bec"),
        "julia": ("1.13.1", "78341862e24734ea1c2fa8795183c52627c23a99aba5aa1d0ec840edecec5ce0"),
        "ghc": ("9.14.1", "6aa27a377451851c851eefdd869e8f5a9217b02ce66c6ca9b418b72efee28427"),
        "cabal": ("3.18.1.0", "b8333291622c0354d72adec64ccb19e13563264bae2c15c9e6657e7f9c1486e8"),
        "jdk": ("25.0.4.1", "69df11a02cfa3ef7d7ca645e03edce6778ec090e100f6ae2b42097865730ac52"),
        "postgresql": ("18.6", "555610c24d53e4316da5b7d3fc25c279d96856d5e0e23ee308c328c5fa881d9f"),
        "mongodb": ("9.0.2", "0f823dcbe151af778e6e7a1ea0acbd9985bcf98ea3989468d30bcb1bde77c72f"),
    }
    tools = by_name(manifest()["tool"])
    for name, (ver, sha) in want.items():
        assert (tools[name]["version"], tools[name]["sha256"]) == (ver, sha), name


def test_tools_without_an_official_arm64_binary_are_built_from_source_with_a_pinned_recipe_or_marked_distro_package():
    tools = by_name(manifest()["tool"])
    assert tools["postgresql"]["provenance"] == "built-from-source"          # postgresql.org: no generic Linux server binary
    assert tools["postgresql"]["recipe"] == "tc/build-postgresql.sh" and tools["postgresql"]["url"].endswith(".tar.bz2")
    for name in ("busybox", "bash", "perl", "jq", "git"):                      # INTERIM (pending user decision): distro packages
        assert tools[name]["provenance"] == "distro-package" and tools[name]["url"].startswith("apt:"), name
    for t in tools.values():
        if t["provenance"] == "built-from-source":
            assert t.get("recipe", "").startswith("tc/") and re.fullmatch(r"[0-9a-f]{64}", t.get("recipe_sha256", "")), t["name"]
        if t["provenance"] == "prebuilt-upstream" and t["url"] != "PLACEHOLDER":
            assert t["url"].startswith("https://"), t["name"]


def test_every_file_a_tool_lists_is_under_its_dest_and_dest_is_under_opt_or_usr():
    for t in manifest()["tool"]:
        if t["role"] == "build-only":
            continue
        assert re.match(r"/(opt|usr)/", t["dest"]), t["name"]
        for f in t["files"]:
            assert f == t["dest"] or f.startswith(t["dest"].rstrip("/") + "/"), (t["name"], f)
        for p in t.get("prune", []):
            assert not p.startswith("/") and ".." not in p, (t["name"], p)
        for e in t.get("env", []):
            assert re.fullmatch(r"[A-Z_]+=[^\s]*", e) and not re.search(r"token|secret|passw|credential|api_?key|anthropic|aws_|github", e, re.I), e


def test_core_is_the_minimum_the_item_classes_need_and_everything_else_is_extension():
    m = manifest()
    tools, images, profiles = by_name(m["tool"]), by_name(m["image"]), by_name(m["profile"])
    core = [images[i] for i in profiles["core"]["images"]]
    assert {i["name"] for i in core} == {"min-both", "min-py"}
    assert {c for i in core for c in i["classes"]} == {"PF", "CP", "CR"}          # ES RS DS OE run no model-written code
    for i in core:
        for t in i["tools"]:
            assert "EXT" not in tools[t]["classes"] or set(i["classes"]) <= set(tools[t]["classes"]), (i["name"], t)
    # PF needs lean + uv + python (the PF oracle is `uv run --script oracle.py` in the PF image) + bash and perl (check_lean.sh)
    assert {"lean", "uv", "python", "bash", "perl", "busybox", "lake-shim"} <= set(images["min-both"]["tools"])
    assert {"uv", "python", "bash", "busybox"} <= set(images["min-py"]["tools"]) and "lean" not in images["min-py"]["tools"]
    assert profiles["core"].get("explicit") == "no"
    for name, p in profiles.items():
        if name not in ("core", "mongo", "candidates"):
            assert p["explicit"] == "no" and all(images[i]["classes"] == ["EXT"] for i in p["images"]), name
    for name in ("mongo", "candidates"):
        assert profiles[name]["explicit"] == "yes"
    for i in m["image"]:
        assert not ({"ES", "RS", "DS", "OE"} & set(i["classes"])), i["name"]


def test_no_network_client_or_package_manager_is_in_any_image_and_applets_are_few():
    m = manifest()
    tools, images = by_name(m["tool"]), by_name(m["image"])
    banned = {"curl", "wget", "ssh", "docker", "sudo", "apt", "pip", "npm", "git", "make", "gcc", "nc"}
    for i in m["image"]:
        assert not banned & set(i["tools"]), i["name"]
        for t in i["tools"]:
            assert tools[t]["role"] != "build-only", (i["name"], t)
        assert set(i.get("applets", [])) <= {"sh", "rm", "sleep", "ls"}, i["name"]
        if i["kind"] != "server":
            assert "applets" not in i
    assert tools["git"]["role"] == "build-only" and not any("git" in i["tools"] for i in m["image"])
    assert images["tc-pg"]["base"] == images["tc-mongo"]["base"] == "eq-base"


def test_mongodb_is_explicit_only_and_the_sspl_is_recorded():
    m = manifest()
    tools, profiles = by_name(m["tool"]), by_name(m["profile"])
    assert profiles["mongo"]["explicit"] == "yes"
    assert tools["mongodb"]["licence"] == "SSPL-1.0" and "SSPL" in tools["mongodb"]["notes"] and "ARMv8.2-A" in tools["mongodb"]["notes"]
    assert "ubuntu2404" in tools["mongodb"]["url"] and "Debian" in tools["mongodb"]["notes"]


def test_the_shipped_manifest_never_invents_a_value_it_does_not_know():
    # the values TOOLCHAINS.md did not read stay PLACEHOLDER (scala3 distribution, mongosh); the distro packages wait for
    # `build.sh --resolve-tools --write-pin` (trust on first use)
    tools = by_name(manifest()["tool"])
    for name in ("scala3", "mongosh"):
        assert tools[name]["sha256"] == "PLACEHOLDER" and tools[name]["version"] == "PLACEHOLDER", name
    for name in ("busybox", "bash", "perl", "jq"):
        assert tools[name]["sha256"] == "PLACEHOLDER" and tools[name]["version"] == "PLACEHOLDER", name


# ============================================================================================ verify-tools.sh --manifest
@pytest.mark.parametrize("profile", ["node", "rust", "go", "julia", "haskell"])
def test_fully_pinned_profiles_validate_as_shipped(env, profile):
    r = vt(env, LIB, "--manifest", "--profiles", profile)
    assert r.returncode == 0 and "manifest OK" in r.stdout, r.stdout + r.stderr


@pytest.mark.parametrize("profile,names", [("core", ["busybox", "bash", "perl", "jq"]), ("jvm", ["scala3"]), ("mongo", ["mongosh"]),
                                           ("db", ["busybox"])])
def test_a_placeholder_in_a_selected_profile_is_pending_exit_13(env, profile, names):
    r = vt(env, LIB, "--manifest", "--profiles", profile)
    assert r.returncode == 13 and "TOOLS: PENDING" in r.stdout, r.stdout + r.stderr
    for n in names:
        assert f"PENDING tool {n}:" in r.stdout, (n, r.stdout)
    listed = vt(env, LIB, "--manifest", "--profiles", profile, "--allow-placeholder")
    assert listed.returncode == 0 and "PENDING" in listed.stdout


def test_a_placeholder_outside_the_selection_does_not_block(env):
    r = vt(env, LIB, "--manifest", "--profiles", "node")             # scala3 and the distro tools are placeholders, but not in node
    assert r.returncode == 0 and "PENDING" not in r.stdout


def test_all_means_every_profile_that_is_not_explicit(env, tmp_path):
    lib = fixture_lib(tmp_path, fill_all=True)
    r = vt(env, lib, "--manifest", "--profiles", "all")
    assert r.returncode == 0, r.stdout
    imgs = re.search(r"images: (.*)\)", r.stdout).group(1).split()
    assert "tc-mongo" not in imgs and "min-lean" not in imgs and {"min-both", "min-py", "tc-pg", "tc-jvm"} <= set(imgs)
    r2 = vt(env, lib, "--manifest", "--profiles", "all,mongo")
    assert "tc-mongo" in r2.stdout and r2.returncode == 0


def test_unknown_profile_and_unknown_option_are_usage_errors(env):
    assert vt(env, LIB, "--profiles", "nosuch").returncode == 2
    assert vt(env, LIB, "--bogus").returncode == 2
    assert vt(env, LIB, "--deep").returncode == 2                     # --deep needs --images
    assert vt(env, LIB, "--select", "no-such-image").returncode == 2


MUTATIONS = [
    ("class_not_allowed", dict(images=[("tc-node", {"classes": ["PF"]})]), "class PF may not have tool node"),
    ("profile_not_allowed", dict(tools=[("node", {"profiles": ["go"]})]), "not allowed in profile node"),
    ("bad_sha", dict(tools=[("node", {"sha256": "abc123"})]), "not 64 lowercase hex"),
    ("upper_case_sha", dict(tools=[("node", {"sha256": "A" * 64})]), "not 64 lowercase hex"),
    ("http_url", dict(tools=[("node", {"url": "http://nodejs.org/x.tar.xz"})]), "url must be https://"),
    ("url_credentials", dict(tools=[("node", {"url": "https://user:pw@nodejs.org/x.tar.xz"})]), "credentials in url"),
    ("apt_url_needs_distro_package", dict(tools=[("node", {"url": "apt:node"})]), "needs provenance distro-package"),
    ("https_url_needs_upstream_or_source", dict(tools=[("node", {"provenance": "in-repo"})]), "needs provenance prebuilt-upstream"),
    ("built_from_source_needs_recipe", dict(tools=[("postgresql", {"recipe": ""})]), "built-from-source needs a recipe"),
    ("recipe_needs_hash", dict(tools=[("postgresql", {"recipe_sha256": "short"})]), "recipe_sha256"),
    ("unknown_class_on_tool", dict(tools=[("uv", {"classes": ["ZZ"]})]), "unknown class ZZ"),
    ("unknown_profile_on_tool", dict(tools=[("uv", {"profiles": ["nosuch"]})]), "unknown profile nosuch"),
    ("unknown_role", dict(tools=[("uv", {"role": "root"})]), "role 'root'"),
    ("unknown_linkage", dict(tools=[("node", {"linkage": "weird"})]), "linkage 'weird'"),
    ("unknown_archive", dict(tools=[("node", {"archive": "rar"})]), "archive 'rar'"),
    ("n_a_only_for_build_only", dict(tools=[("node", {"sha256": "n/a"})]), "n/a is only for role build-only"),
    ("image_lists_build_only_tool", dict(images=[("min-both", {"tools": ["lean", "uv", "python", "git"]})]), "lists build-only tool git"),
    ("image_lists_unknown_tool", dict(images=[("tc-node", {"tools": ["node", "nosuchtool"]})]), "lists unknown tool nosuchtool"),
    ("image_kind", dict(images=[("tc-node", {"kind": "vm"})]), "kind must be one of"),
    ("profile_lists_unknown_image", None, "unknown image"),
]


@pytest.mark.parametrize("name,spec,message", [m for m in MUTATIONS if m[1] is not None], ids=[m[0] for m in MUTATIONS if m[1] is not None])
def test_the_static_allowlist_rules_reject(env, tmp_path, name, spec, message):
    lib = mutated(tmp_path, fill_all=True, **spec)
    r = vt(env, lib, "--manifest", "--profiles", "all")
    assert r.returncode == 2 and any(message in p for p in problems(r)), (name, r.stdout)
    assert "TOOLS: INVALID" in r.stdout


def test_a_profile_may_not_list_an_unknown_image(env, tmp_path):
    lib = fixture_lib(tmp_path, fill_all=True)
    p = lib / "TOOLS.toml"
    p.write_text(p.read_text().replace('images = ["tc-node"]', 'images = ["tc-node", "tc-nowhere"]', 1))
    r = vt(env, lib, "--manifest", "--profiles", "node")
    assert r.returncode == 2 and any("unknown image tc-nowhere" in x for x in problems(r)), r.stdout


def test_an_in_repo_file_edited_without_repinning_is_rejected(env, tmp_path):
    lib = fixture_lib(tmp_path, fill_all=True)
    with open(lib / "tc" / "entry-pg.sh", "a") as f:
        f.write("# tampered\n")
    r = vt(env, lib, "--manifest", "--profiles", "db")
    assert r.returncode == 2 and any("entry-pg" in x and "does not hash" in x for x in problems(r)), r.stdout


def test_a_recipe_edited_without_repinning_is_rejected(env, tmp_path):
    lib = fixture_lib(tmp_path, fill_all=True)
    for rec in ("build-postgresql.sh", "install-rust.sh", "install-ghc.sh"):
        with open(lib / "tc" / rec, "a") as f:
            f.write("# tampered\n")
    r = vt(env, lib, "--manifest", "--profiles", "db,rust,haskell")
    msgs = problems(r)
    assert r.returncode == 2 and sum("does not hash to recipe_sha256" in x for x in msgs) == 3, r.stdout


def test_a_missing_recipe_file_is_rejected(env, tmp_path):
    lib = fixture_lib(tmp_path, fill_all=True)
    (lib / "tc" / "install-rust.sh").unlink()
    r = vt(env, lib, "--manifest", "--profiles", "rust")
    assert r.returncode == 2 and any("recipe file tc/install-rust.sh not found" in x for x in problems(r))


def test_a_recipe_outside_tc_is_rejected(env, tmp_path):
    lib = mutated(tmp_path, fill_all=True, tools=[("rust", {"recipe": "../evil.sh"})])
    r = vt(env, lib, "--manifest", "--profiles", "rust")
    assert r.returncode == 2 and any("recipe must be tc/" in x for x in problems(r))


def test_pins_and_manifest_must_agree_for_the_four_tools_both_describe(env, tmp_path):
    lib = fixture_lib(tmp_path, fill_all=True)
    pins = (lib / "PINS").read_text()
    for key in ("LEAN_SHA256", "UV_SHA256", "PYTHON_SHA256", "BUSYBOX_SHA256", "UV_VERSION", "PBS_TAG"):
        p = lib / "PINS"
        p.write_text(re.sub(rf"^{key}=.*$", f"{key}=" + ("9" * 64 if "SHA" in key else "9.9.9"), pins, flags=re.M))
        r = vt(env, lib, "--manifest", "--profiles", "core")
        assert r.returncode == 2 and any("differs from PINS" in x for x in problems(r)), (key, r.stdout)
    p.write_text(pins)
    assert vt(env, lib, "--manifest", "--profiles", "core").returncode == 0


def test_a_duplicate_tool_table_is_an_invalid_manifest(env, tmp_path):
    lib = fixture_lib(tmp_path, fill_all=True)
    p = lib / "TOOLS.toml"
    p.write_text(p.read_text() + '\n[[tool]]\nname = "node"\nversion = "1"\n')
    r = vt(env, lib, "--manifest", "--profiles", "node")
    assert r.returncode == 2


# ============================================================================== verify-tools.sh --images / --inspect / --smoke
@pytest.fixture
def node_lib(tmp_path):
    return fixture_lib(tmp_path, fill_all=True)


def images_run(env, lib, *extra, profile="node", **kw):
    return vt(env, lib, "--images", "--profiles", profile, *extra, **kw)


def test_images_ok_when_record_label_lock_and_files_all_match(env, node_lib):
    env.docker()
    env.built_image(node_lib, "tc-node")
    r = images_run(env, node_lib, "--deep")
    assert r.returncode == 0 and "IMAGE tc-node" in r.stdout and "TOOLS: images OK" in r.stdout, r.stdout + r.stderr
    assert re.search(r"IMAGE tc-node\s+ok\s+sha256:", r.stdout)
    assert not [a for a in env.runs()], "verification starts no container: docker create + docker cp only"
    assert all(a[0] != "start" for a in env.argv_log())


def test_images_missing_without_a_build_record(env, node_lib):
    env.docker()
    r = images_run(env, node_lib)
    assert r.returncode == 11 and "MISSING" in r.stdout and "never built here" in r.stdout


def test_images_missing_when_the_daemon_lost_the_image(env, node_lib):
    env.docker()
    env.built_image(node_lib, "tc-node")
    (env.dstate / "images").write_text("")
    r = images_run(env, node_lib)
    assert r.returncode == 11 and "MISSING" in r.stdout and "not present" in r.stdout


def test_images_mismatch_when_the_daemon_id_is_not_the_recorded_one(env, node_lib):
    env.docker()
    tag, _ = env.built_image(node_lib, "tc-node")
    (env.dstate / "images").write_text(f"{tag}\t{IMAGE_ID_B}\t1\n")
    r = images_run(env, node_lib)
    assert r.returncode == 11 and "MISMATCH" in r.stdout


def test_images_stale_when_the_manifest_entry_changed_after_the_build(env, node_lib):
    env.docker()
    env.built_image(node_lib, "tc-node")
    set_tool(node_lib / "TOOLS.toml", "node", version="24.99.0")       # an edited entry: the label no longer matches
    r = images_run(env, node_lib)
    assert r.returncode == 11 and "STALE" in r.stdout and "rebuild" in r.stdout


def test_images_stale_when_the_image_has_no_tools_label(env, node_lib):
    env.docker()
    env.built_image(node_lib, "tc-node", label=False)
    r = images_run(env, node_lib)
    assert r.returncode == 11 and "STALE" in r.stdout and "none" in r.stdout


def test_images_stale_when_the_label_is_another_hash(env, node_lib):
    env.docker()
    env.built_image(node_lib, "tc-node", label="f" * 64)
    assert "STALE" in images_run(env, node_lib).stdout


def test_images_lock_missing(env, node_lib):
    env.docker()
    env.built_image(node_lib, "tc-node", lock=False)
    r = images_run(env, node_lib)
    assert r.returncode == 11 and "LOCK" in r.stdout and "no /opt/eq/TOOLS.lock" in r.stdout


def test_images_lock_disagrees_with_the_manifest_pin(env, node_lib):
    env.docker()
    tag, _ = env.built_image(node_lib, "tc-node")
    lock = env.dstate / f"tree.{san(tag)}" / "opt" / "eq" / "TOOLS.lock"
    sha = by_name(load_manifest(node_lib / "TOOLS.toml")["tool"])["node"]["sha256"]
    lock.write_text(lock.read_text().replace(sha, "0" * 64))
    r = images_run(env, node_lib)
    assert r.returncode == 11 and "LOCK" in r.stdout and "differs from the manifest" in r.stdout


def test_images_lock_lists_a_tool_the_manifest_does_not_give_this_image(env, node_lib):
    env.docker()
    env.built_image(node_lib, "tc-node", undeclared="curl")           # "forged verdict via an added tool"
    r = images_run(env, node_lib)
    assert r.returncode == 11 and "UNDECLARED" in r.stdout and "curl" in r.stdout


def test_images_deep_notices_a_tool_file_that_does_not_hash_to_the_lock(env, node_lib):
    env.docker()
    env.built_image(node_lib, "tc-node", tamper=("/opt/node/bin/node", "#!/bin/sh\necho owned\n"))
    shallow = images_run(env, node_lib)
    assert shallow.returncode == 0, "without --deep only the lock is read (an in-image lie would pass): that is why --deep exists"
    deep = images_run(env, node_lib, "--deep")
    assert deep.returncode == 11 and "DEEP" in deep.stdout and "/opt/node/bin/node" in deep.stdout


def test_images_a_placeholder_is_never_a_match(env, tmp_path):
    lib = fixture_lib(tmp_path)                                         # tc-jvm: scala3 is still PLACEHOLDER
    env.docker()
    env.built_image(lib, "tc-jvm")
    r = vt(env, lib, "--images", "--profiles", "jvm")
    assert r.returncode == 13 and "PENDING" in r.stdout                  # the manifest check stops it first


def test_images_without_docker_is_exit_10(env, node_lib):
    r = images_run(env, node_lib)
    assert r.returncode == 10


def test_images_checks_every_image_of_every_selected_profile(env, node_lib):
    env.docker()
    env.built_image(node_lib, "tc-node")
    r = vt(env, node_lib, "--images", "--profiles", "node,go")
    assert r.returncode == 11 and "IMAGE tc-go" in r.stdout and "MISSING" in r.stdout and re.search(r"IMAGE tc-node\s+ok", r.stdout)


@pytest.mark.parametrize("what,content,message", [
    ("user", "root", "not unprivileged"), ("user", "0:0", "not unprivileged"), ("user", "", "not unprivileged"),
    ("expose", "1", "EXPOSEd port"), ("volumes", "1", "VOLUME"), ("entrypoint", "[/bin/sh]", "ENTRYPOINT"),
    ("healthcheck", "[CMD true]", "HEALTHCHECK"),
    ("env", "PATH=/opt/node/bin\nAWS_SECRET_ACCESS_KEY=x\n", "secret-like"),
    ("env", "PATH=/opt/node/bin\nGITHUB_TOKEN=x\n", "secret-like"),
    ("env", "PATH=/opt/node/bin:/home/me/bin\n", "PATH leaves /opt and /usr"),
    ("env", "PATH=/opt/node/bin:.\n", "PATH leaves /opt and /usr"),
    ("env", "PATH=/opt/node/bin:/tmp/x y\n", "odd characters"),
])
def test_inspect_rejects(env, node_lib, what, content, message):
    env.docker()
    tag, _ = env.built_image(node_lib, "tc-node")
    (env.dstate / f"{what}.{san(tag)}").write_text(content + ("\n" if what != "env" and content else ""))
    r = vt(env, node_lib, "--inspect", "--profiles", "node")
    assert r.returncode == 11 and "FAIL" in r.stdout and message in r.stdout, r.stdout + r.stderr


def test_inspect_accepts_a_clean_image_and_starts_nothing(env, node_lib):
    env.docker()
    tag, _ = env.built_image(node_lib, "tc-node")
    (env.dstate / f"env.{san(tag)}").write_text("PATH=/opt/node/bin\nLANG=C.UTF-8\nHOME=/tmp\n")
    r = vt(env, node_lib, "--inspect", "--profiles", "node")
    assert r.returncode == 0 and "TOOLS: inspect OK" in r.stdout and env.runs() == []
    missing = vt(env, node_lib, "--inspect", "--profiles", "go")
    assert missing.returncode == 11 and "MISSING" in missing.stdout


def test_smoke_runs_each_tools_argv_under_the_hardened_flags(env, node_lib):
    env.docker()
    env.built_image(node_lib, "tc-node")
    r = vt(env, node_lib, "--smoke", "--profiles", "node")
    assert r.returncode == 0 and "SMOKE tc-node" in r.stdout and "PASS node --version" in r.stdout, r.stdout + r.stderr
    runs = env.runs()
    assert len(runs) == 1
    a = runs[0]
    assert vals(a, "--network") == ["none"] and "--read-only" in a and vals(a, "--cap-drop") == ["ALL"] and vals(a, "--pull") == ["never"]
    assert a[-2:] == ["node", "--version"] and "sha256:" in " ".join(a)          # by the verified image ID, not the tag


def test_smoke_fails_when_a_smoke_command_fails(env, node_lib):
    env.docker()
    env.built_image(node_lib, "tc-node")
    r = vt(env, node_lib, "--smoke", "--profiles", "node", FAKE_SMOKE_FAIL="node --version")
    assert r.returncode == 11 and "FAIL" in r.stdout and "TOOLS: smoke FAILED" in r.stdout


def test_smoke_refuses_an_image_without_a_record(env, node_lib):
    env.docker()
    env.seed_image(IMAGE_TAGS["tc-node"], IMAGE_ID_A)
    r = vt(env, node_lib, "--smoke", "--profiles", "node")
    assert r.returncode == 11 and "no build record" in r.stderr and env.runs() == []


def test_smoke_argv_is_not_glob_expanded(env, tmp_path):
    lib = mutated(tmp_path, fill_all=True, tools=[("node", {"smoke": ["node", "--print", "*"]})])
    env.docker()
    env.built_image(lib, "tc-node")
    (env.t / "a.txt").write_text("x")
    (env.t / "b.txt").write_text("y")
    r = vt(env, lib, "--smoke", "--profiles", "node")
    assert r.returncode == 0, r.stdout + r.stderr
    assert env.runs()[0][-3:] == ["node", "--print", "*"], env.runs()[0]


def test_smoke_in_scope_but_empty_says_so(env, node_lib):
    env.docker()
    r = vt(env, node_lib, "--smoke", "--profiles", "db", "--allow-placeholder")   # tc-pg exists but was never built
    assert r.returncode != 0 or "no smoke" in r.stdout


# ======================================================================================================== build.sh --profiles
def build(env, lib, *args, **kw):
    return env.run("build.sh", "--yes", *args, lib=lib, **kw)


def build_tags(env):
    out = []
    for a in env.builds():
        out.append((vals(a, "-t")[0], vals(a, "--target")[0] if vals(a, "--target") else "", vals(a, "-f")[0], vals(a, "--label")))
    return out


def test_build_core_builds_the_two_core_images_with_the_manifest_label(env, tmp_path):
    lib = fixture_lib(tmp_path)
    env.docker()
    r = build(env, lib, "--profiles", "core")
    assert r.returncode == 0, r.stdout + r.stderr
    bt = {t[0]: t for t in build_tags(env)}
    assert set(bt) == {IMAGE_TAGS["min-both"], IMAGE_TAGS["min-py"]}
    assert bt[IMAGE_TAGS["min-both"]][1:3] == ("eq-min", "Dockerfile.minimal") and bt[IMAGE_TAGS["min-py"]][1] == "eq-py-min"
    for name in ("min-both", "min-py"):
        want = "eq.tools.sha256=" + image_label(lib, lib / "TOOLS.toml", name)
        assert bt[IMAGE_TAGS[name]][3] == [want], name
        rec = (env.state / "images" / f"{name}.env").read_text()
        assert f"EQ_TOOLS_SHA256={want.split('=')[1]}\n" in rec
    imgenv = (env.state / "image.env").read_text()
    pf = re.search(r"^EQ_IMAGE_ID=(.*)$", (env.state / "images" / "min-both.env").read_text(), re.M).group(1)
    cp = re.search(r"^EQ_IMAGE_ID=(.*)$", (env.state / "images" / "min-py.env").read_text(), re.M).group(1)
    assert "EQ_DOCKER_PROFILES=core\n" in imgenv and "EQ_SELECT_LEAN=min-both\n" in imgenv     # PF runs its oracle in the PF image
    assert f"EQ_DOCKER_IMAGE_PF={pf}\n" in imgenv and f"EQ_IMAGE={pf}\n" in imgenv
    assert f"EQ_DOCKER_IMAGE_CP={cp}\n" in imgenv and f"EQ_DOCKER_IMAGE_CR={cp}\n" in imgenv
    assert not (env.state / "images" / "min-lean.env").exists()          # the candidate image is explicit-only


def test_build_an_extension_profile_uses_the_toolchains_dockerfile_and_its_target(env, tmp_path):
    lib = fixture_lib(tmp_path, fill_all=True)
    env.docker()
    r = build(env, lib, "--profiles", "core,node,db")
    assert r.returncode == 0, r.stdout + r.stderr
    bt = {t[0]: t for t in build_tags(env)}
    assert bt[IMAGE_TAGS["tc-node"]][1:3] == ("eq-node", "Dockerfile.toolchains")
    assert bt[IMAGE_TAGS["tc-pg"]][1:3] == ("eq-pg", "Dockerfile.toolchains")
    for a in env.builds():
        if "Dockerfile.toolchains" in a:
            assert not [x for x in a if x.startswith("KEEP_EXTS")], "keep profiles are for the Lean images only"
            assert vals(a, "--platform") == ["linux/arm64"] and "--load" in a
    assert re.search(r"EQ_TC_NODE_TAG=eq-node:arm64", (env.state / "image.env").read_text())


def test_build_all_is_every_profile_but_the_explicit_ones(env, tmp_path):
    lib = fixture_lib(tmp_path, fill_all=True)
    env.docker()
    r = build(env, lib, "--profiles", "all")
    assert r.returncode == 0, r.stdout + r.stderr
    built = {t[0] for t in build_tags(env)}
    want = {IMAGE_TAGS[i] for i in ("min-both", "min-py", "tc-node", "tc-rust", "tc-go", "tc-julia", "tc-haskell", "tc-jvm", "tc-pg")}
    assert built == want, built ^ want                                   # not tc-mongo (SSPL, explicit), not min-lean (candidate)
    r2 = build(env, lib, "--profiles", "all,mongo", "--dry-run")
    assert "tc-mongo" in r2.stdout


def test_build_mongo_only_when_named_and_core_is_not_added_by_build_sh(env, tmp_path):
    lib = fixture_lib(tmp_path, fill_all=True)
    env.docker()
    r = build(env, lib, "--profiles", "mongo")
    assert r.returncode == 0 and {t[0] for t in build_tags(env)} == {IMAGE_TAGS["tc-mongo"]}, r.stdout + r.stderr


def test_build_set_and_profiles_exclude_each_other_and_unknown_profiles_are_usage_errors(env, tmp_path):
    lib = fixture_lib(tmp_path)
    env.docker()
    assert build(env, lib, "--set", "min", "--profiles", "core").returncode == 2
    r = build(env, lib, "--profiles", "nosuch")
    assert r.returncode == 2 and "unknown profile" in r.stderr
    assert env.builds() == []


def shipped_copy(tmp_path):
    return fixture_lib(tmp_path, pin_distro=False, pin_busybox=False)


def test_build_refuses_a_placeholder_exit_13_names_it_and_builds_nothing(env, tmp_path):
    env.docker()
    r = build(env, shipped_copy(tmp_path), "--profiles", "core")          # as shipped: PINS has BUSYBOX_SHA256=UNSET, and the manifest too
    assert r.returncode == 13 and "BUSYBOX_SHA256 is a placeholder" in r.stderr and "--resolve-tools --write-pin" in r.stderr, r.stdout + r.stderr
    assert env.builds() == []


def test_build_refuses_a_pending_distro_tool_when_the_busybox_pin_is_there(env, tmp_path):
    lib = fixture_lib(tmp_path, pin_distro=False)                         # PINS and busybox pinned, bash perl jq still placeholders
    pins = (lib / "PINS").read_text()
    set_tool(lib / "TOOLS.toml", "busybox", version="1.0-fixture", sha256=re.search(r"^BUSYBOX_SHA256=(.*)$", pins, re.M).group(1))
    env.docker()
    r = build(env, lib, "--profiles", "core")
    assert r.returncode == 13 and "PENDING tool bash" in r.stderr and "PENDING tool jq" in r.stderr and "--resolve-tools" in r.stderr, r.stderr
    assert env.builds() == []


def test_build_refuses_a_pending_extension_tool_even_when_core_is_fine(env, tmp_path):
    lib = fixture_lib(tmp_path)                                          # distro tools filled, scala3 and mongosh not
    env.docker()
    r = build(env, lib, "--profiles", "core,jvm")
    assert r.returncode == 13 and "PENDING tool scala3" in r.stderr and env.builds() == [], r.stdout + r.stderr
    r2 = build(env, lib, "--profiles", "mongo")
    assert r2.returncode == 13 and "PENDING tool mongosh" in r2.stderr


def test_build_dry_run_prints_the_plan_and_creates_nothing(env, tmp_path):
    lib = fixture_lib(tmp_path, fill_all=True)
    env.docker()
    r = build(env, lib, "--profiles", "core,node", "--dry-run")
    assert r.returncode == 0 and "dry run" in r.stdout and "profiles: core node" in r.stdout, r.stdout + r.stderr
    for n in ("min-both", "min-py", "tc-node"):
        assert re.search(rf"{n}\s+\S+\s+build", r.stdout), (n, r.stdout)
    assert env.builds() == [] and not env.state.parent.exists()


def test_build_is_idempotent_and_a_manifest_edit_rebuilds_with_a_new_label(env, tmp_path):
    lib = fixture_lib(tmp_path, fill_all=True)
    env.docker()
    assert build(env, lib, "--profiles", "node").returncode == 0
    n1 = len(env.builds())
    r = build(env, lib, "--profiles", "node")
    assert r.returncode == 0 and "up to date" in r.stdout and len(env.builds()) == n1
    first = build_tags(env)[-1][3]
    set_tool(lib / "TOOLS.toml", "node", version="24.99.0")
    assert build(env, lib, "--profiles", "node").returncode == 0
    assert len(env.builds()) == n1 + 1 and build_tags(env)[-1][3] != first
    # --check agrees: ok when nothing changed since, STALE after another edit
    assert build(env, lib, "--profiles", "node", "--check").returncode == 0
    set_tool(lib / "TOOLS.toml", "node", sha256="1" * 64)
    chk = env.run("build.sh", "--profiles", "node", "--check", lib=lib)
    assert chk.returncode == 11 and "STALE" in chk.stdout


def test_build_check_reports_pending_manifest_values(env, tmp_path):
    env.docker()
    r = env.run("build.sh", "--profiles", "core", "--check", lib=shipped_copy(tmp_path))
    assert r.returncode == 11 and "tools manifest" in r.stdout


def test_resolve_tools_prints_and_pins_the_distro_package_values(env, tmp_path):
    lib = shipped_copy(tmp_path)                                         # PINS and the manifest with their placeholders: the real start
    env.docker()
    report = "\n".join([f"TOOL busybox 1:1.37.0-6 {'1' * 64}", f"TOOL bash 5.2.37-2 {'2' * 64}", f"TOOL perl 5.40.1-6 {'3' * 64}",
                        f"TOOL jq 1.7.1-6 {'4' * 64}", f"TOOL notatool 1 {'5' * 64}"])
    before = (lib / "TOOLS.toml").read_text()
    dry = env.run("build.sh", "--resolve-tools", lib=lib, FAKE_TOOLS_REPORT=report)
    assert dry.returncode == 0 and "TOOL bash 5.2.37-2" in dry.stdout and "to pin: re-run with --write-pin" in dry.stdout
    assert (lib / "TOOLS.toml").read_text() == before                        # printing pins nothing
    r = env.run("build.sh", "--resolve-tools", "--write-pin", lib=lib, FAKE_TOOLS_REPORT=report)
    assert r.returncode == 0 and "notatool is not in TOOLS.toml: skipped" in r.stderr, r.stdout + r.stderr
    tools = by_name(load_manifest(lib / "TOOLS.toml")["tool"])
    assert (tools["bash"]["version"], tools["bash"]["sha256"]) == ("5.2.37-2", "2" * 64)
    assert tools["busybox"]["sha256"] == "1" * 64 and "trust on first use" in tools["jq"]["checksum_source"]
    assert re.search(r"^BUSYBOX_SHA256=" + "1" * 64 + "$", (lib / "PINS").read_text(), re.M)
    assert re.search(r"^ARG BUSYBOX_SHA256=" + "1" * 64 + "$", (lib / "Dockerfile.minimal").read_text(), re.M)
    after = vt(env, lib, "--manifest", "--profiles", "core")                 # the pins agree everywhere: core now validates
    assert after.returncode == 0, after.stdout
    assert build(env, lib, "--profiles", "core").returncode == 0


def test_resolve_tools_without_any_tool_line_is_exit_12(env, tmp_path):
    lib = shipped_copy(tmp_path)
    env.docker()
    r = env.run("build.sh", "--resolve-tools", "--write-pin", lib=lib, FAKE_TOOLS_REPORT="nothing useful")
    assert r.returncode == 12 and "could not read the tool hashes" in r.stderr


# =============================================================================================== bounded wait for the daemon
def eqd(env, *args, lib=None, **kw):
    return env.run("eq-docker.sh", "install", "--set", "full", "--yes", *args, lib=lib, **kw)


def test_the_driver_waits_for_a_daemon_that_is_starting_and_then_goes_on(env):
    env.docker()
    t0 = time.time()
    r = eqd(env, "--wait-daemon", "10", FAKE_DOCKER_UP_AFTER="2", EQ_DOCKER_WAIT_POLL="1")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "waiting up to 10s for the Docker daemon" in r.stdout and "answered after" in r.stdout
    assert time.time() - t0 < 60 and len(env.builds()) == 1 and env.status() == "ok"


def test_the_wait_is_bounded_and_ends_as_a_skip_not_a_failure(env):
    env.docker()
    r = eqd(env, "--wait-daemon", "2", FAKE_DOCKER_DOWN="1", EQ_DOCKER_WAIT_POLL="1")
    assert r.returncode == 10 and "waiting up to 2s" in r.stdout and "not reachable" in r.stderr, r.stdout + r.stderr
    assert env.builds() == [] and env.status() == "skipped"


def test_a_daemon_that_needs_longer_than_the_wait_is_a_skip(env):
    env.docker()
    r = eqd(env, "--wait-daemon", "2", FAKE_DOCKER_UP_AFTER="50", EQ_DOCKER_WAIT_POLL="1")
    assert r.returncode == 10 and env.builds() == []


def test_zero_means_no_wait_and_the_test_default_is_zero(env):
    env.docker()
    r = eqd(env, FAKE_DOCKER_DOWN="1")                                   # conftest: EQ_DOCKER_WAIT_S=0
    assert r.returncode == 10 and "waiting up to" not in r.stdout
    r = eqd(env, "--wait-daemon", "0", FAKE_DOCKER_DOWN="1", EQ_DOCKER_WAIT_S="30")
    assert r.returncode == 10 and "waiting up to" not in r.stdout


def test_the_environment_variable_sets_the_wait_and_the_flag_overrides_it(env):
    env.docker()
    r = eqd(env, FAKE_DOCKER_DOWN="1", EQ_DOCKER_WAIT_S="1", EQ_DOCKER_WAIT_POLL="1")
    assert r.returncode == 10 and "waiting up to 1s" in r.stdout
    r = eqd(env, "--wait-daemon", "2", FAKE_DOCKER_DOWN="1", EQ_DOCKER_WAIT_S="30", EQ_DOCKER_WAIT_POLL="1")
    assert "waiting up to 2s" in r.stdout


def test_a_dry_run_never_waits(env):
    env.docker()
    t0 = time.time()
    r = env.run("eq-docker.sh", "install", "--set", "full", "--dry-run", "--wait-daemon", "30", FAKE_DOCKER_DOWN="1")
    assert r.returncode == 10 and "waiting up to" not in r.stdout and time.time() - t0 < 20


@pytest.mark.parametrize("args", [("--wait-daemon", "abc"), ("--wait-daemon", "-1"), ("--wait-daemon", "")])
def test_a_non_numeric_wait_is_a_usage_error(env, args):
    env.docker()
    assert eqd(env, *args).returncode == 2


def test_a_zero_poll_interval_is_raised_to_one_second(env):
    env.docker()
    r = eqd(env, "--wait-daemon", "3", FAKE_DOCKER_UP_AFTER="1", EQ_DOCKER_WAIT_POLL="0")
    assert r.returncode == 0, r.stdout + r.stderr


# ================================================================================================= eq-docker.sh --profiles
def seeded_install_lib(env, tmp_path, images, **kw):
    """fixture copy + the finished tool trees of `images` in the fake daemon (the fake build does not make a rootfs; a real build
    leaves /opt/eq/TOOLS.lock and the tool files, which built_image reproduces and `build.sh` then re-labels)."""
    lib = fixture_lib(tmp_path, fill_all=True)
    env.docker()
    env.use_probe_hooks(lib)
    for i in images:
        env.built_image(lib, i, **kw)
    return lib


def test_install_with_profiles_builds_verifies_smokes_and_records_the_profiles(env, tmp_path):
    lib = seeded_install_lib(env, tmp_path, ["min-both", "min-py", "tc-node"])
    r = env.run("eq-docker.sh", "install", "--profiles", "node", "--yes", lib=lib)
    assert r.returncode == 0, r.stdout + r.stderr
    built = {t[0] for t in build_tags(env)}
    assert built == {IMAGE_TAGS["min-both"], IMAGE_TAGS["min-py"], IMAGE_TAGS["tc-node"]}      # core is always part of it
    assert "tools: verified" in r.stdout and "smoke: PASS" in r.stdout and "spike: PASS" in r.stdout and "probe: PASS" in r.stdout
    assert env.status() == "ok" and env.status("EQ_DOCKER_STATUS_PROFILES") == "core,node"
    ids = env.status("EQ_DOCKER_STATUS_VERIFIED_IDS").split(",")
    assert len(ids) == 3 and all(re.fullmatch(r"sha256:[0-9a-f]{64}", i) for i in ids)
    assert "eq-testrun-smoke-tc-node-node" in " ".join(" ".join(a) for a in env.runs())          # only the extension image is smoked
    assert not any("smoke-min-both" in " ".join(a) for a in env.runs())
    assert (env.state / "logs" / "verify-tools.log").exists() and (env.state / "logs" / "smoke.log").exists()
    assert "EQ_DOCKER_PROFILES=core,node" in (env.state / "image.env").read_text()
    p = env.run("eq-docker.sh", "print-env", lib=lib)
    assert p.returncode == 0 and p.stdout.splitlines()[0] == "EQ_ISOLATION=docker"
    # the probe ran the tools-manifest hook for both core images: PASS rows, not INFO
    probe_log = (env.state / "logs" / "probe.log").read_text()
    assert len(re.findall(r"tools_lock_matches_manifest\s+PASS", probe_log)) == 2, probe_log


def test_install_with_profiles_second_run_skips_everything(env, tmp_path):
    lib = seeded_install_lib(env, tmp_path, ["min-both", "min-py"])
    assert env.run("eq-docker.sh", "install", "--profiles", "core", "--yes", lib=lib).returncode == 0
    n = len(env.builds())
    r = env.run("eq-docker.sh", "install", "--profiles", "core", "--yes", lib=lib)
    assert r.returncode == 0 and "spike and probe skipped" in r.stdout and len(env.builds()) == n


def test_install_changing_the_manifest_runs_the_verification_again(env, tmp_path):
    lib = seeded_install_lib(env, tmp_path, ["min-both", "min-py"])
    assert env.run("eq-docker.sh", "install", "--profiles", "core", "--yes", lib=lib).returncode == 0
    set_tool(lib / "TOOLS.toml", "jq", checksum_source="edited")          # PINS+TOOLS hash is part of the verified state
    env.built_image(lib, "min-both")
    env.built_image(lib, "min-py")
    r = env.run("eq-docker.sh", "install", "--profiles", "core", "--yes", lib=lib)
    assert r.returncode == 0 and "spike and probe skipped" not in r.stdout, r.stdout + r.stderr


def test_install_exit_16_when_a_tool_file_does_not_match_the_lock(env, tmp_path):
    lib = seeded_install_lib(env, tmp_path, ["min-both", "min-py"], tamper=("/opt/uv/uv", "tampered"))
    r = env.run("eq-docker.sh", "install", "--profiles", "core", "--yes", lib=lib)
    assert r.returncode == 16 and env.status() == "failed" and env.status("EQ_DOCKER_STATUS_WHY") == "tools verification failed", r.stdout
    assert "DEEP" in (env.state / "logs" / "verify-tools.log").read_text()
    assert env.run("eq-docker.sh", "print-env", lib=lib).returncode == 1       # nothing is published for an unverified install
    assert [a for a in env.runs() if any("spike" in x for x in a)] == []         # and neither spike nor probe ran


def test_install_exit_16_when_an_extension_smoke_test_fails(env, tmp_path):
    lib = seeded_install_lib(env, tmp_path, ["min-both", "min-py", "tc-node"])
    r = env.run("eq-docker.sh", "install", "--profiles", "node", "--yes", lib=lib, FAKE_SMOKE_FAIL="node --version")
    assert r.returncode == 16 and env.status("EQ_DOCKER_STATUS_WHY") == "smoke test failed", r.stdout + r.stderr


def test_install_a_pending_profile_is_exit_13_and_builds_nothing(env, tmp_path):
    lib = fixture_lib(tmp_path)                                               # scala3 is a placeholder
    env.docker()
    r = env.run("eq-docker.sh", "install", "--profiles", "jvm", "--yes", lib=lib)
    assert r.returncode == 13 and env.builds() == [] and env.status("EQ_DOCKER_STATUS_WHY") == "unresolved pin", r.stdout + r.stderr


def test_install_with_the_shipped_manifest_says_how_to_resolve_the_pins(env, tmp_path):
    env.docker()
    r = env.run("eq-docker.sh", "install", "--profiles", "core", "--yes", lib=shipped_copy(tmp_path))
    assert r.returncode == 13 and "--resolve-tools" in (env.state / "logs" / "build.log").read_text()


def test_install_profile_usage_errors(env):
    env.docker()
    assert env.run("eq-docker.sh", "install", "--profiles", "nosuch").returncode == 2
    assert env.run("eq-docker.sh", "install", "--set", "full", "--profiles", "core").returncode == 2
    assert env.run("eq-docker.sh", "install", "--profiles").returncode == 2


def test_install_accepts_the_equals_form_and_all_without_mongo(env, tmp_path):
    lib = fixture_lib(tmp_path, fill_all=True)
    env.docker()
    r = env.run("eq-docker.sh", "install", "--profiles=all", "--dry-run", lib=lib)
    assert r.returncode == 0 and "tc-mongo" not in r.stdout and "tc-pg" in r.stdout, r.stdout + r.stderr


def test_driver_check_with_profiles(env, tmp_path):
    lib = seeded_install_lib(env, tmp_path, ["min-both", "min-py"])
    assert env.run("eq-docker.sh", "install", "--profiles", "core", "--yes", lib=lib).returncode == 0
    ok = env.run("eq-docker.sh", "check", "--profiles", "core", lib=lib)
    assert ok.returncode == 0 and "CHECK: OK" in ok.stdout, ok.stdout + ok.stderr
    set_tool(lib / "TOOLS.toml", "uv", notes="edited after the build")
    stale = env.run("eq-docker.sh", "check", "--profiles", "core", lib=lib)
    assert stale.returncode == 11 and "STALE" in stale.stdout


# ============================================================================================================ probe.d hooks
def hook_dir(tmp_path, **hooks):
    d = tmp_path / "hooks"
    d.mkdir(exist_ok=True)
    for name, body in hooks.items():
        (d / name).write_text("#!/bin/bash\n" + body)
    return d


def probe(env, hooks, *, images=1, **extra):
    env.docker()
    env.record("a", TAG, IMAGE_ID_A)
    if images == 2:
        env.record("b", TAG_PY, IMAGE_ID_B)
    return env.run("probe.sh", EQ_IMAGE=TAG, EQ_IMAGE_PY=TAG_PY if images == 2 else TAG, EQ_PROBE_D=hooks, **extra)


def prows(out):
    d = {}
    for ln in out.splitlines():
        m = re.match(r"^(\S+)\s+(PASS|FAIL|INFO)\b\s*(.*)$", ln)
        if m:
            d.setdefault(m.group(1), []).append((m.group(2), m.group(3)))
    return d


def test_a_hook_row_is_folded_into_the_report_and_the_noise_is_indented(env, tmp_path):
    hd = hook_dir(tmp_path, **{"10-ok.sh": 'echo "some noise"\necho "T|ok_row|PASS|all good"\n'})
    p = probe(env, hd)
    assert p.returncode == 0 and "PROBE: PASS" in p.stdout, p.stdout + p.stderr
    assert prows(p.stdout)["ok_row"] == [("PASS", "[10-ok.sh] all good")]
    assert "  | 10-ok.sh: some noise" in p.stdout


def test_a_failing_hook_row_fails_the_probe(env, tmp_path):
    p = probe(env, hook_dir(tmp_path, **{"10-bad.sh": 'echo "T|bad_row|FAIL|nope"\n'}))
    assert p.returncode == 1 and prows(p.stdout)["bad_row"][0][0] == "FAIL" and "PROBE: FAIL" in p.stdout


def test_a_hook_that_crashes_without_a_row_is_a_failure_not_a_pass(env, tmp_path):
    p = probe(env, hook_dir(tmp_path, **{"10-crash.sh": "exit 7\n"}))
    assert p.returncode == 1
    assert prows(p.stdout)["hook_10-crash.sh"][0][0] == "FAIL" and "reported no row (exit 7)" in p.stdout


def test_a_hook_that_prints_nothing_with_exit_zero_is_also_a_failure(env, tmp_path):
    p = probe(env, hook_dir(tmp_path, **{"10-mute.sh": "true\n"}))
    assert p.returncode == 1 and prows(p.stdout)["hook_10-mute.sh"][0][0] == "FAIL"


def test_a_hook_exiting_non_zero_after_only_passing_rows_is_a_failure(env, tmp_path):
    p = probe(env, hook_dir(tmp_path, **{"10-liar.sh": 'echo "T|fine|PASS|ok"\nexit 3\n'}))
    assert p.returncode == 1 and prows(p.stdout)["hook_10-liar.sh"][0][0] == "FAIL" and "exited 3 without a failing row" in p.stdout


def test_a_hook_that_only_informs_is_not_a_failure(env, tmp_path):
    p = probe(env, hook_dir(tmp_path, **{"10-info.sh": 'echo "T|just_info|INFO|fyi"\n'}))
    assert p.returncode == 0 and prows(p.stdout)["just_info"][0][0] == "INFO"


def test_hooks_run_sorted_by_name_and_only_dot_sh_files(env, tmp_path):
    hd = hook_dir(tmp_path, **{"20-b.sh": 'echo "T|row_b|PASS|b"\n', "10-a.sh": 'echo "T|row_a|PASS|a"\n',
                               "05-not-a-hook.txt": 'echo "T|row_txt|FAIL|must not run"\n'})
    p = probe(env, hd)
    assert p.returncode == 0 and "row_txt" not in p.stdout
    assert p.stdout.index("row_a") < p.stdout.index("row_b")


def test_a_hook_gets_the_documented_environment(env, tmp_path):
    hd = hook_dir(tmp_path, **{"10-env.sh": (
        'echo "T|env_row|INFO|IMAGE=$EQ_PROBE_IMAGE ID=$EQ_PROBE_IMAGE_ID ROOT=$([ -d "$EQ_PROBE_ROOT" ] && echo dir) '
        'LIB=$(basename "$EQ_PROBE_LIB") HOOK=$(basename "$EQ_PROBE_HOOK") RUNID=$EQ_RUN_ID"\n')})
    p = probe(env, hd)
    detail = prows(p.stdout)["env_row"][0][1]
    assert f"IMAGE={TAG}" in detail and f"ID={IMAGE_ID_A}" in detail and "ROOT=dir" in detail and "LIB=lib.sh" in detail
    assert "HOOK=10-env.sh" in detail and "RUNID=testrun" in detail


def test_the_hook_runs_once_per_probed_image(env, tmp_path):
    hd = hook_dir(tmp_path, **{"10-who.sh": 'echo "T|who|INFO|$EQ_PROBE_IMAGE"\n'})
    p = probe(env, hd, images=2)
    assert [d for _, d in prows(p.stdout)["who"]] == [f"[10-who.sh] {TAG}", f"[10-who.sh] {TAG_PY}"]


def test_no_hook_directory_or_an_empty_one_is_fine(env, tmp_path):
    assert probe(env, tmp_path / "nowhere").returncode == 0
    (tmp_path / "empty").mkdir()
    assert probe(env, tmp_path / "empty").returncode == 0


def test_the_shipped_hook_directory_has_the_manifest_and_network_hooks():
    names = sorted(p.name for p in (LIB / "probe.d").glob("*.sh"))
    assert "20-tools-manifest.sh" in names and "30-internal-net.sh" in names and names == sorted(names)


# --- probe.d/20-tools-manifest.sh
def test_hook_20_an_image_the_manifest_does_not_describe_gets_info_rows_not_a_pass(env):
    p = probe(env, env.probe_d)
    r = prows(p.stdout)
    assert p.returncode == 0
    assert r["tools_manifest_valid"][0][0] == "INFO" and r["tools_lock_matches_manifest"][0][0] == "INFO"


def test_hook_20_passes_for_a_manifest_image_whose_label_lock_and_files_match(env, tmp_path):
    lib = fixture_lib(tmp_path, fill_all=True)
    env.docker()
    env.use_probe_hooks(lib)
    tag, iid = env.built_image(lib, "min-py")
    r = env.run("probe.sh", lib=lib, EQ_IMAGE=tag, EQ_IMAGE_PY=tag)
    rows = prows(r.stdout)
    assert r.returncode == 0, r.stdout + r.stderr
    assert rows["tools_manifest_valid"][0][0] == "PASS" and rows["tools_lock_matches_manifest"][0][0] == "PASS"


def test_hook_20_fails_when_an_installed_file_was_replaced(env, tmp_path):
    lib = fixture_lib(tmp_path, fill_all=True)
    env.docker()
    env.use_probe_hooks(lib)
    tag, _ = env.built_image(lib, "min-py", tamper=("/opt/python/bin/python3", "evil"))
    r = env.run("probe.sh", lib=lib, EQ_IMAGE=tag, EQ_IMAGE_PY=tag)
    assert r.returncode == 1 and prows(r.stdout)["tools_lock_matches_manifest"][0][0] == "FAIL", r.stdout


def test_hook_20_fails_while_the_manifest_has_a_placeholder_for_this_image(env, tmp_path):
    lib = fixture_lib(tmp_path, pin_distro=False)
    env.docker()
    env.use_probe_hooks(lib)
    tag, _ = env.built_image(lib, "min-py")
    r = env.run("probe.sh", lib=lib, EQ_IMAGE=tag, EQ_IMAGE_PY=tag)
    assert r.returncode == 1 and prows(r.stdout)["tools_manifest_valid"][0][0] == "FAIL", r.stdout


# --- probe.d/30-internal-net.sh
def net_probe(env, **extra):
    return probe(env, env.probe_d, **extra)


def test_hook_30_proves_the_internal_network_and_removes_it(env):
    p = net_probe(env)
    r = prows(p.stdout)
    assert p.returncode == 0, p.stdout + p.stderr
    for n in ("internal_net_attached", "internal_net_no_default_route", "internal_net_no_egress"):
        assert r[n][0][0] == "PASS", (n, p.stdout)
    creates = [a for a in env.argv_log() if a[:2] == ["network", "create"]]
    assert creates and "--internal" in creates[0] and creates[0][-1] == "eq-probe-testrun"
    assert [a for a in env.argv_log() if a[:3] == ["network", "rm", "eq-probe-testrun"]], "the throw-away network is removed"
    run = [a for a in env.runs() if "eq-testrun-probe-intnet" in a][0]
    assert vals(run, "--network") == ["none", "eq-probe-testrun"] and "--read-only" in run and vals(run, "--cap-drop") == ["ALL"]
    assert "--publish" not in run and "-p" not in run


@pytest.mark.parametrize("knob,row", [("FAKE_INT_ROUTE", "internal_net_no_default_route"), ("FAKE_INT_REACH", "internal_net_no_egress"),
                                      ("FAKE_INT_DNS", "internal_net_no_egress")])
def test_hook_30_fails_when_the_network_has_a_route_or_egress(env, knob, row):
    p = net_probe(env, **{knob: "1"})
    assert p.returncode == 1 and prows(p.stdout)[row][0][0] == "FAIL", p.stdout


def test_hook_30_fails_when_the_network_cannot_be_created(env):
    p = net_probe(env, FAKE_NETWORK_FAIL="1")
    assert p.returncode == 1 and prows(p.stdout)["internal_net_created"][0][0] == "FAIL"


# ============================================================================================ Dockerfile.toolchains vs the manifest
DF = LIB / "Dockerfile.toolchains"


def stages():
    """{stage name: (base, [instruction lines])} of Dockerfile.toolchains."""
    out, cur = {}, None
    for ln in DF.read_text().splitlines():
        m = re.match(r"^FROM (\S+) AS (\S+)$", ln)
        if m:
            cur = m.group(2)
            out[cur] = (m.group(1), [])
        elif cur and ln.strip() and not ln.lstrip().startswith("#"):
            out[cur][1].append(ln)
    return out


def instr(st, word):
    return [ln.split(None, 1)[1] for ln in st[1] if ln.split(None, 1)[0] == word]


@pytest.fixture(scope="module")
def dfs():
    if not DF.exists():
        pytest.skip("no Dockerfile.toolchains")
    return stages()


def tc_images():
    return [i for i in manifest()["image"] if i["dockerfile"] == "Dockerfile.toolchains"]


def test_each_extension_target_is_a_final_stage_from_eq_base_that_runs_nothing(dfs):
    for i in tc_images():
        base, lines = dfs[i["target"]]
        assert base == "eq-base", i["name"]
        words = [ln.split(None, 1)[0] for ln in lines]
        assert "RUN" not in words and "ADD" not in words, i["name"]                    # nothing executes in a final stage (no shell)
        assert words[0] == "COPY" and f"--from=assemble-{i['target'].removeprefix('eq-')} " in lines[0], i["name"]
        assert instr(dfs[i["target"]], "USER") and instr(dfs[i["target"]], "USER")[0] in ("10001:10001", "10002:10002"), i["name"]
        assert instr(dfs[i["target"]], "USER")[0] == ("10002:10002" if i["kind"] == "server" else "10001:10001")
        assert instr(dfs[i["target"]], "LABEL"), i["name"]
        cmd = instr(dfs[i["target"]], "CMD")
        assert len(cmd) == 1 and cmd[0].startswith('["/opt/'), (i["name"], cmd)


def test_no_dockerfile_instruction_the_inspect_check_forbids(dfs):
    text = "\n".join(ln for ln in DF.read_text().splitlines() if not ln.lstrip().startswith("#"))
    for word in ("ENTRYPOINT", "EXPOSE", "VOLUME", "HEALTHCHECK", "ONBUILD"):
        assert not re.search(rf"^{word}\b", text, re.M), word
    assert not re.search(r"\b(sudo|--privileged|docker\.sock)\b", text)
    for name, (base, lines) in dfs.items():                      # curl only in the discarded builder stages that download
        if name.startswith("eq-") or name.startswith("assemble-"):
            assert not any(re.search(r"\bcurl\b", ln) for ln in lines), name


def test_the_final_stage_env_is_what_the_manifest_says(dfs):
    m = manifest()
    tools, imgs = by_name(m["tool"]), m["image"]
    for i in tc_images():
        env_line = instr(dfs[i["target"]], "ENV")
        assert len(env_line) == 1, i["name"]
        kv = dict(p.split("=", 1) for p in env_line[0].split())
        want_path = []
        for t in i["tools"]:
            for b in tools[t].get("bins", []):
                want_path.append(tools[t]["dest"] if b == "." else f"{tools[t]['dest']}/{b}")
        if i.get("applets"):
            want_path.append("/usr/bin")                                              # the pinned busybox applet links
        assert kv["PATH"] == ":".join(want_path), (i["name"], kv["PATH"], want_path)
        for t in i["tools"]:
            for e in tools[t].get("env", []):
                k, v = e.split("=", 1)
                assert kv.get(k) == v, (i["name"], e, kv.get(k))
        for k in kv:
            assert not re.search(r"token|secret|passw|credential|api_?key|anthropic|aws_|github", k, re.I), k
        assert kv["HOME"] == "/tmp" and kv["TMPDIR"] == "/tmp"
    assert imgs


def test_every_tool_of_an_extension_image_has_a_fetch_stage_and_every_fetch_stage_a_manifest_tool(dfs):
    m = manifest()
    tools = by_name(m["tool"])
    wanted = {t for i in tc_images() for t in i["tools"] if tools[t]["provenance"] != "distro-package"}
    fetch = {}
    for name, (base, lines) in dfs.items():
        if name.startswith("fetch-"):
            run = [ln for ln in lines if "fetch-tool.sh" in ln]
            assert len(run) == 1, name
            fetch[name.removeprefix("fetch-")] = (base, run[0].split("fetch-tool.sh")[1].strip())
    assert set(fetch) == wanted, set(fetch) ^ wanted
    for name, (base, arg) in fetch.items():
        assert arg == name, (name, arg)
        recipe = tools[name].get("recipe")
        needs_compiler = tools[name]["provenance"] == "built-from-source" or bool(
            recipe and re.search(r"\bmake\b|\bcc\b|\bgcc\b", (LIB / recipe).read_text()))
        assert (base == "tools-build") == needs_compiler, (name, base, recipe)         # a compiler exists only where a recipe needs one
    assert fetch["postgresql"][0] == "tools-build" and fetch["ghc"][0] == "tools-build" and fetch["node"][0] == "tools-fetch"


def test_assemble_stages_run_the_extension_rootfs_script_for_their_image_only(dfs):
    for i in tc_images():
        st = dfs["assemble-" + i["target"].removeprefix("eq-")]
        runs = [ln for ln in st[1] if "mkrootfs-tc.sh" in ln]
        assert runs and runs[-1].endswith(f"mkrootfs-tc.sh {i['name']}"), i["name"]
        copied = {ln.split("--from=")[1].split()[0].removeprefix("fetch-") for ln in st[1] if ln.startswith("COPY --from=fetch-")}
        want = {t for t in i["tools"] if by_name(manifest()["tool"])[t]["provenance"] != "distro-package"}
        assert copied == want, (i["name"], copied ^ want)
        if i["kind"] == "server":
            assert any(ln.startswith("COPY --from=busybox ") for ln in st[1]), i["name"]
        else:
            assert not any("busybox" in ln for ln in st[1]), i["name"]                   # a language image carries no shell


def test_the_base_is_scratch_with_no_tools_and_the_builder_stages_are_the_only_ones_with_apt(dfs):
    assert dfs["eq-base"][0] == "scratch"
    assert all(not ln.startswith("RUN") for ln in dfs["eq-base"][1])
    for name, (base, lines) in dfs.items():
        has_apt = any("apt-get" in ln for ln in lines)
        final = name.startswith("eq-")
        assert not (final and has_apt), name
    text = DF.read_text()
    assert "FROM scratch AS eq-base" in text and "COPY --from=assemble-base /rootfs/ /" in text


def test_a_fetch_stage_never_receives_the_final_images_content(dfs):
    # builder stages feed final stages, never the other way round: no `COPY --from=eq-*` into an assemble or fetch stage
    for name, (base, lines) in dfs.items():
        if name.startswith(("fetch-", "assemble-", "tools-")):
            assert not any(re.match(r"COPY --from=eq-", ln) for ln in lines), name


def test_the_server_images_start_only_their_hash_pinned_entry_script(dfs):
    tools = by_name(manifest()["tool"])
    for i in tc_images():
        if i["kind"] != "server":
            continue
        cmd = instr(dfs[i["target"]], "CMD")[0]
        entry = next(t for t in i["tools"] if t.startswith("entry-"))
        assert cmd == f'["{tools[entry]["files"][0]}"]', i["name"]
        assert re.fullmatch(r"[0-9a-f]{64}", tools[entry]["sha256"]) and tools[entry]["provenance"] == "in-repo"
        assert hashlib_of(LIB / "tc" / f"{entry}.sh") == tools[entry]["sha256"], entry          # re-pinned after every edit


def hashlib_of(path):
    import hashlib
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_the_entry_scripts_keep_the_password_out_of_argv_files_and_the_final_environment():
    for name in ("entry-pg.sh", "entry-mongo.sh"):
        text = (LIB / "tc" / name).read_text()
        code = "\n".join(ln for ln in text.splitlines() if not ln.lstrip().startswith("#"))
        assert 'EQ_DB_PASSWORD:?' in code and "unset EQ_DB_PASSWORD" in code, name           # required, and gone before the exec
        assert code.index("unset EQ_DB_PASSWORD") < code.index("exec "), name
        assert not re.search(r"(--password|-p\s*\"?\$EQ_DB_PASSWORD|echo\s+\"?\$EQ_DB_PASSWORD)", code), name
        assert "set -eu" in code, name
    pg = (LIB / "tc" / "entry-pg.sh").read_text()
    assert "scram-sha-256" in pg and "umask 077" in pg and "rm -f \"$pw\"" in pg and "/var/lib/eq-pg" in pg
    mongo = (LIB / "tc" / "entry-mongo.sh").read_text()
    assert "process.env.EQ_DB_PASSWORD" in mongo and "--auth" in mongo and "--bind_ip 127.0.0.1" in mongo


# ============================================================================================ tc/fetch-tool.sh (early exits only)
def fetch(env, lib, name, **kw):
    return subprocess.run([BASH, str(lib / "tc" / "fetch-tool.sh"), name], env=env.environ(EQ_TOOLS_DIR=lib, **kw), capture_output=True,
                          text=True, timeout=60, cwd=str(env.t), check=False)


def test_fetch_tool_refuses_a_placeholder_before_anything_else(env, tmp_path):
    lib = fixture_lib(tmp_path)
    r = fetch(env, lib, "scala3")
    assert r.returncode == 13 and "is PLACEHOLDER" in r.stderr and "refusing to guess" in r.stderr, r.stderr


def test_fetch_tool_refuses_an_unknown_tool_a_plain_http_url_and_a_foreign_dest(env, tmp_path):
    lib = fixture_lib(tmp_path, fill_all=True)
    assert fetch(env, lib, "nosuch").returncode == 2
    set_tool(lib / "TOOLS.toml", "node", url="http://nodejs.org/x.tar.xz")
    r = fetch(env, lib, "node")
    assert r.returncode == 2 and "url must be https" in r.stderr
    set_tool(lib / "TOOLS.toml", "node", url="https://nodejs.org/x.tar.xz", dest="/etc/node")
    r = fetch(env, lib, "node")
    assert r.returncode == 2 and "must be under /opt or /usr" in r.stderr


def test_fetch_tool_built_from_source_needs_a_recipe_and_a_distro_package_is_not_fetched_here(env, tmp_path):
    lib = fixture_lib(tmp_path, fill_all=True)
    set_tool(lib / "TOOLS.toml", "postgresql", recipe="")
    # the download happens before the recipe is looked at, so a stub curl that fails makes this a pure early-exit test
    stub = env.shims / "curl"
    stub.write_text("#!/bin/bash\nexit 22\n")
    stub.chmod(0o755)
    r = fetch(env, lib, "postgresql")
    assert r.returncode != 0 and not (tmp_path / "opt").exists()
    r2 = fetch(env, lib, "busybox")
    assert r2.returncode == 2 and "not fetched here" in r2.stderr, r2.stderr
