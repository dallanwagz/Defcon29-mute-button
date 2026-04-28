# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is the DEF CON 29 badge firmware, modified to serve as a USB macro keypad with a Microsoft Teams mute-state indicator on LED 4. The `playground` branch is the active development branch for the Teams integration.

**Hardware:** ATSAMD21G16B (ARM Cortex-M0+, 64KB flash / 8KB RAM, first 8KB reserved for bootloader → 56KB for application). 4 tactile buttons, 4 RGB LEDs, a capacitive touch slider, buzzer, and multi-badge UART communication pins.

## Building the Firmware

The firmware is written in C using the **Microchip Studio 7.0 IDE** (Windows only) with the **ASF (Advanced Software Framework)**. There is no Makefile-based build; everything goes through the `.cproj` in `Firmware/Source/Defcon29.atsln`.

**Critical build settings** (wrong settings produce firmware the bootloader rejects):
- **Preprocessor symbol:** `__SAMD21G16B__` only — do NOT also add `__SAMD21J18A__`, as `samd21.h`'s `#elif` chain will select the wrong header and break `nvm.c` (missing `NVMCTRL_RWW_EEPROM_SIZE`).
- **Linker script:** `src/samd21g16b_flash.ld` (ORIGIN = 0x2000). Do **not** use `src/ASF/sam0/utils/linker_scripts/samd21/gcc/samd21j18a_flash.ld` (ORIGIN = 0x0).
- **Configuration:** Release only — Debug build does not fit in 56KB.
- **Toolchain:** arm-none-eabi-gcc 6.3.1 (bundled with Microchip Studio).

The `.cproj` has two `<armgcc.linker.miscellaneous.LinkerFlags>` entries inside the Release `<PropertyGroup>`; both must point at `samd21g16b_flash.ld`.

Convert the output `.hex` to `.uf2` for flashing:
```
uf2conv.py DC29.hex --convert --output DC29.uf2
```
(`uf2conv.py` is available from https://github.com/microsoft/uf2 in the utils directory.)

## Flashing Firmware

1. Hold the **bottom-right button (BUTTON4)**.
2. Plug in USB — badge enters bootloader, top-left LED blinks red, badge appears as a mass storage device.
3. **Release the button immediately** once the drive mounts. Holding it across the reboot traps the badge in DFU indefinitely (looks identical to a firmware crash).
4. Drag/copy the `.uf2` onto the drive.
5. Drive disappears → badge rebooted. Confirm a CDC serial port appears (`/dev/tty.usbmodem*` on Mac, `COMx` on Windows).

Flashing does not reset EEPROM (challenge/game data survives). Only explicitly calling `reset_eeprom()` or changing `FIRMWARE_VERSION` in `main.h` resets it.

## Firmware Architecture

### Main loop (`src/main.c`)
Initializes all peripherals, then runs a superloop that:
- Checks button flags set by EXTINT ISRs and calls `send_keys(1–4)`.
- Reads the capacitive touch slider and calls `send_keys(5–6)`.
- Forwards incoming USB CDC bytes to `updateSerialConsole()`.
- Enters standby sleep if unpowered from USB and idle for >1 s.
- Calls `check_comms()` (badge-to-badge UART) and `run_games()`.

The `millis` variable is incremented every 1 ms by the RTC overflow callback (TIME_PERIOD_1MSEC = 33 RTC counts). Debounce is 200 ms per button.

### Key sending (`src/keys.c`)
`send_keys(n)` replays the keymap stored in EEPROM for button n (1–4) or slider direction (5–6). The keymap is a packed byte array: each entry is `[modifier, keycode]`. Modifier byte `0xF0` signals a media key. The keymap is loaded from EEPROM into `keymap[]` at startup; `keymapstarts[]` indexes the start of each button's entries.

### Serial console (`src/serialconsole.c`)
Drives a text menu over USB CDC for configuring LED colors, keymaps, and viewing badge stats. Menu state machine lives in `serialConsoleState`.

**Status indicator side-channel** (Teams integration): byte `0x01` is the escape prefix. The next byte drives LED 4:
- `0x01 'M'` → red (muted)
- `0x01 'U'` → green (unmuted)
- `0x01 'X'` → off (not in meeting)

`0x01` never appears in normal menu traffic, so this is safe to inject while the console is open.

### LED / PWM (`src/pwm.c`)
`led_set_color(n, rgb[3])` drives the RGB LEDs via PWM. `led_on()` / `led_off()` toggle individual color pins. Button press flashes the LED white briefly; color is restored from `ledvalues[]` after.

### Badge-to-badge comms (`src/comms.c`)
Six SERCOM USART instances (top, right, bottom, left, usba, usbc) implement a badge mesh for multi-player games and the DEF CON challenge.

### Games (`src/games.c`)
Simon Says (solo and multiplayer) and Whack-a-Mole (solo and multiplayer). Entered via `gamemode` enum; when not `IDLE`, the game loop handles buttons directly instead of the main loop.

### EEPROM layout (`src/main.h`)
EEPROM is emulated in RWW flash (260-byte max). Layout defined by `EEP_*` constants. `FIRMWARE_VERSION` triggers a full EEPROM reset on mismatch — only bump it when the layout changes.

## Teams Mute Indicator Tool (`tools/`)

Python script that bridges the Microsoft Teams Local API (WebSocket on `localhost:8124`) to the badge's serial port.

**Run:**
```bash
python3 tools/teams_mute_indicator.py --port /dev/tty.usbmodem14201
```

**Dependencies:**
```bash
pip install websockets pyserial
```

First run triggers a Teams pairing dialog. The token is saved to `~/.dc29_teams_token`. See `tools/TEAMS_MUTE_SETUP.md` for full setup, autostart via `launchd`, and troubleshooting.

**Mac shortcut note:** Teams on macOS uses `Cmd+Shift+M` to toggle mute. Set the badge macro using `[gui][shift]m`, not `[ctrl][shift]m` (which is the Windows shortcut).
