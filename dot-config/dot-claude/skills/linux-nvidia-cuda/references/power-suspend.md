# Hybrid graphics, power, suspend and hibernate

Part of `linux-nvidia-cuda`.

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
