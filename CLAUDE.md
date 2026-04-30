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

On button press, if `button_flash_enabled`, `send_keys` calls `takeover_start(key-1)` to fire the LED animation. The Python bridges call `badge.set_button_flash(False)` when they take ownership of LEDs so the firmware animation doesn't corrupt bridge-managed colors.

### Serial console (`src/serialconsole.c`)
Drives a text menu over USB CDC for configuring LED colors, keymaps, and viewing badge stats. Menu state machine lives in `serialConsoleState`.

**Status indicator side-channel** (Teams integration): byte `0x01` is the escape prefix. The next byte drives LED 4:
- `0x01 'M'` → red (muted)
- `0x01 'U'` → green (unmuted)
- `0x01 'X'` → off (not in meeting)

`0x01` never appears in normal menu traffic, so this is safe to inject while the console is open.

### LED / PWM (`src/pwm.c`)
`led_set_resting_color(n, rgb[3])` sets a persistent "resting" color for an LED — it writes a shadow value and only drives hardware immediately when no takeover animation is running. Use this instead of `led_set_color` for any state you want to survive the animation.

`takeover_start(src_0)` (0-based button index) begins the non-blocking button-press animation: the pressed LED fires a bright flash, adjacent LEDs get an additive color blend, then everything cross-fades back to resting values over ~200ms. `takeover_tick()` advances the animation each main-loop iteration and returns `true` while active.

The serial console M/U/X/L commands all call `led_set_resting_color` so mute-state LEDs survive button presses.

### Badge-to-badge comms (`src/comms.c`)
Six SERCOM USART instances (top, right, bottom, left, usba, usbc) implement a badge mesh for multi-player games and the DEF CON challenge.

### Games (`src/games.c`)
Simon Says (solo and multiplayer) and Whack-a-Mole (solo and multiplayer). Entered via `gamemode` enum; when not `IDLE`, the game loop handles buttons directly instead of the main loop.

### EEPROM layout (`src/main.h`)
EEPROM is emulated in RWW flash (260-byte max). Layout defined by `EEP_*` constants. `FIRMWARE_VERSION` triggers a full EEPROM reset on mismatch — only bump it when the layout changes.

## dc29-badge Python Package (`dc29/`)

Installable package (`pip install -e .`) that bridges Teams, Slack, Outlook, and 15+ other apps to the badge.

**Install:**
```bash
pip install -e ".[hotkey]"
```

**Key commands:**
```bash
dc29 flow -v              # Run all bridges (Teams + Slack + Outlook + 15 app pages)
dc29 start                # Run all bridges + TUI in one process
dc29 clear-keys           # Zero all EEPROM keymaps (fix double-injection issues)
dc29 diagnose             # Show EEPROM keymaps, active app, --watch button events
dc29 tui                  # Launch TUI only (no bridges)
dc29 autostart install    # Install launchd agent for login autostart
```

**Teams pairing (first run):**
1. Kill Elgato Stream Deck if running — it holds port 8124 (`killall "Stream Deck"`)
2. Delete any stale token: `rm ~/.dc29_teams_token`
3. In Teams → Settings → Privacy → Third-party app API: remove DC29 from Allowed/Blocked lists
4. **Join a Teams meeting** (pairing only works when `canPair=true`, which requires an active call)
5. Run `dc29 flow -v` — Teams shows a "New connection request" dialog → click Allow
6. Token saved to `~/.dc29_teams_token`; subsequent runs connect automatically

**EEPROM double-injection:** If a button fires both a pynput shortcut AND a firmware HID keymap simultaneously, run `dc29 clear-keys` to zero all EEPROM entries. Use `dc29 diagnose` to check keymap state.

**FocusBridge scaling:** All focus-detecting bridges share a single osascript call via a TTL cache (`_get_active_app()` in `bridges/focus.py`). Without this, 15+ concurrent calls flood macOS System Events and all time out. Do not revert this cache.

See `tools/TEAMS_MUTE_SETUP.md` for full Teams setup walkthrough.
