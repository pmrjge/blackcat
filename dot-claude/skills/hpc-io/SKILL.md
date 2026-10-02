---
name: hpc-io
description: Load for scientific data I/O — HDF5, NetCDF, ADIOS2, Zarr, chunking, collective parallel writes, checkpoints, Lustre striping.
---
# Scientific data and parallel I/O

Baseline: `hpc-computing`. Tabular analytics files (Parquet/Arrow): `dataframes-duckdb`.

## Versions
- HDF5 2.2.0 (2.x is a new major series: read its release notes before moving 1.14 code) — Verified 2026-10-02 https://github.com/HDFGroup/hdf5/releases/latest
- netCDF-C 4.10.1 — Verified 2026-10-02 https://github.com/Unidata/netcdf-c/releases/latest
- Use the site's parallel HDF5/NetCDF builds on clusters (built against its MPI); h5py/netCDF4 wheels are serial.

## Choosing a format
| data | format |
|---|---|
| structured arrays + metadata, general scientific output | HDF5 (h5py, HDF5 C/Fortran) |
| gridded geoscience/climate data with CF conventions | NetCDF-4 (on HDF5) with CF metadata; xarray for analysis |
| very high-throughput simulation output, staging, in-situ | ADIOS2 (BP5 engine) |
| cloud/object storage, chunked arrays for parallel analysis | Zarr (v3) via xarray/zarr-python |
| meshes and fields for visualization | XDMF + HDF5, VTK/VTU (PVTU for parallel), ADIOS2 VTX |
| small configs and metadata | TOML/YAML/JSON, never the bulk data |

## Rules
- Self-describing output: units, coordinate variables, provenance (code version, commit, input hash, date) as attributes in every file.
- Chunking matches the read pattern (time-series reads → chunk along time; slice reads → chunk the slice); chunk sizes ~1–10 MB; compression (zlib/zstd/Blosc via filters) only after checking read performance; shuffle filter with numeric data.
- Parallel writes: collective I/O (`H5Pset_dxpl_mpio(..., H5FD_MPIO_COLLECTIVE)`, NetCDF `nc_var_par_access(..., NC_COLLECTIVE)`) to one shared file, or one file per node/aggregator with an index — never one file per rank at large scale (metadata storms).
- Lustre/GPFS: set stripe count and size for large shared files (`lfs setstripe -c <n> -S 4M dir/`) per the site's guidance; many small files are the most common cause of slow I/O and angry admins.
- Checkpoints: write to a temporary name, flush, then rename atomically; keep the last two; checkpoint frequency from the failure rate and write cost (Young/Daly: interval ≈ √(2 × write time × MTBF)).
- Read-modify-write of big datasets → write new versions, keep old until verified.
- Python: `h5py` with `with h5py.File(...) as f:`; `xarray.open_dataset(..., chunks={})` (dask) for out-of-core analysis; netCDF4/h5netcdf engines.

## Inspect and validate
`h5dump -H file.h5` (headers only), `h5ls -rv`, `h5stat`, `ncdump -h file.nc`, `cfchecks` (CF compliance), `bpls` (ADIOS2), xarray `ds.info()`; compare outputs with `h5diff` (with `--relative` tolerance) or `nccmp`.

Read `references/parallel-io-tuning.md` when I/O dominates run time or the file system is struggling.

## Pitfalls
Rank 0 gathering everything and writing serially; one file per rank per timestep; chunking that forces reading whole datasets for a slice; missing units and coordinates; HDF5 file locking on network file systems (`HDF5_USE_FILE_LOCKING=FALSE` only when the site documents it); writing to scratch without copying results off.

## Verify
Files open in a second tool (h5dump/ncdump/xarray) with expected shapes, units and attributes · round-trip test (write → read → compare) · CF check for NetCDF meant for sharing · I/O time measured as a fraction of total for production runs · output locations reported.
