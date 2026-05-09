#!/usr/bin/env python3
"""F08a-lite Stay Awake autonomous self-test.

Tests:
    1. Single pulse (`awake_pulse`) drops macOS HIDIdleTime to ~0.
    2. Autonomous mode keeps HIDIdleTime suppressed for the full duration,
       then expires cleanly.
    3. `awake_cancel` mid-session lets HIDIdleTime grow again.

No human in the loop.  Reads idle time via `ioreg -c IOHIDSystem`.
Writes a structured report to /tmp/dc29_awake_test.log.

Usage:
    .venv/bin/python tools/test_stay_awake.py [PORT]
"""

from __future__ import annotations

import re
import subprocess
import sys
import time
from pathlib import Path

from dc29.badge import BadgeAPI

LOG_PATH = Path("/tmp/dc29_awake_test.log")
PULSE_PERIOD_S = 30      # firmware autonomous interval
GRACE_S = 5              # tolerance around pulse timing


_idle_re = re.compile(r'"HIDIdleTime"\s*=\s*(\d+)')


def macos_idle_seconds() -> float:
    """Return current macOS HID idle time in seconds (mouse + keyboard)."""
    out = subprocess.run(
        ["ioreg", "-c", "IOHIDSystem"],
        check=True, capture_output=True, text=True,
    ).stdout
    matches = _idle_re.findall(out)
    if not matches:
        raise RuntimeError("HIDIdleTime not found in ioreg output")
    return min(int(m) for m in matches) / 1e9


def main() -> int:
    port = sys.argv[1] if len(sys.argv) > 1 else "/dev/tty.usbmodem123451"
    log = LOG_PATH.open("w", buffering=1)

    def emit(s: str) -> None:
        ts = time.strftime("%H:%M:%S")
        line = f"[{ts}] {s}"
        print(line, flush=True)
        log.write(line + "\n")

    emit(f"Connecting to {port} ...")
    badge = BadgeAPI(port)
    time.sleep(1.5)
    emit(f"connected={badge.connected}")
    if not badge.connected:
        emit("badge not connected — aborting")
        return 1

    badge.awake_cancel()
    time.sleep(0.3)

    results: list[tuple[str, bool, str]] = []

    def record(name: str, passed: bool, detail: str) -> None:
        results.append((name, passed, detail))
        emit(f"  → {'PASS' if passed else 'FAIL'}: {name} — {detail}")

    # ─────────────────────── Phase 1: single pulse ───────────────────────
    emit("")
    emit("=== Phase 1: single pulse ===")
    emit("Sleeping 8s to let baseline idle accumulate (no HID input expected) ...")
    time.sleep(8.0)
    pre = macos_idle_seconds()
    emit(f"  pre-pulse idle  = {pre:.2f}s")
    badge.awake_pulse()
    time.sleep(0.5)
    post = macos_idle_seconds()
    emit(f"  post-pulse idle = {post:.2f}s")
    record(
        "single pulse resets idle",
        passed=(pre >= 5.0 and post < 1.5),
        detail=f"pre={pre:.2f}s post={post:.2f}s (want pre≥5, post<1.5)",
    )

    # ─────────────────────── Phase 2: autonomous mode ───────────────────────
    duration = 75       # seconds — covers 2 pulse cycles plus some tail
    emit("")
    emit(f"=== Phase 2: autonomous mode ({duration}s) ===")
    badge.awake_set_duration(duration)
    started = time.monotonic()
    emit(f"  awake_set_duration({duration}) sent at t=0")

    samples: list[tuple[float, float]] = []
    # Sample every 5s for duration + 30s of tail.
    sample_until = duration + 30
    while True:
        t = time.monotonic() - started
        if t > sample_until:
            break
        idle = macos_idle_seconds()
        samples.append((t, idle))
        emit(f"  t={t:5.1f}s  idle={idle:5.2f}s")
        time.sleep(5.0)

    badge.awake_cancel()    # belt-and-braces

    # During the active window (0..duration), idle must never exceed
    # PULSE_PERIOD_S + GRACE_S — otherwise the autonomous pulses missed.
    max_active_idle = max(
        (idle for t, idle in samples if t <= duration - 1),
        default=0.0,
    )
    record(
        "autonomous keeps idle bounded",
        passed=max_active_idle < (PULSE_PERIOD_S + GRACE_S),
        detail=f"max idle during {duration}s active window = {max_active_idle:.2f}s "
               f"(want <{PULSE_PERIOD_S + GRACE_S})",
    )

    # After expiration, idle should grow.  Sample at duration+25s should be
    # > duration+25 - last pulse time, but more simply: > 15s, since the last
    # pulse fires at most at t=duration and we're at t≈duration+25.
    tail = [(t, idle) for t, idle in samples if t > duration + 10]
    tail_idle = tail[-1][1] if tail else 0.0
    record(
        "autonomous expires cleanly",
        passed=tail_idle > 10.0,
        detail=f"idle at t≈duration+25 = {tail_idle:.2f}s (want >10)",
    )

    # ─────────────────────── Phase 3: cancel mid-session ───────────────────────
    emit("")
    emit("=== Phase 3: cancel mid-session ===")
    badge.awake_set_duration(120)
    emit("  awake_set_duration(120) sent")
    time.sleep(3.0)
    badge.awake_pulse()    # start with low idle
    time.sleep(0.5)
    badge.awake_cancel()
    cancel_t = time.monotonic()
    emit("  awake_pulse + awake_cancel at t=0")

    idle_grew = False
    for _ in range(7):     # 35s of sampling (5s steps)
        time.sleep(5.0)
        t = time.monotonic() - cancel_t
        idle = macos_idle_seconds()
        emit(f"  t={t:5.1f}s  idle={idle:5.2f}s")
        if idle > 10.0:
            idle_grew = True

    record(
        "cancel stops autonomous",
        passed=idle_grew,
        detail="idle grew >10s post-cancel within 35s window"
               if idle_grew else "idle never exceeded 10s — cancel did NOT take effect",
    )

    # ─────────────────────── Cleanup + report ───────────────────────
    badge.awake_cancel()
    time.sleep(0.3)
    badge.close()

    emit("")
    emit("=" * 60)
    emit("RESULTS")
    emit("=" * 60)
    for name, passed, detail in results:
        emit(f"  {'✓' if passed else '✗'} {name}")
        emit(f"      {detail}")
    all_pass = all(p for _, p, _ in results)
    emit("")
    emit(f"OVERALL: {'PASS' if all_pass else 'FAIL'}  ({sum(p for _, p, _ in results)}/{len(results)})")
    log.close()
    return 0 if all_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
