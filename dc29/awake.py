"""dc29.awake — F08b session state shared between bridge, TUI, and CLI.

Single source of truth for the Stay Awake feature.  The bridge, the TUI
tab, and the CLI subcommand group all read and mutate this module-level
singleton.

Lifecycle
---------
Idle → :meth:`AwakeState.start_session` → Active(end_ts, led_mode) →
expires (auto) or :meth:`AwakeState.stop_session` → Idle.

Only one active session at a time.  Starting a new session while one is
active replaces the old one.

Cross-process pointer (headless CLI only)
-----------------------------------------
When ``dc29 awake start`` is invoked WITHOUT a running ``dc29 start``
process, the CLI sets the badge's autonomous timer directly and writes a
tiny pointer file (``~/.config/dc29/awake_session.json``) so a later
``dc29 awake status`` from any shell can still report the projected end
time.  The bridge process ignores this file — when both run, the
in-process singleton wins.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Callable, Optional

log = logging.getLogger(__name__)


# Hard ceiling on a single session — matches the F08 Q6 default-accept of
# 1m..24h for the TUI custom field.  CLI is allowed to go higher (up to
# the firmware's 2**32 - 1 cap) since power-users may want a multi-day run.
MAX_TUI_DURATION_SECS = 24 * 60 * 60
MAX_DURATION_SECS = 2**32 - 1

# "Indefinite" maps to a very large but finite duration.  Per F08 Q2,
# default-accept is "no cap".  We pick u32-max so the firmware sees
# basically forever; the TUI displays "Indefinite" instead of HH:MM:SS.
INDEFINITE_SECS = MAX_DURATION_SECS

# Where the headless pointer file lives.  Keep it next to the regular
# dc29 config so users find it together.
SESSION_FILE = Path.home() / ".config" / "dc29" / "awake_session.json"

# Last-used preferences (duration + LED mode) so the TUI preselects them
# next launch.  Tiny JSON; not part of config.toml because it changes
# every session and config.toml is meant to be hand-editable.
PREFS_FILE = Path.home() / ".config" / "dc29" / "awake_prefs.json"


class LedMode(str, Enum):
    """LED visualization while a Stay Awake session is active."""

    OFF = "off"                     # bridge does not touch LEDs
    CYAN_PULSE = "cyan_pulse"       # slow 0.5 Hz pulse on LED 1 only
    PROGRESS_BAR = "progress_bar"   # 4-LED elapsed/total bar
    EFFECT_MODE = "effect_mode"     # delegate to a firmware effect mode

    @classmethod
    def parse(cls, value: str | None, *, default: "LedMode" = None) -> "LedMode":
        """Best-effort parse from a string; falls back to *default* (or OFF)."""
        if value is None:
            return default or cls.OFF
        v = str(value).strip().lower().replace("-", "_")
        for m in cls:
            if m.value == v:
                return m
        return default or cls.OFF


@dataclass
class AwakeSession:
    """One active Stay Awake session.  Immutable once created."""

    started_ts: float                 # time.time() at start
    duration_secs: int                # original requested duration
    led_mode: LedMode = LedMode.OFF
    effect_mode_id: int = 1           # only used when led_mode == EFFECT_MODE

    @property
    def end_ts(self) -> float:
        return self.started_ts + self.duration_secs

    def remaining_secs(self, now: Optional[float] = None) -> float:
        if now is None:
            now = time.time()
        return max(0.0, self.end_ts - now)

    def elapsed_secs(self, now: Optional[float] = None) -> float:
        if now is None:
            now = time.time()
        return max(0.0, now - self.started_ts)

    def progress(self, now: Optional[float] = None) -> float:
        """Return fraction elapsed in [0, 1]."""
        if self.duration_secs <= 0:
            return 1.0
        return min(1.0, self.elapsed_secs(now) / float(self.duration_secs))

    def is_expired(self, now: Optional[float] = None) -> bool:
        if now is None:
            now = time.time()
        return now >= self.end_ts

    def is_indefinite(self) -> bool:
        return self.duration_secs >= INDEFINITE_SECS // 2


@dataclass
class AwakePreferences:
    """User preferences persisted across sessions."""

    last_duration_secs: int = 60 * 60   # 1 hour
    last_led_mode: LedMode = LedMode.OFF
    last_effect_mode_id: int = 1


class AwakeState:
    """Process-wide singleton coordinating Stay Awake session state.

    Threadsafe — TUI, bridge, and CLI may all touch this from different
    coroutines or threads.  All mutations fire any registered observers
    (used by the TUI to redraw the countdown).
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._session: Optional[AwakeSession] = None
        self._prefs = AwakePreferences()
        self._observers: list[Callable[[], None]] = []

    # ------------------------------------------------------------------
    # Session control
    # ------------------------------------------------------------------

    @property
    def session(self) -> Optional[AwakeSession]:
        """Return the current session, or None if idle."""
        with self._lock:
            s = self._session
            if s is not None and s.is_expired():
                self._session = None
                self._notify()
                return None
            return s

    @property
    def active(self) -> bool:
        return self.session is not None

    def start_session(
        self,
        duration_secs: int,
        led_mode: LedMode = LedMode.OFF,
        effect_mode_id: int = 1,
    ) -> AwakeSession:
        """Start (or restart) a session for *duration_secs* seconds."""
        if duration_secs <= 0:
            raise ValueError(f"duration_secs must be positive, got {duration_secs}")
        if duration_secs > MAX_DURATION_SECS:
            duration_secs = MAX_DURATION_SECS
        s = AwakeSession(
            started_ts=time.time(),
            duration_secs=int(duration_secs),
            led_mode=led_mode,
            effect_mode_id=int(effect_mode_id),
        )
        with self._lock:
            self._session = s
            # Update preferences so the next TUI launch preselects these.
            self._prefs.last_duration_secs = int(duration_secs)
            self._prefs.last_led_mode = led_mode
            self._prefs.last_effect_mode_id = int(effect_mode_id)
            new_prefs = AwakePreferences(
                last_duration_secs=self._prefs.last_duration_secs,
                last_led_mode=self._prefs.last_led_mode,
                last_effect_mode_id=self._prefs.last_effect_mode_id,
            )
        write_prefs(new_prefs)
        self._notify()
        return s

    def stop_session(self) -> None:
        """Stop the current session immediately (no-op if idle)."""
        with self._lock:
            if self._session is None:
                return
            self._session = None
        self._notify()

    # ------------------------------------------------------------------
    # Preferences
    # ------------------------------------------------------------------

    @property
    def prefs(self) -> AwakePreferences:
        with self._lock:
            return AwakePreferences(
                last_duration_secs=self._prefs.last_duration_secs,
                last_led_mode=self._prefs.last_led_mode,
                last_effect_mode_id=self._prefs.last_effect_mode_id,
            )

    def load_prefs(self, prefs: AwakePreferences) -> None:
        with self._lock:
            self._prefs = prefs

    # ------------------------------------------------------------------
    # Observers
    # ------------------------------------------------------------------

    def add_observer(self, fn: Callable[[], None]) -> None:
        with self._lock:
            self._observers.append(fn)

    def remove_observer(self, fn: Callable[[], None]) -> None:
        with self._lock:
            try:
                self._observers.remove(fn)
            except ValueError:
                pass

    def _notify(self) -> None:
        # Snapshot under lock; call outside.
        with self._lock:
            obs = list(self._observers)
        for fn in obs:
            try:
                fn()
            except Exception:
                log.exception("AwakeState observer raised")


# Module-level singleton.
_state: Optional[AwakeState] = None


def get_state() -> AwakeState:
    """Return the process-wide :class:`AwakeState` singleton."""
    global _state
    if _state is None:
        _state = AwakeState()
        # Load persisted prefs so the TUI preselects last-used values.
        try:
            _state.load_prefs(read_prefs())
        except Exception:
            log.exception("get_state: prefs load failed (continuing with defaults)")
    return _state


# ----------------------------------------------------------------------
# Headless pointer file (used only by `dc29 awake start/status` when no
# bridge process is running).
# ----------------------------------------------------------------------

def write_pointer(session: AwakeSession) -> None:
    """Persist the active session to disk so other shells can read it."""
    try:
        SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
        payload = asdict(session)
        payload["led_mode"] = session.led_mode.value
        SESSION_FILE.write_text(json.dumps(payload, indent=2))
    except OSError:
        log.exception("write_pointer failed")


def clear_pointer() -> None:
    try:
        SESSION_FILE.unlink(missing_ok=True)
    except OSError:
        log.exception("clear_pointer failed")


def write_prefs(prefs: AwakePreferences) -> None:
    try:
        PREFS_FILE.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "last_duration_secs": int(prefs.last_duration_secs),
            "last_led_mode": prefs.last_led_mode.value,
            "last_effect_mode_id": int(prefs.last_effect_mode_id),
        }
        PREFS_FILE.write_text(json.dumps(payload, indent=2))
    except OSError:
        log.exception("write_prefs failed")


def read_prefs() -> AwakePreferences:
    if not PREFS_FILE.exists():
        return AwakePreferences()
    try:
        raw = json.loads(PREFS_FILE.read_text())
        return AwakePreferences(
            last_duration_secs=int(raw.get("last_duration_secs", 3600)),
            last_led_mode=LedMode.parse(raw.get("last_led_mode")),
            last_effect_mode_id=int(raw.get("last_effect_mode_id", 1)),
        )
    except (OSError, ValueError, TypeError):
        log.exception("read_prefs: malformed file")
        return AwakePreferences()


def read_pointer() -> Optional[AwakeSession]:
    """Return the session described by the pointer file, or None."""
    if not SESSION_FILE.exists():
        return None
    try:
        raw = json.loads(SESSION_FILE.read_text())
        s = AwakeSession(
            started_ts=float(raw["started_ts"]),
            duration_secs=int(raw["duration_secs"]),
            led_mode=LedMode.parse(raw.get("led_mode")),
            effect_mode_id=int(raw.get("effect_mode_id", 1)),
        )
    except (OSError, KeyError, ValueError, TypeError):
        log.exception("read_pointer: malformed file")
        return None
    if s.is_expired():
        clear_pointer()
        return None
    return s
