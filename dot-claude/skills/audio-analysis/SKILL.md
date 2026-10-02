---
name: audio-analysis
description: Load to analyze audio in Python — loading and resampling, spectral features, loudness (LUFS), pitch, onsets, tempo, ML datasets.
---
# Audio analysis

Baseline: `audio-engineering`. File conversion and probing: `media-ffmpeg`. Model training: `ml-experiment`.

## Libraries
- librosa 1.0.0 (major release: check its changelog for removed or renamed APIs before porting 0.x code) — Verified 2026-10-02 https://github.com/librosa/librosa/releases/latest
- soundfile 0.14.0 (libsndfile I/O: WAV, FLAC, OGG, MP3 read) — Verified 2026-10-02 https://pypi.org/project/soundfile/
- pyloudnorm 0.2.0 (BS.1770 loudness) — Verified 2026-10-02 https://pypi.org/project/pyloudnorm/
- pedalboard 0.9.25 (fast I/O and effects, hosts VST3/AU) — Verified 2026-10-02 https://pypi.org/project/pedalboard/
- torchaudio 2.11.0 is in maintenance mode: its I/O was removed in 2.9; use TorchCodec (or soundfile) for decoding and keep torchaudio for transforms and models — Verified 2026-10-02 https://github.com/pytorch/audio
- Install in a uv project (`uv add librosa soundfile`), run with `uv run`.

## Loading
- `sf.read(path, dtype="float32", always_2d=True)` keeps the native rate and channels; resample deliberately (`librosa.resample` with `res_type="soxr_hq"` or `scipy.signal.resample_poly`). `librosa.load` resamples to 22,050 Hz and downmixes by default — pass `sr=None, mono=False` unless that is intended.
- Probe first: `ffprobe -v error -show_streams -of json file` for codec, rate, channels, duration; decode compressed or video files to WAV/FLAC with ffmpeg once.
- Long files: stream blocks (`sf.blocks`) instead of loading hours into memory.

## Features
- Spectrograms: STFT magnitude in dB (`librosa.amplitude_to_db(ref=np.max)` for display only), mel spectrograms (state `n_fft`, `hop_length`, `n_mels`, `fmin`, `fmax`, power vs amplitude), MFCCs, chroma, CQT for music.
- State the frame/hop in samples and seconds; align feature frames to time with `librosa.frames_to_time`.
- Pitch: pYIN (`librosa.pyin`) or CREPE-style models for monophonic f0; voiced probabilities kept.
- Onsets, beats, tempo: `librosa.onset.onset_detect`, `librosa.beat.beat_track` (tempo octave errors are common — report alternatives); madmom/BeatNet-style models for harder music.
- Source separation and transcription: pretrained models (Demucs, Basic Pitch) — check licenses and run locally.

## Loudness and levels
- Integrated loudness (LUFS), loudness range (LRA), true peak (dBTP, 4× oversampled) with pyloudnorm or `ffmpeg -af ebur128=peak=true`.
- Targets: streaming platforms around −14 LUFS integrated (varies by platform), EBU R128 broadcast −23 LUFS, true peak ≤ −1 dBTP; state which target you used.
- Clipping detection: count samples at or near full scale; inter-sample peaks via true-peak meters.

## Datasets for ML
- Splits by speaker/recording/session/artist, never by clip (leakage); consistent sample rate and loudness normalization; label timing aligned to frames.
- Augmentation (noise, reverb, pitch/time shifts) applied on the fly with seeds; augmentations that change labels (pitch shift for key labels) handled.
- Licenses and consent for speech and music data recorded; personal voice data stays local.

## Pitfalls
`librosa.load` silently resampling/downmixing; dB plots with per-file `ref=np.max` compared across files; mixing amplitude and power spectrograms; frame-to-time offsets (centered frames); MP3 encoder delay padding shifting onsets; clip-level splits leaking speakers.

## Verify
Sample rate, channels and duration printed for inputs · feature parameters recorded with outputs · loudness values cross-checked with ffmpeg's ebur128 · plots Read before describing them · splits checked for leakage.
