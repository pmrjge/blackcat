---
name: geospatial
description: Load before geospatial work — coordinate systems, GDAL/OGR, vector and raster analysis, PostGIS, tiles and web maps; the module map.
---
# Geospatial (hub)

## Scope
Spatial data processing, analysis and map publishing. Databases: `postgresql` (PostGIS) and `dataframes-duckdb` (DuckDB spatial); plots: `data-visualization`; front ends: `frontend-frameworks`.

## Modules
| module | load when |
|---|---|
| `geo-crs-gdal` | CRS, datums, reprojection, PROJ, GDAL/OGR command line, format conversion |
| `geo-raster-vector` | GeoPandas/Shapely, rasterio/rioxarray, overlays, zonal stats, STAC, PostGIS/DuckDB queries |
| `geo-tiles-webmaps` | vector/raster tiles, PMTiles, MapLibre, tile servers, styles, web map performance |

## Versions
- GDAL 3.13.3 — Verified 2026-10-02 https://github.com/OSGeo/gdal/releases/latest
- PROJ 9.9.0 — Verified 2026-10-02 https://github.com/OSGeo/PROJ/releases/latest
- QGIS 4.2.3 is the newest tag (QGIS 4 is Qt6-based; plugins written for 3.x may need porting) — Verified 2026-10-02 https://github.com/qgis/QGIS (tags)

## Baseline rules
- Every dataset has a known CRS; "unknown" is a bug to fix before analysis, not a default to assume.
- Measure distances and areas in an appropriate projected CRS (local UTM or an equal-area projection) or geodesically — never in degrees.
- Axis order: EPSG:4326 is latitude/longitude by authority definition, but most software and GeoJSON use longitude/latitude; use `always_xy=True` in pyproj and check one known point after every transform.
- Topology and validity: fix invalid geometries (`make_valid`) before overlays; report how many were invalid.
- Prefer cloud-native formats: GeoParquet for vectors, Cloud-Optimized GeoTIFF (COG) for rasters, PMTiles for tiles, Zarr for multidimensional arrays; Shapefile only for legacy exchange (10-character field names, 2 GB limit).
- Licenses and attribution travel with the data (OpenStreetMap is ODbL: attribution and share-alike for derived databases); tile and API usage policies respected (no bulk downloading from the public OSM tile servers).
- Location data about people is personal data: aggregate or anonymize before sharing, keep raw traces local.
- MCP: gis-mcp is available in the magg catalog (mounted on request; Shapely/PyProj/GeoPandas/rasterio operations). Local scripts with the libraries below are usually simpler.

## Verify
CRS printed for every input and output · a known point or landmark checked after reprojection · geometry validity counts reported · areas/distances cross-checked geodesically for a sample · outputs open in a second tool (`ogrinfo`/`gdalinfo`, QGIS) · data sources, licenses and versions reported.
