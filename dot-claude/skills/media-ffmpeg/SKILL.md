---
name: media-ffmpeg
description: Use before running ffmpeg or ffprobe — encodes, trims, concat, scaling, GIFs, loudnorm, subtitles.
---
# ffmpeg and ffprobe recipes

## Scope
- Command-line media work: inspection, encoding, cutting, joining, geometry, audio loudness, subtitles,
  color metadata, QA measurements, batch jobs. Creative decisions and platform specs (duration, safe
  zones, reading time, loudness target choice) are in `motion-graphics`; this skill is the execution.
- Commands ran on FFmpeg 6.1 (Ubuntu 24.04) and a Sep 2026 master build; VideoToolbox, NVENC and whisper
  options were checked against the FFmpeg source instead (no such hardware/model on the test box).
- FFmpeg 9.0.2 is the latest release (Verified 2026-10-02 `git ls-remote --tags https://github.com/FFmpeg/FFmpeg`).

## References (read the one the task touches)
| Reference | Read when the task needs |
|---|---|
| `references/encode.md` | codec choice (H.264/HEVC/AV1/ProRes/alpha/lossless), YouTube spec, VideoToolbox/NVENC, pixel formats and color tags, HDR, faststart/remux, batch loops |
| `references/edit.md` | trim, concat, scale/pad/crop, frame rate and speed, stills/contact sheets/GIF, image sequences, stabilization, overlays, burn-ins |
| `references/audio-subs.md` | audio extract/replace, ducking, loudness measurement and two-pass loudnorm, burned or soft subtitles, whisper drafts |

## 0. Check the build before relying on a feature
```sh
ffmpeg -hide_banner -version | head -1
ffmpeg -hide_banner -encoders | grep -E 'libx26[45]|libsvtav1|prores|videotoolbox|nvenc'
ffmpeg -hide_banner -filters  | grep -E ' (subtitles|drawtext|zscale|vidstab\w*|libvmaf|whisper) '
ffmpeg -hide_banner -h encoder=hevc_nvenc    # every option and range for THIS build
ffmpeg -hide_banner -h filter=loudnorm
```
- macOS/Homebrew: the `ffmpeg` formula is slim (x264, x265, SVT-AV1, libvpx, dav1d, opus, lame, libvmaf,
  VideoToolbox). It lacks libass (`subtitles`), freetype (`drawtext`), zimg (`zscale`), vid.stab,
  rubberband and whisper. `brew install ffmpeg-full` has them; it is keg-only, so call
  `"$(brew --prefix ffmpeg-full)/bin/ffmpeg"`.
- Linux: distro builds differ (Ubuntu 24.04 ships 6.1 with libass, vid.stab, zimg, SVT-AV1, NVENC).
  NVENC needs a recent NVIDIA driver; see `linux-workstation`.
- Version breaks: `-vsync` is gone in current builds, use `-fps_mode cfr|vfr|passthrough`. `scale2ref`
  is deprecated since 7.1 (use `scale` with a reference input, §6 in `references/edit.md`). FFmpeg 9.0 removed legacy NVENC
  options: use presets `p1`–`p7` plus `-tune`.
- Script hygiene: `-hide_banner -nostdin`, `-n` (never overwrite) unless you mean `-y`,
  `-loglevel error -stats` for quiet progress, `-progress pipe:1` for machine-readable progress.
  Never write over an input; write a new file and verify it.

## 1. Inspect
```sh
ffprobe -v error -show_format -show_streams -of json in.mp4 > in.probe.json
ffprobe -v error -select_streams v:0 -show_entries stream=codec_name,profile,width,height,sample_aspect_ratio,pix_fmt,r_frame_rate,avg_frame_rate,field_order,color_range,color_space,color_transfer,color_primaries -of json in.mp4
ffprobe -v error -show_entries format=duration -of default=nw=1:nk=1 in.mp4
ffprobe -v error -select_streams v:0 -skip_frame nokey -show_entries frame=pts_time -of csv=p=0 in.mp4  # keyframe times
ffprobe -v error -count_frames -select_streams v:0 -show_entries stream=nb_read_frames -of csv=p=0 in.mp4
ffmpeg -hide_banner -nostdin -i in.mp4 -vf vfrdet -an -f null -    # prints VFR ratio; VFR also shows as r_frame_rate != avg_frame_rate
```
Record codec/profile, WxH and SAR, pix_fmt (bit depth, chroma), r vs avg frame rate, color tags,
audio codec/rate/channels, duration, and rotation side data (phone footage).

## Troubleshooting (general)
| Symptom or message | Cause | Fix |
|---|---|---|
| `Nothing was written into output file…received no packets` | encoder failed or mapping empty | read the first error above it; check `-map` and filter labels |
| `Unrecognized option 'vsync'` | removed option | `-fps_mode` |
| `Filter … has an unconnected output` (9.x: `Filter '…' has output N (…) unconnected`) | a split/asplit output was not consumed | label and use every output |
Tool-specific rows are in each reference.

## Verify
- `ffprobe` the output against the spec (codec, profile, WxH, SAR 1:1, fps, pix_fmt, color tags, audio rate/layout, duration ±1 frame).
- Full decode test: `ffmpeg -v error -i out.mp4 -f null -` prints nothing on a clean file.
- Re-measure loudness with `ebur128`; extract frames at cuts, first/last frame and titles and look at them.
- Encode comparisons: `ffmpeg -i enc.mp4 -i ref.mp4 -lavfi "[0:v]setpts=PTS-STARTPTS[d];[1:v]setpts=PTS-STARTPTS[r];[d][r]libvmaf" -f null -` (VMAF), or `ssim`/`psnr`.
  Check with `blackdetect`, `freezedetect`, `silencedetect` for unwanted gaps.

## Deliverables / Report
Output files with paths; the exact commands as a runnable script; `ffprobe` JSON of each output; a table of
spec vs measured (resolution, fps, codec, bitrate, duration, integrated LUFS and true peak, VMAF if
compared); anything that fell back to a different codec or build and why.
