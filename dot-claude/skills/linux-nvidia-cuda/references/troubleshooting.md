# Troubleshooting

Part of `linux-nvidia-cuda`.

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
