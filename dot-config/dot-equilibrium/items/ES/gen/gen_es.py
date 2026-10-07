# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy>=1.26"]
# ///
"""ES pool generator: estimation items whose true values are World Development Indicators (WDI) values for 2019,
read from the World Bank API v2 on 2026-10-04 (files in ../oracle/sources/, one per indicator, `ISO3<TAB>value`
exactly as quoted in the API JSON).

  uv run gen_es.py            # writes ../manifest.jsonl, ../oracle/truth.jsonl

Deterministic: country selection uses numpy default_rng(SEED_SELECT) with SEED_SELECT = 20261004 ^ sha256("es|select")[:8]
(the COMPARE_eq §8.4 formula); segment order uses default_rng(3725927731) (`eq|items`), items processed in id order.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import numpy as np

GEN = Path(__file__).resolve().parent
ES = GEN.parent
SRC = ES / "oracle" / "sources"
YEAR = 2019
ACCESSED = "2026-10-04"
SEED_ITEMS = 3725927731
SEED_SELECT = 20261004 ^ int(hashlib.sha256(b"es|select").hexdigest()[:8], 16)
PER_INDICATOR = 15
ALLOWED_TOOLS = ["Read"]

NAMES = {
    "ARG": "Argentina", "AUS": "Australia", "AUT": "Austria", "BEL": "Belgium", "BRA": "Brazil", "CAN": "Canada",
    "CHE": "Switzerland", "CHL": "Chile", "COL": "Colombia", "CZE": "Czechia", "DEU": "Germany", "DNK": "Denmark",
    "EGY": "Egypt", "ESP": "Spain", "FIN": "Finland", "FRA": "France", "GBR": "the United Kingdom", "GRC": "Greece",
    "HUN": "Hungary", "IDN": "Indonesia", "IND": "India", "IRL": "Ireland", "ITA": "Italy", "JPN": "Japan",
    "KEN": "Kenya", "KOR": "South Korea", "MAR": "Morocco", "MEX": "Mexico", "MYS": "Malaysia", "NGA": "Nigeria",
    "NLD": "the Netherlands", "NOR": "Norway", "NZL": "New Zealand", "PAK": "Pakistan", "PER": "Peru",
    "PHL": "the Philippines", "POL": "Poland", "PRT": "Portugal", "ROU": "Romania", "SWE": "Sweden",
    "THA": "Thailand", "TUR": "Türkiye", "USA": "the United States", "VNM": "Vietnam", "ZAF": "South Africa",
}

# target indicator -> (short name, definition template, unit, companion indicator, companion label, companion unit)
TARGETS = {
    "IS.RRS.TOTL.KM": ("rail network length",
                       "the total route length of the railway network of {c} in {y}", "km (route-km)",
                       "IS.RRS.PASG.KM", "rail passenger traffic", "million passenger-km"),
    "IS.AIR.PSGR": ("air passengers carried",
                    "the number of passengers carried in {y} by air carriers registered in {c} (domestic and "
                    "international flights of those carriers, wherever they fly)", "passengers",
                    "IS.AIR.DPRT", "flight departures of carriers registered in the country", "departures"),
    "IS.SHP.GOOD.TU": ("container port traffic",
                       "the container traffic handled by the ports of {c} in {y} (loaded and unloaded, including "
                       "transshipment and empty containers)", "TEU (twenty-foot equivalent units)",
                       "TX.VAL.MRCH.CD.WT", "merchandise exports", "current US$"),
    "AG.PRD.CREL.MT": ("cereal production",
                       "the total cereal production of {c} in {y} (wheat, rice, maize, barley, oats, rye, millet, "
                       "sorghum, buckwheat and mixed grains, harvested for dry grain)", "metric tons",
                       "AG.LND.ARBL.HA", "arable land", "hectares"),
    "AG.LND.FRST.K2": ("forest area",
                       "the forest area of {c} in {y} (land spanning more than 0.5 ha with trees taller than 5 m "
                       "and canopy cover above 10 %, excluding agricultural and urban land use)", "km²",
                       "AG.LND.AGRI.ZS", "agricultural land", "% of land area"),
    "IP.PAT.RESD": ("resident patent applications",
                    "the number of patent applications filed in {y} by residents of {c} at their national (or "
                    "competent regional) patent office", "applications",
                    "GB.XPD.RSDV.GD.ZS", "R&D expenditure", "% of GDP"),
    "IP.JRN.ARTC.SC": ("scientific and technical journal articles",
                       "the number of scientific and technical journal articles credited to {c} in {y} (indexed "
                       "articles in the natural sciences, medicine, engineering and technology, counted "
                       "fractionally by the countries of the authors' institutions)", "articles",
                       "GB.XPD.RSDV.GD.ZS", "R&D expenditure", "% of GDP"),
    "AG.CON.FERT.ZS": ("fertilizer use per hectare",
                       "the fertilizer consumption of {c} in {y}, nitrogen, phosphate and potash nutrients per "
                       "hectare of arable land", "kg per hectare of arable land",
                       "AG.YLD.CREL.KG", "cereal yield", "kg per hectare"),
    "IS.AIR.GOOD.MT.K1": ("air freight carried",
                          "the air freight carried in {y} by air carriers registered in {c}", "million tonne-km",
                          "IS.AIR.DPRT", "flight departures of carriers registered in the country", "departures"),
    "SH.TBS.INCD": ("tuberculosis incidence",
                    "the estimated incidence of tuberculosis in {c} in {y} (new and relapse cases, all forms)",
                    "cases per 100,000 people",
                    "SP.DYN.LE00.IN", "life expectancy at birth", "years"),
    "SP.DYN.IMRT.IN": ("infant mortality",
                       "the infant mortality rate of {c} in {y} (deaths before age one)", "per 1,000 live births",
                       "SP.DYN.LE00.IN", "life expectancy at birth", "years"),
    "EN.ATM.PM25.MC.M3": ("PM2.5 exposure",
                          "the population-weighted mean annual exposure to ambient fine particulate matter (PM2.5) "
                          "in {c} in {y}", "micrograms per cubic metre",
                          "SP.URB.TOTL.IN.ZS", "urban population", "% of total population"),
}
DEV = [("IS.RRS.TOTL.KM", 0), ("SH.TBS.INCD", 1), ("AG.PRD.CREL.MT", 2)]  # (indicator, index into leftovers)

BASICS = ("SP.POP.TOTL", "AG.LND.TOTL.K2", "NY.GDP.PCAP.CD")


def load(code):
    path = SRC / f"{code}_{YEAR}.tsv"
    vals, meta = {}, ""
    for line in path.read_text().splitlines():
        if line.startswith("#"):
            meta = line
            continue
        iso, q = line.split("\t")
        vals[iso] = q
    return vals, meta


def fmt(x: float, unit: str = "") -> str:
    """3 significant figures; large numbers in words."""
    def sig(v):
        if v == 0:
            return "0"
        d = 3 - int(math.floor(math.log10(abs(v)))) - 1
        r = round(v, d)
        if d <= 0:
            return f"{int(r):,}"
        return f"{r:.{d}f}"
    if unit == "current US$":
        if x >= 1e9:
            return f"{sig(x / 1e9)} billion US$"
        return f"{sig(x / 1e6)} million US$"
    if abs(x) >= 1e9:
        s = f"{sig(x / 1e9)} billion"
    elif abs(x) >= 1e6:
        s = f"{sig(x / 1e6)} million"
    else:
        s = sig(x)
    return f"{s} {unit}".strip()


def api_url(iso, code):
    return f"https://api.worldbank.org/v2/country/{iso}/indicator/{code}?date={YEAR}&format=json"


def main():
    data = {}
    metas = {}
    codes = set(TARGETS) | {t[3] for t in TARGETS.values()} | set(BASICS)
    for code in sorted(codes):
        data[code], metas[code] = load(code)
    pop, area, gdp = (data[c] for c in BASICS)
    rng_sel = np.random.default_rng(SEED_SELECT)
    plan = []  # (indicator, iso, dev)
    for code in TARGETS:  # dict order is fixed
        comp = TARGETS[code][3]
        elig = sorted(iso for iso in data[code] if iso in data[comp] and float(data[code][iso]) > 0
                      and iso in pop and iso in gdp and iso in area)
        perm = [elig[int(i)] for i in rng_sel.permutation(len(elig))]
        chosen, left = perm[:PER_INDICATOR], perm[PER_INDICATOR:]
        plan += [(code, iso, False) for iso in sorted(chosen)]
        for dcode, k in DEV:
            if dcode == code:
                plan.append((code, left[k], True))
    pool = [p for p in plan if not p[2]]
    dev = [p for p in plan if p[2]]
    ids = {}
    for i, p in enumerate(pool):
        ids[p] = f"ES-{i + 1:04d}"
    for i, p in enumerate(dev):
        ids[p] = f"ES-DEV{i + 1}"

    def dist(a, b):
        return math.hypot(math.log(float(pop[a]) / float(pop[b])), math.log(float(gdp[a]) / float(gdp[b])))

    rng_seg = np.random.default_rng(SEED_ITEMS)
    manifest, truth = [], []
    for p in sorted(ids, key=lambda q: ids[q]):
        code, iso, is_dev = p
        iid = ids[p]
        short, deftpl, unit, comp, comp_label, comp_unit = TARGETS[code]
        vals = data[code]
        cands = sorted((dist(iso, r), r) for r in vals if r != iso and float(vals[r]) > 0 and r in pop and r in gdp)
        r1 = next(r for _, r in cands if r in data[comp])
        r2 = next(r for _, r in cands if r != r1)
        c = NAMES[iso]
        quantity = deftpl.format(c=c, y=YEAR)
        segs = []
        segs.append(("basics", f"Data block ({c}, {YEAR}): population {fmt(float(pop[iso]))}; land area "
                               f"{fmt(float(area[iso]), 'km²')}; GDP per capita {fmt(float(gdp[iso]), 'US$')} (current)."))
        for tag, r in (("ref1", r1), ("ref2", r2)):
            segs.append((tag, f"Reference country ({NAMES[r]}, {YEAR}): {short} {fmt(float(vals[r]), unit)}; "
                              f"population {fmt(float(pop[r]))}; GDP per capita {fmt(float(gdp[r]), 'US$')}."))
        segs.append(("companion", f"Related data ({YEAR}): {comp_label} — {c}: "
                                  f"{fmt(float(data[comp][iso]), comp_unit)}; {NAMES[r1]}: "
                                  f"{fmt(float(data[comp][r1]), comp_unit)}."))
        perm = rng_seg.permutation(len(segs))
        segments = [{"id": segs[int(k)][0], "text": segs[int(k)][1]} for k in perm]
        decisive = int(np.where(perm == 3)[0][0])  # the companion block (data-first clue), by design
        prompt = (f"ES item {iid}. Estimate {quantity}, in {unit}.\n\n"
                  f"Closed book: use only the data blocks below and what you already know; no web access. Data "
                  f"blocks are rounded to 3 significant figures and may be shown in any order. Return in `answer` "
                  f"one positive number in {unit} (a point estimate, not a range; plain number, no units or "
                  f"thousands separators). Scoring is by |ln(estimate / true value)|.")
        manifest.append({
            "id": iid, "class": "ES", "dev": is_dev, "answer_kind": "numeric", "prompt": prompt,
            "segments": segments, "decisive_segment": decisive, "fixture": None, "public_check": None,
            "allowed_tools": ALLOWED_TOOLS,
        })
        truth.append({
            "id": iid, "indicator": code, "iso3": iso, "country": c, "year": YEAR, "unit": unit,
            "true_value": float(vals[iso]), "quoted": vals[iso],
            "source_url": api_url(iso, code), "source_publisher": "World Bank, World Development Indicators (API v2)",
            "fetched_url_batch": f"https://api.worldbank.org/v2/country/<45 ISO3 codes>/indicator/{code}?date={YEAR}&format=json&per_page=100",
            "source_lastupdated": metas[code].split("lastupdated=")[1].split()[0], "accessed": ACCESSED,
            "clue_sources": {"basics": [api_url(iso, b) for b in BASICS],
                             "ref1": [api_url(r1, code), api_url(r1, "SP.POP.TOTL"), api_url(r1, "NY.GDP.PCAP.CD")],
                             "ref2": [api_url(r2, code), api_url(r2, "SP.POP.TOTL"), api_url(r2, "NY.GDP.PCAP.CD")],
                             "companion": [api_url(iso, comp), api_url(r1, comp)]},
            "segment_perm": [int(k) for k in perm],
        })
    with (ES / "manifest.jsonl").open("w") as f:
        for m in manifest:
            f.write(json.dumps(m, ensure_ascii=False) + "\n")
    (ES / "oracle").mkdir(exist_ok=True)
    with (ES / "oracle" / "truth.jsonl").open("w") as f:
        for t in truth:
            f.write(json.dumps(t, ensure_ascii=False) + "\n")
    print(f"ES: {len(pool)} pool items + {len(dev)} dev items; SEED_SELECT={SEED_SELECT}")


if __name__ == "__main__":
    main()
