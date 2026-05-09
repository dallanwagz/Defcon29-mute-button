#!/usr/bin/env python3
"""F06 hyper-fast HID burst test.

Phase 1: short string ("Hello, F06 burst!\n") — visual sanity check.
Phase 2: 256-char known string + timing — verify no drops + throughput
         is in the expected ballpark (≤ 600 ms per the F06 success
         criteria, allowing for chunk overhead).
Phase 3: cancel mid-burst — fire a long string then cancel ~50 ms in,
         confirm the burst stops fast.

Usage:
    1. Open TextEdit (or any editable text field).  Click into the
       window so it has keyboard focus.
    2. .venv/bin/python tools/test_hid_burst.py [PORT]
    3. Watch the typed output.  Manually verify the strings.

There is a 5-second countdown at the top so you can switch focus to
the target window after launching.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

from dc29.badge import BadgeAPI

LOG_PATH = Path("/tmp/dc29_burst_test.log")

PHASE1_TEXT = "Hello, F06 burst!\n"
# 256 chars: a..z * 9 + 0..9 + 4 punctuation = 234+10+4 = 248, pad with periods.
PHASE2_TEXT = (
    ("abcdefghijklmnopqrstuvwxyz" * 9)   # 234
    + "0123456789"                       # 244
    + ",./;\n"                           # 249
    + "."  * 7                           # 256
)
assert len(PHASE2_TEXT) == 256
PHASE3_TEXT = "X" * 200  # long enough to stay running while we cancel


def main() -> int:
    port = sys.argv[1] if len(sys.argv) > 1 else "/dev/tty.usbmodem123451"
    log = LOG_PATH.open("w", buffering=1)

    def emit(s: str) -> None:
        ts = time.strftime("%H:%M:%S")
        line = f"[{ts}] {s}"
        print(line, flush=True)
        log.write(line + "\n")

    badge = BadgeAPI(port)
    time.sleep(1.0)
    emit(f"connected={badge.connected}")
    if not badge.connected:
        emit("badge not connected — aborting")
        return 1

    emit("")
    emit("Switch focus to your text editor NOW.")
    for i in range(5, 0, -1):
        emit(f"  Phase 1 starts in {i} ...")
        time.sleep(1.0)

    emit("")
    emit("=== Phase 1: short string ===")
    emit(f"  typing {PHASE1_TEXT!r} ({len(PHASE1_TEXT)} chars)")
    t0 = time.monotonic()
    badge.type_string(PHASE1_TEXT)
    t1 = time.monotonic()
    emit(f"  done in {(t1 - t0) * 1000:.0f} ms")

    emit("")
    emit("=== Phase 2: 256-char known string + timing ===")
    emit(f"  typing 256 chars (a..z * 9 + 0..9 + ,./;\\n + 7 periods)")
    time.sleep(2.0)
    t0 = time.monotonic()
    badge.type_string(PHASE2_TEXT)
    t1 = time.monotonic()
    expected_ms = 256 * 8 + 50  # 4 frames × 2 ms × 256 + chunk slack
    emit(f"  done in {(t1 - t0) * 1000:.0f} ms (expected ~{expected_ms} ms)")

    emit("")
    emit("=== Phase 3: cancel mid-burst ===")
    emit(f"  start typing {len(PHASE3_TEXT)} 'X's, cancel after ~120ms")
    time.sleep(2.0)
    # Send the burst directly without the type_string sleep so we can cancel
    # mid-flight.  Bypass chunk-wait by writing the raw command and not
    # waiting for completion.
    pairs = [(0, 27)] * len(PHASE3_TEXT)  # HID 27 = 'x'
    flat = bytearray()
    flat.append(0x01)
    flat.append(0x68)  # 'h'
    flat.append(len(pairs) & 0xFF)
    flat.append((len(pairs) >> 8) & 0xFF)
    for mod, key in pairs:
        flat.append(mod)
        flat.append(key)
    badge._write(bytes(flat))
    time.sleep(0.12)
    badge.hid_burst_cancel()
    emit("  cancel sent — burst should stop within ~5 ms")
    time.sleep(1.0)

    emit("")
    emit(f"--- done.  Log: {LOG_PATH}")
    badge.close()
    log.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
