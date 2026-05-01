---
name: flash-badge
description: Build the DC29 firmware (if needed) and flash the connected badge over UF2. Use this every time firmware in Firmware/Source/DC29/src/ changes. Handles toolchain PATH, polling for the bootloader drive, copying the .uf2, and verifying CDC re-enumeration. Args after the slash command are passed through; supports "--no-build" to skip make and "--rebuild" to force a clean build.
---

You are flashing new firmware onto a DEF CON 29 badge connected via USB to the user's macOS machine. Follow these steps in order. **Do NOT skip the diagnostic steps** — the button-during-reboot trap is a real failure mode that wastes hours if you ignore it.

## Inputs you should parse from the user's invocation

- `--no-build` → skip the `make` step; flash whatever `.uf2` is already on disk.
- `--rebuild` → run `make clean && make` instead of incremental `make`.
- (default, no flags) → run `make` (incremental — instant if nothing changed).

If the user attaches additional natural-language context (e.g. "and remind me to restart dc29 start"), incorporate it into the final report.

## Step 0: Survey the working tree (silent — no shell output to user)

Read the project state so the report at the end is grounded:

1. `git rev-parse --abbrev-ref HEAD` — what branch are we on?
2. `pgrep -f 'dc29 (start|flow|ui|teams)'` — is `dc29` currently running? If yes, the user must restart it after flash because the badge gets a new serial port number on each enumeration cycle and the running process holds the old one.
3. `ls /dev/tty.usbmodem*` — is the badge currently enumerated as a CDC device?
4. `ls /Volumes/*/INFO_UF2.TXT 2>/dev/null` — is it already in bootloader mode?

Use this to tailor the user-facing instructions in step 2.

## Step 1: Build the firmware (unless --no-build)

```bash
export PATH="$HOME/opt/arm-gnu-toolchain/Payload/bin:$PATH"
cd "$(git rev-parse --show-toplevel)/Firmware/Source/DC29"
make           # or: make clean && make for --rebuild
```

The macOS toolchain lives at `~/opt/arm-gnu-toolchain/Payload/bin/` (extracted via `pkgutil --expand-full` from the Homebrew cask). If `arm-none-eabi-gcc` is not on PATH, the build will fail — re-run with the `export PATH=...` prefix above.

**Verify the build succeeded** by checking for `Firmware/Source/DC29/build/DC29.uf2` and noting its size from the build output (look for the `text data bss` table). Image must fit in 56 KB (57344 bytes for `.text + .data + .rodata`); if it doesn't, the linker reports `region 'rom' overflowed` and you should stop and tell the user.

## Step 2: Get the badge into bootloader mode

If Step 0 already detected `/Volumes/*/INFO_UF2.TXT`: skip to Step 3.

Otherwise, tell the user **exactly this** (don't paraphrase — the wording matters):

> Unplug the badge. Hold the bottom-right button (B4). Plug it into USB while still holding B4. **Release B4 the moment the `DC29Badge` drive appears in Finder** — holding the button across the reboot is the trap that fakes a "broken firmware" failure. The polling script below will detect the drive and copy automatically.

Then start the polling script (foreground, with a 90-second timeout).

## Step 3: Poll for the bootloader drive and copy the .uf2

```bash
cd "$(git rev-parse --show-toplevel)"
UF2=Firmware/Source/DC29/build/DC29.uf2
start=$(date +%s); volume=""
while :; do
  for v in /Volumes/*/; do [ -f "${v}INFO_UF2.TXT" ] && volume="${v%/}" && break; done
  [ -n "$volume" ] && break
  [ $(($(date +%s) - start)) -ge 90 ] && { echo "✗ timeout — no UF2 bootloader drive within 90s"; exit 1; }
  sleep 0.3
done
echo "→ found bootloader at: $volume"
sed 's/^/    /' "$volume/INFO_UF2.TXT" 2>/dev/null | head -4
echo "→ copying $UF2 ($(stat -f%z "$UF2") bytes)..."
cp "$UF2" "$volume/"
for _ in $(seq 1 15); do
  [ -d "$volume" ] || { echo "✓ flashed — drive unmounted"; exit 0; }
  sleep 0.4
done
echo "⚠ copy completed but drive still mounted; replug without holding any button"
```

Sanity-check the `INFO_UF2.TXT` shows `Board-ID: SAMD21G16B-dc29-v0` — if it doesn't (e.g. user has another UF2-capable device mounted), abort and tell the user.

## Step 4: Verify CDC re-enumeration

After the bootloader unmounts, the badge reboots into the new firmware. Wait for `/dev/tty.usbmodem*` to reappear:

```bash
for i in $(seq 1 50); do
  port=$(ls -t /dev/tty.usbmodem* 2>/dev/null | head -1)
  [ -n "$port" ] && { echo "✓ badge alive on $port"; exit 0; }
  sleep 0.2
done
echo "✗ no CDC port within 10s — replug without holding any button (button-during-reboot trap)"
```

If the badge does NOT re-enumerate within 10 seconds, the user fell into the button-during-reboot trap (held B4 across the bootloader's reboot, which traps it back into DFU). **Do not assume the firmware is broken.** Tell the user to unplug and replug **without holding any button**, then rerun this step.

## Step 5: Report

Concise, factual. Include:

- Branch you flashed from (from Step 0).
- Build size (from Step 1's `text + data + rodata`) vs the 56 KB ceiling.
- The new `/dev/tty.usbmodem*` device path.
- If `dc29` was running before (Step 0 detected it): a one-liner reminder that the user needs to stop and restart it because the port number may have changed and the old process is holding a stale handle. **Do not** kill the user's running `dc29` process automatically — surface it as a recommendation.
- If anything in Steps 0–4 was unusual (different bootloader Board-ID, unexpected size, missing toolchain), call it out.

Keep the report under ~10 lines. The user is iterating fast and doesn't need ceremony — just confirmation it worked.

## When NOT to use this skill

- The user wants to flash an arbitrary `.uf2` (different repo, different firmware). Use Bash directly with the user's path.
- The badge is permanently unresponsive (no UF2 drive after multiple replug attempts). That's hardware debugging, not a flash workflow.
- The user is on Windows. Microchip Studio + drag-and-drop in Explorer; this skill is macOS-specific because it polls `/Volumes/`.
