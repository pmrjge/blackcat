# Literature review: batch reference check (verify_refs.py)

Batch check (tested): flags title/first-author/year mismatches, failed lookups and `updated-by` notices.
```python
# verify_refs.py — run: uv run --with 'bibtexparser<2' python verify_refs.py refs.bib you@example.org
import json, re, sys, time, unicodedata, urllib.parse, urllib.request
import xml.etree.ElementTree as ET
import bibtexparser

def norm(s):
    s = unicodedata.normalize("NFKD", re.sub(r"[{}\\]", "", s or ""))
    return re.sub(r"[^a-z0-9]+", " ", s.encode("ascii", "ignore").decode().lower()).strip()

def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": f"verify-refs (mailto:{sys.argv[2]})"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()

ATOM = "{http://www.w3.org/2005/Atom}"
for e in bibtexparser.load(open(sys.argv[1], encoding="utf-8")).entries:
    key, title, year = e["ID"], norm(e.get("title")), e.get("year", "")
    first = norm(e.get("author", "").split(" and ")[0].split(",")[0])
    try:
        if "doi" in e:
            m = json.loads(get("https://api.crossref.org/works/" + urllib.parse.quote(e["doi"])))["message"]
            t, y = norm((m.get("title") or [""])[0]), str(m.get("issued", {}).get("date-parts", [[None]])[0][0])
            a = norm((m.get("author") or [{}])[0].get("family", ""))
            flags = [u.get("type") for u in m.get("updated-by", [])]
        elif "eprint" in e:
            ent = ET.fromstring(get("https://export.arxiv.org/api/query?id_list=" + e["eprint"])).find(ATOM + "entry")
            t, y = norm(ent.findtext(ATOM + "title")), ent.findtext(ATOM + "published")[:4]   # v1 year
            a = norm(ent.find(ATOM + "author").findtext(ATOM + "name").split()[-1])
            flags = []
            time.sleep(3)                                       # arXiv: 3 s between calls
        else:
            print(f"{key}: NO IDENTIFIER — resolve manually"); continue
    except Exception as exc:                                   # an unresolvable id is itself a finding
        print(f"{key}: LOOKUP FAILED ({exc})"); continue
    author_ok = bool(a and first) and (a in first or first in a)
    problems = [n for n, ok in (("title", t == title), ("first-author", author_ok), ("year", y == year)) if not ok]
    if flags: problems.append("UPDATED-BY:" + ",".join(flags))
    print(f"{key}: {'OK' if not problems else 'CHECK ' + ' '.join(problems)}")
```
Every `CHECK` needs a human look (a published version legitimately has a different year than v1; retracted
titles gain a "RETRACTED:" prefix); `LOOKUP FAILED` on a DOI usually means a fabricated or mistyped DOI.
