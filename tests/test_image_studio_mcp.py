"""Tests for dot-config/dot-claude/mcp/image_studio_mcp.py: SVG and edits through OpenRouter, raster images through
Opper, the model of each tool set in stack.env and checked against the provider's own model catalog;
inputs under the size limit; each key only to its own provider; files kept safe.

Run: uv run --with pytest --with httpx --with pillow --with "mcp>=1.10,<2" pytest -q tests/test_image_studio_mcp.py
No network: every request goes through an httpx.MockTransport. HOME is a temp dir.
"""
import asyncio
import base64
import copy
import importlib.util
import io
import json
import os
import re
import struct
import subprocess
import sys
import zlib
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "dot-config" / "dot-claude" / "mcp" / "image_studio_mcp.py"
OP, OR = "https://opper.test", "https://openrouter.test/api/v1"
KEYS = {"opper.test": "op-test-2", "openrouter.test": "sk-or-test-3"}
SVG = (b'<?xml version="1.0"?>\n<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1024 1024" '
       b'width="1024" height="1024" onload="alert(1)"><script>alert(2)</script>'
       b'<a href="javascript:alert(3)"><path d="M0 0h10v10z" fill="#1A73E8"/></a>'
       b'<path d="M5 5h1v1z" fill="#ffffff"/></svg>')
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
RECRAFT, RIVERFLOW, GPT = "recraft/recraft-v4.1-pro-vector", "sourceful/riverflow-v2.5-pro", "openai/gpt-image-2.5-sunburst"
# OpenRouter's catalog entries as read on 27 September 2026 (GET /images/models/{id}/endpoints).
RECRAFT_EP = {"id": RECRAFT, "endpoints": [{
    "provider_name": "Recraft", "provider_slug": "recraft", "provider_tag": "recraft",
    "supported_parameters": {"aspect_ratio": {"type": "enum", "values": ["1:1", "4:3", "3:4", "16:9", "9:16", "auto"]},
                             "output_format": {"type": "enum", "values": ["svg"]},
                             "n": {"type": "range", "min": 1, "max": 6},
                             "input_references": {"type": "range", "min": 0, "max": 1}},
    "allowed_passthrough_parameters": ["style", "controls", "text_layout"], "supports_streaming": False,
    "pricing": [{"billable": "output_image", "unit": "image", "cost_usd": 0.3}]}]}
RIVERFLOW_EP = {"id": RIVERFLOW, "endpoints": [{
    "provider_name": "Sourceful", "provider_slug": "sourceful", "provider_tag": "sourceful",
    "supported_parameters": {"resolution": {"type": "enum", "values": ["1K", "2K", "4K"]},
                             "aspect_ratio": {"type": "enum", "values": ["1:1", "4:3", "3:4", "3:2", "2:3", "16:9", "9:16", "21:9", "auto"]},
                             "output_format": {"type": "enum", "values": ["png", "jpeg", "webp"]},
                             "background": {"type": "enum", "values": ["auto", "transparent", "opaque"]},
                             "n": {"type": "range", "min": 1, "max": 1},
                             "input_references": {"type": "range", "min": 0, "max": 10}},
    "allowed_passthrough_parameters": ["font_inputs"], "supports_streaming": False,
    "pricing": [{"billable": "output_image", "unit": "image", "cost_usd": 0.13},
                {"billable": "output_image", "unit": "image", "cost_usd": 0.15, "variant": "2k"},
                {"billable": "output_image", "unit": "image", "cost_usd": 0.17, "variant": "4k"}]}]}
# Opper's catalog entry (GET /v3/images/models?q=gpt-image-2.5), trimmed to the fields the server reads.
GPT_ENTRY = {"id": GPT, "type": "image", "name": "GPT Image 2.5 Sunburst", "capabilities": ["image_generation", "image_edit"],
             "cost": 0.211, "params": {"image": {
                 "sizes": ["1024x1024", "1536x1024", "1024x1536", "auto"],
                 "qualities": ["low", "medium", "high", "xhigh", "max", "auto"], "default": "1024x1024",
                 "size_constraints": {"multiple_of": 16, "max_edge": 3840, "max_ratio": 3, "min_pixels": 655360,
                                      "max_pixels": 8294400},
                 "parameters": [{"name": "output_format", "type": "string", "enum": ["png", "jpeg", "webp"]},
                                {"name": "output_compression", "type": "integer"},
                                {"name": "background", "type": "string", "enum": ["auto", "opaque", "transparent"]},
                                {"name": "moderation", "type": "string", "enum": ["auto", "low"]}]}},
             "pricing": {"billing_unit": "per_mtok", "image_output": [30]}}
OR_POST = "POST " + OR + "/images"
GPT_POST = "POST " + OP + "/v3/images"
OPPER_MODELS = "GET " + OP + "/v3/images/models"


def discovery(model):
    return "GET %s/images/models/%s/endpoints" % (OR, model)


def catalog(*entries):
    return lambda req: httpx.Response(200, json={"models": list(entries), "total": len(entries), "offset": 0, "limit": 100})


@pytest.fixture
def home(tmp_path, monkeypatch):
    h = tmp_path / "home"
    h.mkdir()
    monkeypatch.setenv("HOME", str(h))
    for k in ("CLAUDE_CONFIG_DIR", "OPPER_API_KEY", "OPENROUTER_API_KEY", "IMAGE_STUDIO_MAX_UPLOAD_MB",
              "OPENROUTER_IMAGE_OUT_DIR", "STACK_IMAGE_MAX_PX", "IMAGE_STUDIO_TIMEOUT", "IMAGE_STUDIO_SVG_MODEL",
              "IMAGE_STUDIO_IMAGE_MODEL", "IMAGE_STUDIO_EDIT_MODEL"):
        monkeypatch.delenv(k, raising=False)
    env_file = tmp_path / "stack.env"
    env_file.write_text("export OPPER_API_KEY=%s # test\nOPENROUTER_API_KEY='%s'\n"
                        % (KEYS["opper.test"], KEYS["openrouter.test"]))
    monkeypatch.setenv("STACK_ENV_FILE", str(env_file))
    monkeypatch.setenv("OPPER_BASE_URL", OP + "/")
    monkeypatch.setenv("OPENROUTER_BASE_URL", OR)
    monkeypatch.setenv("IMAGE_STUDIO_OUT_DIR", str(tmp_path / "out"))
    return h


def load(name="image_studio_mcp_under_test"):
    spec = importlib.util.spec_from_file_location(name, MODULE)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


@pytest.fixture
def mod(home, monkeypatch):
    m = load()
    clock = {"t": 0.0}

    async def no_sleep(seconds):
        clock["t"] += seconds

    async def public(host):
        return ["93.184.216.34"]

    monkeypatch.setattr(m, "_sleep", no_sleep)
    monkeypatch.setattr(m, "_now", lambda: clock["t"])
    monkeypatch.setattr(m, "_resolve", public)
    yield m
    sys.modules.pop("image_studio_mcp_under_test", None)


class Api:
    """Answers each 'METHOD url' (query ignored): queued responses first, then the catalogs, which
    answer every time. Records every request; `paid` = the POSTs that make images."""

    def __init__(self, routes, sticky):
        self.routes = {k: list(v) for k, v in routes.items()}
        self.sticky = dict(sticky)
        self.requests = []

    @staticmethod
    def _url(request):
        """The request URL with a pinned IP host turned back into the name it was pinned for."""
        sni = request.extensions.get("sni_hostname")
        return request.url.copy_with(host=sni) if sni else request.url

    def __call__(self, request):
        self.requests.append(request)
        key = "%s %s" % (request.method, str(self._url(request)).split("?")[0])
        if self.routes.get(key):
            r = self.routes[key].pop(0)
        elif key in self.sticky:
            r = self.sticky[key]
        else:
            raise AssertionError("unexpected request: " + key)
        return r(request) if callable(r) else r

    def bodies(self, key):
        return [json.loads(r.content) for r in self.requests
                if "%s %s" % (r.method, str(self._url(r)).split("?")[0]) == key]

    @property
    def paid(self):
        return [r for r in self.requests if r.method == "POST"]


def mount(m, routes=None, sticky=None):
    base = {discovery(RECRAFT): lambda req: httpx.Response(200, json=RECRAFT_EP),
            discovery(RIVERFLOW): lambda req: httpx.Response(200, json=RIVERFLOW_EP),
            OPPER_MODELS: catalog(GPT_ENTRY)}
    base.update(sticky or {})
    api = Api(routes or {}, base)
    m._TRANSPORT = httpx.MockTransport(api)
    return api


def call(coro):
    res = asyncio.run(coro)
    return json.loads(res if isinstance(res, str) else res[0]), res


def b64(data):
    return base64.b64encode(data).decode()


def or_ok(*items, cost=0.3):
    return httpx.Response(200, json={"created": 1, "data": list(items), "usage": {"completion_tokens": 4175, "cost": cost}})


def or_item(data, media="image/svg+xml"):
    d = {"b64_json": b64(data)}
    if media:
        d["media_type"] = media
    return d


def endpoint(model, params, passthrough=(), price=None, slug="acme"):
    ep = {"provider_slug": slug, "supported_parameters": params, "allowed_passthrough_parameters": list(passthrough)}
    if price is not None:
        ep["pricing"] = [{"billable": "output_image", "unit": "image", "cost_usd": price}]
    return lambda req: httpx.Response(200, json={"id": model, "endpoints": [ep]})


def real_png(w, h, noise=False):
    raw = b"".join(b"\x00" + (os.urandom(w * 3) if noise else bytes((x * 7 + y) % 256 for x in range(w) for _ in range(3)))
                   for y in range(h))

    def chunk(k, d):
        return struct.pack(">I", len(d)) + k + d + struct.pack(">I", zlib.crc32(k + d) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 1)) + chunk(b"IEND", b""))


def jpeg(w=64, h=48):
    from PIL import Image as PILImage
    buf = io.BytesIO()
    PILImage.new("RGB", (w, h), (10, 120, 200)).save(buf, "JPEG")
    return buf.getvalue()


def webp():
    from PIL import Image as PILImage
    buf = io.BytesIO()
    PILImage.new("RGB", (32, 32)).save(buf, "WEBP")
    return buf.getvalue()


def decoded_size(url):
    from PIL import Image as PILImage
    return PILImage.open(io.BytesIO(base64.b64decode(url.split(",", 1)[1]))).size


# ---------------------------------------------------------------- generate_svg: OpenRouter, Recraft by default
def test_svg_defaults_to_recraft_through_openrouter(mod, tmp_path):
    api = mount(mod, {OR_POST: [or_ok(or_item(SVG), or_item(SVG), cost=0.6)]})
    out, _ = call(mod.generate_svg("minimal fox logo, flat", aspect_ratio="16:9", n=2, name="Fox Logo"))
    assert api.bodies(OR_POST) == [{"model": RECRAFT, "prompt": "minimal fox logo, flat", "n": 2,
                                    "aspect_ratio": "16:9", "output_format": "svg"}]
    assert [r.method for r in api.requests] == ["GET", "POST"]                   # the catalog, then the image
    get, post = api.requests
    assert "authorization" not in get.headers                                   # the public catalog: no key
    assert post.headers["authorization"] == "Bearer " + KEYS["openrouter.test"]
    assert out["model"] == RECRAFT and out["provider"] == "openrouter" and out["format"] == "svg"
    assert out["cost_usd"] == 0.6 and out["estimated_cost_usd"] == 0.6
    first = out["images"][0]
    assert len(out["images"]) == 2 and "fox-logo" in first["path"] and Path(first["path"]).parent == tmp_path / "out"
    assert first["viewBox"] == "0 0 1024 1024" and first["paths"] == 2 and first["colors"] == 2
    saved = Path(first["path"]).read_text()
    assert "<script" not in saved and "onload" not in saved and "javascript:" not in saved
    assert first["sanitized"].startswith("removed 3")


def test_without_an_aspect_ratio_the_model_picks(mod):
    api = mount(mod, {OR_POST: [or_ok(or_item(SVG)), or_ok(or_item(SVG))]})
    call(mod.generate_svg("badge"))
    call(mod.generate_svg("badge 2"))
    assert api.bodies(OR_POST)[0] == {"model": RECRAFT, "prompt": "badge", "n": 1, "output_format": "svg"}
    assert [r.method for r in api.requests] == ["GET", "POST", "POST"]          # the catalog is read once


def test_the_svg_model_comes_from_stack_env(mod, monkeypatch):
    monkeypatch.setenv("IMAGE_STUDIO_SVG_MODEL", "recraft/recraft-v4.1-vector")
    params = {"aspect_ratio": {"type": "enum", "values": ["1:1", "16:9"]}, "output_format": {"type": "enum", "values": ["svg"]},
              "n": {"type": "range", "min": 1, "max": 6}}
    api = mount(mod, {OR_POST: [or_ok(or_item(SVG), cost=0.08)]},
                {discovery("recraft/recraft-v4.1-vector"): endpoint("recraft/recraft-v4.1-vector", params, ["controls"], 0.08, "recraft")})
    out, _ = call(mod.generate_svg("icon", colors=["#000"]))
    body = api.bodies(OR_POST)[0]
    assert body["model"] == "recraft/recraft-v4.1-vector" and out["model"] == "recraft/recraft-v4.1-vector"
    assert body["provider"] == {"options": {"recraft": {"controls": {"colors": [{"rgb": [0, 0, 0]}]}}}}
    assert out["estimated_cost_usd"] == 0.08


def test_a_model_that_cannot_make_svg_is_refused_before_paying(mod, monkeypatch):
    monkeypatch.setenv("IMAGE_STUDIO_SVG_MODEL", "black-forest-labs/flux.2-pro")
    params = {"output_format": {"type": "enum", "values": ["png", "jpeg", "webp"]}}
    api = mount(mod, sticky={discovery("black-forest-labs/flux.2-pro"): endpoint("black-forest-labs/flux.2-pro", params)})
    with pytest.raises(ValueError, match="can't make SVG .png, jpeg, webp."):
        call(mod.generate_svg("logo"))
    assert api.paid == []


def test_unknown_or_malformed_models_are_refused_before_paying(mod, monkeypatch):
    monkeypatch.setenv("IMAGE_STUDIO_SVG_MODEL", "nobody/nothing")
    api = mount(mod, sticky={discovery("nobody/nothing"): lambda req: httpx.Response(404, json={"error": {"message": "not found"}})})
    with pytest.raises(ValueError, match="IMAGE_STUDIO_SVG_MODEL=nobody/nothing isn't an OpenRouter image model"):
        call(mod.generate_svg("logo"))
    for bad in ("two words", "../../v1/keys", "a//b"):
        monkeypatch.setenv("IMAGE_STUDIO_SVG_MODEL", bad)
        with pytest.raises(ValueError, match="isn't a model id"):
            call(mod.generate_svg("logo"))
    assert api.paid == [] and len(api.requests) == 1


@pytest.mark.parametrize("kw, words", [
    ({"aspect_ratio": "21:9"}, "aspect_ratio for recraft/recraft-v4.1-pro-vector must be one of 1:1, 4:3"),
    ({"n": 7}, "n for recraft/recraft-v4.1-pro-vector must be 1-6"), ({"n": 11}, "n must be 1-10"),
    ({"n": 0}, "n must be 1-10"), ({"colors": ["blue"]}, "hex color"), ({"prompt": "  "}, "prompt is empty"),
    ({"reference_image": "ftp://x/y.png"}, "local path or an https URL"),
])
def test_bad_svg_arguments_cost_nothing(mod, kw, words):
    api = mount(mod)
    with pytest.raises(ValueError, match=words):
        call(mod.generate_svg(**dict({"prompt": "logo"}, **kw)))
    assert api.paid == []


def test_the_palette_goes_to_recraft_controls(mod):
    api = mount(mod, {OR_POST: [or_ok(or_item(SVG))]})
    call(mod.generate_svg("clean vector badge", colors=["#1A73E8", "fff"], background_color="#000000"))
    assert api.bodies(OR_POST)[0]["provider"] == {"options": {"recraft": {"controls": {
        "colors": [{"rgb": [26, 115, 232]}, {"rgb": [255, 255, 255]}], "background_color": {"rgb": [0, 0, 0]}}}}}


def test_a_refused_palette_goes_into_the_prompt_once(mod):
    api = mount(mod, {OR_POST: [httpx.Response(400, json={"error": {"message": "invalid controls: colors"}}), or_ok(or_item(SVG))]})
    out, _ = call(mod.generate_svg("badge", colors=["#ff0000"], background_color="#ffffff"))
    first, second = api.bodies(OR_POST)
    assert "provider" in first and "provider" not in second
    assert second["prompt"] == "badge. Use color palette #ff0000; background color #ffffff."
    assert len(out["images"]) == 1 and "palette went into the prompt" in out["notes"][0]


def test_a_model_without_a_palette_option_gets_the_palette_in_words(mod, monkeypatch):
    monkeypatch.setenv("IMAGE_STUDIO_SVG_MODEL", "acme/vector-x")
    params = {"output_format": {"type": "enum", "values": ["svg", "png"]}}
    api = mount(mod, {OR_POST: [or_ok(or_item(SVG))]}, {discovery("acme/vector-x"): endpoint("acme/vector-x", params)})
    out, _ = call(mod.generate_svg("seal", colors=["#123456"], n=1))
    body = api.bodies(OR_POST)[0]
    assert "provider" not in body and "n" not in body and body["prompt"] == "seal. Use color palette #123456."
    assert "takes no palette option" in out["notes"][0] and out["estimated_cost_usd"] is None


def test_a_reference_image_goes_along_when_the_model_takes_one(mod, tmp_path, monkeypatch):
    ref = tmp_path / "sketch.png"
    ref.write_bytes(PNG)
    api = mount(mod, {OR_POST: [or_ok(or_item(SVG)), or_ok(or_item(SVG))]})
    call(mod.generate_svg("clean vector version", reference_image=str(ref)))
    call(mod.generate_svg("x", reference_image="https://example.test/ref.jpg"))
    first, second = api.bodies(OR_POST)
    assert first["input_references"][0]["type"] == "image_url"
    assert base64.b64decode(first["input_references"][0]["image_url"]["url"].split(",", 1)[1]) == PNG
    assert second["input_references"][0]["image_url"]["url"] == "https://example.test/ref.jpg"
    monkeypatch.setenv("IMAGE_STUDIO_SVG_MODEL", "acme/vector-x")
    api = mount(mod, sticky={discovery("acme/vector-x"): endpoint("acme/vector-x", {"output_format": {"type": "enum", "values": ["svg"]}})})
    with pytest.raises(ValueError, match="takes no reference image"):
        call(mod.generate_svg("x", reference_image=str(ref)))
    assert api.paid == []


def test_a_catalog_outage_uses_the_stacks_copy_or_goes_unchecked(mod, monkeypatch):
    down = {discovery(RECRAFT): lambda req: httpx.Response(503, json={"error": {"message": "down"}})}
    api = mount(mod, {OR_POST: [or_ok(or_item(SVG))]}, down)
    out, _ = call(mod.generate_svg("logo", colors=["#010203"]))
    assert api.bodies(OR_POST)[0] == {"model": RECRAFT, "prompt": "logo", "n": 1, "output_format": "svg",
                                      "provider": {"options": {"recraft": {"controls": {"colors": [{"rgb": [1, 2, 3]}]}}}}}
    assert "notes" not in out and out["estimated_cost_usd"] == 0.3
    monkeypatch.setenv("IMAGE_STUDIO_SVG_MODEL", "acme/vector-y")
    api = mount(mod, {OR_POST: [or_ok(or_item(SVG))]},
                {discovery("acme/vector-y"): lambda req: httpx.Response(500, json={"error": {"message": "x"}})})
    out, _ = call(mod.generate_svg("logo", aspect_ratio="7:3"))
    assert api.bodies(OR_POST)[0]["aspect_ratio"] == "7:3" and "went out unchecked" in out["notes"][0]


def test_raster_answers_are_refused_and_never_saved(mod, tmp_path):
    mount(mod, {OR_POST: [or_ok(or_item(PNG, "image/png"), or_item(SVG), or_item(b"<html>not svg</html>", None))]})
    out, _ = call(mod.generate_svg("icon set", n=3))
    assert len(out["images"]) == 1
    assert [r["image"] for r in out["refused"]] == [1, 3] and "image/png" in out["refused"][0]["reason"]
    assert [p.suffix for p in (tmp_path / "out").iterdir()] == [".svg"]


def test_openrouter_errors_explain_themselves(mod):
    for code, words in ((402, "not enough credits"), (401, "OPENROUTER_API_KEY"), (403, "moderation"),
                        (502, "not billed"), (429, "rate limited"), (503, "no provider"),
                        (404, "IMAGE_STUDIO_SVG_MODEL / IMAGE_STUDIO_EDIT_MODEL")):
        mount(mod, {OR_POST: [httpx.Response(code, json={"error": {"message": "x"}})]})
        with pytest.raises(RuntimeError, match=words):
            call(mod.generate_svg("x"))
    mount(mod, {OR_POST: [httpx.Response(307, headers={"location": "https://evil.test/images"})]})
    with pytest.raises(RuntimeError, match="redirect"):
        call(mod.generate_svg("x"))


@pytest.mark.parametrize("evil", [
    b'<svg xmlns="http://www.w3.org/2000/svg" xmlns:s="http://www.w3.org/2000/svg"><s:script>alert(1)</s:script></svg>',
    b'<svg xmlns="http://www.w3.org/2000/svg" xmlns:h="http://www.w3.org/1999/xhtml"><h:script>alert(1)</h:script></svg>',
    b'<svg xmlns="http://www.w3.org/2000/svg"><a href="&#106;avascript:alert(1)"><path d="M0 0"/></a></svg>',
    b'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink">'
    b'<a xlink:href=" JaVaScRiPt:alert(1)"><path d="M0 0"/></a></svg>',
    b'<svg xmlns="http://www.w3.org/2000/svg"><a href="#"><animate attributeName="href" values="javascript:alert(1)"/>'
    b'<set attributeName="onclick" to="alert(1)"/><path d="M0 0"/></a></svg>',
    b'<svg xmlns="http://www.w3.org/2000/svg"><foreignObject><div xmlns="http://www.w3.org/1999/xhtml">x</div>'
    b'</foreignObject><image href="data:text/html;base64,PHNjcmlwdD4=" /></svg>',
])
def test_sanitizer_leaves_nothing_that_runs(mod, evil):
    mount(mod, {OR_POST: [or_ok(or_item(evil))]})
    out, _ = call(mod.generate_svg("x"))
    saved = Path(out["images"][0]["path"]).read_text().lower()
    for bad in ("script", "javascript", "foreignobject", "onclick", "<animate", "data:text"):
        assert bad not in saved, (bad, saved)
    assert "removed" in out["images"][0]["sanitized"]


def test_sanitizer_keeps_only_in_document_links(mod):
    evil = (b'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink">'
            b'<style>@import url(https://evil.test/x.css); .a{fill:url(https://evil.test/y#g)} .b{fill:url(#ok)}</style>'
            b'<defs><linearGradient id="ok"/></defs>'
            b'<image href="file:///etc/passwd"/><image xlink:href="text:/etc/hosts"/><a href="https://evil.test/"><path d="M0 0"/></a>'
            b'<use href="other.svg#x"/><use href="#ok"/><path d="M1 1" style="fill:url(https://evil.test/p#g)" fill="url(#ok)"/>'
            b'<rect fill="url(https://evil.test/q#g)"/><image href="data:image/png;base64,iVBORw0KGgo="/></svg>')
    mount(mod, {OR_POST: [or_ok(or_item(evil))]})
    out, _ = call(mod.generate_svg("x"))
    saved = Path(out["images"][0]["path"]).read_text()
    for bad in ("evil.test", "file:", "text:", "@import", "other.svg"):
        assert bad not in saved, (bad, saved)
    assert saved.count("url(#ok)") == 2 and 'href="#ok"' in saved and "data:image/png;base64" in saved


def test_doctype_entities_and_broken_xml_are_refused_or_dropped(mod):
    bomb = (b'<?xml version="1.0"?><!DOCTYPE svg [<!ENTITY a "aaaaaaaaaa"><!ENTITY b "&a;&a;&a;&a;">]>'
            b'<svg xmlns="http://www.w3.org/2000/svg"><text>&b;</text></svg>')
    plain = b'<?xml version="1.0"?><!DOCTYPE svg PUBLIC "-//W3C//DTD SVG 1.1//EN" "x.dtd"><svg xmlns="http://www.w3.org/2000/svg"/>'
    mount(mod, {OR_POST: [or_ok(*(or_item(x) for x in (bomb, plain, b"<svg><g></svg>", b'<html xmlns="x"><svg/></html>')))]})
    out, _ = call(mod.generate_svg("x", n=4))
    assert len(out["images"]) == 1 and "doctype" not in Path(out["images"][0]["path"]).read_text().lower()
    assert [r["image"] for r in out["refused"]] == [1, 3, 4]
    assert all("nothing saved" in r["reason"] for r in out["refused"])


def test_paid_images_are_never_overwritten_or_lost(mod, tmp_path, monkeypatch):
    monkeypatch.setattr(mod.time, "strftime", lambda fmt: "20260927-120000")    # the same second
    mount(mod, {OR_POST: [or_ok(or_item(SVG)), or_ok(or_item(SVG))]})
    first, _ = call(mod.generate_svg("x", name="logo"))
    second, _ = call(mod.generate_svg("x", name="logo"))
    assert first["images"][0]["path"] != second["images"][0]["path"]
    assert len(list((tmp_path / "out").iterdir())) == 2
    blocker = tmp_path / "afile"
    blocker.write_text("not a folder")
    api = mount(mod)
    with pytest.raises(ValueError, match="out_dir can't be created"):
        call(mod.generate_svg("x", out_dir=str(blocker / "sub")))
    assert api.requests == []                                                    # nothing billed, nothing asked


def test_svg_preview_returns_an_image_without_saving_one(mod, tmp_path, monkeypatch):
    mount(mod, {OR_POST: [or_ok(or_item(SVG))]})
    monkeypatch.setattr(mod, "_preview", lambda path, px=768: PNG)
    out, res = call(mod.generate_svg("x", preview=True))
    assert isinstance(res, list) and len(res) == 2 and isinstance(res[1], mod.Image)
    assert [p.suffix for p in (tmp_path / "out").iterdir()] == [".svg"]


# ---------------------------------------------------------------- generate_image: Opper, GPT Image 2.5 Sunburst by default
def status_route(job):
    return "GET %s/v3/artifacts/%s/status" % (OP, job)


def job_202(job):
    return httpx.Response(202, json={"id": job, "status_url": "%s/v3/artifacts/%s/status" % (OP, job)})


def done(url=None, data=None, cost=0.053, mime="image/png"):
    st = {"status": "completed", "mime_type": mime, "usage": {"cost": cost, "images": 1}}
    if url:
        st["url"] = url
    if data is not None:
        st["b64_json"] = b64(data)
    return httpx.Response(200, json=st)


def test_gpt_image_job_is_polled_downloaded_and_saved(mod, tmp_path):
    api = mount(mod, {GPT_POST: [job_202("gen_1")],
                      status_route("gen_1"): [httpx.Response(202, json={"status": "processing"}),
                                              done(url="https://files.opper.test/gen_1.png?X-Sig=abc")],
                      "GET https://files.opper.test/gen_1.png": [httpx.Response(200, content=real_png(1536, 1024))]})
    out, _ = call(mod.generate_image("a fisherman mending nets at dawn, 35 mm film", aspect_ratio="3:2"))
    assert api.bodies(GPT_POST) == [{"model": GPT, "prompt": "a fisherman mending nets at dawn, 35 mm film",
                                     "size": "1536x1024", "quality": "high", "async": True, "store": False}]
    on_opper = [r for r in api.requests if "opper.test" == r.url.host]
    assert len(on_opper) == 4 and "authorization" not in on_opper[0].headers     # the public catalog: no key
    assert str(on_opper[0].url).startswith(OP + "/v3/images/models?q=openai%2Fgpt-image-2.5-sunburst")
    assert all(r.headers["authorization"] == "Bearer " + KEYS["opper.test"] for r in on_opper[1:])
    download = [r for r in api.requests if r.headers["host"] == "files.opper.test"][0]
    assert "authorization" not in download.headers
    img = out["images"][0]
    assert img["path"].endswith(".png") and (img["width"], img["height"]) == (1536, 1024)
    assert out["cost_usd"] == 0.053 and out["estimated_cost_usd"] == 0.053 and out["size"] == "1536x1024"
    assert out["model"] == GPT and out["provider"] == "opper" and out["quality"] == "high" and "pending" not in out


def test_gpt_defaults_to_a_square_1k_image(mod):
    api = mount(mod, {GPT_POST: [job_202("d1")], status_route("d1"): [done(data=real_png(32, 32))]})
    call(mod.generate_image("x"))
    assert api.bodies(GPT_POST)[0] == {"model": GPT, "prompt": "x", "size": "1024x1024", "quality": "high",
                                       "async": True, "store": False}


@pytest.mark.parametrize("aspect, tier, size", [
    ("1:1", "1K", "1024x1024"), ("3:2", "1K", "1536x1024"), ("2:3", "1K", "1024x1536"), ("16:9", "1K", "1824x1024"),
    ("4:3", "1K", "1360x1024"), ("16:9", "2K", "2560x1440"), ("1:1", "2K", "1440x1440"), ("16:9", "4K", "3840x2160"),
    ("1:1", "4K", "2160x2160"), ("21:9", "4K", "3840x1648"), ("9:16", "4K", "2160x3840"), ("auto", "2K", "auto"),
])
def test_sizes_follow_the_tiers(mod, aspect, tier, size):
    assert mod._gpt_size(aspect, tier, "") == size


def test_every_computed_size_is_one_opper_accepts(mod):
    for aspect in ("1:1", "3:2", "2:3", "4:3", "3:4", "16:9", "9:16", "4:5", "5:4", "21:9", "3:1"):
        for tier in mod.TIERS:
            w, h = map(int, mod._gpt_size(aspect, tier.lower(), "").split("x"))
            assert w % 16 == 0 and h % 16 == 0 and max(w, h) <= 3840 and max(w, h) / min(w, h) <= 3, (aspect, tier)
            assert 655_360 <= w * h <= 8_294_400, (aspect, tier, w, h)
            a, b = map(int, aspect.split(":"))
            assert abs(w / h - a / b) < 0.02, (aspect, tier, w, h)


@pytest.mark.parametrize("size, ok", [("2048x2048", True), ("3840x2160", True), ("auto", True), ("1000x1000", False),
                                      ("4096x1024", False), ("3840x1024", False), ("512x512", False), ("big", False),
                                      ("00x16", False), ("0x1024", False)])
def test_an_exact_size_is_checked(mod, size, ok):
    if ok:
        assert mod._gpt_size("1:1", "1K", size) == size
    else:
        with pytest.raises(ValueError, match="size must"):
            mod._gpt_size("1:1", "1K", size)


def test_several_images_are_separate_jobs_with_their_options(mod, tmp_path):
    routes = {GPT_POST: [job_202("a"), job_202("b"), job_202("c")]}
    for j in "abc":
        routes[status_route(j)] = [done(data=webp(), cost=0.02, mime="image/webp")]
    api = mount(mod, routes)
    out, _ = call(mod.generate_image("three variations of a teapot", n=3, quality="medium",
                                     output_format="webp", background="transparent", resolution="4K"))
    bodies = api.bodies(GPT_POST)
    assert len(bodies) == 3 and all(b == bodies[0] for b in bodies)
    assert bodies[0]["parameters"] == {"output_format": "webp", "background": "transparent"}
    assert bodies[0]["size"] == "2160x2160" and "n" not in bodies[0] and bodies[0]["quality"] == "medium"
    assert [i["format"] for i in out["images"]] == ["webp"] * 3 and out["cost_usd"] == 0.06
    assert out["estimated_cost_usd"] == round(0.013 * 3, 3)                   # 4.7 MP: no 4K surcharge
    assert len([r for r in api.requests if str(r.url).startswith(OP + "/v3/images/models")]) == 1


def test_failed_and_slow_jobs_and_collecting_later(mod, tmp_path):
    api = mount(mod, {GPT_POST: [job_202("gen_bad"), job_202("gen_slow")],
                      status_route("gen_bad"): [httpx.Response(200, json={"status": "failed", "error": "moderation_blocked"})],
                      status_route("gen_slow"): [lambda req: httpx.Response(202, json={"status": "processing"})] * 400})
    mod.TIMEOUT = 20
    out, _ = call(mod.generate_image("x", n=2, quality="max"))
    assert out["images"] == [] and "moderation_blocked" in out["refused"][0]["reason"] and out["refused"][0]["job"] == "gen_bad"
    assert out["pending"] == [{"image": 2, "job": "gen_slow", "status_url": OP + "/v3/artifacts/gen_slow/status",
                               "status": "processing"}]
    ledger = [json.loads(x) for x in (tmp_path / "out" / ".image-studio-jobs.jsonl").read_text().splitlines()]
    assert [e["job"] for e in ledger] == ["gen_bad", "gen_slow"] and ledger[1]["model"] == GPT
    assert any("collect_image" in n for n in out["notes"]) and out["estimated_cost_usd"] == 0.422
    api.routes[status_route("gen_slow")] = [done(url="https://files.opper.test/slow.png")]
    api.routes["GET https://files.opper.test/slow.png"] = [httpx.Response(200, content=real_png(64, 64))]
    got, _ = call(mod.collect_image("gen_slow", name="hero"))
    assert got["images"][0]["path"].endswith(".png") and "hero" in got["images"][0]["path"] and got["cost_usd"] == 0.053
    assert got["images"][0]["job"] == "gen_slow"
    api.routes[status_route("gen_slow")] = [httpx.Response(202, json={"status": "processing"})]
    got, _ = call(mod.collect_image("gen_slow"))
    assert got["status"] == "processing" and got["images"] == []


@pytest.mark.parametrize("job", ["https://evil.test/v3/artifacts/x/status", "../../etc/passwd", "a b", ""])
def test_collect_image_never_sends_the_key_elsewhere(mod, job):
    api = mount(mod)
    with pytest.raises(ValueError):
        call(mod.collect_image(job))
    assert api.requests == []


def test_a_foreign_status_url_is_rebuilt_on_opper(mod):
    api = mount(mod, {GPT_POST: [httpx.Response(202, json={"id": "gen_9", "status_url": "https://evil.test/v3/artifacts/gen_9/status"})],
                      status_route("gen_9"): [done(data=real_png(32, 32))]})
    out, _ = call(mod.generate_image("x"))
    assert len(out["images"]) == 1 and all(r.url.host != "evil.test" for r in api.requests)


def test_references_are_scaled_and_sent_in_order(mod, tmp_path):
    big = tmp_path / "product shot.png"
    big.write_bytes(real_png(3000, 2000))
    api = mount(mod, {GPT_POST: [job_202("r1")], status_route("r1"): [done(data=real_png(32, 32))]})
    call(mod.generate_image("the same bottle on a marble counter", reference_images=[big.as_uri(), "https://example.test/style.jpg"]))
    refs = api.bodies(GPT_POST)[0]["reference_images"]
    assert max(decoded_size(refs[0])) == 1919 and refs[1] == "https://example.test/style.jpg"
    api = mount(mod)
    with pytest.raises(ValueError, match="at most 8"):
        call(mod.generate_image("x", reference_images=[str(big)] * 9))
    with pytest.raises(ValueError, match="local path or an https URL"):
        call(mod.generate_image("x", reference_images=["ftp://x/y.png"]))
    assert api.requests == []


def test_store_and_async_refusals_retry_once_without(mod):
    api = mount(mod, {GPT_POST: [httpx.Response(400, json={"error": {"code": "bad_request", "message": "store must be true for async jobs"}}),
                                 job_202("s1")],
                      status_route("s1"): [done(data=real_png(32, 32))]})
    out, _ = call(mod.generate_image("x"))
    first, second = api.bodies(GPT_POST)
    assert first["store"] is False and "store" not in second and "Opper Files" in out["notes"][0]
    api = mount(mod, {GPT_POST: [httpx.Response(400, json={"error": {"message": "async is not supported for this model"}}),
                                 httpx.Response(200, json={"id": "img_1", "model": GPT, "created": 1,
                                                           "data": [{"b64_json": b64(jpeg()), "mime_type": "image/jpeg"}],
                                                           "usage": {"cost": 0.05, "images": 1}})]})
    out, _ = call(mod.generate_image("x", output_format="jpg"))
    assert "async" not in api.bodies(GPT_POST)[1] and out["images"][0]["format"] == "jpg" and out["cost_usd"] == 0.05
    assert "waited for inline" in out["notes"][0]


def test_opper_errors_explain_themselves(mod):
    for code, words in ((402, "top up"), (401, "OPPER_API_KEY"), (403, "moderation"), (404, "not found")):
        mount(mod, {GPT_POST: [httpx.Response(code, json={"error": {"code": "x", "message": "x"}})]})
        with pytest.raises(RuntimeError, match=words):
            call(mod.generate_image("x"))


@pytest.mark.parametrize("kw, words", [
    ({"quality": "ultra"}, "quality for openai/gpt-image-2.5-sunburst must be one of low"), ({"n": 5}, "n must be"),
    ({"output_format": "gif"}, "output_format must be"), ({"background": "transparent", "output_format": "jpg"}, "needs output_format png"),
    ({"aspect_ratio": "7:1"}, "beyond"), ({"aspect_ratio": "wide"}, "aspect_ratio must be W:H"),
    ({"resolution": "8K"}, "resolution must be"), ({"prompt": ""}, "prompt is empty"), ({"background": "none"}, "background"),
])
def test_bad_image_arguments_cost_nothing(mod, kw, words):
    api = mount(mod)
    with pytest.raises(ValueError, match=words):
        call(mod.generate_image(**dict({"prompt": "x"}, **kw)))
    assert api.paid == []


IMAGEN = {"id": "google/imagen-5-ultra", "name": "Imagen 5 Ultra", "capabilities": ["image_generation"],
          "params": {"image": {"aspect_ratios": ["1:1", "16:9", "9:16", "4:3", "3:4"], "resolutions": ["1K", "2K"],
                               "parameters": [{"name": "seed", "type": "integer"}]}},
          "pricing": {"price_per_generation": 0.06}}


def test_another_opper_model_follows_its_catalog_entry(mod, monkeypatch):
    monkeypatch.setenv("IMAGE_STUDIO_IMAGE_MODEL", "google/imagen-5-ultra")
    api = mount(mod, {GPT_POST: [job_202("i1")], status_route("i1"): [done(data=real_png(32, 32), cost=0.06)]},
                {OPPER_MODELS: catalog(GPT_ENTRY, IMAGEN)})
    out, _ = call(mod.generate_image("a lighthouse at dusk", aspect_ratio="16:9", resolution="2k"))
    assert api.bodies(GPT_POST)[0] == {"model": "google/imagen-5-ultra", "prompt": "a lighthouse at dusk",
                                       "aspect_ratio": "16:9", "resolution": "2K", "async": True, "store": False}
    assert out["model"] == "google/imagen-5-ultra" and out["estimated_cost_usd"] == 0.06 and "quality" not in out
    for kw, words in (({"quality": "high"}, "has no quality option"), ({"background": "transparent"}, "has no background option"),
                      ({"reference_images": ["https://example.test/r.jpg"]}, "takes no reference images"),
                      ({"size": "1024x1024"}, "takes aspect ratios, not pixel sizes"),
                      ({"resolution": "4K"}, "resolution for google/imagen-5-ultra must be one of 1K, 2K"),
                      ({"aspect_ratio": "21:9"}, "aspect_ratio for google/imagen-5-ultra must be one of")):
        with pytest.raises(ValueError, match=words):
            call(mod.generate_image("x", **kw))
    assert len(api.paid) == 1


def test_a_model_with_a_list_of_sizes_gets_the_closest_one(mod, monkeypatch):
    dalle = {"id": "openai/dall-e-3", "capabilities": ["image_generation"],
             "params": {"image": {"sizes": ["1024x1024", "1792x1024", "1024x1792"], "qualities": ["standard", "hd"],
                                  "parameters": [{"name": "style", "enum": ["vivid", "natural"]}]}}}
    monkeypatch.setenv("IMAGE_STUDIO_IMAGE_MODEL", "openai/dall-e-3")
    api = mount(mod, {GPT_POST: [job_202("e1"), job_202("e2")], status_route("e1"): [done(data=real_png(32, 32))],
                      status_route("e2"): [done(data=real_png(32, 32))]}, {OPPER_MODELS: catalog(dalle)})
    call(mod.generate_image("x", aspect_ratio="16:9"))
    call(mod.generate_image("x", aspect_ratio="9:16", quality="hd"))
    first, second = api.bodies(GPT_POST)
    assert first["size"] == "1792x1024" and "quality" not in first
    assert second["size"] == "1024x1792" and second["quality"] == "hd"
    with pytest.raises(ValueError, match="size for openai/dall-e-3 must be one of"):
        call(mod.generate_image("x", size="2048x2048"))


def test_an_unknown_opper_model_is_refused_before_paying(mod, monkeypatch):
    monkeypatch.setenv("IMAGE_STUDIO_IMAGE_MODEL", "acme/nothing-here")
    api = mount(mod)
    with pytest.raises(ValueError, match="IMAGE_STUDIO_IMAGE_MODEL=acme/nothing-here isn't an Opper image model"):
        call(mod.generate_image("x"))
    assert api.paid == [] and len(api.requests) == 2                              # a search, then the full list


def test_an_opper_catalog_outage_uses_the_stacks_copy_or_goes_unchecked(mod, monkeypatch):
    down = {OPPER_MODELS: lambda req: httpx.Response(500, json={"error": {"code": "x", "message": "down"}})}
    api = mount(mod, {GPT_POST: [job_202("o1")], status_route("o1"): [done(data=real_png(32, 32))]}, down)
    out, _ = call(mod.generate_image("x", aspect_ratio="16:9"))
    assert api.bodies(GPT_POST)[0]["size"] == "1824x1024" and api.bodies(GPT_POST)[0]["quality"] == "high"
    assert "notes" not in out
    monkeypatch.setenv("IMAGE_STUDIO_IMAGE_MODEL", "acme/new-model")
    api = mount(mod, {GPT_POST: [job_202("o2")], status_route("o2"): [done(data=real_png(32, 32))]}, down)
    out, _ = call(mod.generate_image("x", aspect_ratio="16:9", resolution="2K"))
    body = api.bodies(GPT_POST)[0]
    assert body["aspect_ratio"] == "16:9" and body["resolution"] == "2K" and "size" not in body and "quality" not in body
    assert "went out unchecked" in out["notes"][0]


# ---------------------------------------------------------------- edit_image: OpenRouter, Riverflow by default
def test_edit_image_sends_inputs_in_order_and_under_the_size_limit(mod, tmp_path):
    big = tmp_path / "shop front.png"
    big.write_bytes(real_png(3000, 2000))
    small = tmp_path / "logo.jpg"
    small.write_bytes(jpeg())
    api = mount(mod, {OR_POST: [or_ok(or_item(real_png(1600, 1200), "image/png"), cost=0.15)]})
    out, _ = call(mod.edit_image([str(big), "https://example.test/texture.jpg", small.as_uri()],
                                 "put the logo on the awning; keep everything else unchanged", resolution="2K"))
    body = api.bodies(OR_POST)[0]
    assert body["model"] == RIVERFLOW and body["aspect_ratio"] == "auto" and body["resolution"] == "2K" and body["n"] == 1
    posts = api.paid
    assert posts[0].headers["authorization"] == "Bearer " + KEYS["openrouter.test"]
    assert posts[0].headers["x-title"] == "claude-agent-stack"
    urls = [r["image_url"]["url"] for r in body["input_references"]]
    assert urls[1] == "https://example.test/texture.jpg"
    assert max(decoded_size(urls[0])) == 1919                                    # scaled in memory
    assert base64.b64decode(urls[2].split(",", 1)[1]) == small.read_bytes()      # small ones go as they are
    assert big.read_bytes()[:4] == b"\x89PNG" and len(big.read_bytes()) > 1000   # the original is untouched
    assert out["images"][0]["width"] == 1600 and out["cost_usd"] == 0.15 and out["provider"] == "openrouter"
    assert out["estimated_cost_usd"] == 0.15                                     # Riverflow at 2K


def test_edit_inputs_are_fitted_into_one_request_or_refused(mod, tmp_path):
    paths = []
    for k in range(11):
        f = tmp_path / f"noise{k}.png"
        f.write_bytes(real_png(1400, 1000, noise=True))                            # ~4 MB each as PNG
        paths.append(str(f))
    api = mount(mod, {OR_POST: [or_ok(or_item(jpeg(), "image/jpeg"))]})
    call(mod.edit_image(paths[:3], "blend these into one collage"))
    urls = [r["image_url"]["url"] for r in api.bodies(OR_POST)[0]["input_references"]]
    assert sum(map(len, urls)) <= mod.BUDGET["openrouter"] and all(u.startswith("data:image/jpeg") for u in urls)
    api = mount(mod)
    with pytest.raises(ValueError, match="don't fit in one request"):
        call(mod.edit_image(paths[:10], "x"))
    with pytest.raises(ValueError, match="takes at most 10 input image"):
        call(mod.edit_image(["https://example.test/%d.jpg" % k for k in range(11)], "x"))
    with pytest.raises(ValueError, match="images must list 1-16"):
        call(mod.edit_image(["https://example.test/%d.jpg" % k for k in range(17)], "x"))
    assert api.paid == []


def test_edit_options_are_checked_against_the_catalog(mod):
    api = mount(mod, {OR_POST: [or_ok(or_item(jpeg(), "image/jpeg"), cost=0.17)]})
    out, _ = call(mod.edit_image(["https://example.test/a.jpg"], "relight at golden hour", resolution="4k",
                                 output_format="jpg", aspect_ratio="21:9"))
    assert api.bodies(OR_POST)[0] == {
        "model": RIVERFLOW, "prompt": "relight at golden hour", "n": 1, "aspect_ratio": "21:9", "resolution": "4K",
        "output_format": "jpeg", "input_references": [{"type": "image_url", "image_url": {"url": "https://example.test/a.jpg"}}]}
    assert out["images"][0]["path"].endswith(".jpg") and out["estimated_cost_usd"] == 0.17
    for kw, words in (({"aspect_ratio": "5:4"}, "aspect_ratio for sourceful/riverflow-v2.5-pro must be one of"),
                      ({"resolution": "8K"}, "resolution for sourceful/riverflow-v2.5-pro must be one of 1K, 2K, 4K"),
                      ({"background": "none"}, "background must be"), ({"output_format": "gif"}, "output_format must be"),
                      ({"background": "transparent", "output_format": "jpg"}, "needs output_format png"),
                      ({"images": []}, "images must list"), ({"prompt": " "}, "prompt is empty")):
        with pytest.raises(ValueError, match=words):
            call(mod.edit_image(**dict({"images": ["https://example.test/a.jpg"], "prompt": "x"}, **kw)))
    assert len(api.paid) == 1


def test_the_edit_model_comes_from_stack_env(mod, monkeypatch):
    monkeypatch.setenv("IMAGE_STUDIO_EDIT_MODEL", "google/gemini-3-pro-image")
    params = {"aspect_ratio": {"type": "enum", "values": ["1:1", "16:9", "9:16"]},
              "input_references": {"type": "range", "min": 0, "max": 3}}
    api = mount(mod, {OR_POST: [or_ok(or_item(real_png(40, 40), "image/png"), cost=0.04)]},
                {discovery("google/gemini-3-pro-image"): endpoint("google/gemini-3-pro-image", params, (), 0.04, "google")})
    out, _ = call(mod.edit_image(["https://example.test/a.jpg", "https://example.test/b.jpg"], "merge them"))
    body = api.bodies(OR_POST)[0]
    assert body["model"] == "google/gemini-3-pro-image" and "n" not in body and "aspect_ratio" not in body
    assert out["model"] == "google/gemini-3-pro-image" and out["estimated_cost_usd"] == 0.04
    for kw, words in (({"images": ["https://example.test/%d.jpg" % k for k in range(4)]}, "takes at most 3 input image"),
                      ({"background": "transparent"}, "has no background option"), ({"resolution": "2K"}, "has no resolution option")):
        with pytest.raises(ValueError, match=words):
            call(mod.edit_image(**dict({"images": ["https://example.test/a.jpg"], "prompt": "x"}, **kw)))
    assert len(api.paid) == 1


def test_an_edit_model_that_takes_no_images_is_refused(mod, monkeypatch):
    monkeypatch.setenv("IMAGE_STUDIO_EDIT_MODEL", "acme/text-only")
    api = mount(mod, sticky={discovery("acme/text-only"): endpoint("acme/text-only", {"aspect_ratio": {"type": "enum", "values": ["1:1"]}})})
    with pytest.raises(ValueError, match="IMAGE_STUDIO_EDIT_MODEL=acme/text-only takes no input images"):
        call(mod.edit_image(["https://example.test/a.jpg"], "x"))
    assert api.paid == []


def test_edit_refuses_non_images_and_keeps_formats(mod, tmp_path):
    mount(mod, {OR_POST: [or_ok(or_item(SVG, "image/svg+xml"), or_item(webp(), "image/webp"), {"url": "https://x.test/a.png"})]})
    out, _ = call(mod.edit_image(["https://example.test/a.jpg"], "x"))
    assert [i["format"] for i in out["images"]] == ["webp"] and [r["image"] for r in out["refused"]] == [1, 3]
    assert sorted(p.suffix for p in (tmp_path / "out").iterdir()) == [".webp"]


def test_raster_preview_is_a_small_jpeg(mod):
    mount(mod, {OR_POST: [or_ok(or_item(real_png(2000, 1000), "image/png"))]})
    _, res = call(mod.edit_image(["https://example.test/a.jpg"], "x", preview=True))
    from PIL import Image as PILImage
    assert isinstance(res, list) and isinstance(res[1], mod.Image)
    assert max(PILImage.open(io.BytesIO(res[1].data)).size) <= 768


# ---------------------------------------------------------------- keys, files, downloads and wiring
def test_protected_and_fake_files_are_never_sent(mod, home, tmp_path):
    (home / ".ssh").mkdir()
    (home / ".ssh" / "id.png").write_bytes(PNG)
    (tmp_path / ".env.assets").mkdir()
    (tmp_path / ".env.assets" / "logo.png").write_bytes(PNG)
    (tmp_path / "notes.png").write_bytes(b"not really a png")
    (tmp_path / "logo.svg").write_bytes(SVG)
    api = mount(mod)
    for ref, words in ((home / ".ssh" / "id.png", "protected directory"), (tmp_path / ".env.assets" / "logo.png", "env"),
                       (tmp_path / "notes.png", "content is not"), (tmp_path / "logo.svg", "PNG, JPEG or WebP"),
                       (tmp_path / "missing.png", "not found")):
        for tool in (lambda r: mod.edit_image([r], "x"), lambda r: mod.generate_image("x", reference_images=[r]),
                     lambda r: mod.generate_svg("x", reference_image=r)):
            with pytest.raises(ValueError, match=words):
                call(tool(str(ref)))
    with pytest.raises(ValueError, match="protected directory"):
        call(mod.generate_svg("x", out_dir=str(home / ".ssh" / "out")))
    assert api.requests == []


def test_file_uri_inputs_are_decoded(mod, tmp_path):
    ref = tmp_path / "Captura de ecrã às 10.12.png"
    ref.write_bytes(PNG)
    for value in (ref.as_uri(), "file://" + str(ref)):
        api = mount(mod, {OR_POST: [or_ok(or_item(real_png(8, 8), "image/png"))]})
        call(mod.edit_image([value], "x"))
        assert api.bodies(OR_POST)[0]["input_references"][0]["image_url"]["url"].startswith("data:image/png;base64,")


def test_each_tool_needs_only_its_own_key(mod, monkeypatch):
    monkeypatch.delenv("OPPER_API_KEY")
    api = mount(mod, {OR_POST: [or_ok(or_item(real_png(32, 32), "image/png")), or_ok(or_item(SVG))]})
    with pytest.raises(RuntimeError, match="OPPER_API_KEY is not set: generate_image can't run without it"):
        call(mod.generate_image("x"))
    out, _ = call(mod.edit_image(["https://example.test/a.jpg"], "x"))
    assert len(out["images"]) == 1
    out, _ = call(mod.generate_svg("x"))
    assert len(out["images"]) == 1 and len(api.paid) == 2
    monkeypatch.delenv("OPENROUTER_API_KEY")
    with pytest.raises(RuntimeError, match="OPENROUTER_API_KEY is not set: generate_svg and edit_image can't run"):
        call(mod.generate_svg("x"))


def test_keys_never_reach_an_error_message(mod, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-v1 SECRETVALUE")
    mount(mod)
    with pytest.raises(RuntimeError, match="contains spaces") as err:
        call(mod.edit_image(["https://example.test/a.jpg"], "x"))
    assert "SECRETVALUE" not in str(err.value)
    monkeypatch.setenv("OPENROUTER_API_KEY", "  sk-or-v1-SECRETVALUE\n")      # stray whitespace is just trimmed

    def boom(request):
        raise httpx.ConnectError("could not send " + request.headers.get("authorization", "(no key)"))
    mod._TRANSPORT = httpx.MockTransport(boom)
    mod._CATALOG.clear()
    with pytest.raises(RuntimeError) as err:
        call(mod.edit_image(["https://example.test/a.jpg"], "x"))
    assert "SECRETVALUE" not in str(err.value) and "<OPENROUTER_API_KEY>" in str(err.value)


def test_a_key_is_never_sent_to_another_host(mod):
    seen = []

    async def go(url):
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: seen.append(r) or httpx.Response(200))) as c:
            await mod._authed(c, "opper", "GET", url)
    for url in ("https://opper.test.evil.test/v3/x", "http://opper.test/v3/x", "https://opper.test:8443/v3/x"):
        with pytest.raises(RuntimeError, match="refusing to send OPPER_API_KEY"):
            asyncio.run(go(url))
    assert seen == []


@pytest.mark.parametrize("host", ["2130706433", "127.1", "0x7f.1", "0177.0.0.1", "169.254.169.254", "[fe80::1]", "localhost.",
                                  "printer.local"])
def test_results_on_private_hosts_are_never_fetched(mod, host):
    api = mount(mod, {GPT_POST: [job_202("p1")], status_route("p1"): [done(url="https://%s/a.png" % host)]})
    out, _ = call(mod.generate_image("x"))
    assert out["images"] == [] and "refusing" in out["pending"][0]["status"]
    assert all(r.url.host in ("opper.test",) for r in api.requests)


def test_names_that_resolve_to_private_addresses_are_never_fetched(mod, monkeypatch):
    async def private(host):
        return ["10.0.0.5"] if host == "cdn.evil.test" else ["93.184.216.34"]
    monkeypatch.setattr(mod, "_resolve", private)
    api = mount(mod, {GPT_POST: [job_202("p2")], status_route("p2"): [done(url="https://cdn.evil.test/a.png")]})
    out, _ = call(mod.generate_image("x"))
    assert "non-public" in out["pending"][0]["status"] and all(r.url.host == "opper.test" for r in api.requests)


def test_download_is_pinned_to_the_vetted_ip_and_never_resolved_twice(mod, monkeypatch):
    calls = []

    async def rebinding(host):                       # public first, loopback on any later resolution
        calls.append(host)
        return ["93.184.216.34"] if len(calls) == 1 else ["127.0.0.1"]
    monkeypatch.setattr(mod, "_resolve", rebinding)
    seen = []

    def handler(req):
        seen.append(req)
        return httpx.Response(200, content=b"pixels")

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            return await mod._download(c, "opper", "https://cdn.example.test:8443/a.png?x=1")
    assert asyncio.run(go()) == b"pixels"
    assert calls == ["cdn.example.test"]
    r = seen[0]
    assert (r.url.host, r.url.port, r.url.path, r.url.query) == ("93.184.216.34", 8443, "/a.png", b"x=1")
    assert r.headers["host"] == "cdn.example.test:8443" and r.extensions["sni_hostname"] == "cdn.example.test"


def test_every_redirect_hop_is_resolved_once_and_pinned(mod, monkeypatch):
    calls, seen = [], []
    ips = {"a.example.test": "93.184.216.34", "b.example.test": "93.184.216.35"}

    async def res(host):
        calls.append(host)
        return [ips[host]]
    monkeypatch.setattr(mod, "_resolve", res)

    def handler(req):
        seen.append(req)
        if req.headers["host"] == "a.example.test":
            return httpx.Response(302, headers={"location": "https://b.example.test/final.png"})
        return httpx.Response(200, content=b"ok")

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            return await mod._download(c, "opper", "https://a.example.test/x.png")
    assert asyncio.run(go()) == b"ok" and calls == ["a.example.test", "b.example.test"]
    assert [r.url.host for r in seen] == ["93.184.216.34", "93.184.216.35"]
    assert [r.extensions["sni_hostname"] for r in seen] == ["a.example.test", "b.example.test"]


def test_paid_jobs_survive_a_later_failure(mod, tmp_path):
    mount(mod, {GPT_POST: [job_202("paid_1"), httpx.Response(429, json={"error": {"message": "slow down"}})],
                status_route("paid_1"): [done(data=real_png(64, 64))]})
    out, _ = call(mod.generate_image("x", n=2))
    assert len(out["images"]) == 1 and out["images"][0]["job"] == "paid_1"
    assert any("stopped before image 2 of 2" in n and "429" in n for n in out["notes"])
    mount(mod, {GPT_POST: [httpx.Response(200, json={"data": [{"b64_json": b64(real_png(32, 32))}], "usage": {"cost": 0.01}}),
                           httpx.Response(504, json={"error": {"message": "timeout"}})]})
    out, _ = call(mod.generate_image("x", n=2))                  # the inline path: the first image is kept
    assert len(out["images"]) == 1 and out["cost_usd"] == 0.01 and any("stopped before image 2" in n for n in out["notes"])
    mount(mod, {GPT_POST: [httpx.Response(429, json={"error": {"message": "slow down"}})]})
    with pytest.raises(RuntimeError, match="429"):              # nothing accepted, nothing paid: a plain error
        call(mod.generate_image("x", n=2))


def test_unfetched_results_and_failing_checks_stay_collectable(mod, tmp_path):
    mount(mod, {GPT_POST: [job_202("a1"), job_202("b2")],
                status_route("a1"): [done(url="https://files.opper.test/a1.png")],
                "GET https://files.opper.test/a1.png": [httpx.Response(503)],
                status_route("b2"): [lambda req: httpx.Response(503, json={"error": {"message": "down"}})] * 50})
    out, _ = call(mod.generate_image("x", n=2))
    assert out["images"] == [] and "refused" not in out and out["cost_usd"] == 0.053
    by_job = {p["job"]: p for p in out["pending"]}
    assert by_job["a1"]["status"].startswith("completed, but the download failed") and "503" in by_job["a1"]["status"]
    assert by_job["b2"]["status"].startswith("status check failed") and by_job["b2"]["status_url"].endswith("/b2/status")
    mount(mod, {status_route("a1"): [done(url="https://files.opper.test/a1.png")],
                "GET https://files.opper.test/a1.png": [httpx.Response(200, content=real_png(40, 30))]})
    got, _ = call(mod.collect_image("a1"))
    assert got["images"][0]["width"] == 40


def test_one_bad_item_never_costs_the_others(mod):
    mount(mod, {OR_POST: [or_ok({"b64_json": "@@@not base64@@@"}, "junk", or_item(SVG))]})
    out, _ = call(mod.generate_svg("x", n=3))
    assert len(out["images"]) == 1 and [r["image"] for r in out["refused"]] == [1, 2]


def test_fallbacks_only_for_errors_that_name_the_option(mod):
    refusal = {"error": {"code": "content_policy_violation", "message": "blocked: controls colors in a corner store"}}
    api = mount(mod, {OR_POST: [httpx.Response(400, json=refusal)]})
    with pytest.raises(RuntimeError, match="400"):
        call(mod.generate_svg("badge", colors=["#ff0000"]))
    assert len(api.paid) == 1
    api = mount(mod, {GPT_POST: [httpx.Response(400, json=refusal)]})
    with pytest.raises(RuntimeError, match="400"):
        call(mod.generate_image("a corner store at dusk"))
    assert len(api.paid) == 1


def test_base64_variants_and_corrupt_images(mod):
    img = real_png(33, 17)
    good = [{"b64_json": "data:image/png;base64," + b64(img)},
            {"b64_json": base64.urlsafe_b64encode(img).decode().rstrip("=")}]
    broken = bytearray(real_png(20, 20))
    broken[40] ^= 0xFF                                            # a flipped byte inside IDAT: the CRC fails
    mount(mod, {OR_POST: [or_ok(*good, {"b64_json": b64(bytes(broken))}, {"b64_json": "@@not base64@@"})]})
    out, _ = call(mod.edit_image(["https://example.test/a.jpg"], "x"))
    assert [(i["width"], i["height"]) for i in out["images"]] == [(33, 17), (33, 17)]
    reasons = {r["image"]: r["reason"] for r in out["refused"]}
    assert "corrupt" in reasons[3] and "base64" in reasons[4]


def test_job_ids_are_checked(mod):
    assert mod._status_url("gen.1:abc") == OP + "/v3/artifacts/gen.1%3Aabc/status"
    assert mod._status_url("/v3/artifacts/gen_2/status") == OP + "/v3/artifacts/gen_2/status"
    for bad in ("a..b", "//evil.test/v3/artifacts/x/status", "gen/../x"):
        with pytest.raises(ValueError):
            mod._status_url(bad)


def test_the_older_out_dir_setting_still_works(home, tmp_path, monkeypatch):
    monkeypatch.delenv("IMAGE_STUDIO_OUT_DIR")
    monkeypatch.setenv("OPENROUTER_IMAGE_OUT_DIR", str(tmp_path / "old"))
    assert load("image_studio_legacy_out").OUT_DIR == tmp_path / "old"
    monkeypatch.delenv("OPENROUTER_IMAGE_OUT_DIR")
    assert load("image_studio_default_out").OUT_DIR == Path(str(home)) / "Pictures" / "image-studio"


def test_tool_descriptions_name_the_models_in_use(home, monkeypatch):
    described = {t.name: t.description for t in asyncio.run(load("image_studio_defaults").mcp.list_tools())}
    assert "Recraft V4.1 Pro Vector (recraft/recraft-v4.1-pro-vector) through OpenRouter" in described["generate_svg"]
    assert "GPT Image 2.5 Sunburst (openai/gpt-image-2.5-sunburst) through Opper" in described["generate_image"]
    assert "Riverflow V2.5 Pro (sourceful/riverflow-v2.5-pro) through OpenRouter" in described["edit_image"]
    monkeypatch.setenv("IMAGE_STUDIO_SVG_MODEL", "recraft/recraft-v4.1-vector")
    monkeypatch.setenv("IMAGE_STUDIO_IMAGE_MODEL", "google/imagen-5-ultra")
    monkeypatch.setenv("IMAGE_STUDIO_EDIT_MODEL", "google/gemini-3-pro-image")
    described = {t.name: t.description for t in asyncio.run(load("image_studio_custom").mcp.list_tools())}
    assert "recraft/recraft-v4.1-vector through OpenRouter" in described["generate_svg"]
    assert "google/imagen-5-ultra through Opper" in described["generate_image"]
    assert "google/gemini-3-pro-image through OpenRouter" in described["edit_image"]
    assert all("stack.env" in d for n, d in described.items() if n != "collect_image")


def test_four_tools_and_three_model_settings(home):    # home: load() runs the module's import-time stack.env read; keep it off the real file
    src = MODULE.read_text()
    assert re.findall(r"@mcp\.tool\([^\n]*\)\s*\nasync def (\w+)", src) == ["generate_svg", "generate_image", "collect_image", "edit_image"]
    for setting, default in (("IMAGE_STUDIO_SVG_MODEL", RECRAFT), ("IMAGE_STUDIO_IMAGE_MODEL", GPT), ("IMAGE_STUDIO_EDIT_MODEL", RIVERFLOW)):
        assert re.search(r'"env": "%s", "default": "%s"' % (setting, re.escape(default)), src)
    assert "krea" not in src.lower() and "thinking_level" not in src and "lumenfall.ai" not in src.lower()
    assert [ln.split(":")[0] for ln in src.splitlines() if "lumenfall" in ln.lower()] == \
        ['RETIRED_ENV = {"LUMENFALL_API_KEY"']                    # only to flag a leftover key
    assert copy.deepcopy(RECRAFT_EP["endpoints"][0]["supported_parameters"]) == \
        load("image_studio_known").OR_KNOWN[RECRAFT][0]["supported_parameters"]


# ---------------------------------------------------------------- --check: what /stack-doctor shows
def test_check_shows_each_tools_model_from_the_catalogs(mod):
    api = mount(mod)
    rows = asyncio.run(mod._check())
    assert rows == [
        ("ok", "generate_svg: recraft/recraft-v4.1-pro-vector (Recraft V4.1 Pro Vector, the default): SVG output, 1-6 a "
               "call, $0.30 an image (checked in OpenRouter's catalog)"),
        ("ok", "generate_image: openai/gpt-image-2.5-sunburst (GPT Image 2.5 Sunburst, the default): takes reference "
               "images, $0.006-$0.211 an image by quality (checked in Opper's catalog)"),
        ("ok", "edit_image: sourceful/riverflow-v2.5-pro (Riverflow V2.5 Pro, the default): up to 10 input images, "
               "$0.13-$0.17 an image by resolution (checked in OpenRouter's catalog)")]
    assert api.paid == []


def test_check_names_models_set_in_stack_env(mod, monkeypatch):
    monkeypatch.setenv("IMAGE_STUDIO_SVG_MODEL", "acme/vector-2")
    monkeypatch.setenv("IMAGE_STUDIO_IMAGE_MODEL", "google/imagen-5-ultra")
    monkeypatch.setenv("IMAGE_STUDIO_EDIT_MODEL", "google/gemini-3-pro-image")
    mount(mod, sticky={
        discovery("acme/vector-2"): endpoint("acme/vector-2", {"output_format": {"type": "enum", "values": ["svg", "png"]}},
                                             price=0.08),
        discovery("google/gemini-3-pro-image"): endpoint("google/gemini-3-pro-image", {
            "input_references": {"type": "range", "min": 0, "max": 3}}, price=0.134),
        OPPER_MODELS: catalog(GPT_ENTRY, IMAGEN)})
    rows = dict((t.split(":")[0], (lvl, t)) for lvl, t in asyncio.run(mod._check()))
    assert rows["generate_svg"] == ("ok", "generate_svg: acme/vector-2 (from stack.env): SVG output, 1 a call, "
                                          "$0.08 an image (checked in OpenRouter's catalog)")
    assert rows["generate_image"] == ("ok", "generate_image: google/imagen-5-ultra (from stack.env): no reference "
                                            "images, $0.06 an image (checked in Opper's catalog)")
    assert rows["edit_image"][1].endswith(": up to 3 input images, $0.134 an image (checked in OpenRouter's catalog)")


def test_check_fails_a_model_that_cant_do_its_job(mod, monkeypatch):
    monkeypatch.setenv("IMAGE_STUDIO_SVG_MODEL", "acme/raster-only")
    monkeypatch.setenv("IMAGE_STUDIO_IMAGE_MODEL", "acme/nothing-here")
    monkeypatch.setenv("IMAGE_STUDIO_EDIT_MODEL", "acme/text-to-image")
    api = mount(mod, sticky={
        discovery("acme/raster-only"): endpoint("acme/raster-only", {"output_format": {"type": "enum", "values": ["png", "jpeg"]}}),
        discovery("acme/text-to-image"): endpoint("acme/text-to-image", {"aspect_ratio": {"type": "enum", "values": ["1:1"]}})})
    rows = asyncio.run(mod._check())
    assert [lvl for lvl, _ in rows] == ["FAIL", "FAIL", "FAIL"]
    assert rows[0][1].startswith("IMAGE_STUDIO_SVG_MODEL=acme/raster-only can't make SVG (png, jpeg): pick a vector model")
    assert rows[1][1].startswith("IMAGE_STUDIO_IMAGE_MODEL=acme/nothing-here isn't an Opper image model")
    assert rows[2][1].startswith("IMAGE_STUDIO_EDIT_MODEL=acme/text-to-image takes no input images")
    monkeypatch.setenv("IMAGE_STUDIO_EDIT_MODEL", RECRAFT)                          # SVG out: edit_image saves rasters
    assert asyncio.run(mod._check())[2] == ("FAIL", "IMAGE_STUDIO_EDIT_MODEL=recraft/recraft-v4.1-pro-vector makes only "
                                                    "svg, and edit_image saves PNG, JPEG or WebP: pick a raster model such "
                                                    "as sourceful/riverflow-v2.5-pro (vector work: generate_svg)")
    with pytest.raises(ValueError, match="makes only svg"):
        call(mod.edit_image(["https://example.test/a.jpg"], "x"))
    monkeypatch.setenv("IMAGE_STUDIO_EDIT_MODEL", "acme/gone")
    mount(mod, sticky={discovery("acme/gone"): lambda req: httpx.Response(404, json={"error": {"message": "not found"}})})
    assert asyncio.run(mod._check())[2] == ("FAIL", "IMAGE_STUDIO_EDIT_MODEL=acme/gone isn't an OpenRouter image model: "
                                                    "pick one at https://openrouter.ai/models?output_modalities=image")
    assert api.paid == []


def test_check_without_a_key_or_a_catalog(mod, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY")
    down = {OPPER_MODELS: lambda req: httpx.Response(503, json={"error": {"message": "maintenance"}})}
    api = mount(mod, sticky=down)
    svg, image, edit = asyncio.run(mod._check())
    assert svg == ("WARN", "generate_svg: recraft/recraft-v4.1-pro-vector (Recraft V4.1 Pro Vector, the default): SVG "
                           "output, 1-6 a call, $0.30 an image (checked in OpenRouter's catalog); OPENROUTER_API_KEY is "
                           "empty, so generate_svg can't run yet")
    assert edit[0] == "WARN" and edit[1].endswith("; OPENROUTER_API_KEY is empty, so edit_image can't run yet")
    assert image[0] == "WARN" and "(the stack's copy: Opper's catalog couldn't be read: Opper 503" in image[1]
    assert all("authorization" not in r.headers for r in api.requests)       # catalogs are read without a key
    monkeypatch.setenv("IMAGE_STUDIO_IMAGE_MODEL", "acme/new-model")
    image = asyncio.run(mod._check())[1]
    assert image[0] == "WARN" and "acme/new-model (from stack.env): not checked — Opper's catalog couldn't be read" in image[1]


def test_check_flags_settings_nothing_reads(mod, monkeypatch):
    monkeypatch.setenv("LUMENFALL_API_KEY", "lf-live-secret-1")
    monkeypatch.setenv("OPPER_IMAGE_MODEL", "bytedance:ap/seedream-5-pro")
    mount(mod)
    rows = asyncio.run(mod._check())
    assert rows[3:] == [
        ("WARN", "LUMENFALL_API_KEY is set but image-studio doesn't read it (generate_svg runs on OpenRouter, with "
                 "OPENROUTER_API_KEY): delete it from stack.env"),
        ("WARN", "OPPER_IMAGE_MODEL is set but image-studio doesn't read it (generate_image's model is "
                 "IMAGE_STUDIO_IMAGE_MODEL): delete it from stack.env")]
    assert "lf-live-secret-1" not in json.dumps(rows)


def test_check_runs_as_a_command_and_fails_a_bad_setting(home, tmp_path):
    env = {k: v for k, v in os.environ.items()
           if k not in ("OPPER_API_KEY", "OPENROUTER_API_KEY") and "proxy" not in k.lower()}
    env.update(STACK_ENV_FILE=str(tmp_path / "missing.env"), IMAGE_STUDIO_SVG_MODEL="not a model",
               OPPER_BASE_URL="https://127.0.0.1:9", OPENROUTER_BASE_URL="https://127.0.0.1:9/api/v1")
    r = subprocess.run([sys.executable, str(MODULE), "--check"], env=env, capture_output=True, text=True, timeout=120)
    lines = r.stdout.splitlines()
    assert r.returncode == 1 and len(lines) == 3, r.stdout + r.stderr
    assert lines[0] == ("  FAIL  generate_svg: IMAGE_STUDIO_SVG_MODEL isn't a model id: 'not a model' (fix it in "
                        "~/.claude/stack.env)")
    assert lines[1].startswith("  WARN  generate_image: openai/gpt-image-2.5-sunburst (GPT Image 2.5 Sunburst, the "
                               "default): takes reference images, $0.006-$0.211 an image by quality (the stack's copy: "
                               "Opper's catalog couldn't be read: Opper: ConnectError")
    assert lines[1].endswith("; OPPER_API_KEY is empty, so generate_image can't run yet")
    assert lines[2].startswith("  WARN  edit_image: sourceful/riverflow-v2.5-pro (Riverflow V2.5 Pro, the default): up "
                               "to 10 input images, $0.13-$0.17 an image by resolution (the stack's copy")
    env.pop("IMAGE_STUDIO_SVG_MODEL")
    assert subprocess.run([sys.executable, str(MODULE), "--check"], env=env, capture_output=True,
                          timeout=120).returncode == 0


def test_an_edit_only_opper_model_needs_references(mod, monkeypatch):
    retoucher = {"id": "acme/retoucher", "capabilities": ["image_edit"],
                 "params": {"image": {"aspect_ratios": ["1:1", "16:9"], "resolutions": ["1K"]}}}
    monkeypatch.setenv("IMAGE_STUDIO_IMAGE_MODEL", "acme/retoucher")
    api = mount(mod, {GPT_POST: [job_202("r1")], status_route("r1"): [done(data=real_png(32, 32))]},
                {OPPER_MODELS: catalog(retoucher)})
    with pytest.raises(ValueError, match="IMAGE_STUDIO_IMAGE_MODEL=acme/retoucher only edits images"):
        call(mod.generate_image("x"))
    assert api.paid == []
    out, _ = call(mod.generate_image("x", reference_images=["https://example.test/r.jpg"]))
    assert len(api.paid) == 1 and out["images"]


def test_an_edit_model_that_also_makes_svg_is_asked_for_a_raster(mod, monkeypatch):
    monkeypatch.setenv("IMAGE_STUDIO_EDIT_MODEL", "acme/both")
    api = mount(mod, {OR_POST: [or_ok(or_item(real_png(64, 64), "image/png"), cost=0.1)]}, {
        discovery("acme/both"): endpoint("acme/both", {"output_format": {"type": "enum", "values": ["svg", "png"]},
                                                       "input_references": {"type": "range", "min": 0, "max": 2}})})
    out, _ = call(mod.edit_image(["https://example.test/a.jpg"], "x"))
    assert api.bodies(OR_POST)[0]["output_format"] == "png" and out["images"]



# ---------------------------------------------------------------- catalog quirks (independent review, round 10)
def test_only_openrouters_own_not_found_means_an_unknown_model(mod):
    api = mount(mod, {OR_POST: [or_ok(or_item(SVG))]}, {discovery(RECRAFT): lambda req: httpx.Response(404, text="404 Not Found")})
    out, _ = call(mod.generate_svg("logo"))              # a missing route (a gateway?): the stack's copy of the entry
    assert len(out["images"]) == 1 and len(api.paid) == 1
    gone = {discovery(RECRAFT): lambda req: httpx.Response(404, json={"error": {"message": 'No image model found for "x"',
                                                                                "code": 404}})}
    api = mount(mod, sticky=gone)
    with pytest.raises(ValueError, match="isn't an OpenRouter image model"):
        call(mod.generate_svg("logo"))
    assert api.paid == []


def test_a_catalog_entry_in_an_unknown_shape_falls_back_to_the_stacks_copy(mod):
    def listy(req):
        return httpx.Response(200, json={"id": "x", "endpoints": [{"provider_slug": "recraft", "supported_parameters": [
            "aspect_ratio", "output_format", "n", "input_references"]}]})
    api = mount(mod, {OR_POST: [or_ok(or_item(SVG)), or_ok(or_item(real_png(64, 64), "image/png"), cost=0.13)]},
                {discovery(RECRAFT): listy, discovery(RIVERFLOW): listy})
    out, _ = call(mod.generate_svg("logo", colors=["#112233"]))
    assert len(out["images"]) == 1
    assert api.bodies(OR_POST)[0]["provider"] == {"options": {"recraft": {"controls": {"colors": [{"rgb": [17, 34, 51]}]}}}}
    out, _ = call(mod.edit_image(["https://example.test/a.jpg"], "x"))
    assert len(out["images"]) == 1 and ("openrouter", RECRAFT) not in mod._CATALOG     # never cached


def test_a_model_no_provider_serves_is_refused(mod, monkeypatch):
    monkeypatch.setenv("IMAGE_STUDIO_SVG_MODEL", "meta/muse-image")
    api = mount(mod, sticky={discovery("meta/muse-image"): lambda req: httpx.Response(200, json={"id": "meta/muse-image",
                                                                                                 "endpoints": []})})
    with pytest.raises(ValueError, match="no provider serves this model on OpenRouter right now"):
        call(mod.generate_svg("logo"))
    assert api.paid == [] and asyncio.run(mod._check())[0][0] == "FAIL"


def test_models_that_need_reference_images(mod, monkeypatch):
    styles = "recraft/recraft-v4-styles-vector"
    monkeypatch.setenv("IMAGE_STUDIO_SVG_MODEL", styles)
    api = mount(mod, {OR_POST: [or_ok(or_item(SVG))]}, {discovery(styles): endpoint(styles, {
        "output_format": {"type": "enum", "values": ["svg"]}, "input_references": {"type": "range", "min": 1, "max": 10}},
        ["controls"], 0.3, slug="recraft")})
    with pytest.raises(ValueError, match="needs a reference image on every call: pass reference_image"):
        call(mod.generate_svg("logo"))
    assert api.paid == []
    out, _ = call(mod.generate_svg("logo", reference_image="https://example.test/style.png"))
    assert len(out["images"]) == 1 and "a reference image required on every call" in asyncio.run(mod._check())[0][1]
    monkeypatch.setenv("IMAGE_STUDIO_SVG_MODEL", "acme/two-refs")
    monkeypatch.setenv("IMAGE_STUDIO_EDIT_MODEL", "acme/pairs")
    api = mount(mod, sticky={
        discovery("acme/two-refs"): endpoint("acme/two-refs", {"output_format": {"type": "enum", "values": ["svg"]},
                                                               "input_references": {"type": "range", "min": 2, "max": 4}}),
        discovery("acme/pairs"): endpoint("acme/pairs", {"output_format": {"type": "enum", "values": ["png"]},
                                                         "input_references": {"type": "range", "min": 2, "max": 4}})})
    with pytest.raises(ValueError, match="needs 2 reference images on every call, and generate_svg sends at most one"):
        call(mod.generate_svg("logo", reference_image="https://example.test/style.png"))
    with pytest.raises(ValueError, match="needs at least 2 input images"):
        call(mod.edit_image(["https://example.test/a.jpg"], "x"))
    assert api.paid == []


def test_an_opper_model_that_answers_with_svg_keeps_what_was_paid_for(mod, monkeypatch):
    bria = {"id": "deepinfra/Bria/Bria-3.2-vector", "capabilities": ["image_generation"], "params": {},
            "pricing": {"price_per_generation": 0.04}}
    monkeypatch.setenv("IMAGE_STUDIO_IMAGE_MODEL", bria["id"])
    api = mount(mod, {GPT_POST: [httpx.Response(200, json={"data": [{"b64_json": b64(SVG)}], "usage": {"cost": 0.04}}),
                                 job_202("v2")],
                      status_route("v2"): [done(url="https://files.opper.test/v2.svg", cost=0.04, mime="image/svg+xml")],
                      "GET https://files.opper.test/v2.svg": [httpx.Response(200, content=SVG)]},
                {OPPER_MODELS: catalog(bria)})
    out, _ = call(mod.generate_image("a fox"))
    saved = Path(out["images"][0]["path"])
    assert saved.suffix == ".svg" and "script" not in saved.read_text() and out["cost_usd"] == 0.04
    assert "the model returned SVG: saved as a sanitized .svg" in out["notes"]
    out, _ = call(mod.generate_image("a fox"))           # the same through a job and a download
    assert Path(out["images"][0]["path"]).suffix == ".svg" and len(api.paid) == 2


def test_the_defaults_details_describe_only_the_default_model(home, monkeypatch):
    monkeypatch.setenv("IMAGE_STUDIO_EDIT_MODEL", RECRAFT)
    monkeypatch.setenv("IMAGE_STUDIO_SVG_MODEL", RIVERFLOW)
    m = load("image_studio_swapped")
    assert "$0.13 at 1K" not in m._edit_description() and "checked before paying" in m._edit_description()
    assert "about $0.30 each" not in m._svg_description() and "catalog before paying" in m._svg_description()


def test_a_key_pasted_into_a_model_setting_is_refused_and_never_shown(mod, monkeypatch):
    monkeypatch.setenv("IMAGE_STUDIO_SVG_MODEL", KEYS["openrouter.test"])
    api = mount(mod)
    with pytest.raises(ValueError, match="IMAGE_STUDIO_SVG_MODEL holds an API key, not a model id") as err:
        call(mod.generate_svg("logo"))
    assert KEYS["openrouter.test"] not in str(err.value) and api.requests == []
    assert KEYS["opper.test"] not in str(mod.ModelError("model " + KEYS["opper.test"]))


def test_a_transparent_background_needs_a_format_with_alpha(mod, monkeypatch):
    fast = "sourceful/riverflow-v2.5-fast"
    monkeypatch.setenv("IMAGE_STUDIO_EDIT_MODEL", fast)
    api = mount(mod, sticky={discovery(fast): endpoint(fast, {
        "output_format": {"type": "enum", "values": ["jpeg"]},
        "background": {"type": "enum", "values": ["auto", "transparent", "opaque"]},
        "input_references": {"type": "range", "min": 0, "max": 10}})})
    with pytest.raises(ValueError, match="makes only jpeg: a transparent background needs PNG or WebP"):
        call(mod.edit_image(["https://example.test/a.png"], "cut out the product", background="transparent"))
    assert api.paid == []
    monkeypatch.setenv("IMAGE_STUDIO_EDIT_MODEL", RIVERFLOW)
    api = mount(mod, {OR_POST: [or_ok(or_item(real_png(8, 8), "image/png"))]})
    call(mod.edit_image(["https://example.test/a.png"], "cut out the product", background="transparent"))
    assert api.bodies(OR_POST)[0]["output_format"] == "png" and api.bodies(OR_POST)[0]["background"] == "transparent"
    monkeypatch.setenv("IMAGE_STUDIO_IMAGE_MODEL", "acme/jpeg-only")
    jpeg_only = {"id": "acme/jpeg-only", "capabilities": ["image_generation"], "params": {"image": {
        "aspect_ratios": ["1:1"], "parameters": [{"name": "output_format", "enum": ["jpeg"]}, {"name": "background",
                                                                                            "enum": ["transparent"]}]}}}
    api = mount(mod, sticky={OPPER_MODELS: catalog(jpeg_only)})
    with pytest.raises(ValueError, match="makes only jpeg: a transparent background needs PNG or WebP"):
        call(mod.generate_image("x", background="transparent"))
    assert api.paid == []
