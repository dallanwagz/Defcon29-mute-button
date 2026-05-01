#!/usr/bin/env bash
# Wait for a UF2 bootloader volume to appear on macOS, then copy the firmware.
# Usage: scripts/flash.sh [path/to/firmware.uf2]
#
# Default firmware: build/DC29.uf2 (relative to Firmware/Source/DC29/).
# Exits 0 on successful copy, 1 on timeout, 2 on user interrupt.

set -u

UF2="${1:-build/DC29.uf2}"
TIMEOUT_SEC="${TIMEOUT_SEC:-60}"

if [[ ! -f "$UF2" ]]; then
	echo "error: $UF2 not found — run 'make' first" >&2
	exit 1
fi

echo "→ waiting for badge bootloader (hold bottom-right button + plug USB)..."
echo "  giving up after ${TIMEOUT_SEC}s"

start=$(date +%s)
volume=""
while true; do
	# Any /Volumes entry that contains INFO_UF2.TXT is a UF2 bootloader.
	for v in /Volumes/*/; do
		[[ -f "${v}INFO_UF2.TXT" ]] || continue
		volume="${v%/}"
		break
	done
	[[ -n "$volume" ]] && break

	now=$(date +%s)
	if (( now - start >= TIMEOUT_SEC )); then
		echo "error: no UF2 bootloader appeared within ${TIMEOUT_SEC}s" >&2
		exit 1
	fi
	sleep 0.2
done

# Sanity-check it's a SAMD21 bootloader (family 0x68ed2b88 / "SAMD21").
if grep -q "SAMD21\|0x68ed2b88\|ATSAMD21" "${volume}/INFO_UF2.TXT" 2>/dev/null; then
	echo "→ found SAMD21 bootloader at ${volume}"
else
	echo "warning: ${volume} doesn't look like a SAMD21 bootloader — copying anyway" >&2
	echo "  (INFO_UF2.TXT contents:)"
	sed 's/^/    /' "${volume}/INFO_UF2.TXT" 2>/dev/null || true
fi

echo "→ copying $(basename "$UF2") ($(stat -f%z "$UF2") bytes)..."
cp "$UF2" "${volume}/"

# The bootloader unmounts itself; wait briefly for that and report.
for _ in 1 2 3 4 5 6 7 8 9 10; do
	[[ -d "$volume" ]] || { echo "✓ flashed (bootloader unmounted)"; exit 0; }
	sleep 0.3
done
echo "✓ flashed (volume still mounted — bootloader may not have rebooted)"
