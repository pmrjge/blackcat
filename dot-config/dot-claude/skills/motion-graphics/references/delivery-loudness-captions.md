# Delivery specs, loudness, captions

Part of `motion-graphics`.

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
