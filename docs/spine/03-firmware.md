# DC29 Badge — Firmware Reference

> **docs/spine/** is the authoritative source of truth.

← Back to [Project Overview](00-overview.md)

## Overview

The firmware is written in C using **Microchip Studio 7.0** with the **Atmel Software Framework (ASF)**. It targets the ATSAMD21G16B (ARM Cortex-M0+).

Source tree: `Firmware/Source/DC29/src/`

| File | Responsibility |
|------|---------------|
| `main.c` | Entry point, superloop, EEPROM init, chord detection, effects |
| `main.h` | Pin definitions, EEPROM layout constants, extern declarations |
| `keys.c` | Keymap loading from EEPROM, HID report sending |
| `keys.h` | Declarations for keys.c |
| `serialconsole.c` | Escape-byte protocol parser, command dispatch |
| `serialconsole.h` | Declarations for serialconsole.c |
| `pwm.c` | LED PWM driver (`led_set_color`, `led_on`, `led_off`) |
| `pwm.h` | LED pin enum, function declarations |
| `comms.c` | Badge-to-badge UART mesh (6 SERCOM instances) |
| `comms.h` | Declarations for comms.c |
| `config/` | ASF configuration headers (USB, clocks, touch, etc.) |
| `qtouch/` | Capacitive touch library for the slider |

---

## Main Loop (Superloop)

`main()` initializes all peripherals, then runs an infinite superloop:

```c
while (1) {
    // 1. Chord detection (all 4 buttons)
    // 2. LED effect animation update
    // 3. HID key sending (if USB connected)
    // 4. Capacitive slider reading
    // 5. Serial console (escape-byte protocol)
    // 6. Sleep check (if no USB and idle > 1 s)
}
```

### Timing

The `millis` variable is incremented every 1 ms by the RTC overflow callback:

```c
#define TIME_PERIOD_1MSEC 33u   // 33 RTC counts ≈ 1 ms at 32.768 kHz
void rtc_overflow_callback(void) {
    millis++;
    // ... touch timing
}
```

Debounce is 200 ms per button. Chord detection uses 300 ms (short) and 2000 ms (long) thresholds.

---

## Button Handling

Buttons 1–4 use EXTINT (external interrupt) callbacks on falling edges:

| Button | Pin | EXTINT channel |
|--------|-----|---------------|
| BUTTON1 | PA04 | 4 |
| BUTTON2 | PA05 | 5 |
| BUTTON3 | PA06 | 6 |
| BUTTON4 | PA07 | 7 |

The ISR handlers (`button1_handler` … `button4_handler`) set a volatile boolean flag and record `lastButtonNPress = millis`. They check the debounce window before setting the flag.

The main loop checks these flags and calls `send_keys(n)`, then clears the flag. This keeps HID sending out of ISR context.

---

## Chord Detection

All 4-button chord logic is in the main loop (not ISRs):

```c
bool all4 = !port_pin_get_input_level(BUTTON1) && ...;

if (all4) {
    button1 = button2 = button3 = button4 = false;  // suppress HID
    if (chord_state == CHORD_IDLE) {
        chord_state = CHORD_PENDING;
        chord_start = millis;
    } else if (chord_state == CHORD_PENDING) {
        if ((millis - chord_start) >= CHORD_LONG_MS) {
            chord_state = CHORD_LONG_FIRED;
            set_effect_mode(0);
            // emit 0x01 C 2
        }
    }
} else {
    if (chord_state == CHORD_PENDING) {
        uint32_t held = millis - chord_start;
        if (held >= CHORD_SHORT_MS) {
            set_effect_mode((effect_mode + 1) % NUM_EFFECT_MODES);
            // emit 0x01 C 1
        }
    }
    chord_state = CHORD_IDLE;
}
```

Relevant constants:
- `CHORD_SHORT_MS = 300`
- `CHORD_LONG_MS = 2000`
- `NUM_EFFECT_MODES = 3`

---

## Effect Modes

`set_effect_mode(mode)` resets animation state and emits `0x01 V mode`:

```c
void set_effect_mode(uint8_t mode) {
    effect_mode = mode;
    effect_step = 0; effect_hue = 0; effect_timer = millis;
    if (mode == 0) {
        // Restore LEDs 1-3 to EEPROM colors
        led_set_color(1, led1color);
        led_set_color(2, led2color);
        led_set_color(3, led3color);
    }
    // emit 0x01 V mode
}
```

`update_effects()` advances the animation by one frame each main-loop iteration:

| Mode | Step interval | Algorithm |
|------|--------------|-----------|
| 0 (off) | N/A | Returns immediately |
| 1 (rainbow-chase) | 150 ms | One LED lit at a time; `hsv_to_rgb(hue + step * 64, 200)`, step cycles 0–3 across all four LEDs, hue += 16 per full cycle |
| 2 (breathe) | 8 ms | All four LEDs together; brightness = triangle wave 0→255→0, `effect_step` wraps at 256, hue += 8 per full breath |

`update_effects()` animates all four LEDs.  Bridges that need exclusive control of an LED — Teams's `LED4` mute indicator, FocusBridge's per-app pages — must suspend the effect via `set_effect_mode(0)` while they hold ownership and restore the prior mode on release.  `TeamsBridge._set_meeting_state()` and `FocusBridge.run()` both implement this save/restore pattern.

The internal `hsv_to_rgb()` is a fixed-point integer implementation (h and v both 0–255).

---

## Serial Console and Protocol Handler

`updateSerialConsole()` is called from the main loop whenever `udi_cdc_get_nb_received_data() > 0`. It reads one byte per call.

The escape-byte state machine:

```c
if (escape_state == 1) {
    // Got the command byte — dispatch immediately or set arg collection
    escape_cmd = data;
    if (data == 'M') { led_set_color(4, LED_COLOR_RED); return; }
    if (data == 'U') { led_set_color(4, LED_COLOR_GREEN); return; }
    if (data == 'X') { led_set_color(4, LED_COLOR_OFF); return; }
    if (data == 'K') { escape_args_needed = 3; escape_state = 2; return; }
    // ... etc.
}
if (escape_state == 2) {
    // Collect arg bytes
    escape_args[escape_args_count++] = data;
    if (escape_args_count < escape_args_needed) return;
    // Dispatch complete command
}
if (data == 0x01) { escape_state = 1; return; }
// else: normal serial console handling
```

The protocol is fully defined in `serialconsole.c`. See [01-protocol.md](01-protocol.md) for the complete command reference.

---

## Key Sending (`keys.c`)

`send_keys(n)` replays the keymap stored in EEPROM for button `n`:

1. If CDC is enabled, emit `0x01 B n mod key` event
2. Flash LED `n` white (if `button_flash_enabled`)
3. Walk the keymap array from `keymapstarts[n-1]+1` to `keymapstarts[n]`, step 2:
   - If `keymap[x] == 0xF0`: send media report (`udi_hid_media_down` / `udi_hid_media_up`)
   - Else if `keymap[x+1] != 0`: send keyboard report (`udi_hid_kbd_modifier_down` / `udi_hid_kbd_down` / `udi_hid_kbd_up` / `udi_hid_kbd_modifier_up`)
4. Restore LED `n` to saved color

Each HID report has a 10 ms inter-report delay to allow the host to process it.

Slider (keys 5–6) iterates from `keymapstarts[4]` or `keymapstarts[5]` to `keymaplength`.

---

## LED Driver (`pwm.c`)

LEDs are driven via TCC (Timer/Counter for Control) PWM.

`led_set_color(n, rgb[3])` sets all three channels (R, G, B) for LED `n`.

`led_on(pin)` / `led_off(pin)` toggle individual color channels directly.

`ledvalues[]` is a 12-element array (4 LEDs × 3 channels) that tracks current PWM values for restoration after button-press flash.

---

## EEPROM Layout

EEPROM is emulated in RWW (Read-While-Write) flash. Maximum usable size: 260 bytes.

| Constant | Offset | Size | Description |
|----------|--------|------|-------------|
| `EEP_FIRMWARE_VERSION` | 0 | 1 | Firmware version byte; mismatch triggers full reset |
| `EEP_LED_BRIGHTNESS` | 1 | 1 | Global brightness (currently unused by pwm.c) |
| `EEP_LED_1_COLOR` | 2 | 3 | LED 1 idle color (R, G, B) |
| `EEP_LED_2_COLOR` | 5 | 3 | LED 2 idle color |
| `EEP_LED_3_COLOR` | 8 | 3 | LED 3 idle color |
| `EEP_LED_4_COLOR` | 11 | 3 | LED 4 idle color |
| `EEP_LED_1_PRESSED_COLOR` | 14 | 3 | LED 1 color while button is pressed |
| `EEP_LED_2_PRESSED_COLOR` | 17 | 3 | LED 2 color while button is pressed |
| `EEP_LED_3_PRESSED_COLOR` | 20 | 3 | LED 3 color while button is pressed |
| `EEP_LED_4_PRESSED_COLOR` | 23 | 3 | LED 4 color while button is pressed |
| `EEP_KEY_MAP` | 26 | max 234 | Packed keymap byte array |

**EEPROM reset rules:**
- `FIRMWARE_VERSION` mismatch on boot → full erase + re-initialize (all data lost)
- Flashing does **not** reset EEPROM
- Only `reset_eeprom()` or a version bump resets it
- `reset_user_eeprom()` resets only LED colors and keymaps, not the version byte

Current `FIRMWARE_VERSION = 2`.

---

## Build Instructions

### Prerequisites

- **Microchip Studio 7.0** (Windows only) — available from microchip.com
- **arm-none-eabi-gcc 6.3.1** — bundled with Microchip Studio
- **uf2conv.py** — from https://github.com/microsoft/uf2 (`utils/` directory)

### Critical Build Settings

These settings are easy to get wrong and produce firmware the bootloader will reject:

#### 1. Preprocessor symbol

Define **only** `__SAMD21G16B__`. Do **not** also define `__SAMD21J18A__`.

`samd21.h` uses an `#elif` chain. If both symbols are defined, the wrong header is selected and `nvm.c` will fail to compile (missing `NVMCTRL_RWW_EEPROM_SIZE`).

In Microchip Studio: `Project → Properties → Toolchain → ARM/GNU C Compiler → Symbols`

#### 2. Linker script

Use **`src/samd21g16b_flash.ld`** (application starts at `ORIGIN = 0x2000`).

Do **not** use `src/ASF/sam0/utils/linker_scripts/samd21/gcc/samd21j18a_flash.ld` (starts at `ORIGIN = 0x0` — overwrites the bootloader).

The `.cproj` file has two `<armgcc.linker.miscellaneous.LinkerFlags>` entries inside the Release `<PropertyGroup>` — both must point at `samd21g16b_flash.ld`.

#### 3. Configuration

Build the **Release** configuration only. The Debug build does not fit in the 56 KB application space.

### Build Steps

1. Open `Firmware/Source/Defcon29.atsln` in Microchip Studio 7.0
2. Confirm the active project is `DC29`
3. Select the **Release** configuration in the toolbar
4. Build → Build Solution (or F7)
5. Output: `Firmware/Source/DC29/Release/DC29.hex`

### Convert to UF2

```bash
python3 uf2conv.py Firmware/Source/DC29/Release/DC29.hex --convert --output DC29.uf2
```

The resulting `DC29.uf2` is the file you drag to the badge bootloader drive.

---

## Flashing Firmware

1. Hold **BUTTON4** (bottom-right button)
2. Plug the badge into USB while holding the button
3. **Release BUTTON4 immediately** once the drive mounts — the badge appears as a mass storage device and the top-left LED blinks red
4. Copy (drag) `DC29.uf2` onto the mounted drive
5. The drive unmounts and the badge reboots automatically
6. Confirm a CDC serial port appears (`/dev/tty.usbmodem*` on Mac, `COMx` on Windows)

> **Pitfall:** If you hold BUTTON4 through the reboot (i.e., keep it held while the drive mounts and the badge reboots), the badge gets stuck in DFU mode indefinitely — it looks identical to a firmware crash. This is fixed by unplugging, releasing the button, and starting over from step 1.

Flashing does **not** reset EEPROM. Challenge data, keymaps, and LED colors survive. Only a version bump in `FIRMWARE_VERSION` or an explicit `reset_eeprom()` call resets EEPROM data.

---

## Adding a New Effect Mode

1. Increment `NUM_EFFECT_MODES` in `main.h` and `main.c`
2. Add a new `else if (effect_mode == N)` branch in `update_effects()` in `main.c`
3. Add the effect name to the protocol constants in `dc29/protocol.py` (`EffectMode` enum and `EFFECT_NAMES` dict)
4. LED 4 must never be written by `update_effects()` — reserve it for the mute indicator
5. Rebuild and reflash

See [docs/hacker/adding-effects.md](../hacker/adding-effects.md) for a step-by-step walkthrough.

---

## Badge-to-Badge Communication

`comms.c` implements six SERCOM USART instances for the badge mesh network used by the DEF CON games:

| Instance | Direction |
|----------|-----------|
| `usart_top_instance` | Top connector |
| `usart_right_instance` | Right connector |
| `usart_bottom_instance` | Bottom connector |
| `usart_left_instance` | Left connector |
| `usart_usba_instance` | USBA pin |
| `usart_usbc_instance` | USBC pin |

This subsystem is used for multi-player Simon Says and Whack-a-Mole. It is not related to the Teams mute indicator functionality.

---

## Sleep Behavior

When unpowered from USB and idle for >1 second, the badge enters standby sleep:

```c
if (!USBPower && ((millis - uart_event) > 1000)) {
    standby_sleep();
}
```

`standby_sleep()`:
1. Turns off all LEDs
2. Waits for all USART TX operations to complete
3. Stops the buzzer TCC
4. Slows the RTC to 500 ms period
5. Enters `SLEEPMGR_STANDBY` (ARM Cortex-M0+ standby mode)
6. Wakes on any badge-to-badge UART activity
7. Restores the 1 ms RTC period and advances `millis` by 500
