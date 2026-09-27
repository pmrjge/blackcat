---
name: media-ffmpeg
description: Load before running ffmpeg or ffprobe. Tested recipes for probing streams, H.264/HEVC/AV1/ProRes and VideoToolbox/NVENC encodes, keyframe vs frame-accurate trims, concat, scale/pad/crop, frame rates, stills and GIFs, audio swap and two-pass loudnorm, subtitles, color tags, speed, stabilization, overlays, faststart MP4, batch loops and troubleshooting.
---
# ffmpeg and ffprobe recipes

## Scope
- Command-line media work: inspection, encoding, cutting, joining, geometry, audio loudness, subtitles,
  color metadata, QA measurements, batch jobs. Creative decisions and platform specs (duration, safe
  zones, reading time, loudness target choice) are in `motion-graphics`; this skill is the execution.
- Commands ran on FFmpeg 6.1 (Ubuntu 24.04) and a Sep 2026 master build; VideoToolbox, NVENC and whisper
  options were checked against the FFmpeg source instead (no such hardware/model on the test box).

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
  is deprecated since 7.1 (use `scale` with a reference input, §6). FFmpeg 9.0 removed legacy NVENC
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

## 2. Encode: choose the codec
| Goal | Core arguments | Notes |
|---|---|---|
| Universal delivery (web, social, NLE-safe) | `-c:v libx264 -preset slow -crf 18 -pix_fmt yuv420p -profile:v high -c:a aac -b:a 192k -movflags +faststart` | CRF 0–51, default 23, ~18 is visually transparent; +6 CRF ≈ ½ the size, −6 ≈ ×2 |
| Smaller files, 10-bit, HDR, Apple playback | `-c:v libx265 -preset slow -crf 22 -pix_fmt yuv420p10le -profile:v main10 -tag:v hvc1` | default CRF 28; without `hvc1` QuickTime/Safari refuse the file |
| Web AV1 | `-c:v libsvtav1 -preset 6 -crf 32 -pix_fmt yuv420p10le -g 240 -svtav1-params tune=0` | preset −1…13 (default 8, lower = slower/better); CRF default 35; `film-grain=8` in `-svtav1-params` for grainy sources; Opus in WebM/MKV or AAC in MP4 |
| Edit master / intermediate | `-c:v prores_ks -profile:v hq -vendor apl0 -pix_fmt yuv422p10le -c:a pcm_s24le out.mov` | profiles `proxy lt standard hq 4444 4444xq` |
| Master with alpha | `-c:v prores_ks -profile:v 4444 -pix_fmt yuva444p10le out.mov` | keep straight (unmatted) alpha |
| Alpha on the web | `-c:v libvpx-vp9 -pix_fmt yuva420p -crf 30 -b:v 0 out.webm` (Chrome, Firefox) + HEVC-alpha `.mov` for Safari (§3) | ship both as `<source>` fallbacks; test each target browser |
| Lossless archive | `-c:v ffv1 -level 3 -g 1 -slicecrc 1 -c:a flac out.mkv` | bit-exact, large |

YouTube's upload spec: MP4, moov at front (faststart), no edit lists, H.264 High, progressive, 2 consecutive
B-frames, closed GOP of half the frame rate, CABAC, 4:2:0, AAC-LC or Opus at 48 kHz, BT.709 tags. With x264:
`-bf 2 -g 15 -flags +cgop` for 30 fps (`-g 12` at 24/25 fps). Recommended SDR upload bitrates: 1080p 8 Mb/s
(24–30 fps) / 12 Mb/s (48–60 fps); 2160p 35–45 / 53–68 Mb/s; stereo audio 384 kb/s.

## 3. Hardware encoders (fast; less quality per bit than slow x264/x265 presets)
- VideoToolbox (macOS): `h264_videotoolbox`, `hevc_videotoolbox`, `prores_videotoolbox`.
  `-q:v 1..100` is constant quality on Apple Silicon only; otherwise use `-b:v`. Decode with `-hwaccel videotoolbox`.
```sh
ffmpeg -hwaccel videotoolbox -i in.mov -c:v hevc_videotoolbox -q:v 60 -tag:v hvc1 -c:a aac -b:a 192k -movflags +faststart out.mp4
ffmpeg -i in.mov -c:v prores_videotoolbox -profile:v hq -c:a pcm_s16le out_prores.mov
ffmpeg -i alpha.mov -c:v hevc_videotoolbox -alpha_quality 0.75 -pix_fmt bgra -tag:v hvc1 out_alpha.mov   # Safari alpha
```
- NVENC (RTX 5070 Ti laptop: H.264, HEVC, AV1). Quality mode: `-rc vbr -cq N` (`-b:v 0` is harmless and
  needed on older builds). Keep frames on the GPU only if every filter is a CUDA filter (`scale_cuda`).
```sh
ffmpeg -hwaccel cuda -hwaccel_output_format cuda -i in.mp4 -vf scale_cuda=1920:-2 -c:v hevc_nvenc -preset p5 -tune hq -rc vbr -cq 24 -b:v 0 -spatial-aq 1 -temporal-aq 1 -rc-lookahead 32 -bf 3 -b_ref_mode middle -tag:v hvc1 -c:a copy out.mp4
ffmpeg -hwaccel cuda -i in.mp4 -c:v av1_nvenc -preset p6 -tune hq -rc vbr -cq 30 -b:v 0 -c:a copy out_av1.mp4
```
`-tune uhq` exists only with recent SDKs and GPUs; check `-h encoder=…`. "Driver does not support the
required nvenc API version" → the log names the minimum driver; update it.

## 4. Trim
- `-c copy` cannot cut between keyframes: packets from the previous keyframe are copied and MP4 gets an edit
  list hiding the pre-roll. Players that ignore edit lists (and YouTube ingest) show extra or frozen
  frames. Copy-cut only at keyframe times (§1) or re-encode.
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

## 10. Audio
```sh
ffmpeg -i in.mp4 -vn -c:a copy audio.m4a                         # extract as-is
ffmpeg -i in.mp4 -vn -c:a pcm_s24le -ar 48000 audio.wav
ffmpeg -i in.mp4 -i mix.wav -map 0:v:0 -map 1:a:0 -c:v copy -c:a aac -b:a 192k -shortest replaced.mp4
ffmpeg -i vo.mp4 -stream_loop -1 -i music.mp3 -filter_complex "[0:a]asplit=2[vo][sc];[1:a][sc]sidechaincompress=threshold=0.03:ratio=8:attack=20:release=400[bed];[vo][bed]amix=inputs=2:duration=first:normalize=0[a]" -map 0:v -map "[a]" -c:v copy -c:a aac -b:a 192k ducked.mp4
ffmpeg -nostats -i in.mp4 -af ebur128=peak=true -f null -          # integrated LUFS, LRA, true peak
```
Two-pass loudness normalization (defaults are I −24, LRA 7, TP −2; always set them):
```sh
T="I=-14:TP=-1:LRA=11"
J=$(ffmpeg -hide_banner -nostdin -i in.mp4 -af "loudnorm=${T}:print_format=json" -f null - 2>&1 | sed -n '/^{/,/^}/p')
read -r MI MTP MLRA MTH OFF < <(printf '%s' "$J" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d["input_i"], d["input_tp"], d["input_lra"], d["input_thresh"], d["target_offset"])')
ffmpeg -i in.mp4 -af "loudnorm=${T}:measured_I=${MI}:measured_TP=${MTP}:measured_LRA=${MLRA}:measured_thresh=${MTH}:offset=${OFF}:linear=true" -ar 48000 -c:v copy -c:a aac -b:a 192k normalized.mp4
```
(bash/zsh.) Brace every variable: zsh reads `$OFF:linear` as `$OFF` plus the `:l` modifier and emits
`offset=0.01inear=true`. loudnorm upsamples to 192 kHz internally, hence `-ar 48000`. If the linear gain
would break the true-peak ceiling it falls back to dynamic mode; re-measure with `ebur128` and report it.

## 11. Subtitles
```sh
ffmpeg -i in.mp4 -vf "subtitles=subs.srt:force_style='FontName=Inter,FontSize=16,Outline=2,BorderStyle=1,MarginV=24'" -c:v libx264 -crf 18 -c:a copy burned.mp4
ffmpeg -i in.mp4 -vf "ass=styled.ass" -c:v libx264 -crf 18 -c:a copy burned.mp4
ffmpeg -i in.mp4 -i subs.srt -map 0 -map 1 -c copy -c:s mov_text -metadata:s:s:0 language=eng -disposition:s:0 default soft.mp4
ffmpeg -i in.mp4 -i subs.srt -map 0 -map 1 -c copy -c:s srt -metadata:s:s:0 language=eng soft.mkv
ffmpeg -i subs.srt subs.vtt        # WebVTT for <track>; ffmpeg -i subs.srt subs.ass to restyle
```
SRT→ASS uses a 384×288 canvas, so `force_style` sizes and margins are in 1/288ths of the frame height
(FontSize=16 ≈ 5.6 % of height, 60 px at 1080p). Burned text needs the font installed (fontconfig name).
FFmpeg ≥ 8 with whisper.cpp (`ffmpeg-full`) can draft captions:
`-vn -af "whisper=model=ggml-base.en.bin:language=en:queue=3:destination=draft.srt:format=srt" -f null -`. Proofread before use.

## 12. Pixel formats and color tags
- Compatibility: `-pix_fmt yuv420p` (8-bit 4:2:0). 10-bit: `yuv420p10le` (x265 main10, SVT-AV1); ProRes 4:2:2 `yuv422p10le`.
- Tags only (no pixel change): `-color_primaries bt709 -color_trc bt709 -colorspace bt709 -color_range tv`
  with `-c copy`; when re-encoding use the graph form `setparams=color_primaries=bt709:color_trc=bt709:colorspace=bt709:range=tv`
  (FFmpeg ≥ 7.1 silently drops output-side `-color_primaries`/`-color_trc` on re-encode).
- Convert (changes pixels): `zscale=matrixin=470bg:matrix=709:primariesin=170m:primaries=709:transferin=601:transfer=709:rangein=limited:range=limited,format=yuv420p`
  (or `colorspace=all=bt709:iall=bt601-6-625`). Untagged SD sources are usually BT.601; HD BT.709.
- HDR10 with x265: `-pix_fmt yuv420p10le -x265-params "colorprim=bt2020:transfer=smpte2084:colormatrix=bt2020nc:master-display=G(13250,34500)B(7500,3000)R(34000,16000)WP(15635,16450)L(10000000,1):max-cll=1000,400:hdr10-opt=1:repeat-headers=1"`
  (replace master-display and max-cll with the grade's real metadata). HDR→SDR preview:
  `zscale=t=linear:npl=100,format=gbrpf32le,zscale=p=bt709,tonemap=tonemap=hable:desat=0,zscale=t=bt709:m=bt709:r=tv,format=yuv420p`.
  Color pipelines beyond this: `color-management`.

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

## 14. Streaming-friendly MP4 and remux
- `-movflags +faststart` moves the moov atom to the front (progressive playback); remux without re-encoding:
  `ffmpeg -i in.mp4 -c copy -movflags +faststart out.mp4`. Check: `ffprobe -v trace -i out.mp4 2>&1 | grep -oE "type:'(moov|mdat)'" | head -2` lists moov first.
- Piped/live MP4 needs fragmentation instead: `-movflags +frag_keyframe+empty_moov`.
- `-use_editlist 0` forces no edit list; timestamps then shift instead.

## 15. Batch patterns
```sh
# zsh (bash: "${f%.*}")
for f in *.mov; do ffmpeg -hide_banner -nostdin -n -i "$f" -c:v libx264 -crf 18 -pix_fmt yuv420p -c:a aac -movflags +faststart "${f:r}.mp4"; done
# fish
for f in *.mov; ffmpeg -hide_banner -nostdin -n -i $f -c:v libx264 -crf 18 -pix_fmt yuv420p -c:a aac (path change-extension mp4 $f); end
# parallel, NUL-safe (spaces, quotes in names)
find . -name '*.mov' -print0 | xargs -0 -n1 -P 4 sh -c 'ffmpeg -hide_banner -nostdin -n -loglevel error -i "$1" -c:v libx264 -crf 20 -c:a aac "${1%.*}.mp4"' _
```
Without `-nostdin`, ffmpeg inside a `while read` loop swallows the list from stdin. Hardware encoders
have session limits; keep `-P` small for NVENC and VideoToolbox. Log each command and exit status.

## Troubleshooting
| Symptom or message | Cause | Fix |
|---|---|---|
| `width not divisible by 2 (1281x721)` / `height not divisible by 2` | 4:2:0 needs even dimensions | `scale=trunc(iw/2)*2:trunc(ih/2)*2` or crop; `-2` in `scale` |
| A/V drift that grows over time | VFR source (phones, screen capture) | `-vf fps=30` or `-fps_mode cfr -r 30`; audio `-af aresample=async=1` |
| Constant offset between A and V | stream start times differ, or edit lists ignored | delay the early stream: `ffmpeg -i in.mp4 -itsoffset 0.12 -i in.mp4 -map 0:v -map 1:a -c copy fixed.mp4` delays audio 120 ms |
| First frames frozen or black after `-c copy` cut | cut not on a keyframe | cut at keyframes (§1) or re-encode (§4) |
| `Nothing was written into output file…received no packets` | encoder failed or mapping empty | read the first error above it; check `-map` and filter labels |
| Washed-out or shifted colors in one player | missing/mismatched color tags or full-range | tag explicitly (§12); convert full→limited with `zscale=rangein=full:range=limited` |
| Portrait phone clip appears sideways | display-matrix rotation | re-encoding applies it (`-noautorotate` disables); stream copy keeps the flag |
| Banding in gradients | 8-bit, low bitrate | 10-bit encode, lower CRF, or add grain (`noise=alls=3:allf=t`) before encoding |
| `Unrecognized option 'vsync'` | removed option | `-fps_mode` |
| `Filter … has an unconnected output` (9.x: `Filter '…' has output N (…) unconnected`) | a split/asplit output was not consumed | label and use every output |
| Burned-in subtitles in the wrong font | font not visible to fontconfig | install it or pass `fontsdir=` to `subtitles` |

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
