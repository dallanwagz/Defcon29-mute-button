# Windows Build Handoff — v2

**Current branch:** `playground`  
**What changed since last build:** ripple LED animation in `pwm.c` / `keys.c`. No EEPROM layout change — existing keymaps and LED colors survive the flash.

---

## Prerequisites

| Thing | Notes |
|-------|-------|
| Microchip Studio 7.0 | Windows only — the only supported build toolchain |
| Python 3 | For UF2 conversion. Already on PATH on the build machine from prior session. |
| `uf2conv.py` + `uf2families.json` | Both must be in the same directory. See Step 2. |
| Git | To pull latest `playground` |

---

## Step 1 — Pull latest code

```
cd <wherever the repo is cloned>
git checkout playground
git pull origin playground
git log --oneline -3
```

The top commit should be:
```
ce84d41  Add multi-app bridge system, firmware ripple animation, and StreamDeck TUI
```

If the hash differs, that's fine — just confirm `playground` is checked out and up to date with origin.

---

## Step 2 — Confirm uf2conv.py + uf2families.json are present

Both files must live in the **same directory** when you run the conversion. Without `uf2families.json` the script errors out silently or produces a zero-byte file.

Check:
```
dir uf2conv.py uf2families.json
```

If either is missing, download both from the same commit of the microsoft/uf2 repo:
- `uf2conv.py` — https://github.com/microsoft/uf2/blob/master/utils/uf2conv.py
- `uf2families.json` — https://github.com/microsoft/uf2/blob/master/utils/uf2families.json

Save them to the repo root or wherever you'll run the conversion from.

---

## Step 3 — Build in Microchip Studio

1. Open `Firmware\Source\Defcon29.atsln`.

2. Set configuration to **Release** (toolbar dropdown). Debug doesn't fit in 56 KB.

3. **Verify these settings are correct** (they should already be committed correctly, just double-check):

   - `Project → Properties → Toolchain → ARM/GNU C Compiler → Symbols`  
     Must contain `__SAMD21G16B__` and nothing else device-specific.  
     Must NOT contain `__SAMD21J18A__`.

   - `Project → Properties → Toolchain → ARM/GNU C Linker → Miscellaneous`  
     Linker flags must end with `-T../src/samd21g16b_flash.ld`  
     Must NOT reference `samd21j18a_flash.ld` (that linker script sets ORIGIN=0x0 and overwrites the bootloader).

4. Build: **Build → Build Solution** (F7 or Ctrl+Shift+B).

5. Expected output in the Build output window:
   ```
   Program Memory Usage :  ~40,000–44,000 bytes  (~75% Full)
   Data Memory Usage    :  ~5,000–6,000 bytes     (~60% Full)
   Build succeeded.
   ```
   The ripple animation added ~2 KB vs the last validated build. If it says "Build FAILED" — stop, do not flash.

6. Output file: `Firmware\Source\DC29\Release\DC29.hex`

---

## Step 4 — Convert to UF2

From the directory containing `uf2conv.py` and `uf2families.json`:

```
python uf2conv.py Firmware\Source\DC29\Release\DC29.hex --convert --output DC29.uf2
```

Verify the output is non-zero:
```
dir DC29.uf2
```

Should be around 77,000–90,000 bytes. If it's 0 bytes or missing, `uf2families.json` is probably not in the same directory.

---

## Step 5 — Enter bootloader (DFU) mode

1. **Hold** the bottom-right button (BUTTON4).
2. While holding it, **plug the badge into USB**.
3. The top-left LED blinks red and the badge mounts as a USB mass-storage drive (e.g. `D:\`).
4. **Release the button immediately** once the drive letter appears in Explorer.

> **Critical gotcha:** If you hold the button through the reboot after flashing, the badge stays in DFU indefinitely — looks identical to a firmware crash. Fix: unplug, wait 2 seconds, replug with no buttons held.

---

## Step 6 — Flash

```
copy DC29.uf2 D:\
```
(substitute the actual drive letter)

Or drag-and-drop `DC29.uf2` onto the drive in Explorer. The drive disappears within 1–2 seconds as the badge reboots.

---

## Step 7 — Verify on Windows (quick smoke test)

Unplug and replug the badge (no buttons held).

Expected:
- Red → green → blue LED chase across all 4 LEDs at startup.
- A CDC serial port appears in Device Manager under "Ports (COM & LPT)" — note the COM number.

Press each of the 4 buttons — each should briefly ripple its color into the adjacent LEDs (the new animation). If the LEDs do nothing on press, the firmware isn't running — check that the drive disappeared after flashing (if it didn't, the UF2 was rejected).

**You're done on Windows.** Bring the badge to the Mac for the software stack verification below.

---

## After flashing — Mac verification

The firmware flash preserves the existing EEPROM (no `FIRMWARE_VERSION` bump — the ripple animation is pure C, no new EEPROM fields). No keymap reprogramming needed.

### 1. Confirm the badge enumerates

```bash
ls /dev/tty.usbmodem*
```

Should show one device. If nothing appears, try a different USB cable (the badge uses the same port for both power and CDC — some cables are charge-only).

### 2. Run dc29 flow

```bash
dc29 flow --port /dev/tty.usbmodem<whatever>
```

Or if autostart is configured, reload it:
```bash
launchctl unload ~/Library/LaunchAgents/com.local.dc29.plist
launchctl load  ~/Library/LaunchAgents/com.local.dc29.plist
```

### 3. Verify the TUI

In a separate terminal tab (the "always-on iTerm companion"):
```bash
dc29 tui --port /dev/tty.usbmodem<whatever>
```

Dashboard → ACTIVE PROFILE should show "NO ACTIVE CONTEXT" initially.

Switch to VS Code → pane should update to show VS CODE with 4 button cards (close-tab / terminal / quick-open / save) glowing in their positional colors.

### 4. Verify the ripple animation

Press any of the 4 buttons while the badge is connected. You should see:
- The pressed LED briefly boosted and its color radiating into adjacent LEDs
- Adjacent LEDs mixing their color with the pressed LED's color (additive blend)
- Fade back to resting colors over ~200ms

This is firmware-side — no Python involvement. If the ripple works but a button's shortcut doesn't fire, that's a `dc29 flow` issue. If neither the ripple nor the shortcut fire, the badge isn't in `flow` mode or the port is wrong.

### 5. Test Teams mute (if Teams is open)

Join a Teams meeting. The badge B4 should go red (muted) or green (live). Pressing B4 toggles mute. The TUI should update context to show the Teams profile.

---

## What changed in this build (vs last Windows build at `2292a30`)

| File | Change |
|------|--------|
| `pwm.c` | Added `led_ripple_start()` / `led_ripple_finish()`: circular additive color-blend ripple on button press (~112 lines) |
| `pwm.h` | Added `led_ripple_start` / `led_ripple_finish` declarations |
| `keys.c` | Replaced white-flash with `led_ripple_start` / `led_ripple_finish` calls |

No EEPROM layout changes. `FIRMWARE_VERSION` stays at `2`. EEPROM survives the flash.

---

## Critical settings quick-reference

| Setting | Correct value | Wrong value (will break things) |
|---------|--------------|--------------------------------|
| Preprocessor symbol | `__SAMD21G16B__` only | `__SAMD21J18A__` added — breaks `nvm.c` |
| Linker script | `src/samd21g16b_flash.ld` (ORIGIN=0x2000) | `samd21j18a_flash.ld` (ORIGIN=0x0) — overwrites bootloader |
| Build configuration | Release | Debug — doesn't fit in 56 KB |
| UF2 conversion | `uf2conv.py` + `uf2families.json` in same dir | Only `uf2conv.py` — silent failure |
| Button release timing | Release immediately when DFU drive appears | Hold through reboot — badge stuck in DFU |
