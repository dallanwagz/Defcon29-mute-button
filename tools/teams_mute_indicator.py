#!/usr/bin/env python3
"""
DC29 Teams mute-state indicator.

Connects to the Microsoft Teams Local API (ws://localhost:8124) and forwards
the meeting mute state to the DC29 badge over its USB CDC serial port. The
badge's LED 4 reflects the current state:

    \\x01 M  -> red (muted)
    \\x01 U  -> green (unmuted)
    \\x01 X  -> off  (not in a meeting / cleared)

The 0x01 prefix is an escape byte the firmware reserves for status commands.
It never collides with normal serial-console traffic (menu input or macro
entry), so this script is safe to run while the badge's serial console is
also being used interactively.

Button 4 toggle
---------------
With --toggle-hotkey (default: <ctrl>+<alt>+m), a global keyboard listener
intercepts that combo and sends a toggle-mute action directly to Teams via
the WebSocket API — only while isInMeeting is true. Configure badge button 4
via the serial console to send that same combo (modifier 0x05 = ctrl+alt,
keycode 0x10 = m). Because the toggle goes through the Teams API, the LED
always reflects the actual Teams state regardless of how mute was changed.

Requires: pip install pynput
macOS:    grant Terminal (or your app) Accessibility access in
          System Settings -> Privacy & Security -> Accessibility.

Setup
-----
1. Microsoft Teams: Settings -> Privacy -> Manage API -> turn on
   "Enable third-party API" (label varies by Teams version). Without this,
   localhost:8124 is closed.
2. Pip dependencies:
       pip install websockets pyserial pynput
3. First run: Teams will show a confirmation dialog — click Allow. The token
   is saved to ~/.dc29_teams_token for subsequent runs.
4. Find the badge's serial port: ls /dev/tty.usbmodem*

Usage
-----
    python teams_mute_indicator.py --port /dev/tty.usbmodem14201

Use --toggle-hotkey '' to disable the button-toggle listener.
"""

import argparse
import asyncio
import json
import logging
import os
import sys
import threading
import time
from contextlib import suppress
from pathlib import Path

try:
    import websockets
except ImportError:
    sys.exit("Missing dependency: pip install websockets")

try:
    import serial
except ImportError:
    sys.exit("Missing dependency: pip install pyserial")

try:
    from pynput import keyboard as pynput_keyboard
    _PYNPUT_AVAILABLE = True
except ImportError:
    _PYNPUT_AVAILABLE = False


WS_HOST = "localhost"
WS_PORT = 8124
TOKEN_PATH = Path.home() / ".dc29_teams_token"

APP_MANUFACTURER = "DC29"
APP_DEVICE = "DefconBadgeMacropad"
APP_NAME = "MuteIndicator"
APP_VERSION = "1.0.0"
PROTOCOL_VERSION = "2.0.0"

ESCAPE = b"\x01"
CMD_MUTED = ESCAPE + b"M"
CMD_UNMUTED = ESCAPE + b"U"
CMD_CLEAR = ESCAPE + b"X"

RECONNECT_DELAY_SECONDS = 5

# Hotkey the badge button 4 should send (pynput format).
# Badge keymap: modifier 0x05 (ctrl+alt), keycode 0x10 (m).
DEFAULT_TOGGLE_HOTKEY = "<ctrl>+<alt>+m"


def load_token() -> str:
    if TOKEN_PATH.exists():
        return TOKEN_PATH.read_text().strip()
    return ""


def save_token(token: str) -> None:
    TOKEN_PATH.write_text(token)
    try:
        os.chmod(TOKEN_PATH, 0o600)
    except OSError:
        pass


def build_url(token: str) -> str:
    params = [
        ("protocol-version", PROTOCOL_VERSION),
        ("manufacturer", APP_MANUFACTURER),
        ("device", APP_DEVICE),
        ("app", APP_NAME),
        ("app-version", APP_VERSION),
    ]
    if token:
        params.insert(0, ("token", token))
    qs = "&".join(f"{k}={v}" for k, v in params)
    return f"ws://{WS_HOST}:{WS_PORT}?{qs}"


class BadgeWriter:
    """Owns the serial port and survives reopen on transient USB drops.

    Runs a background reader thread that parses badge→host escape events:
      0x01 B n mod key  — button n was pressed (logs modifier + keycode)
      0x01 R n mod key  — reply to a Q query
      0x01 A n          — ACK for a K set-keymap command
    """

    def __init__(self, port_name: str) -> None:
        self.port_name = port_name
        self._serial = None
        self._last_cmd = None
        self._lock = threading.Lock()
        self._reader_thread: threading.Thread | None = None
        self._rx_state = 0  # 0=idle 1=got_escape 2=collecting_args
        self._rx_cmd = 0
        self._rx_args: list[int] = []
        self._rx_args_needed = 0
        self.on_button4_press: "Callable[[], None] | None" = None

    def _ensure_open(self) -> None:
        if self._serial is None or not self._serial.is_open:
            self._serial = serial.Serial(self.port_name, 9600, timeout=0.1)
            self._start_reader()

    def _start_reader(self) -> None:
        if self._reader_thread is None or not self._reader_thread.is_alive():
            t = threading.Thread(target=self._reader_loop, daemon=True)
            t.start()
            self._reader_thread = t

    def _reader_loop(self) -> None:
        while True:
            try:
                ser = self._serial
                if ser and ser.is_open:
                    b = ser.read(1)
                    if b:
                        self._parse_rx(b[0])
                else:
                    time.sleep(0.1)
            except (serial.SerialException, OSError):
                break
            except Exception:
                break

    def _parse_rx(self, b: int) -> None:
        if self._rx_state == 0:
            if b == 0x01:
                self._rx_state = 1
        elif self._rx_state == 1:
            self._rx_cmd = b
            self._rx_args = []
            if b == ord('B'):
                self._rx_args_needed = 3
                self._rx_state = 2
            elif b == ord('A'):
                self._rx_args_needed = 1
                self._rx_state = 2
            elif b == ord('R'):
                self._rx_args_needed = 3
                self._rx_state = 2
            else:
                self._rx_state = 0
        elif self._rx_state == 2:
            self._rx_args.append(b)
            if len(self._rx_args) >= self._rx_args_needed:
                self._dispatch_rx()
                self._rx_state = 0

    def _dispatch_rx(self) -> None:
        cmd = chr(self._rx_cmd)
        args = self._rx_args
        if cmd == 'B' and len(args) == 3:
            logging.info("Badge button %d pressed → modifier=0x%02X keycode=0x%02X",
                         args[0], args[1], args[2])
            if args[0] == 4 and self.on_button4_press is not None:
                self.on_button4_press()
        elif cmd == 'R' and len(args) == 3:
            logging.info("Badge button %d keymap: modifier=0x%02X keycode=0x%02X",
                         args[0], args[1], args[2])
        elif cmd == 'A' and len(args) == 1:
            logging.info("Badge ACK: keymap set for button %d", args[0])

    def _close(self) -> None:
        try:
            if self._serial:
                self._serial.close()
        except Exception:
            pass
        self._serial = None
        self._last_cmd = None

    def write(self, cmd: bytes) -> None:
        with self._lock:
            if cmd == self._last_cmd:
                return
            try:
                self._ensure_open()
                self._serial.write(cmd)
                self._serial.flush()
                self._last_cmd = cmd
            except (serial.SerialException, OSError) as exc:
                logging.warning("Badge write failed: %s. Will retry on next update.", exc)
                self._close()

    def set_keymap(self, button: int, modifier: int, keycode: int) -> None:
        """Write a single-key macro for button (1-6) directly to badge EEPROM."""
        cmd = bytes([0x01, ord('K'), button & 0xFF, modifier & 0xFF, keycode & 0xFF])
        with self._lock:
            try:
                self._ensure_open()
                self._serial.write(cmd)
                self._serial.flush()
            except (serial.SerialException, OSError) as exc:
                logging.warning("Badge set_keymap failed: %s", exc)
                self._close()

    def query_keymap(self, button: int) -> None:
        """Ask the badge to report the current keymap for button (1-6)."""
        cmd = bytes([0x01, ord('Q'), button & 0xFF])
        with self._lock:
            try:
                self._ensure_open()
                self._serial.write(cmd)
                self._serial.flush()
            except (serial.SerialException, OSError) as exc:
                logging.warning("Badge query_keymap failed: %s", exc)
                self._close()

    def set_led(self, n: int, r: int, g: int, b: int) -> None:
        """Set LED n (1-4) color immediately. Not saved to EEPROM."""
        cmd = bytes([0x01, ord('L'), n & 0xFF, r & 0xFF, g & 0xFF, b & 0xFF])
        with self._lock:
            try:
                self._ensure_open()
                self._serial.write(cmd)
                self._serial.flush()
            except (serial.SerialException, OSError) as exc:
                logging.warning("Badge set_led failed: %s", exc)
                self._close()


Color = tuple[int, int, int]

BUILTIN_COLORS: dict[str, Color] = {
    "red":    (255, 0,   0),
    "green":  (0,   255, 0),
    "blue":   (0,   0,   255),
    "white":  (255, 255, 255),
    "cyan":   (0,   200, 255),
    "purple": (160, 0,   255),
    "orange": (255, 80,  0),
    "off":    (0,   0,   0),
}


class LedAnimator:
    """Drives LED animation patterns as asyncio tasks.

    Animations send 0x01 L n r g b commands at timed intervals — all logic
    lives in Python, no firmware loop required.  LED 4 is the mute indicator;
    most patterns default to LEDs 1-3 so they don't clash with mute state.

    Patterns
    --------
    chase   — one LED lit at a time, cycling through leds tuple
    solid   — all specified LEDs set to the same color
    """

    def __init__(self, badge: BadgeWriter) -> None:
        self._badge = badge
        self._task: asyncio.Task | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start_chase(
        self,
        color: Color = (0, 100, 255),
        speed_ms: int = 150,
        leds: tuple[int, ...] = (1, 2, 3),
    ) -> None:
        """Cycle one LED at a time through leds with the given color."""
        self._cancel()
        self._task = asyncio.create_task(
            self._chase(color=color, speed_ms=speed_ms, leds=leds),
            name="led-chase",
        )

    def start_solid(
        self,
        color: Color = (0, 100, 255),
        leds: tuple[int, ...] = (1, 2, 3),
    ) -> None:
        """Set all specified LEDs to the same static color."""
        self._cancel()
        for n in leds:
            self._badge.set_led(n, *color)

    def stop(self, leds: tuple[int, ...] = (1, 2, 3)) -> None:
        """Cancel the running animation and turn off the specified LEDs."""
        self._cancel()
        for n in leds:
            self._badge.set_led(n, 0, 0, 0)

    # ------------------------------------------------------------------
    # Patterns (private async coroutines)
    # ------------------------------------------------------------------

    async def _chase(
        self,
        color: Color,
        speed_ms: int,
        leds: tuple[int, ...],
    ) -> None:
        r, g, b = color
        try:
            while True:
                for n in leds:
                    self._badge.set_led(n, r, g, b)
                    await asyncio.sleep(speed_ms / 1000)
                    self._badge.set_led(n, 0, 0, 0)
        except asyncio.CancelledError:
            for n in leds:
                self._badge.set_led(n, 0, 0, 0)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _cancel(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
        self._task = None


def parse_color(value: str) -> Color:
    """Parse 'r,g,b' or a named color into a (r,g,b) tuple."""
    low = value.strip().lower()
    if low in BUILTIN_COLORS:
        return BUILTIN_COLORS[low]
    parts = low.split(",")
    if len(parts) == 3:
        try:
            r, g, b = (int(p.strip()) for p in parts)
            if all(0 <= v <= 255 for v in (r, g, b)):
                return (r, g, b)
        except ValueError:
            pass
    raise argparse.ArgumentTypeError(
        f"Invalid color {value!r}. Use 'r,g,b' (0-255 each) or one of: "
        + ", ".join(BUILTIN_COLORS)
    )


def state_to_command(meeting_state: dict | None) -> bytes:
    """Map a Teams meetingState dict to the corresponding badge command."""
    if not meeting_state:
        return CMD_CLEAR
    if not meeting_state.get("isInMeeting"):
        return CMD_CLEAR
    return CMD_MUTED if meeting_state.get("isMuted") else CMD_UNMUTED


class _MeetingTracker:
    """Shared mutable state between the WebSocket loop and the toggle sender."""

    def __init__(self) -> None:
        self.is_in_meeting = False
        self._next_request_id = 100

    def next_request_id(self) -> int:
        rid = self._next_request_id
        self._next_request_id += 1
        return rid


async def _toggle_sender(ws, queue: asyncio.Queue, tracker: _MeetingTracker) -> None:
    """Consume toggle requests from the hotkey listener and forward to Teams."""
    while True:
        await queue.get()
        if tracker.is_in_meeting:
            rid = tracker.next_request_id()
            await ws.send(json.dumps({"requestId": rid, "action": "toggle-mute"}))
            logging.info("Sent toggle-mute to Teams")
        else:
            logging.debug("Toggle hotkey pressed but not in a meeting — ignored")


async def run_once(
    badge: BadgeWriter,
    toggle_queue: asyncio.Queue,
    tracker: _MeetingTracker,
    animator: LedAnimator | None = None,
    idle_animation: str | None = None,
    idle_color: Color = (0, 200, 255),
    idle_speed: int = 150,
) -> None:
    token = load_token()
    url = build_url(token)
    logging.info("Connecting to Teams Local API (token=%s)...", "<saved>" if token else "<none, expect pairing prompt>")

    # Discard stale toggle requests that accumulated while disconnected.
    while not toggle_queue.empty():
        toggle_queue.get_nowait()

    def _start_idle() -> None:
        if animator and idle_animation == "chase":
            animator.start_chase(color=idle_color, speed_ms=idle_speed)

    async with websockets.connect(url, max_size=2**20) as ws:
        logging.info("Connected. Listening for meeting updates...")
        if not token:
            await ws.send(json.dumps({"requestId": 1, "action": "pair"}))
            logging.info("Sent pair request — watch for a Teams authorization dialog")

        # Start idle animation if we connect while not in a meeting.
        if not tracker.is_in_meeting:
            _start_idle()

        toggle_task = asyncio.create_task(_toggle_sender(ws, toggle_queue, tracker))
        try:
            async for raw in ws:
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue

                logging.debug("Raw message: %s", raw)

                new_token = msg.get("tokenRefresh") or msg.get("newToken")
                if new_token:
                    save_token(new_token)
                    logging.info("Saved new pairing token to %s", TOKEN_PATH)

                update = msg.get("meetingUpdate") or msg.get("MeetingUpdate")
                if update:
                    state = update.get("meetingState") or update.get("MeetingState")
                    logging.debug("meetingState dict: %s", state)
                    if state is not None:
                        was_in_meeting = tracker.is_in_meeting
                        tracker.is_in_meeting = bool(state.get("isInMeeting"))
                        if animator:
                            if tracker.is_in_meeting and not was_in_meeting:
                                animator.stop()       # entering a meeting
                            elif not tracker.is_in_meeting and was_in_meeting:
                                _start_idle()         # leaving a meeting
                    cmd = state_to_command(state)
                    label = {CMD_MUTED: "MUTED", CMD_UNMUTED: "UNMUTED", CMD_CLEAR: "CLEAR"}[cmd]
                    logging.info("State -> %s", label)
                    badge.write(cmd)
        finally:
            if animator:
                animator.stop()
            toggle_task.cancel()
            with suppress(asyncio.CancelledError):
                await toggle_task


async def supervise(
    port_name: str,
    toggle_hotkey: str | None,
    idle_animation: str | None = None,
    idle_color: Color = (0, 200, 255),
    idle_speed: int = 150,
) -> None:
    badge = BadgeWriter(port_name)
    badge.write(CMD_CLEAR)
    badge.query_keymap(4)  # log button 4's configured keymap at startup

    animator = LedAnimator(badge) if idle_animation else None

    toggle_queue: asyncio.Queue = asyncio.Queue()
    tracker = _MeetingTracker()

    loop = asyncio.get_running_loop()
    badge.on_button4_press = lambda: loop.call_soon_threadsafe(toggle_queue.put_nowait, True)

    hotkey_listener = None
    if toggle_hotkey:
        if not _PYNPUT_AVAILABLE:
            logging.warning(
                "pynput not installed — toggle hotkey disabled. Run: pip install pynput"
            )
        else:
            def _on_hotkey() -> None:
                loop.call_soon_threadsafe(toggle_queue.put_nowait, True)

            try:
                hotkey_listener = pynput_keyboard.GlobalHotKeys(
                    {toggle_hotkey: _on_hotkey}
                )
                hotkey_listener.start()
                logging.info("Toggle hotkey active: %s", toggle_hotkey)
            except Exception as exc:
                logging.warning("Could not start hotkey listener: %s", exc)
                hotkey_listener = None

    try:
        while True:
            try:
                await run_once(badge, toggle_queue, tracker,
                               animator=animator, idle_animation=idle_animation,
                               idle_color=idle_color, idle_speed=idle_speed)
            except (websockets.ConnectionClosed, ConnectionRefusedError, OSError) as exc:
                logging.warning("Disconnected: %s. Reconnecting in %ds...", exc, RECONNECT_DELAY_SECONDS)
            except Exception as exc:
                logging.exception("Unexpected error: %s. Reconnecting in %ds...", exc, RECONNECT_DELAY_SECONDS)
            badge.write(CMD_CLEAR)
            tracker.is_in_meeting = False
            await asyncio.sleep(RECONNECT_DELAY_SECONDS)
    finally:
        if hotkey_listener:
            hotkey_listener.stop()


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--port", required=True, help="Badge serial port (e.g., /dev/tty.usbmodem14201)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Debug-level logging")
    parser.add_argument(
        "--toggle-hotkey",
        default=DEFAULT_TOGGLE_HOTKEY,
        help=(
            "Global hotkey that triggers Teams mute toggle via the API (pynput format). "
            "Configure badge button 4 to send the matching keystroke. "
            "Pass '' to disable. Default: %(default)s"
        ),
    )
    parser.add_argument(
        "--idle-animation",
        choices=["chase"],
        default=None,
        help="LED animation to run on LEDs 1-3 when not in a meeting (default: none).",
    )
    parser.add_argument(
        "--idle-color",
        type=parse_color,
        default="cyan",
        metavar="COLOR",
        help=(
            "Color for idle animation. Named color (red/green/blue/cyan/purple/orange/white) "
            "or r,g,b (0-255 each). Default: cyan"
        ),
    )
    parser.add_argument(
        "--idle-speed",
        type=int,
        default=150,
        metavar="MS",
        help="Animation step duration in milliseconds. Default: 150",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    try:
        asyncio.run(supervise(
            args.port,
            args.toggle_hotkey or None,
            idle_animation=args.idle_animation,
            idle_color=args.idle_color,
            idle_speed=args.idle_speed,
        ))
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
