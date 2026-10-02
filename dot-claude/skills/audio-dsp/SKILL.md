---
name: audio-dsp
description: Use for audio DSP — filters, FFT/STFT, resampling, anti-aliasing, dynamics, oscillators.
---
# Audio DSP

Baseline (ear safety, real-time rules, buffer formats): `audio-engineering`. Plugin wrappers: `audio-plugins`.

## Filters
- Biquads from the RBJ Audio EQ Cookbook (low/high-pass, shelves, peaking, notch); coefficients recomputed on parameter change with smoothing, not per sample unless modulated.
- Topology: transposed direct form II (float) for static filters; for modulated filters use state-variable / TPT (Zavalishin's topology-preserving transform) designs, which stay stable and click-free under fast modulation.
- High-order filters as cascaded second-order sections, never one high-order polynomial (numerical instability).
- Linear-phase FIR (windowed-sinc, Parks–McClellan via `scipy.signal.remez`) when phase matters; latency = (N−1)/2 samples, reported to the host.
- Bilinear transform warps frequency: prewarp the cutoff; near Nyquist, analog-matched designs (e.g. Vicanek's matched biquads) avoid cramping.
- Denormals: flush-to-zero/denormals-are-zero on the audio thread (JUCE `ScopedNoDenormals`, `_MM_SET_FLUSH_ZERO_MODE`), or add tiny DC/noise in feedback paths.

## Spectral processing
- STFT with a window and hop that satisfy COLA for resynthesis (Hann with 50 % or 75 % overlap; sqrt-Hann for analysis+synthesis windows); zero-padding interpolates the spectrum, it does not add resolution.
- FFT libraries: pffft/KissFFT (permissive), FFTW (GPL or commercial), vDSP/Accelerate on Apple, `numpy.fft`/`scipy.fft` offline. Partitioned convolution (uniform or non-uniform) for long impulse responses in real time.
- Phase vocoder time-stretching needs phase locking to avoid phasiness; transient handling separately.

## Resampling and aliasing
- Band-limited resampling (polyphase windowed-sinc; libsamplerate, r8brain, soxr; `scipy.signal.resample_poly` offline); never linear interpolation for quality paths.
- Nonlinear processing (distortion, saturation, waveshaping) creates harmonics above Nyquist: oversample 2–8× (with proper anti-aliasing filters) or use antiderivative antialiasing (ADAA).
- Oscillators: band-limited (PolyBLEP/BLAMP, minBLEP, wavetables with mip-mapping) — naive sawtooth/square alias audibly.

## Dynamics and gain
- Gain changes ramped (5–50 ms) to avoid zipper noise; parameter smoothing (one-pole or linear ramps) on every user-facing parameter.
- Compressors: detector (peak/RMS) in dB domain, attack/release ballistics, soft knee, lookahead with reported latency; limiters with true-peak detection (oversampled) for mastering outputs.
- Dither (TPDF) when reducing word length to 16 bits; not between float stages.

## Numeric choices
- float32 is standard in real time; double for coefficient computation, long IIR feedback at low cutoffs, and accumulators.
- Fixed-point on MCUs/DSP chips: Q-format with headroom and saturation; CMSIS-DSP on Cortex-M (`embedded-firmware`).
- SIMD: process blocks, structure-of-arrays for channels; auto-vectorization checked in compiler output before hand-writing intrinsics.

## Testing
- Unit tests on impulse/step/sine responses against analytic magnitude and phase (`scipy.signal.freqz` reference), tolerances in dB.
- Null tests between implementations (render both, subtract, report residual peak in dBFS).
- Sweep tests (log sine sweep) for frequency response and THD+N; aliasing check with a high-frequency sine through nonlinear stages.
- Modulation stress: automate parameters fast with sample-accurate changes; check for clicks (derivative spikes) and NaNs.

## Pitfalls
Coefficients computed at the wrong sample rate after a host change; filter state not reset on transport jumps (or reset when it shouldn't be); unsmoothed parameters; denormal CPU spikes on silence; aliasing from nonlinearities; latency not reported; mono/stereo assumptions breaking on other layouts.

## Verify
Frequency/phase response matches the design within tolerance at 44.1/48/96 kHz · null test vs reference implementation · aliasing and THD+N measured for nonlinear stages · no NaN/Inf/denormal slowdowns under automation stress.
