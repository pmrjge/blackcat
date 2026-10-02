---
name: bio-single-cell
description: Use for single-cell analysis — scanpy/AnnData, Seurat, QC, integration, annotation, pseudobulk.
---
# Single-cell analysis

Data rules and baseline: `bio-chem-computing`. Statistics (differential expression design, multiple testing): `data-analysis`.

## Versions
- scanpy 1.12.4, anndata 0.13.4 — Verified 2026-10-02 https://github.com/scverse/scanpy/releases/latest https://github.com/scverse/anndata/releases/latest
- Seurat 5.5.1 — Verified 2026-10-02 https://github.com/satijalab/seurat/releases/latest
- Python side in a uv project (`uv add scanpy anndata`) or pixi when compiled dependencies need conda-forge; R side with renv.

## Standard workflow (scRNA-seq)
1. **Counts**: Cell Ranger / STARsolo / alevin-fry / simpleaf output; keep raw and filtered matrices; record chemistry and reference.
2. **Ambient RNA and empty droplets**: CellBender or SoupX on raw matrices when ambient contamination matters.
3. **QC per sample**: counts, genes per cell, % mitochondrial (and ribosomal/hemoglobin); thresholds from the distributions per sample (MAD-based), not copied numbers; doublet detection (scDblFinder, scrublet) per sample before merging.
4. **Normalization**: `sc.pp.normalize_total` + `log1p` (or Pearson residuals / SCTransform); keep raw counts in a layer (`adata.layers["counts"]`).
5. **Features and reduction**: highly variable genes (batch-aware: `batch_key`), PCA; neighbors graph; UMAP for display only — never quantify distances on UMAP.
6. **Integration** across batches/samples when needed: scVI/scANVI, Harmony, or Seurat integration; check with metrics (scib-metrics) that biology is kept and batch removed.
7. **Clustering**: Leiden at several resolutions; stability checked; clusters are hypotheses.
8. **Annotation**: marker genes (`sc.tl.rank_genes_groups`) plus reference-based tools (CellTypist, Azimuth, scANVI label transfer); annotations reviewed against known markers.
9. **Differential expression between conditions**: pseudobulk per sample (sum counts per sample × cell type, then DESeq2/edgeR) — never cell-level Wilcoxon p-values treating cells as replicates.

## AnnData rules
- `X` content documented (raw counts, normalized, scaled?); raw counts preserved in `layers`; `obs` for cell metadata, `var` for genes (Ensembl IDs as index, symbols as a column).
- Large data: backed mode (`sc.read_h5ad(path, backed="r")`), sparse matrices kept sparse, `adata.copy()` only when needed; Dask-backed arrays for out-of-core.
- Write `.h5ad` (or zarr) with provenance in `uns`.
- Seurat interop through `.h5ad` conversion tools (zellkonverter, sceasy) with checks that counts and metadata survived.

## Multimodal and spatial
CITE-seq (muon/MuData, totalVI), multiome ATAC+RNA (ArchR, Signac, SnapATAC2, muon), spatial (squidpy, spatialdata) — load the specific tool's docs; same QC discipline per modality.

## Pitfalls
Filtering with fixed thresholds across very different samples; doublets merged into "intermediate" clusters; integrating away real condition effects; overinterpreting UMAP; cell-level DE p-values; gene symbol vs ID mismatches; normalized data fed to tools expecting counts (scVI, DESeq2).

## Verify
Per-sample QC plots reviewed and thresholds stated · cell counts after each filter reported · integration metrics recorded · markers support each annotated cell type · pseudobulk design used for condition comparisons · versions and references recorded.
