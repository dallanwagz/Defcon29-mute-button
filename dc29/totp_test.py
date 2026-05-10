"""dc29.totp_test — F09 golden-vector reference + harness.

Two goals:

1. **Pure host-side reference** :func:`totp_compute` — RFC 6238 6-digit
   TOTP, used by the CLI for sanity checks and by anyone who wants to
   compare what the badge will type without firing the burst.
2. **Live firmware diff** when invoked as a script: provision a known
   key, push specific timestamps, fire each, and (if a HID-keypress
   listener is wired up) check that the typed digits match
   :func:`totp_compute` for the same (key, timestamp).  Without a
   listener, we can at least exercise the protocol path and confirm
   the firmware doesn't crash on the RFC vectors.

Run as: ``.venv/bin/python -m dc29.totp_test``
"""

from __future__ import annotations

import base64
import hmac
import struct
import sys
import time
from hashlib import sha1


def base32_decode(s: str) -> bytes:
    """Lenient base32 decode: strip whitespace + dashes, uppercase, pad."""
    cleaned = "".join(s.split()).replace("-", "").upper()
    pad = (-len(cleaned)) % 8
    return base64.b32decode(cleaned + "=" * pad)


def hotp_compute(key: bytes, counter: int, digits: int = 6) -> str:
    """RFC 4226 HOTP."""
    msg = struct.pack(">Q", counter)
    h = hmac.new(key, msg, sha1).digest()
    off = h[-1] & 0x0F
    bin_code = (
        ((h[off]     & 0x7F) << 24)
        | ((h[off + 1] & 0xFF) << 16)
        | ((h[off + 2] & 0xFF) <<  8)
        |  (h[off + 3] & 0xFF)
    )
    return str(bin_code % (10 ** digits)).zfill(digits)


def totp_compute(key: bytes, unix_time: int,
                 *, period: int = 30, digits: int = 6) -> str:
    """RFC 6238 TOTP wrapper around :func:`hotp_compute`.  Matches the
    firmware-side ``totp_compute()`` output for the same inputs."""
    return hotp_compute(key, unix_time // period, digits=digits)


# ─── RFC 6238 Appendix B golden vectors ───────────────────────────────
# Spec uses 8-digit codes; we truncate to 6 to match the firmware (per
# F09 Q2 default-accept).  20-byte ASCII secret "12345678901234567890".

RFC6238_KEY = b"12345678901234567890"

RFC6238_VECTORS: list[tuple[int, str]] = [
    # (unix_time, expected 6-digit code)
    (         59, "287082"),
    (1111111109, "081804"),
    (1234567890, "005924"),
    (2000000000, "279037"),
]


def run_host_only_tests() -> int:
    """Verify our host-side reference against the RFC vectors.  Returns
    process exit code (0 = pass)."""
    fail = 0
    for ts, expected in RFC6238_VECTORS:
        got = totp_compute(RFC6238_KEY, ts)
        ok = got == expected
        print(f"  t={ts:>10}  expected={expected}  got={got}  {'OK' if ok else 'FAIL'}")
        if not ok:
            fail += 1
    return 1 if fail else 0


def run_firmware_diff_test(port: str) -> int:
    """Provision the RFC key into slot 0, push each test timestamp via
    'T', and fire — the firmware will type the code into whatever has
    focus.  We can't capture the keystrokes here without an accessibility-
    permitted listener, so this is exercising the protocol path; the
    user / a separate listener verifies the typed digits.

    For unattended verification, see ``tools/test_totp.py`` (uses
    pynput global listener if accessibility is granted).
    """
    from dc29.badge import BadgeAPI

    badge = BadgeAPI(port)
    time.sleep(1.0)
    if not badge.connected:
        print("badge not connected — aborting", file=sys.stderr)
        return 1

    print(f"provisioning slot 0 with RFC6238 test key (label='RFC6')")
    badge.totp_provision(0, "RFC6", RFC6238_KEY)
    time.sleep(0.3)

    for ts, expected in RFC6238_VECTORS:
        print(f"  syncing t={ts}, firing — expect '{expected}' typed into focused window")
        badge.totp_sync_time(ts)
        time.sleep(0.1)
        badge.totp_fire(0)
        # Burst is 6 pairs × ~10 ms = 60 ms; pad to 500 ms before next fire.
        time.sleep(0.5)

    badge.close()
    print("\nfirmware exercised — visually verify the codes typed match the expected column above.")
    return 0


def main() -> int:
    print("=== F09 host-side TOTP reference vs. RFC 6238 Appendix B ===")
    rc = run_host_only_tests()
    if rc != 0:
        print("\nHOST REFERENCE FAILED — fix totp_compute() before flashing", file=sys.stderr)
        return rc

    print("\nHost reference: PASS")

    if len(sys.argv) > 1 and sys.argv[1] == "--firmware":
        port = sys.argv[2] if len(sys.argv) > 2 else "/dev/tty.usbmodem123451"
        print(f"\n=== Live firmware diff via {port} ===")
        return run_firmware_diff_test(port)

    print("\nRun with `--firmware [PORT]` to exercise the badge as well.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
