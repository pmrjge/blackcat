---
name: linux-desktop-btrfs
description: Use for the Linux desktop — fish shell, Wayland, fonts, input, btrfs snapshots.
---
# Linux desktop: fish, Wayland, fonts, snapshots

Part of `linux-workstation` (ground rules; [CachyOS]/[Ubuntu]/[both] tags). NVIDIA on Wayland and suspend: `linux-nvidia-cuda`.

## fish shell (CachyOS default)
- Order: conf.d snippets (`~/.config/fish/conf.d/*.fish` plus system/vendor ones) load first, then `config.fish`.
  CachyOS's `~/.config/fish/config.fish` starts with `source /usr/share/cachyos-fish-config/cachyos-config.fish`
  (fastfetch greeting, aliases, `fish_add_path ~/.local/bin ~/.cargo/bin`); override those after that line; put
  independent settings in `~/.config/fish/conf.d/50-<topic>.fish`. Don't edit files under `/usr/share`.
- PATH: `fish_add_path -g <dir>` in config files (global scope; silently skips missing dirs; tested on fish 4.8).
  Without `-g` it writes the universal `fish_user_paths` into `fish_variables`: hidden state, avoid in config.
- `set -gx VAR value`, `set -e VAR`; `VAR=1 cmd` and `export VAR=1` work; `$(...)`, `&&`, `||` work (fish >= 3.4).
  No heredocs or `$((...))`: run such snippets with `bash -c '...'` or save them as a bash script with a shebang.
- `abbr -a gs git status`; subcommand-only: `abbr -a --command git co checkout`. Functions live in
  `~/.config/fish/functions/<name>.fish` (autoloaded; `funcsave <name>`). Interactive-only code goes in
  `if status is-interactive ... end`.
- Tool hooks: `direnv hook fish | source`, `zoxide init fish | source`, `starship init fish | source`,
  `eval (ssh-agent -c)`, venv `source .venv/bin/activate.fish` (or just `uv run`).
- Homebrew on Linux is optional (prefix `/home/linuxbrew/.linuxbrew`; needs base-devel/build-essential):
  fish `/home/linuxbrew/.linuxbrew/bin/brew shellenv fish | source`, bash `eval "$(/home/linuxbrew/.linuxbrew/bin/brew shellenv)"`.
  shellenv moves brew's bin to the front of PATH, so brew's python/gcc/openssl then shadow the system ones:
  use brew only for tools the distro lacks, and never for toolchains that build CUDA code.
- Automation for agents: bash scripts with `#!/usr/bin/env bash`; never assume the login shell is POSIX.

## Wayland, fonts, input
- GNOME 50 (Ubuntu 26.04) has no X11 session; KDE Plasma 6.8 (autumn 2026) drops its X11 session (6.7's X11
  session supported into early 2027). X11 apps run under XWayland.
- NVIDIA on Wayland needs DRM KMS (`cat /sys/module/nvidia_drm/parameters/modeset` -> `Y`; default in current drivers)
  and `egl-wayland`. Screen sharing/recording goes through xdg-desktop-portal + PipeWire (install the DE's portal
  backend); global hotkeys and xdotool-style input injection don't work under Wayland.
- Chromium/Electron apps blurry or on XWayland: start with `--ozone-platform-hint=auto` or use the app's
  Wayland setting.
- Fonts: user fonts in `~/.local/share/fonts/`, then `fc-cache -f`; check `fc-list | grep -i <family>` and
  `fc-match "<family>:style=Bold"`. Noto: **[CachyOS]** `noto-fonts noto-fonts-cjk noto-fonts-emoji`,
  **[Ubuntu]** `fonts-noto-core fonts-noto-cjk fonts-noto-color-emoji`. Copy commercial fonts only as their
  desktop license allows (often per seat/device).
- Keyboard layout: the DE's settings on Wayland (not `setxkbmap`); console/system default via `localectl`.
  Input methods: fcitx5 (in KDE Wayland select it as the virtual keyboard). Wacom tablets work through the
  kernel driver + libwacom (KDE: Drawing Tablet settings; GNOME: Wacom settings); other brands may need
  OpenTabletDriver (follow its docs for udev rules).

## btrfs snapshots and rollback
- **[CachyOS]** btrfs layout with separate subvolumes for `/`, `/home`, `/root`, `/srv`, `/var/cache`, `/var/log`,
  `/var/tmp`: a root snapshot does not roll back home or logs. See what is installed:
  `pacman -Q snapper snap-pac btrfs-assistant limine-snapper-sync grub-btrfs-support cachyos-snapper-support`.
  - `sudo snapper list`; before risky changes `sudo snapper create --type single --description "before <change>"`;
    diff/undo files: `snapper status N..M`, `snapper undochange N..M <path>`. snap-pac wraps pacman transactions
    in pre/post snapshots; `snapper-cleanup.timer` prunes.
  - Boot a snapshot: Limine + `limine-snapper-sync.service`, or GRUB + `grub-btrfs-support` (`grub-btrfsd`).
    Restore per the CachyOS wiki: Limine offers a restore prompt after booting the snapshot; with GRUB, boot it
    and restore with Btrfs Assistant.
  - Monthly scrub: `sudo systemctl enable --now btrfs-scrub@-.timer`; errors: `sudo btrfs device stats /`.
- **[Ubuntu]** ext4 by default: Timeshift (rsync mode, universe) for system snapshots.
- Snapshots live on the same disk: they are not backups.

## Verify
- `fish -n <file>` on edited fish files and a new shell starts without errors; `fc-match` resolves the intended fonts.
- [CachyOS] `sudo snapper list` shows a snapshot from before the change; `btrfs device stats /` shows no errors.
