"""
dc29 — CLI and library tools for the DEF CON 29 badge macro-keypad.

The badge is an ATSAMD21G16B (ARM Cortex-M0+) running custom firmware that
presents itself as a USB CDC serial port and a USB HID keyboard.  This package
provides:

* :mod:`dc29.protocol` — authoritative protocol constants and helpers
* :mod:`dc29.badge`    — :class:`~dc29.badge.BadgeAPI`, the thread-safe
  serial interface
* :mod:`dc29.bridges`  — optional bridges (Teams WebSocket, etc.)
* ``dc29`` CLI entry point — run ``dc29 --help`` for available commands
"""

__version__ = "1.0.0"

__all__ = [
    "__version__",
    "BadgeAPI",
    "BadgeState",
    "protocol",
    "config",
]

from dc29.badge import BadgeAPI, BadgeState
from dc29 import protocol
from dc29 import config
