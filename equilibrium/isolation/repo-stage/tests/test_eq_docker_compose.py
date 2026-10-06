"""compose.yaml, compose.wall.yaml and eq-compose.sh of lib/eq-docker (X1, X3, X7): static checks of the two compose files with a real YAML
parser (needs PyYAML: `uv run --with pytest --with pyyaml`), and eq-compose.sh against a fake `docker` (hermetic: nothing is started).

The static rules are the isolation promises of the scope extensions: a read-only root, every capability dropped, no-new-privileges,
resource limits, an unprivileged user, no published port, no host network, no privileged flag, no docker socket, the only host mounts the
per-run work directory (and, in compose.wall.yaml, the one WALL tunnel at /eq/tunnel), no network for anything that runs model-written
code except the Python solver that reaches the databases of its run on the one internal-only network, no secret in the file, images only
by an interpolated reference that eq-compose.sh fills from the verified build record. What only a real daemon can show (that
`docker compose config` accepts the file, that a container started from it really is read-only) is a user step in RUNBOOK_MINIMAL.md.

Run: uv run --with pytest --with pyyaml pytest -q -p no:cacheprovider tests/test_eq_docker_compose.py
"""
import os
import re
import subprocess

import pytest

from conftest import IMAGE_TAGS, LIB, fixture_lib, load_manifest, set_tool, vals

yaml = pytest.importorskip("yaml")

COMPOSE = LIB / "compose.yaml"
WALL = LIB / "compose.wall.yaml"
pytestmark = pytest.mark.skipif(not COMPOSE.exists(), reason="no compose.yaml in the directory under test")

CODE_SERVICES = {"pf", "cp", "cr", "cp-db", "node", "rust", "go", "julia", "haskell", "jvm"}      # run model-written code
DB_SERVICES = {"pg", "mongo"}
LANG_SERVICES = {"node", "rust", "go", "julia", "haskell", "jvm"}
CHECK_SERVICES = {"pf", "cp", "cr", "cp-db"}
# the harness's COPY_IN prefix (eq_harness.py COPY_IN): the check services start with this text
HARNESS_COPY_IN = 'while [ "$1" != -- ]; do cp -R "$1"/. "$2"/ || exit 1; shift 2; done; shift; exec "$@"'


@pytest.fixture(scope="module")
def cfg():
    return yaml.safe_load(COMPOSE.read_text())


@pytest.fixture(scope="module")
def wall():
    if not WALL.exists():
        pytest.skip("no compose.wall.yaml")
    return yaml.safe_load(WALL.read_text())


def svc(cfg, name):
    return cfg["services"][name]


# ================================================================================================================ static: compose.yaml
def test_the_file_has_only_the_expected_top_level_keys_and_no_named_volume_secret_or_config(cfg):
    assert cfg["name"] == "eq"
    assert set(cfg) <= {"name", "services", "networks"} | {k for k in cfg if k.startswith("x-")}
    assert not {"volumes", "secrets", "configs"} & set(cfg)


def test_the_service_set_is_the_manifests(cfg):
    assert set(cfg["services"]) == CODE_SERVICES | DB_SERVICES
    m = load_manifest(LIB / "TOOLS.toml")
    for i in m["image"]:
        assert i["service"] in cfg["services"], i["name"]


def test_every_service_is_hardened(cfg):
    for name, s in cfg["services"].items():
        assert s["read_only"] is True, name
        assert s["cap_drop"] == ["ALL"] and "cap_add" not in s, name
        assert "no-new-privileges:true" in s["security_opt"] and len(s["security_opt"]) == 1, name
        assert s["init"] is True and s["pull_policy"] == "never", name
        uid = str(s["user"]).split(":")[0]
        assert uid.isdigit() and int(uid) >= 10000, (name, s["user"])                       # never root
        for k in ("pids_limit", "mem_limit", "memswap_limit", "cpus"):
            assert k in s, (name, k)
        assert s["memswap_limit"] == s["mem_limit"], name                                    # no swap
        assert s["logging"]["driver"] == "json-file" and "max-size" in s["logging"]["options"], name
        assert s["labels"].get("eq-compose") == "1", name


def test_resource_limits_have_sane_defaults(cfg):
    for name, s in cfg["services"].items():
        for k in ("pids_limit", "mem_limit", "cpus"):
            v = str(s[k])
            m = re.fullmatch(r"\$\{EQ_[A-Z]+:-([0-9.]+[a-z]?)\}|([0-9.]+[a-z]?)", v)
            assert m, (name, k, v)
            val = m.group(1) or m.group(2)
            assert float(re.sub(r"[a-z]$", "", val)) > 0, (name, k)
            if k == "pids_limit":
                assert int(val) <= 512, (name, val)
    for name in DB_SERVICES:
        assert int(svc(cfg, name)["pids_limit"]) <= 256 and svc(cfg, name)["mem_limit"] in ("1g", "2g")


def test_nothing_that_widens_the_container_is_set(cfg):
    forbidden = {"privileged", "ports", "expose", "pid", "ipc", "uts", "userns_mode", "cgroup", "cgroup_parent", "devices",
                 "device_cgroup_rules", "sysctls", "extra_hosts", "dns", "dns_search", "env_file", "volumes_from", "build", "secrets",
                 "configs", "links", "external_links", "mac_address", "runtime", "group_add", "cap_add"}
    for name, s in cfg["services"].items():
        assert not forbidden & set(s), (name, forbidden & set(s))
        for opt in s.get("security_opt", []):
            assert "unconfined" not in opt and "seccomp" not in opt.replace("no-new-privileges", ""), (name, opt)


def test_no_network_for_model_written_code_except_the_internal_database_network(cfg):
    for name in CODE_SERVICES - {"cp-db"}:
        s = svc(cfg, name)
        assert s.get("network_mode") == "none" and "networks" not in s, name
    for name in DB_SERVICES | {"cp-db"}:
        s = svc(cfg, name)
        assert s["networks"] == ["eqdb"] and "network_mode" not in s, name
    assert set(cfg["networks"]) == {"eqdb"}
    n = cfg["networks"]["eqdb"]
    assert n["internal"] is True and n["attachable"] is False and n["enable_ipv6"] is False and n["driver"] == "bridge"
    assert not {"external", "ipam", "driver_opts", "name"} & set(n)
    for name, s in cfg["services"].items():
        assert s.get("network_mode") not in ("host", "bridge", "default") and not str(s.get("network_mode", "")).startswith(("service:", "container:"))


def test_services_are_profiled_as_the_manifest_says(cfg):
    m = load_manifest(LIB / "TOOLS.toml")
    want = {"pf": ["core"], "cp": ["core"], "cr": ["core"], "node": ["node"], "rust": ["rust"], "go": ["go"], "julia": ["julia"],
            "haskell": ["haskell"], "jvm": ["jvm"], "pg": ["db"], "mongo": ["mongo"], "cp-db": ["db", "mongo"]}
    for name, p in want.items():
        assert svc(cfg, name)["profiles"] == p, name
    for i in m["image"]:
        if i["service"] in want and i["profile"] != "candidates":
            assert i["profile"] in want[i["service"]], (i["name"], i["service"])
    prof = {p["name"]: p for p in m["profile"]}
    assert prof["mongo"]["explicit"] == "yes"
    assert {n for n, s in cfg["services"].items() if "mongo" in s["profiles"]} == {"mongo", "cp-db"}


def test_images_come_only_from_interpolated_references_never_a_literal(cfg):
    for name, s in cfg["services"].items():
        assert re.fullmatch(r"\$\{EQ_IMAGE_[A-Z]+:\?[^}]+\}", s["image"]), (name, s["image"])


def test_the_only_host_mount_of_a_service_is_the_read_only_per_run_work_directory(cfg):
    for name, s in cfg["services"].items():
        vols = s.get("volumes", [])
        if name in DB_SERVICES:
            assert vols == [], name                                                           # databases mount nothing from the host
        for v in vols:
            assert isinstance(v, dict) and v["type"] == "bind", (name, v)                    # long syntax, never a named volume
            assert v["source"].startswith("${EQ_WORK_DIR:?") and v["read_only"] is True, (name, v)
            assert v["bind"]["create_host_path"] is False, (name, v)
            assert v["target"] == ("/eqsrc/work" if name in CHECK_SERVICES else "/work"), (name, v)
        assert len(vols) == (0 if name in DB_SERVICES else 1), name
    assert "docker.sock" not in COMPOSE.read_text() and "/var/run" not in COMPOSE.read_text()


def test_every_tmpfs_is_nosuid_nodev_and_size_capped_and_database_data_is_never_exec(cfg):
    for name, s in cfg["services"].items():
        assert s["tmpfs"], name
        for t in s["tmpfs"]:
            path, _, opts = t.partition(":")
            o = opts.split(",")
            assert path.startswith("/") and "nosuid" in o and "nodev" in o and any(x.startswith("size=") for x in o), (name, t)
            if name in DB_SERVICES:
                assert "noexec" in o and not ("exec" in o), (name, t)
        paths = [t.split(":")[0] for t in s["tmpfs"]]
        assert "/tmp" in paths, name
        if name in CHECK_SERVICES:
            assert "/work" in paths, name                                                     # the capped copy the harness's isolate() makes


def test_check_services_start_with_the_harness_copy_in_prefix_and_a_read_only_source(cfg):
    for name in CHECK_SERVICES:
        ep = svc(cfg, name)["entrypoint"]
        assert ep[:2] == ["/bin/sh", "-c"], name
        assert ep[2].replace("$$", "$") == HARNESS_COPY_IN, name
        assert ep[3:] == ["eq-run", "/eqsrc/work", "/work", "--"], name
    for name in LANG_SERVICES | DB_SERVICES:
        assert "entrypoint" not in svc(cfg, name), name                                       # no shell in these images
    assert svc(cfg, "pf")["command"] == ["bash", "check_lean.sh", "Answer.lean"]


def test_the_check_environment_is_the_harness_container_env(cfg):
    keys = {"LANG", "HOME", "TMPDIR", "UV_CACHE_DIR", "UV_OFFLINE", "UV_NO_CONFIG", "UV_PYTHON_DOWNLOADS"}
    for name in ("pf", "cp", "cr"):
        assert set(svc(cfg, name)["environment"]) == keys, name
    e = svc(cfg, "cp-db")["environment"]
    assert keys <= set(e) and e["EQ_PG_HOST"] == "pg" and e["EQ_MONGO_HOST"] == "mongo"          # reached by service name only
    assert not any(re.search(r"\d+\.\d+\.\d+\.\d+", str(v)) for v in e.values())


def test_the_database_password_is_only_ever_an_interpolation_and_never_a_literal(cfg):
    text = COMPOSE.read_text()
    assert not re.search(r"[0-9a-fA-F]{24,}", text), "a long hex string in compose.yaml"
    assert not re.search(r"(?im)^\s*(POSTGRES_PASSWORD|MONGO_INITDB_ROOT_PASSWORD|[A-Z_]*PASSWORD)\s*:\s*[^$\s]", text)
    for name in ("pg", "mongo", "cp-db"):
        assert svc(cfg, name)["environment"]["EQ_DB_PASSWORD"].startswith("${EQ_DB_PASSWORD:?"), name
    for name in set(cfg["services"]) - {"pg", "mongo", "cp-db"}:
        assert "EQ_DB_PASSWORD" not in svc(cfg, name).get("environment", {}), name           # the lang and core services never see it


def test_database_services_have_healthchecks_and_the_solver_waits_for_them(cfg):
    for name in DB_SERVICES:
        h = svc(cfg, name)["healthcheck"]
        assert h["test"][0] == "CMD" and h["retries"] >= 10, name
    d = svc(cfg, "cp-db")["depends_on"]
    assert d["pg"]["condition"] == "service_healthy" and d["mongo"]["condition"] == "service_healthy"
    assert d["pg"]["required"] is False and d["mongo"]["required"] is False                    # only the one(s) of the selected profile
    assert svc(cfg, "pg")["command"] == ["/opt/eq/entry-pg.sh"] and svc(cfg, "mongo")["command"] == ["/opt/eq/entry-mongo.sh"]
    for name in DB_SERVICES:
        assert svc(cfg, name)["user"] == "10002:10002"


# =========================================================================================================== static: compose.wall.yaml
def test_wall_overrides_add_exactly_one_tunnel_mount_to_code_services_only(cfg, wall):
    assert set(wall) <= {"services"} | {k for k in wall if k.startswith("x-")}
    assert set(wall["services"]) == CODE_SERVICES                                        # never a database server
    for name, o in wall["services"].items():
        assert set(o) == {"volumes"} and len(o["volumes"]) == 1, name                    # nothing else is overridden: no network, port, env
        v = o["volumes"][0]
        assert v["type"] == "bind" and v["target"] == "/eq/tunnel", name
        assert v["source"].startswith("${EQ_TUNNEL_CHANNEL:?") and "EQ_TUNNEL_DIR" not in v["source"] and v["bind"]["create_host_path"] is False, name
        assert "read_only" in v
    # compose merges `volumes` by target: the merged service has the work mount and the tunnel, nothing more
    for name in CODE_SERVICES:
        base = [x["target"] for x in svc(cfg, name)["volumes"]]
        assert sorted(base + ["/eq/tunnel"]) == sorted(set(base) | {"/eq/tunnel"}), name
        assert len(set(base + ["/eq/tunnel"])) == 2, name


def test_compose_yaml_names_the_channel_variable_the_wall_file_really_uses(wall):
    """N24#10: the header comment said ${EQ_TUNNEL_DIR} (the tunnel ROOT variable, never read by eq-compose.sh); the mount is one channel."""
    head = COMPOSE.read_text().split("\nservices:", 1)[0]
    assert "EQ_TUNNEL_DIR" not in head and "${EQ_TUNNEL_CHANNEL}, ONE channel directory, at /eq/tunnel" in head
    assert "EQ_TUNNEL_CHANNEL" in WALL.read_text()


def test_the_wall_file_says_which_document_decides_whether_the_tunnel_is_writable(wall):
    text = WALL.read_text()
    assert "WALL_DESIGN.md" in text and "channel" in text and "never the" in text        # names the document and the one-channel rule
    # the request/response directory (dir-v1) is written by the container; change it with the WALL document
    assert wall["services"]["pf"]["volumes"][0]["read_only"] is False
    assert "docker.sock" not in text and "network_mode" not in text


# ============================================================================================================= eq-compose.sh (fake docker)
@pytest.fixture
def core_lib(env, tmp_path):
    lib = fixture_lib(tmp_path, fill_all=True)
    env.docker()
    return lib


def eqc(env, lib, *args, **kw):
    return env.run("eq-compose.sh", *args, lib=lib, **kw)


def acts(env):
    """The compose actions of the run so far, in order (`version` calls are not recorded)."""
    return [e["act"] for e in env.compose_envs()]


def workdir(env, name="work"):
    w = env.t / name
    w.mkdir()
    return w


def test_config_validates_the_compose_files_with_the_selected_profiles_and_prints_no_secret(env, core_lib):
    r = eqc(env, core_lib, "config")
    assert r.returncode == 0 and "compose files OK (profiles: core)" in r.stdout, r.stdout + r.stderr
    cfg_calls = [c for c in env.composes() if "config" in c]
    assert len(cfg_calls) == 1 and vals(cfg_calls[0], "-f") == [str(core_lib / "compose.yaml")] and vals(cfg_calls[0], "-p") == ["eq-testrun"]
    e = env.compose_env()
    assert e["COMPOSE_PROFILES"] == "core" and e["EQ_IMAGE_PF"] == IMAGE_TAGS["min-both"] and e["EQ_IMAGE_CP"] == IMAGE_TAGS["min-py"]
    assert e["EQ_IMAGE_CR"] == e["EQ_IMAGE_CP"] and e["EQ_IMAGE_NODE"] == "eq-unselected:none"      # an unselected service cannot start
    assert env.runs() == [] and env.builds() == []


def test_config_for_the_database_profile_uses_a_placeholder_password(env, core_lib):
    r = eqc(env, core_lib, "--profiles", "db", "config")
    assert r.returncode == 0, r.stderr
    e = env.compose_env()
    assert e["COMPOSE_PROFILES"] == "core,db" and e["EQ_IMAGE_PG"] == IMAGE_TAGS["tc-pg"] and e["EQ_DB_PASSWORD_LEN"] == "24"


def test_profiles_all_is_every_profile_that_is_not_explicit_and_mongo_must_be_named(env, core_lib):
    assert eqc(env, core_lib, "--profiles", "all", "config").returncode == 0
    p = env.compose_env()["COMPOSE_PROFILES"].split(",")
    assert "mongo" not in p and "candidates" not in p and {"core", "node", "jvm", "db"} <= set(p)
    assert eqc(env, core_lib, "--profiles", "all,mongo", "config").returncode == 0
    assert "mongo" in env.compose_env()["COMPOSE_PROFILES"].split(",")


def test_core_is_always_part_of_the_selection(env, core_lib):
    assert eqc(env, core_lib, "--profiles", "node", "config").returncode == 0
    assert env.compose_env()["COMPOSE_PROFILES"] == "core,node"


@pytest.mark.parametrize("args", [(), ("bogus",), ("--bogus", "config"), ("--profiles", "nosuch", "config"), ("run",), ("--run-id",)])
def test_usage_errors_are_exit_2(env, core_lib, args):
    assert eqc(env, core_lib, *args).returncode == 2


def test_docker_missing_and_no_compose_plugin_are_exit_10(env, tmp_path):
    lib = fixture_lib(tmp_path, fill_all=True)
    assert eqc(env, lib, "config").returncode == 10                          # no docker shim on PATH
    env.docker()
    r = eqc(env, lib, "config", FAKE_NO_COMPOSE="1")
    assert r.returncode == 10 and "compose plugin" in r.stderr


def built_core(env, lib, extra=()):
    for i in ("min-both", "min-py", *extra):
        env.built_image(lib, i)


def test_run_verifies_the_tools_then_runs_one_service_and_always_removes_the_project(env, core_lib):
    built_core(env, core_lib)
    w = workdir(env)
    r = eqc(env, core_lib, "--work", str(w), "run", "pf")
    assert r.returncode == 0, r.stdout + r.stderr
    seq = acts(env)
    assert seq[-2:] == ["run", "down"], seq
    e = [x for x in env.compose_envs() if x["act"] == "run"][0]
    run_call = [c for c in env.composes() if "run" in c[:8]][0]
    assert run_call[-3:] == ["run", "--rm", "pf"] and vals(run_call, "-p") == ["eq-testrun"]
    down = [c for c in env.composes() if "down" in c][-1]
    assert "--volumes" in down and "--remove-orphans" in down
    assert any(a[:2] == ["cp", "-L"] for a in env.argv_log()), "the deep re-hash of every installed tool file ran before the run"
    assert env.runs() == [], "eq-compose starts nothing itself: only compose does"
    assert e["EQ_WORK_DIR"] == str(w) and e["EQ_IMAGE_PF"] == image_id_of(env, IMAGE_TAGS["min-both"])


def image_id_of(env, tag):
    """The ID the fake daemon holds for a tag (its images file: tag, id, size)."""
    for ln in (env.dstate / "images").read_text().splitlines():
        f = ln.split("\t")
        if f[0] == tag:
            return f[1]
    raise AssertionError(f"no image {tag} in the fake daemon")


def test_run_hands_compose_the_verified_image_id_not_the_tag(env, core_lib):
    """W4 (CWE-367): the tag was verified against the recorded ID, but compose re-resolves a tag at start; the ID cannot be re-pointed."""
    built_core(env, core_lib)
    r = eqc(env, core_lib, "--work", str(workdir(env)), "run", "pf")
    assert r.returncode == 0, r.stdout + r.stderr
    e = [x for x in env.compose_envs() if x["act"] == "run"][0]
    want = image_id_of(env, IMAGE_TAGS["min-both"])
    assert want.startswith("sha256:") and e["EQ_IMAGE_PF"] == want and e["EQ_IMAGE_PF"] != IMAGE_TAGS["min-both"]
    assert e["EQ_IMAGE_CP"] == e["EQ_IMAGE_CR"] == image_id_of(env, IMAGE_TAGS["min-py"])
    assert e["EQ_IMAGE_NODE"] == "eq-unselected:none"


def test_run_is_refused_for_an_image_without_a_verified_build(env, core_lib):
    env.built_image(core_lib, "min-both")                                   # min-py was never built here
    r = eqc(env, core_lib, "--work", str(workdir(env)), "run", "cp")
    assert r.returncode == 11 and "MISSING" in r.stdout
    assert "run" not in acts(env) and "up" not in acts(env)


def test_run_is_refused_for_a_stale_image(env, core_lib):
    built_core(env, core_lib)
    set_tool(core_lib / "TOOLS.toml", "jq", checksum_source="edited after the build")
    r = eqc(env, core_lib, "--work", str(workdir(env)), "run", "pf")
    assert r.returncode == 11 and "STALE" in r.stdout and "run" not in acts(env)


def test_run_is_refused_for_a_tampered_tool_file(env, core_lib):
    env.built_image(core_lib, "min-both", tamper=("/opt/lean/bin/lean", "evil"))
    env.built_image(core_lib, "min-py")
    r = eqc(env, core_lib, "--work", str(workdir(env)), "run", "pf")
    assert r.returncode == 11 and "DEEP" in r.stdout and "run" not in acts(env)


def test_no_deep_skips_the_host_side_rehash_only(env, core_lib):
    built_core(env, core_lib)
    r = eqc(env, core_lib, "--no-deep", "--work", str(workdir(env)), "run", "pf")
    assert r.returncode == 0 and not any(a[:2] == ["cp", "-L"] for a in env.argv_log())


def test_a_failing_compose_run_still_removes_the_project_and_keeps_its_exit_code(env, core_lib):
    built_core(env, core_lib)
    r = eqc(env, core_lib, "--work", str(workdir(env)), "run", "pf", FAKE_COMPOSE_FAIL="1")
    assert r.returncode == 1 and acts(env)[-1] == "down"


def test_up_ps_logs_and_down_are_passed_through(env, core_lib):
    built_core(env, core_lib)
    assert eqc(env, core_lib, "--work", str(workdir(env)), "up", "-d").returncode == 0
    assert "up" in acts(env) and acts(env)[-1] == "down"
    assert eqc(env, core_lib, "ps").returncode == 0 and acts(env)[-1] == "ps"
    assert eqc(env, core_lib, "down").returncode == 0
    assert env.composes()[-1][-2:] == ["--volumes", "--remove-orphans"]


def test_the_database_credential_is_generated_per_run_never_in_argv_or_a_file(env, core_lib):
    built_core(env, core_lib, ("tc-pg",))
    shas, lens = [], []
    for k in range(2):
        r = eqc(env, core_lib, "--profiles", "db", "--work", str(workdir(env, f"w{k}")), "run", "cp-db")
        assert r.returncode == 0, r.stdout + r.stderr
        e = [x for x in env.compose_envs() if x["act"] == "run"][k]
        shas.append(e["EQ_DB_PASSWORD_SHA256"])
        lens.append(e["EQ_DB_PASSWORD_LEN"])
    assert lens == ["48", "48"] and shas[0] != shas[1]                          # 24 random bytes, fresh for each run
    for a in env.argv_log():
        assert not [x for x in a if re.fullmatch(r"[0-9a-f]{48}", x)], a        # never on a command line
    for f in list(env.state.rglob("*")) + list(env.t.glob("*.log")):
        if f.is_file():
            assert not re.search(r"\b[0-9a-f]{48}\b", f.read_text(errors="ignore")), f


def test_without_a_database_profile_no_real_credential_exists(env, core_lib):
    built_core(env, core_lib)
    assert eqc(env, core_lib, "--work", str(workdir(env)), "run", "pf").returncode == 0
    run_e = [x for x in env.compose_envs() if x["act"] == "run"][0]
    assert run_e["EQ_DB_PASSWORD_LEN"] != "48"


@pytest.mark.parametrize("make", ["relative", "missing", "symlink", "home", "ancestor_of_home", "comma", "file"])
def test_the_work_directory_must_be_a_plain_absolute_directory_you_own(env, core_lib, make):
    built_core(env, core_lib)
    target = env.t / "real"
    target.mkdir()
    arg = {"relative": "work", "missing": str(env.t / "nope"), "home": str(env.home), "ancestor_of_home": str(env.t),
           "comma": str(env.t / "a,b"), "file": str(env.t / "afile"), "symlink": str(env.t / "link")}[make]
    if make == "comma":
        (env.t / "a,b").mkdir()
    if make == "file":
        (env.t / "afile").write_text("x")
    if make == "symlink":
        os.symlink(target, env.t / "link")
    r = eqc(env, core_lib, "--work", arg, "run", "pf")
    assert r.returncode == 2 and "run" not in acts(env), (make, r.stderr)


def test_run_without_a_work_directory_is_a_usage_error(env, core_lib):
    built_core(env, core_lib)
    r = eqc(env, core_lib, "run", "pf")
    assert r.returncode == 2 and "needs --work" in r.stderr


def make_tunnel(env, run_id="run1"):
    """The layout eq_wall.open_channel creates under a tunnel ROOT: <root>/<run_id>/c<32 hex>/.channel.json (0700 dirs), plus a sibling
    channel whose token must stay invisible. Returns (root, run_dir, channel_dir, sibling_dir)."""
    root = env.t / "tunroot"
    run = root / run_id
    run.mkdir(parents=True)
    dirs = []
    for k in range(2):
        c = run / ("c" + f"{k:032x}")
        c.mkdir(mode=0o700)
        c.chmod(0o700)
        (c / ".channel.json").write_text('{"schema":"eqwall.channel.v1","token":"secret-%d"}\n' % k)
        dirs.append(c)
    for d in (root, run):
        d.chmod(0o700)
    return root, run, dirs[0], dirs[1]


def test_no_tunnel_by_default_and_exactly_the_wall_file_with_one_channel(env, core_lib):
    assert eqc(env, core_lib, "config").returncode == 0
    assert vals(env.composes()[-1], "-f") == [str(core_lib / "compose.yaml")]
    assert env.compose_env()["EQ_TUNNEL_CHANNEL"] == ""
    root, run, ch, sibling = make_tunnel(env)
    assert eqc(env, core_lib, "--tunnel", str(ch), "config").returncode == 0
    assert vals(env.composes()[-1], "-f") == [str(core_lib / "compose.yaml"), str(core_lib / "compose.wall.yaml")]
    assert env.compose_env()["EQ_TUNNEL_CHANNEL"] == str(ch)


def test_the_tunnel_root_in_the_environment_is_never_a_default_and_never_mounted(env, core_lib):
    # EQ_TUNNEL_DIR is the tunnel ROOT the harness and the installer use: it must neither turn the tunnel on nor reach compose
    root, run, ch, sibling = make_tunnel(env)
    assert eqc(env, core_lib, "config", EQ_TUNNEL_DIR=str(root)).returncode == 0
    assert vals(env.composes()[-1], "-f") == [str(core_lib / "compose.yaml")]
    assert env.compose_env()["EQ_TUNNEL_CHANNEL"] == ""
    assert eqc(env, core_lib, "--tunnel", str(ch), "config", EQ_TUNNEL_DIR=str(root)).returncode == 0
    assert env.compose_env()["EQ_TUNNEL_CHANNEL"] == str(ch) != str(root)


@pytest.mark.parametrize("which", ["root", "run_dir", "sibling_name_wrong", "no_channel_file", "channel_file_symlink", "holds_a_subdirectory",
                                   "uppercase_hex", "short_name", "channels_parent_of_root"])
def test_only_one_channel_directory_may_be_mounted_never_the_root(env, core_lib, which):
    # fails before the fix: eq-compose.sh accepted any 0700 directory, so the tunnel ROOT (every channel's token) was mounted
    root, run, ch, sibling = make_tunnel(env)
    if which == "root":
        arg = root
    elif which == "run_dir":
        arg = run
    elif which == "sibling_name_wrong":
        arg = ch.rename(run / ("x" * 33))
    elif which == "no_channel_file":
        (ch / ".channel.json").unlink()
        arg = ch
    elif which == "channel_file_symlink":
        (ch / ".channel.json").unlink()
        os.symlink(sibling / ".channel.json", ch / ".channel.json")
        arg = ch
    elif which == "holds_a_subdirectory":
        (ch / "sub").mkdir()
        arg = ch
    elif which == "uppercase_hex":
        arg = ch.rename(run / ("c" + "A" * 32))
        (arg / ".channel.json").write_text("{}")
    elif which == "short_name":
        arg = ch.rename(run / ("c" + "a" * 31))
    else:
        arg = run.parent.parent
    r = eqc(env, core_lib, "--tunnel", str(arg), "config")
    assert r.returncode == 2 and not any("config" in c for c in env.composes()), (which, r.stdout, r.stderr)
    assert env.compose_envs() == [] or env.compose_envs()[-1]["EQ_TUNNEL_CHANNEL"] == ""
    if which in ("root", "run_dir"):
        assert "ONE channel directory" in r.stderr


def test_a_run_with_the_tunnel_mounts_only_the_named_channel(env, core_lib):
    built_core(env, core_lib)
    root, run, ch, sibling = make_tunnel(env)
    r = eqc(env, core_lib, "--tunnel", str(ch), "--work", str(workdir(env)), "run", "pf")
    assert r.returncode == 0, r.stdout + r.stderr
    e = [x for x in env.compose_envs() if x["act"] == "run"][0]
    assert e["EQ_TUNNEL_CHANNEL"] == str(ch) and str(sibling) not in e.values() and str(root) not in e.values()


def test_tunnel_with_up_is_refused_before_anything_starts(env, core_lib):
    """W3 (CWE-362): `--tunnel C up` would start every service of the profiles on ONE channel; only `run SERVICE` is one container per channel."""
    built_core(env, core_lib)
    root, run, ch, sibling = make_tunnel(env)
    r = eqc(env, core_lib, "--tunnel", str(ch), "--work", str(workdir(env)), "up")
    assert r.returncode == 2 and "only with 'run SERVICE'" in r.stderr, r.stdout + r.stderr
    assert not any("up" in c for c in env.composes()), env.composes()
    assert env.compose_envs() == [] and not any(a[:2] == ["cp", "-L"] for a in env.argv_log()), "refused before verify-tools and compose"
    assert eqc(env, core_lib, "--work", str(workdir(env, "work2")), "up").returncode == 0, "up without a tunnel stays allowed"


@pytest.mark.parametrize("make", ["mode_755", "symlink", "relative", "home", "missing"])
def test_the_tunnel_directory_must_be_0700_owned_and_plain(env, core_lib, make):
    root, run, real, sibling = make_tunnel(env)
    arg = {"mode_755": str(real), "symlink": str(env.t / "tlink"), "relative": real.name, "home": str(env.home), "missing": str(env.t / "x")}[make]
    if make == "mode_755":
        real.chmod(0o755)
    if make == "symlink":
        os.symlink(real, env.t / "tlink")
    r = eqc(env, core_lib, "--tunnel", arg, "config")
    assert r.returncode == 2 and "tunnel directory" in r.stderr and not any("config" in c for c in env.composes()), (make, r.stderr)


def test_eq_compose_mounts_nothing_itself_and_does_not_pass_the_host_environment(env, core_lib):
    text = (LIB / "eq-compose.sh").read_text()
    code = "\n".join(ln for ln in text.splitlines() if not ln.lstrip().startswith("#"))
    assert "--mount" not in code and "-v " not in code and "docker.sock" not in code and "--privileged" not in code
    assert "docker run" not in code and "--env-file" not in code
    assert "-e " not in code or "echo -e" in code
