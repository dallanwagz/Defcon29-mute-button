"""dc29.bridges.stay_awake — F08b "Stay Awake" session bridge.

Owns the host-side session timer, the heartbeat that keeps macOS awake
via ``BadgeAPI.awake_pulse`` (F08a-lite), and the optional LED
visualization while a session is active.

Architecture
------------
- Session state lives in :mod:`dc29.awake` as a process-wide singleton.
  The TUI tab and CLI commands mutate it via
  :meth:`~dc29.awake.AwakeState.start_session` /
  :meth:`~dc29.awake.AwakeState.stop_session`.
- This bridge polls the singleton at ~10 Hz, fires a host-side jiggle
  every 30 s (path 2 of F08), refreshes the badge's autonomous timer
  every 60 s as a safety net, and renders the selected LED mode.
- Cleanly yields LEDs when:
    * Teams is in a meeting (let the mute LED through).
    * Audio-reactive bridge is running (highest claim, per existing
      convention).

Graceful shutdown sends ``awake_cancel`` so the badge stops jiggling
within ~30 s of the bridge dying.

The bridge claims **no buttons**.  All session control happens via the
TUI, the CLI, or external automation.
"""

from __future__ import annotations

import asyncio
import logging
import math
import time
from typing import Optional

from dc29.awake import AwakeSession, LedMode, get_state
from dc29.badge import BadgeAPI
from dc29.bridges.base import BaseBridge, BridgePage
from dc29.config import Config, get_config
from dc29.protocol import MuteState

log = logging.getLogger(__name__)


# Cadence constants — per F08 design Q5 (default-accept).  The badge
# autonomously jiggles every 30 s anyway (F08a-lite firmware constant);
# the host-side heartbeat is belt-and-braces against badge timer drift
# and lets us refresh the autonomous end-time from the host clock.
HOST_PULSE_PERIOD_S = 30.0
BADGE_REFRESH_PERIOD_S = 60.0

# How often the bridge wakes up to check session state and render LEDs.
TICK_INTERVAL_S = 0.5

# LED visualization tunables.
CYAN = (0, 200, 255)
DIM_CYAN = (0, 24, 32)
LED_OFF = (0, 0, 0)
PULSE_HZ = 0.5            # cyan-pulse mode — slow breathing on LED 1
PROGRESS_FILL = CYAN
PROGRESS_EMPTY = DIM_CYAN


class StayAwakeBridge(BaseBridge):
    """Run the Stay Awake session timer + heartbeat + LED visualization."""

    target_app_names = ("stay-awake",)  # not focus-driven

    def __init__(self, badge: BadgeAPI, config: Optional[Config] = None) -> None:
        super().__init__(badge)
        self._cfg = config or get_config()
        self._state = get_state()
        self._page = BridgePage(
            name="stay-awake",
            description="Keep the host awake (Amphetamine-style) with optional LED viz",
            buttons={},  # no button claims
        )

        # Heartbeat bookkeeping.
        self._last_host_pulse: float = 0.0
        self._last_badge_refresh: float = 0.0
        self._owns_leds: bool = False
        self._saved_effect: int = 0
        self._effect_started: bool = False
        # Track which session we sent the badge — when start() is called
        # for a new session, push the new duration immediately.
        self._badge_session_id: Optional[float] = None  # session.started_ts

    @property
    def page(self) -> BridgePage:
        return self._page

    # ------------------------------------------------------------------

    async def run(self) -> None:
        log.info("StayAwake bridge started; waiting for sessions")
        try:
            while True:
                await asyncio.sleep(TICK_INTERVAL_S)
                await self._tick()
        except asyncio.CancelledError:
            log.info("StayAwake bridge stopping; cancelling badge autonomous mode")
            try:
                self._badge.awake_cancel()
            except Exception:
                log.exception("awake_cancel on shutdown failed")
            self._release_leds()
            raise

    # ------------------------------------------------------------------
    # Tick
    # ------------------------------------------------------------------

    async def _tick(self) -> None:
        session = self._state.session
        if session is None:
            self._on_idle()
            return

        # If session changed (or is brand-new to this bridge), push the
        # full remaining duration to the badge as a safety net.
        if self._badge_session_id != session.started_ts:
            self._badge_session_id = session.started_ts
            self._send_badge_refresh(session)
            # Fire one immediate pulse so idle resets right away.
            self._send_host_pulse()
            self._last_host_pulse = time.monotonic()
            self._last_badge_refresh = time.monotonic()
            self._on_session_start(session)
            return

        now = time.monotonic()

        # Periodic host-side jiggle.
        if (now - self._last_host_pulse) >= HOST_PULSE_PERIOD_S:
            self._send_host_pulse()
            self._last_host_pulse = now

        # Periodic refresh of the badge's autonomous end-time.
        if (now - self._last_badge_refresh) >= BADGE_REFRESH_PERIOD_S:
            self._send_badge_refresh(session)
            self._last_badge_refresh = now

        # LED render.
        self._render_leds(session)

    # ------------------------------------------------------------------
    # State transitions
    # ------------------------------------------------------------------

    def _on_session_start(self, session: AwakeSession) -> None:
        """Called once when a new session enters this bridge's view."""
        # Suppress takeover so progress-bar / effect-mode renders survive
        # button presses.  Restored in _release_leds.
        if session.led_mode != LedMode.OFF:
            try:
                self._badge.set_button_flash(False)
            except Exception:
                log.exception("set_button_flash(False) failed")

    def _on_idle(self) -> None:
        """Called every tick while no session is active."""
        if self._badge_session_id is not None:
            # Just transitioned active → idle (expired or stopped).
            self._badge_session_id = None
            try:
                self._badge.awake_cancel()
            except Exception:
                log.exception("awake_cancel on idle transition failed")
            self._release_leds()

    # ------------------------------------------------------------------
    # Badge I/O wrappers
    # ------------------------------------------------------------------

    def _send_host_pulse(self) -> None:
        try:
            self._badge.awake_pulse()
        except Exception:
            log.exception("awake_pulse failed")

    def _send_badge_refresh(self, session: AwakeSession) -> None:
        remaining = int(math.ceil(session.remaining_secs()))
        if remaining <= 0:
            return
        try:
            self._badge.awake_set_duration(remaining)
        except Exception:
            log.exception("awake_set_duration(%d) failed", remaining)

    # ------------------------------------------------------------------
    # LED visualization
    # ------------------------------------------------------------------

    def _render_leds(self, session: AwakeSession) -> None:
        # Yield to Teams during meetings — never clobber the mute LED.
        if self._badge.state.mute_state != MuteState.NOT_IN_MEETING:
            self._release_leds()
            return

        mode = session.led_mode

        if mode == LedMode.OFF:
            self._release_leds()
            return

        if mode == LedMode.EFFECT_MODE:
            self._render_effect_mode(session)
            return

        # Custom rendering modes: claim LED ownership, then write.
        self._engage_leds()

        if mode == LedMode.CYAN_PULSE:
            self._render_cyan_pulse()
        elif mode == LedMode.PROGRESS_BAR:
            self._render_progress_bar(session)

    def _render_cyan_pulse(self) -> None:
        # Slow sine on LED 1 between dim-cyan and saturated cyan; LEDs 2-4
        # restored to off (we don't know the user's prior colors, so
        # leaving them dim is the least surprising).
        phase = (math.sin(2.0 * math.pi * PULSE_HZ * time.monotonic()) + 1.0) / 2.0
        r = int(CYAN[0] * phase)
        g = int(DIM_CYAN[1] + (CYAN[1] - DIM_CYAN[1]) * phase)
        b = int(DIM_CYAN[2] + (CYAN[2] - DIM_CYAN[2]) * phase)
        try:
            self._badge.set_led(1, r, g, b)
        except Exception:
            log.exception("cyan_pulse set_led failed")

    def _render_progress_bar(self, session: AwakeSession) -> None:
        # 4 LEDs encode elapsed/total: full-bright cyan for completed
        # quarters, dim cyan for not-yet.
        progress = session.progress()    # 0..1
        filled_f = progress * 4.0
        try:
            for i in range(4):
                if (i + 1) <= int(filled_f):
                    color = PROGRESS_FILL
                elif i < filled_f:
                    # Partial: scale the leading LED by the fractional bit.
                    frac = filled_f - i
                    color = (
                        int(PROGRESS_FILL[0] * frac + PROGRESS_EMPTY[0] * (1 - frac)),
                        int(PROGRESS_FILL[1] * frac + PROGRESS_EMPTY[1] * (1 - frac)),
                        int(PROGRESS_FILL[2] * frac + PROGRESS_EMPTY[2] * (1 - frac)),
                    )
                else:
                    color = PROGRESS_EMPTY
                self._badge.set_led(i + 1, *color)
        except Exception:
            log.exception("progress_bar set_led failed")

    def _render_effect_mode(self, session: AwakeSession) -> None:
        # Effect modes are firmware-side; just set once.
        if self._effect_started:
            return
        try:
            cur = self._badge.state.effect_mode
            if cur != session.effect_mode_id:
                self._saved_effect = cur
                self._badge.set_effect_mode(session.effect_mode_id)
            self._effect_started = True
        except Exception:
            log.exception("set_effect_mode failed")

    def _engage_leds(self) -> None:
        if self._owns_leds:
            return
        # If the user had an effect mode running, save it so we can restore.
        try:
            cur = self._badge.state.effect_mode
            if cur != 0:
                self._saved_effect = cur
                self._badge.set_effect_mode(0)
        except Exception:
            log.exception("engage_leds: effect_mode read failed")
        self._owns_leds = True

    def _release_leds(self) -> None:
        if not self._owns_leds and not self._effect_started:
            return
        try:
            if self._effect_started or self._saved_effect != 0:
                self._badge.set_effect_mode(self._saved_effect)
                self._saved_effect = 0
                self._effect_started = False
            if self._owns_leds:
                # Best-effort: turn LEDs off; user can repaint via TUI.
                for i in range(1, 5):
                    self._badge.set_led(i, 0, 0, 0)
                self._badge.set_button_flash(True)
        except Exception:
            log.exception("release_leds failed")
        self._owns_leds = False
