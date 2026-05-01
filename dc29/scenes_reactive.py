"""
dc29.scenes_reactive — Stub for audio-reactive scenes.

Not implemented this turn — captures the contract so a future audio backend
can plug in cleanly without refactoring :mod:`dc29.scenes`.

Design intent
-------------

A reactive scene is one whose color output is driven by external input
(microphone, mouse position, system telemetry) rather than time.  The
runner contract is:

* ``ReactiveScene.tick(features)`` returns a 4-tuple of RGB triples for
  the current frame.  Called at the configured fps by a runner identical
  in shape to :class:`SceneRunner`.

* ``features`` is a small dict with keys whose meaning depends on the
  source.  For audio:

  - ``rms``: 0.0–1.0 normalized loudness over the last frame
  - ``bass``, ``mid``, ``treble``: 0.0–1.0 band energy from a simple FFT
  - ``beat``: bool, fired once per detected beat
  - ``hue_phase``: 0.0–1.0 cycling at the BPM (driven by beat detector)

The audio backend is a separate concern: capture via :mod:`sounddevice`,
run a small FFT (numpy or pure-Python), produce ``features`` dicts at
30–60 Hz.  When implemented it goes in ``dc29/audio.py`` (new file).

Why not implement now
---------------------

Cross-platform mic capture has real footguns (CoreAudio permissions on
macOS, ALSA on Linux, WASAPI on Windows), and a respectable beat detector
needs more thought than fits this turn.  The TOML schema is unchanged —
when reactive scenes ship, they'll be a fourth payload kind alongside
static / animation / firmware:

.. code-block:: toml

    name = "Bass Pulse"

    [reactive]
    source = "audio"
    backend = "sounddevice"
    mapping = "bass-to-brightness"   # or a Python expression in a sandbox
    fps = 60
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass
class AudioFeatures:
    """Per-frame audio analysis output produced by a future ``dc29.audio`` backend.

    All band energies are linearly scaled to ``0.0–1.0``.  ``beat`` fires once
    per detected beat (rising edge); reactive scenes that want a sustained
    "in beat" window should look at ``hue_phase`` instead.
    """

    rms: float = 0.0
    bass: float = 0.0
    mid: float = 0.0
    treble: float = 0.0
    beat: bool = False
    hue_phase: float = 0.0


class ReactiveScene(Protocol):
    """The shape every reactive scene must satisfy.

    Implement :meth:`tick` to map ``AudioFeatures`` (or other input) to a
    4-tuple of ``(r, g, b)`` triples.  A future ``ReactiveSceneRunner`` will
    call this at the configured fps and emit via ``badge.set_all_leds``.
    """

    def tick(self, features: AudioFeatures) -> tuple[
        tuple[int, int, int],
        tuple[int, int, int],
        tuple[int, int, int],
        tuple[int, int, int],
    ]:
        ...


# ---------------------------------------------------------------------------
# Reference example — kept here so the contract is testable without a
# real audio backend.  Maps RMS to overall brightness and bass to red bias.
# ---------------------------------------------------------------------------


class BassPulseScene:
    """Tiny example: bright on bass hits, dim otherwise; hue shifts on beat."""

    def __init__(self) -> None:
        self._hue = 0

    def tick(self, features: AudioFeatures) -> tuple[
        tuple[int, int, int],
        tuple[int, int, int],
        tuple[int, int, int],
        tuple[int, int, int],
    ]:
        if features.beat:
            self._hue = (self._hue + 32) & 0xFF
        v = max(20, int(255 * (0.2 + 0.8 * features.rms)))
        b = int(255 * features.bass)
        c: tuple[int, int, int] = (v, v // 4, b)
        return (c, c, c, c)
