"""
dc29.bridges.outlook — Microsoft Outlook shortcut bridge.

Activates a page of 4 Outlook shortcuts when Outlook has focus.  Button 1
is the **delete** key — mapped to a bright red LED with a satisfying
breathe-pulse animation on LEDs 2–4 after each press.

Default button layout
---------------------
.. list-table::
   :header-rows: 1

   * - Button
     - Action
     - Shortcut (mac / win)
     - LED color
   * - 1
     - **Delete email**
     - Cmd+Delete / Delete
     - **red** (always on)
   * - 2
     - Reply
     - Cmd+R / Ctrl+R
     - blue
   * - 3
     - Reply All
     - Cmd+Shift+R / Ctrl+Shift+R
     - yellow
   * - 4
     - Forward
     - Cmd+J / Ctrl+F
     - purple

Delete pulse animation
----------------------
After pressing Delete, LEDs 2–4 pulse with the delete color (red by
default, configurable) in two smooth breathe cycles, then restore the
page LED state.  The animation is fully configurable:

* ``pulse_color`` — RGB color of the pulse (default ``(220, 0, 0)``)
* ``pulse_count`` — number of breathe cycles (default ``2``)
* ``pulse_steps`` — smoothness (higher = smoother, default ``20``)
* ``pulse_step_ms`` — ms per brightness step (default ``25``)

Color profiles
--------------
Customize button LED colors in ``~/.config/dc29/config.toml``::

    [outlook.colors]
    delete    = "220,0,0"
    reply     = "0,60,180"
    reply-all = "180,160,0"
    forward   = "100,0,180"
    pulse     = "255,0,0"

Usage::

    badge = BadgeAPI("/dev/tty.usbmodem14201")
    bridge = OutlookBridge(badge)
    asyncio.run(bridge.run())
"""

from __future__ import annotations

import asyncio
import logging
import platform
from typing import Optional

from dc29.badge import BadgeAPI
from dc29.bridges.base import BridgePage, PageButton
from dc29.bridges.colors import BRAND_COLORS, POSITION_ACTIVE
from dc29.bridges.focus import FocusBridge
from dc29.bridges.slack import _press_shortcut, _PYNPUT_AVAILABLE
from dc29.config import Config, get_config

log = logging.getLogger(__name__)

_SYSTEM = platform.system()

# -----------------------------------------------------------------
# Shortcuts
# -----------------------------------------------------------------

_SHORTCUTS_MAC: dict[str, tuple[list[str], object]] = {
    "delete":    (["cmd"], "delete"),
    "reply":     (["cmd"], "r"),
    "reply-all": (["cmd", "shift"], "r"),
    "forward":   (["cmd"], "j"),
    "archive":   (["cmd"], "e"),
    "flag":      (["cmd", "shift"], "h"),
}

_SHORTCUTS_WIN: dict[str, tuple[list[str], object]] = {
    "delete":    ([], "delete"),
    "reply":     (["ctrl"], "r"),
    "reply-all": (["ctrl", "shift"], "r"),
    "forward":   (["ctrl"], "f"),
    "archive":   (["ctrl"], "e"),
    "flag":      (["ctrl", "shift"], "g"),
}

_DEFAULT_BUTTON_ACTIONS: dict[int, str] = {
    1: "delete",
    2: "reply",
    3: "reply-all",
    4: "forward",
}

_DEFAULT_LED_COLORS: dict[str, tuple[int, int, int]] = {
    # Default layout: B1=delete, B2=reply, B3=reply-all, B4=forward
    # Positional semantics land almost perfectly here.
    "delete":    POSITION_ACTIVE[1],  # warm red  — destructive ✓
    "reply":     POSITION_ACTIVE[2],  # cool blue — direct communication ✓
    "reply-all": POSITION_ACTIVE[3],  # amber     — reach everyone ✓
    "forward":   POSITION_ACTIVE[4],  # green     — send forward / create new thread ✓
    "archive":   POSITION_ACTIVE[4],  # green     — positive triage action
    "flag":      POSITION_ACTIVE[3],  # amber     — mark / find later
}

_DEFAULT_PULSE_COLOR: tuple[int, int, int] = (255, 0, 0)


def _resolve_shortcuts() -> dict[str, tuple[list[str], object]]:
    return _SHORTCUTS_MAC if _SYSTEM == "Darwin" else _SHORTCUTS_WIN


class OutlookBridge(FocusBridge):
    """Activates 4 Outlook shortcuts when Outlook has focus.

    Pressing the Delete button triggers a red LED satisfaction-pulse
    animation on LEDs 2–4.

    Args:
        badge:         :class:`~dc29.badge.BadgeAPI` instance to control.
        config:        Optional :class:`~dc29.config.Config` (defaults to singleton).
        pulse_color:   Override the pulse color (R, G, B).  Defaults to
                       ``(255, 0, 0)`` or ``[outlook.colors] pulse`` from config.
        pulse_count:   Number of breathe cycles after delete (default 2).
        pulse_steps:   Brightness steps per half-cycle; higher = smoother (default 20).
        pulse_step_ms: Milliseconds per brightness step (default 25).
    """

    target_app_names = ("Microsoft Outlook", "Outlook")

    def __init__(
        self,
        badge: BadgeAPI,
        config: Optional[Config] = None,
        pulse_color: Optional[tuple[int, int, int]] = None,
        pulse_count: int = 2,
        pulse_steps: int = 20,
        pulse_step_ms: int = 25,
    ) -> None:
        super().__init__(badge)
        cfg = config or get_config()
        self._button_actions: dict[int, str] = cfg.outlook_button_actions
        self._led_colors: dict[str, tuple[int, int, int]] = {
            **_DEFAULT_LED_COLORS,
            **cfg.outlook_led_colors,
        }
        self._pulse_color = pulse_color or cfg.outlook_pulse_color or _DEFAULT_PULSE_COLOR
        self._pulse_count = pulse_count
        self._pulse_steps = pulse_steps
        self._pulse_step_ms = pulse_step_ms
        self._shortcuts = _resolve_shortcuts()
        self._page = self._build_page()
        self._pulse_task: Optional[asyncio.Task] = None

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
            name="outlook",
            description="Outlook — email shortcuts",
            brand_color=BRAND_COLORS["outlook"],
            buttons=buttons,
        )

    async def handle_button(self, btn: int) -> None:
        action = self._button_actions.get(btn)
        if not action:
            return
        log.info("Outlook: button %d → %s", btn, action)
        self._inject(action)
        if action == "delete":
            self._start_delete_pulse()

    # ------------------------------------------------------------------
    # Delete satisfaction animation
    # ------------------------------------------------------------------

    def _start_delete_pulse(self) -> None:
        """Start the delete-pulse animation, cancelling any in-progress one."""
        if self._pulse_task and not self._pulse_task.done():
            self._pulse_task.cancel()
        self._pulse_task = asyncio.create_task(
            self._delete_pulse(), name="outlook-delete-pulse"
        )

    async def _delete_pulse(self) -> None:
        """Breathe-pulse LEDs 2–4 with the pulse color, then restore page LEDs."""
        r, g, b = self._pulse_color
        steps = self._pulse_steps
        step_s = self._pulse_step_ms / 1000.0

        try:
            for _ in range(self._pulse_count):
                # Fade up
                for i in range(1, steps + 1):
                    v = i / steps
                    for led in (2, 3, 4):
                        self._badge.set_led(led, int(r * v), int(g * v), int(b * v))
                    await asyncio.sleep(step_s)
                # Fade down
                for i in range(steps - 1, -1, -1):
                    v = i / steps
                    for led in (2, 3, 4):
                        self._badge.set_led(led, int(r * v), int(g * v), int(b * v))
                    await asyncio.sleep(step_s)
        except asyncio.CancelledError:
            pass
        finally:
            # Restore the page LED state (button 1 stays red; 2–4 restore)
            for btn, action in self._button_actions.items():
                if btn in (2, 3, 4):
                    led = self._led_colors.get(action, (0, 0, 0))
                    self._badge.set_led(btn, *led)

    # ------------------------------------------------------------------
    # Shortcut injection
    # ------------------------------------------------------------------

    def _inject(self, action: str) -> None:
        shortcut = self._shortcuts.get(action)
        if shortcut is None:
            log.debug("No shortcut defined for Outlook action %r", action)
            return
        if not _PYNPUT_AVAILABLE:
            log.warning("pynput not installed — shortcut injection skipped")
            return

        mods, key = shortcut
        if action == "delete" and _SYSTEM == "Darwin":
            # Cmd+Delete = "move to trash" on macOS Outlook
            try:
                from pynput.keyboard import Controller, Key
                kb = Controller()
                with kb.pressed(Key.cmd):
                    kb.press(Key.delete)
                    kb.release(Key.delete)
            except Exception as exc:
                log.warning("Shortcut injection failed: %s", exc)
        elif action == "delete" and _SYSTEM == "Windows":
            try:
                from pynput.keyboard import Controller, Key
                kb = Controller()
                kb.press(Key.delete)
                kb.release(Key.delete)
            except Exception as exc:
                log.warning("Shortcut injection failed: %s", exc)
        else:
            _press_shortcut(mods, key)
