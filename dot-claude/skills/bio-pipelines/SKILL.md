---
name: bio-pipelines
description: Use for bioinformatics workflows — Nextflow/nf-core, Snakemake, containers, pixi.
---
# Bioinformatics workflows

Data rules and baseline: `bio-chem-computing`. Cluster submission and cost consent: `hpc-slurm`. Containers: `container-images`.

## Versions
- Nextflow 26.04.6 — Verified 2026-10-02 https://github.com/nextflow-io/nextflow/releases/latest
- nf-core/tools 4.1.0 — Verified 2026-10-02 https://github.com/nf-core/tools/releases/latest
- Snakemake 9.27.0 (executors are plugins since 8.x: `snakemake-executor-plugin-slurm` etc.) — Verified 2026-10-02 https://github.com/snakemake/snakemake/releases/latest
- pixi 0.81.0 — Verified 2026-10-02 https://github.com/prefix-dev/pixi/releases/latest

## Choosing
- An nf-core pipeline exists for the analysis (rnaseq, sarek, scrnaseq, …) → run it with a pinned release (`-r <version>`) and a params file; don't rewrite it.
- New pipeline, team on Nextflow, cloud/HPC portability → Nextflow DSL2 with nf-core modules.
- Python-centric lab, file-based rules → Snakemake.
- One-off analysis of a few steps → a script with a Makefile/justfile is fine; promote to a workflow when it repeats.

## Nextflow rules
- DSL2 modules, one process per tool, `container`/`conda` directives per process; `nextflow.config` profiles (`test`, `docker`, `singularity`/`apptainer`, `slurm`) and resource labels (`process_low`, …).
- Pin the pipeline (`-r`), Nextflow version (`NXF_VER`), and container tags (digests for production).
- `-resume` with a persistent `work/` directory; `-with-report -with-trace -with-timeline` for resource tuning; clean `work/` only after results are verified and the user agrees (it deletes intermediate results).
- Params in a YAML/JSON file (`-params-file`), validated by the pipeline's schema (nf-schema plugin).
- Testing: nf-test (`nf-test test`) with snapshot assertions; `nextflow run . -profile test,docker` on tiny data.
- Executors: local for tests; `slurm`/`awsbatch`/`google-batch` for scale — submitting them spends the user's allocation or money, so consent with an estimate first.

## Snakemake rules
- Rules with explicit `input`/`output`/`log`/`benchmark`; wildcards constrained; `conda:` or `container:` per rule; config in `config.yaml` validated with a JSON schema.
- `snakemake -n` (dry run) and `--dag | dot -Tsvg` before running; `--use-conda`/`--software-deployment-method conda apptainer`; profiles for cluster settings.
- Tests: `snakemake --generate-unit-tests` scaffolding, small test data in the repo.

## Environments
- pixi workspace: `pixi init`, `pixi add -c bioconda samtools=1.24`, `pixi run <task>`; lock file committed; platforms listed (`osx-arm64`, `linux-64`) — tools missing on osx-arm64 run in linux-64 containers.
- Containers from BioContainers/quay.io (`quay.io/biocontainers/<tool>:<version>--<build>`) or Seqera Containers; never `latest`.
- Python analysis steps in uv projects (`uv run`) or the pipeline's own environment.

## Data handling
- Inputs described by a samplesheet (CSV) with validated columns; checksums (`md5sum`) for raw data; raw data read-only.
- Outputs organized per sample and step with a MultiQC report at the end.
- Big references (genome FASTA, indexes) downloaded once to a shared cache (iGenomes or a local refs directory) with versions recorded.

## Pitfalls
Unpinned pipeline revisions; mixing genome builds between steps; running on full data first; `work/` on a small home quota; samplesheet typos silently dropping samples; containers pulled as `latest`; deleting `work/` before checking outputs.

## Verify
Test profile run green · nf-test/Snakemake tests pass · MultiQC report reviewed (sample counts, QC metrics within expectations) · versions file (`software_versions.yml` or equivalent) archived with results.
