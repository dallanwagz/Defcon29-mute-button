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

Setup
-----
1. Microsoft Teams: Settings -> Privacy -> Manage API -> turn on
   "Enable third-party API" (label varies by Teams version). Without this,
   localhost:8124 is closed.
2. Pip dependencies:
       pip install websockets pyserial
3. First run: this script will try to connect without a token. Teams will
   show a confirmation dialog asking whether to allow the connection.
   Accept it. Teams responds with a token, which we save to
   ~/.dc29_teams_token for subsequent runs.
4. Find the badge's COM port (Device Manager -> Ports, or
   `Get-PnpDevice -Class Ports`). Pass it via --port.

Usage
-----
    python teams_mute_indicator.py --port COM7

Leave the script running in a terminal (or set up Task Scheduler / a
login-time autostart). The LED updates within ~1s of any Teams mute
state change, regardless of whether the user toggled mute via the badge,
the Teams UI, or a keyboard shortcut.
"""

import argparse
import asyncio
import json
import logging
import os
import sys
from pathlib import Path

try:
    import websockets
except ImportError:
    sys.exit("Missing dependency: pip install websockets")

try:
    import serial
except ImportError:
    sys.exit("Missing dependency: pip install pyserial")


WS_HOST = "localhost"
WS_PORT = 8124
TOKEN_PATH = Path.home() / ".dc29_teams_token"

# Identification fields Teams shows in its app-permission dialog when pairing.
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
        # Avoid spamming the badge with redundant updates.
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
    return CMD_MUTED if meeting_state.get("isMicMuted") else CMD_UNMUTED


async def run_once(badge: BadgeWriter) -> None:
    token = load_token()
    url = build_url(token)
    logging.info("Connecting to Teams Local API (token=%s)...", "<saved>" if token else "<none, expect pairing prompt>")

    async with websockets.connect(url, max_size=2**20) as ws:
        logging.info("Connected. Listening for meeting updates...")
        async for raw in ws:
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue

            # Teams sends a refreshed token after pairing approval.
            new_token = msg.get("tokenRefresh") or msg.get("newToken")
            if new_token:
                save_token(new_token)
                logging.info("Saved new pairing token to %s", TOKEN_PATH)

            # Look for the meetingUpdate envelope. Different Teams versions
            # shape it slightly differently; check both common keys.
            update = msg.get("meetingUpdate") or msg.get("MeetingUpdate")
            if update:
                state = update.get("meetingState") or update.get("MeetingState")
                cmd = state_to_command(state)
                label = {CMD_MUTED: "MUTED", CMD_UNMUTED: "UNMUTED", CMD_CLEAR: "CLEAR"}[cmd]
                logging.info("State -> %s", label)
                badge.write(cmd)


async def supervise(port_name: str) -> None:
    badge = BadgeWriter(port_name)
    badge.write(CMD_CLEAR)  # neutral until we know
    while True:
        try:
            await run_once(badge)
        except (websockets.ConnectionClosed, ConnectionRefusedError, OSError) as exc:
            logging.warning("Disconnected: %s. Reconnecting in %ds...", exc, RECONNECT_DELAY_SECONDS)
        except Exception as exc:
            logging.exception("Unexpected error: %s. Reconnecting in %ds...", exc, RECONNECT_DELAY_SECONDS)
        badge.write(CMD_CLEAR)
        await asyncio.sleep(RECONNECT_DELAY_SECONDS)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--port", required=True, help="Badge serial port (e.g., COM7)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Debug-level logging")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    try:
        asyncio.run(supervise(args.port))
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
