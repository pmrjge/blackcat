---
name: geo-tiles-webmaps
description: Load before publishing web maps — vector/raster tiles, PMTiles, MapLibre, tile servers, styles.
---
# Tiles and web maps

Baseline: `geospatial`. Front-end code: `frontend-frameworks`, `typescript-engineering`; hosting: `self-hosting-ops`.

## Tools
- MapLibre GL JS 6.11.2 (open-source WebGL vector map renderer) — Verified 2026-10-02 https://github.com/maplibre/maplibre-gl-js/releases/latest
- tippecanoe 2.79.0 (vector tiles from GeoJSON/FlatGeobuf/CSV, maintained by Felt) — Verified 2026-10-02 https://github.com/felt/tippecanoe/releases/latest
- Martin 1.16.1 (tile server for PostGIS, MBTiles, PMTiles, COG) — Verified 2026-10-02 https://github.com/maplibre/martin/releases/latest
- PMTiles (single-file tile archives over HTTP range requests; `pmtiles` CLI, JS/Python readers) — https://github.com/protomaps/PMTiles (versions per component; check the CLI's `pmtiles version`)
- deck.gl, OpenLayers and Leaflet as alternatives (WebGL overlays, full GIS client, simple raster maps).

## Choosing a delivery
| situation | delivery |
|---|---|
| static dataset, any size | PMTiles on object storage/CDN + MapLibre (no server) |
| frequently changing data in PostGIS | Martin serving `ST_AsMVT` tiles directly from tables/functions |
| raster imagery | COG served via TiTiler or pre-rendered raster tiles in PMTiles |
| basemap | a hosted provider with its terms and key, or a self-hosted Protomaps/OpenMapTiles basemap build |
| small overlay (< few MB) | GeoJSON source directly in MapLibre |

## Vector tile rules
- Tiles are in Web Mercator (EPSG:3857) with z/x/y; input for tippecanoe in WGS 84 lon/lat.
- Choose zoom range per layer (`-Z`/`-z`), simplification and dropping strategy (`--drop-densest-as-needed`, `--coalesce-densest-as-needed`, `--extend-zooms-if-still-dropping`); keep tile size under ~500 KB (tippecanoe warns) and attribute sets minimal per zoom.
- `tippecanoe -o out.pmtiles -zg --drop-densest-as-needed -l parcels parcels.fgb` then inspect with `pmtiles show` / the PMTiles viewer.
- Feature IDs stable (`--use-attribute-for-id`) for feature-state styling and interaction.

## MapLibre rules
- Style spec JSON versioned in the repo; sources (`vector`, `raster`, `geojson`, `pmtiles://` via the pmtiles protocol plugin), layers with data-driven expressions; glyphs and sprites hosted with the style.
- Attribution control always shows data and basemap attributions (OSM's "© OpenStreetMap contributors").
- Performance: fewer, larger layers; filter in the source/tiles rather than with many style filters; `promoteId` for feature state; avoid huge GeoJSON sources (tile them); test on a mid-range phone.
- Accessibility: maps need a text alternative (list/table of the data) and keyboard-reachable controls (`web-accessibility`).

## Hosting and cost
- PMTiles on S3-compatible storage needs CORS allowing `Range` headers and a CDN in front; check egress cost with the user before publishing large tile sets.
- Publishing to a public bucket or domain is externally visible: the user's consent first.
- API keys for commercial basemaps are public in the browser: restrict them by referrer on the provider side; never ship unrestricted keys.

## Pitfalls
Tiles missing features at low zooms (dropping without telling users); oversized tiles; mismatched source-layer names between tiles and style; CORS/range failures for PMTiles; GeoJSON coordinates in a projected CRS; missing attribution; using public OSM tile servers for production traffic.

## Verify
Tile stats checked (`pmtiles show`, tippecanoe summary: max tile size, dropped features) · map loads in a headless browser with no console errors and screenshots Read at several zooms · attribution visible · served files return 206 for range requests with CORS headers.
