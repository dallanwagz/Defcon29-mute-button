# Windows Build Handoff

This file contains complete instructions for the Claude Code agent on the Windows machine
to build and flash the DEF CON 29 badge firmware.

---

## Objective

Build the firmware from the `playground` branch and flash it to the badge over USB.
The badge is an ATSAMD21G16B repurposed as a USB macro keypad with a Teams mute indicator.

---

## Prerequisites

- **Microchip Studio 7.0** must be installed.
- **Git** must be available.
- **Python 3** must be available (`python` or `python3` on PATH) for the UF2 conversion step.
- The badge must be present and able to enter DFU (bootloader) mode.

---

## Step 1 — Get the code

If this repo is already cloned on this machine, pull the latest:

```
git pull origin playground
git checkout playground
```

If it is not cloned yet:

```
git clone https://github.com/dallanwagz/Defcon29-mute-button.git
cd Defcon29-mute-button
git checkout playground
```

Confirm you are on the `playground` branch and that the latest commit matches the one pushed
from the Mac (run `git log --oneline -5` and check for the firmware cleanup commit).

---

## Step 2 — Get uf2conv.py

`uf2conv.py` is needed to convert the compiled `.hex` to `.uf2` for the bootloader.

Check if it is already present anywhere on the machine:
```
where uf2conv.py
```

If not found, download it:
```
curl -o uf2conv.py https://raw.githubusercontent.com/microsoft/uf2/master/utils/uf2conv.py
```
or download it manually from https://github.com/microsoft/uf2/blob/master/utils/uf2conv.py
and save it to the repo root or somewhere on PATH.

---

## Step 3 — Build in Microchip Studio

1. Open `Firmware\Source\Defcon29.atsln` in Microchip Studio 7.0.

2. In the Solution Explorer, expand the project. You should see the source files under `src\`.
   Verify that `games.c` and `games.h` are **not** present — they were deleted as part of the
   cleanup. If Microchip Studio shows a missing-file error for them, right-click each and
   choose "Remove from Project".

3. Set the build configuration to **Release** (not Debug — Debug does not fit in the 56 KB
   available after the 8 KB bootloader).

4. Verify build settings — these should already be correct in the `.cproj` but double-check:
   - **Project → Properties → Toolchain → ARM/GNU C Compiler → Symbols**
     Must contain `__SAMD21G16B__`. Must NOT also contain `__SAMD21J18A__`.
   - **Project → Properties → Toolchain → ARM/GNU C Linker → Miscellaneous → Linker Flags**
     Must end with `-T../src/samd21g16b_flash.ld` (ORIGIN = 0x2000).
     Must NOT reference `samd21j18a_flash.ld` (ORIGIN = 0x0 — this would overwrite the
     bootloader and brick the badge).

5. Build: **Build → Build Solution** (Ctrl+Shift+B).

   The output window should end with something like:
   ```
   Program Memory Usage  :  XXXXX bytes  XX.X% Full
   Data Memory Usage     :  XXXX bytes   XX.X% Full
   Build succeeded.
   ```
   Program memory should be well under 57344 bytes (56 KB). If it says "Build FAILED",
   check the error list — do not proceed to flash.

6. The compiled output is at:
   ```
   Firmware\Source\DC29\Release\DC29.hex
   ```

---

## Step 4 — Convert to UF2

From the repo root (or wherever `uf2conv.py` is):

```
python uf2conv.py Firmware\Source\DC29\Release\DC29.hex --convert --output DC29.uf2
```

Confirm `DC29.uf2` was created and is non-zero in size.

---

## Step 5 — Enter DFU (bootloader) mode

1. **Hold** the bottom-right button (BUTTON4 / physical button at bottom-right of badge).
2. While holding it, **plug the badge into USB**.
3. The top-left LED will blink red and the badge will appear as a USB mass-storage drive
   (e.g. `D:\` or `E:\`).
4. **Release the button immediately** once the drive letter appears in Explorer.
   - If you hold the button through the reboot, the badge gets stuck in DFU indefinitely
     (it looks like a crash). Fix: unplug and replug USB without holding any button.

---

## Step 6 — Flash

Drag and drop `DC29.uf2` onto the DFU drive, or use the command line:

```
copy DC29.uf2 D:\
```
(substitute the correct drive letter)

The drive will disappear within a second as the badge reboots with new firmware.

---

## Step 7 — Verify the badge rebooted

After flashing, unplug and replug the badge (no button held). A CDC serial port should
appear in Device Manager under "Ports (COM & LPT)" — note the COM number (e.g. `COM5`).

The badge's startup LED sequence (red → green → blue chase across all 4 LEDs) confirms
the firmware is running.

---

## What happens on first boot after this flash

`FIRMWARE_VERSION` was bumped from 1 to 2. On first boot the badge detects the mismatch
and calls `reset_eeprom()`, which:
- Erases and reinitializes the EEPROM with the new compact layout
- Writes the default keymap including button 4 = **ctrl+alt+m** (modifier `0x05`, keycode `0x10`)
- Sets default LED colors (red / green / blue / grey)

This is expected and correct. No manual keymap programming is needed after flash.

---

## After flashing — verification on Mac

Bring the badge back to the Mac. With the badge plugged in, reload the launchd service:

```
launchctl unload ~/Library/LaunchAgents/com.local.dc29-teams-mute.plist
launchctl load  ~/Library/LaunchAgents/com.local.dc29-teams-mute.plist
```

Then watch the log:

```
tail -f /tmp/dc29-teams-mute.err
```

**Expected on startup:**
```
Badge button 4 keymap: modifier=0x05 keycode=0x10
```

**Expected each time button 4 is pressed:**
```
Badge button 4 pressed → modifier=0x05 keycode=0x10
```

If the keymap line shows wrong values (modifier or keycode not 0x05/0x10), the EEPROM reset
did not apply the default correctly. Fix by sending the `K` command from the Mac Python
service directly (the interactive serial console menu no longer exists in this firmware):

```python
# Run this once from a Python REPL with pyserial installed, badge on /dev/tty.usbmodem*
import serial, time
s = serial.Serial('/dev/tty.usbmodem123451', 9600, timeout=1)
s.write(bytes([0x01, ord('K'), 4, 0x05, 0x10]))   # set button 4 to ctrl+alt+m
time.sleep(0.1)
print(s.read(3))  # should print b'\x01An' (ACK for button 4)
s.close()
```

---

## Escape-byte protocol reference

The full bidirectional side-channel over USB CDC (`0x01` prefix):

| Direction    | Bytes              | Meaning                                           |
|--------------|--------------------|---------------------------------------------------|
| Mac → Badge  | `0x01 M`           | LED 4 → red (muted)                               |
| Mac → Badge  | `0x01 U`           | LED 4 → green (unmuted)                           |
| Mac → Badge  | `0x01 X`           | LED 4 → off (not in meeting)                      |
| Mac → Badge  | `0x01 K n mod key` | Set button n (1–6) to single key; saved to EEPROM |
| Mac → Badge  | `0x01 Q n`         | Query button n keymap                             |
| Mac → Badge  | `0x01 L n r g b`   | Set LED n (1–4) color immediately (not saved)     |
| Badge → Mac  | `0x01 B n mod key` | Button n was pressed, first keymap entry          |
| Badge → Mac  | `0x01 R n mod key` | Reply to Q query                                  |
| Badge → Mac  | `0x01 A n`         | ACK after K set-keymap                            |
