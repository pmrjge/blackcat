# Editor engineering: terminal

Read when building the integrated terminal (moved from `editor-engineering` SKILL.md).

## Integrated terminal
```rust
let pair = native_pty_system().openpty(PtySize { rows: 24, cols: 80, pixel_width: 0, pixel_height: 0 })?;
let mut cmd = CommandBuilder::new_default_prog();     // user's login shell
cmd.env("TERM", "xterm-256color");
let mut child = pair.slave.spawn_command(cmd)?;
drop(pair.slave);                                      // parent keeps only the master side
let reader = pair.master.try_clone_reader()?;          // blocking Read: own thread -> channel
let writer = pair.master.take_writer()?;               // keystrokes / pastes
pair.master.resize(PtySize { rows: 40, cols: 120, pixel_width: 0, pixel_height: 0 })?; // on view resize
```
- Terminal state: `alacritty_terminal` (grid + VT handling + tty/event loop; Zed's terminal builds on it) or the lower-level `vte` parser (implement `Perform`: `print`, `execute`, `csi_dispatch`, `esc_dispatch`, `osc_dispatch`) over your own grid.
- Must handle: alternate screen, scrollback cap, bracketed paste, mouse reporting modes, wide/combining characters, true color, OSC 8 hyperlinks, OSC 133 prompt marks; treat OSC 52 clipboard writes as a permission.
- Flood control: read continuously, but cap bytes parsed per frame and redraw at display rate (`yes`, `cat bigfile`); render damaged lines only.
- Keys: map to escape sequences per mode (application cursor keys); Option-as-Meta setting on macOS.
