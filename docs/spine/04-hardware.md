# DC29 Badge — Hardware Reference

> **docs/spine/** is the authoritative source of truth.

← Back to [Project Overview](00-overview.md)

## Microcontroller

**ATSAMD21G16B** — ARM Cortex-M0+ @ 48 MHz

| Parameter | Value |
|-----------|-------|
| Flash | 64 KB (8 KB bootloader + 56 KB application) |
| RAM | 8 KB |
| RWW EEPROM emulation | 256 bytes (in flash) |
| USB | Full-speed USB 2.0 device (HID + CDC) |
| SERCOM | 6 instances (UART/I2C/SPI) |
| TCC / TC | Hardware PWM timers |
| EIC | External interrupt controller (buttons, VBUS) |

Bootloader starts at address `0x0000`. Application starts at `0x2000` (8 KB offset). The linker script `samd21g16b_flash.ld` enforces this.

Chip serial number is read from fixed memory locations:
- `0x0080A040`, `0x0080A044`, `0x0080A048`, `0x0080A00C`

---

## Pin Assignments

### Buttons

All buttons are active-low with pull-ups. EXTINT on falling edge.

| Button | Pin | EXTINT | Active level |
|--------|-----|--------|-------------|
| BUTTON1 (top-left) | PIN_PA04 | EIC_EXTINT4 | LOW |
| BUTTON2 (top-right) | PIN_PA05 | EIC_EXTINT5 | LOW |
| BUTTON3 (bottom-left) | PIN_PA06 | EIC_EXTINT6 | LOW |
| BUTTON4 (bottom-right) | PIN_PA07 | EIC_EXTINT7 | LOW |

BUTTON4 doubles as the DFU trigger: hold while plugging USB to enter bootloader.

### RGB LEDs

Each LED has three PWM outputs (R, G, B). All are active-high.

| LED | Red pin | Green pin | Blue pin |
|-----|---------|-----------|----------|
| LED1 (top-left) | PIN_PA22 | PIN_PA10 | PIN_PB08 |
| LED2 (top-right) | PIN_PA23 | PIN_PA11 | PIN_PB09 |
| LED3 (bottom-left) | PIN_PA20 | PIN_PA18 | PIN_PB10 |
| LED4 (bottom-right) | PIN_PA21 | PIN_PA19 | PIN_PB11 |

LED4 is adjacent to BUTTON4 and is the **Teams mute indicator**.

### Other Pins

| Function | Pin | Notes |
|----------|-----|-------|
| Buzzer | PIN_PB22 | TCC output |
| USB VBUS sense | PIN_PA01 | EIC_EXTINT1, pull-down, detect both edges |
| Badge matrix comms | PIN_PA28 | SERCOM input |
| MAX comms | PIN_PA27 | SERCOM |
| Aliens comms | PIN_PB02 | SERCOM |

### Capacitive Touch Slider

The QTouch slider uses a dedicated set of pins configured by the `touch_config_samd.h` header. It is a linear slider providing position values 0–255. Slider thresholds are ±10 counts from the last position to prevent jitter.

---

## Power

The badge is powered from USB 5V through the **SW5 power switch** (physical rocker switch on the badge). When SW5 is off, no power reaches the MCU.

USB VBUS presence is detected on PIN_PA01 via an EXTINT interrupt. On VBUS high, the USB stack starts. On VBUS low, the badge configures the top USART for badge-to-badge comms and eventually enters standby sleep.

---

## EEPROM Layout (Detailed)

EEPROM is emulated in the SAMD21's RWW (Read-While-Write) flash section. Maximum: 260 bytes per the ASF `conf_rwwee.h` configuration.

| Constant | Byte offset | Size | Default value | Description |
|----------|-------------|------|---------------|-------------|
| `EEP_FIRMWARE_VERSION` | 0 | 1 | 2 | Must match `FIRMWARE_VERSION` or full reset occurs |
| `EEP_LED_BRIGHTNESS` | 1 | 1 | 255 | Global brightness scale (currently informational) |
| `EEP_LED_1_COLOR` | 2 | 3 | 255, 0, 0 | LED1 idle RGB (red by default) |
| `EEP_LED_2_COLOR` | 5 | 3 | 0, 255, 0 | LED2 idle RGB (green by default) |
| `EEP_LED_3_COLOR` | 8 | 3 | 0, 0, 255 | LED3 idle RGB (blue by default) |
| `EEP_LED_4_COLOR` | 11 | 3 | 127, 127, 127 | LED4 idle RGB (white by default) |
| `EEP_LED_1_PRESSED_COLOR` | 14 | 3 | 0, 127, 127 | LED1 color when button 1 is pressed |
| `EEP_LED_2_PRESSED_COLOR` | 17 | 3 | 127, 0, 127 | LED2 color when button 2 is pressed |
| `EEP_LED_3_PRESSED_COLOR` | 20 | 3 | 127, 127, 0 | LED3 color when button 3 is pressed |
| `EEP_LED_4_PRESSED_COLOR` | 23 | 3 | 0, 0, 0 | LED4 color when button 4 is pressed |
| `EEP_KEY_MAP` | 26 | max 234 | see default_keymap | Packed keymap (see protocol doc) |

**Total used:** 26 + keymap length. Default keymap is 21 bytes → 47 bytes total.

The `CMD_SET_KEY` protocol command writes single-entry keymaps and calls `rww_eeprom_emulator_commit_page_buffer()` to persist.

---

## Physical Layout

```
+---------------------------+
|  [LED1]  B1   B2  [LED2]  |
|                           |
|  [===== SLIDER =====]     |
|                           |
|  [LED3]  B3   B4  [LED4]  |
+---------------------------+
              |
           USB connector
```

- Top row: LED1 (top-left), BUTTON1 (top-left area), BUTTON2 (top-right area), LED2 (top-right)
- Middle: capacitive touch slider
- Bottom row: LED3 (bottom-left), BUTTON3 (bottom-left area), BUTTON4 (bottom-right area), LED4 (bottom-right)

LED4 and BUTTON4 are co-located in the bottom-right corner. This is intentional — the Teams mute indicator and the mute toggle button are adjacent.

---

## 4-Button Chord Physical Gesture

Hold all four tactile buttons simultaneously:
- **300 ms to 2 s then release** → short chord → cycles effect mode
- **Hold ≥ 2 s** → long chord → resets effect mode to 0 (fires while held)

The chord works without USB — the effect animation runs on firmware alone.

---

## Schematics and BOM

Full hardware documentation is in the `Hardware/` directory:

- `Hardware/Defcon29Schematic.pdf` — full schematic
- `Hardware/Defcon29BOM.pdf` — bill of materials
- `Hardware/Defcon29-TopAssembly.png` — top assembly diagram
- `Hardware/Defcon29BadgeTypes.jpg` — the different badge variants
- `Hardware/Keycaps/` — 3D-printable keycap STL files (one per badge type)

The badge was produced in several variants for different DEF CON participant types. The firmware is identical across variants; only the keycap artwork differs.
