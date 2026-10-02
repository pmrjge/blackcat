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

## Hybrid graphics and power
- Keep hybrid mode (PRIME render offload): the desktop runs on the iGPU, the dGPU sleeps (runtime D3). CUDA
  needs no offload variables; it always uses the NVIDIA GPU.
- Offload a graphics app: `prime-run <app>` (nvidia-prime; it sets `__NV_PRIME_RENDER_OFFLOAD=1`
  `__VK_LAYER_NV_optimus=NVIDIA_only` `__GLX_VENDOR_LIBRARY_NAME=nvidia`), or the desktop's "Launch using
  dedicated GPU" (switcheroo-control; CLI `switcherooctl list`, `switcherooctl launch -g <id> <cmd>`).
- RTD3 is on by default for Ampere+ notebooks (`NVreg_DynamicPowerManagement=0x03`, fine-grained). Check idle
  state: `cat /sys/bus/pci/devices/<addr>/power/runtime_status` (`suspended`; address from `lspci -D -d 10de::`)
  or `/proc/driver/nvidia/gpus/<addr>/power`.
- The dGPU stays awake while: something holds `/dev/nvidia*` (`sudo fuser -v /dev/nvidia*`), a monitor is on a
  dGPU-wired port (often HDMI), nvidia-persistenced runs with persistence, or a status bar polls `nvidia-smi`
  (it wakes the GPU; read sysfs instead).
- `nvidia-powerd` (Dynamic Boost) is enabled by chwd on non-Turing laptops: `systemctl status nvidia-powerd`.
- A dGPU-only/MUX mode comes from the firmware setup or the vendor's tool. EnvyControl was archived in May 2026.

## Suspend and hibernate
- **[CachyOS]** With 595+ open modules, nvidia-utils sets `NVreg_UseKernelSuspendNotifiers=1` and
  `NVreg_TemporaryFilePath=/var/tmp` (`/usr/lib/modprobe.d/nvidia-utils.conf`); the nvidia-suspend/-resume/
  -hibernate services are unnecessary and the package disables them on upgrade. Don't re-enable them.
- **[Ubuntu]** See which mechanism is active: `grep -E 'UseKernelSuspendNotifiers|PreserveVideoMemoryAllocations|TemporaryFilePath' /proc/driver/nvidia/params`
  and `systemctl is-enabled nvidia-suspend nvidia-resume nvidia-hibernate`.
- **[both]** `cat /sys/power/mem_sleep`: NVIDIA documents resume failures with `s2idle` on some systems; the
  workaround is the kernel parameter `mem_sleep_default=deep` where firmware offers `deep`. The temporary file
  path must not be tmpfs (VRAM is saved there). Hibernation also needs swap that holds the memory image and a
  `resume=` kernel parameter.
- Evidence: `journalctl -b -1 -k | grep -iE 'nvrm|nvidia|PM:'` after a failed resume.

## GPUs in containers
- Install the NVIDIA Container Toolkit. **[CachyOS]** `sudo pacman -S nvidia-container-toolkit`. **[Ubuntu]**:
  ```bash
  curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
  curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
  sudo apt update && sudo apt install nvidia-container-toolkit
  ```
- Docker **[both]**: `sudo nvidia-ctk runtime configure --runtime=docker && sudo systemctl restart docker`;
  test `docker run --rm --gpus all nvidia/cuda:13.0.0-base-ubuntu24.04 nvidia-smi`. Rootless Docker: configure
  `--config=$HOME/.config/docker/daemon.json` and `no-cgroups` as the toolkit docs describe.
- Podman uses CDI. **[Ubuntu]** toolkit >= 1.18 ships `nvidia-cdi-refresh` (path + service) that rewrites
  `/var/run/cdi/nvidia.yaml` on driver changes. **[CachyOS]** the package has no such unit; its pacman hook
  regenerates `/etc/cdi/nvidia.yaml` when nvidia-utils or the toolkit is installed or upgraded (by hand:
  `sudo nvidia-ctk cdi generate --output=/etc/cdi/nvidia.yaml`). Test:
  `podman run --rm --device nvidia.com/gpu=all --security-opt=label=disable ubuntu nvidia-smi -L`; `nvidia-ctk cdi list`.
- The image's CUDA must be <= the host driver's CUDA version.


## Troubleshooting
| Symptom | Check | Fix |
|---|---|---|
| `nvidia-smi`: couldn't communicate with the driver | `lsmod \| grep nvidia`, `dkms status`, `journalctl -b -k \| grep -i nvrm`, `mokutil --sb-state` | install the kernel's matching module package / rebuild DKMS; Secure Boot + unsigned DKMS: enroll the MOK or use Ubuntu's signed modules |
| `Failed to initialize NVML: Driver/library version mismatch` | `/proc/driver/nvidia/version` vs `pacman -Q nvidia-utils` / `dpkg -l \| grep nvidia-utils` | reboot (old module still loaded) |
| GPU unusable after install, license shows `NVIDIA` | `modinfo -F license nvidia` | proprietary module on Blackwell: switch to the open flavour |
| Black screen after an update | TTY (Ctrl+Alt+F3), `journalctl -b -1 -p err`, boot the previous kernel or a snapshot; `systemd.unit=multi-user.target` for a console | reinstall matching modules, rebuild the initramfs (**[CachyOS]** `sudo mkinitcpio -P`, **[Ubuntu]** `sudo update-initramfs -u`), or roll back |
| nouveau/nova bound instead | `lspci -nnk -d 10de::` | driver packages blacklist them; rebuild the initramfs |
| Battery drain, dGPU never sleeps | `runtime_status`, `fuser -v /dev/nvidia*` | stop the holder, stop polling nvidia-smi |
| Freeze or black screen on resume | `journalctl -b -1 -k`, `/sys/power/mem_sleep` | suspend section above |
| PyTorch "no kernel image is available" / sm_120 unsupported | `torch.version.cuda`, `get_arch_list()` | cu130/cu132 wheels |
| Container: "could not select device driver" | runtime configured? CDI spec current? | `nvidia-ctk runtime configure`, regenerate CDI |
| Wayland session falls back or fails | `nvidia_drm` modeset, `egl-wayland` installed | fix KMS, reinstall egl-wayland |

## Verify
- The driver/CUDA checks, the torch smoke test and a container `nvidia-smi` all pass.
- Idle dGPU reaches `suspended`; one suspend/resume cycle works.
