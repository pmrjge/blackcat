---
name: geo-raster-vector
description: Load before spatial analysis in code — GeoPandas, Shapely, rasterio, rioxarray, STAC, PostGIS.
---
# Vector and raster analysis

Baseline: `geospatial`; CRS and GDAL: `geo-crs-gdal`; SQL engines: `postgresql`, `dataframes-duckdb`.

## Libraries
- GeoPandas 1.2.0, Shapely 2.1.2 (vectorized GEOS) — Verified 2026-10-02 https://github.com/geopandas/geopandas/releases/latest https://github.com/shapely/shapely/releases/latest
- rasterio 1.5.2, rioxarray 0.23.0 — Verified 2026-10-02 https://github.com/rasterio/rasterio/releases/latest https://pypi.org/project/rioxarray/
- pystac 1.15.2 (+ pystac-client for STAC APIs) — Verified 2026-10-02 https://pypi.org/project/pystac/
- PostGIS 3.6.4 — Verified 2026-10-02 https://github.com/postgis/postgis (tags); DuckDB 1.5.6 with the `spatial` extension — Verified 2026-10-02 https://pypi.org/project/duckdb/
- Install in a uv project (`uv add geopandas pyogrio rasterio`); wheels bundle GDAL/PROJ — check `pyogrio.__gdal_version__` and `rasterio.__gdal_version__` match your needs.

## Vector rules
- Read/write with the pyogrio engine (`gpd.read_file(path, engine="pyogrio")`, `columns=`, `bbox=`, `where=` to read less); GeoParquet with `to_parquet`/`read_parquet`.
- Reproject before measuring: `gdf.to_crs(gdf.estimate_utm_crs())` for local metric work.
- Validity: `gdf.geometry.is_valid.sum()`, `make_valid`; consistent geometry types after overlays (`explode`, filter by `geom_type`).
- Spatial joins with the right predicate (`intersects`, `within`, `contains`, `dwithin` in metric CRS); nearest joins with `sjoin_nearest(max_distance=…)`; spatial index used implicitly — check sizes of results for duplicates (one-to-many matches).
- Overlay (`gpd.overlay`) for intersections/unions of polygons; `dissolve` for aggregation; areas apportioned by intersection share when attributes are extensive (population), not for intensive ones (density).
- Large data: DuckDB spatial (`INSTALL spatial; LOAD spatial; SELECT … FROM ST_Read('in.gpkg')`, GeoParquet natively) or PostGIS with GiST indexes; `dask-geopandas` for partitioned work.

## Raster rules
- Windowed reads (`src.read(1, window=…)`, block iteration) and overviews for large rasters; `masked=True` to honor nodata.
- rioxarray for labelled arrays: `rxr.open_rasterio(path, chunks=True)`, `.rio.reproject`, `.rio.clip(geoms, crs)`; time stacks with xarray.
- Align rasters before arithmetic (same CRS, resolution, grid origin): `rio.reproject_match`.
- Zonal statistics: `rasterstats`/`exactextract` (fractional pixel coverage, better for small polygons); state the method.
- Data types: keep scale factors and offsets; compute indices (NDVI) in float with nodata handling; write outputs as COG with nodata set.

## Remote sensing data
- Search via STAC (`pystac_client.Client.open(<catalog>).search(collections=…, bbox=…, datetime=…, query={"eo:cloud_cover": {"lt": 20}})`), read COGs in place; `odc-stac`/`stackstac` to build xarray cubes.
- Cloud masks (scene classification layers), surface reflectance vs top-of-atmosphere, and radiometric scaling read from the product docs.
- Public catalogs (Earth Search, Microsoft Planetary Computer, Copernicus Data Space) have their own access rules and keys; credentials from the user's store.

## PostGIS essentials
`geometry(Polygon, 3763)` typed columns; GiST index on geometry; `ST_DWithin` with a metric CRS (or `geography`) for radius searches; `ST_Subdivide` big polygons before joins; `EXPLAIN ANALYZE` to confirm index use (`postgresql`).

## Pitfalls
Joins in geographic CRS with distance thresholds in degrees; duplicated rows from one-to-many joins; mixing nodata with valid zeros; misaligned raster grids; area-weighting intensive attributes; reading whole continental rasters into memory.

## Verify
Feature/pixel counts and CRS reported before and after each step · validity and duplicate checks · a result checked by hand on one feature (area, join, zonal value) · maps of inputs and outputs rendered and Read.
