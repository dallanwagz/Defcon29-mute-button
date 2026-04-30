"""
dc29.bridges.teams — Microsoft Teams Local API bridge.

Connects to the Teams Local API WebSocket (``ws://localhost:8124``) and manages
a full **Teams page** on the badge while a meeting is active.

Teams page (default button layout)
------------------------------------
.. list-table::
   :header-rows: 1

   * - Button
     - Action
     - LED (idle / in-meeting)
   * - 1
     - Leave call
     - dark / red
   * - 2
     - Toggle video
     - dark / blue or dark
   * - 3
     - Raise hand
     - dark / yellow or dark
   * - 4
     - Toggle mute
     - dark / red (muted) or green (live)

The layout is fully configurable via ``~/.config/dc29/config.toml``::

    [teams.buttons]
    1 = "leave-call"
    2 = "toggle-video"
    3 = "toggle-hand"
    4 = "toggle-mute"

Valid action strings: ``toggle-mute``, ``toggle-video``, ``toggle-hand``,
``toggle-background-blur``, ``leave-call``.

Page lifecycle
--------------
* Not in meeting → all page LEDs dark; button presses fall through to EEPROM macros.
* In meeting → page LEDs lit per action state; button presses go to Teams WebSocket.
* Bridge disconnects → page LEDs cleared; badge returns to normal EEPROM operation.

Token management
----------------
On first connection Teams shows a pairing dialog.  The token is saved to
``~/.dc29_teams_token`` and reused automatically.

Optional hotkey
---------------
Pass a pynput-format hotkey string (``pip install pynput``; Accessibility
permission required on macOS) to trigger mute toggle from the keyboard::

    bridge = TeamsBridge(badge, toggle_hotkey="<ctrl>+<alt>+m")

Usage::

    badge = BadgeAPI("/dev/tty.usbmodem14201")
    bridge = TeamsBridge(badge)
    asyncio.run(bridge.run())
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from contextlib import suppress
from pathlib import Path
from typing import Callable, Optional

try:
    import websockets
    from websockets.exceptions import ConnectionClosed
except ImportError as _exc:
    raise ImportError("websockets is required: pip install websockets") from _exc

from dc29.badge import BadgeAPI
from dc29.bridges.base import BaseBridge, BridgePage, PageButton
from dc29.bridges.colors import BRAND_COLORS, POSITION_ACTIVE, POSITION_DIM
from dc29.config import Config, get_config
from dc29.protocol import MuteState

log = logging.getLogger(__name__)

_PYNPUT_AVAILABLE = False
try:
    from pynput import keyboard as _pynput_keyboard
    _PYNPUT_AVAILABLE = True
except ImportError:
    pass

# Teams Local API application identity
_APP_MANUFACTURER = "DC29"
_APP_DEVICE = "DefconBadgeMacropad"
_APP_NAME = "MuteIndicator"
_APP_VERSION = "1.0.0"
_PROTOCOL_VERSION = "2.0.0"

# Teams API action → WebSocket "action" field
_TEAMS_ACTIONS: dict[str, str] = {
    "toggle-mute":             "toggle-mute",
    "toggle-video":            "toggle-video",
    "toggle-hand":             "toggle-hand",
    "toggle-background-blur":  "toggle-background-blur",
    "leave-call":              "leave-call",
}

# LED colors per action — positional semantics applied.
# toggle-mute (B4) is overridden dynamically based on mute state.
_ACTION_LEDS: dict[str, tuple[int, int, int]] = {
    "leave-call":             POSITION_ACTIVE[1],  # warm red — destructive/exit ✓
    "toggle-video":           POSITION_ACTIVE[2],  # cool blue — visibility/status ✓
    "toggle-hand":            POSITION_ACTIVE[3],  # amber — raise hand / reach out ✓
    "toggle-mute":            POSITION_ACTIVE[4],  # green baseline; overridden per state
    "toggle-background-blur": POSITION_ACTIVE[2],  # blue — visual status family
}


def _build_page(button_actions: dict[int, str]) -> BridgePage:
    buttons: dict[int, PageButton] = {}
    for btn, action in button_actions.items():
        positional_default = POSITION_ACTIVE.get(btn, (60, 60, 60))
        led = _ACTION_LEDS.get(action, positional_default)
        buttons[btn] = PageButton(
            label=action,
            led=led,
            led_active=POSITION_ACTIVE[4],   # green = on / live / active
            led_inactive=POSITION_ACTIVE[1],  # warm red = muted / off / inactive
        )
    return BridgePage(
        name="teams",
        description="Microsoft Teams — meeting controls",
        brand_color=BRAND_COLORS["teams"],
        buttons=buttons,
    )


class TeamsBridge(BaseBridge):
    """Connects to the Microsoft Teams Local API and drives the badge meeting page.

    Args:
        badge:         The :class:`~dc29.badge.BadgeAPI` instance to control.
        toggle_hotkey: Optional pynput-format global hotkey string (e.g.
                       ``"<ctrl>+<alt>+m"``) that triggers a mute toggle.
                       Pass ``None`` to disable.
        config:        Optional :class:`~dc29.config.Config` instance.  Defaults
                       to the module-level singleton from :func:`~dc29.config.get_config`.
    """

    WS_HOST: str = "localhost"
    WS_PORT: int = 8124
    TOKEN_PATH: Path = Path.home() / ".dc29_teams_token"
    RECONNECT_DELAY: int = 5

    def __init__(
        self,
        badge: BadgeAPI,
        toggle_hotkey: Optional[str] = None,
        config: Optional[Config] = None,
    ) -> None:
        super().__init__(badge)
        cfg = config or get_config()
        self._toggle_hotkey = toggle_hotkey or cfg.teams_toggle_hotkey
        self._button_actions: dict[int, str] = cfg.teams_button_actions

        self._in_meeting: bool = False
        self._mute_state: MuteState = MuteState.NOT_IN_MEETING
        self._video_on: bool = False
        self._hand_raised: bool = False

        self._next_request_id: int = 100
        self._action_queue: asyncio.Queue[str] = asyncio.Queue()
        self._hotkey_listener: object = None

        self._page = _build_page(self._button_actions)

    # ------------------------------------------------------------------
    # BaseBridge interface
    # ------------------------------------------------------------------

    @property
    def page(self) -> BridgePage:
        return self._page

    def _should_handle_button(self, btn: int) -> bool:
        return self._in_meeting

    async def handle_button(self, btn: int) -> None:
        """Enqueue the Teams action bound to *btn*."""
        action = self._button_actions.get(btn)
        if action:
            log.debug("Button %d → Teams action %s", btn, action)
            await self._action_queue.put(action)

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def in_meeting(self) -> bool:
        """``True`` if Teams reports an active meeting."""
        return self._in_meeting

    @property
    def mute_state(self) -> MuteState:
        """Current :class:`~dc29.protocol.MuteState` as last reported by Teams."""
        return self._mute_state

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    async def run(self) -> None:
        """Run the bridge forever, reconnecting on any failure."""
        self._loop = asyncio.get_running_loop()
        self._install_button_hook()
        self._start_hotkey_listener()
        try:
            while True:
                try:
                    await self._connect_and_run()
                except (ConnectionClosed, ConnectionRefusedError, OSError) as exc:
                    log.warning(
                        "Teams WebSocket disconnected: %s. Reconnecting in %ds…",
                        exc, self.RECONNECT_DELAY,
                    )
                except Exception:
                    log.exception(
                        "Unexpected error in Teams bridge. Reconnecting in %ds…",
                        self.RECONNECT_DELAY,
                    )
                self._set_meeting_state(MuteState.NOT_IN_MEETING)
                await asyncio.sleep(self.RECONNECT_DELAY)
        finally:
            self._stop_hotkey_listener()
            self._uninstall_button_hook()
            self._clear_page_leds()

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    async def _connect_and_run(self) -> None:
        token = self._load_token()
        url = self._build_url(token)
        log.info(
            "Connecting to Teams Local API (token=%s)…",
            "<saved>" if token else "<none — expect pairing dialog>",
        )

        # Drain stale actions that queued while disconnected.
        while not self._action_queue.empty():
            self._action_queue.get_nowait()

        async with websockets.connect(url, max_size=2**20, open_timeout=30) as ws:
            log.info("Connected. Listening for meeting updates…")
            if not token:
                await ws.send(json.dumps({"requestId": 1, "action": "pair"}))
                log.info("Sent pair request — watch for a Teams authorisation dialog")

            sender_task = asyncio.create_task(
                self._action_sender(ws), name="teams-action-sender"
            )
            try:
                async for raw in ws:
                    await self._handle_message(raw)
            finally:
                sender_task.cancel()
                with suppress(asyncio.CancelledError):
                    await sender_task

    async def _handle_message(self, raw: str | bytes) -> None:
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            return

        log.debug("Teams message: %s", raw)

        new_token = msg.get("tokenRefresh") or msg.get("newToken")
        if new_token:
            self._save_token(new_token)
            log.info("Saved new pairing token to %s", self.TOKEN_PATH)

        update = msg.get("meetingUpdate") or msg.get("MeetingUpdate")
        if update:
            state = update.get("meetingState") or update.get("MeetingState")
            if state is not None:
                self._in_meeting = bool(state.get("isInMeeting"))
                self._video_on = bool(state.get("isVideoOn", False))
                self._hand_raised = bool(state.get("isHandRaised", False))

                if not self._in_meeting:
                    new_state = MuteState.NOT_IN_MEETING
                elif state.get("isMuted"):
                    new_state = MuteState.MUTED
                else:
                    new_state = MuteState.UNMUTED
                self._set_meeting_state(new_state)

    async def _action_sender(self, ws: object) -> None:
        """Consume actions from the queue and forward to Teams."""
        while True:
            action = await self._action_queue.get()
            if not self._in_meeting and action != "leave-call":
                log.debug("Action %r ignored — not in a meeting", action)
                continue
            ws_action = _TEAMS_ACTIONS.get(action, action)
            rid = self._next_request_id
            self._next_request_id += 1
            await ws.send(json.dumps({"requestId": rid, "action": ws_action}))
            log.info("Sent %s to Teams (requestId=%d)", ws_action, rid)

    def _set_meeting_state(self, new_state: MuteState) -> None:
        """Update local state, drive badge LEDs, and fire callbacks."""
        was_in_meeting = self._mute_state != MuteState.NOT_IN_MEETING
        now_in_meeting = new_state != MuteState.NOT_IN_MEETING
        changed = new_state != self._mute_state
        self._mute_state = new_state

        # Suppress the button-press takeover animation during meetings so LED 4
        # always shows accurate mute state instead of a 2.5 s light show.
        if not was_in_meeting and now_in_meeting:
            self._badge.set_button_flash(False)
        elif was_in_meeting and not now_in_meeting:
            self._badge.set_button_flash(True)

        if new_state == MuteState.NOT_IN_MEETING:
            # Only touch LEDs when leaving a meeting — don't clobber other bridges
            # (Outlook, Slack, etc.) just because Teams isn't connected.
            if was_in_meeting:
                self._clear_page_leds()
                self._badge.set_current_page(None)
        else:
            # Light up all page buttons with their action colors
            for btn, action in self._button_actions.items():
                if action == "toggle-mute":
                    # Safety-critical exception to positional rule: state IS the semantics.
                    if new_state == MuteState.MUTED:
                        self._badge.set_led(btn, *POSITION_ACTIVE[1])  # warm red = muted
                    else:
                        self._badge.set_led(btn, *POSITION_ACTIVE[4])  # green = live
                elif action == "toggle-video":
                    if self._video_on:
                        self._badge.set_led(btn, *POSITION_ACTIVE[2])  # blue = on
                    else:
                        self._badge.set_led(btn, *POSITION_DIM[2])     # dim blue = off
                elif action == "toggle-hand":
                    if self._hand_raised:
                        self._badge.set_led(btn, *POSITION_ACTIVE[3])  # amber = raised
                    else:
                        self._badge.set_led(btn, *POSITION_DIM[3])     # dim amber = lowered
                elif action == "leave-call":
                    self._badge.set_led(btn, *POSITION_ACTIVE[1])      # always warm red
                else:
                    positional_default = POSITION_ACTIVE.get(btn, (60, 60, 60))
                    led = _ACTION_LEDS.get(action, positional_default)
                    self._badge.set_led(btn, *led)

            self._badge.set_current_page(self._page)

        label = {
            MuteState.NOT_IN_MEETING: "NOT_IN_MEETING",
            MuteState.UNMUTED: "UNMUTED",
            MuteState.MUTED: "MUTED",
        }.get(new_state, "UNKNOWN")

        if changed:
            log.info("Meeting state → %s", label)

        # Only drive the firmware LED when transitioning into or out of a meeting.
        # Sending NOT_IN_MEETING while Teams is simply disconnected would turn off
        # LED 4 even when another bridge (Outlook, Slack) owns it.
        if was_in_meeting or now_in_meeting:
            self._badge.set_mute_state(new_state)

        if changed and self.on_state_change is not None:
            try:
                self.on_state_change(new_state)
            except Exception:
                log.exception("on_state_change callback raised")

    # ------------------------------------------------------------------
    # Token management
    # ------------------------------------------------------------------

    def _load_token(self) -> str:
        if self.TOKEN_PATH.exists():
            return self.TOKEN_PATH.read_text().strip()
        return ""

    def _save_token(self, token: str) -> None:
        self.TOKEN_PATH.write_text(token)
        try:
            os.chmod(self.TOKEN_PATH, 0o600)
        except OSError:
            pass

    def _build_url(self, token: str) -> str:
        params = [
            ("protocol-version", _PROTOCOL_VERSION),
            ("manufacturer", _APP_MANUFACTURER),
            ("device", _APP_DEVICE),
            ("app", _APP_NAME),
            ("app-version", _APP_VERSION),
        ]
        if token:
            params.insert(0, ("token", token))
        qs = "&".join(f"{k}={v}" for k, v in params)
        return f"ws://{self.WS_HOST}:{self.WS_PORT}?{qs}"

    # ------------------------------------------------------------------
    # Hotkey listener
    # ------------------------------------------------------------------

    def _start_hotkey_listener(self) -> None:
        if not self._toggle_hotkey:
            return
        if not _PYNPUT_AVAILABLE:
            log.warning(
                "pynput not installed — toggle hotkey disabled. "
                "Run: pip install 'dc29-badge[hotkey]'"
            )
            return

        def _on_hotkey() -> None:
            if self._loop is not None:
                self._loop.call_soon_threadsafe(
                    self._action_queue.put_nowait, "toggle-mute"
                )

        try:
            self._hotkey_listener = _pynput_keyboard.GlobalHotKeys(
                {self._toggle_hotkey: _on_hotkey}
            )
            self._hotkey_listener.start()
            log.info("Toggle hotkey active: %s", self._toggle_hotkey)
        except Exception as exc:
            log.warning("Could not start hotkey listener: %s", exc)
            self._hotkey_listener = None

    def _stop_hotkey_listener(self) -> None:
        if self._hotkey_listener is not None:
            try:
                self._hotkey_listener.stop()
            except Exception:
                pass
            self._hotkey_listener = None
