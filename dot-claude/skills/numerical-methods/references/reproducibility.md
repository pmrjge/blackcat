# Numerical methods — reproducibility and library choices (reference)
Read when seeding, GPU determinism, TF32 and BLAS-thread effects, or choosing NumPy/SciPy vs MLX vs PyTorch CUDA for a numerical task. Parent: `numerical-methods` SKILL.md (environments and the Sept 2026 version note are there).

## 10. Reproducibility
- Seeds:
  - `np.random.default_rng(seed)`: pass Generators around, with no global state.
  - `torch.manual_seed(seed)` (all devices), `mx.random.seed(seed)`, `random.seed`.
  - For DataLoader, use `worker_init_fn` plus a seeded `generator` (PyTorch reproducibility notes).
- GPU determinism:
  - `torch.use_deterministic_algorithms(True)` makes nondeterministic ops raise; `warn_only=True`
    surveys them first. Also set `torch.backends.cudnn.benchmark = False` and
    `torch.backends.cudnn.deterministic = True`.
  - Older PyTorch/CUDA stacks ask for `CUBLAS_WORKSPACE_CONFIG=:4096:8`; set it if the error says so.
  - On CUDA, atomic-add ops (`scatter_add`, `index_add`, many backward kernels) are nondeterministic.
    Some MPS ops raise under deterministic mode.
- TF32 silently changes fp32 convolutions on NVIDIA (cuDNN default), and matmuls once enabled: set
  `torch.backends.fp32_precision = "ieee"` for reference runs.
- BLAS threads change reduction order:
  - pin `OMP_NUM_THREADS`, `OPENBLAS_NUM_THREADS`, `MKL_NUM_THREADS` or `VECLIB_MAXIMUM_THREADS`
    (Accelerate), or use `threadpoolctl` (installed with scikit-learn);
  - record `np.show_config()`.
- Record versions, device, dtype, BLAS, threads and seeds. Across devices, specify tolerances;
  bitwise equality is not a realistic target.

## 11. Library choices
| need | CPU (sci venv) | Mac GPU (MLX) | NVIDIA (PyTorch CUDA) |
|---|---|---|---|
| float64 dense LA, references | NumPy/SciPy (LAPACK), mpmath | CPU only (NumPy, or MLX on `mx.cpu`) | `torch.linalg` in float64: correct but slow (consumer GPUs have little fp64 throughput) |
| sparse | `scipy.sparse` | — | `torch.sparse` (limited) |
| batched fp32/bf16 kernels | NumPy | `mlx.core`, `mx.compile` | `torch`, `torch.compile` |
| autodiff | — | `mx.grad` | `torch.func` |
| ODE/SDE | `solve_ivp`, hand-written SDE schemes | hand-written | torchdiffeq/torchsde (install per project) |
