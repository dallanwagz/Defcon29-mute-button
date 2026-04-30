"""
dc29.badge — Thread-safe interface to the DC29 badge over USB CDC serial.

The :class:`BadgeAPI` class owns the serial connection and a background reader
thread.  All write methods are non-blocking fire-and-forget; badge→host events
are dispatched via registered callbacks that are called from the reader thread.

If you are crossing into asyncio, use ``loop.call_soon_threadsafe`` in your
callbacks.

Example::

    badge = BadgeAPI("/dev/tty.usbmodem14201", brightness=0.4)
    badge.on_button_press = lambda btn, mod, kc: print(f"Button {btn}")
    badge.set_mute_state(MuteState.MUTED)
    ...
    badge.close()
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

try:
    import serial
    from serial import SerialException
except ImportError as _exc:
    raise ImportError("pyserial is required: pip install pyserial") from _exc

from dc29.protocol import (
    ESCAPE,
    CMD_MUTED,
    CMD_UNMUTED,
    CMD_CLEAR,
    CMD_SET_LED,
    CMD_SET_EFFECT,
    CMD_BUTTON_FLASH,
    CMD_SET_KEY,
    CMD_QUERY_KEY,
    EVT_BUTTON,
    EVT_KEY_REPLY,
    EVT_KEY_ACK,
    EVT_EFFECT_MODE,
    EVT_CHORD,
    MuteState,
)

log = logging.getLogger(__name__)

# Argument counts for each incoming event type (bytes after the command byte).
_EVT_ARG_COUNTS: dict[int, int] = {
    EVT_BUTTON:      3,  # n, mod, key
    EVT_KEY_REPLY:   3,  # n, mod, key
    EVT_KEY_ACK:     1,  # n
    EVT_EFFECT_MODE: 1,  # mode
    EVT_CHORD:       1,  # type
}


@dataclass
class BadgeState:
    """Snapshot of all observable badge state.

    Broadcast via :attr:`BadgeAPI.on_state_change` whenever anything changes.
    The TUI subscribes to this single callback rather than wiring up all
    individual callbacks.
    """

    connected: bool = False
    effect_mode: int = 0
    mute_state: MuteState = MuteState.NOT_IN_MEETING
    last_button: Optional[int] = None
    last_chord: Optional[int] = None
    key_map: dict[int, tuple[int, int]] = field(default_factory=dict)
    """button → (modifier, keycode) as last reported by EVT_KEY_REPLY."""

    current_page: Optional[Any] = None
    """The currently active bridge page (a :class:`~dc29.bridges.base.BridgePage`
    or ``None``), updated by the bridge layer via :meth:`BadgeAPI.set_current_page`."""


class BadgeAPI:
    """Thread-safe interface to the DC29 badge over USB CDC serial.

    The port is opened automatically when a write is attempted or when the
    background reader thread first sees it; it is reopened automatically after
    any disconnect.  Callers never need to handle reconnection.

    All ``set_*`` / ``send_*`` methods are non-blocking.  Badge→host events
    are delivered via optional callbacks called from the reader thread.  To
    cross into an asyncio loop, use ``loop.call_soon_threadsafe(...)`` in your
    callbacks, or subscribe to :attr:`on_state_change` for a unified feed.

    Brightness scaling is applied only to :meth:`set_led`; the mute-state
    commands (:meth:`set_mute_state`) always drive LED 4 at full intensity.

    Args:
        port:       Serial port path (e.g. ``"/dev/tty.usbmodem14201"``).
        brightness: Global LED brightness scalar, clamped to ``[0.0, 1.0]``.
                    Applied to :meth:`set_led` calls only.
    """

    def __init__(self, port: str, brightness: float = 1.0) -> None:
        self._port = port
        self._brightness = max(0.0, min(1.0, brightness))
        self._serial: Optional[serial.Serial] = None
        self._lock = threading.Lock()
        self._effect_mode: int = 0

        # Parser state
        self._rx_state: int = 0          # 0=idle, 1=got_escape, 2=collecting
        self._rx_cmd: int = 0
        self._rx_args: list[int] = []
        self._rx_args_needed: int = 0

        # Reader thread
        self._reader_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

        # Current observable state — mutated only from reader thread or _dispatch_rx.
        self._state = BadgeState()

        # ------------------------------------------------------------------
        # Callbacks — all are optional, default None.
        # ------------------------------------------------------------------

        self.on_button_press: Optional[Callable[[int, int, int], None]] = None
        """Called when a button is pressed: ``(button: int, modifier: int, keycode: int)``."""

        self.on_key_reply: Optional[Callable[[int, int, int], None]] = None
        """Called when the badge replies to a key query: ``(button, modifier, keycode)``."""

        self.on_key_ack: Optional[Callable[[int], None]] = None
        """Called when the badge acknowledges a set-key command: ``(button,)``."""

        self.on_effect_mode: Optional[Callable[[int], None]] = None
        """Called when the badge firmware effect mode changes: ``(mode,)``."""

        self.on_chord: Optional[Callable[[int], None]] = None
        """Called when a button chord fires: ``(chord_type,)`` where 1=short, 2=long."""

        self.on_connect: Optional[Callable[[], None]] = None
        """Called from the reader thread each time the serial port opens successfully."""

        self.on_disconnect: Optional[Callable[[], None]] = None
        """Called from the reader thread each time the serial port is lost."""

        self.on_state_change: Optional[Callable[[BadgeState], None]] = None
        """Called after any state change with the full current :class:`BadgeState`.

        Use this in the TUI / bridge layer instead of wiring up every individual
        callback — it fires after the granular callbacks so those still work.
        """

        self.on_page_change: Optional[Callable[[Optional[Any]], None]] = None
        """Called when the active bridge page changes.

        Argument is the new :class:`~dc29.bridges.base.BridgePage` (or ``None``
        when no bridge has focus).  Fired by :meth:`set_current_page`.
        """

        # Start reader immediately so callbacks fire as soon as badge plugs in.
        self._start_reader()

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def connected(self) -> bool:
        """``True`` if the serial port is currently open."""
        return self._serial is not None and self._serial.is_open

    @property
    def port(self) -> str:
        """The serial port path this instance is bound to."""
        return self._port

    @property
    def effect_mode(self) -> int:
        """Locally-tracked firmware effect mode, updated by :data:`~dc29.protocol.EVT_EFFECT_MODE`."""
        return self._effect_mode

    @property
    def state(self) -> BadgeState:
        """A *reference* to the current :class:`BadgeState` (not a copy)."""
        return self._state

    @property
    def brightness(self) -> float:
        """Global LED brightness scalar in ``[0.0, 1.0]``."""
        return self._brightness

    @brightness.setter
    def brightness(self, value: float) -> None:
        self._brightness = max(0.0, min(1.0, value))

    # ------------------------------------------------------------------
    # Public write API
    # ------------------------------------------------------------------

    def set_led(self, n: int, r: int, g: int, b: int) -> None:
        """Set the color of LED *n* (1–4) in RAM (not saved to EEPROM).

        The global brightness scalar is applied to all three components.

        Args:
            n: LED number, 1–4.
            r: Red component, 0–255.
            g: Green component, 0–255.
            b: Blue component, 0–255.
        """
        s = self._brightness
        cmd = bytes([
            ESCAPE, CMD_SET_LED, n & 0xFF,
            int(r * s) & 0xFF,
            int(g * s) & 0xFF,
            int(b * s) & 0xFF,
        ])
        self._write(cmd)

    def set_mute_state(self, state: MuteState) -> None:
        """Drive LED 4 to reflect the Teams meeting mute state.

        LED 4 is always driven at full brightness regardless of the
        :attr:`brightness` setting.

        Args:
            state: One of :class:`~dc29.protocol.MuteState`.
        """
        if state == MuteState.MUTED:
            cmd = bytes([ESCAPE, CMD_MUTED])
        elif state == MuteState.UNMUTED:
            cmd = bytes([ESCAPE, CMD_UNMUTED])
        else:
            cmd = bytes([ESCAPE, CMD_CLEAR])
        self._write(cmd)
        self._state.mute_state = state
        self._fire_state_change()

    def set_current_page(self, page: Any) -> None:
        """Notify observers that the active bridge page has changed.

        Called by :class:`~dc29.bridges.focus.FocusBridge` on focus gain/loss
        and by :class:`~dc29.bridges.teams.TeamsBridge` on meeting start/end.
        The TUI subscribes via :attr:`on_page_change` to update its context pane.

        Args:
            page: The active :class:`~dc29.bridges.base.BridgePage`, or ``None``.
        """
        self._state.current_page = page
        if self.on_page_change is not None:
            try:
                self.on_page_change(page)
            except Exception:
                log.exception("on_page_change callback raised")
        self._fire_state_change()

    def set_effect_mode(self, mode: int) -> None:
        """Set the firmware-driven LED effect mode.

        Args:
            mode: 0=off, 1=rainbow-chase, 2=breathe.
        """
        cmd = bytes([ESCAPE, CMD_SET_EFFECT, mode & 0xFF])
        self._write(cmd)

    def set_button_flash(self, enabled: bool) -> None:
        """Enable or disable the white LED flash on button press.

        Args:
            enabled: ``True`` to enable (firmware default), ``False`` to suppress.
        """
        cmd = bytes([ESCAPE, CMD_BUTTON_FLASH, 1 if enabled else 0])
        self._write(cmd)

    def set_key(self, button: int, modifier: int, keycode: int) -> None:
        """Write a single-key macro for *button* to badge EEPROM.

        The badge will acknowledge with :data:`~dc29.protocol.EVT_KEY_ACK`,
        triggering :attr:`on_key_ack` if registered.

        Args:
            button:   Button number, 1–4 (or 5–6 for slider directions).
            modifier: HID modifier byte.
            keycode:  HID keycode byte.
        """
        cmd = bytes([ESCAPE, CMD_SET_KEY, button & 0xFF, modifier & 0xFF, keycode & 0xFF])
        self._write(cmd)

    def query_key(self, button: int) -> None:
        """Ask the badge to report the current keymap for *button*.

        The badge replies with :data:`~dc29.protocol.EVT_KEY_REPLY`, triggering
        :attr:`on_key_reply` if registered.

        Args:
            button: Button number, 1–6.
        """
        cmd = bytes([ESCAPE, CMD_QUERY_KEY, button & 0xFF])
        self._write(cmd)

    def send_raw(self, data: bytes) -> None:
        """Send arbitrary bytes to the badge (escape hatch).

        Args:
            data: Raw bytes to write.
        """
        self._write(data)

    def close(self) -> None:
        """Shut down the background reader thread and close the serial port."""
        self._stop_event.set()
        with self._lock:
            if self._serial is not None:
                try:
                    self._serial.close()
                except Exception:
                    pass
                self._serial = None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _write(self, cmd: bytes) -> None:
        """Write *cmd* unconditionally."""
        with self._lock:
            self._do_write(cmd)

    def _do_write(self, cmd: bytes) -> None:
        """Low-level write; caller must hold ``_lock``."""
        try:
            self._ensure_open_locked()
            if self._serial is None:
                return
            self._serial.write(cmd)
            self._serial.flush()
        except (SerialException, OSError) as exc:
            log.warning("Badge write failed (%s): will retry on next update.", exc)
            self._close_locked()

    def _ensure_open_locked(self) -> None:
        """Open the serial port if not already open; caller must hold ``_lock``."""
        if self._serial is None or not self._serial.is_open:
            self._serial = serial.Serial(self._port, 9600, timeout=0.1)
            log.debug("Opened serial port %s", self._port)

    def _close_locked(self) -> None:
        """Close and discard the serial port; caller must hold ``_lock``."""
        try:
            if self._serial:
                self._serial.close()
        except Exception:
            pass
        self._serial = None

    def _fire_state_change(self) -> None:
        if self.on_state_change is not None:
            try:
                self.on_state_change(self._state)
            except Exception:
                log.exception("on_state_change callback raised")

    # ------------------------------------------------------------------
    # Background reader thread
    # ------------------------------------------------------------------

    def _start_reader(self) -> None:
        if self._reader_thread is not None and self._reader_thread.is_alive():
            return
        t = threading.Thread(target=self._reader_loop, name="dc29-reader", daemon=True)
        t.start()
        self._reader_thread = t

    def _reader_loop(self) -> None:
        while not self._stop_event.is_set():
            with self._lock:
                if self._serial is None or not self._serial.is_open:
                    try:
                        self._serial = serial.Serial(self._port, 9600, timeout=0.1)
                        log.debug("Reader opened %s", self._port)
                    except (SerialException, OSError) as exc:
                        log.debug("Reader cannot open %s: %s — retrying in 1s", self._port, exc)
                        self._serial = None

            if not self.connected:
                self._stop_event.wait(1.0)
                continue

            self._state.connected = True
            self._fire_state_change()
            if self.on_connect is not None:
                try:
                    self.on_connect()
                except Exception:
                    log.exception("on_connect callback raised")

            disconnected = False
            while not self._stop_event.is_set():
                try:
                    ser = self._serial
                    if ser is None or not ser.is_open:
                        disconnected = True
                        break
                    data = ser.read(1)
                    if data:
                        self._parse_rx(data[0])
                except (SerialException, OSError) as exc:
                    if not self._stop_event.is_set():
                        log.warning("Badge reader error (%s): reconnecting in 1s.", exc)
                    disconnected = True
                    break
                except Exception:
                    log.exception("Unexpected error in reader loop")
                    disconnected = True
                    break

            if disconnected:
                with self._lock:
                    self._close_locked()
                self._state.connected = False
                self._fire_state_change()
                if self.on_disconnect is not None:
                    try:
                        self.on_disconnect()
                    except Exception:
                        log.exception("on_disconnect callback raised")
                if not self._stop_event.is_set():
                    self._stop_event.wait(1.0)

    # ------------------------------------------------------------------
    # Protocol parser
    # ------------------------------------------------------------------

    def _parse_rx(self, b: int) -> None:
        """Consume one byte and advance the parser state machine."""
        if self._rx_state == 0:
            if b == ESCAPE:
                self._rx_state = 1

        elif self._rx_state == 1:
            self._rx_cmd = b
            self._rx_args = []
            args_needed = _EVT_ARG_COUNTS.get(b)
            if args_needed is None:
                self._rx_state = 0
            elif args_needed == 0:
                self._dispatch_rx()
                self._rx_state = 0
            else:
                self._rx_args_needed = args_needed
                self._rx_state = 2

        elif self._rx_state == 2:
            self._rx_args.append(b)
            if len(self._rx_args) >= self._rx_args_needed:
                self._dispatch_rx()
                self._rx_state = 0

    def _dispatch_rx(self) -> None:
        """Dispatch a fully-assembled badge→host event to the appropriate callback."""
        cmd = self._rx_cmd
        args = self._rx_args

        if cmd == EVT_BUTTON and len(args) == 3:
            n, mod, kc = args
            log.info("Button %d pressed — modifier=0x%02X keycode=0x%02X", n, mod, kc)
            self._state.last_button = n
            if self.on_button_press is not None:
                try:
                    self.on_button_press(n, mod, kc)
                except Exception:
                    log.exception("on_button_press callback raised")
            self._fire_state_change()

        elif cmd == EVT_KEY_REPLY and len(args) == 3:
            n, mod, kc = args
            log.info("Key reply for button %d — modifier=0x%02X keycode=0x%02X", n, mod, kc)
            self._state.key_map[n] = (mod, kc)
            if self.on_key_reply is not None:
                try:
                    self.on_key_reply(n, mod, kc)
                except Exception:
                    log.exception("on_key_reply callback raised")
            self._fire_state_change()

        elif cmd == EVT_KEY_ACK and len(args) == 1:
            n = args[0]
            log.info("Key ACK for button %d", n)
            if self.on_key_ack is not None:
                try:
                    self.on_key_ack(n)
                except Exception:
                    log.exception("on_key_ack callback raised")

        elif cmd == EVT_EFFECT_MODE and len(args) == 1:
            mode = args[0]
            self._effect_mode = mode
            self._state.effect_mode = mode
            from dc29.protocol import EFFECT_NAMES
            log.info("Effect mode: %d (%s)", mode, EFFECT_NAMES.get(mode, "unknown"))
            if self.on_effect_mode is not None:
                try:
                    self.on_effect_mode(mode)
                except Exception:
                    log.exception("on_effect_mode callback raised")
            self._fire_state_change()

        elif cmd == EVT_CHORD and len(args) == 1:
            chord_type = args[0]
            log.info("Chord: %s", "long" if chord_type == 2 else "short")
            self._state.last_chord = chord_type
            if self.on_chord is not None:
                try:
                    self.on_chord(chord_type)
                except Exception:
                    log.exception("on_chord callback raised")
            self._fire_state_change()
