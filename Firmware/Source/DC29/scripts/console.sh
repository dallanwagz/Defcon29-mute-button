#!/usr/bin/env bash
# Open the badge's USB-CDC serial console on macOS.
# Detects the badge by VID:PID (0xDC29:0xDC29) using ioreg.
# Usage: scripts/console.sh [--wait]
#   --wait  block until the badge appears (default: fail if not present)
#
# Inside `screen`: exit with Ctrl-A then K then Y.
# Inside `tio`:    exit with Ctrl-T then Q.

set -u

WAIT=0
[[ "${1:-}" == "--wait" ]] && WAIT=1
TIMEOUT_SEC="${TIMEOUT_SEC:-30}"

# Find the badge's tty.usbmodem* by walking ioreg for our VID/PID.
# This avoids ambiguity when other USB-CDC devices are connected.
find_port() {
	local match
	match=$(ioreg -p IOUSB -l -r -c IOUSBHostDevice 2>/dev/null \
		| awk '
			/idVendor.*= 56361/ { vid=1 }                # 0xDC29 = 56361
			/idProduct.*= 56361/ { pid=1 }
			vid && pid && /IODialinDevice/ {
				match($0, /"\/dev\/tty\.usbmodem[^"]+"/);
				if (RSTART) {
					print substr($0, RSTART+1, RLENGTH-2);
					exit
				}
			}
			/^[[:space:]]*}/ { vid=0; pid=0 }')
	if [[ -n "$match" ]]; then
		echo "$match"; return 0
	fi
	# Fallback: any tty.usbmodem* (single-device case).
	local candidates=( /dev/tty.usbmodem* )
	if [[ -e "${candidates[0]}" ]]; then
		# Pick the one most recently seen by the kernel.
		ls -t /dev/tty.usbmodem* 2>/dev/null | head -1
		return 0
	fi
	return 1
}

PORT=""
if (( WAIT )); then
	echo "→ waiting for badge CDC port (VID:PID 0xDC29:0xDC29)..."
	start=$(date +%s)
	while true; do
		PORT=$(find_port) && break
		now=$(date +%s)
		if (( now - start >= TIMEOUT_SEC )); then
			echo "error: badge did not enumerate within ${TIMEOUT_SEC}s" >&2
			exit 1
		fi
		sleep 0.2
	done
else
	PORT=$(find_port) || { echo "error: badge not found — replug it (no bootloader button)" >&2; exit 1; }
fi

echo "→ attaching to $PORT"

if command -v tio >/dev/null 2>&1; then
	echo "  (tio: exit with Ctrl-T then Q)"
	exec tio "$PORT"
else
	echo "  (screen: exit with Ctrl-A then K then Y)"
	# Baud is ignored on USB-CDC but screen still wants one.
	exec screen "$PORT" 115200
fi
