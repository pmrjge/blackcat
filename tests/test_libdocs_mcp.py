"""Tests for dot-config/dot-claude/mcp/libdocs_mcp.py: SSRF guard on every fetch that is not a fixed API endpoint.

Run: uv run --with pytest --with httpx --with "mcp>=1.10,<2" pytest -q tests/test_libdocs_mcp.py
No network: every request goes through an httpx.MockTransport; DNS is a stub. HOME and LIBDOCS_CACHE are temp dirs.
"""
import asyncio
import importlib.util
import sys
from pathlib import Path

import httpx
import pytest

MODULE = Path(__file__).resolve().parents[1] / "dot-config" / "dot-claude" / "mcp" / "libdocs_mcp.py"
BODY = "# Guide\n" + "some documentation text. " * 20


@pytest.fixture
def mod(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("LIBDOCS_CACHE", str(tmp_path / "cache"))
    monkeypatch.setenv("STACK_ENV_FILE", str(tmp_path / "none.env"))
    spec = importlib.util.spec_from_file_location("libdocs_under_test", MODULE)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    m.dns = {"docs.example.test": ["93.184.216.34"]}
    m.resolved = []
    m.seen = []

    async def resolve(host):
        m.resolved.append(host)
        return m.dns.get(host, [])

    def handler(req):
        m.seen.append(req)
        return m.routes(req)

    m.routes = lambda req: httpx.Response(200, text=BODY, headers={"content-type": "text/plain"})
    monkeypatch.setattr(m, "_resolve_host", resolve)
    monkeypatch.setattr(m, "_TRANSPORT", httpx.MockTransport(handler))
    yield m
    sys.modules.pop("libdocs_under_test", None)


def fetch(m, url):
    async def go():
        async with m._client() as c:
            return await m._fetch_raw(c, url)
    return asyncio.run(go())


@pytest.mark.parametrize("url", [
    "http://docs.example.test/llms.txt",
    "https://127.0.0.1/",
    "https://localhost/",
    "https://app.localhost/",
    "https://printer.local/",
    "https://169.254.169.254/latest/meta-data",
    "https://[::ffff:127.0.0.1]/",
    "https://[::1]/",
    "https://2130706433/",
    "https://0177.0.0.1/",
    "https://0x7f.1/",
])
def test_refused_urls_never_reach_the_network(mod, url):
    with pytest.raises(ValueError, match="refusing"):
        asyncio.run(mod._guarded_get(url))
    assert fetch(mod, url) is None
    assert mod.seen == [] and mod.resolved == []


@pytest.mark.parametrize("ip", ["10.0.0.5", "127.0.0.1", "169.254.169.254", "::ffff:10.0.0.5", "fd00::1"])
def test_public_looking_name_resolving_to_a_private_address_is_refused(mod, ip):
    mod.dns["evil.example.test"] = ["93.184.216.34", ip]        # one bad address is enough
    with pytest.raises(ValueError, match="non-public"):
        asyncio.run(mod._guarded_get("https://evil.example.test/x.md"))
    assert mod.seen == []


def test_unresolvable_name_is_refused(mod):
    with pytest.raises(ValueError, match="does not resolve"):
        asyncio.run(mod._guarded_get("https://nowhere.example.test/"))


def test_allowed_request_goes_to_the_checked_ip_with_host_and_sni(mod):
    status, ct, text = asyncio.run(mod._guarded_get("https://docs.example.test:8443/a/llms.txt?v=1#frag"))
    assert status == 200 and text == BODY
    (r,) = mod.seen
    assert (r.url.host, r.url.port, r.url.path, r.url.query) == ("93.184.216.34", 8443, "/a/llms.txt", b"v=1")
    assert r.headers["host"] == "docs.example.test:8443" and r.extensions["sni_hostname"] == "docs.example.test"
    assert mod.resolved == ["docs.example.test"]


def test_ipv6_address_is_pinned_in_brackets(mod):
    mod.dns["v6.example.test"] = ["2606:2800:220:1:248:1893:25c8:1946"]
    asyncio.run(mod._guarded_get("https://v6.example.test/"))
    (r,) = mod.seen
    assert r.url.host == "2606:2800:220:1:248:1893:25c8:1946" and r.headers["host"] == "v6.example.test"
    assert r.extensions["sni_hostname"] == "v6.example.test"


def test_fetch_raw_of_a_docs_page_is_guarded_and_pinned(mod):
    assert fetch(mod, "https://docs.example.test/llms.txt") == BODY
    assert mod.seen[0].url.host == "93.184.216.34"


@pytest.mark.parametrize("target,dns", [
    ("https://127.0.0.1/", {}),
    ("https://metadata.example.test/x", {"metadata.example.test": ["169.254.169.254"]}),
    ("http://docs.example.test/x", {}),
    ("https://[::ffff:169.254.169.254]/", {}),
])
def test_redirect_to_a_forbidden_target_is_refused(mod, target, dns):
    mod.dns.update(dns)
    mod.routes = lambda req: httpx.Response(302, headers={"location": target})
    with pytest.raises(ValueError, match="refusing"):
        asyncio.run(mod._guarded_get("https://docs.example.test/start"))
    assert len(mod.seen) == 1                                      # the hop itself was never requested
    assert fetch(mod, "https://docs.example.test/start") is None


def test_relative_redirects_are_followed_and_rechecked(mod):
    mod.routes = lambda req: (httpx.Response(301, headers={"location": "/final"}) if req.url.path == "/start"
                              else httpx.Response(200, text=BODY))
    status, _, _ = asyncio.run(mod._guarded_get("https://docs.example.test/start"))
    assert status == 200 and [r.url.path for r in mod.seen] == ["/start", "/final"]
    assert mod.resolved == ["docs.example.test"] * 2


def test_redirect_loop_stops_after_five_hops(mod):
    mod.routes = lambda req: httpx.Response(302, headers={"location": "/again"})
    with pytest.raises(ValueError, match="too many redirects"):
        asyncio.run(mod._guarded_get("https://docs.example.test/start"))
    assert len(mod.seen) == 6


def test_size_cap(mod):
    mod.routes = lambda req: httpx.Response(200, content=b"x" * 9_000_000)
    _, _, text = asyncio.run(mod._guarded_get("https://docs.example.test/big.txt"))
    assert len(text) == 8_000_000


def test_fixed_endpoints_skip_the_guard_and_do_not_follow_redirects(mod):
    mod.routes = lambda req: httpx.Response(302, headers={"location": "https://127.0.0.1/"})
    assert fetch(mod, "https://raw.githubusercontent.com/o/r/HEAD/README.md") is None
    assert [r.url.host for r in mod.seen] == ["raw.githubusercontent.com"] and mod.resolved == []

    async def go():
        async with mod._client() as c:
            return await mod._get_json(c, "https://pypi.org/pypi/x/json")
    assert asyncio.run(go()) is None and mod.seen[-1].url.host == "pypi.org"


def test_toc_links_to_another_origin_are_dropped(mod):
    txt = ("- [Intro](https://docs.example.test/intro.md): start\n"
           "- [Evil](https://evil.example.test/x.md)\n- [Local](https://127.0.0.1/x.md)\n"
           "- [Other port](https://docs.example.test:8443/x.md)\n- [Plain](http://docs.example.test/x.md)\n")
    assert mod._toc(txt, "https://docs.example.test/llms.txt") == [("Intro start", "https://docs.example.test/intro.md")]


def test_jina_only_gets_https_urls_that_pass_the_string_checks(mod):
    async def go(url):
        async with mod._client() as c:
            return await mod._jina(c, url)
    for url in ("http://docs.example.test/", "https://127.0.0.1/", "https://localhost/x", "https://[::1]/"):
        assert asyncio.run(go(url)) is None
    assert mod.seen == []
    mod.routes = lambda req: httpx.Response(200, json={"data": {"title": "T", "content": "c"}})
    assert asyncio.run(go("https://docs.example.test/")) == ("T", "c")
    assert mod.seen[0].url.host == "r.jina.ai"


def test_index_library_docs_refuses_a_local_start_url(mod, monkeypatch):
    monkeypatch.setenv("SPIDER_API_KEY", "k")
    mod.routes = lambda req: httpx.Response(200, json={"info": {"name": "x", "version": "1", "project_urls": {}}})
    out = asyncio.run(mod.index_library_docs("pypi:x", start_url="https://127.0.0.1:8000/docs/"))
    assert "Refused" in out and all(r.url.host != "127.0.0.1" for r in mod.seen)
    assert not any("spider" in r.url.host for r in mod.seen)
