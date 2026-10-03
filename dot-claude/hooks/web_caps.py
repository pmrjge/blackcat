#!/usr/bin/env python3
"""web_caps.py: per-call caps for the exa, jina and spider MCP tools, and Spider's politeness rules.

PreToolUse hook (settings.json matcher ^mcp__(exa|jina|spider)__). For each call it
  - clamps result counts, characters per call, crawl pages and depth to the caps in KNOBS,
  - fills a cap where the server's own default is unbounded or large (jina num 30, spider limit 0 =
    every page, spider return_format raw HTML, jina sort_by_relevance returning every document),
  - fills Spider's anti-bot options (request mode, fingerprint, proxies, country, idle wait, browser
    stealth) the agent left out (SPIDER_ANTIBOT=1, the default),
  - refuses spider `cron`, `webhooks` and `run_in_background` (recurring spend, data sent to a third URL),
  - with SPIDER_ANTIBOT=0 (opt-in polite mode, the user's choice in stack.env) instead fills
    respect_robots=true, a crawl delay floor and a concurrency cap, sends fingerprint=false, and refuses
    respect_robots=false and Spider's bypasses: spider_unblocker, spider_browser_open / spider_ai_browser
    (stealth escalation, CAPTCHA solving), proxies, fingerprint profiles, custom user agents and cookies,
and returns the whole input as updatedInput with one line of additionalContext naming the changes.
No permissionDecision: the changed input still goes through the normal permission evaluation, so
nothing here loosens a guard. Values the agent passes within the caps are kept.

Knobs: KNOBS below, overridden by the same names in stack.env ($STACK_ENV_FILE, else ../stack.env);
0 turns a numeric cap off, an empty string leaves that option to the agent and the server. Only these
names are read from stack.env, never the keys. Fails open: any error leaves the call unchanged.
Parameter names match spider-cloud-mcp 2.1.2, the Exa remote server (web_search_exa, web_fetch_exa,
web_search_advanced_exa) and the Jina remote server as of 2026-10-03; an unknown tool passes untouched.

  /usr/bin/python3 web_caps.py < event.json     hook mode
  /usr/bin/python3 web_caps.py --self-test      built-in cases
  /usr/bin/python3 web_caps.py --print          effective knob values
"""
import json
import os
import re
import sys

# name: (default, meaning). The single source of these numbers; stack.env.example documents them.
KNOBS = {
    # exa
    "EXA_MAX_RESULTS": (15, "numResults per web_search_exa / web_search_advanced_exa call (server default 10)"),
    "EXA_MAX_SUBPAGES": (3, "subpages per result, web_search_advanced_exa"),
    "EXA_MAX_PAGE_CHARS": (10000, "maxCharacters / textMaxCharacters / highlightsMaxCharacters per page"),
    "EXA_MAX_TOTAL_CHARS": (80000, "pages x characters per page in one call; contextMaxCharacters"),
    "EXA_MAX_LIVECRAWL_MS": (15000, "livecrawlTimeout"),
    # jina
    "JINA_MAX_RESULTS": (10, "num per query, search_web/search_arxiv/search_ssrn/search_images (server default 30; filled)"),
    "JINA_MAX_TOPK": (10, "read_url topk"),
    "JINA_MAX_CHUNK_WORDS": (1000, "read_url chunk_size"),
    "JINA_MAX_RERANK": (20, "sort_by_relevance top_n (server default: every document; filled)"),
    # spider caps
    "SPIDER_DEFAULT_PAGES": (25, "crawl limit when omitted or 0 (Spider's 0 = every page)"),
    "SPIDER_MAX_PAGES": (100, "pages per crawl call over all its URLs; budget values"),
    "SPIDER_DEFAULT_DEPTH": (3, "crawl depth when omitted or 0 (Spider's default 25)"),
    "SPIDER_MAX_DEPTH": (10, "crawl depth"),
    "SPIDER_MAX_RESULTS": (10, "spider_search / spider_ai_search num and search_limit (filled)"),
    "SPIDER_MAX_LINKS": (500, "spider_links / spider_ai_links limit (filled)"),
    "SPIDER_MAX_DELAY_MS": (10000, "crawl delay"),
    "SPIDER_RETURN_FORMAT": ("markdown", "return_format when omitted (Spider's default: raw HTML)"),
    "SPIDER_REQUEST": ("smart", "request mode: smart (HTTP, Chrome when needed), chrome, http"),
    # spider mode: 1 fills the anti-bot options below the agent left out; 0 is polite mode
    "SPIDER_ANTIBOT": ("1", "0 = polite mode: robots.txt, delay, concurrency; bypass tools and options refused"),
    # polite mode only (SPIDER_ANTIBOT=0)
    "SPIDER_DELAY_MS": (1000, "crawl delay floor and fill, ms between requests to the site (Spider: disables concurrency)"),
    "SPIDER_CONCURRENCY": (2, "concurrency_limit fill and cap (Spider's default: unlimited)"),
    # anti-bot defaults (SPIDER_ANTIBOT=1; filled only when the agent left them out)
    "SPIDER_FINGERPRINT": ("1", "fingerprint: a full, consistent browser profile"),
    "SPIDER_PROXY_ENABLED": ("0", "premium proxies on every call (x1.5 credits); spider_unblocker always defaults to 1"),
    "SPIDER_PROXY": ("residential", "proxy pool when proxies are on: residential, mobile, isp, datacenter"),
    "SPIDER_COUNTRY_CODE": ("", "ISO country for the proxy exit (empty = Spider's choice)"),
    "SPIDER_WAIT_IDLE_S": (5, "wait_for idle_network seconds on spider_unblocker and chrome-mode calls (0 = Spider's 500 ms)"),
    "SPIDER_BROWSER": ("auto", "spider_browser_open engine: auto, chrome, chrome-new, firefox"),
    "SPIDER_BROWSER_STEALTH": (0, "spider_browser_open stealth: 0 auto-escalates 1 -> 3, 1 standard, 2 residential, 3 premium"),
}

KEY_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
REFUSED_SPIDER = ("cron", "webhooks", "run_in_background")
# SPIDER_ANTIBOT=0: tools and options that defeat a site's bot protection or carry credentials
BYPASS_TOOLS = ("spider_unblocker", "spider_browser_open", "spider_ai_browser")
BYPASS_OPTS = ("proxy", "remote_proxy", "country_code", "user_agent", "cookies")
SPIDER_FORMAT_TOOLS = {"spider_crawl", "spider_scrape", "spider_unblocker", "spider_search"}
SPIDER_REQUEST_TOOLS = {"spider_crawl", "spider_scrape", "spider_unblocker", "spider_search",
                        "spider_links", "spider_ai_crawl", "spider_ai_scrape", "spider_ai_links"}
SPIDER_PAGE_TOOLS = {"spider_crawl", "spider_scrape", "spider_unblocker", "spider_screenshot"}
SPIDER_PROXY_TOOLS = SPIDER_PAGE_TOOLS | {"spider_search", "spider_ai_crawl", "spider_ai_scrape",
                                          "spider_ai_browser"}
SPIDER_POOL_TOOLS = {"spider_crawl", "spider_scrape", "spider_unblocker"}


def env_path():
    explicit = os.environ.get("STACK_ENV_FILE")
    if explicit:
        return os.path.expanduser(explicit)
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "stack.env")


def read_knobs(path=None):
    """KNOBS defaults overridden by stack.env lines for the same names (shell-style KEY=value)."""
    vals = {k: v[0] for k, v in KNOBS.items()}
    try:
        with open(path or env_path(), encoding="utf-8") as f:
            text = f.read()
    except (OSError, UnicodeDecodeError):
        return vals
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if s.startswith("export "):
            s = s[7:].lstrip()
        key, sep, value = s.partition("=")
        key = key.strip()
        if not sep or key not in KNOBS or not KEY_RE.fullmatch(key):
            continue
        value = value.strip()
        if value[:1] in ("'", '"') and value[0] in value[1:]:
            value = value[1:value.index(value[0], 1)]
        else:
            value = re.split(r"\s+#", value, maxsplit=1)[0].strip()
        default = KNOBS[key][0]
        if isinstance(default, int):
            try:
                vals[key] = max(0, int(value))
            except ValueError:
                pass                     # a malformed number keeps the default
        else:
            vals[key] = value
    return vals


def num(v):
    """An agent's numeric argument (exa accepts numeric strings), or None."""
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return v
    if isinstance(v, str):
        try:
            return float(v) if "." in v else int(v)
        except ValueError:
            return None
    return None


def truthy(v):
    return str(v).strip().lower() in ("1", "true", "yes", "on")


class Edit:
    def __init__(self, inp):
        self.inp = dict(inp)
        self.notes = []
        self.deny = None

    def cap(self, key, cap, fill=None, floor=1):
        """Clamp inp[key] to cap (cap 0 = off). fill: value for an absent key, or for 0 when the
        server reads 0 as unlimited (fill is then also clamped)."""
        if cap is not None and cap <= 0:
            return
        cur = num(self.inp.get(key))
        if key not in self.inp or self.inp.get(key) is None or (fill is not None and cur == 0):
            if fill is None:
                return
            new = min(fill, cap) if cap else fill
            self.inp[key] = max(floor, new)
            self.notes.append("%s=%s" % (key, self.inp[key]))
            return
        if cur is None:
            return
        if cap and cur > cap:
            self.inp[key] = max(floor, int(cap))
            self.notes.append("%s %s->%s" % (key, cur, self.inp[key]))

    def fill(self, key, value):
        if value in ("", None) or key in self.inp:
            return
        self.inp[key] = value
        self.notes.append("%s=%s" % (key, json.dumps(value) if not isinstance(value, str) else value))


def url_count(v):
    if isinstance(v, list):
        return max(1, len(v))
    if isinstance(v, str):
        s = v.strip()
        if s.startswith("["):
            try:
                parsed = json.loads(s)
                if isinstance(parsed, list):
                    return max(1, len(parsed))
            except ValueError:
                pass
        return max(1, len([u for u in s.split(",") if u.strip()]))
    return 1


def exa(tool, e, k):
    if tool == "web_search_exa":
        e.cap("numResults", k["EXA_MAX_RESULTS"])
    elif tool == "web_search_advanced_exa":
        e.cap("numResults", k["EXA_MAX_RESULTS"])
        e.cap("subpages", k["EXA_MAX_SUBPAGES"])
        e.cap("highlightsMaxCharacters", k["EXA_MAX_PAGE_CHARS"])
        e.cap("contextMaxCharacters", k["EXA_MAX_TOTAL_CHARS"])
        e.cap("livecrawlTimeout", k["EXA_MAX_LIVECRAWL_MS"])
        docs = int(num(e.inp.get("numResults")) or 10) * (1 + int(num(e.inp.get("subpages")) or 0))
        per = k["EXA_MAX_PAGE_CHARS"]
        if k["EXA_MAX_TOTAL_CHARS"]:
            per = min(per or k["EXA_MAX_TOTAL_CHARS"], k["EXA_MAX_TOTAL_CHARS"] // max(1, docs))
        e.cap("textMaxCharacters", per, floor=100)
    elif tool == "web_fetch_exa":
        n = url_count(e.inp.get("urls"))
        per = k["EXA_MAX_PAGE_CHARS"]
        if k["EXA_MAX_TOTAL_CHARS"]:
            per = min(per or k["EXA_MAX_TOTAL_CHARS"], k["EXA_MAX_TOTAL_CHARS"] // n)
        server_default = 3000
        if per and "maxCharacters" not in e.inp and per < server_default:
            e.inp["maxCharacters"] = max(100, per)
            e.notes.append("maxCharacters=%d (%d URLs)" % (e.inp["maxCharacters"], n))
        else:
            e.cap("maxCharacters", per, floor=100)


def jina(tool, e, k):
    if tool in ("search_web", "search_arxiv", "search_ssrn", "search_images", "search_jina_blog"):
        e.cap("num", k["JINA_MAX_RESULTS"], fill=k["JINA_MAX_RESULTS"] or None)
    elif tool == "read_url":
        e.cap("topk", k["JINA_MAX_TOPK"])
        e.cap("chunk_size", k["JINA_MAX_CHUNK_WORDS"])
    elif tool == "sort_by_relevance":
        e.cap("top_n", k["JINA_MAX_RERANK"], fill=k["JINA_MAX_RERANK"] or None)


def wait_idle(secs):
    return {"idle_network": {"timeout": {"secs": int(secs), "nanos": 0}}}


def spider(tool, e, k):
    hit = [f for f in REFUSED_SPIDER if e.inp.get(f) not in (None, False, "", {}, [])]
    if hit:
        e.deny = ("Spider %s is refused for agents (%s: recurring spend or data sent to a third-party "
                  "URL). Call again without it; run the crawl now and read its result."
                  % (", ".join(hit), tool))
        return
    antibot = truthy(k["SPIDER_ANTIBOT"])
    if not antibot:
        if e.inp.get("respect_robots") is False or str(e.inp.get("respect_robots")).lower() == "false":
            e.deny = "Spider respect_robots=false is refused: robots.txt is obeyed. Call again without it."
            return
        hit = ([tool] if tool in BYPASS_TOOLS else []) + \
              [f for f in BYPASS_OPTS if e.inp.get(f) not in (None, False, "", {}, [])] + \
              [f for f in ("proxy_enabled", "fingerprint") if e.inp.get(f) is True]
        if hit:
            e.deny = ("Spider call refused (%s in %s): no bot-protection bypass (stealth, CAPTCHA "
                      "solving, proxies, fingerprint or user-agent profiles, cookies). Follow "
                      "web-research's blocked-page steps: spider_scrape request=chrome, then jina/exa, "
                      "then browser-operator, else report the URL as blocked." % (", ".join(hit), tool))
            return
    if tool == "spider_crawl":
        n = url_count(e.inp.get("url"))
        top = k["SPIDER_MAX_PAGES"]
        per_site = max(1, top // n) if top else 0
        dflt = k["SPIDER_DEFAULT_PAGES"] or None
        e.cap("limit", per_site, fill=dflt)
        e.cap("depth", k["SPIDER_MAX_DEPTH"], fill=k["SPIDER_DEFAULT_DEPTH"] or None)
        e.cap("delay", k["SPIDER_MAX_DELAY_MS"], floor=0)
        lo = min(k["SPIDER_DELAY_MS"], k["SPIDER_MAX_DELAY_MS"] or k["SPIDER_DELAY_MS"])
        cur = num(e.inp.get("delay"))
        if not antibot and lo and (cur is None or cur < lo):
            e.inp["delay"] = lo
            e.notes.append("delay=%d" % lo if cur is None else "delay %s->%d" % (cur, lo))
        b = e.inp.get("budget")
        if isinstance(b, dict) and per_site:
            nb = {p: (min(v, per_site) if isinstance(num(v), (int, float)) and num(v) > 0 else
                      (per_site if num(v) == 0 else v)) for p, v in b.items()}
            if nb != b:
                e.inp["budget"] = nb
                e.notes.append("budget capped at %d pages" % per_site)
    elif tool == "spider_ai_crawl":
        e.cap("limit", k["SPIDER_MAX_PAGES"], fill=k["SPIDER_DEFAULT_PAGES"] or None)
    elif tool in ("spider_search", "spider_ai_search"):
        e.cap("num", k["SPIDER_MAX_RESULTS"], fill=k["SPIDER_MAX_RESULTS"] or None)
        if tool == "spider_search":
            e.cap("search_limit", k["SPIDER_MAX_RESULTS"], fill=k["SPIDER_MAX_RESULTS"] or None)
            if e.inp.get("limit") is not None:
                e.cap("limit", max(1, k["SPIDER_MAX_PAGES"] // max(1, k["SPIDER_MAX_RESULTS"] or 1))
                      if k["SPIDER_MAX_PAGES"] else 0)
    elif tool in ("spider_links", "spider_ai_links"):
        e.cap("limit", k["SPIDER_MAX_LINKS"], fill=k["SPIDER_MAX_LINKS"] or None)
    elif tool == "spider_browser_open":
        e.fill("browser", k["SPIDER_BROWSER"])
        st = k["SPIDER_BROWSER_STEALTH"]
        if "stealth" not in e.inp and 0 < st <= 3:
            e.fill("stealth", st)

    if tool in SPIDER_FORMAT_TOOLS:
        e.fill("return_format", k["SPIDER_RETURN_FORMAT"])
    if not antibot and tool in SPIDER_POOL_TOOLS:
        e.fill("respect_robots", True)
        e.cap("concurrency_limit", k["SPIDER_CONCURRENCY"], fill=k["SPIDER_CONCURRENCY"] or None)
    if tool in SPIDER_REQUEST_TOOLS:
        e.fill("request", k["SPIDER_REQUEST"])
    if not antibot:
        if tool in SPIDER_PAGE_TOOLS:
            e.fill("fingerprint", False)      # Spider's default is true
    elif tool in SPIDER_PAGE_TOOLS and k["SPIDER_FINGERPRINT"] != "":
        e.fill("fingerprint", truthy(k["SPIDER_FINGERPRINT"]))
    if antibot and tool in SPIDER_PROXY_TOOLS:
        want = True if tool == "spider_unblocker" else truthy(k["SPIDER_PROXY_ENABLED"])
        if want:
            e.fill("proxy_enabled", True)
        if tool in SPIDER_POOL_TOOLS and e.inp.get("proxy_enabled") is True:
            e.fill("proxy", k["SPIDER_PROXY"])
    if antibot and tool in SPIDER_PAGE_TOOLS:
        e.fill("country_code", k["SPIDER_COUNTRY_CODE"])
    if k["SPIDER_WAIT_IDLE_S"] and "wait_for" not in e.inp and (
            tool == "spider_unblocker" or (tool in SPIDER_REQUEST_TOOLS and e.inp.get("request") == "chrome"
                                          and tool in SPIDER_PAGE_TOOLS)):
        e.fill("wait_for", wait_idle(min(60, k["SPIDER_WAIT_IDLE_S"])))


SERVERS = {"exa": exa, "jina": jina, "spider": spider}


def decide(ev, knobs=None):
    """The hook output for one PreToolUse event, or None to leave the call alone."""
    if not isinstance(ev, dict) or ev.get("hook_event_name", "PreToolUse") != "PreToolUse":
        return None
    parts = str(ev.get("tool_name") or "").split("__", 2)
    if len(parts) != 3 or parts[0] != "mcp" or parts[1] not in SERVERS:
        return None
    inp = ev.get("tool_input")
    if not isinstance(inp, dict):
        return None
    e = Edit(inp)
    SERVERS[parts[1]](parts[2], e, knobs or read_knobs())
    if e.deny:
        return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                       "permissionDecisionReason": e.deny}}
    if not e.notes:
        return None
    return {"hookSpecificOutput": {
        "hookEventName": "PreToolUse", "updatedInput": e.inp,
        "additionalContext": "web caps (stack.env, hooks/web_caps.py) set: %s." % "; ".join(e.notes)}}


def self_test():
    k = {n: v[0] for n, v in KNOBS.items()}
    fails = []

    def run(tool, inp, knobs=None):
        out = decide({"hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": inp}, knobs or k)
        hso = (out or {}).get("hookSpecificOutput", {})
        return hso.get("updatedInput"), hso.get("permissionDecision")

    def check(name, cond):
        if not cond:
            fails.append(name)

    u, _ = run("mcp__exa__web_search_exa", {"query": "q", "numResults": 50})
    check("exa numResults clamp", u and u["numResults"] == 15)
    u, _ = run("mcp__exa__web_search_exa", {"query": "q", "numResults": 8})
    check("exa within cap untouched", u is None)
    u, _ = run("mcp__exa__web_fetch_exa", {"urls": ["a"] * 40})
    check("exa fetch total", u and u["maxCharacters"] == 2000)
    u, _ = run("mcp__exa__web_fetch_exa", {"urls": ["a"] * 41, "maxCharacters": 110})
    check("exa fetch small kept", u is None)
    u, _ = run("mcp__exa__web_fetch_exa", {"urls": "https://x", "maxCharacters": 50000})
    check("exa fetch per page", u and u["maxCharacters"] == 10000)
    u, _ = run("mcp__exa__web_search_advanced_exa", {"query": "q", "numResults": 20, "subpages": 9,
                                                     "textMaxCharacters": 9000})
    check("exa advanced", u and u["numResults"] == 15 and u["subpages"] == 3
          and u["textMaxCharacters"] == 80000 // 60)
    u, _ = run("mcp__jina__search_web", {"query": ["a", "b"]})
    check("jina num fill", u and u["num"] == 10)
    u, _ = run("mcp__jina__search_web", {"query": "a", "num": 5})
    check("jina num kept", u is None)
    u, _ = run("mcp__jina__read_url", {"url": "u", "question": "q", "topk": 50, "chunk_size": 4096})
    check("jina read caps", u and u["topk"] == 10 and u["chunk_size"] == 1000)
    u, _ = run("mcp__jina__sort_by_relevance", {"query": "q", "documents": ["d"] * 300})
    check("jina rerank fill", u and u["top_n"] == 20)
    u, _ = run("mcp__spider__spider_crawl", {"url": "https://a.example"})
    check("spider crawl defaults", u and u["limit"] == 25 and u["depth"] == 3
          and u["return_format"] == "markdown" and u["request"] == "smart" and u["fingerprint"] is True
          and "proxy_enabled" not in u and not {"respect_robots", "delay", "concurrency_limit"} & set(u))
    pol = dict(k, SPIDER_ANTIBOT="0")
    u, _ = run("mcp__spider__spider_crawl", {"url": "https://a.example"}, pol)
    check("spider polite defaults", u and u["fingerprint"] is False and u["respect_robots"] is True
          and u["delay"] == 1000 and u["concurrency_limit"] == 2)
    u, _ = run("mcp__spider__spider_crawl", {"url": "https://a.example", "delay": 100, "concurrency_limit": 50},
               pol)
    check("spider polite floor", u and u["delay"] == 1000 and u["concurrency_limit"] == 2)
    for inp in ({"respect_robots": False}, {"proxy_enabled": True}, {"fingerprint": True},
                {"user_agent": "x"}, {"cookies": "a=b"}, {"proxy": "residential"}, {"country_code": "us"}):
        _, d = run("mcp__spider__spider_scrape", dict(inp, url="https://a.example"), pol)
        check("spider polite refuses %s" % list(inp)[0], d == "deny")
    for tool in ("spider_unblocker", "spider_browser_open", "spider_ai_browser"):
        _, d = run("mcp__spider__" + tool, {"url": "https://a.example"}, pol)
        check("spider polite refuses " + tool, d == "deny")
    ab = k
    u, _ = run("mcp__spider__spider_crawl", {"url": "https://a.example,https://b.example", "limit": 0,
                                             "depth": 40, "budget": {"*": 500}})
    check("spider crawl multi-url", u and u["limit"] == 25 and u["depth"] == 10 and u["budget"]["*"] == 50)
    u, _ = run("mcp__spider__spider_crawl", {"url": "https://a.example", "limit": 400})
    check("spider crawl max", u and u["limit"] == 100)
    u, _ = run("mcp__spider__spider_unblocker", {"url": "https://a.example"}, ab)
    check("spider unblocker anti-bot", u and u["proxy_enabled"] is True and u["proxy"] == "residential"
          and u["wait_for"]["idle_network"]["timeout"]["secs"] == 5)
    u, _ = run("mcp__spider__spider_scrape", {"url": "https://a.example", "request": "chrome",
                                              "proxy_enabled": False})
    check("spider chrome wait, agent proxy kept", u and "wait_for" in u and u["proxy_enabled"] is False
          and "proxy" not in u and u["fingerprint"] is True)
    _, d = run("mcp__spider__spider_crawl", {"url": "https://a.example", "cron": "daily"})
    check("spider cron refused", d == "deny")
    u, _ = run("mcp__spider__spider_browser_open", {}, dict(ab, SPIDER_BROWSER_STEALTH=2))
    check("spider browser stealth", u and u["stealth"] == 2 and u["browser"] == "auto")
    u, _ = run("mcp__spider__spider_search", {"search": "q", "fetch_page_content": True})
    check("spider search fill", u and u["num"] == 10 and u["search_limit"] == 10)
    u, _ = run("mcp__spider__spider_get_credits", {})
    check("spider credits untouched", u is None)
    u, _ = run("mcp__exa__web_search_exa", {"query": "q", "numResults": 50}, dict(k, EXA_MAX_RESULTS=0))
    check("cap 0 = off", u is None)
    u, _ = run("mcp__other__web_search_exa", {"numResults": 50})
    check("other server untouched", u is None)
    if fails:
        print("web_caps self-test FAILED: " + ", ".join(fails))
        return 1
    print("web_caps self-test ok")
    return 0


def main(argv):
    if "--self-test" in argv:
        return self_test()
    if "--print" in argv:
        for name, val in read_knobs().items():
            print("%s=%s  # %s" % (name, val, KNOBS[name][1]))
        return 0
    try:
        out = decide(json.loads(sys.stdin.read() or "{}"))
    except Exception as exc:  # noqa: BLE001 - fail open: never block a call over a cap we can't compute
        sys.stderr.write("web_caps: not applied (%s: %s)\n" % (type(exc).__name__, exc))
        return 0
    if out:
        sys.stdout.write(json.dumps(out))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
