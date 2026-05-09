#!/usr/bin/env python3
"""F04 beep-pattern audible test.

Plays each of the 8 firmware patterns with a 1.5 s pause between, then
exercises:
  * SILENCE cancels a long pattern (TEAMS_RINGING)
  * Pattern preempts pattern (CI_PASSED interrupted by CI_FAILED)
  * Coexistence with F03 haptic click (the click is suppressed during
    a pattern; can't be auto-verified without ear-on-badge, but a
    button-press is fired mid-pattern so user can confirm)

Usage:
    .venv/bin/python tools/test_beep_patterns.py [PORT]

Expected runtime: ~25 s.  Listen.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

from dc29.badge import BadgeAPI
from dc29.protocol import BeepPattern

LOG_PATH = Path("/tmp/dc29_beep_test.log")


def main() -> int:
    port = sys.argv[1] if len(sys.argv) > 1 else "/dev/tty.usbmodem123451"
    log = LOG_PATH.open("w", buffering=1)

    def emit(s: str) -> None:
        ts = time.strftime("%H:%M:%S")
        line = f"[{ts}] {s}"
        print(line, flush=True)
        log.write(line + "\n")

    badge = BadgeAPI(port)
    time.sleep(1.5)
    emit(f"connected={badge.connected}")
    if not badge.connected:
        emit("badge not connected — aborting")
        return 1

    emit("")
    emit("=== Phase 1: play each of 8 patterns (1.5 s gap) ===")
    for p in BeepPattern:
        emit(f"  → {p.name}")
        badge.play_beep(p)
        time.sleep(1.5)

    emit("")
    emit("=== Phase 2: SILENCE cancels mid-pattern ===")
    emit("  start TEAMS_RINGING (long), wait 200ms, send SILENCE")
    badge.play_beep(BeepPattern.TEAMS_RINGING)
    time.sleep(0.2)
    badge.play_beep(BeepPattern.SILENCE)
    emit("  buzzer should be silent now (verify by ear)")
    time.sleep(1.5)

    emit("")
    emit("=== Phase 3: pattern preempts pattern ===")
    emit("  start CI_PASSED, wait 80ms, send CI_FAILED")
    badge.play_beep(BeepPattern.CI_PASSED)
    time.sleep(0.08)
    badge.play_beep(BeepPattern.CI_FAILED)
    emit("  expect: short snippet of CI_PASSED then full CI_FAILED")
    time.sleep(2.0)

    emit("")
    emit("=== Phase 4: F03 click suppression during pattern ===")
    emit("  start TEAMS_RINGING, then quietly fire a fake button press via 'T'")
    emit("  (takeover-ripple) — that DOES preempt the pattern (cancel-on-takeover")
    emit("  is per design); confirm pattern stops + takeover click fires")
    badge.play_beep(BeepPattern.TEAMS_RINGING)
    time.sleep(0.05)
    # Use the takeover trigger (0x01 'T' n) so user doesn't need to physically
    # press a button.  Same arbitration path.
    from dc29.protocol import ESCAPE, CMD_FIRE_TAKEOVER
    badge._write(bytes([ESCAPE, CMD_FIRE_TAKEOVER, 1]))
    time.sleep(2.0)

    emit("")
    emit(f"--- done.  Log: {LOG_PATH}")
    badge.close()
    log.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
