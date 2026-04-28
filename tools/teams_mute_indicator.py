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
    """Owns the serial port and survives reopen on transient USB drops."""

    def __init__(self, port_name: str) -> None:
        self.port_name = port_name
        self._serial = None
        self._last_cmd = None

    def _ensure_open(self) -> None:
        if self._serial is None or not self._serial.is_open:
            self._serial = serial.Serial(self.port_name, 9600, timeout=1)

    def write(self, cmd: bytes) -> None:
        if cmd == self._last_cmd:
            return
        try:
            self._ensure_open()
            self._serial.write(cmd)
            self._serial.flush()
            self._last_cmd = cmd
        except (serial.SerialException, OSError) as exc:
            logging.warning("Badge write failed: %s. Will retry on next update.", exc)
            try:
                if self._serial:
                    self._serial.close()
            except Exception:
                pass
            self._serial = None
            self._last_cmd = None


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


async def run_once(badge: BadgeWriter, toggle_queue: asyncio.Queue, tracker: _MeetingTracker) -> None:
    token = load_token()
    url = build_url(token)
    logging.info("Connecting to Teams Local API (token=%s)...", "<saved>" if token else "<none, expect pairing prompt>")

    # Discard stale toggle requests that accumulated while disconnected.
    while not toggle_queue.empty():
        toggle_queue.get_nowait()

    async with websockets.connect(url, max_size=2**20) as ws:
        logging.info("Connected. Listening for meeting updates...")
        if not token:
            await ws.send(json.dumps({"requestId": 1, "action": "pair"}))
            logging.info("Sent pair request — watch for a Teams authorization dialog")

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
                        tracker.is_in_meeting = bool(state.get("isInMeeting"))
                    cmd = state_to_command(state)
                    label = {CMD_MUTED: "MUTED", CMD_UNMUTED: "UNMUTED", CMD_CLEAR: "CLEAR"}[cmd]
                    logging.info("State -> %s", label)
                    badge.write(cmd)
        finally:
            toggle_task.cancel()
            with suppress(asyncio.CancelledError):
                await toggle_task


async def supervise(port_name: str, toggle_hotkey: str | None) -> None:
    badge = BadgeWriter(port_name)
    badge.write(CMD_CLEAR)

    toggle_queue: asyncio.Queue = asyncio.Queue()
    tracker = _MeetingTracker()

    hotkey_listener = None
    if toggle_hotkey:
        if not _PYNPUT_AVAILABLE:
            logging.warning(
                "pynput not installed — toggle hotkey disabled. Run: pip install pynput"
            )
        else:
            loop = asyncio.get_running_loop()

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
                await run_once(badge, toggle_queue, tracker)
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
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    try:
        asyncio.run(supervise(args.port, args.toggle_hotkey or None))
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
