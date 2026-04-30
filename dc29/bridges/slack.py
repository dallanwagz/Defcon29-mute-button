"""
dc29.bridges.slack — Slack productivity shortcut bridge with live huddle mute tracking.

When Slack has focus, 4 shortcuts are active on the badge buttons.  When a
huddle is detected, button 4 switches from "join/leave huddle" to a live mute
indicator: green = live, red = muted.  Button press toggles mute.  Button flash
is suppressed during a huddle (same behaviour as Teams during a meeting).

Huddle state detection uses the macOS Accessibility API via osascript — no
Slack app token required.  The script scans all Slack window buttons for
"Mute" / "Unmute" labels.  If the Slack version changes button labels, set
SLACK_MUTE_BUTTON / SLACK_UNMUTE_BUTTON env vars to override (substrings,
case-insensitive).

Default button layout
---------------------
  B1  All Unreads       Cmd+Shift+A   warm red
  B2  Mentions          Cmd+Shift+M   cool blue
  B3  Quick Switcher    Cmd+K         amber
  B4  Toggle Huddle     Cmd+Shift+H   green
      (in huddle →      Cmd+Shift+Spc mute toggle, LED = live mute state)
"""

from __future__ import annotations

import asyncio
import logging
import os
import platform
import subprocess
from typing import Optional

from dc29.badge import BadgeAPI
from dc29.bridges.base import BridgePage, PageButton
from dc29.bridges.colors import BRAND_COLORS, POSITION_ACTIVE
from dc29.bridges.focus import FocusBridge
from dc29.config import Config, get_config

log = logging.getLogger(__name__)

_SYSTEM = platform.system()

_PYNPUT_AVAILABLE = False
try:
    from pynput.keyboard import Controller as _KbController, Key as _Key, KeyCode as _KeyCode
    _PYNPUT_AVAILABLE = True
except ImportError:
    pass

# Accessibility label substrings — override via env vars if Slack changes them.
_MUTE_LABEL   = os.environ.get("SLACK_MUTE_BUTTON",   "Mute").lower()
_UNMUTE_LABEL = os.environ.get("SLACK_UNMUTE_BUTTON", "Unmute").lower()

_HUDDLE_POLL_INTERVAL = 1.0   # seconds between accessibility checks

# ---------------------------------------------------------------------------
# Shortcuts
# ---------------------------------------------------------------------------

_SHORTCUTS_MAC: dict[str, tuple[list[str], object]] = {
    "all-unreads":  (["cmd", "shift"], "a"),
    "mentions":     (["cmd", "shift"], "m"),
    "quick-switch": (["cmd"],          "k"),
    "threads":      (["cmd", "shift"], "t"),
    "huddle":       (["cmd", "shift"], "h"),
    "huddle-mute":  (["cmd", "shift"], "space"),   # mute toggle inside a huddle
    "next-unread":  (["alt", "shift"], "↓"),
    "dnd":          (["cmd", "shift"], "i"),
}

_SHORTCUTS_WIN: dict[str, tuple[list[str], object]] = {
    "all-unreads":  (["ctrl", "shift"], "a"),
    "mentions":     (["ctrl", "shift"], "m"),
    "quick-switch": (["ctrl"],          "k"),
    "threads":      (["ctrl", "shift"], "t"),
    "huddle":       (["ctrl", "shift"], "h"),
    "huddle-mute":  (["ctrl", "shift"], "space"),
    "next-unread":  (["alt", "shift"],  "↓"),
    "dnd":          (["ctrl", "shift"], "i"),
}

_DEFAULT_BUTTON_ACTIONS: dict[int, str] = {
    1: "all-unreads",
    2: "mentions",
    3: "quick-switch",
    4: "huddle",
}

_DEFAULT_LED_COLORS: dict[str, tuple[int, int, int]] = {
    "all-unreads":  POSITION_ACTIVE[1],
    "mentions":     POSITION_ACTIVE[2],
    "quick-switch": POSITION_ACTIVE[3],
    "threads":      POSITION_ACTIVE[2],
    "huddle":       POSITION_ACTIVE[4],
    "next-unread":  POSITION_ACTIVE[3],
    "dnd":          POSITION_ACTIVE[1],
}

# ---------------------------------------------------------------------------
# Accessibility probe — macOS only
# ---------------------------------------------------------------------------

_OSASCRIPT = """\
tell application "System Events"
    if not (exists process "Slack") then return "off"
    tell process "Slack"
        try
            repeat with w in windows
                repeat with b in (get every button of w)
                    try
                        set bName to name of b
                        if bName is not missing value then
                            set bLow to do shell script "echo " & quoted form of bName & " | tr '[:upper:]' '[:lower:]'"
                            if bLow contains "unmute" then
                                return "muted"
                            end if
                            if bLow contains "mute" then
                                return "unmuted"
                            end if
                        end if
                    end try
                end repeat
            end repeat
        on error
        end try
    end tell
    return "off"
end tell
"""


def _probe_huddle() -> tuple[bool, bool]:
    """Return ``(in_huddle, is_muted)`` by reading Slack's accessibility tree.

    Falls back to ``(False, False)`` on any error or non-macOS platform.
    """
    if _SYSTEM != "Darwin":
        return False, False
    try:
        result = subprocess.run(
            ["osascript", "-e", _OSASCRIPT],
            capture_output=True, text=True, timeout=2.5,
        )
        out = result.stdout.strip().lower()
        log.debug("Slack huddle probe: %r", out)
        if out == "muted":
            return True, True
        if out == "unmuted":
            return True, False
    except Exception as exc:
        log.debug("Slack huddle probe failed: %s", exc)
    return False, False


# ---------------------------------------------------------------------------
# Bridge
# ---------------------------------------------------------------------------


class SlackBridge(FocusBridge):
    """Slack shortcut bridge with live huddle mute-state tracking on LED 4.

    Args:
        badge:  :class:`~dc29.badge.BadgeAPI` instance to control.
        config: Optional :class:`~dc29.config.Config` (defaults to singleton).
    """

    target_app_names = ("Slack",)

    def __init__(self, badge: BadgeAPI, config: Optional[Config] = None) -> None:
        super().__init__(badge)
        cfg = config or get_config()
        self._button_actions: dict[int, str] = cfg.slack_button_actions
        self._led_colors: dict[str, tuple[int, int, int]] = {
            **_DEFAULT_LED_COLORS,
            **cfg.slack_led_colors,
        }
        self._shortcuts = _SHORTCUTS_MAC if _SYSTEM == "Darwin" else _SHORTCUTS_WIN
        self._page = self._build_page()

        self._in_huddle: bool = False
        self._huddle_muted: bool = False
        self._huddle_poll_task: Optional[asyncio.Task] = None

    @property
    def page(self) -> BridgePage:
        return self._page

    def _build_page(self) -> BridgePage:
        buttons: dict[int, PageButton] = {}
        for btn, action in self._button_actions.items():
            led = self._led_colors.get(action, POSITION_ACTIVE.get(btn, (60, 60, 60)))
            buttons[btn] = PageButton(label=action, led=led)
        return BridgePage(
            name="slack",
            description="Slack — productivity shortcuts",
            brand_color=BRAND_COLORS["slack"],
            buttons=buttons,
        )

    # ------------------------------------------------------------------
    # FocusBridge hooks
    # ------------------------------------------------------------------

    async def on_focus_gained(self) -> None:
        self._huddle_poll_task = asyncio.create_task(
            self._poll_loop(), name="slack-huddle-poll"
        )

    async def on_focus_lost(self) -> None:
        if self._huddle_poll_task:
            self._huddle_poll_task.cancel()
            self._huddle_poll_task = None
        if self._in_huddle:
            self._update_huddle_state(False, False)

    # ------------------------------------------------------------------
    # Huddle polling
    # ------------------------------------------------------------------

    async def _poll_loop(self) -> None:
        while True:
            try:
                loop = asyncio.get_running_loop()
                in_huddle, is_muted = await loop.run_in_executor(None, _probe_huddle)
                self._update_huddle_state(in_huddle, is_muted)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.debug("Slack poll error", exc_info=True)
            await asyncio.sleep(_HUDDLE_POLL_INTERVAL)

    def _update_huddle_state(self, in_huddle: bool, is_muted: bool) -> None:
        entering = in_huddle and not self._in_huddle
        leaving  = not in_huddle and self._in_huddle

        self._in_huddle    = in_huddle
        self._huddle_muted = is_muted

        btn = self._huddle_button()
        if btn is None:
            return

        if entering:
            log.info("Slack huddle started — mute tracking active")
            self._badge.set_button_flash(False)
        elif leaving:
            log.info("Slack huddle ended — mute tracking stopped")
            self._badge.set_button_flash(True)

        if in_huddle:
            if is_muted:
                self._badge.set_led(btn, *POSITION_ACTIVE[1])   # red  = muted
            else:
                self._badge.set_led(btn, *POSITION_ACTIVE[4])   # green = live
        else:
            pb = self._page.buttons.get(btn)
            if pb:
                self._badge.set_led(btn, *pb.led)

    def _huddle_button(self) -> Optional[int]:
        for btn, action in self._button_actions.items():
            if action == "huddle":
                return btn
        return None

    # ------------------------------------------------------------------
    # Button handling
    # ------------------------------------------------------------------

    async def handle_button(self, btn: int) -> None:
        action = self._button_actions.get(btn)
        if not action:
            return
        if action == "huddle" and self._in_huddle:
            log.info("Slack: huddle mute toggle")
            self._inject("huddle-mute")
        else:
            log.info("Slack: button %d → %s", btn, action)
            self._inject(action)

    # ------------------------------------------------------------------
    # Shortcut injection
    # ------------------------------------------------------------------

    def _inject(self, action: str) -> None:
        shortcut = self._shortcuts.get(action)
        if shortcut is None:
            log.debug("No shortcut for Slack action %r", action)
            return
        if not _PYNPUT_AVAILABLE:
            log.warning("pynput not installed — shortcut injection skipped")
            return
        _press_shortcut(*shortcut)


def _press_shortcut(modifier_names: list[str], key: object) -> None:
    if not _PYNPUT_AVAILABLE:
        return
    kb = _KbController()

    mods = []
    for name in modifier_names:
        try:
            mods.append(getattr(_Key, name))
        except AttributeError:
            pass

    if isinstance(key, str):
        if key == "space":
            main_key = _Key.space
        elif len(key) == 1:
            main_key = _KeyCode.from_char(key)
        else:
            main_key = getattr(_Key, key, None)
    else:
        main_key = key

    if main_key is None:
        return

    for mod in mods:
        kb.press(mod)
    kb.press(main_key)
    kb.release(main_key)
    for mod in reversed(mods):
        kb.release(mod)
