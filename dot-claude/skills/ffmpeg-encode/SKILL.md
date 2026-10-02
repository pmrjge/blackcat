---
name: ffmpeg-encode
description: Use to choose and run an ffmpeg encode — x264/x265/AV1/ProRes, VideoToolbox/NVENC, pixel formats, color tags, HDR, faststart, batch.
---
# ffmpeg encoding, color tags and batch jobs

Part of `media-ffmpeg` (build check §0, inspection §1, verify). Cuts and geometry: `ffmpeg-edit`; audio and subtitles: `ffmpeg-audio-subs`.

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
| Washed-out or shifted colors in one player | missing/mismatched color tags or full-range | tag explicitly (§12); convert full→limited with `zscale=rangein=full:range=limited` |
| Banding in gradients | 8-bit, low bitrate | 10-bit encode, lower CRF, or add grain (`noise=alls=3:allf=t`) before encoding |

## Verify
- `ffprobe` shows the intended codec, profile, pix_fmt, color tags and `hvc1` tag where needed; moov before mdat for web MP4.
- Hardware encodes compared against a software reference (VMAF/SSIM, hub Verify) before choosing them for delivery.
- Batch runs: every input has an output and a logged exit status 0.
