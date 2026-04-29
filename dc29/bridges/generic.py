"""
dc29.bridges.generic — Data-driven FocusBridge: add apps without writing Python.

A :class:`PageDef` describes an entire app integration — what process/window
to watch, what 4 shortcuts to bind, what brand color to flash.
:class:`GenericFocusBridge` turns that data into a running bridge.

New apps live in :mod:`dc29.bridges.registry`.  To add another app, add one
``PageDef`` there — no Python subclass needed.
"""

from __future__ import annotations

import logging
import platform
from dataclasses import dataclass, field
from typing import Optional

from dc29.badge import BadgeAPI
from dc29.bridges.base import BridgePage, PageButton
from dc29.bridges.colors import POSITION_ACTIVE
from dc29.bridges.focus import FocusBridge

log = logging.getLogger(__name__)

_SYSTEM = platform.system()

_PYNPUT_AVAILABLE = False
try:
    from pynput.keyboard import Controller as _KbController, Key as _Key, KeyCode as _KeyCode
    _PYNPUT_AVAILABLE = True
except ImportError:
    pass


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class ActionDef:
    """A single button binding: label + platform-specific shortcut.

    Args:
        label:        Short human name shown in logs and the TUI.
        shortcut_mac: ``([modifier_names], key_string)`` for macOS.
        shortcut_win: ``([modifier_names], key_string)`` for Windows/Linux.

    Modifier names: ``"cmd"``, ``"ctrl"``, ``"shift"``, ``"alt"``.

    Key strings:
    - Single character: ``"a"``, ``"["``
    - Named special key: ``"escape"``, ``"delete"``, ``"backspace"``,
      ``"enter"``, ``"left"``, ``"f5"`` — anything in pynput ``Key.*``.
    """

    label: str
    shortcut_mac: tuple[list[str], str]
    shortcut_win: tuple[list[str], str]

    def shortcut(self) -> tuple[list[str], str]:
        return self.shortcut_mac if _SYSTEM == "Darwin" else self.shortcut_win


@dataclass
class PageDef:
    """Complete definition for one app's bridge page.

    Args:
        name:               Slug identifier (e.g. ``"vscode"``).
        description:        One-line label shown in the TUI.
        match_names:        Process or window-title substrings to watch for
                            (case-insensitive).
        button_actions:     Map of button number (1–4) → :class:`ActionDef`.
        brand_color:        (R, G, B) for the context-switch flash animation.
        match_window_title: ``True`` for web apps — match against the browser
                            window title rather than the process name.
    """

    name: str
    description: str
    match_names: list[str]
    button_actions: dict[int, ActionDef] = field(default_factory=dict)
    brand_color: Optional[tuple[int, int, int]] = None
    match_window_title: bool = False


# ---------------------------------------------------------------------------
# Bridge
# ---------------------------------------------------------------------------

class GenericFocusBridge(FocusBridge):
    """A :class:`~dc29.bridges.focus.FocusBridge` driven entirely by a :class:`PageDef`.

    Args:
        badge:    :class:`~dc29.badge.BadgeAPI` instance to control.
        page_def: :class:`PageDef` describing the app integration.
    """

    def __init__(self, badge: BadgeAPI, page_def: PageDef) -> None:
        super().__init__(badge)
        self._page_def = page_def
        self.match_window_title: bool = page_def.match_window_title
        self._built_page = self._build_page()

    @property
    def target_app_names(self) -> tuple[str, ...]:
        return tuple(self._page_def.match_names)

    @property
    def page(self) -> BridgePage:
        return self._built_page

    def _build_page(self) -> BridgePage:
        buttons: dict[int, PageButton] = {}
        for btn, action_def in self._page_def.button_actions.items():
            led = POSITION_ACTIVE.get(btn, (60, 60, 60))
            buttons[btn] = PageButton(label=action_def.label, led=led)
        return BridgePage(
            name=self._page_def.name,
            description=self._page_def.description,
            brand_color=self._page_def.brand_color,
            buttons=buttons,
        )

    async def handle_button(self, btn: int) -> None:
        action_def = self._page_def.button_actions.get(btn)
        if not action_def:
            return
        if not _PYNPUT_AVAILABLE:
            log.warning("pynput not installed — shortcut injection skipped")
            return
        mods, key = action_def.shortcut()
        log.info("%s: button %d → %s", self._page_def.name, btn, action_def.label)
        _press_shortcut(mods, key)


def _press_shortcut(modifier_names: list[str], key: object) -> None:
    """Press modifier+key and release cleanly."""
    if not _PYNPUT_AVAILABLE:
        return

    kb = _KbController()

    _MOD_MAP_MAC = {"cmd": "cmd", "shift": "shift", "alt": "alt", "ctrl": "ctrl"}
    _MOD_MAP_WIN = {"ctrl": "ctrl", "shift": "shift", "alt": "alt", "cmd": "cmd"}
    mod_map = _MOD_MAP_MAC if _SYSTEM == "Darwin" else _MOD_MAP_WIN

    mods = []
    for name in modifier_names:
        resolved = mod_map.get(name, name)
        try:
            mods.append(getattr(_Key, resolved))
        except AttributeError:
            pass

    if isinstance(key, str) and len(key) == 1:
        main_key = _KeyCode.from_char(key)
    elif isinstance(key, str) and key.startswith("Key."):
        main_key = getattr(_Key, key[4:], None)
    elif isinstance(key, str):
        # Named special key: "escape", "delete", "backspace", "enter", "left", "f5", etc.
        main_key = getattr(_Key, key, None)
    else:
        main_key = key

    if main_key is None:
        log.debug("Could not resolve key %r — shortcut skipped", key)
        return

    for mod in mods:
        kb.press(mod)
    kb.press(main_key)
    kb.release(main_key)
    for mod in reversed(mods):
        kb.release(mod)
