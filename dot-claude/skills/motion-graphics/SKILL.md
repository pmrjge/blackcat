---
name: motion-graphics
description: Use for motion design — easing, timing, kinetic type, After Effects, Premiere, Lottie, Remotion.
---
# Motion graphics for video and UI

## Scope
- Craft and production of motion: principles, timing, type in motion, logos, transitions; After Effects
  (AE) and Premiere Pro practice; code-based motion (Lottie, CSS/SVG, Remotion); delivery specs,
  loudness, captions, QA. Versions checked Sep 2026 (AE 26.5, lottie-web 5.13, Remotion 4.0).
- Elsewhere: ffmpeg commands (encode, trim, loudnorm, frame grabs) in `media-ffmpeg`; typeface choice in
  `typography`; logo design in `brand-identity`; vector prep in `svg-vector-craft`; color pipelines in
  `color-management`; driving AE/Premiere through the screen in `computer-use-apps`.

## 1. Procedure
1. Spec sheet per deliverable: placement, aspect, pixels, fps, duration, codec/container, alpha, audio
   and loudness target, captions (burned/sidecar), languages, safe-zone template, deadline.
2. Lock script, voice-over and music first when possible; timing follows audio.
3. Animatic in text or boards: beats with timecodes, on-screen text, motion notes (direction, easing),
   transitions, sound cues. Approve before polish.
4. Style frames, then a 5–10 s motion test that fixes the motion language (curves, durations, stagger).
5. Build scripted-first (AE/Premiere MCP servers, expressions), review low-res renders, fix, render a
   master (ProRes 422 HQ, or 4444 with alpha), derive deliverables, run QA, hand off.

## 2. Animation principles, applied
| Principle | In motion graphics | How |
|---|---|---|
| Slow in/out (easing) | Entrances decelerate, exits accelerate; linear only for mechanical or continuous motion (tickers, spinners, loops) | AE Easy Ease (F9; Shift+F9 in; Cmd/Ctrl+Shift+F9 out), then shape influence in the Graph Editor |
| Anticipation | A small counter-move (3–6 frames) before a big move | extra keyframe opposite to travel |
| Overshoot and settle | Pass the target, settle back; sells weight and snap | two extra keyframes or the inertial-bounce expression (§6) |
| Follow-through, overlapping action | Parts arrive at different times; trailing elements lag | stagger layers 2–4 frames (Keyframe Assistant > Sequence Layers), `valueAtTime` delay |
| Staging | One focal point at a time; motion direction, contrast and scale lead the eye | fewer simultaneous movers; dim or blur the rest |
| Secondary motion | Quiet life after arrival: drift, parallax, shimmer | low-amplitude `wiggle`, slow 100→102 % scale |
| Arcs | Organic paths curve | spatial Bézier handles on position |
| Squash and stretch | Scale along the motion axis, area preserved | sparingly in brand and UI work |
| Timing and spacing | Frame count carries weight and energy | §3 |

Easing references (Material 3 tokens, as CSS `cubic-bezier`): standard `(0.2, 0, 0, 1)`, standard-decelerate
`(0, 0, 0, 1)`, standard-accelerate `(0.3, 0, 1, 1)`, emphasized-decelerate `(0.05, 0.7, 0.1, 1)`,
emphasized-accelerate `(0.3, 0, 0.8, 0.15)`, legacy `(0.4, 0, 0.2, 1)`. M3 durations: short 50–200 ms,
medium 250–400 ms, long 450–600 ms, extra-long 700–1000 ms. Zooms read as even when scale changes
exponentially (AE Keyframe Assistant > Exponential Scale). One motion language per piece: 2–3 curves,
2–3 durations, one stagger interval.

## 3. Timing, reading time, rhythm
- Frames per beat = fps × 60 / BPM: 120 BPM → 12 frames at 24 fps, 15 at 30, 12.5 at 25 (alternate 12/13).
  Land cuts and accents on beats, section changes on 4- or 8-bar phrases.
- In AE: `LL` reveals the audio waveform; tapping `*` on the numeric keypad during a preview drops
  markers on the beat; Keyframe Assistant > Convert Audio to Keyframes feeds audio-reactive expressions.
- Reading time, anchored to subtitle practice: Netflix caps adult subtitles at 20 characters/s and
  children's at 17, ≤ 42 characters per line, ≤ 2 lines, 5/6 s minimum and 7 s maximum per event.
  For titles, hold still for at least (characters ÷ 15) seconds, ≈ 0.35–0.4 s per word, after the
  entrance settles, plus ~0.5 s for the eye to find new text, never under ~1 s (heuristic derived from the above).
  Test with someone who has not seen the piece.
- Hold end cards and calls to action long enough to be read twice.

## 4. Kinetic typography
- Build with Text Animators: keyframe the Range Selector Offset; Advanced: Based On characters/words/lines,
  Shape Ramp Up, Ease High/Low, Randomize Order. Stagger 1–3 frames per unit.
- Read, then move: animate in, hold still while it is read, animate out. One moving text block at a time;
  no tracking or blur changes while the viewer should be reading. ALL CAPS only for short labels.
- Break lines by sense units; keep lines short on 9:16. Contrast ≥ 4.5:1 against the actual pixels behind
  the text (scrim, box or shadow over busy video).
- Size-to-text boxes with `sourceRectAtTime()` (§6). Variable fonts: AE 26 exposes axes in Text Animators
  (expressions: `text.animator("A").property.fontAxisWght`); animate weight/width instead of faux scaling.
- Fonts: confirm the licence covers video/broadcast output and, for Lottie or apps, embedding.

## 5. Logos and transitions
- Start from the vector master (AE 26.2+ imports SVG as vectors, 26.3+ pastes Illustrator/SVG content as
  shape layers; earlier: Layer > Create > Create Shapes from Vector Layer). Reveal with trim paths, masks or mattes;
  respect clear space, colors and proportions from the brand guide; never distort; end on the approved lockup.
- Deliver the logo sting as an alpha master (ProRes 4444) plus 16:9, 9:16 and 1:1 versions, and Lottie for UI.
- Animate only marks you are authorized to use; third-party logos are trademarks: use them unaltered and
  per their guidelines.
- Transitions: default to the cut. Motivated alternatives: match cut on shape, color or direction; a mask
  or wipe that continues an element's motion; a push in the direction of travel; a morph of a shared shape.
  Keep 2–3 transition types per piece.

## 6. After Effects practice
Read `references/ae-premiere-practice.md` when building or fixing an After Effects project (structure, expressions, rendering).

## 7. Premiere Pro practice
Read `references/ae-premiere-practice.md` (Premiere part) when editing, conforming or exporting in Premiere Pro.

## 8. Code-based motion
Read `references/code-based-motion.md` when animating in code (Remotion, Lottie, CSS/web animation, scripted renders).

## 9. Delivery specs
| Placement | Aspect → pixels | Notes |
|---|---|---|
| YouTube | 16:9 → 1920×1080, 3840×2160 | spec and bitrates in `media-ffmpeg` §2; upload at the recorded frame rate (24, 25, 30, 48, 50, 60 are common) |
| YouTube Shorts | 9:16 (or 1:1) → 1080×1920 | square or vertical uploads up to 3 min are categorized as Shorts |
| Reels, TikTok, Stories | 9:16 → 1080×1920 | TikTok ads: ≥ 540×960, ≤ 10 min, ≤ 500 MB, ≥ 516 kb/s |
| Feed (Instagram, Facebook) | 4:5 → 1080×1350; 1:1 → 1080×1080 | 4:5 takes the most feed height |
| Broadcast HD (16:9) | 1920×1080 | EBU R 95: action-safe 3.5 %, graphics-safe 5 % margins per edge |

- Codecs: H.264 High 4:2:0 8-bit for uploads; HEVC Main10 for HDR or Apple-first delivery; ProRes 422 HQ
  mezzanine, ProRes 4444 for alpha; AV1 for web players that support it. Upload generous bitrates:
  platforms re-encode everything.
- Social UI overlays: safe zones differ per platform and placement and change with app updates. TikTok
  publishes downloadable safe-zone templates per placement; Meta documents Reels/Stories zones in its Ads
  Guide. Overlay the current template on exported frames. Conservative working margins for 9:16 when no
  template is at hand: keep text and logos out of the top ~15 % and bottom ~35 % and clear of the right-edge
  action rail (heuristic, not a platform spec).
- Frame rates: deliver at the comp rate; avoid 25↔30 conversions (judder) unless a spec demands them.

## 10. Loudness
| Target | Integrated | True peak |
|---|---|---|
| EBU R 128 broadcast | −23 LUFS ±0.5 LU (±1 LU live) | ≤ −1 dBTP |
| US broadcast (ATSC A/85) | −24 LKFS | per network spec |
| Streaming/social | Spotify normalizes to −14 LUFS (documented); YouTube plays loud uploads at roughly −14 LUFS (observed, unpublished) | ≤ −1 dBTP (lossy encoding adds overs) |

Mix dialogue first, then music under it (ducked 10–15 dB is a common starting point); measure the
final mix with ebur128 and normalize with two-pass loudnorm (`media-ffmpeg` §10); report both numbers.

## 11. Captions
- Sidecar (closed) captions are toggleable, searchable and translatable: SRT (`00:00:01,000 --> 00:00:03,000`)
  for most platforms, WebVTT (`WEBVTT` header, `00:00:01.000`, cue positioning) for web `<track>`.
- Burned-in (open) captions serve muted autoplay feeds; style them inside the safe zone, bottom-center,
  moving up when they would cover on-screen text. Ship the sidecar too where the platform accepts one.
- Line and timing rules from §3 (≤ 42 characters/line, ≤ 2 lines, ≤ 17–20 characters/s). Break lines at
  punctuation and before conjunctions or prepositions; do not split article from noun or first name from surname.

## 12. Legal and safety
- Logos, fonts, music, stock and generated imagery each need a licence that covers this use and channel
  (music also needs sync rights; platforms fingerprint audio). Keep a credits/licence list with the project.
- Photosensitivity: no more than three flashes in any one-second period (WCAG 2.3.1); avoid large
  high-contrast strobes and saturated red flashes. UI motion must respect reduced-motion settings.

## Verify (QA checklist)
- Specs: ffprobe each deliverable against the spec sheet (pixels, SAR, fps, codec, duration, audio).
- Frames: extract frames at every beat, title and cut (`media-ffmpeg` §8) and review them at the target
  display size (phone size for social); overlay the safe-zone template on 9:16 exports.
- Legibility: every text hold passes the §3 reading-time rule; contrast checked on the real background.
- Artifacts: flicker from 1-px lines or fine stripes (keep strokes ≥ 2 px at 1080p, add slight blur),
  banding in gradients (16 bpc, grain, 10-bit delivery), stray frames at head/tail (`blackdetect`).
- Motion: easing consistent, no unintended linear keys, no pops at loop points, motion blur on fast moves.
- Audio: integrated loudness and true peak measured on the final file; sync checked at hard hits.
- Text: spelling, names, numbers, dates and legal lines proofread against the approved script.

## Deliverables / Report
Project files (AE/Premiere, collected with footage), master render (ProRes), deliverables per placement
with a spec table (pixels, fps, codec, bitrate, duration, LUFS/true peak), caption files, still frames used
for review, licence list for fonts/music/stock/logos, and open issues.
