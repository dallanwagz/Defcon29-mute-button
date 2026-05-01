# Building DC29 firmware on macOS

This is the procedure that actually produces a flashable `.uf2` on macOS using
`arm-none-eabi-gcc`. Validated against GCC 15.2.1 on Apple Silicon.

## 1. One-time setup

### Toolchain

The Homebrew cask `gcc-arm-embedded` ships a `.pkg` that needs `sudo`.
Easier: extract it without root.

```bash
brew install --cask gcc-arm-embedded   # downloads the pkg, install step will fail without sudo — that's fine
PKG=$(ls ~/Library/Caches/Homebrew/downloads/*arm-gnu-toolchain*.pkg | head -1)
mkdir -p ~/opt
pkgutil --expand-full "$PKG" ~/opt/arm-gnu-toolchain
~/opt/arm-gnu-toolchain/Payload/bin/arm-none-eabi-gcc --version   # sanity
```

Add to your shell profile so the cross-compiler is on `PATH`:

```bash
export PATH="$HOME/opt/arm-gnu-toolchain/Payload/bin:$PATH"
```

If you'd rather use the official Arm tarball, download
`arm-gnu-toolchain-*-darwin-arm64-arm-none-eabi.tar.xz` from
developer.arm.com, extract, and put its `bin/` on `PATH`. Same result.

### Python

Stock macOS `python3` is sufficient — `uf2conv.py` has no extra deps.

## 2. Build

```bash
cd Firmware/Source/DC29
make           # produces build/DC29.{elf,hex,bin,uf2,map} and prints flash usage
make clean     # remove build/
make size      # re-print size summary
```

Expected output ends with something like:

```
Wrote 108032 bytes to build/DC29.uf2
Flash used (.text+.data+.rodata): 53176 bytes (limit 57344 = 56 KB)
```

If `arm-none-eabi-gcc: command not found`, your `PATH` isn't set — see §1.

## 3. Inner-loop iteration

Three Make targets wrap the dev loop:

```bash
make flash      # build (if needed) → wait for bootloader → copy .uf2
make console    # open the CDC serial console (auto-detects badge by VID:PID)
make dev        # build → flash → console, all in one
```

Typical edit-test cycle:

1. Edit code.
2. Run `make dev` (or `make flash` if you don't want the console).
3. **Unplug the badge, hold the bottom-right button, plug it back in.**
   The script polls `/Volumes/` and copies the `.uf2` as soon as the
   bootloader mounts, then (for `dev`) waits for the badge to re-enumerate
   as a CDC port and attaches.

The console uses `tio` if installed (`brew install tio`) — exit with `Ctrl-T Q`.
Otherwise it falls back to `screen` — exit with `Ctrl-A K Y`.

### Manual flashing (no scripts)

If you'd rather do it by hand:

1. Unplug the badge.
2. Hold the **bottom-right button** while plugging into USB.
3. Wait for it to mount (Finder shows a `DC29BOOT`-style volume under `/Volumes/`).
4. `cp build/DC29.uf2 /Volumes/DC29BOOT/`

The volume unmounts itself when the copy finishes — macOS may show a
"disk was not ejected properly" warning, which is harmless. The badge
reboots into the new firmware.

## 4. Why this differs from the Windows build

The cproj's Release config has settings that don't match the actual hardware
or modern GCC. The `Makefile` in this directory bakes in the four corrections
needed; you don't have to do anything beyond running `make`. For reference:

| Item | Windows cproj Release | macOS Makefile |
|---|---|---|
| Chip define | `__SAMD21J18A__` | `__SAMD21G16B__` (matches actual silicon; required for RWW EEPROM headers) |
| Linker script | `samd21j18a_flash.ld` | `src/samd21g16b_flash.ld` (correct memory map: 56 KB flash starting at `0x2000`, 8 KB RAM) |
| `-fcommon` | implicit (older GCC default) | explicit (GCC 10+ defaults to `-fno-common`, breaks the codebase's tentative-definition globals) |
| `-flto` | off | on (GCC 15 `-Os` is ~440 B too big without it; LTO saves ~4.5 KB) |
| `_read`/`_write` stubs | not needed (older newlib-nano didn't pull them) | provided in `src/syscalls_extra.c` |

The Microchip Studio project files (`DC29.cproj`, `Defcon29.atsln`) are
untouched — Windows users continue to use the IDE.

## 5. What's not covered

- **On-chip debugging.** No SWD/J-Link path from macOS in this Makefile. If
  you need it, add `openocd` or `pyocd` plus a `gdbserver` invocation.
  Print-via-CDC (`comms.c`) remains the practical debug channel.
- **Building the bootloader.** Not in this repo. The prebuilt
  `Firmware/Compiled/dc29boot.hex` is flashed once via SWD by the badge maker.
