---
name: linux-workstation
description: Use for a Linux ML/dev workstation (CachyOS or Ubuntu, RTX 50 laptop) — NVIDIA driver, CUDA, PyTorch, desktop, btrfs.
---
# Linux ML workstation: CachyOS or Ubuntu, NVIDIA Blackwell laptop

Verified Sep 2026 against NVIDIA's 595 driver README, CUDA 13.4 release notes, CachyOS chwd profiles and wiki,
Arch/Ubuntu package archives and PyTorch's wheel indexes. Re-checked 2026-10-02: torch 2.14.1 is the latest on PyPI
(https://pypi.org/pypi/torch/json); the driver, CUDA, desktop and distro versions were not re-checked — unverified since Sep 2026.
Tags: **[CachyOS]** (also plain Arch unless noted), **[Ubuntu]** (24.04 LTS / 26.04 LTS), **[both]**.

## Scope and ground rules
- Covers the GPU stack, CUDA userland, containers, shell, session, packages, snapshots, firmware, backups, basic
  security, the Tailscale client, troubleshooting. Not here: kernels/perf tuning (`accelerator-perf`), services
  on a server (`self-hosting-ops`), git (`git-workflows`).
- Ask before installing/removing packages, touching boot entries, kernel parameters, firewall or sshd.
  [CachyOS] take a snapshot first. Never partially upgrade Arch. Never pipe an unread script into a shell.

## Modules (load the one the task touches)
| Module | Load for |
|---|---|
| `linux-nvidia-cuda` | open NVIDIA driver, CUDA toolkit, PyTorch wheels, hybrid graphics and power, suspend, GPU containers, GPU troubleshooting |
| `linux-desktop-btrfs` | fish shell, Wayland, fonts and input, btrfs snapshots and rollback |

## Packages
- **[CachyOS]** Full upgrades only: `sudo pacman -Syu` or `paru` (never `pacman -Sy <pkg>`). Read news first:
  `paru -Pw` (Arch news) and CachyOS announcements. Reboot after kernel or nvidia updates.
  AUR (paru and yay are in the CachyOS repos): read the PKGBUILD diff before every build; prefer repo packages,
  Flatpak or upstream releases for security-sensitive software. Housekeeping: `pacman -Qdtq` (orphans; review
  before removing), `paccache -rk2` and `pacdiff` (pacman-contrib) for cache and `.pacnew` files.
- **[Ubuntu]** `sudo apt update && sudo apt full-upgrade`; `unattended-upgrades` applies security updates;
  `apt policy <pkg>` shows where a package comes from; keep PPAs to a minimum.
- **[both]** Flatpak for desktop apps (`flatpak install flathub <id>`, `flatpak update`,
  `flatpak info --show-permissions <id>`). Python: uv only; never `sudo pip`.

## Firmware, backups, security, Tailscale
- Firmware **[both]**: `fwupdmgr refresh && fwupdmgr get-updates && fwupdmgr update` (`fwupd-refresh.timer`
  keeps metadata fresh). On AC power, after a snapshot, after reading the release notes.
- Backups **[both]**: back up `/home` minus caches (`~/.cache`, venvs, model caches are re-downloadable),
  `/etc`, and package lists (`pacman -Qqe` / `apt-mark showmanual`). restic 0.19 / borg 1.4 commands, timers,
  retention and restore drills are in `ops-backups`.
- Firewall: check `sudo ufw status verbose` (or `firewall-cmd --state`). Baseline:
  `sudo ufw default deny incoming && sudo ufw default allow outgoing && sudo ufw allow in on tailscale0 && sudo ufw enable`.
  Ports published by Docker bypass ufw: bind them to `127.0.0.1`.
- SSH: keys only (`ssh-keygen -t ed25519 -a 100`); if sshd runs, drop-in `/etc/ssh/sshd_config.d/10-hardening.conf`
  with `PasswordAuthentication no`, `KbdInteractiveAuthentication no`, `PermitRootLogin no`; `sudo sshd -t`
  before restarting. A laptop rarely needs sshd at all.
- Updates: Ubuntu keeps unattended security updates on; CachyOS gets a manual full upgrade weekly
  (snapshot, news, upgrade, reboot).
- Tailscale **[CachyOS]** `sudo pacman -S tailscale && sudo systemctl enable --now tailscaled`; **[Ubuntu]** the
  official apt repo (its install script sets it up; read it first). Then `sudo tailscale up`,
  `sudo tailscale set --operator=$USER`, `tailscale status`, `tailscale ping <host>`, `tailscale netcheck`.
  Exit node: `tailscale set --exit-node=<host> --exit-node-allow-lan-access`; stop: `tailscale set --exit-node=`.

## Verify
- `systemctl --failed` is empty; `journalctl -b -p err` has nothing new; a snapshot exists from before the change;
  the last backup succeeded. Plus the Verify block of every module used.

## Report
Distro, kernel, driver version and flavour (open), CUDA toolkit (if any), torch version/CUDA/arch list; what
changed (packages, files with paths, kernel parameters); snapshot IDs taken; checks run with results; pending
user actions (reboot, MOK enrollment, firmware setting).
