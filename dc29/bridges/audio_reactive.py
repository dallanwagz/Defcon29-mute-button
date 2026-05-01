"""
dc29.bridges.audio_reactive — LEDs reacting to live system audio.

Captures audio via :mod:`dc29.audio` (BlackHole + FFT) and renders the
4-LED frame at 60 fps.  Optionally pulls Spotify currently-playing for
per-artist palette context — the live audio drives reactivity, Spotify
drives mood.

Why this replaced the original Spotify-reactive bridge: Spotify deprecated
``/audio-analysis`` and ``/audio-features`` for new dev apps on
2024-11-27.  Live FFT via BlackHole achieves the user's goal better
anyway — true real-time response, no third-party deprecation risk, works
with any audio source (Spotify, YouTube, Apple Music, anything).

Design
------

* **Audio thread (PortAudio):** :class:`~dc29.audio.AudioCapture` callback
  computes :class:`~dc29.audio.AudioFeatures` ~43 fps.  Latest snapshot is
  stored thread-safely.
* **Render task (asyncio):** at ~60 fps, reads the latest features and
  emits one ``set_all_leds`` packet per frame.  Beat events fire
  ``fire_takeover`` on a rotating LED.
* **Spotify task (asyncio, optional):** polls currently-playing every
  10 s for track-change notifications (used to refresh the palette + log
  unique tracks heard).  No analysis — just metadata.

Bridge contract
---------------

Inherits :class:`BaseBridge`.  Owns no buttons (presses fall through).
Owns LEDs while audio is loud enough to register.  Yields to Teams during
active meetings (mute LED safety carve-out).

Hot-reloadable via :class:`BridgeManager`.
"""

from __future__ import annotations

import asyncio
import hashlib
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


# Render rate.  60 Hz is smooth on the badge's 4 LEDs without flooding the
# serial port (each frame = 13-byte set_all_leds packet ≈ 0.8 kB/s).
RENDER_FPS = 60.0

# Spotify currently-playing poll interval — only for palette context, so a
# slow poll is fine.
SPOTIFY_POLL_INTERVAL_S = 10.0

# RMS below this is "silence" — we release the LEDs back to whatever was
# running before, so the badge doesn't sit dim during a pause.
RMS_SILENCE_THRESHOLD = 0.02

# How long after the last non-silent frame to keep rendering before
# releasing.  Prevents flapping during quiet passages.
SILENCE_HOLD_S = 1.5


def _hsv_to_rgb(h: float, s: float, v: float) -> tuple[int, int, int]:
    """HSV → RGB.  ``h`` in [0, 360), ``s`` and ``v`` in [0, 1]."""
    h = h % 360
    c = v * s
    x = c * (1 - abs((h / 60) % 2 - 1))
    m = v - c
    if h < 60:    r, g, b = c, x, 0
    elif h < 120: r, g, b = x, c, 0
    elif h < 180: r, g, b = 0, c, x
    elif h < 240: r, g, b = 0, x, c
    elif h < 300: r, g, b = x, 0, c
    else:         r, g, b = c, 0, x
    return (
        max(0, min(255, int((r + m) * 255))),
        max(0, min(255, int((g + m) * 255))),
        max(0, min(255, int((b + m) * 255))),
    )


def _palette_for_artist(artist: str) -> tuple[tuple[int, int, int], ...]:
    """Derive a 4-color palette from the artist name's hash.

    Stable across runs — same artist → same hue family.  Adjacent LEDs
    span ~80° of the hue wheel so the palette reads as "shades of one mood"
    rather than "rainbow chaos".
    """
    if not artist:
        # Default cool-blue palette when we don't know who's playing.
        base_hue = 200.0
    else:
        h = int(hashlib.sha1(artist.encode("utf-8")).hexdigest()[:6], 16)
        base_hue = (h % 360)
    spread = 80.0  # hue range covered across LEDs
    return tuple(
        _hsv_to_rgb(base_hue + spread * (i / 3 - 0.5), 0.9, 1.0)
        for i in range(4)
    )


class AudioReactiveBridge(BaseBridge):
    """LED reactivity from live audio + optional Spotify metadata."""

    target_app_names = ("audio-reactive",)  # not focus-driven; placeholder

    def __init__(self, badge: BadgeAPI, config: Optional[Config] = None) -> None:
        super().__init__(badge)
        cfg = config or get_config()
        self._cfg = cfg

        self._page = BridgePage(
            name="audio-reactive",
            description="Live audio-reactive LED show (BlackHole + FFT)",
            brand_color=(0, 200, 255),
            buttons={},  # no button claims; lower-priority bridges handle them
        )

        self._capture: Optional[AudioCapture] = None
        self._features_lock = threading.Lock()
        self._latest_features: Optional[AudioFeatures] = None
        self._saved_effect: int = 0
        self._led_rotation: int = 0
        self._last_loud_at: float = 0.0
        self._owning_leds: bool = False

        # Spotify-derived palette (refreshed every SPOTIFY_POLL_INTERVAL_S).
        self._palette: tuple[tuple[int, int, int], ...] = _palette_for_artist("")
        self._current_artist: str = ""

    @property
    def page(self) -> BridgePage:
        return self._page

    # ------------------------------------------------------------------

    async def run(self) -> None:
        if not HAS_AUDIO:
            log.warning(
                "audio-reactive: numpy + sounddevice not installed.  "
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
            log.warning("audio-reactive: capture init failed (%s) — bridge idle", exc)
            await asyncio.Event().wait()
            return

        try:
            spotify_task = asyncio.create_task(self._spotify_loop(), name="audio-reactive-spotify")
            render_task = asyncio.create_task(self._render_loop(), name="audio-reactive-render")
            await asyncio.gather(spotify_task, render_task)
        except asyncio.CancelledError:
            raise
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
        with self._features_lock:
            self._latest_features = features

    # ------------------------------------------------------------------
    # Spotify metadata polling (palette context only — no analysis)
    # ------------------------------------------------------------------

    async def _spotify_loop(self) -> None:
        cfg = self._cfg
        if not cfg.spotify_client_id:
            return  # no Spotify configured — palette stays default

        try:
            from dc29.spotify import SpotifyClient
            client = SpotifyClient(cfg.spotify_client_id, cfg.spotify_redirect_uri)
        except Exception:
            log.exception("audio-reactive: Spotify client init failed")
            return

        if not client.has_tokens:
            log.info(
                "audio-reactive: Spotify configured but no token "
                "(palette will stay default — run `dc29 spotify auth` to enable)"
            )
            return

        loop = asyncio.get_running_loop()
        while True:
            try:
                playing = await loop.run_in_executor(None, client.currently_playing)
            except Exception:
                playing = None

            if playing and playing.is_playing and playing.artist:
                if playing.artist != self._current_artist:
                    self._current_artist = playing.artist
                    self._palette = _palette_for_artist(playing.artist)
                    log.info(
                        "audio-reactive: palette → %r",
                        playing.artist,
                    )
                if playing.track_id:
                    try:
                        from dc29.stats import record
                        record.spotify_track_heard(playing.track_id)
                    except Exception:
                        pass

            await asyncio.sleep(SPOTIFY_POLL_INTERVAL_S)

    # ------------------------------------------------------------------
    # Render loop (asyncio)
    # ------------------------------------------------------------------

    async def _render_loop(self) -> None:
        gate = Throttle(fps_to_interval(RENDER_FPS))

        while True:
            await asyncio.sleep(gate.min_interval / 2)
            if not gate.allow():
                continue

            # Yield to Teams during meetings — never clobber the mute LED.
            if self._badge.state.mute_state != MuteState.NOT_IN_MEETING:
                self._release_if_owning()
                continue

            with self._features_lock:
                feat = self._latest_features
            if feat is None:
                continue

            now = time.monotonic()
            loud = feat.rms > RMS_SILENCE_THRESHOLD
            if loud:
                self._last_loud_at = now
                self._engage_if_silent()
            elif now - self._last_loud_at > SILENCE_HOLD_S:
                self._release_if_owning()
                continue

            # Render the frame.
            self._render_frame(feat)

            # Beat splash: a short firmware ripple on a rotating LED.
            if feat.beat:
                led = (self._led_rotation % 4) + 1
                self._led_rotation += 1
                try:
                    self._badge.fire_takeover(led)
                except Exception:
                    pass
                try:
                    from dc29.stats import record
                    record.splash_fired()
                except Exception:
                    pass

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
        # Restore prior firmware effect; don't try to clear LEDs (let the
        # next rendering layer or default state take over).
        if self._saved_effect != 0:
            self._badge.set_effect_mode(self._saved_effect)
            self._saved_effect = 0
        self._owning_leds = False

    def _render_frame(self, feat: AudioFeatures) -> None:
        """Map current features → 4 LED colors → emit one paint-all packet.

        Mapping:
          * Each LED's hue comes from the current palette (artist-derived).
          * Brightness scales with that LED's "responsibility band":
              LED1 = bass    (0–250 Hz, the kick/sub presence)
              LED2 = low-mid (chroma low half ≈ snares + low harmonies)
              LED3 = high-mid (chroma high half ≈ vocals + lead)
              LED4 = treble  (cymbals, hi-hats, sparkle)
          * Final value is multiplied by the overall RMS so quiet passages
            stay subdued and loud passages saturate.
        """
        bass = feat.bass
        chroma = feat.chroma
        # Split chroma into low-half (C..F) and high-half (F#..B) energies.
        low_chroma = float(sum(chroma[:6])) / 6 if chroma else 0.0
        high_chroma = float(sum(chroma[6:])) / 6 if chroma else 0.0
        treble = feat.treble
        rms = max(0.2, feat.rms)  # floor so we don't go fully dark on quiet beats

        bands = (bass, low_chroma * 1.2, high_chroma * 1.2, treble)
        out: list[tuple[int, int, int]] = []
        for i, energy in enumerate(bands):
            base = self._palette[i]
            scale = max(0.05, min(1.0, energy * rms * 1.5))
            out.append((
                max(0, min(255, int(base[0] * scale))),
                max(0, min(255, int(base[1] * scale))),
                max(0, min(255, int(base[2] * scale))),
            ))

        try:
            self._badge.set_all_leds(out[0], out[1], out[2], out[3])
        except Exception:
            log.exception("audio-reactive: set_all_leds failed")
