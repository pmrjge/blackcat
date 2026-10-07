# Platform notes: Apple silicon, MLX, PyTorch

PyTorch/CUDA and MLX extras claims below: unverified (checked when written, Sep 2026); latest on PyPI torch 2.14.1, mlx 0.32.3 (Verified 2026-10-02 https://pypi.org/pypi/torch/json, https://pypi.org/pypi/mlx/json).

- Apple Silicon: uv-managed Pythons are native arm64 — check with `uv run python -c "import platform; print(platform.processor())"` (`arm`; `i386` means Rosetta). A missing arm64 wheel falls back to building the sdist (needs Xcode command-line tools, may fail) — prefer a version that ships wheels.
- MLX: `uv add mlx mlx-lm` on macOS ≥ 14 with Apple silicon. On Linux: `mlx[cuda12]` (driver ≥ 550.54.14, GPU ≥ SM 7.5, glibc ≥ 2.35), `mlx[cuda13]` (driver ≥ 580) or `mlx[cpu]`. Gate platform-specific deps with markers: `"mlx>=0.30; sys_platform == 'darwin'"`.
- PyTorch: PyPI's macOS arm64 wheels have no CUDA but include the MPS backend (`torch.backends.mps.is_available()`); PyPI's Linux wheels target CUDA 13.0 (since PyTorch 2.11) and need a driver that supports it. RTX 50-series (Blackwell, sm_120) needs CUDA ≥ 12.8 builds; CUDA 13.0 builds need driver ≥ 580 — the cu128 index stops at torch 2.11, so upgrade an older driver rather than pinning cu128; confirm `sm_120` in `torch.cuda.get_arch_list()`. Index only Linux, fall back to PyPI on macOS:
```toml
[tool.uv.sources]
torch = [{ index = "pytorch-cu130", marker = "sys_platform == 'linux'" }]
[[tool.uv.index]]
name = "pytorch-cu130"
url = "https://download.pytorch.org/whl/cu130"
explicit = true            # only packages pinned to this index use it
```
- `--torch-backend=auto` (GPU autodetection) exists only in the `uv pip` interface. Driver/CUDA/PyTorch matching on the Linux laptop is covered in `linux-workstation`.
