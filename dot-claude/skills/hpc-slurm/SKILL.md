---
name: hpc-slurm
description: Use before writing or submitting cluster jobs — SLURM scripts, arrays, GPUs, accounting, Spack.
---
# SLURM and cluster work

Cost and consent rules: `hpc-computing` — every `sbatch`/`srun`/`salloc` on a real cluster is a consent gate with a core-hour estimate.

## Version
- Slurm 26.05.4 is the latest tag; clusters run older releases, so check `sinfo --version` and the site docs — Verified 2026-10-02 https://github.com/SchedMD/slurm (tags)

## Read the cluster before writing a script (read-only, fine)
`sinfo -s` (partitions), `sinfo -o '%P %l %D %c %m %G'` (time limit, nodes, cores, memory, GRES), `scontrol show partition <p>`, `sacctmgr show assoc user=$USER format=account,partition,qos` (accounts you can charge), `squeue --me`, `sshare -U` (fair share), `module avail` / `module spider <name>`, the site's user guide (limits, scratch paths, GPU types, billing weights).

## Job script template
```bash
#!/bin/bash
#SBATCH --job-name=solver-strong-4n
#SBATCH --account=<account>            # charged; confirm with the user
#SBATCH --partition=<partition>
#SBATCH --nodes=4
#SBATCH --ntasks-per-node=8
#SBATCH --cpus-per-task=16             # OpenMP threads per rank
#SBATCH --mem=0                        # all node memory (or --mem-per-cpu)
#SBATCH --time=00:30:00                # tight: shorter jobs start sooner and cost less
#SBATCH --output=logs/%x-%j.out
#SBATCH --error=logs/%x-%j.err
set -euo pipefail
module purge
module load gcc/<ver> openmpi/<ver> hdf5/<ver>      # exact versions recorded
export OMP_NUM_THREADS=$SLURM_CPUS_PER_TASK OMP_PLACES=cores OMP_PROC_BIND=close
srun --cpu-bind=cores ./solver input.toml           # srun, not mpirun, unless the site says otherwise
```
- GPUs: `--gpus-per-node=<n>` or `--gres=gpu:<type>:<n>`, `--gpu-bind=closest` where supported; one rank per GPU is the common default.
- Cost estimate for the user: nodes × wall time × (cores or GPUs per node) × the site's billing weight; say it in the consent request.

## Patterns
- Job arrays for parameter sweeps: `--array=0-99%10` (max 10 concurrent), `$SLURM_ARRAY_TASK_ID` indexes a parameter file; one array instead of 100 jobs.
- Dependencies: `sbatch --dependency=afterok:<jobid> post.sh` for pipelines.
- Checkpoint/restart for jobs longer than the partition limit; `--signal=B:USR1@300` to get warning before the time limit and write a checkpoint.
- Interactive debugging: a short `salloc` on a debug partition (still a consent gate), not long interactive sessions holding nodes idle.
- Containers: Apptainer/Singularity (`apptainer exec --nv image.sif …`) where the site supports them; MPI inside containers must match the host MPI ABI.
- Workflow managers (Snakemake/Nextflow SLURM executors) submit many jobs: the consent covers the whole run with its estimated total.

## After a job
`sacct -j <id> --format=JobID,State,Elapsed,TotalCPU,MaxRSS,ReqMem,AllocTRES` (efficiency), `seff <id>` where installed; right-size the next request from MaxRSS and elapsed time. Report job IDs, state, elapsed, and core-hours used.

## Software environments
Site modules first; Spack (`spack env create`, `spack.yaml` + `spack.lock` committed) for custom stacks built against site compilers/MPI (external packages declared); pixi/conda only for user-level Python tooling, not for MPI-linked libraries.

## Pitfalls
Requesting whole nodes for serial work; `--mem` too high (longer queue) or too low (OOM kill — check `sacct` State=OUT_OF_MEMORY); writing many small files to the parallel file system; jobs running from `$HOME` with quota limits; forgetting `module purge`; `mpirun` inside SLURM with the wrong process manager; array jobs without a concurrency cap.

## Verify
Script passes `sbatch --test-only` (validates without submitting; check that the site allows it) · small test job succeeded before scale-up (with consent) · `sacct` efficiency reviewed · outputs copied off scratch · job IDs and core-hours reported.
