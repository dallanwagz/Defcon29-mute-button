#!/usr/bin/env python3
"""Non-destructive F01/F02 listener.

Registers double-tap, long-press, and 2-button chord mappings on the badge,
then prints every event it receives WITHOUT injecting any system keystrokes.
The previous version of this harness mapped long-press to Cmd+W, which
closed the iTerm tab running the listener and prevented any events from
being captured.

Output is mirrored to ``/tmp/dc29_input_test.log`` via tee-style flushing,
so even if a future demo does kill the terminal, captured events survive.

Usage:
    .venv/bin/python tools/test_input_modifiers.py [PORT] [SECONDS]

Defaults: PORT=/dev/tty.usbmodem123451, SECONDS=120.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

from dc29.badge import BadgeAPI

LOG_PATH = Path("/tmp/dc29_input_test.log")


def main() -> int:
    port = sys.argv[1] if len(sys.argv) > 1 else "/dev/tty.usbmodem123451"
    duration = float(sys.argv[2]) if len(sys.argv) > 2 else 120.0

    log = LOG_PATH.open("w", buffering=1)

    def emit(line: str) -> None:
        print(line, flush=True)
        log.write(line + "\n")

    badge = BadgeAPI(port)
    time.sleep(1.0)
    emit(f"connected={badge.connected}")
    if not badge.connected:
        emit("badge not connected — aborting")
        return 1

    # Firmware treats (mod=0, key=0) as "slot unused" and falls through to
    # the legacy fast path — no EXT events would fire.  We set mod=0x01
    # (LeftCtrl) with key=0x00 as a sentinel: action_is_set() returns true
    # so the state machine engages, but fire_action() early-returns on
    # key==0, so no HID keystroke is injected.
    badge.clear_modifier_actions()
    badge.set_modifier_action("double", 1, 0x01, 0x00)
    badge.set_modifier_action("triple", 1, 0x01, 0x00)
    badge.set_modifier_action("long", 1, 0x01, 0x00)
    badge.set_chord_action(1, 2, 0x01, 0x00)

    counts = {"legacy": 0, "ext": 0}

    def on_press(btn: int, mod: int, kc: int) -> None:
        counts["legacy"] += 1
        emit(f"[{counts['legacy']+counts['ext']:02d}] LEGACY single btn={btn} mod=0x{mod:02X} kc=0x{kc:02X}")

    def on_ext(kind: str, a: int, c: int | None) -> None:
        counts["ext"] += 1
        if c is None:
            emit(f"[{counts['legacy']+counts['ext']:02d}] EXT {kind} btn={a}")
        else:
            emit(f"[{counts['legacy']+counts['ext']:02d}] EXT {kind} btn={a}+{c}")

    badge.on_button_press = on_press
    badge.on_button_ext = on_ext

    emit("=" * 60)
    emit(f"Listening for {duration:.0f}s. NO host keystrokes are injected.")
    emit("Try:")
    emit("  • B1 single tap          → EXT? no — single fires via LEGACY path after 250ms window")
    emit("  • B1 double tap          → EXT double btn=1")
    emit("  • B1 triple tap          → EXT triple btn=1")
    emit("  • B1 hold ≥500ms         → EXT long btn=1")
    emit("  • B1 + B2 within 80ms    → EXT chord btn=1+2")
    emit("  • B3, B4 single          → LEGACY single (fast-path, no modifier set)")
    emit(f"Logging to {LOG_PATH}")
    emit("=" * 60)

    deadline = time.monotonic() + duration
    try:
        while time.monotonic() < deadline:
            time.sleep(0.25)
    except KeyboardInterrupt:
        emit("interrupted")

    emit(f"--- {counts['legacy']} legacy + {counts['ext']} extended events captured.")
    badge.close()
    log.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
