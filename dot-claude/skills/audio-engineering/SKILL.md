---
name: audio-engineering
description: Load before audio software work — DSP, real-time audio, plugins (VST3/AU/CLAP), audio analysis and ML features; the module map.
---
# Audio engineering (hub)

## Scope
Signal processing code, real-time audio engines and plugins, and offline analysis of audio. Encoding, transcoding, loudness normalization of media files: `media-ffmpeg`; numerics: `numerical-methods`; speech/music ML models: `ml-experiment`, `training-debug`.

## Modules
| module | load when |
|---|---|
| `audio-dsp` | filters, FFT/STFT, resampling, dynamics, oscillators, fixed vs float, real-time constraints |
| `audio-plugins` | JUCE, nih-plug, VST3, AU, CLAP, Faust; plugin state, parameters, validation, signing |
| `audio-analysis` | Python analysis: loading, spectral features, loudness, onset/pitch/tempo, datasets for ML |

## Baseline rules
- **Protect ears and speakers**: never play generated or processed audio through the user's speakers or headphones without saying so first; test signals at −20 dBFS or lower, with a hard limiter/clip guard on any output path under development; NaN/Inf or DC can damage equipment — sanitize outputs.
- Know the format of every buffer: sample rate, channel count and layout, interleaved vs planar, sample type (float32 [−1, 1], int16/int24), and block size; convert explicitly.
- Real-time audio threads never block: no allocation, locks, file or network I/O, logging or system calls in the callback; communicate with lock-free FIFOs and atomics; precompute everything else.
- Levels in dBFS with the reference stated; loudness in LUFS (ITU-R BS.1770 / EBU R128) for program material; peak vs true peak distinguished.
- Determinism for tests: render offline with fixed block sizes and sample rates, compare against reference files with tolerances (e.g. max abs difference < 1e-6 for float pipelines, or a null test in dB).
- No audio MCP server is enabled in this stack (none passed vetting): work through CLIs (ffmpeg/ffprobe, sox) and Python libraries.

## Verify
Offline render tests at several sample rates (44.1, 48, 96 kHz) and block sizes (including 1 and odd sizes) pass · no allocations or locks on the audio thread (sanitizer or allocation hook in tests) · output levels checked (peak, true peak, LUFS) before anything is played · versions of frameworks and SDKs reported.
