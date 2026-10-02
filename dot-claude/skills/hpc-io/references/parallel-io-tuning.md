# Parallel I/O tuning

1. **Measure**: time I/O phases separately; Darshan (if the site loads it) gives per-job I/O characterization — number of files, operations, sizes, time per rank. Look for: many small writes, many files, metadata operations (open/stat) dominating, rank imbalance.
2. **Aggregate**: collective buffering (MPI-IO hints `cb_nodes`, `cb_buffer_size`; `romio_cb_write=enable`) so a few aggregators write large contiguous blocks; ADIOS2 aggregation (`NumAggregators`) or HDF5 subfiling where available.
3. **Align**: Lustre stripe size and HDF5 alignment (`H5Pset_alignment(fapl, threshold, stripe_size)`); chunk sizes multiples of the stripe size.
4. **Reduce metadata**: open files once per run (not per timestep), write many timesteps into one file, avoid `ls`-heavy post-processing on directories with millions of files; HDF5 `H5Pset_libver_bounds` with latest format and `H5Pset_coll_metadata_write` for collective metadata.
5. **Asynchronous / staged I/O**: ADIOS2 asynchronous engines or SST staging for in-situ analysis; HDF5 async VOL where installed; dedicate I/O ranks or threads so compute continues.
6. **Write less**: output only what analysis needs, at the needed frequency and precision (float32 for visualization outputs, lossy compression like ZFP/SZ only with an error bound agreed with the user).
7. **Burst buffers / node-local NVMe**: write locally, drain to the parallel file system asynchronously — if the site provides them.

Report before/after I/O time and the configuration (stripe settings, hints, aggregator counts).
