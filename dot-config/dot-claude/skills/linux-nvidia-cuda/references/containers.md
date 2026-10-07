# GPUs in containers

Part of `linux-nvidia-cuda`.

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
