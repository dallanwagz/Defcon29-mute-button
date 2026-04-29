# Windows Build Handoff

This file is a session handoff for the Claude Code agent on the Windows machine.
Pull the `playground` branch and follow the steps below.

## What was done on the Mac (summary)

Firmware cleanup + macropad hardening on `playground`:

| File | Change |
|------|--------|
| `Firmware/Source/DC29/src/keys.c` | Emits `0x01 B n mod key` over CDC before each button press |
| `Firmware/Source/DC29/src/serialconsole.c` | Stripped to escape-byte dispatcher only (~100 lines vs 1661); fixed `set_button_keymap` boundary-marker guard |
| `Firmware/Source/DC29/src/serialconsole.h` | Stripped to bare minimum |
| `Firmware/Source/DC29/src/main.h` | FIRMWARE_VERSION→2, compact EEPROM layout (offsets 1-26), default button4 keymap = ctrl+alt+m |
| `Firmware/Source/DC29/src/main.c` | Removed game/challenge globals, unwrapped IDLE check, removed Simon ISR/audio |
| `Firmware/Source/DC29/src/comms.c` | Stripped inter-badge protocol; kept UART hardware setup and callbacks |
| `Firmware/Source/DC29/src/comms.h` | Removed inter-badge function declarations |
| `games.c` / `games.h` | Deleted |
| `tools/teams_mute_indicator.py` | Python-side: reader thread, `set_led()`, `LedAnimator` with rainbow chase, `--brightness`, `--idle-animation` |

The full bidirectional escape protocol is now:

| Direction | Bytes | Meaning |
|-----------|-------|---------|
| Mac → Badge | `0x01 M` | LED 4 → red (muted) |
| Mac → Badge | `0x01 U` | LED 4 → green (unmuted) |
| Mac → Badge | `0x01 X` | LED 4 → off (not in meeting) |
| Mac → Badge | `0x01 K n mod key` | Set button n (1–6) to modifier+keycode, saved to EEPROM |
| Mac → Badge | `0x01 Q n` | Query button n keymap |
| Mac → Badge | `0x01 L n r g b` | Set LED n (1–4) color immediately (not saved) |
| Badge → Mac | `0x01 B n mod key` | Button n was pressed, first keymap entry |
| Badge → Mac | `0x01 R n mod key` | Reply to Q query |
| Badge → Mac | `0x01 A n` | ACK after K set-keymap |

## Expected behavior after flash

FIRMWARE_VERSION is now 2. On first boot after flash the badge detects the version mismatch
and calls `reset_eeprom()`, writing the new compact layout with the default keymap including
button 4 = ctrl+alt+m (modifier `0x05`, keycode `0x10`).

The Mac-side Python service triggers mute toggle via the `0x01 B 4` CDC event (serial
side-channel), not the HID keystroke — so button 4 works even if HID is momentarily broken.
After flashing, the service log should show `Badge button 4 pressed → modifier=0x05 keycode=0x10`
on each press.

## Build steps (Microchip Studio 7.0, Windows)

1. `git pull origin playground` (or clone if not already present)
2. Open `Firmware/Source/Defcon29.atsln` in Microchip Studio
3. Confirm **Release** configuration is selected (not Debug — Debug doesn't fit in 56 KB)
4. Confirm preprocessor symbol is `__SAMD21G16B__` only (Project → Properties → Toolchain → ARM/GNU C Compiler → Symbols). Do **not** also add `__SAMD21J18A__`.
5. Confirm linker script is `src/samd21g16b_flash.ld` (ORIGIN = 0x2000). Both `<armgcc.linker.miscellaneous.LinkerFlags>` entries in the Release `<PropertyGroup>` of the `.cproj` must point here.
6. Build → Build Solution. Output should end with no errors.
7. Convert: `uf2conv.py DC29.hex --convert --output DC29.uf2`

## Flash steps

1. Hold **bottom-right button (BUTTON4)**.
2. Plug in USB — badge appears as a mass-storage drive, top-left LED blinks red.
3. **Release the button immediately** once the drive mounts. Holding it across reboot traps the badge in DFU indefinitely (looks like a crash — just unplug and replug without holding any button).
4. Drag `DC29.uf2` onto the drive.
5. Drive disappears → badge rebooted. Confirm a CDC serial port appears (`COMx` on Windows).

## After flashing — verification on Mac

With the badge plugged in and the launchd service running
(`~/Library/LaunchAgents/com.local.dc29-teams-mute.plist`):

```
tail -f /tmp/dc29-teams-mute.err
```

Expected on startup:
```
Badge button 4 keymap: modifier=0x05 keycode=0x10
```

Expected each time button 4 is pressed:
```
Badge button 4 pressed → modifier=0x05 keycode=0x10
```

If modifier or keycode is wrong, use the badge serial console menu (option 2 → button 4)
and type `[ctrl][alt]m` to restore the correct keymap.

## Mac service config (already deployed)

- Plist: `~/Library/LaunchAgents/com.local.dc29-teams-mute.plist`
- Python: `/Users/dallan/repo/Defcon29-mute-button/.venv/bin/python3`
- Port: `/dev/tty.usbmodem123451`
- Toggle hotkey: `<ctrl>+<alt>+m`

To reload after reflash:
```
launchctl unload ~/Library/LaunchAgents/com.local.dc29-teams-mute.plist
launchctl load  ~/Library/LaunchAgents/com.local.dc29-teams-mute.plist
```
