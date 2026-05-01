"""
dc29.throttle — Frame-rate throttling for animation streams.

Used by the TUI's paint mode and :class:`SceneRunner` so a slider drag (or
fast keyframe animation) doesn't flood the badge's USB CDC with redundant
updates.  At 60 Hz with the 13-byte paint-all packet, total bandwidth is
under 1 kB/s — but reader-thread pressure on the host is the real limiter,
not the wire.
"""

from __future__ import annotations

import time


class Throttle:
    """Simple wall-clock minimum-interval gate.

    .. code-block:: python

        gate = Throttle(min_interval_s=1 / 60)  # 60 Hz
        for frame in stream:
            if gate.allow():
                badge.set_all_leds(*frame)

    Calls to :meth:`allow` outside the gate window return ``False`` without
    side effects, so callers can decide whether to drop the frame, coalesce,
    or just skip the work.
    """

    def __init__(self, min_interval_s: float) -> None:
        self.min_interval = float(min_interval_s)
        self._last = 0.0

    def allow(self) -> bool:
        """Return ``True`` if at least ``min_interval`` has elapsed since the last allow."""
        now = time.monotonic()
        if now - self._last >= self.min_interval:
            self._last = now
            return True
        return False

    def reset(self) -> None:
        """Forget the last-allow timestamp so the next :meth:`allow` returns ``True``."""
        self._last = 0.0


def fps_to_interval(fps: float) -> float:
    """Convert a frame rate (Hz) to a minimum interval (seconds)."""
    if fps <= 0:
        return 0.0
    return 1.0 / fps
