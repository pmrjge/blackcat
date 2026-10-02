---
name: geo-crs-gdal
description: Load before reprojecting or converting geodata — CRS, datums, PROJ, GDAL/OGR command line, formats.
---
# Coordinate systems and GDAL/OGR

Baseline and versions: `geospatial`.

## CRS essentials
- Identify by authority code (`EPSG:3763` for Portugal PT-TM06/ETRS89, `EPSG:32629` UTM 29N, `EPSG:3857` Web Mercator, `EPSG:4326` WGS 84 geographic); store WKT2 or PROJJSON in outputs, not only proj strings.
- Datum transformations: ETRS89 ↔ WGS 84 differ by ~1 m and growing; old national datums (e.g. Lisboa/Datum 73) need grid-based transformations. Let PROJ choose the best available operation and check it: `projinfo -s EPSG:4274 -t EPSG:3763 --spatial-test intersects` lists candidates and accuracies; enable grids with `PROJ_NETWORK=ON` (downloads from the PROJ CDN — fine for public grids) or install `proj-data`.
- Web Mercator distorts area heavily: display only, never for measurements.
- Vertical datums (ellipsoidal vs orthometric heights, geoid models) matter for elevation work: state the vertical CRS (compound CRS like `EPSG:3763+5780`).
- Python: `pyproj.Transformer.from_crs(src, dst, always_xy=True)`; `pyproj.Geod(ellps="WGS84").inv(...)` for geodesic distance; pyproj 3.8.0 — Verified 2026-10-02 https://pypi.org/project/pyproj/

## GDAL/OGR command line (read-only first)
```bash
gdalinfo -stats -json in.tif | jq '.coordinateSystem.wkt, .size, .bands[].noDataValue'
ogrinfo -so -al in.gpkg                                   # layers, CRS, fields, extent
gdalsrsinfo -o wkt2_2019 EPSG:3763
```
Newer GDAL has the unified `gdal` CLI (`gdal raster info`, `gdal vector convert`, `gdal raster reproject`, pipelines); the classic tools below still work — check `gdal --help` on the installed version.

## Common operations
```bash
# reproject raster: choose resampling by data type (nearest/mode for categories, bilinear/cubic for continuous)
gdalwarp -t_srs EPSG:3763 -r bilinear -tr 10 10 -tap -co COMPRESS=DEFLATE -co TILED=YES in.tif out.tif
# make a Cloud-Optimized GeoTIFF
gdal_translate -of COG -co COMPRESS=DEFLATE -co PREDICTOR=2 in.tif out_cog.tif
# vector convert + reproject
ogr2ogr -f GPKG -t_srs EPSG:3763 -nln parcels out.gpkg in.shp
ogr2ogr -f Parquet out.parquet in.gpkg                    # GeoParquet (GDAL built with Arrow/Parquet)
# clip raster by polygon, keep nodata
gdalwarp -cutline aoi.gpkg -crop_to_cutline -dstnodata -9999 in.tif clip.tif
# SQL on vectors (SQLite dialect gives spatial functions)
ogr2ogr -dialect SQLite -sql "SELECT name, ST_Area(geom) AS a FROM parcels" out.csv in.gpkg
```
- VRTs (`gdalbuildvrt`) to mosaic without copying; `/vsicurl/`, `/vsis3/`, `/vsizip/` to read remote and zipped data in place (credentials from environment, never in commands that get logged).
- `GDAL_NUM_THREADS=ALL_CPUS`, `-wm` (warp memory) and `GDAL_CACHEMAX` for large rasters; `-multi` in gdalwarp.

## Formats
| need | format |
|---|---|
| vector exchange, multi-layer, editing | GeoPackage |
| vector analytics, cloud | GeoParquet |
| web/APIs, small data | GeoJSON (always lon/lat WGS 84 per RFC 7946) or FlatGeobuf for streaming |
| rasters | COG (GeoTIFF) |
| multidimensional (time, bands) | NetCDF/Zarr (`hpc-io`) |

## Pitfalls
Assigning a CRS (`-a_srs`) when you meant to reproject (`-t_srs`); bilinear resampling of categorical rasters; misaligned grids (use `-tap` and a common resolution); nodata lost in conversions; GeoJSON in a projected CRS; lat/lon swapped; datum shift ignored for survey-grade data.

## Verify
`gdalinfo`/`ogrinfo` on outputs show the intended CRS, extent, resolution and nodata · one control point compared before/after (within the expected transformation accuracy) · row/feature counts match inputs · COG validity (`gdalinfo` shows `LAYOUT=COG`, or `rio cogeo validate`).
