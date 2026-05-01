"""
dc29.bridges.beat_strobe — Audio-driven 200 Hz beat strobe.

Subscribes to live audio features from :class:`~dc29.audio.AudioCapture`
and, on each detected beat, fires a ~50 ms strobe burst across all four
LEDs.  Inside the burst, alternating frames flip between a saturated
palette color and full white at ~62 Hz — produces a tight "DJ booth
strobe" feel synced to whatever's playing.

Cousin to :class:`~dc29.bridges.audio_reactive.AudioReactiveBridge` but
much simpler: it doesn't do continuous frequency-band rendering; it just
listens for beats and slams the LEDs hard on each one.  Run it solo for
a club-rig vibe, or alongside ``audio-reactive`` if you want sweeping
color reactivity *plus* punchy beat hits.

Usage::

    dc29 start --enable beat-strobe

Requires the ``[audio]`` extra (sounddevice + numpy) and a working
BlackHole capture device.  See ``CLAUDE.md`` for setup.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from typing import Optional

from dc29.audio import HAS_AUDIO, AudioCapture, AudioFeatures
from dc29.badge import BadgeAPI
from dc29.bridges.base import BaseBridge, BridgePage
from dc29.config import Config, get_config
from dc29.protocol import MuteState
from dc29.throttle import Throttle, fps_to_interval

log = logging.getLogger(__name__)


# Render rate inside a strobe burst.  At 200 Hz with alternating frames
# we get ~100 Hz on/off cycle — well above the perceived-flicker floor
# (~80 Hz) so the eye fuses individual flashes but feels the energy.
RENDER_FPS = 200.0

# Strobe burst duration, in seconds, after each detected beat.  ~50 ms
# is enough to read as a "stab" without bleeding into the next beat at
# typical club tempos (120–140 BPM = 430–500 ms between beats).
BURST_S = 0.050

# Palette cycled through across beats — saturated, high-contrast.
# Each beat advances the index so consecutive beats fire different colors.
_PALETTE: list[tuple[int, int, int]] = [
    (255,   0,   0),   # red
    (255, 100,   0),   # orange
    (255, 200,   0),   # gold
    (  0, 255,   0),   # green
    (  0, 200, 255),   # cyan
    (100,   0, 255),   # violet
]

_WHITE = (255, 255, 255)
_OFF = (0, 0, 0)
_IDLE_BASELINE = (8, 8, 24)   # very dim purple-ish so LEDs don't go pitch-black


class BeatStrobeBridge(BaseBridge):
    """Fires a tight 200 Hz strobe burst on every detected beat."""

    target_app_names = ("beat-strobe",)  # placeholder — bridge isn't focus-driven

    def __init__(self, badge: BadgeAPI, config: Optional[Config] = None) -> None:
        super().__init__(badge)
        cfg = config or get_config()
        self._cfg = cfg
        self._page = BridgePage(
            name="beat-strobe",
            description="Audio-driven 200 Hz beat strobe",
            brand_color=_WHITE,
            buttons={},  # no button claims
        )

        self._capture: Optional[AudioCapture] = None
        # Beat state — written by the PortAudio thread, read by the asyncio loop.
        self._lock = threading.Lock()
        self._burst_until: float = 0.0
        self._color_idx: int = 0
        self._saved_effect: int = 0
        self._owning_leds: bool = False

    @property
    def page(self) -> BridgePage:
        return self._page

    # ------------------------------------------------------------------

    async def run(self) -> None:
        if not HAS_AUDIO:
            log.warning(
                "beat-strobe: numpy + sounddevice not installed.  "
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
            log.warning("beat-strobe: capture init failed (%s) — bridge idle", exc)
            await asyncio.Event().wait()
            return

        try:
            await self._render_loop()
        finally:
            if self._capture is not None:
                self._capture.stop()
                self._capture = None
            if self._saved_effect != 0:
                self._badge.set_effect_mode(self._saved_effect)
                self._saved_effect = 0

    # ------------------------------------------------------------------
    # Audio-thread callback (PortAudio)
    # ------------------------------------------------------------------

    def _on_features(self, features: AudioFeatures) -> None:
        if features.beat:
            now = time.monotonic()
            with self._lock:
                self._burst_until = now + BURST_S
                self._color_idx = (self._color_idx + 1) % len(_PALETTE)
            try:
                from dc29.stats import record
                record.splash_fired()
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Render loop (asyncio)
    # ------------------------------------------------------------------

    async def _render_loop(self) -> None:
        gate = Throttle(fps_to_interval(RENDER_FPS))
        frame_idx = 0

        while True:
            await asyncio.sleep(gate.min_interval / 2)
            if not gate.allow():
                continue

            # Yield to Teams during meetings — never clobber the mute LED.
            if self._badge.state.mute_state != MuteState.NOT_IN_MEETING:
                self._release_if_owning()
                continue

            now = time.monotonic()
            with self._lock:
                in_burst = now < self._burst_until
                color_idx = self._color_idx

            self._engage_if_silent()

            if in_burst:
                # Inside burst: alternate between saturated color, white, off
                # at the render rate so the eye sees rapid pulse train.
                phase = frame_idx % 4
                if phase == 0:
                    c = _WHITE
                elif phase == 1:
                    c = _PALETTE[color_idx]
                elif phase == 2:
                    c = _WHITE
                else:
                    c = _OFF
            else:
                # Idle baseline: dim color so the LEDs aren't pitch black.
                c = _IDLE_BASELINE

            try:
                self._badge.set_all_leds(c, c, c, c)
            except Exception:
                log.exception("beat-strobe: set_all_leds failed")

            frame_idx += 1

    def _engage_if_silent(self) -> None:
        if self._owning_leds:
            return
        cur = self._badge.state.effect_mode
        if cur != 0:
            self._saved_effect = cur
            self._badge.set_effect_mode(0)
        self._owning_leds = True

    def _release_if_owning(self) -> None:
        if not self._owning_leds:
            return
        if self._saved_effect != 0:
            self._badge.set_effect_mode(self._saved_effect)
            self._saved_effect = 0
        self._owning_leds = False
