#!/usr/bin/env python3
"""Hardware test for F03 — haptic-style buzzer click on macro send.

Phase 1: button_flash OFF, haptic_click ON  → expect click on every press
Phase 2: button_flash OFF, haptic_click OFF → expect silence on every press
Phase 3: button_flash ON  (default restored) → expect takeover animation +
         its built-in click (haptic suppressed automatically)

Logs every observed button press to /tmp/dc29_haptic_test.log so we can
correlate user reports of "I heard a click" / "I didn't" with actual events.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

from dc29.badge import BadgeAPI

LOG_PATH = Path("/tmp/dc29_haptic_test.log")
PHASE_SECS = 20.0


def main() -> int:
    port = sys.argv[1] if len(sys.argv) > 1 else "/dev/tty.usbmodem123451"
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

    counts = {"presses": 0}

    def on_press(btn: int, mod: int, kc: int) -> None:
        counts["presses"] += 1
        emit(f"  · press btn={btn}  (#{counts['presses']})")

    badge.on_button_press = on_press

    def run_phase(label: str, button_flash: bool, haptic: bool, expect: str) -> None:
        badge.set_button_flash(button_flash)
        badge.set_haptic_click(haptic)
        time.sleep(0.2)
        emit("")
        emit("=" * 60)
        emit(f"PHASE: {label}")
        emit(f"  button_flash={button_flash}  haptic_click={haptic}")
        emit(f"  EXPECT: {expect}")
        emit(f"  Tap any button (B1-B4) for {PHASE_SECS:.0f}s.")
        emit("=" * 60)
        deadline = time.monotonic() + PHASE_SECS
        while time.monotonic() < deadline:
            time.sleep(0.25)

    try:
        run_phase(
            "1 of 3 — haptic ON, no takeover",
            button_flash=False, haptic=True,
            expect="faint high-pitch click on every press",
        )
        run_phase(
            "2 of 3 — both OFF",
            button_flash=False, haptic=False,
            expect="silence on every press (LEDs unchanged too)",
        )
        run_phase(
            "3 of 3 — takeover restored",
            button_flash=True, haptic=True,
            expect="full LED ripple + personality click; F03 stays out of the way",
        )
    finally:
        badge.set_button_flash(True)
        badge.set_haptic_click(True)
        emit("")
        emit(f"--- {counts['presses']} total presses captured.")
        badge.close()
        log.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
