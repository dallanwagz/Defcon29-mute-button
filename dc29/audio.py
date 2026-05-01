"""
dc29.audio — Live system-audio capture, FFT, and beat detection.

Used by :class:`~dc29.bridges.audio_reactive.AudioReactiveBridge` to make the
badge LEDs respond to whatever's playing on the user's machine — Spotify,
Apple Music, YouTube, anything that produces audio output.

Architecture
------------

We capture from a virtual audio loopback device (BlackHole on macOS) so we
get system audio without using the microphone.  The user creates a Multi-
Output Device combining BlackHole + their AirPods/speakers — sound goes to
both, we capture from BlackHole, the user still hears their music normally.

Setup
-----

macOS::

    brew install blackhole-2ch

Then in **Audio MIDI Setup** (`/System/Applications/Utilities/Audio MIDI Setup.app`):

1. Click the ``+`` → **Create Multi-Output Device**.
2. Check both your speaker/AirPods *and* "BlackHole 2ch".
3. Right-click the new device → **Use This Device for Sound Output**.

System audio now plays through your AirPods (you hear it) AND BlackHole
(we capture it).  Run ``dc29 audio status`` to confirm BlackHole is visible.

Implementation
--------------

* Capture via :mod:`sounddevice` (PortAudio wrapper).  Callback runs on the
  PortAudio thread.
* :class:`AudioCapture` rolls samples through a 2048-sample buffer and runs
  a windowed real-FFT each callback (every ~23 ms at 44.1 kHz with 1024-
  sample hop).  Output: :class:`AudioFeatures` dicts at ~43 fps.
* Beat detection: rolling-window energy threshold.  When current bass-band
  energy exceeds ``mean + threshold·std`` over the last ~1 second AND we're
  past the minimum inter-beat interval (250 ms = 240 BPM ceiling), fire a
  beat event.  Crude vs. madmom but adequate and zero-deps.

Optional dependency
-------------------

This module imports :mod:`numpy` and :mod:`sounddevice`.  Both are listed
under the ``[audio]`` extra in ``pyproject.toml``.  If they're not present,
:data:`HAS_AUDIO` is ``False`` and the audio bridge will log a friendly
"missing extra" warning and sleep.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

log = logging.getLogger(__name__)

try:
    import sounddevice as sd
    import numpy as np
    HAS_AUDIO = True
except ImportError:
    HAS_AUDIO = False
    sd = None         # type: ignore[assignment]
    np = None         # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Frame configuration
# ---------------------------------------------------------------------------

SAMPLE_RATE = 44100
"""Capture sample rate.  44.1 kHz matches consumer audio output."""

FRAME_SIZE = 2048
"""FFT window size in samples (~46 ms at 44.1 kHz).  Big enough for usable
low-frequency resolution (~21 Hz/bin), small enough for snappy reactivity."""

HOP_SIZE = 1024
"""Samples per PortAudio callback = effective update rate (~23 ms = 43 fps)."""

# Frequency-band boundaries (Hz).  Aligned to standard "bass / mid / treble"
# divisions used by audio engineers; tweakable but these are sane defaults.
BAND_BASS_HI = 250
BAND_MID_HI = 2000
BAND_TREBLE_HI = 8000

# Beat-detection parameters.
BEAT_HISTORY_S = 1.0           # rolling window for mean+std
BEAT_THRESHOLD_STD = 1.5       # how many σ above the mean triggers a beat
BEAT_MIN_INTERVAL_S = 0.25     # 240 BPM ceiling — anything faster is noise
BEAT_ABSOLUTE_FLOOR = 0.05     # ignore beats below this (silence/quiet music)


@dataclass
class AudioFeatures:
    """Per-frame audio analysis output.

    All band energies are normalized to ``[0, 1]``.  ``beat`` fires once on
    the rising edge of an onset (consumers should treat it as a transient
    event, not a sustained signal).
    """

    rms: float = 0.0
    """Root-mean-square loudness, 0..1 (rough auto-normalized)."""

    bass: float = 0.0
    """Energy in the 20–250 Hz band, 0..1."""

    mid: float = 0.0
    """Energy in the 250–2000 Hz band, 0..1."""

    treble: float = 0.0
    """Energy in the 2000–8000 Hz band, 0..1."""

    beat: bool = False
    """True for one frame on each detected onset (rising edge)."""

    chroma: list[float] = field(default_factory=lambda: [0.0] * 12)
    """12-bin pitch-class profile: which musical notes are present.  Index 0
    = C, 1 = C♯/D♭, ..., 11 = B.  Useful for key-aware color mapping."""

    timestamp: float = 0.0
    """``time.monotonic()`` at the moment this frame was computed."""


# ---------------------------------------------------------------------------
# Capture
# ---------------------------------------------------------------------------


class AudioCapture:
    """Captures audio from a system input device and emits :class:`AudioFeatures`.

    The PortAudio callback runs on its own thread.  Consumers register a
    callback via the ``on_features`` constructor arg or pull the latest
    snapshot via :attr:`latest`.

    .. code-block:: python

        cap = AudioCapture(on_features=lambda f: print(f.rms))
        cap.start()
        time.sleep(10)
        cap.stop()
    """

    def __init__(
        self,
        device: Optional[str] = None,
        on_features: Optional[Callable[[AudioFeatures], None]] = None,
        sample_rate: int = SAMPLE_RATE,
        frame_size: int = FRAME_SIZE,
        hop_size: int = HOP_SIZE,
        beat_threshold_std: float = BEAT_THRESHOLD_STD,
    ) -> None:
        if not HAS_AUDIO:
            raise ImportError(
                "Audio capture requires sounddevice + numpy.  "
                "Install with: pip install 'dc29-badge[audio]'  "
                "(plus `brew install blackhole-2ch` on macOS for system loopback)"
            )

        self.device = device
        self.on_features = on_features
        self.sample_rate = sample_rate
        self.frame_size = frame_size
        self.hop_size = hop_size
        self.beat_threshold_std = beat_threshold_std

        self._stream: Optional[sd.InputStream] = None
        self._buffer = np.zeros(frame_size, dtype=np.float32)
        self._window = np.hanning(frame_size).astype(np.float32)
        self._bin_freqs = np.fft.rfftfreq(frame_size, 1.0 / sample_rate)

        # Pre-compute band masks for fast feature extraction.
        self._mask_bass = self._bin_freqs <= BAND_BASS_HI
        self._mask_mid = (self._bin_freqs > BAND_BASS_HI) & (self._bin_freqs <= BAND_MID_HI)
        self._mask_treble = (self._bin_freqs > BAND_MID_HI) & (self._bin_freqs <= BAND_TREBLE_HI)

        # Beat history — circular buffer of recent bass-band energy.
        history_len = max(2, int(BEAT_HISTORY_S * sample_rate / hop_size))
        self._beat_history = np.zeros(history_len, dtype=np.float32)
        self._beat_idx = 0
        self._last_beat_time = 0.0

        # Latest snapshot for pull-style consumers.
        self._latest_lock = threading.Lock()
        self._latest: Optional[AudioFeatures] = None

        # Pre-compute chroma bin → pitch-class lookup (cached).  Each FFT bin
        # is mapped to a MIDI note number; %12 gives the chroma class.
        with np.errstate(divide="ignore", invalid="ignore"):
            midi = 69 + 12 * np.log2(self._bin_freqs / 440.0)
        self._chroma_class = np.where(
            (self._bin_freqs >= 27.5) & (self._bin_freqs <= 4186.0),
            np.round(midi).astype(int) % 12,
            -1,                # -1 means "skip this bin"
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> None:
        device_idx = self._resolve_device()
        self._stream = sd.InputStream(
            samplerate=self.sample_rate,
            channels=1,
            callback=self._callback,
            blocksize=self.hop_size,
            device=device_idx,
            dtype="float32",
        )
        self._stream.start()
        log.info(
            "audio capture started on device %r (rate %d Hz, hop %d, frame %d)",
            self._device_name(device_idx),
            self.sample_rate, self.hop_size, self.frame_size,
        )

    def stop(self) -> None:
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                log.exception("audio capture: stop failed")
            self._stream = None

    @property
    def latest(self) -> Optional[AudioFeatures]:
        with self._latest_lock:
            return self._latest

    # ------------------------------------------------------------------
    # PortAudio callback (separate thread!) and feature extraction
    # ------------------------------------------------------------------

    def _callback(self, indata, frames: int, time_info, status) -> None:  # type: ignore[no-untyped-def]
        if status and status.input_overflow:
            # Common when the host is busy; non-fatal.
            log.debug("audio: input overflow")

        # Roll: drop oldest `frames` samples, append the new ones.
        n = min(frames, self.frame_size)
        self._buffer[:-n] = self._buffer[n:]
        self._buffer[-n:] = indata[:n, 0]   # mono channel 0

        features = self._compute_features()

        with self._latest_lock:
            self._latest = features

        if self.on_features is not None:
            try:
                self.on_features(features)
            except Exception:
                log.exception("audio: on_features callback raised")

    def _compute_features(self) -> AudioFeatures:
        samples = self._buffer
        windowed = samples * self._window
        spectrum = np.abs(np.fft.rfft(windowed))

        # RMS — rough auto-normalization.  Real-world digital audio rarely
        # exceeds RMS ~0.2; multiplying by 5 puts it in 0..1 for typical
        # input levels.
        rms = float(np.sqrt(np.mean(samples * samples)))
        rms_norm = min(1.0, rms * 5.0)

        # Band energies — average magnitude per band.  Constants below are
        # empirically chosen so typical music output lands near 0.5–0.8
        # in each band; loud sections clip to 1.0.
        bass = float(spectrum[self._mask_bass].mean()) if self._mask_bass.any() else 0.0
        mid = float(spectrum[self._mask_mid].mean()) if self._mask_mid.any() else 0.0
        treble = float(spectrum[self._mask_treble].mean()) if self._mask_treble.any() else 0.0
        bass_n = min(1.0, bass / 50.0)
        mid_n = min(1.0, mid / 30.0)
        treble_n = min(1.0, treble / 20.0)

        # Beat detection on the bass band.
        self._beat_history[self._beat_idx % len(self._beat_history)] = bass_n
        self._beat_idx += 1
        hist_mean = float(self._beat_history.mean())
        hist_std = float(self._beat_history.std())
        now = time.monotonic()
        beat = (
            bass_n > hist_mean + self.beat_threshold_std * hist_std + BEAT_ABSOLUTE_FLOOR
            and (now - self._last_beat_time) > BEAT_MIN_INTERVAL_S
        )
        if beat:
            self._last_beat_time = now

        # Chroma: sum spectrum magnitudes by pitch class.  Vectorized via
        # the pre-computed _chroma_class lookup; -1 entries are skipped.
        chroma = np.zeros(12, dtype=np.float32)
        valid = self._chroma_class >= 0
        np.add.at(chroma, self._chroma_class[valid], spectrum[valid])
        cmax = float(chroma.max())
        if cmax > 0:
            chroma = chroma / cmax

        return AudioFeatures(
            rms=rms_norm,
            bass=bass_n,
            mid=mid_n,
            treble=treble_n,
            beat=beat,
            chroma=chroma.tolist(),
            timestamp=now,
        )

    # ------------------------------------------------------------------
    # Device discovery
    # ------------------------------------------------------------------

    def _resolve_device(self) -> Optional[int]:
        if self.device:
            for i, dev in enumerate(sd.query_devices()):
                if (
                    self.device.lower() in dev["name"].lower()
                    and dev["max_input_channels"] > 0
                ):
                    return i
            log.warning(
                "audio: device %r not found — falling back to system default",
                self.device,
            )
            return None

        # Auto: prefer BlackHole if present.
        idx = find_blackhole()
        if idx is not None:
            return idx
        log.info("audio: BlackHole not detected; using system default input")
        return None

    def _device_name(self, idx: Optional[int]) -> str:
        if idx is None:
            return "(system default)"
        try:
            return sd.query_devices(idx)["name"]
        except Exception:
            return f"device {idx}"


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def list_input_devices() -> list[dict]:
    """Return all input-capable audio devices with their indices and names.

    Empty list if sounddevice isn't installed.  Used by ``dc29 audio status``.
    """
    if not HAS_AUDIO:
        return []
    out: list[dict] = []
    for i, d in enumerate(sd.query_devices()):
        if d["max_input_channels"] > 0:
            out.append({
                "index": i,
                "name": d["name"],
                "channels": d["max_input_channels"],
                "default_samplerate": d.get("default_samplerate", 0),
            })
    return out


def find_blackhole() -> Optional[int]:
    """Return the device index of BlackHole if present, else None."""
    if not HAS_AUDIO:
        return None
    for i, d in enumerate(sd.query_devices()):
        if "blackhole" in d["name"].lower() and d["max_input_channels"] > 0:
            return i
    return None
