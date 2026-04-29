# Windows Build Handoff

This file is a session handoff for the Claude Code agent on the Windows machine.
Pull the `playground` branch and follow the steps below.

## What was done on the Mac (summary)

Three firmware files were modified and pushed to `playground`:

| File | Change |
|------|--------|
| `Firmware/Source/DC29/src/keys.c` | Emits `0x01 B n mod key` over CDC before each button press |
| `Firmware/Source/DC29/src/serialconsole.c` | Extended escape protocol with `K` (set keymap), `Q` (query keymap), `L` (set LED color) commands |
| `tools/teams_mute_indicator.py` | Python-side: reader thread, `set_led()`, `LedAnimator` with chase pattern, `--idle-animation` CLI flag |

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

## Active debugging problem

Button 4 is configured in EEPROM to send `[ctrl][alt]y` (modifier `0x05`, keycode `0x1C`).
The Mac-side Python service listens for `Ctrl+Alt+Y` globally and calls the Teams WebSocket
`toggle-mute` action. However it's not yet confirmed whether the badge is actually sending
the right bytes — that's what the new firmware will reveal. After flashing, the service log
will show `Badge button 4 pressed → modifier=0x05 keycode=0x1C` on each press if correct.

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
Badge button 4 keymap: modifier=0x05 keycode=0x1C
```

Expected each time button 4 is pressed:
```
Badge button 4 pressed → modifier=0x05 keycode=0x1C
```

If modifier or keycode is wrong, the keymap can now be set programmatically from Python
without touching the serial menu — no firmware change needed:

```python
badge.set_keymap(4, 0x05, 0x1C)   # ctrl+alt+y
```

## Mac service config (already deployed)

- Plist: `~/Library/LaunchAgents/com.local.dc29-teams-mute.plist`
- Python: `/Users/dallan/repo/Defcon29-mute-button/.venv/bin/python3`
- Port: `/dev/tty.usbmodem123451`
- Toggle hotkey: `<ctrl>+<alt>+y`

To reload after reflash:
```
launchctl unload ~/Library/LaunchAgents/com.local.dc29-teams-mute.plist
launchctl load  ~/Library/LaunchAgents/com.local.dc29-teams-mute.plist
```
