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

**Recommended workflow** (macOS): use the project slash command **`/flash-badge`** — it runs `make`, polls for the bootloader drive, copies the `.uf2`, and verifies CDC re-enumeration. Flags: `--no-build` (skip make) and `--rebuild` (force clean build). Source: `.claude/commands/flash-badge.md`.

**Manual fallback** (any OS):

1. Hold the **bottom-right button (BUTTON4)**.
2. Plug in USB — badge enters bootloader, top-left LED blinks red, badge appears as a mass storage device.
3. **Release the button immediately** once the drive mounts. Holding it across the reboot traps the badge in DFU indefinitely (looks identical to a firmware crash).
4. Drag/copy the `.uf2` onto the drive.
5. Drive disappears → badge rebooted. Confirm a CDC serial port appears (`/dev/tty.usbmodem*` on Mac, `COMx` on Windows).

Flashing does not reset EEPROM (challenge/game data survives). Only explicitly calling `reset_eeprom()` or changing `FIRMWARE_VERSION` in `main.h` resets it.

**macOS toolchain note:** `arm-none-eabi-gcc` is at `~/opt/arm-gnu-toolchain/Payload/bin/` (extracted via `pkgutil --expand-full` from the Homebrew cask). The project Makefile at `Firmware/Source/DC29/Makefile` produces a working `.uf2` with `__SAMD21G16B__` define, `samd21g16b_flash.ld` linker script, `-fcommon` (GCC 10+ default change), and `-flto` (to fit in 56 KB on GCC 15). See `BUILD_MACOS.md` for the full setup.

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

**Status indicator side-channel** (Teams integration + general LED control): byte `0x01` is the escape prefix. Common commands:
- `0x01 'M' / 'U' / 'X'` — LED 4 red/green/off (Teams mute state)
- `0x01 'L' n r g b` — set LED n (1-4) to (r,g,b)
- `0x01 'P' r1 g1 b1 r2 g2 b2 r3 g3 b3 r4 g4 b4` — atomic 4-LED paint (preferred for animation streams)
- `0x01 'E' n` — set firmware effect mode (0=off, 1=rainbow-chase, 2=breathe, 3=wipe, 4=twinkle, 5=gradient, 6=theater, 7=cylon)
- `0x01 'I' 0/1` — disable/enable interactive splash on press (RAM-only, default on)
- `0x01 'S' 0/1` — disable/enable capacitive touch slider (RAM-only, default on)
- `0x01 'F' 0/1` — disable/enable button-press takeover animation (RAM-only, default on)
- `0x01 'T' n` — fire takeover ripple for button n (1-4) on demand

`0x01` never appears in normal menu traffic, so this channel is safe to inject while the console is open. See `dc29/protocol.py` for the full command + event list.

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

## Web config UI (`web/dc29-config/`) — Playwright validation is REQUIRED

The browser config UI lives at `web/dc29-config/index.html` + `protocol.js`, deploys to GitHub Pages via `.github/workflows/pages.yml`, and talks to the badge via the WebSerial API.  Live URL: `https://dallanwagz.github.io/Defcon29-mute-button/`.

**Hard rule:** any time you change `web/dc29-config/**` you MUST run the Playwright smoke suite and report the pass/fail line BEFORE telling the user the change is done.  The user has been bitten by silently-broken UI changes — visual review at the source level is not enough.

### How to validate

```bash
.venv/bin/python tests/web/smoke_web.py
```

Expects `PASS: 43    FAIL: 0` (or higher counts as the suite grows — the only acceptable result is `FAIL: 0`).  The suite hits the live deployed URL, so:

1. Wait ~30 s after pushing for GitHub Actions to redeploy before running it.  Check the deploy status at https://github.com/dallanwagz/Defcon29-mute-button/actions if a run feels off.
2. If the suite fails, fix the JS / HTML, push, wait for redeploy, re-run — repeat until green.  Do NOT report the change as complete with failing assertions.

### What the suite covers

- **Static**: page loads, every panel's `<h2>` renders, no JS console errors during load, Connect button enabled.
- **Pure JS helpers**: `base32Decode` against the well-known "Hello!" vector, `asciiToHidPair` across lower/upper/shifted/newline cases, `keyEventToHidPair` for modifier+key combos.
- **Hash-based config banner**: navigating to `?#cfg=…` decodes JSON and surfaces the share-banner.
- **Mocked `navigator.serial` → protocol byte assertions**: the suite injects a fake serial port via `add_init_script`, captures every byte the page would write, and asserts exact-byte protocol encoding for each action button (LED color, effect mode, beep pattern, jiggler pulse/start/cancel, haptic toggle, slider toggle, WLED knobs, vault clear + chained refresh, modifier-table clear).
- **RX-driven UI**: emit synthetic `0x01 'b' 'V' …` and `0x01 'B' …` bytes through the mock port → vault / activity-log panels populate.

### What the suite does NOT cover

- Real WebSerial against an attached badge (Chrome's port-picker is OS-level UI and Playwright can't reliably click through it).
- macOS HID injection from `vault fire` / `totp fire` (those keystrokes go to Playwright's headless Chromium, not a visible window).

For those, the user has to test in real Chrome with the badge attached.  When you ship a UI change that touches a fire-into-focused-window flow (vault, totp, hid burst, type-any-string), explicitly call out in your "what to test" message that the user needs to do the in-Chrome step.

### Adding new assertions when you add a new panel / button

When you add a new UI surface, extend `tests/web/smoke_web.py`:

1. If the panel has a heading: add the heading text to `expected_panels` in `test_static_render`.
2. If the panel has buttons that send protocol bytes: add a section to `test_mocked_serial_protocol` that clicks the button and asserts the exact byte sequence (pattern: `reset_tx() → page.click(...) → page.wait_for_function("window.__mockTx.length > 0", ...) → check(...)`).
3. If the panel reads RX events from the badge: extend `test_rx_driven_panels` with a `page.evaluate("() => window.__mockEmitRx([...])")` and assert the resulting DOM update.

Re-run the suite after every change.  Goal is full byte-level coverage of every UI → protocol path, since real-badge testing happens manually one-shot.

## Audio-reactive bridge setup

The `audio-reactive` bridge captures system audio via [BlackHole](https://github.com/ExistentialAudio/BlackHole) (free MIT-licensed virtual loopback driver), runs FFT + beat detection in Python, and drives the badge LEDs at 60 fps. One-time setup on macOS:

1. **Install BlackHole + Python audio extras**
   ```bash
   brew install blackhole-2ch
   pip install -e '.[audio]'    # adds sounddevice + numpy
   ```

2. **Create a Multi-Output Device in Audio MIDI Setup** (`/System/Applications/Utilities/Audio MIDI Setup.app`)
   - Click the `+` in the lower-left → "Create Multi-Output Device"
   - Check **both** your speaker/AirPods *and* "BlackHole 2ch"
   - Right-click the new device → "Use This Device for Sound Output"

3. **Verify**
   ```bash
   dc29 audio status     # should show ⭐ next to BlackHole 2ch
   dc29 audio test       # play music, watch live RMS / band / beat bars
   ```

4. **Enable the bridge**
   ```bash
   dc29 start --enable audio-reactive
   # or via TUI: tab 5 → check "audio-reactive"
   ```

**Optional Spotify palette context:** if `[spotify] client_id` is configured and `dc29 spotify auth` was run, the bridge polls currently-playing every 10s and shifts the LED palette per artist (stable hash → consistent hue family). Live audio drives reactivity; Spotify drives mood.

**Why this replaced the original Spotify-analysis bridge:** Spotify deprecated `/audio-analysis` and `/audio-features` for new dev apps on 2024-11-27. Live FFT achieves the same goal with no third-party deprecation risk and works with any audio source (Spotify, YouTube, Apple Music, anything that produces audio output).

See `tools/TEAMS_MUTE_SETUP.md` for full Teams setup walkthrough.
