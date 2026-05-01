#!/usr/bin/env bash
# Full inner-loop iteration: build → wait for bootloader → flash → console.
# Usage: scripts/dev.sh [--no-build] [--no-console]

set -eu

BUILD=1
CONSOLE=1
for arg in "$@"; do
	case "$arg" in
		--no-build)   BUILD=0   ;;
		--no-console) CONSOLE=0 ;;
		-h|--help)
			sed -n '2,4p' "$0"; exit 0 ;;
		*)
			echo "unknown arg: $arg" >&2; exit 2 ;;
	esac
done

cd "$(dirname "$0")/.."   # -> Firmware/Source/DC29

if (( BUILD )); then
	echo "▸ make"
	make
fi

echo
echo "▸ flash"
scripts/flash.sh

if (( CONSOLE )); then
	echo
	echo "▸ console (waiting for CDC enumeration)"
	scripts/console.sh --wait
fi
