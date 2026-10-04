# /// script
# requires-python = ">=3.10"
# dependencies = ["mcp>=1.10,<2", "httpx>=0.27", "pillow>=10"]
# [tool.uv]
# exclude-newer = "2026-09-27T00:00:00Z"
# ///
"""image-studio — the stack's image tools: one job per tool, the model of each set in stack.env.

- generate_svg → OpenRouter, IMAGE_STUDIO_SVG_MODEL (default recraft/recraft-v4.1-pro-vector,
  Recraft V4.1 Pro Vector, about $0.30 an image). Logos, icons, illustrations, posters and other
  graphic design, always SVG: every request asks for output_format "svg", a model that can't make
  SVG is refused before paying, and an item that isn't SVG is refused and never saved.
- generate_image → Opper, IMAGE_STUDIO_IMAGE_MODEL (default openai/gpt-image-2.5-sunburst, GPT Image
  2.5 Sunburst, about $0.006 at low quality to $0.21 at max for 1024x1024). Photographs and other
  raster images, 1-4 a call, optional style or subject references.
- edit_image → OpenRouter, IMAGE_STUDIO_EDIT_MODEL (default sourceful/riverflow-v2.5-pro, Riverflow
  V2.5 Pro, $0.13 at 1K, $0.15 at 2K, $0.17 at 4K). Edits and composites of input images.
- collect_image → saves an Opper image that was still rendering (or couldn't be fetched) when
  generate_image returned; job ids are also logged to .image-studio-jobs.jsonl in the output folder.
Before a paid request, each call reads its model's entry in the provider's own public image-model
catalog, without a key (OpenRouter GET /images/models/{id}/endpoints, Opper GET /v3/images/models;
cached per session) and checks the arguments against it: a parameter the model lacks, a value outside its list, a model that
doesn't exist, or an SVG model that can't make SVG is refused before paying. When a catalog can't be
reached, the stack's own copy of the default models' entries is used, and any other model's request
goes out unchecked. Files go to disk and only their paths and facts come back; a preview (a small
render, never saved) is returned only when asked for. `image_studio_mcp.py --check` prints the model
of each tool as found in its catalog (bin/doctor.sh runs it; no paid call, no key needed).

APIs
- OpenRouter: POST {OPENROUTER_BASE_URL}/images — model, prompt, n, aspect_ratio, resolution,
  output_format, background, input_references, provider.options.<provider slug> (Recraft's palette
  goes in its "controls"). Response data[].b64_json + media_type, usage.cost.
  https://openrouter.ai/docs/guides/overview/multimodal/image-generation
- Opper: POST {OPPER_BASE_URL}/v3/images with async: true → 202 {id, status_url}; GET status_url
  until "completed" (presigned url, mime_type) or "failed". size WxH or aspect_ratio + resolution
  (whichever the model takes), quality, reference_images, store false, parameters {output_format,
  background}. https://docs.opper.ai/build/multimodal/images

Env (from the environment, else $STACK_ENV_FILE, else <config dir>/stack.env next to this script's
parent, else ~/.claude/stack.env): OPENROUTER_API_KEY (generate_svg, edit_image), OPPER_API_KEY
(generate_image); IMAGE_STUDIO_SVG_MODEL, IMAGE_STUDIO_IMAGE_MODEL, IMAGE_STUDIO_EDIT_MODEL (empty =
the default); OPENROUTER_BASE_URL, OPPER_BASE_URL; IMAGE_STUDIO_OUT_DIR (default
~/Pictures/image-studio; an older OPENROUTER_IMAGE_OUT_DIR is honored); IMAGE_STUDIO_TIMEOUT (seconds
to wait for one call, default 900); IMAGE_STUDIO_MAX_UPLOAD_MB (one local input image, default 50);
STACK_IMAGE_MAX_PX (longest side of an image sent to a model, default 1919: bigger inputs go out as
scaled copies made in memory).

Security: each key goes only to its own provider's host, authenticated requests never follow
redirects, and keys are redacted from every error. Opper's presigned result URLs are fetched with no
key, over https to a host that resolves to public addresses (or Opper's own host), following at most
5 redirects under the same rule and stopping at 200 MB. A local input image is sent only if it is a
real PNG/JPEG/WebP outside credential and config folders. Saved SVGs are rebuilt from the parsed tree
without DOCTYPE, scripts, foreignObject, event handlers, links that leave the document (only
#fragments and embedded PNG/JPEG/GIF/WebP data stay) or animations that target them. A file never
overwrites another, and a paid result that can't be saved yet is reported with what it takes to
fetch it.
"""
from __future__ import annotations

import asyncio
import base64
import binascii
import io
import ipaddress
import json
import logging
import math
import os
import re
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import quote, unquote, urljoin, urlparse

import httpx
from mcp.server.fastmcp import FastMCP, Image


def _env_file_candidates() -> list:
    cands = []
    if os.environ.get("STACK_ENV_FILE"):
        cands.append(Path(os.environ["STACK_ENV_FILE"]).expanduser())
    cands.append(Path(__file__).resolve().parent.parent / "stack.env")
    cands.append(Path("~/.claude/stack.env").expanduser())
    return cands


def _env_value(raw: str) -> str:
    """A value the way the shell that sources stack.env reads it (same rules as bin/mcp-headers and
    bin/with-stack-env): "quoted" or 'quoted' with anything after the closing quote dropped, or a
    bare value with an unquoted " # comment" removed."""
    v = raw.strip()
    if v[:1] in ("'", '"') and v[0] in v[1:]:
        return v[1:v.index(v[0], 1)]
    return re.split(r"\s+#", v, maxsplit=1)[0].strip()


def _load_env_file() -> None:
    f = next((c for c in _env_file_candidates() if c.is_file()), None)
    if f is None:
        return
    for line in f.read_text().splitlines():
        m = re.match(r"\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)$", line.rstrip("\r"))
        if m and not line.lstrip().startswith("#"):
            k, v = m.group(1), os.path.expandvars(_env_value(m.group(2)))
            if v and not os.environ.get(k):
                os.environ[k] = v


def _env(*names: str, default: str = "") -> str:
    return next((os.environ[n] for n in names if os.environ.get(n)), default)


_load_env_file()
PROVIDERS = {
    "opper": {"name": "Opper", "key": "OPPER_API_KEY", "tool": "generate_image",
              "base": _env("OPPER_BASE_URL", default="https://api.opper.ai").rstrip("/"),
              "keys": "https://platform.opper.ai"},
    "openrouter": {"name": "OpenRouter", "key": "OPENROUTER_API_KEY", "tool": "generate_svg and edit_image",
                   "base": _env("OPENROUTER_BASE_URL", default="https://openrouter.ai/api/v1").rstrip("/"),
                   "keys": "https://openrouter.ai/settings/keys"},
}
# The model of each tool: set in stack.env, these are the defaults.
MODELS = {
    "svg": {"env": "IMAGE_STUDIO_SVG_MODEL", "default": "recraft/recraft-v4.1-pro-vector", "provider": "openrouter"},
    "image": {"env": "IMAGE_STUDIO_IMAGE_MODEL", "default": "openai/gpt-image-2.5-sunburst", "provider": "opper"},
    "edit": {"env": "IMAGE_STUDIO_EDIT_MODEL", "default": "sourceful/riverflow-v2.5-pro", "provider": "openrouter"},
}
MODEL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@+/-]{0,159}$")
NAMES = {"recraft/recraft-v4.1-pro-vector": "Recraft V4.1 Pro Vector", "sourceful/riverflow-v2.5-pro": "Riverflow V2.5 Pro",
         "openai/gpt-image-2.5-sunburst": "GPT Image 2.5 Sunburst", "openai/gpt-image-2.5-flare": "GPT Image 2.5 Flare"}
# OpenRouter's catalog entries for the default models, as read on 27 September 2026 (GET
# /images/models/{id}/endpoints): used only when the live catalog can't be reached.
OR_KNOWN = {
    "recraft/recraft-v4.1-pro-vector": [{
        "provider_slug": "recraft",
        "supported_parameters": {
            "aspect_ratio": {"type": "enum", "values": ["1:1", "4:3", "3:4", "16:9", "9:16", "auto"]},
            "output_format": {"type": "enum", "values": ["svg"]},
            "n": {"type": "range", "min": 1, "max": 6},
            "input_references": {"type": "range", "min": 0, "max": 1}},
        "allowed_passthrough_parameters": ["style", "controls", "text_layout"],
        "pricing": [{"billable": "output_image", "unit": "image", "cost_usd": 0.3}]}],
    "sourceful/riverflow-v2.5-pro": [{
        "provider_slug": "sourceful",
        "supported_parameters": {
            "resolution": {"type": "enum", "values": ["1K", "2K", "4K"]},
            "aspect_ratio": {"type": "enum", "values": ["1:1", "4:3", "3:4", "3:2", "2:3", "16:9", "9:16", "21:9", "auto"]},
            "output_format": {"type": "enum", "values": ["png", "jpeg", "webp"]},
            "background": {"type": "enum", "values": ["auto", "transparent", "opaque"]},
            "n": {"type": "range", "min": 1, "max": 1},
            "input_references": {"type": "range", "min": 0, "max": 10}},
        "allowed_passthrough_parameters": ["font_inputs"],
        "pricing": [{"billable": "output_image", "unit": "image", "cost_usd": 0.13},
                    {"billable": "output_image", "unit": "image", "cost_usd": 0.15, "variant": "2k"},
                    {"billable": "output_image", "unit": "image", "cost_usd": 0.17, "variant": "4k"}]}],
}
# Opper's catalog entry for GPT Image 2.5 (Flare and Sunburst share it; GET /v3/images/models, September
# 2026) and OpenAI's per-image output cost at 1024x1024 by quality ($30 per million output tokens).
GPT_IMAGE = {
    "capabilities": ["image_generation", "image_edit"],
    "image": {"sizes": ["1024x1024", "1536x1024", "1024x1536", "auto"],
              "qualities": ["low", "medium", "high", "xhigh", "max", "auto"],
              "size_constraints": {"multiple_of": 16, "max_edge": 3840, "max_ratio": 3,
                                   "min_pixels": 655360, "max_pixels": 8294400},
              "parameters": [{"name": "output_format", "enum": ["png", "jpeg", "webp"]},
                             {"name": "output_compression"},
                             {"name": "background", "enum": ["auto", "opaque", "transparent"]},
                             {"name": "moderation", "enum": ["auto", "low"]}]},
    "prices": {"low": 0.006, "medium": 0.013, "high": 0.053, "xhigh": 0.094, "max": 0.211},
    "quality": "high",
}
OPPER_KNOWN = {"openai/gpt-image-2.5-sunburst": GPT_IMAGE, "openai/gpt-image-2.5-flare": GPT_IMAGE}
TIERS = {"1K": 1024, "2K": 1440, "4K": 2160}                 # a pixel-sized model's short side per tier
MAX_OPPER_N, MAX_OPPER_REFS = 4, 8
OUT_DIR = Path(_env("IMAGE_STUDIO_OUT_DIR", "OPENROUTER_IMAGE_OUT_DIR", default="~/Pictures/image-studio")).expanduser()
TIMEOUT = float(_env("IMAGE_STUDIO_TIMEOUT", default="900"))
POLL_TIMEOUT, DOWNLOAD_TIMEOUT = 30.0, 120.0       # seconds for one status check / one result download
JOB_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
DONE, FAILED = {"completed", "succeeded", "success", "done"}, {"failed", "error", "cancelled", "canceled", "expired"}
POLL = (2, 3, 5)                                             # seconds between status checks, then 5
MAX_POLL_ERRORS = 12                                         # a job with this many failed checks in a row is parked
LEDGER = ".image-studio-jobs.jsonl"
FORMATS = ("png", "jpeg", "webp")
BACKGROUNDS = ("auto", "transparent", "opaque")
BUDGET = {"openrouter": 4_400_000, "opper": 12_000_000}      # bytes of inline images in one request
RASTER_EXT = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}
REF_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}
REF_MIMES = {"image/png", "image/jpeg", "image/webp"}
HEX = re.compile(r"^#?([0-9a-fA-F]{6}|[0-9a-fA-F]{3})$")
MAX_REDIRECTS, MAX_DOWNLOAD = 5, 200 * 1024 * 1024
_COMMON = {408: "the request timed out: retry", 413: "the request is too large (the input images?)",
           429: "rate limited: wait a little and retry", 500: "the service failed: retry",
           502: "the model failed upstream: retry", 503: "no provider is available right now: retry later",
           504: "the provider timed out: retry"}
ERRORS = {
    "opper": {**_COMMON, 400: "the request was rejected", 401: "OPPER_API_KEY is missing or invalid",
              402: "not enough credits: top up at https://platform.opper.ai",
              403: "refused by moderation or permissions (the prompt may have been flagged)",
              404: "not found (the model, or a job that expired)"},
    "openrouter": {**_COMMON, 400: "the request was rejected", 401: "OPENROUTER_API_KEY is missing or invalid",
                   402: "not enough credits on the account or this key: add credits or raise the key's "
                        "limit at https://openrouter.ai/settings",
                   403: "refused by moderation or permissions (the prompt may have been flagged)",
                   404: "the model isn't available: check IMAGE_STUDIO_SVG_MODEL / IMAGE_STUDIO_EDIT_MODEL in "
                        "stack.env, and that your account's provider settings "
                        "(https://openrouter.ai/settings/preferences) allow the model's provider",
                   502: "the model failed upstream (not billed): retry"},
}
_TRANSPORT = None  # tests inject an httpx.MockTransport here
_CATALOG: dict = {}  # (provider, model) -> capabilities read from the provider's catalog this session
_CATALOG_ERR: dict = {}  # provider -> why its catalog couldn't be read (for --check)

logging.getLogger("httpx").setLevel(logging.WARNING)
mcp = FastMCP("image-studio", log_level="WARNING")


# ---------------------------------------------------------------------------- HTTP, keys, downloads
class ApiError(RuntimeError):
    """An HTTP error from a provider; keeps the status and the provider's own error fields."""

    def __init__(self, provider: str, status: int, message: str, detail: str, json_error: bool = False):
        super().__init__(message)
        self.provider, self.status, self.detail, self.json_error = provider, status, detail, json_error

    def about(self, *words: str) -> bool:
        """Whether the provider's error fields name one of these words (never for a moderation refusal)."""
        if re.search(r"content[_ ]?policy|moderat|safety|flagged", self.detail):
            return False
        return any(re.search(r"\b%s\b" % re.escape(w), self.detail) for w in words)


def _redact(text: str) -> str:
    for p in PROVIDERS.values():
        k = (os.environ.get(p["key"]) or "").strip()
        if len(k) >= 4:
            text = text.replace(k, "<" + p["key"] + ">")
    return text


def _key(provider: str) -> str:
    p = PROVIDERS[provider]
    key = (os.environ.get(p["key"]) or "").strip()
    if not key:
        raise RuntimeError(f"{p['key']} is not set: {p['tool']} can't run without it. Put your {p['name']} key "
                           f"in ~/.claude/stack.env ({p['keys']})")
    if not re.fullmatch(r"[\x21-\x7e]+", key):
        raise RuntimeError(f"{p['key']} contains spaces or control characters: fix it in ~/.claude/stack.env")
    return key


def _client() -> httpx.AsyncClient:
    # Never follow redirects: an authenticated request must not carry a key off-host.
    return httpx.AsyncClient(timeout=httpx.Timeout(TIMEOUT, connect=30.0), follow_redirects=False,
                             transport=_TRANSPORT)


def _origin(url: str) -> tuple:
    u = urlparse(url)
    return (u.scheme.lower(), (u.netloc or "").lower())


def _error(provider: str, r: httpx.Response) -> ApiError:
    why = ERRORS[provider].get(r.status_code, "request failed")
    detail, err = "", None
    try:
        body = r.json()
        err = body.get("error") if isinstance(body, dict) else None
        if isinstance(err, dict):
            detail = " ".join(str(err.get(k) or "") for k in ("code", "type", "param", "message"))
        elif isinstance(err, str):
            detail = err
        elif isinstance(body, dict):
            detail = str(body.get("message") or body.get("detail") or "")
    except ValueError:
        detail = r.text[:600]
    msg = f"{PROVIDERS[provider]['name']} {r.status_code}: {why}: {r.text[:600]}"
    return ApiError(provider, r.status_code, _redact(msg), _redact(detail).lower(), isinstance(err, dict))


async def _authed(c: httpx.AsyncClient, provider: str, method: str, url: str, **kw) -> httpx.Response:
    """A request with the provider's key, only ever to that provider's own origin."""
    p = PROVIDERS[provider]
    if _origin(url) != _origin(p["base"]):
        raise RuntimeError(f"refusing to send {p['key']} to {url[:160]}: not {p['base']}")
    headers = {"Authorization": "Bearer " + _key(provider)}
    if provider == "openrouter":
        headers["X-Title"] = "claude-agent-stack"
    try:
        r = await c.request(method, url, headers=headers, **kw)
    except Exception as exc:  # noqa: BLE001 - transport errors may quote the request: never the key
        raise RuntimeError(f"{p['name']}: {type(exc).__name__}: {_redact(str(exc))[:300]}") from None
    if r.is_redirect:
        raise RuntimeError(f"{p['name']} {r.status_code}: unexpected redirect (not followed)")
    if r.status_code >= 400:
        raise _error(provider, r)
    return r


async def _public_get(c: httpx.AsyncClient, provider: str, url: str, **kw) -> httpx.Response:
    """A GET with no key at all, to the provider's own origin: its public model catalog. Read keyless
    so that an account's own provider settings can't make a real model look unknown."""
    p = PROVIDERS[provider]
    if _origin(url) != _origin(p["base"]):
        raise RuntimeError(f"refusing to read {url[:160]}: not {p['base']}")
    try:
        r = await c.get(url, **kw)
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"{p['name']}: {type(exc).__name__}: {_redact(str(exc))[:300]}") from None
    if r.is_redirect:
        raise RuntimeError(f"{p['name']} {r.status_code}: unexpected redirect (not followed)")
    if r.status_code >= 400:
        raise _error(provider, r)
    return r


def _ip_literal(host: str):
    """The address a host names literally, including the legacy IPv4 forms (2130706433, 127.1,
    0x7f.1, 0177.0.0.1) that the resolver accepts; None for a name."""
    try:
        return ipaddress.ip_address(host)
    except ValueError:
        pass
    if re.fullmatch(r"[0-9a-fx.]+", host) and re.search(r"[0-9]", host):
        try:
            return ipaddress.ip_address(socket.inet_aton(host))
        except OSError:
            return None
    return None


def _downloadable(url: str) -> str:
    """The host of a result URL that may be fetched (without any key): https only, never localhost
    or a private, loopback or link-local address."""
    u = urlparse(url)
    host = (u.hostname or "").lower().rstrip(".")
    if u.scheme.lower() != "https" or not host:
        raise ValueError(f"refusing to download a result from a non-https URL: {url[:160]}")
    if host == "localhost" or host.endswith((".localhost", ".local", ".internal", ".home.arpa")):
        raise ValueError(f"refusing to download a result from a local host: {host}")
    ip = _ip_literal(host)
    if ip is not None and not ip.is_global:
        raise ValueError(f"refusing to download a result from a non-public address: {host}")
    return host


async def _resolve(host: str) -> list:
    """The addresses host resolves to here ([] when it doesn't); tests replace this."""
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    except OSError:
        return []
    return [sa[0] for *_, sa in infos]


def _pinned(url: str, host: str, addr: str) -> tuple:
    """(url, headers, extensions) that send `url` to the vetted address `addr` while the Host header
    and the TLS server name (SNI and certificate check) stay the original host name."""
    u = urlparse(url)
    bare = addr.split("%", 1)[0]
    ip = ipaddress.ip_address(bare)
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        bare, ip = str(ip.ipv4_mapped), ip.ipv4_mapped
    netloc = f"[{bare}]" if ip.version == 6 else bare
    if u.port:
        netloc += f":{u.port}"
    pinned = u._replace(netloc=netloc).geturl()
    hosthdr = (f"[{host}]" if ":" in host else host) + (f":{u.port}" if u.port else "")
    return pinned, {"Host": hosthdr}, {"sni_hostname": host}


async def _download(c: httpx.AsyncClient, provider: str, url: str) -> bytes:
    for _ in range(MAX_REDIRECTS + 1):
        target, headers, ext = url, {}, {}
        if _origin(url) != _origin(PROVIDERS[provider]["base"]):
            host = _downloadable(url)
            addrs = await _resolve(host)        # resolved once per hop: the request goes to this address
            if not addrs:
                raise ValueError(f"refusing to download a result from {host}: it does not resolve")
            for addr in addrs:
                ip = ipaddress.ip_address(addr.split("%", 1)[0])
                if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
                    ip = ip.ipv4_mapped
                if not ip.is_global:
                    raise ValueError(f"refusing to download a result from {host}: it resolves to a non-public address")
            target, headers, ext = _pinned(url, host, addrs[0])
        async with c.stream("GET", target, headers=headers, extensions=ext, timeout=DOWNLOAD_TIMEOUT) as r:   # no Authorization: none needed
            if r.is_redirect:
                url = urljoin(url, r.headers.get("location", ""))
                continue
            if r.status_code >= 400:
                raise RuntimeError(f"the download failed with HTTP {r.status_code}")
            buf = bytearray()
            async for chunk in r.aiter_bytes():
                buf += chunk
                if len(buf) > MAX_DOWNLOAD:
                    raise RuntimeError("the download is larger than 200 MB: refused")
            return bytes(buf)
    raise RuntimeError(f"too many redirects (> {MAX_REDIRECTS}) downloading a result")


async def _sleep(seconds: float) -> None:     # tests replace this and _now
    await asyncio.sleep(seconds)


def _now() -> float:
    return time.monotonic()


# ---------------------------------------------------------------------------- local files and inputs
def _deny_roots() -> list:
    home = Path.home()
    config = Path(os.environ.get("CLAUDE_CONFIG_DIR") or home / ".claude").expanduser()
    # the same secrets settings.json Read-denies (C4/C8): credential dirs and files, the config dir
    roots = [home / ".ssh", home / ".aws", home / ".gnupg", home / ".kube", home / ".docker",
             home / ".config" / "gcloud", home / "Library" / "Keychains", config,
             home / ".git-credentials", home / ".npmrc", home / ".pypirc", home / ".netrc",
             home / ".config" / "gh", home / ".cache" / "huggingface" / "token"]
    out = []
    for r in roots:
        out.append(r)
        try:
            out.append(r.resolve())
        except OSError:
            pass
    return out


def _check_allowed_path(p: Path, what: str) -> None:
    for root in _deny_roots():
        if p == root or root in p.parents:
            raise ValueError(f"{what} is inside a protected directory ({root}): refused")
    if any(part.startswith(".env") for part in p.parts):
        raise ValueError(f"{what} looks like an env/secret file: refused")


def _sniff(b: bytes) -> str:
    if b.startswith(b"\x89PNG"):
        return "image/png"
    if b[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if b[:4] == b"RIFF" and b[8:12] == b"WEBP":
        return "image/webp"
    if b[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    return "application/octet-stream"


def _is_svg(b: bytes) -> bool:
    head = b[:4096].lstrip(b"\xef\xbb\xbf \t\r\n").lower()
    return (head.startswith(b"<svg") or head.startswith(b"<?xml") or head.startswith(b"<!doctype svg")
            or head.startswith(b"<!--")) and b"<svg" in b[:65536].lower()


def _max_px() -> int:
    try:
        v = int(os.environ.get("STACK_IMAGE_MAX_PX", "1919"))
    except ValueError:
        v = 1919
    return v if v > 0 else 4096


def _image_size(b: bytes):
    """(width, height) from a PNG, JPEG, WebP or GIF header; None if unknown."""
    if b[:8] == b"\x89PNG\r\n\x1a\n" and len(b) >= 24:
        return int.from_bytes(b[16:20], "big"), int.from_bytes(b[20:24], "big")
    if b[:6] in (b"GIF87a", b"GIF89a") and len(b) >= 10:
        return int.from_bytes(b[6:8], "little"), int.from_bytes(b[8:10], "little")
    if b[:4] == b"RIFF" and b[8:12] == b"WEBP" and len(b) >= 30:
        kind = b[12:16]
        if kind == b"VP8 ":
            return int.from_bytes(b[26:28], "little") & 0x3FFF, int.from_bytes(b[28:30], "little") & 0x3FFF
        if kind == b"VP8L":
            bits = int.from_bytes(b[21:25], "little")
            return (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
        if kind == b"VP8X":
            return int.from_bytes(b[24:27], "little") + 1, int.from_bytes(b[27:30], "little") + 1
        return None
    if b[:2] == b"\xff\xd8":
        i, n = 2, len(b)
        while i + 9 < n:
            if b[i] != 0xFF:
                i += 1
                continue
            m = b[i + 1]
            if m == 0xFF or m == 0x01 or 0xD0 <= m <= 0xD8:
                i += 1 if m == 0xFF else 2
                continue
            seg = int.from_bytes(b[i + 2:i + 4], "big")
            if m in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                return int.from_bytes(b[i + 7:i + 9], "big"), int.from_bytes(b[i + 5:i + 7], "big")
            i += 2 + seg
    return None


def _verifies(data: bytes) -> bool:
    """Whether Pillow reads the image as intact (checksums, structure)."""
    try:
        from PIL import Image as PILImage
    except ImportError:
        return True
    try:
        with PILImage.open(io.BytesIO(data)) as im:
            im.verify()
        return True
    except Exception:   # noqa: BLE001 - any decoder complaint means a broken file
        return False


def _load_local(ref: str, what: str) -> tuple:
    """(bytes, mime) of a local PNG/JPEG/WebP after the path, type and size checks."""
    path = unquote(urlparse(ref).path) if ref.lower().startswith("file://") else ref
    given = Path(path).expanduser()
    try:
        p = given.resolve(strict=True)
    except (OSError, RuntimeError):
        raise ValueError(f"{what} not found: {ref}") from None
    st = p.stat()
    if not stat.S_ISREG(st.st_mode):
        raise ValueError(f"{what} is not a regular file: {ref}")
    _check_allowed_path(given.absolute(), what)
    _check_allowed_path(p, what)
    if p.suffix.lower() not in REF_SUFFIXES or given.suffix.lower() not in REF_SUFFIXES:
        raise ValueError(f"{what} must be a PNG, JPEG or WebP file")
    cap = float(_env("IMAGE_STUDIO_MAX_UPLOAD_MB", default="50")) * 1024 * 1024
    if st.st_size > cap:
        raise ValueError(f"{what} is larger than IMAGE_STUDIO_MAX_UPLOAD_MB: {ref}")
    data = p.read_bytes()
    mime = _sniff(data)
    if mime not in REF_MIMES:
        raise ValueError(f"{what} content is not a PNG, JPEG or WebP image: {ref}")
    return data, mime


def _encode_ref(data: bytes, mime: str, px: int, quality: int, force: bool) -> tuple:
    """The image as it goes out: unchanged when it fits px and nothing forces a re-encode, else
    scaled to fit px in memory (upright per EXIF), PNG when it has transparency, JPEG otherwise."""
    size = _image_size(data)
    if size and max(size) <= px and not force:
        return data, mime
    from PIL import Image as PILImage, ImageOps
    try:
        with PILImage.open(io.BytesIO(data)) as im:
            im = ImageOps.exif_transpose(im)
            alpha = im.mode in ("RGBA", "LA", "PA") or (im.mode == "P" and "transparency" in im.info)
            im = im.convert("RGBA" if alpha else "RGB")
            im.thumbnail((px, px), PILImage.Resampling.LANCZOS)
            buf = io.BytesIO()
            if alpha:
                im.save(buf, "PNG", optimize=True)
                return buf.getvalue(), "image/png"
            im.save(buf, "JPEG", quality=quality, optimize=True)
            return buf.getvalue(), "image/jpeg"
    except (OSError, ValueError, PILImage.DecompressionBombError) as exc:
        raise ValueError(f"an input image can't be read: {exc}") from exc


def _references(refs: list, what: str, budget: int) -> list:
    """URLs of the input images in the order given: https URLs as they are, local files as data URLs
    scaled under STACK_IMAGE_MAX_PX and together under the request budget."""
    items = []
    for ref in refs:
        ref = ref.strip() if isinstance(ref, str) else ""
        if not ref:
            raise ValueError(f"an empty {what}")
        if re.match(r"^https://", ref, re.I):
            items.append(("url", ref, None))
        elif re.match(r"^[a-z][a-z0-9+.-]*:", ref, re.I) and not ref.lower().startswith("file://"):
            raise ValueError(f"{what} must be a local path or an https URL")
        else:
            items.append(("file",) + _load_local(ref, what))
    px = _max_px()
    for size, quality, force in ((px, 90, False), (px, 80, True), (min(px, 1600), 75, True), (min(px, 1280), 70, True)):
        out, total = [], 0
        for kind, a, b in items:
            if kind == "url":
                out.append(a)
            else:
                data, mime = _encode_ref(a, b, size, quality, force)
                out.append(f"data:{mime};base64,{base64.b64encode(data).decode()}")
            total += len(out[-1])
        if total <= budget:
            return out
    raise ValueError("the input images don't fit in one request even at 1280 px: send fewer, or "
                     "https URLs of them")


def _rgb(color: str, what: str) -> list:
    m = HEX.match(color.strip())
    if not m:
        raise ValueError(f"{what} must be a hex color such as #1A73E8, not {color!r}")
    h = m.group(1)
    h = "".join(c * 2 for c in h) if len(h) == 3 else h
    return [int(h[i:i + 2], 16) for i in (0, 2, 4)]


# ---------------------------------------------------------------------------- SVG safety and facts
SVG_NS, XLINK_NS = "http://www.w3.org/2000/svg", "http://www.w3.org/1999/xlink"
ET.register_namespace("", SVG_NS)
ET.register_namespace("xlink", XLINK_NS)
_DROP = {"script", "foreignobject", "iframe", "embed", "object", "handler", "listener"}
_ANIMATION = {"animate", "set", "animatetransform", "animatemotion", "animatecolor"}
_LINKS = {"href", "src"}
_ANIM_VALUES = {"values", "to", "from", "by", "action", "formaction"}
_SAFE_DATA = re.compile(r"data:image/(?:png|jpe?g|gif|webp)[;,]")
_DOCTYPE = re.compile(r"<!DOCTYPE\b(?:[^\[>]|\[.*?\])*>", re.I | re.S)
_CSS_URL = re.compile(r"url\(\s*(['\"]?)(.*?)\1\s*\)", re.I | re.S)
_CSS_IMPORT = re.compile(r"@import\b[^;]*;?", re.I)


def _local(name: str) -> str:
    return name.rsplit("}", 1)[-1].rsplit(":", 1)[-1].lower()


def _plain(value: str) -> str:
    return re.sub(r"[\x00-\x20]+", "", value).lower()


def _safe_link(value: str) -> bool:
    """Only in-document references and embedded PNG/JPEG/GIF/WebP data: no file:, http(s):, text:,
    msl:, script or other external target."""
    v = _plain(value)
    return v.startswith("#") or bool(_SAFE_DATA.match(v))


def _unsafe_value(value: str) -> bool:
    v = _plain(value)
    return "javascript:" in v or "vbscript:" in v or (v.startswith("data:") and not _SAFE_DATA.match(v))


def _clean_css(css: str) -> tuple:
    """(css, changed): without @import and with every url() that leaves the document set to none."""
    out = _CSS_IMPORT.sub("", css)
    out = _CSS_URL.sub(lambda m: m.group(0) if _safe_link(m.group(2)) else "none", out)
    return out, out != css


def _sanitize(data: bytes) -> tuple:
    """(clean SVG text, items removed) from the parsed tree: no DOCTYPE, no script, foreignObject or
    other embedding element in any namespace, no on* attribute, no link or CSS url() outside the
    document (after entity decoding), no @import and no animation that targets a link or a handler.
    Raises ValueError for anything that isn't a well-formed <svg> document."""
    text = data.decode("utf-8", errors="replace").lstrip("﻿")
    text, removed = _DOCTYPE.subn("", text)
    try:
        root = ET.fromstring(text.encode("utf-8"))
    except ET.ParseError as exc:
        raise ValueError(f"not well-formed XML ({exc})") from exc
    if not isinstance(root.tag, str) or _local(root.tag) != "svg":
        raise ValueError("the root element isn't <svg>")

    def clean(el) -> None:
        nonlocal removed
        for child in list(el):
            if not isinstance(child.tag, str):
                continue
            name, target = _local(child.tag), _local(child.get("attributeName", ""))
            if name in _DROP or (name in _ANIMATION and (target in _LINKS or target.startswith("on"))):
                el.remove(child)
                removed += 1
                continue
            clean(child)
        for attr in list(el.attrib):
            name, value = _local(attr), el.attrib[attr]
            if (name.startswith("on") or (name in _LINKS and not _safe_link(value))
                    or (name in _ANIM_VALUES and _unsafe_value(value))
                    or (name == "style" and "javascript:" in _plain(value))):
                del el.attrib[attr]
                removed += 1
            elif name == "style" or "url(" in value.lower():
                css, changed = _clean_css(value)
                if changed:
                    el.attrib[attr] = css
                    removed += 1
        if _local(el.tag) == "style" and el.text:
            css, changed = _clean_css(el.text)
            if changed:
                el.text = css
                removed += 1

    clean(root)
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="unicode"), removed


def _svg_facts(svg: str) -> dict:
    facts: dict = {}
    root = re.search(r"<svg\b[^>]*>", svg, re.I | re.S)
    if root:
        for attr in ("viewBox", "width", "height"):
            m = re.search(r"\s%s\s*=\s*[\"']([^\"']*)[\"']" % attr, root.group(0))
            if m:
                facts[attr] = m.group(1)
    facts["paths"] = len(re.findall(r"<path\b", svg, re.I))
    colors = {c.lower() for c in re.findall(r"(?:fill|stroke|stop-color)\s*[:=]\s*[\"']?\s*(#[0-9a-fA-F]{3,8})", svg)}
    facts["colors"] = len(colors)
    return facts


# ---------------------------------------------------------------------------- saving and previews
def _write_new(folder: Path, base: str, content, ext: str) -> Path:
    """Write content to <folder>/<base>.<ext>, or <base>-2.<ext> ... when taken: a paid image never
    overwrites another."""
    for k in range(1, 1000):
        path = folder / (f"{base}.{ext}" if k == 1 else f"{base}-{k}.{ext}")
        try:
            if isinstance(content, str):
                with open(path, "x", encoding="utf-8") as f:
                    f.write(content)
            else:
                with open(path, "xb") as f:
                    f.write(content)
            return path
        except FileExistsError:
            continue
    raise RuntimeError(f"no free file name for {base} in {folder}")


def _out_folder(out_dir: str) -> Path:
    """The output folder, checked, created and writable before anything is paid for."""
    folder = Path(out_dir).expanduser() if out_dir else OUT_DIR
    _check_allowed_path(folder.absolute(), "out_dir")
    _check_allowed_path(folder.resolve(), "out_dir")
    try:
        folder.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ValueError(f"out_dir can't be created: {exc}") from exc
    if not os.access(folder, os.W_OK | os.X_OK):
        raise ValueError(f"out_dir isn't writable: {folder}")
    return folder


def _ledger(folder: Path, entry: dict) -> None:
    """Append a submitted Opper job to <folder>/.image-studio-jobs.jsonl, so it can be collected even
    if the call is cancelled or fails later. Best effort."""
    try:
        fd = os.open(folder / LEDGER, os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
        with os.fdopen(fd, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except OSError:
        pass


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40] or "image"


def _raster_preview(data: bytes, px: int = 768):
    """A small JPEG of a raster result for a look (never saved), or None without Pillow."""
    try:
        from PIL import Image as PILImage
        with PILImage.open(io.BytesIO(data)) as im:
            im = im.convert("RGB")
            im.thumbnail((px, px))
            buf = io.BytesIO()
            im.save(buf, "JPEG", quality=80)
            return buf.getvalue()
    except Exception:   # noqa: BLE001 - a preview is optional
        return None


def _rasterizer():
    # librsvg first; Quick Look on macOS otherwise. No ImageMagick: its SVG coders can read local files.
    for name in ("rsvg-convert", "qlmanage"):
        exe = shutil.which(name)
        if exe:
            return name, exe
    return None, None


def _preview(svg_path: Path, px: int = 768):
    """A PNG of the SVG at most px wide/high, rendered in a temp folder and never saved; or None."""
    name, exe = _rasterizer()
    if not exe:
        return None
    with tempfile.TemporaryDirectory(prefix="svg-preview-") as tmp:
        out = Path(tmp) / "preview.png"
        if name == "rsvg-convert":
            cmd = [exe, "-a", "-w", str(px), "-h", str(px), "-o", str(out), str(svg_path)]
        else:
            cmd = [exe, "-t", "-s", str(px), "-o", tmp, str(svg_path)]
        try:
            subprocess.run(cmd, capture_output=True, timeout=60, check=False)
        except (OSError, subprocess.SubprocessError):
            return None
        if name == "qlmanage":
            out = Path(tmp) / (svg_path.name + ".png")
        return out.read_bytes() if out.is_file() and out.stat().st_size else None


class Batch:
    """The images of one call: what was saved, what was refused and why, previews and notes."""

    def __init__(self, folder: Path, name: str, preview: bool):
        self.folder, self.base, self.preview = folder, f"{time.strftime('%Y%m%d-%H%M%S')}-{_slug(name)}", preview
        self.saved, self.refused, self.previews, self.notes, self.costs = [], [], [], [], []

    def refuse(self, i: int, reason: str, **extra) -> None:
        self.refused.append({"image": i, "reason": _redact(reason), **extra})

    def raster(self, i: int, data: bytes, extra: dict | None = None) -> bool:
        mime = _sniff(data)
        if mime not in RASTER_EXT:
            self.refuse(i, f"the model returned {mime}, not a PNG/JPEG/WebP image: nothing saved")
            return False
        if not _verifies(data):
            self.refuse(i, "the image data is corrupt: nothing saved")
            return False
        try:
            path = _write_new(self.folder, f"{self.base}-{i}", data, RASTER_EXT[mime])
        except (OSError, RuntimeError) as exc:
            self.refuse(i, f"the image couldn't be written ({exc})")
            return False
        rec = {"path": str(path), "bytes": len(data), "format": RASTER_EXT[mime]}
        size = _image_size(data)
        if size:
            rec["width"], rec["height"] = size
        rec.update(extra or {})
        self.saved.append(rec)
        if self.preview:
            jpg = _raster_preview(data)
            if jpg:
                self.previews.append(Image(data=jpg, format="jpeg"))
        return True

    def svg(self, i: int, data: bytes, extra: dict | None = None) -> bool:
        if not _is_svg(data):
            self.refuse(i, f"the model returned {_sniff(data)}, not SVG: nothing saved")
            return False
        try:
            svg, removed = _sanitize(data)
        except ValueError as exc:
            self.refuse(i, f"unusable SVG ({exc}): nothing saved")
            return False
        try:
            path = _write_new(self.folder, f"{self.base}-{i}", svg, "svg")
        except (OSError, RuntimeError) as exc:
            self.refuse(i, f"the SVG couldn't be written ({exc})")
            return False
        rec = {"path": str(path), "bytes": path.stat().st_size, **_svg_facts(svg), **(extra or {})}
        if removed:
            rec["sanitized"] = f"removed {removed} unsafe item(s): scripts, handlers, outside links or a DOCTYPE"
        self.saved.append(rec)
        if self.preview:
            png = _preview(path)
            if png:
                self.previews.append(Image(data=png, format="png"))
            else:
                self.notes.append("no preview: install librsvg (brew install librsvg) for rsvg-convert")
        return True

    def cost(self, value) -> None:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            self.costs.append(float(value))

    def result(self, **head):
        out = dict(head, images=self.saved)
        out["cost_usd"] = round(sum(self.costs), 6) if self.costs else None
        if self.refused:
            out["refused"] = self.refused
        if self.notes:
            out["notes"] = sorted({_redact(n) for n in self.notes})
        text = json.dumps(out)
        return [text, *self.previews] if self.previews else text


def _decode(b64: str) -> bytes:
    """Base64 image data, strictly: an optional data: URI prefix, standard or URL-safe alphabet."""
    s = b64.strip()
    if s[:5].lower() == "data:" and "," in s:
        s = s.split(",", 1)[1]
    s = re.sub(r"\s+", "", s)
    padded = s + "=" * (-len(s) % 4)
    for alt in (None, b"-_"):
        try:
            return base64.b64decode(padded, altchars=alt, validate=True)
        except (binascii.Error, ValueError):
            continue
    raise ValueError("unreadable base64 image data")


# ---------------------------------------------------------------------------- models and catalogs
class ModelError(ValueError):
    """The configured model can't do what the call asks: found before anything is paid for."""

    def __init__(self, message: str):
        super().__init__(_redact(message))


def _model(route: str) -> str:
    m = MODELS[route]
    value = (os.environ.get(m["env"]) or "").strip() or m["default"]
    if any(value == (os.environ.get(p["key"]) or "").strip() for p in PROVIDERS.values()):
        raise ModelError(f"{m['env']} holds an API key, not a model id: fix it in ~/.claude/stack.env")
    if not MODEL_ID.match(value) or ".." in value or "//" in value:
        raise ModelError(f"{m['env']} isn't a model id: {value[:80]!r} (fix it in ~/.claude/stack.env)")
    return value


def _label(model: str) -> str:
    return f"{NAMES[model]} ({model})" if model in NAMES else model


def _or_merge(endpoints: list) -> dict:
    """A model's capabilities from its OpenRouter endpoint records: the parameters it accepts (enum
    values and ranges joined across endpoints), the provider options each endpoint accepts, and the
    output price per variant ("" = the base price, "2k", "4k" ...)."""
    params: dict = {}
    options: dict = {}
    prices: dict = {}
    for ep in endpoints:
        if not isinstance(ep, dict):
            continue
        supported = ep.get("supported_parameters") if isinstance(ep.get("supported_parameters"), dict) else {}
        for key, d in supported.items():
            if not isinstance(d, dict):
                continue
            cur = params.get(key)
            if d.get("type") == "enum":
                values = [str(v) for v in d.get("values") or []]
                if cur and cur.get("type") == "enum":
                    cur["values"] += [v for v in values if v not in cur["values"]]
                else:
                    params[key] = {"type": "enum", "values": values}
            elif d.get("type") == "range":
                lo, hi = d.get("min"), d.get("max")
                if cur and cur.get("type") == "range":
                    los = [x for x in (cur.get("min"), lo) if isinstance(x, (int, float))]
                    his = [x for x in (cur.get("max"), hi) if isinstance(x, (int, float))]
                    cur["min"], cur["max"] = (min(los) if los else None), (max(his) if his else None)
                else:
                    params[key] = {"type": "range", "min": lo, "max": hi}
            else:
                params.setdefault(key, {"type": "boolean"})
        slug = ep.get("provider_slug")
        if isinstance(slug, str) and slug:
            options[slug] = [str(x) for x in ep.get("allowed_passthrough_parameters") or []]
        for line in ep.get("pricing") or []:
            if (isinstance(line, dict) and line.get("billable") == "output_image" and line.get("unit") == "image"
                    and isinstance(line.get("cost_usd"), (int, float))):
                variant, cost = str(line.get("variant") or "").lower(), float(line["cost_usd"])
                prices[variant] = min(prices.get(variant, cost), cost)
    return {"params": params, "options": options, "prices": prices}


def _or_known(model: str):
    if model not in OR_KNOWN:
        return None
    caps = _or_merge(OR_KNOWN[model])
    caps["source"] = "built-in"
    return caps


async def _or_caps(c: httpx.AsyncClient, route: str, model: str):
    """The model's capabilities from OpenRouter's public image-model catalog (read once a session); the
    stack's copy for a default model when the catalog can't be reached; else None (the request goes
    unchecked). A model the catalog doesn't know is refused before paying."""
    if ("openrouter", model) in _CATALOG:
        return _CATALOG["openrouter", model]
    url = f"{PROVIDERS['openrouter']['base']}/images/models/{quote(model, safe='/:@+')}/endpoints"
    try:
        r = await _public_get(c, "openrouter", url, timeout=POLL_TIMEOUT)
        body = r.json()
        endpoints = body.get("endpoints") if isinstance(body, dict) else None
        if not isinstance(endpoints, list):
            raise ValueError("no endpoint list in the catalog reply")
    except ApiError as exc:
        if exc.status == 404 and exc.json_error:     # OpenRouter's own "No image model found" reply
            raise ModelError(f"{MODELS[route]['env']}={model} isn't an OpenRouter image model: pick one at "
                             "https://openrouter.ai/models?output_modalities=image") from None
        _CATALOG_ERR["openrouter"] = str(exc)[:200]
        return _or_known(model)
    except Exception as exc:  # noqa: BLE001 - the catalog helps; an outage never blocks a known model
        _CATALOG_ERR["openrouter"] = _redact(str(exc))[:200] or type(exc).__name__
        return _or_known(model)
    if not endpoints:
        raise ModelError(f"{MODELS[route]['env']}={model}: no provider serves this model on OpenRouter right now; "
                         "pick another, or try again later")
    caps = _or_merge(endpoints)
    if not caps["params"]:                          # no parameter descriptors we can read: not a usable entry
        _CATALOG_ERR["openrouter"] = "the catalog entry lists no parameters in a known shape"
        return _or_known(model)
    caps["source"] = "catalog"
    _CATALOG["openrouter", model] = caps
    return caps


def _values(caps, key: str) -> list:
    d = ((caps or {}).get("params") or {}).get(key) or {}
    return [str(v) for v in d.get("values") or []] if d.get("type") == "enum" else []


def _pick(values: list, value: str, what: str, model: str) -> str:
    match = next((v for v in values if v.lower() == value.strip().lower()), None)
    if match is None:
        raise ModelError(f"{what} for {model} must be one of {', '.join(values)}")
    return match


def _or_param(caps, key: str, value: str, model: str):
    """What to send for one optional parameter (None = leave it out), checked against the catalog: an
    option the model lacks, or a value outside its list, is refused before paying."""
    if not value:
        return None
    if caps is None:
        return value
    d = caps["params"].get(key)
    if d is None:
        raise ModelError(f"{model} has no {key} option")
    if d.get("type") == "enum":
        return _pick(_values(caps, key), value, key, model)
    return value


def _or_range(caps, key: str, unknown: tuple) -> tuple:
    """(min, max) of a range parameter: `unknown` without a catalog; (1, 1) for an n the model lacks and
    (0, 0) for anything else it lacks."""
    if caps is None:
        return unknown
    d = caps["params"].get(key)
    if d is None:
        return (1, 1) if key == "n" else (0, 0)
    if d.get("type") != "range":
        return unknown
    lo, hi = d.get("min"), d.get("max")
    return (int(lo) if isinstance(lo, (int, float)) else unknown[0], int(hi) if isinstance(hi, (int, float)) else unknown[1])


def _or_price(caps, resolution: str = ""):
    prices = (caps or {}).get("prices") or {}
    return prices.get((resolution or "").lower(), prices.get(""))


def _svg_problem(caps, model: str):
    """Why this model can't be generate_svg's (None when it can, or when no catalog says)."""
    if caps is None:
        return None
    made = _values(caps, "output_format")
    if "svg" not in [v.lower() for v in made]:
        return (f"IMAGE_STUDIO_SVG_MODEL={model} can't make SVG ({', '.join(made) or 'no output format listed'}): "
                f"pick a vector model such as {MODELS['svg']['default']}")
    fewest = _or_range(caps, "input_references", (0, 10))[0]
    if fewest > 1:
        return (f"IMAGE_STUDIO_SVG_MODEL={model} needs {fewest} reference images on every call, and generate_svg "
                f"sends at most one: pick a vector model such as {MODELS['svg']['default']}")
    return None


def _edit_problem(caps, model: str):
    """Why this model can't be edit_image's: it takes no input images, or makes no raster image."""
    if caps is None:
        return None
    if _or_range(caps, "input_references", (0, 16))[1] < 1:
        return (f"IMAGE_STUDIO_EDIT_MODEL={model} takes no input images: pick a model that edits, such as "
                f"{MODELS['edit']['default']}")
    made = [v.lower() for v in _values(caps, "output_format")]
    if made and not set(made) & {"png", "jpeg", "jpg", "webp"}:
        return (f"IMAGE_STUDIO_EDIT_MODEL={model} makes only {', '.join(made)}, and edit_image saves PNG, JPEG or "
                f"WebP: pick a raster model such as {MODELS['edit']['default']} (vector work: generate_svg)")
    return None


def _palette_options(caps, model: str, colors_rgb: list, bg_rgb) -> dict:
    """provider.options carrying the palette in Recraft's "controls" shape, for each endpoint that takes
    it; {} when none does (the palette then goes into the prompt)."""
    controls: dict = {}
    if colors_rgb:
        controls["colors"] = [{"rgb": col} for col in colors_rgb]
    if bg_rgb:
        controls["background_color"] = {"rgb": bg_rgb}
    if not controls:
        return {}
    if caps is None:
        return {"recraft": {"controls": controls}} if model.startswith("recraft/") else {}
    return {slug: {"controls": controls} for slug, allowed in caps["options"].items() if "controls" in allowed}


def _palette_words(prompt: str, colors: list | None, background_color: str) -> str:
    words = []
    if colors:
        words.append("color palette " + ", ".join(col if col.startswith("#") else "#" + col for col in colors))
    if background_color:
        words.append("background color " + (background_color if background_color.startswith("#") else "#" + background_color))
    return prompt.rstrip(". ") + ". Use " + "; ".join(words) + "."


async def _or_post(c: httpx.AsyncClient, body: dict) -> dict:
    r = await _authed(c, "openrouter", "POST", PROVIDERS["openrouter"]["base"] + "/images", json=body)
    try:
        res = r.json()
    except ValueError:
        raise RuntimeError("OpenRouter's reply isn't JSON: " + r.text[:200]) from None
    return res if isinstance(res, dict) else {}


def _configured(route: str) -> str:
    return (os.environ.get(MODELS[route]["env"]) or "").strip() or MODELS[route]["default"]


def _svg_description() -> str:
    model = _configured("svg")
    known = model == MODELS["svg"]["default"]
    return (f"Generate vector images with {_label(model)} through OpenRouter and save them as SVG files; returns "
            "paths, viewBox, path and color counts, and cost. The tool for logos, icons, illustrations, stickers, "
            "patterns, posters and other graphic design: output is always SVG. Photographs and other raster "
            "images: generate_image; changes to existing images: edit_image. "
            + ("n: 1-6 a call, about $0.30 each. aspect_ratio: 1:1, 4:3, 3:4, 16:9, 9:16 or auto (empty = the "
               "model's default). reference_image: one local PNG/JPEG/WebP or https URL to redraw as vector art. "
               if known else
               "n, aspect_ratio and reference_image are checked against the model's entry in OpenRouter's "
               "catalog before paying. ")
            + "colors: palette as hex ('#1A73E8'); background_color: hex. out_dir: absolute folder (default "
            "~/Pictures/image-studio). preview=true also returns a PNG render of each file (not saved). The model "
            "is set by IMAGE_STUDIO_SVG_MODEL in stack.env.")


def _image_description() -> str:
    model = _configured("image")
    gpt = model in OPPER_KNOWN
    return (f"Generate 1-4 photographs or other raster images with {_label(model)} through Opper and save them; "
            "returns paths, sizes and cost. Logos, icons, illustrations and graphic design are SVG: generate_svg. "
            "Changing or combining existing images: edit_image. "
            + ("quality (per 1024x1024 image): low ~$0.006 (drafts), medium ~$0.013, high ~$0.053 (default), "
               "xhigh ~$0.094, max ~$0.21 (finals; slowest), auto. aspect_ratio: W:H such as 1:1, 3:2, 16:9, "
               "21:9 (up to 3:1) or auto; resolution: 1K (short side 1024: 1024x1024, 1536x1024), 2K (1440: "
               "2560x1440), 4K (2160: 3840x2160; about twice the cost); or an exact size 'WxH' (multiples of 16, "
               "sides up to 3840). " if gpt else
               "aspect_ratio (W:H), resolution (1K/2K/4K), size ('WxH') and quality are matched to the model's "
               "entry in Opper's catalog and checked before paying. ")
            + "output_format png/jpeg/webp; background auto/opaque/transparent (png or webp). reference_images: up "
            "to 8 local PNG/JPEG/WebP paths or https URLs as style or subject references (sent under 1920 px). "
            "out_dir: absolute folder (default ~/Pictures/image-studio). preview=true returns a small JPEG of "
            "each image. Images not saved in time come back in 'pending': collect_image(job) saves them later. "
            "The model is set by IMAGE_STUDIO_IMAGE_MODEL in stack.env.")


def _edit_description() -> str:
    model = _configured("edit")
    known = model == MODELS["edit"]["default"]
    return (f"Edit or combine raster images with {_label(model)} through OpenRouter and save the result; returns "
            "path, size and cost. images: local PNG/JPEG/WebP paths or https URLs (local ones go out under 1920 px)"
            + ("; 1-10 of them; $0.13 at 1K, $0.15 at 2K, $0.17 at 4K. " if known else
               "; how many the model takes is checked before paying. ")
            + "prompt: the change, and what must stay as it is ('replace the sky with dusk; keep the building, "
            "people and framing unchanged'). Retouching, background swaps, object edits, relighting, style "
            "transfer, composites, product shots, a design placed on a mockup. "
            + ("aspect_ratio (empty = keep the framing): 1:1 4:3 3:4 3:2 2:3 16:9 9:16 21:9 auto; resolution "
               "1K/2K/4K; output_format png/jpeg/webp; background auto/transparent/opaque. " if known else
               "aspect_ratio, resolution, output_format and background are checked against the model's entry in "
               "OpenRouter's catalog. ")
            + "out_dir: absolute folder (default ~/Pictures/image-studio). preview=true returns a small JPEG. The "
            "model is set by IMAGE_STUDIO_EDIT_MODEL in stack.env.")


# ---------------------------------------------------------------------------- generate_svg (OpenRouter)
@mcp.tool(description=_svg_description())
async def generate_svg(prompt: str, aspect_ratio: str = "", n: int = 1, colors: list[str] | None = None,
                       background_color: str = "", reference_image: str = "", name: str = "",
                       out_dir: str = "", preview: bool = False):
    if not prompt or not prompt.strip():
        raise ValueError("prompt is empty")
    if not isinstance(n, int) or isinstance(n, bool) or not 1 <= n <= 10:
        raise ValueError("n must be 1-10")
    colors_rgb = [_rgb(col, "colors") for col in colors or []]
    bg_rgb = _rgb(background_color, "background_color") if background_color else None
    model = _model("svg")
    folder = _out_folder(out_dir)
    _key("openrouter")
    refs = _references([reference_image], "reference_image", BUDGET["openrouter"]) if reference_image else []
    batch = Batch(folder, name or prompt, preview)
    async with _client() as c:
        caps = await _or_caps(c, "svg", model)
        problem = _svg_problem(caps, model)
        if problem:
            raise ModelError(problem)
        lo, hi = _or_range(caps, "n", (1, 10))
        if not lo <= n <= hi:
            raise ModelError(f"n for {model} must be {lo}-{hi}" if hi > lo else f"{model} makes {hi} image a call")
        body: dict = {"model": model, "prompt": prompt.strip()}
        if n > 1 or caps is None or "n" in caps["params"]:
            body["n"] = n
        aspect = _or_param(caps, "aspect_ratio", aspect_ratio, model)
        if aspect:
            body["aspect_ratio"] = aspect
        body["output_format"] = "svg"
        if len(refs) < _or_range(caps, "input_references", (0, 10))[0]:
            raise ModelError(f"{model} needs a reference image on every call: pass reference_image")
        if refs:
            if _or_range(caps, "input_references", (0, 10))[1] < 1:
                raise ModelError(f"{model} takes no reference image")
            body["input_references"] = [{"type": "image_url", "image_url": {"url": u}} for u in refs]
        options = _palette_options(caps, model, colors_rgb, bg_rgb)
        if options:
            body["provider"] = {"options": options}
        elif colors_rgb or bg_rgb:
            body["prompt"] = _palette_words(body["prompt"], colors, background_color)
            batch.notes.append(f"{model} takes no palette option, so the palette went into the prompt")
        if caps is None:
            batch.notes.append("OpenRouter's model catalog couldn't be read: the request went out unchecked")
        try:
            res = await _or_post(c, body)
        except ApiError as exc:
            if "provider" not in body or exc.status != 400 or not exc.about("controls", "colors", "background_color"):
                raise
            body.pop("provider")
            body["prompt"] = _palette_words(body["prompt"], colors, background_color)
            batch.notes.append("OpenRouter refused the palette option, so the palette went into the prompt: "
                               + str(exc)[:200])
            res = await _or_post(c, body)
    items = res.get("data") if isinstance(res.get("data"), list) else []
    for i, it in enumerate(items, 1):
        if not isinstance(it, dict) or not it.get("b64_json"):
            batch.refuse(i, "no b64_json in the response: nothing saved")
            continue
        try:
            data = _decode(it["b64_json"])
        except ValueError as exc:
            batch.refuse(i, f"{exc}: nothing saved")
            continue
        mime = str(it.get("media_type") or "").lower()
        if mime and not mime.startswith("image/svg+xml"):
            batch.refuse(i, f"the model returned {mime}, not SVG: nothing saved")
            continue
        batch.svg(i, data)
    batch.cost((res.get("usage") or {}).get("cost") if isinstance(res.get("usage"), dict) else None)
    if not batch.saved and not batch.refused:
        batch.notes.append("OpenRouter returned no images (nothing billed for a failed generation)")
    price = _or_price(caps)
    return batch.result(model=model, provider="openrouter", format="svg",
                        estimated_cost_usd=round(price * n, 2) if price else None)


# ---------------------------------------------------------------------------- generate_image (Opper)
def _ratio(aspect_ratio: str) -> tuple:
    m = re.fullmatch(r"\s*(\d{1,2})\s*:\s*(\d{1,2})\s*", aspect_ratio or "")
    if not m or not int(m.group(1)) or not int(m.group(2)):
        raise ValueError("aspect_ratio must be W:H, such as 16:9, or auto")
    return int(m.group(1)), int(m.group(2))


def _num(cons: dict, key: str, default: float) -> float:
    v = cons.get(key)
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else default


def _fits(w: int, h: int, cons: dict) -> bool:
    mult = int(_num(cons, "multiple_of", 1)) or 1
    return (min(w, h) >= max(mult, _num(cons, "min_edge", 1)) and w % mult == 0 and h % mult == 0
            and max(w, h) <= _num(cons, "max_edge", 1e9) and max(w, h) / min(w, h) <= _num(cons, "max_ratio", 1e9)
            and _num(cons, "min_pixels", 0) <= w * h <= _num(cons, "max_pixels", 1e15))


def _constrained(a: int, b: int, short: int, cons: dict, model: str) -> str:
    """The aspect ratio at the tier's short side, shrunk (or grown) into the model's size constraints,
    in multiples of its step."""
    mult = int(_num(cons, "multiple_of", 16)) or 16
    if max(a, b) / min(a, b) > _num(cons, "max_ratio", 1e9):
        raise ModelError(f"aspect_ratio {a}:{b} is beyond {model}'s {_num(cons, 'max_ratio', 0):g}:1 limit")
    w, h = (short * a / b, short) if a >= b else (short, short * b / a)
    scale = min(1.0, _num(cons, "max_edge", 1e9) / max(w, h), (_num(cons, "max_pixels", 1e15) / (w * h)) ** 0.5)
    w, h = w * scale, h * scale
    if w * h < _num(cons, "min_pixels", 0):
        grow = (_num(cons, "min_pixels", 0) / (w * h)) ** 0.5
        w, h = w * grow, h * grow
    w, h = (max(mult, int(round(x / mult)) * mult) for x in (w, h))
    for _ in range(4096):
        if _fits(w, h, cons):
            return f"{w}x{h}"
        too_big = w * h > _num(cons, "max_pixels", 1e15) or max(w, h) > _num(cons, "max_edge", 1e9)
        if (w >= h) == too_big:
            w += -mult if too_big else mult
        else:
            h += -mult if too_big else mult
        if min(w, h) < mult:
            break
    raise ModelError(f"no size for aspect_ratio {a}:{b} fits {model}'s size limits")


def _pixel_size(model: str, aspect_ratio: str, resolution: str, size: str, cons, sizes: list) -> str:
    """The pixel size for a pixel-sized model: `size` as given (checked), or aspect_ratio at the tier's
    short side (1K 1024, 2K 1440, 4K 2160) within the model's constraints, or the listed size closest
    in shape and scale."""
    listed = [s for s in sizes if s != "auto"]
    if size:
        s = size.strip().lower()
        if s == "auto":
            if "auto" in sizes:
                return "auto"
            raise ModelError(f"{model} has no automatic size")
        m = re.fullmatch(r"(\d{2,5})x(\d{2,5})", s)
        if not m:
            raise ValueError("size must be 'WxH' (such as 1536x1024) or 'auto'")
        w, h = int(m.group(1)), int(m.group(2))
        if cons:
            if not _fits(w, h, cons):
                raise ModelError(f"size must use multiples of {int(_num(cons, 'multiple_of', 1))}, sides up to "
                                 f"{_num(cons, 'max_edge', 0):g}, a ratio up to {_num(cons, 'max_ratio', 0):g}:1 and "
                                 f"{_num(cons, 'min_pixels', 0):g}-{_num(cons, 'max_pixels', 0):g} pixels for {model} "
                                 "(1024x1024, 1536x1024, 2560x1440, 3840x2160 ...)")
        elif s not in listed:
            raise ModelError(f"size for {model} must be one of {', '.join(sizes)}")
        return f"{w}x{h}"
    if aspect_ratio.strip().lower() == "auto":
        if "auto" in sizes:
            return "auto"
        raise ModelError(f"{model} has no automatic size")
    a, b = _ratio(aspect_ratio or "1:1")
    tier = (resolution or "1K").strip().upper()
    if tier not in TIERS:
        raise ValueError(f"resolution must be one of {', '.join(TIERS)}")
    if cons:
        return _constrained(a, b, TIERS[tier], cons, model)
    target, area = math.log(a / b), TIERS[tier] ** 2 * max(a / b, b / a)

    def distance(s: str) -> tuple:
        w, h = (int(x) for x in s.split("x"))
        return (round(abs(math.log(w / h) - target), 3), abs(w * h - area))
    return min(listed, key=distance)


def _gpt_size(aspect_ratio: str, resolution: str, size: str) -> str:
    """The pixel size GPT Image 2.5 would get (see _pixel_size)."""
    img = GPT_IMAGE["image"]
    return _pixel_size(MODELS["image"]["default"], aspect_ratio, resolution, size, img["size_constraints"], img["sizes"])


def _opper_known(model: str):
    known = OPPER_KNOWN.get(model)
    if not known:
        return None
    return {"source": "built-in", "capabilities": list(known["capabilities"]), "image": known["image"],
            "prices": known["prices"], "quality": known["quality"], "price": None}


def _image_problem(caps, model: str, references: bool = False):
    """Why this model can't be generate_image's: the catalog lists it as editing only (then it works
    only with reference images)."""
    if caps is None or not caps["capabilities"] or "image_generation" in caps["capabilities"] or references:
        return None
    return (f"IMAGE_STUDIO_IMAGE_MODEL={model} only edits images ({', '.join(caps['capabilities'])}): give it "
            f"reference_images, or pick a model that generates, such as {MODELS['image']['default']}")


async def _opper_caps(c: httpx.AsyncClient, model: str):
    """The model's entry in Opper's public image-model catalog (read once a session); the stack's copy for
    GPT Image 2.5 when the catalog can't be reached; else None (the request goes unchecked). A model the
    catalog doesn't list is refused before paying."""
    if ("opper", model) in _CATALOG:
        return _CATALOG["opper", model]
    url = PROVIDERS["opper"]["base"] + "/v3/images/models"
    entry = None
    try:
        for params in ({"q": model, "limit": 100}, {"limit": 500}):
            r = await _public_get(c, "opper", url, params=params, timeout=POLL_TIMEOUT)
            body = r.json()
            entries = body.get("models") if isinstance(body, dict) else None
            if not isinstance(entries, list):
                raise ValueError("no models in the catalog reply")
            entry = next((e for e in entries if isinstance(e, dict) and e.get("id") == model), None)
            if entry is not None:
                break
    except Exception as exc:  # noqa: BLE001 - the catalog helps; an outage never blocks a known model
        _CATALOG_ERR["opper"] = _redact(str(exc))[:200] or type(exc).__name__
        return _opper_known(model)
    if entry is None:
        raise ModelError(f"IMAGE_STUDIO_IMAGE_MODEL={model} isn't an Opper image model: pick one from "
                         "https://api.opper.ai/v3/images/models")
    known = OPPER_KNOWN.get(model, {})
    params = entry.get("params") if isinstance(entry.get("params"), dict) else {}
    pricing = entry.get("pricing") if isinstance(entry.get("pricing"), dict) else {}
    per_image = pricing.get("price_per_generation")
    caps = {"source": "catalog", "capabilities": [str(x) for x in entry.get("capabilities") or []],
            "image": params.get("image") if isinstance(params.get("image"), dict) else {},
            "prices": known.get("prices", {}), "quality": known.get("quality", ""),
            "price": per_image if isinstance(per_image, (int, float)) and not isinstance(per_image, bool) else None}
    _CATALOG["opper", model] = caps
    return caps


def _opper_fields(model: str, caps, aspect_ratio: str, resolution: str, size: str, quality: str) -> dict:
    """size, or aspect_ratio + resolution, and quality: whichever the model takes, checked against its
    catalog entry; without one, sent as asked."""
    out: dict = {}
    if caps is None:
        for key, value in (("size", size), ("aspect_ratio", aspect_ratio), ("resolution", resolution),
                           ("quality", quality)):
            if value:
                out[key] = value.strip()
        return out
    img = caps["image"]
    cons = img.get("size_constraints") if isinstance(img.get("size_constraints"), dict) else None
    sizes = [str(s) for s in img.get("sizes") or []]
    ratios = [str(s) for s in img.get("aspect_ratios") or []]
    tiers = [str(s) for s in img.get("resolutions") or []]
    if cons or [s for s in sizes if s != "auto"]:
        out["size"] = _pixel_size(model, aspect_ratio, resolution, size, cons, sizes)
    else:
        if size:
            raise ModelError(f"{model} takes aspect ratios, not pixel sizes: use aspect_ratio" if ratios
                             else f"{model} has no size option")
        if aspect_ratio:
            if not ratios:
                raise ModelError(f"{model} has no aspect_ratio option")
            out["aspect_ratio"] = _pick(ratios, aspect_ratio, "aspect_ratio", model)
        if resolution:
            if not tiers:
                raise ModelError(f"{model} has no resolution option")
            out["resolution"] = _pick(tiers, resolution, "resolution", model)
    qualities = [str(q) for q in img.get("qualities") or []]
    wanted = quality.strip() or caps.get("quality") or ""
    if quality and not qualities:
        raise ModelError(f"{model} has no quality option")
    if wanted and qualities:
        out["quality"] = _pick(qualities, wanted, "quality", model)
    return out


def _opper_params(model: str, caps, fmt: str, background: str) -> dict:
    """output_format and background for `parameters`, when asked for and the model lists them."""
    out: dict = {}
    listed = None
    if caps is not None:
        listed = {p.get("name"): p for p in caps["image"].get("parameters") or [] if isinstance(p, dict)}
    if background == "transparent" and not fmt and listed and "output_format" in listed:
        made = [str(v).lower() for v in listed["output_format"].get("enum") or []]
        if made and not {"png", "webp"} & set(made):
            raise ModelError(f"{model} makes only {', '.join(made)}: a transparent background needs PNG or WebP")
    for key, value in (("output_format", fmt), ("background", background)):
        if not value:
            continue
        if listed is not None:
            if key not in listed:
                raise ModelError(f"{model} has no {key} option")
            enum = listed[key].get("enum")
            if isinstance(enum, list) and enum:
                value = _pick([str(v) for v in enum], value, key, model)
        out[key] = value
    return out


def _opper_estimate(caps, fields: dict, n: int):
    if not caps:
        return None
    prices = caps.get("prices") or {}
    quality = fields.get("quality")
    if prices and quality in prices:
        m = re.fullmatch(r"(\d+)x(\d+)", fields.get("size", ""))
        big = bool(m) and int(m.group(1)) * int(m.group(2)) > 6_000_000
        return round(prices[quality] * (1.9 if big else 1.0) * n, 3)
    price = caps.get("price")
    return round(price * n, 3) if isinstance(price, (int, float)) else None


def _status_url(job: str) -> str:
    base = PROVIDERS["opper"]["base"]
    job = job.strip()
    if job.startswith("/"):
        job = urljoin(base + "/", job)
    if re.match(r"^https?://", job, re.I):
        if _origin(job) != _origin(base):
            raise ValueError("a status_url must be on OPPER_BASE_URL's host: the key goes nowhere else")
        return job
    if not JOB_ID.match(job) or ".." in job:
        raise ValueError("job must be an Opper job id (letters, digits and _ . : -, up to 128 characters) "
                         "or its status_url")
    return f"{base}/v3/artifacts/{quote(job, safe='')}/status"


def _state(r: httpx.Response, st: dict) -> str:
    """'done', 'failed' or the job's current state."""
    status = str(st.get("status") or ("processing" if r.status_code == 202 else "")).lower()
    if status in DONE or (not status and (st.get("url") or st.get("b64_json") or st.get("data"))):
        return "done"
    if status in FAILED:
        return "failed"
    return status or "unknown"


async def _opper_post(c: httpx.AsyncClient, body: dict, notes: list) -> httpx.Response:
    """POST /v3/images; a 400 whose error fields name store or async gets one retry without that key."""
    url = PROVIDERS["opper"]["base"] + "/v3/images"
    for _ in range(3):
        try:
            return await _authed(c, "opper", "POST", url, json=body)
        except ApiError as exc:
            if exc.status != 400:
                raise
            if "store" in body and exc.about("store"):
                body.pop("store")
                notes.append("Opper refused store=false: these images are also kept in your Opper Files")
            elif body.get("async") and exc.about("async"):
                body.pop("async")
                notes.append("Opper refused async for this model: each image was waited for inline")
            else:
                raise
    raise RuntimeError("Opper kept refusing the request")


async def _opper_done(c: httpx.AsyncClient, batch: Batch, i: int, st: dict, job: str | None) -> str | None:
    """Save one finished Opper result (a status payload or an inline data item). Returns why it
    couldn't be fetched when the job can be collected again later, else None."""
    item = st
    if isinstance(st.get("data"), list) and st["data"] and isinstance(st["data"][0], dict):
        item = st["data"][0]
    batch.cost((st.get("usage") or {}).get("cost", st.get("cost")))
    extra = {"revised_prompt": item["revised_prompt"]} if item.get("revised_prompt") else {}
    if job:
        extra["job"] = job
    if item.get("b64_json"):
        try:
            data = _decode(item["b64_json"])
        except ValueError as exc:
            batch.refuse(i, f"{exc}: nothing saved", **({"job": job} if job else {}))
            return None
    elif item.get("url"):
        try:
            data = await _download(c, "opper", item["url"])
        except Exception as exc:  # noqa: BLE001 - the job stays collectable
            return f"the download failed ({_redact(str(exc))[:200]})"
        if _sniff(data) not in RASTER_EXT and not _is_svg(data):
            return f"the download wasn't an image ({_sniff(data)})"
    else:
        return "the reply has no image or URL yet"
    if _sniff(data) not in RASTER_EXT and _is_svg(data):     # a vector model: keep what was paid for
        batch.notes.append("the model returned SVG: saved as a sanitized .svg")
        saved = batch.svg(i, data, extra or None)
    else:
        saved = batch.raster(i, data, extra or None)
    if not saved and job:
        batch.refused[-1]["job"] = job
    return None


async def _opper_wait(c: httpx.AsyncClient, batch: Batch, jobs: list) -> list:
    """Poll the jobs [(index, id, status_url)] until each is saved or failed, or the time is up.
    Returns the ones to collect later: still running, or finished but not fetched yet."""
    pending, parked, errors, last = list(jobs), [], {}, {}
    deadline, k = _now() + TIMEOUT, 0
    while pending and _now() < deadline:
        await _sleep(POLL[min(k, len(POLL) - 1)])
        k += 1
        for job in list(pending):
            i, job_id, url = job
            try:
                r = await _authed(c, "opper", "GET", url, timeout=POLL_TIMEOUT)
                st = r.json() if r.content else {}
                if not isinstance(st, dict):
                    raise ValueError("the status reply isn't a JSON object")
            except Exception as exc:  # noqa: BLE001 - a failed check never drops a paid job
                errors[job_id] = errors.get(job_id, 0) + 1
                last[job_id] = f"status check failed: {str(exc)[:200]}"
                if errors[job_id] >= MAX_POLL_ERRORS:
                    pending.remove(job)
                    parked.append(job)
                continue
            errors[job_id] = 0
            state = _state(r, st)
            if state == "done":
                pending.remove(job)
                problem = await _opper_done(c, batch, i, st, job_id)
                if problem:
                    last[job_id] = "completed, but " + problem
                    parked.append(job)
            elif state == "failed":
                pending.remove(job)
                batch.cost((st.get("usage") or {}).get("cost", st.get("cost")))
                batch.refuse(i, f"the job {st.get('status')}: {str(st.get('error') or 'no reason given')[:300]}", job=job_id)
            else:
                last[job_id] = state
    return [{"image": i, "job": job_id, "status_url": url, "status": last.get(job_id, "submitted")}
            for i, job_id, url in pending + parked]


@mcp.tool(description=_image_description())
async def generate_image(prompt: str, aspect_ratio: str = "", resolution: str = "", quality: str = "",
                         n: int = 1, output_format: str = "", background: str = "",
                         reference_images: list[str] | None = None, size: str = "", name: str = "",
                         out_dir: str = "", preview: bool = False):
    if not prompt or not prompt.strip():
        raise ValueError("prompt is empty")
    if not isinstance(n, int) or isinstance(n, bool) or not 1 <= n <= MAX_OPPER_N:
        raise ValueError(f"n must be 1-{MAX_OPPER_N}")
    fmt = (output_format or "").strip().lower().replace("jpg", "jpeg")
    if fmt and fmt not in FORMATS:
        raise ValueError(f"output_format must be one of {', '.join(FORMATS)}")
    if background and background not in BACKGROUNDS:
        raise ValueError(f"background must be one of {', '.join(BACKGROUNDS)}")
    if background == "transparent" and fmt == "jpeg":
        raise ValueError("a transparent background needs output_format png or webp")
    refs = list(reference_images or [])
    if len(refs) > MAX_OPPER_REFS:
        raise ValueError(f"reference_images takes at most {MAX_OPPER_REFS} images")
    model = _model("image")
    folder = _out_folder(out_dir)
    _key("opper")
    urls = _references(refs, "reference image", BUDGET["opper"]) if refs else []
    batch = Batch(folder, name or prompt, preview)
    jobs, pending = [], []
    async with _client() as c:
        caps = await _opper_caps(c, model)
        fields = _opper_fields(model, caps, aspect_ratio, resolution, size, quality)
        params = _opper_params(model, caps, fmt, background)
        if urls and caps is not None and "image_edit" not in caps["capabilities"]:
            raise ModelError(f"{model} takes no reference images")
        problem = _image_problem(caps, model, bool(urls))
        if problem:
            raise ModelError(problem)
        if caps is None:
            batch.notes.append("Opper's model catalog couldn't be read: the request went out unchecked")
        body: dict = {"model": model, "prompt": prompt.strip(), **fields, "async": True, "store": False}
        if params:
            body["parameters"] = params
        if urls:
            body["reference_images"] = urls
        for i in range(1, n + 1):          # one job per image: Opper's async runs are single-image
            try:
                r = await _opper_post(c, body, batch.notes)
            except Exception as exc:
                if not (jobs or batch.saved or batch.refused):
                    raise                   # nothing was accepted, so nothing was paid
                batch.notes.append(f"stopped before image {i} of {n}: {str(exc)[:300]}")
                break
            try:
                res = r.json() if r.content else {}
            except ValueError:
                res = {"unreadable_reply": r.text[:300]}
            res = res if isinstance(res, dict) else {"unexpected_reply": str(res)[:300]}
            if r.status_code == 202:
                job_id, url = str(res.get("id") or ""), None
                for cand in (res.get("status_url"), job_id):     # a foreign status_url: rebuild it
                    try:
                        url = _status_url(str(cand)) if cand else None
                    except ValueError:
                        url = None
                    if url:
                        break
                if not url:
                    batch.refuse(i, "Opper accepted the job, but its reply has no usable job id or status_url "
                                    f"({str(res)[:200]}): look for it at https://platform.opper.ai")
                    continue
                jobs.append((i, job_id or url, url))
                _ledger(folder, {"time": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "job": job_id or url,
                                 "status_url": url, "model": model, "name": name, "prompt": prompt.strip()[:200]})
            else:
                usage = res.get("usage")
                for it in [x for x in res.get("data") or [] if isinstance(x, dict)]:
                    problem = await _opper_done(c, batch, i, {"data": [it], "usage": usage}, None)
                    usage = None            # the call's cost counts once
                    if problem:
                        batch.refuse(i, problem + ": nothing saved")
        if jobs:
            pending = await _opper_wait(c, batch, jobs)
    if pending:
        batch.notes.append("not saved yet (still rendering, or not fetched in time): collect_image with the job "
                           f"id saves it; the job ids are also in {folder / LEDGER}")
    if not batch.saved and not batch.refused and not pending:
        batch.notes.append("Opper returned no images")
    head: dict = {"model": model, "provider": "opper"}
    head.update({k: fields[k] for k in ("size", "aspect_ratio", "resolution", "quality") if k in fields})
    estimate = _opper_estimate(caps, fields, n)
    if estimate is not None:
        head["estimated_cost_usd"] = estimate
    if pending:
        head["pending"] = pending
    return batch.result(**head)


@mcp.tool()
async def collect_image(job: str, name: str = "", out_dir: str = "", preview: bool = False):
    """Save an Opper image that generate_image didn't save in time (a job id from its 'pending' list or
    from .image-studio-jobs.jsonl in the output folder, or the status_url): saves it when done, else
    reports its status. cost_usd is that job's cost, already billed when it ran."""
    url = _status_url(job)
    folder = _out_folder(out_dir)
    batch = Batch(folder, name or "collected", preview)
    async with _client() as c:
        r = await _authed(c, "opper", "GET", url, timeout=POLL_TIMEOUT)
        try:
            st = r.json() if r.content else {}
        except ValueError:
            st = {}
        st = st if isinstance(st, dict) else {}
        model = str(st.get("model") or _configured("image"))
        state = _state(r, st)
        if state == "done":
            problem = await _opper_done(c, batch, 1, st, job.strip())
            if problem:
                return json.dumps({"model": model, "job": job.strip(), "status": "completed", "images": [],
                                   "notes": [problem + ": try again in a minute"]})
        elif state == "failed":
            batch.refuse(1, f"the job {st.get('status')}: {str(st.get('error') or 'no reason given')[:300]}")
        else:
            return json.dumps({"model": model, "job": job.strip(), "status": state, "images": [],
                               "notes": ["not done yet: try again in a minute"]})
    return batch.result(model=model, provider="opper", job=job.strip())


# ---------------------------------------------------------------------------- edit_image (OpenRouter)
@mcp.tool(description=_edit_description())
async def edit_image(images: list[str], prompt: str, aspect_ratio: str = "", resolution: str = "",
                     output_format: str = "", background: str = "", name: str = "", out_dir: str = "",
                     preview: bool = False):
    if not isinstance(images, list) or not 1 <= len(images) <= 16:
        raise ValueError("images must list 1-16 local paths or https URLs")
    if not prompt or not prompt.strip():
        raise ValueError("prompt is empty")
    fmt = (output_format or "").strip().lower().replace("jpg", "jpeg")
    if fmt and fmt not in FORMATS:
        raise ValueError(f"output_format must be one of {', '.join(FORMATS)}")
    if background and background not in BACKGROUNDS:
        raise ValueError(f"background must be one of {', '.join(BACKGROUNDS)}")
    if background == "transparent" and fmt == "jpeg":
        raise ValueError("a transparent background needs output_format png or webp")
    model = _model("edit")
    folder = _out_folder(out_dir)
    _key("openrouter")
    urls = _references(images, "an image", BUDGET["openrouter"])
    batch = Batch(folder, name or ("edit " + prompt), preview)
    async with _client() as c:
        caps = await _or_caps(c, "edit", model)
        problem = _edit_problem(caps, model)
        if problem:
            raise ModelError(problem)
        fewest, most = _or_range(caps, "input_references", (0, 16))
        if len(images) > most:
            raise ModelError(f"{model} takes at most {most} input image(s)")
        if len(images) < fewest:
            raise ModelError(f"{model} needs at least {fewest} input images")
        body: dict = {"model": model, "prompt": prompt.strip()}
        if caps is None or "n" in caps["params"]:
            body["n"] = 1
        aspect = aspect_ratio or ("auto" if "auto" in _values(caps, "aspect_ratio") else "")
        made = [v.lower() for v in _values(caps, "output_format")]
        if not fmt and background == "transparent" and made:
            fmt = next((f for f in ("png", "webp") if f in made), "")
            if not fmt:
                raise ModelError(f"{model} makes only {', '.join(made)}: a transparent background needs PNG or WebP")
        if not fmt and "svg" in made:           # a model that can also make SVG: ask for a raster edit_image can save
            fmt = next((f for f in ("png", "webp", "jpeg") if f in made), "")
        for key, value in (("aspect_ratio", aspect), ("resolution", resolution), ("output_format", fmt),
                           ("background", background)):
            chosen = _or_param(caps, key, value, model)
            if chosen:
                body[key] = chosen
        body["input_references"] = [{"type": "image_url", "image_url": {"url": u}} for u in urls]
        if caps is None:
            batch.notes.append("OpenRouter's model catalog couldn't be read: the request went out unchecked")
        res = await _or_post(c, body)
    items = res.get("data") if isinstance(res.get("data"), list) else []
    for i, it in enumerate(items, 1):
        if not isinstance(it, dict) or not it.get("b64_json"):
            batch.refuse(i, "no b64_json in the response: nothing saved")
            continue
        try:
            batch.raster(i, _decode(it["b64_json"]))
        except ValueError as exc:
            batch.refuse(i, f"{exc}: nothing saved")
    batch.cost((res.get("usage") or {}).get("cost") if isinstance(res.get("usage"), dict) else None)
    if not batch.saved and not batch.refused:
        batch.notes.append("OpenRouter returned no images (nothing billed for a failed generation)")
    return batch.result(model=model, provider="openrouter", estimated_cost_usd=_or_price(caps, body.get("resolution", "")))


# ---------------------------------------------------------------------------- --check (bin/doctor.sh)
RETIRED_ENV = {"LUMENFALL_API_KEY": "generate_svg runs on OpenRouter, with OPENROUTER_API_KEY",
               "OPPER_IMAGE_MODEL": "generate_image's model is IMAGE_STUDIO_IMAGE_MODEL",
               "OPPER_IMAGE_OUT_DIR": "the output folder is IMAGE_STUDIO_OUT_DIR"}


def _money(x: float) -> str:
    text = f"{x:.3f}".rstrip("0")
    return "$" + (text if len(text.split(".")[1]) >= 2 else f"{x:.2f}")


def _span(values: list) -> str:
    vals = sorted({float(v) for v in values})
    return _money(vals[0]) if len(vals) == 1 else f"{_money(vals[0])}-{_money(vals[-1])}"


async def _check_one(c: httpx.AsyncClient, route: str, tool: str) -> tuple:
    """(level, text): the model behind one tool, looked up in its provider's catalog."""
    spec = MODELS[route]
    prov = PROVIDERS[spec["provider"]]
    try:
        model = _model(route)
    except ModelError as exc:
        return "FAIL", f"{tool}: {exc}"
    about = [NAMES.get(model, ""), "the default" if model == spec["default"] else "from stack.env"]
    head = f"{tool}: {model} ({', '.join(x for x in about if x)})"
    keyless = "" if (os.environ.get(prov["key"]) or "").strip() else f"; {prov['key']} is empty, so {tool} can't run yet"
    try:
        caps = await (_or_caps(c, route, model) if spec["provider"] == "openrouter" else _opper_caps(c, model))
    except ModelError as exc:
        return "FAIL", str(exc)
    if caps is None:
        return "WARN", (f"{head}: not checked — {prov['name']}'s catalog couldn't be read "
                        f"({_CATALOG_ERR.get(spec['provider'], 'no reply')}){keyless}")
    problem = (_svg_problem(caps, model) if route == "svg" else _edit_problem(caps, model) if route == "edit"
               else _image_problem(caps, model))
    if problem:
        return "FAIL", problem
    if route == "svg":
        lo, hi = _or_range(caps, "n", (1, 1))
        facts = ["SVG output", f"{lo}-{hi} a call" if hi > lo else "1 a call"]
        if _or_range(caps, "input_references", (0, 0))[0] == 1:
            facts.append("a reference image required on every call")
    elif route == "edit":
        fewest, most = _or_range(caps, "input_references", (0, 0))
        facts = [f"{fewest}-{most} input images" if fewest > 1 else f"up to {most} input image{'s' if most != 1 else ''}"]
    else:
        facts = ["takes reference images" if "image_edit" in caps["capabilities"] else "no reference images"]
    prices = list((caps.get("prices") or {}).values())
    if not prices and isinstance(caps.get("price"), (int, float)):
        prices = [caps["price"]]
    if prices:
        facts.append(_span(prices) + " an image" + (" by quality" if route == "image" and len(prices) > 1 else
                                                     " by resolution" if len(prices) > 1 else ""))
    if caps.get("source") != "catalog":
        return "WARN", (f"{head}: {', '.join(facts)} (the stack's copy: {prov['name']}'s catalog couldn't be "
                        f"read: {_CATALOG_ERR.get(spec['provider'], 'no reply')}){keyless}")
    return ("WARN" if keyless else "ok"), f"{head}: {', '.join(facts)} (checked in {prov['name']}'s catalog){keyless}"


async def _check() -> list:
    """Doctor lines for the three models (no paid call), then any retired setting still in stack.env."""
    routes = (("svg", "generate_svg"), ("image", "generate_image"), ("edit", "edit_image"))
    async with _client() as c:
        rows = await asyncio.gather(*(_check_one(c, r, t) for r, t in routes), return_exceptions=True)
    rows = [row if isinstance(row, tuple) else ("WARN", f"{t}: not checked ({type(row).__name__}: {row})")
            for row, (_, t) in zip(rows, routes, strict=True)]
    rows += [("WARN", f"{k} is set but image-studio doesn't read it ({why}): delete it from stack.env")
             for k, why in RETIRED_ENV.items() if (os.environ.get(k) or "").strip()]
    return [(level, _redact(text)) for level, text in rows]


if __name__ == "__main__":
    if sys.argv[1:] == ["--check"]:
        POLL_TIMEOUT = 10.0                 # a doctor run waits at most this long for one catalog read
        results = asyncio.run(_check())
        for level, text in results:
            print(f"  {level:<6}{text}")
        sys.exit(1 if any(level == "FAIL" for level, _ in results) else 0)
    mcp.run()
