# Motion graphics: After Effects and Premiere Pro practice

## 6. After Effects practice
- Comp setup: delivery size, square pixels, delivery frame rate (never mix 29.97 and 30). Project color
  depth 16 bpc for gradients and glows (8 bpc bands); 32 bpc float for linear-light or HDR work; set the
  working color space deliberately (Rec.709/sRGB for web video, OCIO/ACES for VFX pipelines; AE 26.5 ships ACES 2.0).
- Structure: one precomp per scene or element, named layers, a controller null carrying Expression Controls
  sliders; Essential Properties to expose precomp parameters per instance; Collapse Transformations on
  vector precomps so they stay sharp when scaled.
- Shapes, masks, mattes: shape layers with Trim Paths, Repeater, Offset Paths. Since AE 2023 any layer can be
  a track matte (Track Matte menu or pick whip), several layers can share one matte, and the matte layer is
  hidden automatically; choose Alpha or Luma and Inverted with the two toggles.
- Parenting: rig with nulls; avoid non-uniform scale on parents (it skews rotated children).
- Graph Editor (Shift+F3): speed graph for feel, value graph for overshoot; Separate Dimensions for
  independent X/Y curves; motion blur (layer switch plus comp switch) on fast moves.
- Templates: Essential Graphics panel → Export Motion Graphics Template (.mogrt) for Premiere; Composition >
  Responsive Design – Time protects intros/outros when the template is stretched. Test with the longest and
  shortest real text.
- Performance: Multi-Frame Rendering (AE 2022+, Settings > Memory & Performance), Composition Profiler to
  find slow layers, Cache Frames When Idle, disk cache on a fast SSD, preview at Half/Quarter resolution
  with Region of Interest, pre-render heavy precomps to ProRes 4444 or use proxies, avoid expressions that
  sample many layers or times per frame; `posterizeTime(n)` lowers evaluation rate.
- Render: Render Queue (native H.264 since AE 23.0) or Media Encoder; best practice is a ProRes master,
  then deliverables with `media-ffmpeg`.

Expression library (JavaScript engine; `U`/`UU` reveal keyframes/changed properties, `EE` expressions,
Alt/Option-click a stopwatch to add one):
```js
[wiggle(2, 30)[0], value[1]]                        // wiggle(freq, amp[, octaves=1, amp_mult=0.5, t=time]) on X only
var L = 3, t = time % L;                            // seamless 3 s wiggle loop
linear(t, 0, L, wiggle(1, 40, 1, 0.5, t), wiggle(1, 40, 1, 0.5, t - L));
loopOut("cycle");                                    // also "pingpong", "offset", "continue"; loopIn(), loopOutDuration(type, dur)
ease(effect("Progress")("Slider"), 0, 100, 0, 360); // ease(t, tMin, tMax, v1, v2); easeIn/easeOut/linear alike
thisComp.layer("Leader").transform.position.valueAtTime(time - framesToTime(4)); // 4-frame follow-through
// inertial bounce after the last keyframe passed
var amp = 0.06, freq = 2.5, decay = 5, n = 0;
if (numKeys > 0) { n = nearestKey(time).index; if (key(n).time > time) n--; }
if (n > 0) { var t = time - key(n).time; var v = velocityAtTime(key(n).time - thisComp.frameDuration / 10);
  value + v * amp * Math.sin(freq * t * 2 * Math.PI) / Math.exp(decay * t); } else { value; }
// shape-layer Rectangle Size that hugs a text layer (+padding)
var r = thisComp.layer("Title").sourceRectAtTime(time, false); [r.width + 40, r.height + 24];
posterizeTime(12); value;                            // animate "on twos" at 24 fps
// Time Remap: play the precomp from its start at every layer marker
var m = thisLayer.marker, k = 0;
if (m.numKeys > 0) { k = m.nearestKey(time).index; if (m.key(k).time > time) k--; }
k > 0 ? time - m.key(k).time : 0;
// audio-reactive scale (after Convert Audio to Keyframes)
var a = thisComp.layer("Audio Amplitude").effect("Both Channels")("Slider"), s = 1 + linear(a, 0, 20, 0, 0.15);
[value[0] * s, value[1] * s];
seedRandom(index, true); random(-15, 15);           // stable random value per layer
```

## 7. Premiere Pro practice
- Sequences: New Sequence From Clip to match the source; for vertical and square versions use a custom
  frame size or Sequence > Auto Reframe Sequence, then check every reframed shot by eye.
- Adjustment layers (File > New > Adjustment Layer) for grades and effects across clips; Essential Graphics /
  Properties panel for text, shapes and .mogrt templates.
- Captions: Text panel → Transcript (Speech to Text) → Create captions; style the caption track; export a
  sidecar (SRT) or burn in at export. Proofread names and numbers.
- Color: Lumetri Color (Basic Correction, Creative, Curves, Color Wheels & Match, HSL Secondary, Vignette)
  judged on Lumetri Scopes (waveform, parade, vectorscope), not by eye alone.
- Audio: Essential Sound (Dialogue/Music/SFX/Ambience, loudness auto-match, music ducking), Loudness Meter;
  measure the final mix (§10) rather than trusting meters mid-edit.
