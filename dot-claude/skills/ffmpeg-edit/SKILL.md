---
name: ffmpeg-edit
description: Use to cut and reshape video with ffmpeg — trim, concat, scale/pad/crop, fps and speed, stills, GIFs, image sequences, overlays.
---
# ffmpeg editing: cuts, geometry, time, stills, overlays

Part of `media-ffmpeg` (build check §0, keyframe times §1, verify). Codec arguments: `ffmpeg-encode`; audio and subtitles: `ffmpeg-audio-subs`.

## 4. Trim
- `-c copy` cannot cut between keyframes: packets from the previous keyframe are copied and MP4 gets an edit
  list hiding the pre-roll. Players that ignore edit lists (and YouTube ingest) show extra or frozen
  frames. Copy-cut only at keyframe times (§1 in `media-ffmpeg`) or re-encode.
```sh
ffmpeg -ss 00:01:00 -to 00:01:30 -i in.mp4 -c copy -avoid_negative_ts make_zero cut_fast.mp4   # fast, keyframe-snapped
ffmpeg -ss 60.2 -i in.mp4 -t 29.5 -c:v libx264 -crf 18 -preset slow -pix_fmt yuv420p -c:a aac -b:a 192k cut_exact.mp4   # frame-accurate
```
`-ss` before `-i` seeks the input (fast) and, when re-encoding, decodes-and-discards to the exact frame.
After input seeking timestamps restart at 0, so an output-side `-to` acts as a duration; use `-t`.

## 5. Concatenate
```sh
printf "file '%s'\n" part1.mp4 part2.mp4 part3.mp4 > list.txt      # names with ' need escaping as '\''
ffmpeg -f concat -safe 0 -i list.txt -c copy joined.mp4              # identical codec, size, fps, timebase, audio layout
V="scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=30,format=yuv420p"
A="aformat=sample_rates=48000:channel_layouts=stereo"
ffmpeg -i a.mp4 -i b.mov -filter_complex "[0:v]${V}[v0];[0:a]${A}[a0];[1:v]${V}[v1];[1:a]${A}[a1];[v0][a0][v1][a1]concat=n=2:v=1:a=1[v][a]" -map "[v]" -map "[a]" -c:v libx264 -crf 18 -c:a aac joined.mp4
```
Braces matter: in zsh `$V[v0]` is an array subscript and silently expands to nothing.
Use the demuxer when `ffprobe` shows matching parameters; otherwise the concat filter, with every input
normalized to the same size, SAR, fps, pixel format, sample rate and channel layout (a clip without
audio needs a silent track: `-f lavfi -t <dur> -i anullsrc=r=48000:cl=stereo`).

## 6. Geometry: scale, pad, crop, square pixels
```sh
-vf "scale=1280:-2:flags=lanczos"                              # keep aspect, force even height
-vf "scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1"   # fit + letterbox
-vf "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1"   # fill + center crop
-vf "crop=ih*4/5:ih"                                           # centered 4:5 crop from a wider (e.g. 16:9) frame
-vf "scale=1280:720:force_original_aspect_ratio=decrease:force_divisible_by=2"
-vf "scale=trunc(iw/2)*2:trunc(ih/2)*2"                        # fix odd dimensions
```
Logo scaled to 1/10 of the video height (FFmpeg ≥ 7.1; the ref input is the second one):
`[0:v]split[base][ref];[1:v][ref]scale=w=oh*dar:h=rh/10[wm];[base][wm]overlay=W-w-24:H-h-24`.
Older builds: `[1:v][0:v]scale2ref=w=oh*mdar:h=ih/10[wm][base];[base][wm]overlay=W-w-24:H-h-24`.

## 7. Frame rate and speed
```sh
-vf fps=24                         # drop/duplicate to constant 24 fps (sync-safe)
-fps_mode cfr -r 30                # force CFR output (VFR phone or screen recordings)
-vf "minterpolate=fps=60:mi_mode=mci:mc_mode=aobmc:vsbmc=1"   # motion interpolation: slow, warps edges
-filter_complex "[0:v]setpts=PTS/2[v];[0:a]atempo=2[a]" -map "[v]" -map "[a]"          # 2x
-filter_complex "[0:v]setpts=4*PTS[v];[0:a]atempo=0.5,atempo=0.5[a]" -map "[v]" -map "[a]"  # 0.25x
-vf reverse -af areverse           # buffers the whole clip in RAM: trim first
```
`atempo` accepts 0.5–100 per instance (chain for lower values); `rubberband=tempo=…:pitch=1` (full builds) sounds better on voice.

## 8. Stills, contact sheets, GIF
```sh
ffmpeg -ss 12.5 -i in.mp4 -frames:v 1 -update 1 frame.png
ffmpeg -i in.mp4 -vf fps=1 frames/f_%04d.png
ffmpeg -i in.mp4 -vf "select='eq(pict_type,I)'" -fps_mode vfr kf_%04d.png
ffmpeg -i in.mp4 -vf "select='gt(scene,0.3)'" -fps_mode vfr scene_%04d.png
ffmpeg -i in.mp4 -vf "fps=1/5,scale=320:-2,tile=6x5:padding=4:margin=4" -frames:v 1 -update 1 sheet.png
ffmpeg -i in.mp4 -vf "thumbnail=90,scale=1280:-2" -frames:v 1 -update 1 thumb.jpg
ffmpeg -ss 2 -t 4 -i in.mp4 -vf "fps=15,scale=480:-1:flags=lanczos,split[a][b];[a]palettegen=stats_mode=diff[p];[b][p]paletteuse=dither=bayer:bayer_scale=5:diff_mode=rectangle" -loop 0 out.gif
```
GIF: keep ≤ 15 fps and ≤ 640 px wide; offer MP4/WebM as well (a fraction of the size).

## 9. Image sequences to video
```sh
ffmpeg -framerate 24 -i render/frame_%04d.png -c:v libx264 -crf 16 -pix_fmt yuv420p -movflags +faststart seq.mp4
ffmpeg -framerate 24 -start_number 1001 -i render/frame_%04d.exr -c:v prores_ks -profile:v 4444 -pix_fmt yuva444p10le seq.mov
ffmpeg -framerate 24 -pattern_type glob -i 'render/*.png' -c:v libx264 -pix_fmt yuv420p seq_glob.mp4   # not on Windows
```
`-framerate` is an input option (how to read the stills); an output `-r` resamples time.

## 13. Stabilization, overlays, burn-ins
```sh
ffmpeg -i shaky.mp4 -vf vidstabdetect=shakiness=5:accuracy=15:result=transforms.trf -f null -
ffmpeg -i shaky.mp4 -vf "vidstabtransform=input=transforms.trf:smoothing=30:optzoom=1,unsharp=5:5:0.8:3:3:0.4" -c:v libx264 -crf 18 -c:a copy stable.mp4
ffmpeg -i in.mp4 -i logo.png -filter_complex "[0:v][1:v]overlay=W-w-24:H-h-24" -c:a copy branded.mp4
ffmpeg -i in.mp4 -loop 1 -i logo.png -filter_complex "[1:v]format=rgba,fade=t=in:st=0.5:d=0.5:alpha=1,colorchannelmixer=aa=0.7[wm];[0:v][wm]overlay=24:24:shortest=1:enable='between(t,0.5,9)'" -c:a copy wm.mp4
ffmpeg -i in.mp4 -vf "drawtext=fontfile=/path/Inter.ttf:text='DRAFT %{pts\:hms}':x=(w-text_w)/2:y=h-th-40:fontsize=36:fontcolor=white:box=1:boxcolor=black@0.5:boxborderw=10" review.mp4
```
vid.stab needs libvidstab (`-filters | grep vidstab`); `deshake` is the built-in, weaker fallback.
Only overlay logos and fonts you are licensed to use.

## Troubleshooting
| Symptom or message | Cause | Fix |
|---|---|---|
| `width not divisible by 2 (1281x721)` / `height not divisible by 2` | 4:2:0 needs even dimensions | `scale=trunc(iw/2)*2:trunc(ih/2)*2` or crop; `-2` in `scale` |
| A/V drift that grows over time | VFR source (phones, screen capture) | `-vf fps=30` or `-fps_mode cfr -r 30`; audio `-af aresample=async=1` |
| Constant offset between A and V | stream start times differ, or edit lists ignored | delay the early stream: `ffmpeg -i in.mp4 -itsoffset 0.12 -i in.mp4 -map 0:v -map 1:a -c copy fixed.mp4` delays audio 120 ms |
| First frames frozen or black after `-c copy` cut | cut not on a keyframe | cut at keyframes (§1 in `media-ffmpeg`) or re-encode (§4) |
| Portrait phone clip appears sideways | display-matrix rotation | re-encoding applies it (`-noautorotate` disables); stream copy keeps the flag |

## Verify
- Cut points: extract the first and last frame of each cut and look at them; duration matches ±1 frame.
- Geometry: even dimensions, SAR 1:1, nothing important cropped; concat outputs keep A/V sync to the end.
- Speed changes: audio pitch and sync checked by ear at start, middle and end.
