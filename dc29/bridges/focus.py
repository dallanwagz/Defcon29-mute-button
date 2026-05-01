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

Window title matching
---------------------
Set ``match_window_title = True`` on a subclass (or pass ``page_def.match_window_title``
via :class:`~dc29.bridges.generic.GenericFocusBridge`) to match against the
browser window title rather than the process name.  Required for web apps
(JIRA, Confluence, GitHub, …) running inside Chrome/Firefox/Safari.

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
import threading
import time
from abc import abstractmethod
from typing import Optional

from dc29.bridges.base import BaseBridge, BridgePage
from dc29.protocol import MuteState

log = logging.getLogger(__name__)

_SYSTEM = platform.system()


# ---------------------------------------------------------------------------
# Platform-level active-app detection
# ---------------------------------------------------------------------------

# Shared TTL cache so concurrent FocusBridge polls share a single osascript call.
# Without this, 15+ bridges hitting run_in_executor simultaneously flood System
# Events and all calls time out.
_focus_lock = threading.Lock()
_focus_cache: tuple[str, str] = ("", "")
_focus_cache_at: float = 0.0
_FOCUS_CACHE_TTL: float = 0.35  # seconds


def _get_active_app() -> tuple[str, str]:
    """Return ``(app_name, window_title)`` for the frontmost application.

    Both strings may be empty on failure.  ``window_title`` is only populated
    on a best-effort basis — it is empty on Linux unless ``xdotool`` is installed.

    Results are cached for up to 350 ms so concurrent bridge polls share a
    single subprocess call rather than flooding the OS.
    """
    global _focus_cache, _focus_cache_at
    with _focus_lock:
        if time.monotonic() - _focus_cache_at < _FOCUS_CACHE_TTL:
            return _focus_cache
        try:
            if _SYSTEM == "Darwin":
                result = _macos_active_app()
            elif _SYSTEM == "Windows":
                result = _windows_active_app()
            elif _SYSTEM == "Linux":
                result = _linux_active_app()
            else:
                result = ("", "")
        except Exception:
            result = ("", "")
        _focus_cache = result
        _focus_cache_at = time.monotonic()
        return result


def _macos_active_app() -> tuple[str, str]:
    import subprocess
    result = subprocess.run(
        [
            "osascript", "-e",
            '''tell application "System Events"
                set frontApp to first process whose frontmost is true
                set appName to name of frontApp
                try
                    set winTitle to name of front window of frontApp
                on error
                    set winTitle to ""
                end try
                return appName & "|" & winTitle
            end tell''',
        ],
        capture_output=True, text=True, timeout=1.5,
    )
    output = result.stdout.strip()
    if "|" in output:
        app, _, title = output.partition("|")
        return (app.strip(), title.strip())
    return (output, "")


def _windows_active_app() -> tuple[str, str]:
    import ctypes
    import ctypes.wintypes
    import os

    hwnd = ctypes.windll.user32.GetForegroundWindow()
    if not hwnd:
        return ("", "")

    title_buf = ctypes.create_unicode_buffer(512)
    ctypes.windll.user32.GetWindowTextW(hwnd, title_buf, 512)
    window_title = title_buf.value

    pid = ctypes.wintypes.DWORD()
    ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    if not pid.value:
        return ("", window_title)

    h_proc = ctypes.windll.kernel32.OpenProcess(0x0410, False, pid.value)
    if not h_proc:
        return ("", window_title)

    buf = ctypes.create_unicode_buffer(260)
    ctypes.windll.psapi.GetModuleFileNameExW(h_proc, None, buf, 260)
    ctypes.windll.kernel32.CloseHandle(h_proc)
    name = os.path.basename(buf.value)
    if name.lower().endswith(".exe"):
        name = name[:-4]
    return (name or "", window_title)


def _linux_active_app() -> tuple[str, str]:
    import subprocess

    try:
        win_result = subprocess.run(
            ["xdotool", "getactivewindow"],
            capture_output=True, text=True, timeout=1.5,
        )
        if win_result.returncode == 0:
            win_id = win_result.stdout.strip()
            title_result = subprocess.run(
                ["xdotool", "getwindowname", win_id],
                capture_output=True, text=True, timeout=1.5,
            )
            pid_result = subprocess.run(
                ["xdotool", "getwindowpid", win_id],
                capture_output=True, text=True, timeout=1.5,
            )
            window_title = title_result.stdout.strip()
            if pid_result.returncode == 0:
                pid = pid_result.stdout.strip()
                try:
                    with open(f"/proc/{pid}/comm") as fh:
                        proc_name = fh.read().strip()
                    return (proc_name, window_title)
                except OSError:
                    pass
            return ("", window_title)
    except Exception:
        pass
    return ("", "")


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

    match_window_title: bool = False
    """Set ``True`` to also match :attr:`target_app_names` against the active
    window title — required for web apps running inside a browser."""

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
        app_name, window_title = _get_active_app()
        if not app_name and not window_title:
            return False
        app_lower = app_name.lower()
        title_lower = window_title.lower()
        return any(
            name.lower() in app_lower
            or (self.match_window_title and name.lower() in title_lower)
            for name in self.target_app_names
        )

    async def _context_flash(self) -> None:
        """Flash the page brand color 2× then settle into action colors.

        The quick flash (≈280 ms total) confirms to the user which context is
        now active before the per-button action colors appear.
        """
        brand = self.page.brand_color
        if brand is None:
            self._apply_page_leds()
            return
        r, g, b = brand
        for _ in range(2):
            for led in range(1, 5):
                self._badge.set_led(led, r, g, b)
            await asyncio.sleep(0.08)
            for led in range(1, 5):
                self._badge.set_led(led, 0, 0, 0)
            await asyncio.sleep(0.06)
        self._apply_page_leds()

    async def run(self) -> None:
        """Poll focus state forever, activating the page when the target app is in front."""
        self._loop = asyncio.get_running_loop()
        self._install_button_hook()
        self._saved_effect: int = 0
        try:
            focused = False
            last_in_meeting = False
            while True:
                now_focused = await self._loop.run_in_executor(None, self._check_focus)
                in_meeting = self._badge.state.mute_state != MuteState.NOT_IN_MEETING

                self._is_currently_focused = now_focused

                if now_focused and not focused:
                    log.info("%s gained focus", self.page.name)
                    from dc29.stats import record
                    record.app_focused(self.page.name)
                    if not in_meeting:
                        # Suspend any running effect so bridge LED colors aren't overwritten.
                        self._saved_effect = self._badge.state.effect_mode
                        if self._saved_effect != 0:
                            self._badge.set_effect_mode(0)
                        # Suppress the firmware's white takeover animation on button press —
                        # bridge manages its own LEDs and the flash would corrupt them.
                        self._badge.set_button_flash(False)
                        asyncio.create_task(
                            self._context_flash(),
                            name=f"{self.page.name}-context-flash",
                        )
                        self._badge.set_current_page(self.page)
                    await self.on_focus_gained()

                elif not now_focused and focused:
                    log.info("%s lost focus", self.page.name)
                    # Sticky-LEDs mode (config.sticky_focus_leds): keep the page's
                    # LED colors lit until another bridge gains focus or the user
                    # disables it. Skip the LED clear, effect-mode restoration, and
                    # button-flash re-enable — but still clear set_current_page so
                    # the TUI accurately shows "no app focused".
                    from dc29.config import get_config
                    sticky = get_config().sticky_focus_leds
                    if not sticky:
                        self._clear_page_leds()
                    if not in_meeting:
                        self._badge.set_current_page(None)
                        if not sticky:
                            # Restore effect mode that was active before this bridge took over.
                            if self._saved_effect != 0:
                                self._badge.set_effect_mode(self._saved_effect)
                                self._saved_effect = 0
                            self._badge.set_button_flash(True)
                    await self.on_focus_lost()

                elif now_focused and last_in_meeting and not in_meeting:
                    # Teams meeting ended while this app is focused — restore our page
                    self._badge.set_current_page(self.page)
                    asyncio.create_task(
                        self._context_flash(),
                        name=f"{self.page.name}-context-flash-resume",
                    )

                elif now_focused and not last_in_meeting and in_meeting:
                    # Teams meeting started — Teams will claim current_page
                    self._clear_page_leds()

                focused = now_focused
                last_in_meeting = in_meeting
                await asyncio.sleep(self.POLL_INTERVAL)
        finally:
            self._uninstall_button_hook()
            self._clear_page_leds()
            self._badge.set_current_page(None)

    async def on_focus_gained(self) -> None:
        """Called when a target app gains focus.  Override for custom behaviour."""

    async def on_focus_lost(self) -> None:
        """Called when a target app loses focus.  Override for custom behaviour."""
