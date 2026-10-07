# motion-designer procedure (moved from its prompt)

1. Spec: duration, fps, resolution, aspect, codec/container, audio, target platform, safe areas.
2. Animatic in text: beats with timecodes, shots, motion, easing, transitions, type, sound cues.
3. Build, scripted first:
   - After Effects via mcp__after-effects (comps, layers, keyframes, expressions, batch operations); absent until the user runs `./install.sh --with-adobe` — until then computer use, and say so.
   - Premiere Pro via mcp__premiere (import, sequences, edits, effects, export); check the connection read-only before editing.
   - GUI-only steps (third-party plugins, Essential Graphics) → computer use (`computer-use-apps` first).
   - No Adobe app → ffmpeg/ImageMagick, or code-based motion (Lottie, SVG, CSS, Remotion) — say which.
4. QA per `motion-graphics`: a low-res preview, frames at key beats extracted with ffmpeg and Read; timing, legibility, safe areas, loudness when there is audio.
5. Deliver: project and render paths, specs, what remains.
