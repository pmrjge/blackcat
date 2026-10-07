# ES pool: estimation with sourced true values (2026-10-04, built by mathematician)

**Counts:** 180 pool items (ES-0001..ES-0180) + 3 dev items (ES-DEV1..3). 12 indicators x 15 countries in the pool; the dev items
add one more country each to rail, cereals and TB. All values are for the year 2019.

**True values:** World Bank, World Development Indicators, API v2 (`https://api.worldbank.org/v2/country/<ISO3>/indicator/<CODE>?date=2019&format=json`),
dataset `lastupdated` 2026-07-13, accessed 2026-10-04. Per item `oracle/truth.jsonl` holds the source URL, the value
quoted exactly as in the API JSON, unit, year, access date and the URLs of every clue value. Raw values per indicator:
`oracle/sources/<CODE>_2019.tsv` (one batch request of 45 countries per indicator, read through the jina reader;
Bash egress to api.worldbank.org is blocked in this sandbox, so values were transcribed from the returned JSON).
Indicators: rail route-km, air passengers of national carriers, container port TEU, cereal production, forest area,
resident patent applications, S&T journal articles, fertilizer kg/ha, air freight t-km, TB incidence, infant mortality,
PM2.5 exposure. Excluded as definitionally ambiguous: tourist arrivals (same-day visitors mixed in), listed companies.

**Item:** prompt = the quantity in plain words (definition paraphrased, no database named) + unit; 4 segments
(data blocks, 3 significant figures): `basics` (population, land area, GDP per capita), `ref1`/`ref2` (the indicator for
the two countries nearest in (log population, log GDP per capita) that report it), `companion` (a related indicator
for the country and ref1, e.g. departures for air passengers, arable land for cereals). `decisive_segment` = the
companion block (author's design choice, not measured). Closed book: `allowed_tools` = ["Read"] (no Bash, so no web).

**Determinism:** `gen/gen_es.py` (uv PEP 723). Country choice per indicator: eligible countries (value > 0, companion
present) permuted by `numpy.random.default_rng(2502605934)` (= 20261004 ^ sha256("es|select")[:8]), first 15 to the
pool, leftovers 0/1/2 to the dev items. Segment order: one `default_rng(3725927731)` (`eq|items`) over items in id order.

**Oracle:** `uv run oracle.py --item ES-0001 --answer out.json` -> `{"item","score","detail"}` with score
e = |ln(estimate/true)|, or `"inf"` for a non-positive, non-finite, non-numeric or missing estimate; exit 2 on malformed
input. `selftest.sh`: per dev item, true x 1.05 scores within ln 1.1; x10, /10 score >= ln 2; negative, zero, string,
missing score inf; malformed exits 2 (24/24 PASS).

**Checks done:** 20 randomly drawn true values re-fetched one by one from the single-country URL: 20/20 identical
(`oracle/sources/SPOTCHECK.tsv`). Ratio sanity bounds across indicators (forest/land, passengers/departures,
production/arable land, ...) flagged only genuine outliers (CAN/KOR rail, EGY/KEN/MAR ports, EGY TB/IMR), no digit
slips. The other 163 true values are unverified beyond these bounds.

**Known weaknesses:** WDI values get revised (the access date pins them; a re-fetch later may differ). TB incidence,
infant mortality and PM2.5 are modelled estimates (WHO, UN IGME, GBD-type models): "true" means "as published".
Some values may be memorised by models (large countries); the same country recurs across indicators. Reference
countries are chosen mechanically and can be misleading outliers (e.g. Nigeria's 1.84 Mt-km air freight). Air
traffic counts carriers by registration (Ireland, Hungary are large), which the prompt states but arms may miss.
Clues come from the same source family, so an arm that has memorised WDI is advantaged in every arm equally.
