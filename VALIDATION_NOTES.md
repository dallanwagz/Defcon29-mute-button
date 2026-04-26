# Validation Notes — Issue #5 Modifier Key Fix

End-to-end verification of the modifier key parser fix on real DEF CON 29 badge
hardware (SAMD21G16B). This document captures what was tested, the build
configuration that produced working firmware, and gotchas encountered during
the test cycle.

## What Was Verified

Built the fix on Windows with Microchip Studio 7.0, flashed via UF2, and
exercised the keymap parser through the badge's serial console:

| Macro Set Via Serial | Parser Result | What It Sends | Hardware Behavior |
|---|---|---|---|
| `[ctrl]p` (single modifier) | Accepted, returned to main menu | Ctrl+P | (set successfully; per-button physical test pending) |
| `[ctrl][shift]p` (multi-modifier — the bug case) | Accepted, returned to main menu | Ctrl+Shift+P | (set successfully) |
| `[gui][shift]s` (multi-modifier with system-visible effect) | Accepted | Win+Shift+S | Snipping Tool overlay appears on host |

The acceptance of multi-modifier macros without falling through to "Invalid
Input" is the parser-level confirmation. Pre-fix, multi-modifier strings
silently produced wrong modifier bytes (e.g., `[ctrl]p` → LEFT_CTRL +
LEFT_SHIFT + RIGHT_CTRL).

## Build Configuration That Produced Working Firmware

The previous `Firmware/Compiled/DC29.uf2` committed in this branch was built
with the wrong linker script (ORIGIN=0x0) and was rejected by the badge's UF2
bootloader, which expects the application at 0x2000. The replacement `.uf2`
in this commit was built with:

- **Device defines**: `__SAMD21G16B__` only (do **not** add `__SAMD21J18A__` —
  with both defined, `samd21.h`'s `#elif` chain selects `samd21j18a.h`, which
  doesn't define `NVMCTRL_RWW_EEPROM_SIZE` and breaks `nvm.c`).
- **Linker script**: `src/samd21g16b_flash.ld` (this is the in-tree custom
  script with `ORIGIN = 0x00000000+0x2000`, not the ASF default at
  `src/ASF/sam0/utils/linker_scripts/samd21/gcc/samd21j18a_flash.ld` which
  has ORIGIN=0x0).
- **Configuration**: Release (Debug doesn't fit in 56KB).
- **Toolchain**: arm-none-eabi-gcc 6.3.1 from Microchip Studio.

The Microchip Studio `.cproj` was edited so that **both** the Release
preprocessor symbols and Release linker flags reflect the above. Note that the
cproj contains two `<armgcc.linker.miscellaneous.LinkerFlags>` entries inside
the Release `<PropertyGroup>`; both must point at `samd21g16b_flash.ld`. UF2
conversion was done from `DC29.hex` using a custom PowerShell port of
`uf2conv.py` (Python isn't required on the build machine).

## Validation Gotcha — Button-During-Reboot Trap

When flashing, holding the bottom-right button across the bootloader's reboot
keeps the badge in DFU mode after the new firmware is written. From the host
this looks identical to a firmware crash: drive stays mounted, top-left LED
keeps pulsing, no COM port enumerates. We spent significant time chasing
imaginary firmware crashes (comparing vector tables, checking memory layout,
inspecting startup code) before unplug-and-replug **without holding any
button** booted the firmware cleanly.

**Recommended flash workflow:**
1. Hold bottom-right button.
2. Plug in USB.
3. **Release the button as soon as the bootloader drive (D:, E:, etc.) appears.**
4. Drag/copy the `.uf2` onto the drive.
5. When the drive disappears, badge has rebooted into the new firmware. Verify
   a CDC serial port appears (e.g., `COM3` on Windows, `/dev/ttyACM*` on
   Linux/Mac).

If the firmware appears not to boot after a flash, **before** debugging the
build, unplug and replug without touching any button. The firmware is almost
certainly fine.
