# DC29 Badge — Firmware Hacker Guide

![Language](https://img.shields.io/badge/language-C-blue)
![MCU](https://img.shields.io/badge/MCU-ATSAMD21G16B-orange)
![Toolchain](https://img.shields.io/badge/toolchain-arm--none--eabi--gcc%206.3.1-lightgrey)

> **Note:** This directory is regenerated from `docs/spine/` by the `/regen-docs` Claude Code skill. Do not hand-edit files here — edit `docs/spine/` instead.

Welcome, badge hacker. This guide is for people who want to understand and modify the firmware running on the DC29 badge.

---

## What You Can Hack

The badge firmware is C code on an ARM Cortex-M0+ (ATSAMD21G16B). Here's what you can do:

| Hack | Difficulty | Where to start |
|------|-----------|----------------|
| Add a new LED effect mode | Easy | [adding-effects.md](adding-effects.md) |
| Change button debounce timing | Trivial | `main.c` — `DEBOUNCE_TIME` constant |
| Change chord hold thresholds | Trivial | `main.c` — `CHORD_SHORT_MS`, `CHORD_LONG_MS` |
| Modify the default keymap | Easy | `main.h` — `default_keymap` array |
| Add a new protocol command | Medium | `serialconsole.c` |
| Add badge-to-badge comms features | Hard | `comms.c` |

---

## Firmware Overview

The firmware runs a **superloop** (bare-metal, no RTOS):

```c
while (1) {
    check_chord_gesture();
    update_effects();
    if (usb_connected) {
        send_pending_keystrokes();
        read_touch_slider();
    }
    process_serial_console();
    if (no_usb && idle > 1s) sleep();
}
```

Buttons are handled by hardware EXTINT interrupts that set flags; the main loop drains those flags.

The USB CDC side-channel protocol uses byte `0x01` as an escape prefix — see [protocol.md](protocol.md).

---

## Pages in This Guide

| Page | What's in it |
|------|-------------|
| [protocol.md](protocol.md) | Complete byte-level protocol reference |
| [firmware-build.md](firmware-build.md) | Full build instructions (Microchip Studio, toolchain) |
| [flashing.md](flashing.md) | DFU mode, flashing, recovery |
| [adding-effects.md](adding-effects.md) | Step-by-step: add a new LED animation in C |
| [hardware-ref.md](hardware-ref.md) | Pin assignments, EEPROM layout |

---

## Quick Reference: Source Files

```
Firmware/Source/DC29/src/
├── main.c           Superloop, chord detection, effect animation, EEPROM init
├── main.h           Pin defines, EEPROM offsets, constants
├── keys.c           Keymap parsing and HID report sending
├── serialconsole.c  Escape-byte protocol parser (the full protocol lives here)
├── pwm.c            LED PWM driver
└── comms.c          Badge-to-badge UART mesh
```

---

## Before You Start

- Build environment: **Microchip Studio 7.0 on Windows** (no Linux/Mac build)
- Flash space is tight — Debug builds don't fit. **Release only.**
- Wrong linker script = firmware that doesn't boot. See [firmware-build.md](firmware-build.md).
- EEPROM persists across flashes. Only a `FIRMWARE_VERSION` bump in `main.h` clears it.

Good luck, and have fun.
