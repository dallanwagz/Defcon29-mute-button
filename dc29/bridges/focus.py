"""
dc29.bridges.focus — Focus-aware bridge base class.

:class:`FocusBridge` activates its page whenever one of its target
applications is the frontmost window.  It polls the active app every
:attr:`FocusBridge.POLL_INTERVAL` seconds (default 0.5 s).

Priority
--------
:class:`FocusBridge` respects an active Teams meeting: if
:attr:`~dc29.badge.BadgeState.mute_state` is not
:attr:`~dc29.protocol.MuteState.NOT_IN_MEETING`, button interception and
LED management are suspended so the Teams meeting page stays in control.

Platform support
----------------
* **macOS** — AppleScript via ``osascript`` (no extra dependencies)
* **Windows** — ``ctypes`` win32 API (no extra dependencies)
* **Linux** — ``xdotool`` subprocess (install ``xdotool``; optional)
"""

from __future__ import annotations

import asyncio
import logging
import platform
from abc import abstractmethod
from typing import Optional

from dc29.bridges.base import BaseBridge, BridgePage
from dc29.protocol import MuteState

log = logging.getLogger(__name__)

_SYSTEM = platform.system()


# ---------------------------------------------------------------------------
# Platform-level active-app detection
# ---------------------------------------------------------------------------

def _get_active_app() -> Optional[str]:
    """Return the name of the currently focused application, or ``None``."""
    try:
        if _SYSTEM == "Darwin":
            return _macos_active_app()
        elif _SYSTEM == "Windows":
            return _windows_active_app()
        elif _SYSTEM == "Linux":
            return _linux_active_app()
    except Exception:
        pass
    return None


def _macos_active_app() -> Optional[str]:
    import subprocess
    result = subprocess.run(
        [
            "osascript", "-e",
            'tell application "System Events" to get name of first process whose frontmost is true',
        ],
        capture_output=True, text=True, timeout=1.5,
    )
    return result.stdout.strip() or None


def _windows_active_app() -> Optional[str]:
    import ctypes
    import ctypes.wintypes
    import os

    hwnd = ctypes.windll.user32.GetForegroundWindow()
    if not hwnd:
        return None
    pid = ctypes.wintypes.DWORD()
    ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    if not pid.value:
        return None
    h_proc = ctypes.windll.kernel32.OpenProcess(0x0410, False, pid.value)
    if not h_proc:
        return None
    buf = ctypes.create_unicode_buffer(260)
    ctypes.windll.psapi.GetModuleFileNameExW(h_proc, None, buf, 260)
    ctypes.windll.kernel32.CloseHandle(h_proc)
    name = os.path.basename(buf.value)
    # Strip .exe suffix for readability
    if name.lower().endswith(".exe"):
        name = name[:-4]
    return name or None


def _linux_active_app() -> Optional[str]:
    import subprocess
    # Try wmctrl first (returns window title), then xdotool
    for cmd in (
        ["xdotool", "getactivewindow", "getwindowname"],
        ["wmctrl", "-a", ":ACTIVE:"],
    ):
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=1.5)
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    return None


# ---------------------------------------------------------------------------
# FocusBridge
# ---------------------------------------------------------------------------

class FocusBridge(BaseBridge):
    """Activates its page whenever a target application has focus.

    Subclasses must implement :attr:`page` and :attr:`target_app_names`.
    Override :meth:`on_focus_gained` / :meth:`on_focus_lost` for custom
    behaviour beyond LED management.

    Args:
        badge: The :class:`~dc29.badge.BadgeAPI` instance to control.
    """

    POLL_INTERVAL: float = 0.5
    """Seconds between focus-check polls (default 0.5 s)."""

    @property
    @abstractmethod
    def target_app_names(self) -> tuple[str, ...]:
        """Tuple of app name substrings to watch for (case-insensitive)."""
        ...

    # Set by the poll loop; read from the reader thread for _should_handle_button.
    _is_currently_focused: bool = False

    def _should_handle_button(self, btn: int) -> bool:
        return (
            self._is_currently_focused
            and self._badge.state.mute_state == MuteState.NOT_IN_MEETING
        )

    def _check_focus(self) -> bool:
        """Return ``True`` if a target app is currently the frontmost window."""
        active = _get_active_app()
        if active is None:
            return False
        active_lower = active.lower()
        return any(name.lower() in active_lower for name in self.target_app_names)

    async def run(self) -> None:
        """Poll focus state forever, activating the page when the target app is in front."""
        self._loop = asyncio.get_running_loop()
        self._install_button_hook()
        try:
            focused = False
            last_in_meeting = False
            while True:
                now_focused = self._check_focus()
                in_meeting = self._badge.state.mute_state != MuteState.NOT_IN_MEETING

                self._is_currently_focused = now_focused

                if now_focused and not focused:
                    log.info("%s gained focus", self.page.name)
                    if not in_meeting:
                        self._apply_page_leds()
                    await self.on_focus_gained()

                elif not now_focused and focused:
                    log.info("%s lost focus", self.page.name)
                    self._clear_page_leds()
                    await self.on_focus_lost()

                elif now_focused and last_in_meeting and not in_meeting:
                    # Teams meeting ended while this app is focused — restore our LEDs
                    self._apply_page_leds()

                elif now_focused and not last_in_meeting and in_meeting:
                    # Teams meeting started while this app is focused — hand off LEDs
                    self._clear_page_leds()

                focused = now_focused
                last_in_meeting = in_meeting
                await asyncio.sleep(self.POLL_INTERVAL)
        finally:
            self._uninstall_button_hook()
            self._clear_page_leds()

    async def on_focus_gained(self) -> None:
        """Called when a target app gains focus.  Override for custom behaviour."""

    async def on_focus_lost(self) -> None:
        """Called when a target app loses focus.  Override for custom behaviour."""
