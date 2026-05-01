"""
dc29.bridges.base — Abstract base for badge bridges and the BridgePage model.

A *bridge* connects an external service (Teams, Slack, …) to the badge and
owns a *page* — a set of per-button behaviors that replace the badge's normal
EEPROM keymaps while the bridge is active.

Page lifecycle
--------------
1. Bridge starts → calls ``badge.push_page(page)`` to claim buttons and set LEDs.
2. Badge button-press events are routed to ``bridge.handle_button(btn)``.
3. Bridge stops / disconnects → calls ``badge.pop_page()`` to restore normal behaviour.

Button ownership
----------------
A bridge only claims the buttons it cares about.  Unowned buttons fire normal
HID keystrokes from EEPROM as usual.  LED 4 is special-cased in :class:`TeamsBridge`
as the mute indicator and is always full-brightness regardless of the page LED spec.

Extending
---------
To add a new integration (e.g. Slack, Zoom, OBS):

1. Subclass :class:`BaseBridge`.
2. Implement :meth:`run` (an asyncio coroutine that runs forever).
3. Return a :class:`BridgePage` from the :attr:`page` property.
4. In :meth:`run`, call ``self._badge.push_page(self.page)`` on connect and
   ``self._badge.pop_page()`` on disconnect.
5. Override :meth:`handle_button` to act on button presses.

Example skeleton::

    class MyBridge(BaseBridge):
        @property
        def page(self) -> BridgePage:
            return BridgePage(
                name="my-service",
                description="My custom integration",
                buttons={
                    1: PageButton("end-call",   led=(180, 0, 0)),
                    2: PageButton("toggle-video", led=(0, 0, 180)),
                    4: PageButton("toggle-mute",  led=(180, 0, 0)),
                },
            )

        async def handle_button(self, btn: int) -> None:
            if btn == 4:
                await self._send_action("toggle-mute")

        async def run(self) -> None:
            ...
"""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Callable, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from dc29.badge import BadgeAPI

log = logging.getLogger(__name__)


@dataclass
class PageButton:
    """Describes one button's role within a :class:`BridgePage`.

    Args:
        label:      Short human-readable action name (e.g. ``"toggle-mute"``).
        led:        Static LED color (R, G, B) 0–255 to show while the page is
                    active.  Pass ``(0, 0, 0)`` to leave the LED dark.  Bridges
                    may override this dynamically (e.g. mute indicator flips
                    between red and green).
        led_active: Optional alternative color for the "active / on" state.
        led_inactive: Optional alternative color for the "inactive / off" state.
    """

    label: str
    led: tuple[int, int, int] = (0, 0, 0)
    led_active: tuple[int, int, int] = (0, 180, 0)
    led_inactive: tuple[int, int, int] = (180, 0, 0)


@dataclass
class BridgePage:
    """A named set of button behaviors pushed by a bridge onto the badge.

    While a page is active, :class:`~dc29.badge.BadgeAPI` routes button-press
    events to the owning bridge rather than letting the badge firmware fire its
    EEPROM keystrokes.

    Args:
        name:        Slug identifier used in config / logs (e.g. ``"teams"``).
        description: One-line human label shown in the TUI.
        buttons:     Map of button number (1–4) → :class:`PageButton`.  Only
                     buttons listed here are intercepted; others behave normally.
        brand_color: Optional (R, G, B) color for the context-switch flash
                     animation played when this page gains focus.  ``None``
                     skips the animation and applies LEDs immediately.
    """

    name: str
    description: str = ""
    buttons: dict[int, PageButton] = field(default_factory=dict)
    brand_color: Optional[tuple[int, int, int]] = None


class BaseBridge(ABC):
    """Abstract base class for all badge bridges.

    Concrete subclasses connect an external service to the badge.  The base
    class handles page lifecycle, button routing setup, and the reconnect loop
    pattern.

    Args:
        badge: The :class:`~dc29.badge.BadgeAPI` instance to control.
    """

    def __init__(self, badge: "BadgeAPI") -> None:
        self._badge = badge
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        # Cookie returned by badge.add_button_handler — held so we can
        # cleanly deregister in _uninstall_button_hook (and survive hot-stop
        # via task.cancel without leaking handlers).
        self._button_handler_record = None
        # Set by BridgeManager from BRIDGE_MANIFEST priority before the run
        # task is created.  Defaults to 0 if the bridge is started directly
        # (e.g. unit tests), in which case ties keep insertion order.
        self._priority_value: int = 0

        self.on_state_change: Optional[Callable] = None
        """Optional callback fired (from the asyncio loop) on any state change."""

    # ------------------------------------------------------------------
    # Abstract interface
    # ------------------------------------------------------------------

    @property
    @abstractmethod
    def page(self) -> BridgePage:
        """The :class:`BridgePage` this bridge contributes to the badge."""
        ...

    @abstractmethod
    async def run(self) -> None:
        """Run the bridge forever; cancel the task to stop."""
        ...

    async def handle_button(self, btn: int) -> None:
        """Called when a button owned by this bridge's page is pressed.

        Default implementation does nothing.  Override to dispatch actions.

        Args:
            btn: Button number (1–4).
        """

    # ------------------------------------------------------------------
    # Lifecycle helpers — call from subclass run()
    # ------------------------------------------------------------------

    def _should_handle_button(self, btn: int) -> bool:
        """Return True if this bridge should intercept a button press right now.

        Default: always intercept owned buttons.  Override to add conditions
        (e.g. :class:`TeamsBridge` only intercepts while in a meeting;
        :class:`FocusBridge` only intercepts while its app is focused).

        Args:
            btn: Button number (1–4).
        """
        return True

    def _install_button_hook(self) -> None:
        """Register a priority-ordered button handler with the badge.

        Idempotent — calling twice is a no-op (already-registered handlers
        are not duplicated).  Bridges hot-toggled by :class:`BridgeManager`
        rely on the matching :meth:`_uninstall_button_hook` cleanly removing
        the registration on cancellation.
        """
        self._loop = asyncio.get_running_loop()
        if self._button_handler_record is not None:
            return  # already installed

        owned = set(self.page.buttons.keys())

        def _on_button(btn: int, mod: int, kc: int) -> None:
            # Reader thread → marshal onto our event loop.
            self._loop.call_soon_threadsafe(
                asyncio.ensure_future,
                self.handle_button(btn),
            )

        self._button_handler_record = self._badge.add_button_handler(
            name=self.page.name,
            priority=self._priority_value,
            owned_buttons=owned,
            should_handle=self._should_handle_button,
            handler=_on_button,
        )

    def _uninstall_button_hook(self) -> None:
        """Deregister the button handler (idempotent)."""
        if self._button_handler_record is not None:
            self._badge.remove_button_handler(self._button_handler_record)
            self._button_handler_record = None

    def _apply_page_leds(self) -> None:
        """Set LED colors for all buttons defined in :attr:`page`."""
        for btn, pb in self.page.buttons.items():
            if btn <= 4:
                self._badge.set_led(btn, *pb.led)

    def _clear_page_leds(self) -> None:
        """Turn off LEDs for all buttons defined in :attr:`page`."""
        for btn in self.page.buttons:
            if btn <= 4:
                self._badge.set_led(btn, 0, 0, 0)
