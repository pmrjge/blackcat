# /// script
# requires-python = ">=3.10"
# dependencies = ["mcp>=1.10,<2", "httpx>=0.27"]
# [tool.uv]
# exclude-newer = "2026-09-27T00:00:00Z"
# ///
"""libdocs — up-to-date library documentation for coding agents (a Context7 replacement).

Tools
  resolve_library(name, ecosystem)          -> candidate ids with latest version, docs site, repo
  get_library_docs(library, topic, version) -> the most relevant doc sections as markdown, with sources
  index_library_docs(library, ...)          -> crawl a docs site once (Spider) into the local index

Where the text comes from, cheapest first (everything fetched is kept in a local SQLite FTS index):
  1. local index                          free, instant
  2. llms-full.txt / llms.txt on the docs  free (many modern docs sites publish them)
  3. project README from GitHub            free
  4. Exa search limited to docs + repo     paid (EXA_API_KEY), page text included
  5. Jina Reader for pages still thin      JINA_API_KEY optional (keyless is rate-limited)
  Spider crawls whole sites on request     paid (SPIDER_API_KEY)
Package metadata comes from PyPI, npm and crates.io (free).

Env: EXA_API_KEY, JINA_API_KEY, SPIDER_API_KEY, GITHUB_TOKEN (optional), LIBDOCS_CACHE
(~/.cache/libdocs), LIBDOCS_TTL_DAYS (14). Unset keys are read from $STACK_ENV_FILE, else
stack.env in this script's config dir (<dir>/mcp/../stack.env), else ~/.claude/stack.env.
"""
from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import os
import re
import socket
import sqlite3
import ssl
import time
from pathlib import Path
from urllib.parse import quote, urljoin, urlparse

import httpx
from mcp.server.fastmcp import FastMCP


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


_load_env_file()
logging.getLogger("httpx").setLevel(logging.WARNING)
CACHE = Path(os.environ.get("LIBDOCS_CACHE", "~/.cache/libdocs")).expanduser()
TTL = float(os.environ.get("LIBDOCS_TTL_DAYS", "14")) * 86400
EXA_URL = os.environ.get("LIBDOCS_EXA_URL", "https://api.exa.ai").rstrip("/")
JINA_URL = os.environ.get("LIBDOCS_JINA_URL", "https://r.jina.ai").rstrip("/")
JINA_SEARCH_URL = os.environ.get("LIBDOCS_JINA_SEARCH_URL", "https://s.jina.ai").rstrip("/")
SPIDER_URL = os.environ.get("LIBDOCS_SPIDER_URL", "https://api.spider.cloud").rstrip("/")
UA = "libdocs-mcp/1.0"
MAX_TEXT = 8_000_000   # bytes kept from any fetched text
MAX_HOPS = 5           # redirects followed by hand in the guarded fetch
_TRANSPORT = None      # tests inject an httpx.MockTransport here
STOP = set("a an and are as at be by for from how i in into is it of on or the this to use using with what when "
           "where which why do does can should example examples docs documentation".split())

mcp = FastMCP("libdocs", log_level="WARNING")


# ------------------------------------------------------------------ storage
_DB: sqlite3.Connection | None = None
_FTS = True


def db() -> sqlite3.Connection:
    global _DB, _FTS
    if _DB is None:
        CACHE.mkdir(parents=True, exist_ok=True)
        c = sqlite3.connect(CACHE / "index.sqlite", timeout=15)
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA busy_timeout=15000")
        c.execute("CREATE TABLE IF NOT EXISTS libs(key TEXT PRIMARY KEY, data TEXT, t REAL)")
        c.execute("CREATE TABLE IF NOT EXISTS pages(lib TEXT, url TEXT, title TEXT, via TEXT, t REAL, "
                  "PRIMARY KEY(lib, url))")
        c.execute("CREATE TABLE IF NOT EXISTS asked(lib TEXT, q TEXT, t REAL, PRIMARY KEY(lib, q))")
        try:
            c.execute("CREATE VIRTUAL TABLE IF NOT EXISTS chunks USING fts5("
                      "lib UNINDEXED, page UNINDEXED, url UNINDEXED, heading, body, tokenize='porter unicode61')")
        except sqlite3.OperationalError:
            _FTS = False
            c.execute("CREATE TABLE IF NOT EXISTS chunks(lib TEXT, page TEXT, url TEXT, heading TEXT, body TEXT)")
        c.commit()
        _DB = c
    return _DB


def _kv_get(key: str, max_age: float):
    row = db().execute("SELECT data, t FROM libs WHERE key=?", (key,)).fetchone()
    if row and time.time() - row[1] < max_age:
        return json.loads(row[0])
    return None


def _kv_put(key: str, data) -> None:
    db().execute("INSERT OR REPLACE INTO libs VALUES(?,?,?)", (key, json.dumps(data), time.time()))
    db().commit()


# ------------------------------------------------------------------ chunking and search
_HEAD = re.compile(r"^(#{1,4})\s+(.+?)\s*#*\s*$")
_LINKHEAD = re.compile(r"^\[([^\]]+)\]\((https?://[^)\s]+)\)$")
_SRCLINE = re.compile(r"^\s*(?:Source|URL|Source URL)\s*:\s*<?(https?://[^\s>]+)>?\s*$", re.I)


def _chunks(text: str, title: str, max_chars: int = 1800):
    """Split markdown into (heading trail, body, source url or None) sections."""
    out, stack, buf, fence, src = [], [], [], False, [None]

    def trail():
        return " › ".join([title] + [h for _, h in stack]) if title else " › ".join(h for _, h in stack)

    def flush():
        body = "\n".join(buf).strip()
        buf.clear()
        if len(re.sub(r"\s", "", body)) < 40:
            return
        if len(body) <= max_chars * 1.3:
            out.append((trail(), body, src[0]))
            return
        part, infence = [], False
        for para in re.split(r"(\n\s*\n)", body):
            if para.count("```") % 2:
                infence = not infence
            part.append(para)
            if not infence and sum(map(len, part)) >= max_chars:
                out.append((trail(), "".join(part).strip(), src[0]))
                part = []
        if "".join(part).strip():
            out.append((trail(), "".join(part).strip(), src[0]))

    for line in text.splitlines():
        s = line.lstrip()
        if s.startswith("```") or s.startswith("~~~"):
            fence = not fence
        m = None if fence else _HEAD.match(line)
        sm = None if fence or m else _SRCLINE.match(line)
        if m:
            flush()
            lvl, head = len(m.group(1)), re.sub(r"\\([_*`\[\]])", r"\1", m.group(2).strip())
            lm = _LINKHEAD.match(head)
            if lm:  # "# [Page title](https://…)" marks a new page inside llms-full.txt
                head, src[0] = lm.group(1), lm.group(2)
            while stack and stack[-1][0] >= lvl:
                stack.pop()
            if not (stack and stack[-1][1] == head):
                stack.append((lvl, head))
        elif sm:
            flush()
            src[0] = sm.group(1)
        else:
            buf.append(line)
    flush()
    return out


def _index(lib: str, url: str, title: str, text: str, via: str) -> int:
    c = db()
    c.execute("DELETE FROM chunks WHERE lib=? AND page=?", (lib, url))
    rows = [(lib, url, u or url, h, b) for h, b, u in _chunks(text or "", title or "")]
    c.executemany("INSERT INTO chunks(lib, page, url, heading, body) VALUES(?,?,?,?,?)", rows)
    c.execute("INSERT OR REPLACE INTO pages VALUES(?,?,?,?,?)", (lib, url, title or "", via, time.time()))
    c.commit()
    return len(rows)


def _terms(topic: str) -> list[str]:
    ts = [t.strip(".") for t in re.findall(r"[A-Za-z_][A-Za-z0-9_.]*", topic.lower())]
    return [t for t in dict.fromkeys(ts) if len(t) > 1 and t not in STOP][:12]


def _search(lib: str, topic: str) -> list[tuple]:
    c, terms = db(), _terms(topic)
    if not terms:
        return c.execute("SELECT url, heading, body, 0 FROM chunks WHERE lib=? ORDER BY rowid LIMIT 40",
                         (lib,)).fetchall()
    if _FTS:
        quoted = ['"%s"' % t.replace('"', "") for t in terms]
        tiers = ([" ".join(['"%s"' % " ".join(terms)])] if len(terms) > 1 else []) + \
                [" AND ".join(quoted), " OR ".join(quoted)]
        out, seen = [], set()
        try:
            for q in dict.fromkeys(tiers):
                for row in c.execute("SELECT url, heading, body, bm25(chunks, 0.0, 0.0, 0.0, 4.0, 1.0) AS s "
                                     "FROM chunks WHERE chunks MATCH ? AND lib=? ORDER BY s LIMIT 40", (q, lib)):
                    k = (row[0], row[1], row[2][:120])
                    if k not in seen:
                        seen.add(k)
                        out.append(row)
                if len(out) >= 40:
                    break
            return out[:40]
        except sqlite3.OperationalError:
            pass
    rows = c.execute("SELECT url, heading, body FROM chunks WHERE lib=?", (lib,)).fetchall()
    scored = []
    for u, h, b in rows:
        hl, bl = h.lower(), b.lower()
        s = sum(4 * hl.count(t) + bl.count(t) for t in terms)
        if s:
            scored.append((u, h, b, -s))
    return sorted(scored, key=lambda r: r[3])[:40]


def _enough(hits: list, budget: int, topic: str) -> bool:
    if not hits:
        return False
    terms = _terms(topic)
    if terms:  # the best hit should contain most of the query terms
        top = (hits[0][1] + " " + hits[0][2]).lower()
        if sum(t in top for t in terms) < max(1, (len(terms) + 1) // 2):
            return False
    return len(hits) >= 3 and sum(len(h[2]) for h in hits[:8]) >= min(budget, 2500)


def _expire(lib: str) -> None:
    c = db()
    old = [u for (u,) in c.execute("SELECT url FROM pages WHERE lib=? AND t<?", (lib, time.time() - TTL))]
    for u in old:
        c.execute("DELETE FROM chunks WHERE lib=? AND page=?", (lib, u))
        c.execute("DELETE FROM pages WHERE lib=? AND url=?", (lib, u))
    c.execute("DELETE FROM asked WHERE lib=? AND t<?", (lib, time.time() - TTL))
    c.commit()


def _have_pages(lib: str) -> set[str]:
    return {u for (u,) in db().execute("SELECT url FROM pages WHERE lib=?", (lib,))}


# ------------------------------------------------------------------ HTTP helpers
def _client() -> httpx.AsyncClient:
    """For the fixed API endpoints only. Never follows redirects (a 3xx counts as a failed call);
    every other URL goes through _guarded_get."""
    ca = os.environ.get("SSL_CERT_FILE")  # honor corporate/proxy CA bundles
    verify = ssl.create_default_context(cafile=ca) if ca and os.path.isfile(ca) else True
    return httpx.AsyncClient(timeout=httpx.Timeout(45, connect=10), follow_redirects=False,
                             headers={"User-Agent": UA}, verify=verify, transport=_TRANSPORT)


def _origin(url: str) -> tuple:
    u = urlparse(url)
    return (u.scheme.lower(), (u.hostname or "").lower().rstrip("."), u.port or (443 if u.scheme.lower() == "https" else 80))


def _fixed_origins() -> set:
    urls = ["https://pypi.org", "https://registry.npmjs.org", "https://api.npmjs.org", "https://pypistats.org",
            "https://crates.io", "https://api.github.com", "https://raw.githubusercontent.com",
            EXA_URL, JINA_URL, JINA_SEARCH_URL, SPIDER_URL]
    return {_origin(u) for u in urls}


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


def _public(ip) -> bool:
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast


def _fetchable(url: str) -> str:
    """The host of a URL that may be fetched at all: https only, never localhost or a non-public literal."""
    u = urlparse(url)
    host = (u.hostname or "").lower().rstrip(".")
    if u.scheme.lower() != "https" or not host:
        raise ValueError(f"refusing to fetch a non-https URL: {url[:160]}")
    if host == "localhost" or host.endswith((".localhost", ".local", ".internal", ".home.arpa")):
        raise ValueError(f"refusing to fetch a local host: {host}")
    ip = _ip_literal(host)
    if ip is not None and not _public(ip):
        raise ValueError(f"refusing to fetch a non-public address: {host}")
    return host


async def _resolve_host(host: str) -> list:
    """The addresses host resolves to here ([] when it doesn't); tests replace this."""
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    except OSError:
        return []
    return [sa[0] for *_, sa in infos]


async def _vet(url: str) -> tuple:
    """(host name for Host/SNI, checked addresses): every address must be global."""
    host = _fetchable(url)
    ip = _ip_literal(host)
    if ip is not None:
        return str(ip), [str(ip)]
    addrs = await _resolve_host(host)
    if not addrs:
        raise ValueError(f"refusing to fetch {host}: it does not resolve")
    for a in addrs:
        if not _public(ipaddress.ip_address(a.split("%", 1)[0])):
            raise ValueError(f"refusing to fetch {host}: it resolves to a non-public address")
    return host, [a.split("%", 1)[0] for a in addrs]


async def _hop(c: httpx.AsyncClient, url: str, max_bytes: int):
    """One checked request: (next url, None) on a redirect, else (None, (status, content-type, text))."""
    host, addrs = await _vet(url)
    u = urlparse(url)
    port = f":{u.port}" if u.port else ""
    last: Exception | None = None
    for addr in addrs:   # connect to the checked address, never to the name
        pinned = u._replace(netloc=(f"[{addr}]" if ":" in addr else addr) + port, path=u.path or "/",
                            fragment="").geturl()
        try:
            async with c.stream("GET", pinned, headers={"Host": (f"[{host}]" if ":" in host else host) + port},
                                extensions={"sni_hostname": host}) as r:
                if r.is_redirect:
                    return urljoin(url, r.headers["location"]), None
                body = bytearray()
                async for chunk in r.aiter_bytes():
                    body += chunk
                    if len(body) >= max_bytes:
                        break
                text = bytes(body[:max_bytes]).decode(r.encoding or "utf-8", "replace")
                return None, (r.status_code, r.headers.get("content-type", ""), text)
        except (httpx.ConnectError, httpx.ConnectTimeout) as e:
            last = e   # try the next checked address
    raise last or httpx.ConnectError("no address")


async def _guarded_get(url: str, max_bytes: int = MAX_TEXT) -> tuple:
    """GET any URL that is not a fixed API endpoint -> (status, content-type, text). https only; the host is
    resolved once per hop and every address checked; the connection goes to the checked IP (Host header and
    TLS server name stay the real host); redirects are followed by hand (MAX_HOPS), each one fully re-checked.
    Raises ValueError for a refused URL."""
    ca = os.environ.get("SSL_CERT_FILE")
    verify = ssl.create_default_context(cafile=ca) if ca and os.path.isfile(ca) else True
    async with httpx.AsyncClient(timeout=httpx.Timeout(45, connect=10), follow_redirects=False, verify=verify,
                                 headers={"User-Agent": UA}, transport=_TRANSPORT) as c:
        for _ in range(MAX_HOPS + 1):
            url, res = await _hop(c, url, max_bytes)
            if res:
                return res
    raise ValueError(f"too many redirects (> {MAX_HOPS})")


async def _get_json(c, url, **kw):
    try:
        r = await c.get(url, **kw)
        return r.json() if r.status_code == 200 else None
    except (httpx.HTTPError, ValueError):
        return None


def _repo(url: str | None) -> str | None:
    if not url:
        return None
    m = re.search(r"github\.com[/:]([^/\s]+)/([^/#?\s]+?)(?:\.git)?(?:[/#?].*)?$", url)
    return f"https://github.com/{m.group(1)}/{m.group(2)}" if m else None


def _pick(urls: dict, keys: list[str]) -> str | None:
    for k in keys:
        for name, v in urls.items():
            if name.lower().replace("-", " ").strip() == k and v:
                return v
    return None


# ------------------------------------------------------------------ registries
async def _pypi(c, name):
    d = await _get_json(c, f"https://pypi.org/pypi/{quote(name)}/json")
    if not d:
        return None
    i = d["info"]
    urls = i.get("project_urls") or {}
    docs = _pick(urls, ["documentation", "docs", "doc"]) or i.get("docs_url")
    home = _pick(urls, ["homepage", "home", "home page"]) or i.get("home_page")
    repo = _repo(_pick(urls, ["source", "source code", "repository", "code", "github"])) or _repo(home) or _repo(docs)
    stats = None
    for _ in range(2):  # pypistats is occasionally slow; unknown downloads are ranked neutrally
        stats = await _get_json(c, f"https://pypistats.org/api/packages/{quote(name.lower())}/recent", timeout=8)
        if stats:
            break
    dl = ((stats or {}).get("data") or {}).get("last_week") if stats else None
    return {"id": f"pypi:{i['name'].lower()}", "name": i["name"], "ecosystem": "pypi", "version": i.get("version"),
            "summary": i.get("summary") or "", "docs": docs or (home if not _repo(home) else None),
            "repo": repo, "downloads": dl}


async def _npm(c, name):
    d = await _get_json(c, f"https://registry.npmjs.org/{quote(name, safe='@')}/latest")
    if not d:
        return None
    dl = await _get_json(c, f"https://api.npmjs.org/downloads/point/last-week/{quote(name, safe='@/')}", timeout=6)
    repo_field = d.get("repository")
    repo = _repo(repo_field.get("url") if isinstance(repo_field, dict) else repo_field)
    home = d.get("homepage")
    return {"id": f"npm:{name}", "name": name, "ecosystem": "npm", "version": d.get("version"),
            "summary": d.get("description") or "", "docs": home if home and not _repo(home) else None,
            "repo": repo or _repo(home), "downloads": (dl or {}).get("downloads")}


async def _crates(c, name):
    d = await _get_json(c, f"https://crates.io/api/v1/crates/{quote(name)}")
    if not d:
        return None
    cr = d["crate"]
    return {"id": f"crates:{cr['name']}", "name": cr["name"], "ecosystem": "crates",
            "version": cr.get("max_stable_version") or cr.get("newest_version"),
            "summary": cr.get("description") or "",
            "docs": cr.get("documentation") or f"https://docs.rs/{cr['name']}",
            "repo": _repo(cr.get("repository")), "downloads": int((cr.get("recent_downloads") or 0) / 13)}


async def _github(c, owner_repo):
    hdr = {"Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}"} if os.environ.get("GITHUB_TOKEN") else {}
    d = await _get_json(c, f"https://api.github.com/repos/{owner_repo}", headers=hdr)
    repo = f"https://github.com/{owner_repo}"
    home = (d or {}).get("homepage") or None
    return {"id": f"gh:{owner_repo}", "name": owner_repo.split("/")[-1], "ecosystem": "github",
            "version": None, "summary": (d or {}).get("description") or "", "docs": home,
            "repo": repo, "downloads": (d or {}).get("stargazers_count", 0)}


REGISTRIES = {"pypi": _pypi, "npm": _npm, "crates": _crates}


async def _candidates(c, name: str, ecosystem: str = "") -> list[dict]:
    name = name.strip()
    if re.match(r"^https?://", name):
        u = urlparse(name)
        return [{"id": "url:" + u.netloc + u.path.rstrip("/"), "name": u.netloc, "ecosystem": "url",
                 "version": None, "summary": "", "docs": name, "repo": _repo(name), "downloads": 0}]
    m = re.match(r"^(pypi|npm|crates|gh|github):(.+)$", name)
    if m:
        eco, name = ("gh" if m.group(1) == "github" else m.group(1)), m.group(2)
        ecosystem = eco
    if ecosystem in ("gh", "github") or re.match(r"^[\w.-]+/[\w.-]+$", name) and not name.startswith("@"):
        return [await _github(c, name)]
    ecos = [ecosystem] if ecosystem in REGISTRIES else list(REGISTRIES)
    found = await asyncio.gather(*(REGISTRIES[e](c, name) for e in ecos))
    return sorted([f for f in found if f], key=lambda x: -_score(x))


def _score(x: dict) -> float:
    """Rank same-named packages across registries: popularity (log), docs/repo presence, no placeholders."""
    import math
    if "security holding" in (x.get("summary") or "").lower() or "-security" in str(x.get("version")):
        return -100.0
    dl = x.get("downloads")
    pop = math.log10(dl + 1) if isinstance(dl, (int, float)) else 5.0  # unknown ≈ an established package
    return pop + (1.0 if x.get("docs") else 0.0) + (1.0 if x.get("repo") else 0.0)


async def _resolve(c, library: str) -> dict | None:
    key = "resolve:" + library.strip().lower()
    hit = _kv_get(key, TTL / 7)
    if hit:
        return hit
    cands = await _candidates(c, library)
    if not cands:
        return None
    lib = cands[0]
    if not lib.get("docs") and lib.get("repo") and lib["ecosystem"] != "github":
        gh = await _github(c, lib["repo"].split("github.com/")[1])
        lib["docs"] = gh.get("docs")
    _kv_put(key, lib)
    return lib


# ------------------------------------------------------------------ fetchers
async def _fetch_raw(c, url: str) -> str | None:
    try:
        if _origin(url) in _fixed_origins():
            r = await c.get(url)
            status, ct, text = r.status_code, r.headers.get("content-type", ""), r.text[:MAX_TEXT]
        else:
            status, ct, text = await _guarded_get(url)
    except (httpx.HTTPError, ValueError):
        return None
    if status != 200 or "html" in ct or text.lstrip()[:15].lower().startswith(("<!doctype", "<html")):
        return None
    return text


async def _llms(c, docs: str | None) -> tuple[str, str] | None:
    if not docs or "github.com" in docs:
        return None
    base = docs if docs.endswith("/") else docs + "/"
    origin = "{0.scheme}://{0.netloc}/".format(urlparse(docs))
    for u in dict.fromkeys([urljoin(base, "llms-full.txt"), urljoin(origin, "llms-full.txt"),
                            urljoin(base, "llms.txt"), urljoin(origin, "llms.txt")]):
        t = await _fetch_raw(c, u)
        if t and len(t) > 200:
            return u, t
    return None


async def _jina(c, url: str) -> tuple[str, str] | None:
    h = {"Accept": "application/json", "X-Retain-Images": "none"}
    if os.environ.get("JINA_API_KEY"):
        h["Authorization"] = "Bearer " + os.environ["JINA_API_KEY"]
    try:
        _fetchable(url)   # a third-party fetcher gets only https URLs that pass the string checks
    except ValueError:
        return None
    d = await _get_json(c, f"{JINA_URL}/{url}", headers=h, timeout=90)
    d = (d or {}).get("data") or {}
    return (d.get("title") or url, d.get("content") or "") if d.get("content") else None


async def _readme(c, repo: str | None) -> tuple[str, str] | None:
    if not repo:
        return None
    path = repo.split("github.com/")[1]
    for f in ("README.md", "readme.md", "README.rst", "README"):
        t = await _fetch_raw(c, f"https://raw.githubusercontent.com/{path}/HEAD/{f}")
        if t:
            return f"{repo}#readme", t
    return None


async def _exa(c, query: str, domains: list[str], n: int = 6) -> tuple[list, float]:
    key = os.environ.get("EXA_API_KEY")
    if not key:
        return [], 0.0
    body = {"query": query, "type": "auto", "numResults": n, "contents": {"text": {"maxCharacters": 20000}}}
    if domains:
        body["includeDomains"] = domains
    try:
        r = await c.post(f"{EXA_URL}/search", json=body, headers={"x-api-key": key}, timeout=60)
        d = r.json() if r.status_code == 200 else {}
    except (httpx.HTTPError, ValueError):
        d = {}
    res = [(x.get("url"), x.get("title") or "", x.get("text") or "") for x in d.get("results", []) if x.get("url")]
    return res, float((d.get("costDollars") or {}).get("total") or 0)


async def _jina_search(c, query: str, site: str | None) -> list:
    key = os.environ.get("JINA_API_KEY")
    if not key:
        return []
    params = {"q": query}
    if site:
        params["site"] = site
    d = await _get_json(c, f"{JINA_SEARCH_URL}/", params=params, timeout=90,
                        headers={"Accept": "application/json", "Authorization": "Bearer " + key,
                                 "X-Retain-Images": "none"})
    return [(x.get("url"), x.get("title") or "", x.get("content") or "") for x in (d or {}).get("data") or []
            if x.get("url")]


def _toc(llms_text: str, docs_url: str) -> list[tuple[str, str]]:
    """The links of an llms.txt that stay on the docs origin (a third-party file must not pick our targets)."""
    return [(m.group(1) + " " + (m.group(3) or ""), m.group(2))
            for m in re.finditer(r"\[([^\]]+)\]\((https?://[^)\s]+)\)(?::\s*([^\n]*))?", llms_text)
            if _origin(m.group(2)) == _origin(docs_url)]


def _rank_toc(toc, topic, skip, k):
    terms = _terms(topic)
    scored = [(sum(t in label.lower() for t in terms), i, label, u) for i, (label, u) in enumerate(toc)
              if u not in skip]
    scored.sort(key=lambda x: (-x[0], x[1]))
    return [(label, u) for s, _, label, u in scored[:k] if s > 0 or not terms]


async def _fetch_pages(c, lib_id, items) -> list[str]:
    """items: [(label, url)] — .md/.txt fetched directly (free), others through Jina."""
    sem, done = asyncio.Semaphore(5), []

    async def one(label, u):
        async with sem:
            t = await _fetch_raw(c, u) if re.search(r"\.(md|mdx|txt)(\?|#|$)", u) else None
            via = "direct"
            if not t:
                j = await _jina(c, u)
                if not j:
                    return
                label, t, via = j[0], j[1], "jina"
            _index(lib_id, u, label, t, via)
            done.append(via)

    await asyncio.gather(*(one(lb, u) for lb, u in items))
    return done


# ------------------------------------------------------------------ retrieval pipeline
async def _seed(c, lib: dict, topic: str) -> list[str]:
    notes = []
    got = await _llms(c, lib.get("docs"))
    if got:
        url, text = got
        _index(lib["id"], url, lib["name"] + " docs", text, "llms")
        notes.append(url.rsplit("/", 1)[-1])
        if url.endswith("llms.txt"):
            toc = _toc(text, url)
            _kv_put("toc:" + lib["id"], toc)
            vias = await _fetch_pages(c, lib["id"], _rank_toc(toc, topic, set(), 4))
            if vias:
                notes.append(f"{len(vias)} pages from llms.txt")
    rd = await _readme(c, lib.get("repo"))
    if rd:
        _index(lib["id"], rd[0], lib["name"] + " README", rd[1], "github")
        notes.append("README")
    if not got and lib.get("docs"):
        j = await _jina(c, lib["docs"])
        if j:
            _index(lib["id"], lib["docs"], j[0], j[1], "jina")
            notes.append("docs home (jina)")
    return notes


async def _augment(c, lib: dict, topic: str, version: str) -> list[str]:
    notes, have = [], _have_pages(lib["id"])
    toc = [(lb, u) for lb, u in _kv_get("toc:" + lib["id"], TTL) or []
           if lib.get("docs") and _origin(u) == _origin(lib["docs"])]
    if toc:
        vias = await _fetch_pages(c, lib["id"], _rank_toc(toc, topic, have, 4))
        if vias:
            notes.append(f"{len(vias)} more llms.txt pages")
            hits = _search(lib["id"], topic)
            if _enough(hits, 3000, topic):
                return notes
    domains = []
    if lib.get("docs"):
        u = urlparse(lib["docs"])
        domains.append(u.netloc + (u.path.rstrip("/") if u.path not in ("", "/") and "github.com" not in u.netloc else ""))
    if lib.get("repo"):
        domains.append(lib["repo"].replace("https://", ""))
    query = f"{lib['name']} {version} {topic}".replace("  ", " ").strip()
    results, cost = await _exa(c, query, domains)
    if not results and domains:
        results, cost2 = await _exa(c, query + " documentation", [])
        cost += cost2
    src = "exa"
    if not results:
        results = await _jina_search(c, query, urlparse(lib["docs"]).netloc if lib.get("docs") else None)
        src = "jina search"
    thin = []
    for u, title, text in results:
        if len(text) >= 600:
            _index(lib["id"], u, title, text, src)
        else:
            thin.append((title, u))
    if results:
        notes.append(f"{src}: {len(results)} pages" + (f" (${cost:.3f})" if cost else ""))
    if thin:
        vias = await _fetch_pages(c, lib["id"], thin[:3])
        if vias:
            notes.append(f"jina: {len(vias)} pages")
    return notes


def _render(lib: dict, hits: list, budget: int, notes: list[str], version: str) -> str:
    head = f"# {lib['name']} {lib.get('version') or ''} ({lib['ecosystem']})".rstrip()
    lines = [head, f"docs: {lib.get('docs') or '-'} · repo: {lib.get('repo') or '-'}"]
    if version and lib.get("version") and version not in str(lib["version"]):
        lines.append(f"note: latest release is {lib['version']}; you asked for {version} — check version-specific APIs")
    lines.append("retrieved via: " + (", ".join(notes) if notes else "local cache"))
    out, used, seen = "\n".join(lines) + "\n", 0, set()
    for url, heading, body, _ in hits:
        k = body[:200]
        if k in seen:
            continue
        seen.add(k)
        block = f"\n### {heading or urlparse(url).path}\nSource: {url}\n\n{body}\n"
        if used + len(block) > budget:
            if used == 0:
                out += block[:budget] + "\n…[truncated]\n"
            break
        out += block
        used += len(block)
    if not hits:
        out += ("\nNo matching documentation found. Try a broader topic, pass the docs URL as `library`, "
                "or run index_library_docs.\n")
    return out


# ------------------------------------------------------------------ tools
@mcp.tool()
async def resolve_library(name: str, ecosystem: str = "") -> str:
    """Find a library and its canonical id. name: package name ('httpx', '@tanstack/react-query', 'tokio'),
    'owner/repo' for GitHub, or a docs URL. ecosystem: optional 'pypi' | 'npm' | 'crates' | 'gh'.
    Returns candidates (most downloaded first): id | latest version | weekly downloads | docs | repo | summary."""
    async with _client() as c:
        cands = await _candidates(c, name, ecosystem)
    if not cands:
        return f"No package named '{name}' on PyPI, npm or crates.io. Pass 'owner/repo' or a docs URL instead."
    rows = [f"{x['id']} | {x.get('version') or '-'} | "
            f"{x['downloads'] if x.get('downloads') is not None else '?'}/wk | {x.get('docs') or '-'} | "
            f"{x.get('repo') or '-'} | {(x.get('summary') or '')[:90]}" for x in cands]
    return "\n".join(rows) + "\nUse the id with get_library_docs."


@mcp.tool()
async def get_library_docs(library: str, topic: str = "", version: str = "", tokens: int = 5000) -> str:
    """Up-to-date documentation for a library, focused on a topic.
    library: id from resolve_library ('pypi:httpx', 'npm:react', 'crates:tokio', 'gh:owner/repo'),
    a bare package name, or a docs URL. topic: what you need ('async client timeouts', 'useEffect cleanup').
    version: optional version you target. tokens: max size of the answer (500-20000, default 5000).
    Returns the most relevant doc sections with their source URLs; results are cached locally."""
    budget = max(500, min(int(tokens or 5000), 20000)) * 4
    async with _client() as c:
        lib = await _resolve(c, library)
        if not lib:
            return f"Could not resolve '{library}'. Use resolve_library, 'owner/repo', or a docs URL."
        _expire(lib["id"])
        notes = []
        if not _have_pages(lib["id"]):
            notes += await _seed(c, lib, topic)
        hits = _search(lib["id"], topic)
        qkey = f"{version} {topic}".strip().lower()
        asked = db().execute("SELECT 1 FROM asked WHERE lib=? AND q=?", (lib["id"], qkey)).fetchone()
        if topic and not _enough(hits, budget, topic) and not asked:
            notes += await _augment(c, lib, topic, version)
            db().execute("INSERT OR REPLACE INTO asked VALUES(?,?,?)", (lib["id"], qkey, time.time()))
            db().commit()
            hits = _search(lib["id"], topic)
    return _render(lib, hits, budget, notes, version)


@mcp.tool()
async def index_library_docs(library: str, start_url: str = "", path_prefix: str = "", limit: int = 150) -> str:
    """Crawl a library's documentation site once into the local index so later get_library_docs calls are
    free and complete. Uses Spider (SPIDER_API_KEY); without it, falls back to the llms.txt page list.
    start_url: override the docs root. path_prefix: only crawl URLs under this path (e.g. '/docs/').
    limit: max pages (default 150, max 1000)."""
    limit = max(1, min(int(limit or 150), 1000))
    async with _client() as c:
        lib = await _resolve(c, library)
        if not lib:
            return f"Could not resolve '{library}'."
        root = start_url or lib.get("docs")
        if not root:
            return "No docs site known for this library; pass start_url."
        try:
            await _vet(root)
        except ValueError as e:
            return f"Refused start_url/docs root: {e}"
        u = urlparse(root)
        prefix = f"{u.scheme}://{u.netloc}" + (path_prefix or (u.path if u.path not in ("", "/") else "/"))
        key = os.environ.get("SPIDER_API_KEY")
        if key:
            body = {"url": root, "limit": limit, "return_format": "markdown", "readability": True,
                    "request": "smart", "whitelist": ["^" + re.escape(prefix)]}
            try:
                r = await c.post(f"{SPIDER_URL}/crawl", json=body, timeout=900,
                                 headers={"Authorization": "Bearer " + key})
                data = r.json() if r.status_code == 200 else {"error": r.text[:300]}
            except (httpx.HTTPError, ValueError) as e:
                data = {"error": str(e)}
            if isinstance(data, dict) and "error" in data and not data.get("data"):
                return f"Spider error: {data['error']}"
            items = data.get("data", []) if isinstance(data, dict) else data
            n = chunks = 0
            cost = 0.0
            for it in items:
                if it.get("content") and not it.get("error"):
                    chunks += _index(lib["id"], it["url"], it.get("title") or "", it["content"], "spider")
                    n += 1
                cost += float(((it.get("costs") or {}).get("total_cost")) or 0)
            return (f"Indexed {n} pages ({chunks} sections) of {lib['id']} from {prefix} via Spider"
                    + (f", cost ${cost:.3f}" if cost else "") + ".")
        got = await _llms(c, root)
        if not got or not got[0].endswith("llms.txt"):
            if got:
                chunks = _index(lib["id"], got[0], lib["name"] + " docs", got[1], "llms")
                return f"No SPIDER_API_KEY; indexed {got[0]} ({chunks} sections) instead."
            return "No SPIDER_API_KEY and no llms.txt on this site; nothing to crawl."
        toc = [(lb, x) for lb, x in _toc(got[1], got[0]) if x.startswith(prefix)][:limit]
        vias = await _fetch_pages(c, lib["id"], toc)
        return f"No SPIDER_API_KEY; indexed {len(vias)} pages listed in {got[0]}."


if __name__ == "__main__":
    mcp.run()
