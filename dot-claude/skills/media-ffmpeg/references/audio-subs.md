# ffmpeg audio, loudness and subtitles

Part of `media-ffmpeg` (build check §0: `subtitles` and `whisper` need full builds; verify). Loudness target choice: `motion-graphics`.

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
read -r MI MTP MLRA MTH OFF < <(printf '%s' "$J" | jq -r '"\(.input_i) \(.input_tp) \(.input_lra) \(.input_thresh) \(.target_offset)"')
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

## Troubleshooting
| Symptom or message | Cause | Fix |
|---|---|---|
| Burned-in subtitles in the wrong font | font not visible to fontconfig | install it or pass `fontsdir=` to `subtitles` |

## Verify
- `ebur128=peak=true` on the output matches the target (integrated LUFS ±1, true peak under the ceiling); report a dynamic-mode fallback.
- Soft subtitles: `ffprobe` shows the subtitle stream with language and disposition; burned ones checked on frames at each cue in the intended font.
