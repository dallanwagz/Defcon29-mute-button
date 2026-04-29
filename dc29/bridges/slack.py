"""
dc29.bridges.slack — Slack productivity shortcut bridge.

Activates a page of 4 Slack shortcuts when the Slack desktop app has focus.
Shortcuts are injected as keyboard events via *pynput* (``pip install pynput``).

Default button layout
---------------------
.. list-table::
   :header-rows: 1

   * - Button
     - Action
     - Shortcut (mac / win)
     - LED color
   * - 1
     - All Unreads
     - Cmd+Shift+A / Ctrl+Shift+A
     - blue
   * - 2
     - Mentions & Reactions
     - Cmd+Shift+M / Ctrl+Shift+M
     - purple
   * - 3
     - Quick Switcher
     - Cmd+K / Ctrl+K
     - cyan
   * - 4
     - Toggle Huddle
     - Cmd+Shift+H / Ctrl+Shift+H
     - green

All shortcuts and LED colors are configurable via
``[slack.buttons]`` and ``[slack.colors]`` in
``~/.config/dc29/config.toml``.

Usage::

    badge = BadgeAPI("/dev/tty.usbmodem14201")
    bridge = SlackBridge(badge)
    asyncio.run(bridge.run())
"""

from __future__ import annotations

import logging
import platform
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

# -----------------------------------------------------------------
# Shortcuts: action → ([modifiers], key_char_or_Key)
# -----------------------------------------------------------------
# macOS modifier string → pynput Key
_MOD_MAP_MAC = {"cmd": "_Key.cmd", "shift": "_Key.shift", "alt": "_Key.alt"}
_MOD_MAP_WIN = {"ctrl": "_Key.ctrl", "shift": "_Key.shift", "alt": "_Key.alt"}

_SHORTCUTS_MAC: dict[str, tuple[list[str], object]] = {
    "all-unreads":  (["cmd", "shift"], "a"),
    "mentions":     (["cmd", "shift"], "m"),
    "quick-switch": (["cmd"], "k"),
    "threads":      (["cmd", "shift"], "t"),
    "huddle":       (["cmd", "shift"], "h"),
    "next-unread":  (["alt", "shift"], "↓"),
    "dnd":          (["cmd", "shift"], "i"),
}

_SHORTCUTS_WIN: dict[str, tuple[list[str], object]] = {
    "all-unreads":  (["ctrl", "shift"], "a"),
    "mentions":     (["ctrl", "shift"], "m"),
    "quick-switch": (["ctrl"], "k"),
    "threads":      (["ctrl", "shift"], "t"),
    "huddle":       (["ctrl", "shift"], "h"),
    "next-unread":  (["alt", "shift"], "↓"),
    "dnd":          (["ctrl", "shift"], "i"),
}

_DEFAULT_BUTTON_ACTIONS: dict[int, str] = {
    1: "all-unreads",
    2: "mentions",
    3: "quick-switch",
    4: "huddle",
}

_DEFAULT_LED_COLORS: dict[str, tuple[int, int, int]] = {
    # Default layout: B1=all-unreads, B2=mentions, B3=quick-switch, B4=huddle
    # Colors follow positional semantics (warm-red / blue / amber / green).
    "all-unreads":  POSITION_ACTIVE[1],  # warm red  — the "urgent pile" energy
    "mentions":     POSITION_ACTIVE[2],  # cool blue — @you = direct communication
    "quick-switch": POSITION_ACTIVE[3],  # amber     — navigate/find
    "threads":      POSITION_ACTIVE[2],  # blue      — communication family
    "huddle":       POSITION_ACTIVE[4],  # green     — connect with people
    "next-unread":  POSITION_ACTIVE[3],  # amber     — navigate to next
    "dnd":          POSITION_ACTIVE[1],  # warm red  — do-not-disturb = stop/block
}


def _resolve_shortcuts() -> dict[str, tuple[list[str], object]]:
    return _SHORTCUTS_MAC if _SYSTEM == "Darwin" else _SHORTCUTS_WIN


class SlackBridge(FocusBridge):
    """Activates 4 Slack shortcuts when Slack has focus.

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
        self._shortcuts = _resolve_shortcuts()
        self._page = self._build_page()

    @property
    def page(self) -> BridgePage:
        return self._page

    def _build_page(self) -> BridgePage:
        buttons: dict[int, PageButton] = {}
        for btn, action in self._button_actions.items():
            positional_default = POSITION_ACTIVE.get(btn, (60, 60, 60))
            led = self._led_colors.get(action, positional_default)
            buttons[btn] = PageButton(label=action, led=led)
        return BridgePage(
            name="slack",
            description="Slack — productivity shortcuts",
            brand_color=BRAND_COLORS["slack"],
            buttons=buttons,
        )

    async def handle_button(self, btn: int) -> None:
        action = self._button_actions.get(btn)
        if action:
            log.info("Slack: button %d → %s", btn, action)
            self._inject(action)

    # ------------------------------------------------------------------
    # Shortcut injection
    # ------------------------------------------------------------------

    def _inject(self, action: str) -> None:
        shortcut = self._shortcuts.get(action)
        if shortcut is None:
            log.debug("No shortcut defined for Slack action %r", action)
            return
        if not _PYNPUT_AVAILABLE:
            log.warning("pynput not installed — shortcut injection skipped")
            return
        _press_shortcut(*shortcut)


def _press_shortcut(modifier_names: list[str], key: object) -> None:
    """Press modifier+key and release cleanly."""
    if not _PYNPUT_AVAILABLE:
        return
    kb = _KbController()
    mod_map = _MOD_MAP_MAC if _SYSTEM == "Darwin" else _MOD_MAP_WIN

    # Resolve modifier key objects
    mods = []
    for name in modifier_names:
        attr = mod_map.get(name, f"_Key.{name}")
        # eval the string like "_Key.cmd" → Key.cmd
        try:
            mods.append(getattr(_Key, attr.split(".")[-1]))
        except AttributeError:
            pass

    # Resolve the main key
    if isinstance(key, str) and len(key) == 1:
        main_key = _KeyCode.from_char(key)
    elif isinstance(key, str) and key.startswith("Key."):
        main_key = getattr(_Key, key[4:], None)
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
