---
name: subtitles
description: Use for subtitles — SRT, WebVTT, TTML, ASS; timing, reading speed, line breaks, translation.
---
# Subtitles and captions

Translation rules: `localization`; pt-PT language: `portuguese-pt-writing`; encoding, burn-in and muxing: `media-ffmpeg`.

## Formats
| format | use |
|---|---|
| SRT | universal plain subtitles; `HH:MM:SS,mmm --> HH:MM:SS,mmm`; numbered cues; minimal styling (`<i>`) |
| WebVTT | web players (`<track>`); `WEBVTT` header, `HH:MM:SS.mmm`, cue settings (`line`, `position`, `align`), `::cue` CSS, chapters/metadata |
| TTML / IMSC 1.1 | broadcast and streaming deliverables (Netflix requires TTML-based formats for many deliveries — check the spec sheet) |
| ASS/SSA | styled/typeset subtitles (fansubs, karaoke), Aegisub |
| SCC / CEA-608/708 | US broadcast captions embedded in video |
Convert with Subtitle Edit (5.2.0 — Verified 2026-10-02 https://github.com/SubtitleEdit/subtitleedit/releases/latest), ffmpeg (`ffmpeg -i in.srt out.vtt`), or Python libraries (pysubs2, srt) via `uv run --with pysubs2 …`; check styling and positioning survived.

## Timing and readability (Netflix English as a reference profile)
- Max 42 characters per line, max 2 lines, reading speed up to 20 characters per second for adult programs and 17 for children's — Verified 2026-10-02 https://partnerhelp.netflixstudios.com/hc/en-us/articles/217350977-English-Timed-Text-Style-Guide
- Other languages and clients have their own guides (Netflix publishes one per language, including European Portuguese); use the client's spec when one exists and state which profile you applied.
- Common practice: minimum duration ~5/6 s (20 frames at 24 fps), maximum ~7 s, at least 2 frames gap between consecutive subtitles, in/out times snapped to shot changes when within a few frames, lead-in no earlier than the speech onset.
- Frame rate matters: timecodes in frames (`HH:MM:SS:FF`) depend on the fps (23.976, 24, 25, 29.97 drop-frame); converting between 25 and 23.976 versions needs retiming (speed change), not just format conversion.

## Line breaking and text
- One idea per subtitle; break lines at natural linguistic points (after punctuation, before conjunctions/prepositions), never splitting article–noun, name, or verb phrase; bottom line longer when possible (pyramid).
- Condense, don't transcribe verbatim, when reading speed would be exceeded: drop repetitions, fillers and redundancies, keep meaning and tone.
- Italics for off-screen voices, songs and foreign-language dialogue per the style guide; dialogue in one subtitle with a hyphen per speaker as the guide specifies.
- SDH/captions: speaker identification, sound effects and music cues in brackets (`[door slams]`), per the client's conventions.
- Forced narratives (on-screen text, foreign dialogue) delivered as a separate track when required.

## Workflow
1. Transcribe (human or ASR such as local Whisper models; sending audio to cloud ASR shares the content — ask first) → 2. spot/time (sync to audio: `ffsubsync video.mp4 -i in.srt -o out.srt`; ffsubsync 0.5.1 — Verified 2026-10-02 https://github.com/smacke/ffsubsync/releases/latest) → 3. translate from the timed template (keep timing, re-condense for the target language) → 4. QA → 5. deliver in the required format, UTF-8.

## QA checks (scriptable)
CPS and CPL per cue against the profile; durations below min or above max; overlaps and gaps < 2 frames; cues extending past the video duration; empty cues; unbalanced tags; line count > 2; encoding UTF-8 without stray BOM issues; numbering continuous (SRT). Then watch the changed passages with the subtitles rendered (`ffplay -vf subtitles=out.srt video.mp4`, or burn a preview) — screenshots Read before reporting.

## Pitfalls
Converting fps without retiming; overlapping cues after sync; translating from a non-timed transcript; exceeding reading speed after translation (Portuguese and German run longer than English); losing positioning when converting ASS/TTML to SRT; burning subtitles into the master instead of a preview copy.

## Verify
QA script report with zero errors (or each explained) for CPS/CPL/duration/overlap · spot-check playback at three points · format validates in the target player or validator (IMSC validators for TTML) · profile and fps stated.
