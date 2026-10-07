---
name: linux-nvidia-cuda
description: Use for NVIDIA on Linux — driver, CUDA, PyTorch wheels, hybrid graphics, GPU containers.
---
# NVIDIA driver, CUDA and PyTorch on the Linux laptop

Part of `linux-workstation` (ground rules: ask before package or boot changes; [CachyOS] snapshot first; the version
note and the [CachyOS]/[Ubuntu]/[both] tags are explained there). PyTorch index config on both OSes: `py-uv-packaging`.

## The facts that drive every choice (RTX 5070 Ti Laptop GPU, 12 GB)
| Item | Value |
|---|---|
| Architecture | Blackwell, compute capability 12.0 (`sm_120`) |
| Kernel modules | **open modules only**: NVIDIA states the proprietary modules are unsupported on Blackwell |
| Driver | >= R570. Sep 2026: production branch 595 (595.104.02), feature branches 610/615; Arch/CachyOS ship 615.x |
| CUDA toolkit | >= 12.8 for sm_120. Matching driver branch: 13.0 R580, 13.2 R595, 13.3 R610, 13.4 R615; 13.x binaries run on >= R580 via minor-version compatibility (not PTX JIT of newer PTX) |
| PyTorch | 2.14 (2026-09-02). Linux PyPI wheel = CUDA 13.0 build (pins CUDA 13.0.3 libs). Indexes for 2.14: cu126 (no sm_120: unusable here), cu130, cu132 |

```bash
lspci -nnk -d 10de::                     # GPU and "Kernel driver in use"
cat /proc/driver/nvidia/version          # loaded module version
modinfo -F license nvidia                # "Dual MIT/GPL" = open modules; "NVIDIA" = proprietary
nvidia-smi --query-gpu=name,driver_version,compute_cap,memory.total --format=csv
nvidia-smi | head -4                     # "CUDA Version" = highest CUDA the driver supports
```

## Install the driver
**[CachyOS]** chwd (CachyOS Hardware Detection) owns this:
1. `chwd --list` (profiles for this machine), `chwd --list-installed`; `sudo chwd -a` autoconfigures.
2. On a laptop it selects `nvidia-open-dkms.prime`: nvidia-utils, lib32-nvidia-utils, egl-wayland, nvidia-settings,
   opencl-nvidia, libva-nvidia-driver, vulkan-icd-loader, nvidia-prime, switcheroo-control, plus prebuilt
   `<kernel>-nvidia-open` for every installed linux-cachyos* kernel (fallback `nvidia-open-dkms`). It enables
   `nvidia-powerd` and `switcheroo-control` and adds the nvidia modules to the initramfs
   (`/etc/mkinitcpio.conf.d/10-chwd.conf`). A pacman hook rebuilds the initramfs.
3. Every kernel you boot needs its matching `-nvidia-open` package (keep `linux-cachyos-lts` + its module as fallback).
4. Skip the `--ai_sdk` profile: it installs system-wide cuda, cudnn, nccl, PyTorch, TensorFlow and enables an
   ollama service. Projects use their own uv environments.

**[Ubuntu]**
1. `sudo ubuntu-drivers list`; packages advertise when the `-open` variant is preferred (Blackwell needs it).
2. `sudo ubuntu-drivers install` (recommended branch) or pin: `sudo ubuntu-drivers install nvidia:595-open`.
   It installs prebuilt, signed modules (Secure Boot works); `--include-dkms` allows DKMS builds (needs MOK enrollment).
3. Newer branches than the archive has: `ppa:graphics-drivers/ppa` (community-tested). Never mix Ubuntu driver
   packages with NVIDIA's `.run` installer or the `cuda`/`cuda-drivers` metapackages from NVIDIA's repo.

**[both]** Reboot, then run the checks above.

## CUDA toolkit (only to compile: nvcc, custom kernels, source builds)
PyTorch/JAX wheels bundle their CUDA runtime; they need only the driver.
- **[CachyOS]** `sudo pacman -S cuda` -> `/opt/cuda` (13.4 in Sep 2026, matching the 615 driver). PATH comes from
  `/etc/profile.d/cuda.sh` and fish's `vendor_conf.d/cuda.fish`: open a new shell.
- **[Ubuntu]** NVIDIA's repo (`ubuntu2404`; `ubuntu2604` carries only 13.3+):
  ```bash
  wget https://developer.download.nvidia.com/compute/cuda/repos/ubuntu2404/x86_64/cuda-keyring_1.1-1_all.deb
  sudo dpkg -i cuda-keyring_1.1-1_all.deb && sudo apt update
  sudo apt install cuda-toolkit-13-2          # toolkit only; pick <= the driver's CUDA Version
  ```
  Then PATH: `/usr/local/cuda-13.2/bin` (fish: `fish_add_path -g /usr/local/cuda-13.2/bin`).
- Compile real SASS for this GPU so nothing JITs: `nvcc -gencode arch=compute_120,code=sm_120 ...`;
  PyTorch extensions: `TORCH_CUDA_ARCH_LIST="12.0"`.

## PyTorch with uv
```toml
# pyproject.toml: CUDA wheels on Linux, PyPI (CPU/MPS) wheels on the Mac
[[tool.uv.index]]
name = "pytorch-cu130"
url = "https://download.pytorch.org/whl/cu130"
explicit = true

[tool.uv.sources]
torch = [{ index = "pytorch-cu130", marker = "sys_platform == 'linux'" }]
```
- cu130 and cu132 both run on driver >= 580 (minor-version compatibility; cu132's matching branch is R595). One-off installs: `uv pip install torch --torch-backend=auto`
  (reads the driver; `uv pip` only, not `uv add`).
- torchvision/torchaudio/xformers/flash-attn/bitsandbytes/vLLM must match the exact torch + CUDA build; install
  them from the same index or their wheels for that torch version.
- Smoke test (expect `(12, 0)` and `sm_120` in the arch list):
  ```bash
  uv run python -c "import torch as t; print(t.__version__, t.version.cuda, t.cuda.is_available(), t.cuda.get_device_name(0), t.cuda.get_device_capability(0), t.cuda.get_arch_list())"
  ```

## Hybrid graphics, power, suspend
Read `references/power-suspend.md` when the laptop's graphics mode, power draw or suspend/hibernate misbehaves (PRIME offload, runtime D3, NVreg suspend options).

## GPUs in containers
Read `references/containers.md` when a container needs the GPU (NVIDIA Container Toolkit, CDI, Docker/Podman).

## Troubleshooting
Read `references/troubleshooting.md` when `nvidia-smi` fails or the GPU misbehaves (symptom → check → fix table).

## Verify
- The driver/CUDA checks, the torch smoke test and a container `nvidia-smi` all pass.
- Idle dGPU reaches `suspended`; one suspend/resume cycle works.
