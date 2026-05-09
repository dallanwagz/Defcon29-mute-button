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
    CMD_FIRE_TAKEOVER,
    CMD_PAINT_ALL,
    CMD_SET_SLIDER,
    CMD_SET_SPLASH,
    CMD_BEEP_PATTERN,
    CMD_HAPTIC_CLICK,
    CMD_HID_BURST,
    CMD_JIGGLER,
    CMD_MOD_TABLE,
    MAX_BURST_PAIRS,
    CMD_SET_KEY,
    CMD_QUERY_KEY,
    CMD_WLED_SET,
    EVT_BUTTON,
    EVT_BUTTON_EXT,
    EVT_KEY_REPLY,
    EVT_KEY_ACK,
    EVT_EFFECT_MODE,
    EVT_CHORD,
    MuteState,
)

log = logging.getLogger(__name__)


# ----------------------------------------------------------------------
# ASCII → HID Usage ID conversion (for F06 type_string convenience).
# Reference: HID Usage Tables, page 7 (Keyboard / Keypad).  US layout.
# ----------------------------------------------------------------------

_HID_MOD_LSHIFT = 0x02

# Unshifted printable map.  Values are HID Usage IDs.
_ASCII_UNSHIFTED: dict[str, int] = {
    **{ch: 4 + i for i, ch in enumerate("abcdefghijklmnopqrstuvwxyz")},
    "1": 0x1E, "2": 0x1F, "3": 0x20, "4": 0x21, "5": 0x22,
    "6": 0x23, "7": 0x24, "8": 0x25, "9": 0x26, "0": 0x27,
    "\n": 0x28, "\t": 0x2B, " ": 0x2C,
    "-": 0x2D, "=": 0x2E, "[": 0x2F, "]": 0x30, "\\": 0x31,
    ";": 0x33, "'": 0x34, "`": 0x35, ",": 0x36, ".": 0x37, "/": 0x38,
}

# Shifted-only printable map (each maps to (key, with_shift=True)).
_ASCII_SHIFTED: dict[str, int] = {
    **{ch: 4 + i for i, ch in enumerate("ABCDEFGHIJKLMNOPQRSTUVWXYZ")},
    "!": 0x1E, "@": 0x1F, "#": 0x20, "$": 0x21, "%": 0x22,
    "^": 0x23, "&": 0x24, "*": 0x25, "(": 0x26, ")": 0x27,
    "_": 0x2D, "+": 0x2E, "{": 0x2F, "}": 0x30, "|": 0x31,
    ":": 0x33, '"': 0x34, "~": 0x35, "<": 0x36, ">": 0x37, "?": 0x38,
}


def _ascii_to_hid_pair(ch: str) -> Optional[tuple[int, int]]:
    """Return ``(modifier, keycode)`` for one ASCII char, or ``None`` if
    no mapping exists (control chars beyond newline/tab, non-ASCII)."""
    if ch in _ASCII_UNSHIFTED:
        return (0, _ASCII_UNSHIFTED[ch])
    if ch in _ASCII_SHIFTED:
        return (_HID_MOD_LSHIFT, _ASCII_SHIFTED[ch])
    return None


# Argument counts for each incoming event type (bytes after the command byte).
_EVT_ARG_COUNTS: dict[int, int] = {
    EVT_BUTTON:      3,  # n, mod, key
    EVT_KEY_REPLY:   3,  # n, mod, key
    EVT_KEY_ACK:     1,  # n
    EVT_EFFECT_MODE: 1,  # mode
    EVT_CHORD:       1,  # type
    # EVT_BUTTON_EXT is variable-length (3 or 4 bytes after escape).
    # We special-case it in _parse_rx after the kind byte arrives.
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


@dataclass
class _ButtonHandler:
    """Internal registration record for a priority-ordered button handler.

    Bridges register one of these via :meth:`BadgeAPI.add_button_handler` when
    they install their button hook, and remove it when they tear down.  The
    reader thread iterates the handler list in priority order on every
    EVT_BUTTON; the first handler whose ``owned_buttons`` includes the press
    AND whose ``should_handle`` returns ``True`` gets to handle it.  If none
    do, :attr:`BadgeAPI.on_button_press` (the public fallback slot) fires.
    """

    name: str
    """Human label, used for log messages.  Typically the bridge/page name."""

    priority: int
    """Higher = called first.  Sorted descending on registration."""

    owned_buttons: set[int]
    """Button numbers (1–4) this handler claims interest in."""

    should_handle: Callable[[int], bool]
    """Late filter — e.g. ``FocusBridge`` only returns True while focused."""

    handler: Callable[[int, int, int], None]
    """Called with ``(button, modifier, keycode)`` when this handler claims a press."""


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

        # Extended button events from F01/F02.  Callback signature:
        #   on_button_ext(kind: str, btn_a: int, btn_b: int | None)
        # where kind is one of "double", "triple", "long", "chord".
        # btn_b is None for non-chord events.
        self.on_button_ext: Optional[Callable[[str, int, Optional[int]], None]] = None
        """Fallback button-press callback.

        Fired only when no registered :class:`_ButtonHandler` (added via
        :meth:`add_button_handler`) claims the press.  Use this for
        diagnostics / logging — bridges should register a handler instead so
        they can hot-add and hot-remove without disturbing the chain.
        """

        # Priority-ordered registry of button handlers.  The reader thread
        # iterates this on every EVT_BUTTON; the asyncio loop mutates it via
        # add_button_handler / remove_button_handler.  The lock keeps a
        # snapshot consistent across the iterate-and-call sequence so
        # registration churn during a press doesn't crash the reader.
        self._button_handlers: list[_ButtonHandler] = []
        self._button_handlers_lock = threading.Lock()

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

    def set_all_leds(
        self,
        c1: tuple[int, int, int],
        c2: tuple[int, int, int],
        c3: tuple[int, int, int],
        c4: tuple[int, int, int],
    ) -> None:
        """Paint all four LEDs atomically in a single packet.

        Sends ``0x01 'P' r1 g1 b1 r2 g2 b2 r3 g3 b3 r4 g4 b4`` (13 bytes total).
        Use this instead of four separate :meth:`set_led` calls for animation
        streams: the badge applies all four colors in one main-loop iteration
        so frames don't tear, and you halve the per-frame serial cost.

        The brightness scalar is applied to every component.

        Args:
            c1, c2, c3, c4: Each a ``(r, g, b)`` triple, components 0–255.
        """
        s = self._brightness
        payload = bytearray([ESCAPE, CMD_PAINT_ALL])
        for (r, g, b) in (c1, c2, c3, c4):
            payload.append(int(r * s) & 0xFF)
            payload.append(int(g * s) & 0xFF)
            payload.append(int(b * s) & 0xFF)
        self._write(bytes(payload))

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
            mode: see :class:`~dc29.protocol.EffectMode` (0=off through 34=sinelon).
        """
        cmd = bytes([ESCAPE, CMD_SET_EFFECT, mode & 0xFF])
        self._write(cmd)

    def set_wled(
        self,
        speed: int = 128,
        intensity: int = 128,
        palette: int = 0,
    ) -> None:
        """Set the WLED-effect runtime knobs (modes 19+).

        Mirrors WLED's ``/win&SX=&IX=&FP=`` HTTP API: speed controls the
        timebase, intensity is the per-effect "amount" (fade rate, sparkle
        density, wave width depending on the effect), and palette picks one
        of :class:`~dc29.protocol.WledPalette`.

        Has no effect on hand-rolled modes 1–18.  Settings are RAM-only and
        reset to defaults (speed=128, intensity=128, palette=RAINBOW) on
        firmware boot.

        Args:
            speed:     0–255, controls timebase for most effects.
            intensity: 0–255, per-effect "amount" knob.
            palette:   :class:`~dc29.protocol.WledPalette` index; out-of-range
                values wrap modulo the firmware's palette count.
        """
        cmd = bytes([
            ESCAPE,
            CMD_WLED_SET,
            speed & 0xFF,
            intensity & 0xFF,
            palette & 0xFF,
        ])
        self._write(cmd)

    # ------------------------------------------------------------------
    # Button handler registry — used by bridges to claim button presses
    # ------------------------------------------------------------------

    def add_button_handler(
        self,
        *,
        name: str,
        priority: int,
        owned_buttons,
        should_handle: Callable[[int], bool],
        handler: Callable[[int, int, int], None],
    ) -> _ButtonHandler:
        """Register a priority-ordered button handler.

        Use this from bridges instead of mutating :attr:`on_button_press`.
        Higher ``priority`` runs first; ties keep insertion order.  The
        returned :class:`_ButtonHandler` is the cookie to pass back to
        :meth:`remove_button_handler` for clean teardown.

        Thread-safe: registration and removal can happen from any thread,
        and the reader thread snapshots the list before iterating so a press
        landing mid-mutation is dispatched against a consistent view.
        """
        record = _ButtonHandler(
            name=name,
            priority=priority,
            owned_buttons=set(owned_buttons),
            should_handle=should_handle,
            handler=handler,
        )
        with self._button_handlers_lock:
            self._button_handlers.append(record)
            self._button_handlers.sort(key=lambda h: h.priority, reverse=True)
        return record

    def remove_button_handler(self, record: _ButtonHandler) -> None:
        """Deregister a handler previously added via :meth:`add_button_handler`."""
        with self._button_handlers_lock:
            try:
                self._button_handlers.remove(record)
            except ValueError:
                pass

    def set_button_flash(self, enabled: bool) -> None:
        """Enable or disable the white LED flash on button press.

        Args:
            enabled: ``True`` to enable (firmware default), ``False`` to suppress.
        """
        cmd = bytes([ESCAPE, CMD_BUTTON_FLASH, 1 if enabled else 0])
        self._write(cmd)

    def fire_takeover(self, button: int) -> None:
        """Fire the firmware ripple animation for *button* on demand.

        Use this when ``button_flash`` is suppressed (because a bridge owns the
        LEDs) but you still want the satisfying ripple feedback for a specific
        action — e.g. a destructive button (B4 by positional convention) when
        the bridge handles the action via pynput rather than letting the
        firmware HID keymap fire.

        Args:
            button: 1–4. Out-of-range values are silently ignored by firmware.
        """
        if button < 1 or button > 4:
            return
        cmd = bytes([ESCAPE, CMD_FIRE_TAKEOVER, button & 0xFF])
        self._write(cmd)

    def set_slider_enabled(self, enabled: bool) -> None:
        """Enable or disable the capacitive touch slider's volume injections.

        When disabled, swiping the slider does nothing.  Firmware default is
        enabled, and this is RAM-only — the slider is back on after every
        power cycle.

        Args:
            enabled: ``True`` to enable (firmware default), ``False`` to suppress.
        """
        cmd = bytes([ESCAPE, CMD_SET_SLIDER, 1 if enabled else 0])
        self._write(cmd)

    def set_splash_on_press(self, enabled: bool) -> None:
        """Enable or disable the interactive splash-on-press animation.

        When enabled, pressing a button during a firmware effect mode fires a
        ~300 ms localized color-spray animation that captures the pressed LED's
        current color and sprays outward.  Designed for "RGB toy" / fidget use.

        Firmware default is enabled.  RAM-only — re-applied on every dc29
        startup if the user has it set in :attr:`Config.splash_on_press`.

        Args:
            enabled: ``True`` to enable (firmware default), ``False`` to suppress.
        """
        cmd = bytes([ESCAPE, CMD_SET_SPLASH, 1 if enabled else 0])
        self._write(cmd)

    def set_haptic_click(self, enabled: bool) -> None:
        """Enable or disable the F03 haptic buzzer click on macro send.

        When enabled, every ``send_keys()`` invocation that emits at least one
        HID report ends with a brief, high-pitch buzzer click — non-visual
        confirmation that the keystroke fired.  The click is suppressed
        automatically while ``button_flash`` is enabled, since the takeover
        animation already produces its own click during phase 1.

        The intended use case is bridges that have called
        :meth:`set_button_flash(False)` to take over LEDs — they lose the
        built-in click and can call this to restore haptic feedback.

        Firmware default is enabled.  RAM-only — re-applied on every dc29
        startup if the user has it set.

        Args:
            enabled: ``True`` to enable (firmware default), ``False`` to suppress.
        """
        cmd = bytes([ESCAPE, CMD_HAPTIC_CLICK, 1 if enabled else 0])
        self._write(cmd)

    def hid_burst(self, pairs) -> None:
        """Fire a back-to-back HID burst on the badge (F06).

        Args:
            pairs: Iterable of ``(modifier, keycode)`` tuples.  Both bytes
                use the same encoding as the per-button keymap (modifier
                is a HID modifier bitmap; keycode is a HID Usage ID).
                Payloads longer than :data:`~dc29.protocol.MAX_BURST_PAIRS`
                (256) are split into successive bursts automatically.

        Each pair is held for 4 × 10 ms frames on the firmware side
        (modifier-down, key-down, key-up, modifier-up), so the wall-clock
        cost is roughly ``len(pairs) * 40 ms``.  The badge's main loop
        keeps running during the burst (LED ticks, button polling, beep
        engine — see DESIGN.md §5).
        """
        flat: list[int] = []
        for mod, key in pairs:
            flat.append(int(mod) & 0xFF)
            flat.append(int(key) & 0xFF)
        # Chunk into MAX_BURST_PAIRS-sized bursts.  Within each chunk the
        # 16-bit length is little-endian.
        i = 0
        n_pairs_total = len(flat) // 2
        while i < n_pairs_total:
            chunk_n = min(MAX_BURST_PAIRS, n_pairs_total - i)
            buf = bytearray()
            buf.append(ESCAPE)
            buf.append(CMD_HID_BURST)
            buf.append(chunk_n & 0xFF)
            buf.append((chunk_n >> 8) & 0xFF)
            buf.extend(flat[i * 2 : (i + chunk_n) * 2])
            self._write(bytes(buf))
            # Wait for the chunk to finish before sending the next one,
            # otherwise the firmware drops the second burst as BURST_BUSY.
            # Per-pair cost is 4 frames × BURST_FRAME_MS (firmware-side,
            # currently 2 ms = 8 ms/pair); add slack for chunk handover.
            import time as _t
            _t.sleep(chunk_n * 0.010 + 0.05)
            i += chunk_n

    def hid_burst_cancel(self) -> None:
        """Cancel any in-progress F06 burst (sends a zero-length burst)."""
        self._write(bytes([ESCAPE, CMD_HID_BURST, 0, 0]))

    def type_string(self, text: str) -> None:
        """Type *text* via :meth:`hid_burst`.

        Converts each ASCII character to (modifier, keycode) using the
        US HID Usage table.  Characters with no mapping (control chars
        beyond newline/tab, non-ASCII) are silently dropped.

        Convenience wrapper for testing and for bridges that want to
        type something quick without owning the full HID conversion.
        """
        pairs = [p for ch in text for p in (_ascii_to_hid_pair(ch),) if p is not None]
        self.hid_burst(pairs)

    def play_beep(self, pattern) -> None:
        """Play one of the firmware-side F04 beep patterns.

        Args:
            pattern: A :class:`~dc29.protocol.BeepPattern` member or its
                integer id.  ``BeepPattern.SILENCE`` cancels any pattern
                currently playing.

        Returns immediately; the buzzer continues asynchronously via
        firmware timers.  A new ``play_beep`` while one is in flight
        preempts it (cancel + restart from note 0 of the new pattern).
        """
        pid = int(pattern) & 0xFF
        self._write(bytes([ESCAPE, CMD_BEEP_PATTERN, pid]))

    def awake_pulse(self) -> None:
        """Fire one F08a-lite wake pulse on the badge.

        Pulse is a no-op HID-Keyboard event (LeftShift down then up, no
        key) — invisible to apps but counted as user activity by macOS for
        ``IOHIDIdleTime``.  See :data:`~dc29.protocol.CMD_JIGGLER`.
        """
        self._write(bytes([ESCAPE, CMD_JIGGLER, ord("M")]))

    def awake_set_duration(self, duration_secs: int) -> None:
        """Start autonomous Stay Awake mode on the badge for *duration_secs*.

        The badge fires one wake pulse every 30 s until the duration
        elapses.  Restart is allowed (replaces previous end).  Passing
        ``0`` is equivalent to :meth:`awake_cancel`.

        Args:
            duration_secs: How long the badge should keep the host awake,
                in seconds.  Clamped to ``[0, 2**32 - 1]``.
        """
        if duration_secs < 0:
            duration_secs = 0
        if duration_secs > 0xFFFFFFFF:
            duration_secs = 0xFFFFFFFF
        d = duration_secs & 0xFFFFFFFF
        self._write(bytes([
            ESCAPE, CMD_JIGGLER, ord("I"),
            d & 0xFF, (d >> 8) & 0xFF, (d >> 16) & 0xFF, (d >> 24) & 0xFF,
        ]))

    def awake_cancel(self) -> None:
        """Cancel autonomous Stay Awake mode on the badge."""
        self._write(bytes([ESCAPE, CMD_JIGGLER, ord("X")]))

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

    # ------------------------------------------------------------------
    # F01/F02 modifier-action table (RAM-only on the badge; bridges
    # repopulate on each connect).
    # ------------------------------------------------------------------

    def set_modifier_action(
        self,
        kind: str,
        button: int,
        modifier: int,
        keycode: int,
    ) -> None:
        """Set a per-button tap-count or long-press action.

        Args:
            kind:     One of ``"double"``, ``"triple"``, ``"long"``.
            button:   Button number, 1–4.
            modifier: HID modifier byte (use 0 for none, 0xF0 for media keys).
            keycode:  HID keycode byte.  Setting both ``modifier=0`` and
                ``keycode=0`` clears the entry.
        """
        sub_map = {"double": ord("D"), "triple": ord("T"), "long": ord("L")}
        sub = sub_map[kind]
        cmd = bytes([
            ESCAPE, CMD_MOD_TABLE, sub,
            button & 0xFF, modifier & 0xFF, keycode & 0xFF,
        ])
        self._write(cmd)

    def set_chord_action(
        self,
        button_a: int,
        button_b: int,
        modifier: int,
        keycode: int,
    ) -> None:
        """Set the action fired when buttons ``a`` and ``b`` are pressed
        together within ~80 ms.

        Args:
            button_a, button_b: 1–4, must differ.  Order is normalized on
                the badge (smaller → larger).
            modifier: HID modifier byte.  ``0, 0`` clears the entry.
            keycode:  HID keycode byte.
        """
        cmd = bytes([
            ESCAPE, CMD_MOD_TABLE, ord("C"),
            button_a & 0xFF, button_b & 0xFF,
            modifier & 0xFF, keycode & 0xFF,
        ])
        self._write(cmd)

    def clear_modifier_actions(self) -> None:
        """Clear every modifier and chord action on the badge."""
        cmd = bytes([ESCAPE, CMD_MOD_TABLE, ord("X")])
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
            if b == EVT_BUTTON_EXT:
                # Variable-length: kind byte arrives next, determines remainder.
                self._rx_args_needed = 1  # tentative; will expand after kind
                self._rx_state = 2
                return
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
            # Special case: EVT_BUTTON_EXT determines length from first byte (kind).
            if self._rx_cmd == EVT_BUTTON_EXT and len(self._rx_args) == 1:
                kind = self._rx_args[0]
                if kind == ord('C'):
                    self._rx_args_needed = 3   # kind + btn_a + btn_b
                elif kind in (ord('2'), ord('3'), ord('L')):
                    self._rx_args_needed = 2   # kind + btn
                else:
                    self._rx_state = 0          # unknown kind — drop
                    return
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
            # Local stats — fire-and-forget; never blocks dispatch.
            try:
                from dc29.stats import record
                record.button_press(n)
            except Exception:
                pass
            # Registered handlers (priority order) get first chance.
            with self._button_handlers_lock:
                handlers_snapshot = list(self._button_handlers)
            claimed = False
            for h in handlers_snapshot:
                if n in h.owned_buttons:
                    try:
                        if h.should_handle(n):
                            h.handler(n, mod, kc)
                            claimed = True
                            break
                    except Exception:
                        log.exception("button handler %r raised", h.name)
            if not claimed and self.on_button_press is not None:
                try:
                    self.on_button_press(n, mod, kc)
                except Exception:
                    log.exception("on_button_press fallback raised")
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

        elif cmd == EVT_BUTTON_EXT and len(args) >= 2:
            kind_byte = args[0]
            kind_map = {ord('2'): 'double', ord('3'): 'triple', ord('L'): 'long', ord('C'): 'chord'}
            kind = kind_map.get(kind_byte)
            if kind is None:
                return
            btn_a = args[1]
            btn_b = args[2] if (kind == 'chord' and len(args) >= 3) else None
            log.info("Extended button event: kind=%s btn_a=%d btn_b=%s", kind, btn_a, btn_b)
            try:
                from dc29.stats import record
                record.button_press(btn_a)
            except Exception:
                pass
            if self.on_button_ext is not None:
                try:
                    self.on_button_ext(kind, btn_a, btn_b)
                except Exception:
                    log.exception("on_button_ext callback raised")

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
