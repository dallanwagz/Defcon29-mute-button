"""dc29.bridges.beat_buzzer — F05 audio-driven buzzer kick.

Subscribes to live audio features from :class:`~dc29.audio.AudioCapture`
and, on each detected beat, fires the F04 ``KICK`` pattern (180 Hz /
12 ms thud) so the badge becomes a tiny physical kick-drum tap synced
to whatever's playing.

Cousin to :class:`~dc29.bridges.beat_strobe.BeatStrobeBridge` but
audible instead of visible.  Run them together for full-sensory beat
sync; run solo if you just want the buzzer feedback.

Usage::

    dc29 start --enable beat-buzzer

Requires the ``[audio]`` extra (sounddevice + numpy) and a working
BlackHole capture device.  See ``CLAUDE.md`` for setup.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Optional

from dc29.audio import HAS_AUDIO, AudioCapture, AudioFeatures
from dc29.badge import BadgeAPI
from dc29.bridges.base import BaseBridge, BridgePage
from dc29.config import Config, get_config
from dc29.protocol import BeepPattern, MuteState

log = logging.getLogger(__name__)


# Minimum spacing between buzzer fires (ms).  At 170 BPM the kick
# interval is ~350 ms so we never trip the guard on real-world music;
# the guard exists to absorb double-detect glitches from the FFT/beat
# detector that would otherwise queue up two buzzer shots back-to-back.
THROTTLE_MS = 80


class BeatBuzzerBridge(BaseBridge):
    """Fire the F04 KICK pattern on every detected beat."""

    target_app_names = ("beat-buzzer",)  # placeholder — bridge isn't focus-driven

    def __init__(self, badge: BadgeAPI, config: Optional[Config] = None) -> None:
        super().__init__(badge)
        cfg = config or get_config()
        self._cfg = cfg
        self._page = BridgePage(
            name="beat-buzzer",
            description="Audio-driven F04 KICK pattern on every beat",
            buttons={},  # no button claims
        )

        self._capture: Optional[AudioCapture] = None
        self._last_fire_ms: float = 0.0

    @property
    def page(self) -> BridgePage:
        return self._page

    # ------------------------------------------------------------------

    async def run(self) -> None:
        if not HAS_AUDIO:
            log.warning(
                "beat-buzzer: numpy + sounddevice not installed.  "
                "Install with: pip install 'dc29-badge[audio]'.  "
                "Bridge will sit idle until extras are present."
            )
            await asyncio.Event().wait()
            return

        try:
            self._capture = AudioCapture(
                device=self._cfg.audio_device,
                on_features=self._on_features,
                beat_threshold_std=self._cfg.audio_beat_threshold,
            )
            self._capture.start()
        except Exception as exc:
            log.warning("beat-buzzer: capture init failed (%s) — bridge idle", exc)
            await asyncio.Event().wait()
            return

        try:
            # Idle forever — all the work happens in _on_features (audio
            # thread).  Sleep on a never-set Event so cancellation is the
            # only exit path.
            await asyncio.Event().wait()
        finally:
            if self._capture is not None:
                self._capture.stop()
                self._capture = None

    # ------------------------------------------------------------------
    # Audio-thread callback (PortAudio)
    # ------------------------------------------------------------------

    def _on_features(self, features: AudioFeatures) -> None:
        if not features.beat:
            return

        now_ms = time.monotonic() * 1000.0
        if (now_ms - self._last_fire_ms) < THROTTLE_MS:
            return

        # Yield to Teams during meetings — the kick would compete with
        # call audio and the F03 click already gives press feedback.
        if self._badge.state.mute_state != MuteState.NOT_IN_MEETING:
            return

        try:
            self._badge.play_beep(BeepPattern.KICK)
        except Exception:
            log.exception("beat-buzzer: play_beep failed")
            return

        self._last_fire_ms = now_ms

        try:
            from dc29.stats import record
            record.splash_fired()
        except Exception:
            pass
