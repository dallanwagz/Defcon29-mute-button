# Building the DC29 Firmware on macOS

This is a from-scratch plan for building this repo on macOS with `arm-none-eabi-gcc`
and a hand-rolled Makefile, replacing Microchip Studio. Cloning the repo and following
this end-to-end should produce a flashable `.uf2` identical in behavior to the Windows
build.

> **Why this exists:** Microchip Studio is Windows-only. This repo's build is otherwise
> a normal embedded ARM project (ATSAMD21G16B, Cortex-M0+, ASF library), so the IDE
> can be replaced by GNU Arm Embedded Toolchain + a Makefile. All ASF sources, CMSIS
> headers, vendor libraries, and linker scripts are already vendored in-tree.

---

## 1. Target hardware (for context)

| Property        | Value                                                     |
| --------------- | --------------------------------------------------------- |
| MCU             | Microchip ATSAMD21G16B                                    |
| Core            | ARM Cortex-M0+ (`-mcpu=cortex-m0plus -mthumb`)            |
| Flash           | 64 KB total, **first 8 KB is bootloader → 56 KB usable**  |
| RAM             | 8 KB                                                      |
| Bootloader      | UF2 (`uf2conv.py`, family id `0x68ed2b88` for SAMD21)     |
| Programming     | Drag-and-drop `.uf2` after entering bootloader mode       |
| ASF version     | Vendored under `Firmware/Source/DC29/src/ASF/`            |

---

## 2. Prerequisites on macOS

```bash
# Install Homebrew if needed: https://brew.sh

# Toolchain — GNU Arm Embedded (provides arm-none-eabi-gcc, -ld, -objcopy, -size)
brew install --cask gcc-arm-embedded

# Verify
arm-none-eabi-gcc --version       # expect 13.x or newer
arm-none-eabi-objcopy --version
arm-none-eabi-size --version

# Python 3 ships with macOS; uf2conv.py needs python3 only
python3 --version

# (Optional, recommended) GNU make is preinstalled on macOS as `make` (BSD-flavor on
# older systems, GNU on newer). Either works for this Makefile.
make --version
```

If `brew install --cask gcc-arm-embedded` fails or feels stale, the alternative is
the official Arm download (https://developer.arm.com/downloads/-/arm-gnu-toolchain-downloads),
extract the `arm-gnu-toolchain-*-darwin-*-arm-none-eabi.tar.xz` somewhere, and add
its `bin/` to `PATH`.

---

## 3. Important caveat — linker script discrepancy

The committed `DC29.cproj` Release config points its linker at:

```
src/ASF/sam0/utils/linker_scripts/samd21/gcc/samd21j18a_flash.ld
```

That script describes a SAMD21**J18A** (256 KB flash, 32 KB RAM). The actual chip is
SAMD21**G16B** (64 KB flash, 8 KB RAM, with the first 8 KB owned by the UF2 bootloader).
The repo *also* contains the correct script at `src/samd21g16b_flash.ld` (used by the
cproj's Debug config). On Windows this is part of the "local edits required to build"
that aren't committed.

**The Mac Makefile in this plan uses `src/samd21g16b_flash.ld` directly** — this is the
correct script for the actual hardware and it does not require any uncommitted local
edits. Image must fit in 56 KB.

---

## 4. Repository layout assumed by the Makefile

```
<repo root>/
├── Firmware/Source/DC29/
│   ├── Makefile           ← new file you will create from §6
│   ├── DC29.cproj         (untouched; Microchip Studio still works on Windows)
│   ├── src/
│   │   ├── ASF/           (vendored)
│   │   ├── config/
│   │   ├── qtouch/
│   │   ├── samd21g16b_flash.ld   ← linker script we use
│   │   ├── main.c, comms.c, games.c, keys.c, pwm.c, serialconsole.c, ...
│   ├── build/             ← created by `make` (object files, .elf, .hex, .uf2, .map)
│   └── ...
├── utils/uf2conv.py
├── uf2conv.py             (duplicate at root — either works)
└── BUILD_MACOS.md         (this file)
```

The Makefile must live at `Firmware/Source/DC29/Makefile` so its relative paths
(`src/...`, `../../../uf2conv.py`) resolve correctly.

---

## 5. Build configuration extracted from `DC29.cproj` (Release)

Captured here so the Makefile is auditable against the IDE config.

**Preprocessor defines (Release):**
```
NDEBUG
BOARD=SAMD21_XPLAINED_PRO
__SAMD21J18A__              # ASF uses this define even on G16B; matches Windows build
EXTINT_CALLBACK_MODE=true
UDD_ENABLE
ARM_MATH_CM0PLUS=true
USB_DEVICE_LPM_SUPPORT
USART_CALLBACK_MODE=true
SYSTICK_MODE
RTC_COUNT_ASYNC=true
TC_ASYNC=false
TCC_ASYNC=false
```

**Compiler flags (C, Release):**
- `-mcpu=cortex-m0plus -mthumb`
- `-Os` (optimize for size — required, debug build no longer fits in 56 KB)
- `-ffunction-sections -fdata-sections` (so `--gc-sections` can drop unused)
- `-pipe -fno-strict-aliasing -std=gnu99`
- Warning soup from cproj line 449: `-Wall -Wstrict-prototypes -Wmissing-prototypes
  -Werror-implicit-function-declaration -Wpointer-arith -Wchar-subscripts -Wcomment
  -Wformat=2 -Wimplicit-int -Wmain -Wparentheses -Wsequence-point -Wreturn-type
  -Wswitch -Wtrigraphs -Wunused -Wuninitialized -Wunknown-pragmas -Wfloat-equal
  -Wundef -Wshadow -Wbad-function-cast -Wwrite-strings -Wsign-compare
  -Waggregate-return -Wmissing-declarations -Wformat -Wmissing-format-attribute
  -Wno-deprecated-declarations -Wpacked -Wredundant-decls -Wnested-externs
  -Wlong-long -Wunreachable-code -Wcast-align --param max-inline-insns-single=500`

**Linker flags:**
- `-Wl,--entry=Reset_Handler -Wl,--cref -Wl,--gc-sections -mthumb`
- `--specs=nano.specs` (newlib-nano — cproj's `UseNewlibNano=True`)
- `-T src/samd21g16b_flash.ld`
- `-Wl,-Map=build/DC29.map` (gives `--cref` an output sink and produces a usable map)

**Libraries:** `-lsamd21_qt_gcc -larm_cortexM0l_math -lm`
**Library search paths:**
- `src/ASF/thirdparty/CMSIS/Lib/GCC` (libarm_cortexM0l_math.a)
- `src/ASF/thirdparty/qtouch/devspecific/sam0/samd/lib/gcc` (libsamd21_qt_gcc.a)

**Source files (full list, from cproj `<Compile Include>` — 39 files):**

Project sources (7):
```
src/main.c
src/comms.c
src/games.c
src/keys.c
src/pwm.c
src/serialconsole.c
src/qtouch/touch.c
```

ASF sources (32):
```
src/ASF/common/services/sleepmgr/samd/sleepmgr.c
src/ASF/common/services/usb/class/cdc/device/udi_cdc.c
src/ASF/common/services/usb/class/composite/device/udi_composite_desc.c
src/ASF/common/services/usb/class/hid/device/kbd/udi_hid_kbd.c
src/ASF/common/services/usb/class/hid/device/udi_hid.c
src/ASF/common/services/usb/udc/udc.c
src/ASF/common/utils/interrupt/interrupt_sam_nvic.c
src/ASF/common2/services/delay/sam0/systick_counter.c
src/ASF/sam0/drivers/extint/extint_callback.c
src/ASF/sam0/drivers/extint/extint_sam_d_r_h/extint.c
src/ASF/sam0/drivers/nvm/nvm.c
src/ASF/sam0/drivers/port/port.c
src/ASF/sam0/drivers/rtc/rtc_sam_d_r_h/rtc_count.c
src/ASF/sam0/drivers/rtc/rtc_sam_d_r_h/rtc_count_interrupt.c
src/ASF/sam0/drivers/sercom/sercom.c
src/ASF/sam0/drivers/sercom/sercom_interrupt.c
src/ASF/sam0/drivers/sercom/usart/usart.c
src/ASF/sam0/drivers/sercom/usart/usart_interrupt.c
src/ASF/sam0/drivers/system/clock/clock_samd21_r21_da_ha1/clock.c
src/ASF/sam0/drivers/system/clock/clock_samd21_r21_da_ha1/gclk.c
src/ASF/sam0/drivers/system/interrupt/system_interrupt.c
src/ASF/sam0/drivers/system/pinmux/pinmux.c
src/ASF/sam0/drivers/system/system.c
src/ASF/sam0/drivers/tc/tc_sam_d_r_h/tc.c
src/ASF/sam0/drivers/tcc/tcc.c
src/ASF/sam0/drivers/usb/stack_interface/usb_device_udd.c
src/ASF/sam0/drivers/usb/stack_interface/usb_dual.c
src/ASF/sam0/drivers/usb/usb_sam_d_r/usb.c
src/ASF/sam0/services/eeprom/emulator/rwwee_array/rww_eeprom.c
src/ASF/sam0/utils/cmsis/samd21/source/gcc/startup_samd21.c
src/ASF/sam0/utils/cmsis/samd21/source/system_samd21.c
src/ASF/sam0/utils/syscalls/gcc/syscalls.c
```

**Include paths (47, exactly as in cproj Release config):** see Makefile below.

---

## 6. The Makefile

Create `Firmware/Source/DC29/Makefile` with the following contents.

```make
# DC29 firmware — macOS / Linux Makefile (replaces Microchip Studio Release config)
# Target: ATSAMD21G16B (Cortex-M0+). Image must fit in 56 KB (8 KB bootloader reserved).

# ---- Toolchain --------------------------------------------------------------
CROSS    ?= arm-none-eabi-
CC       := $(CROSS)gcc
OBJCOPY  := $(CROSS)objcopy
SIZE     := $(CROSS)size

PYTHON   ?= python3
UF2CONV  := ../../../uf2conv.py
UF2_FAMILY := 0x68ed2b88

# ---- Output -----------------------------------------------------------------
BUILD_DIR := build
TARGET    := DC29
ELF       := $(BUILD_DIR)/$(TARGET).elf
HEX       := $(BUILD_DIR)/$(TARGET).hex
BIN       := $(BUILD_DIR)/$(TARGET).bin
UF2       := $(BUILD_DIR)/$(TARGET).uf2
MAP       := $(BUILD_DIR)/$(TARGET).map

LDSCRIPT  := src/samd21g16b_flash.ld

# ---- Sources ----------------------------------------------------------------
SRCS := \
  src/main.c \
  src/comms.c \
  src/games.c \
  src/keys.c \
  src/pwm.c \
  src/serialconsole.c \
  src/qtouch/touch.c \
  src/ASF/common/services/sleepmgr/samd/sleepmgr.c \
  src/ASF/common/services/usb/class/cdc/device/udi_cdc.c \
  src/ASF/common/services/usb/class/composite/device/udi_composite_desc.c \
  src/ASF/common/services/usb/class/hid/device/kbd/udi_hid_kbd.c \
  src/ASF/common/services/usb/class/hid/device/udi_hid.c \
  src/ASF/common/services/usb/udc/udc.c \
  src/ASF/common/utils/interrupt/interrupt_sam_nvic.c \
  src/ASF/common2/services/delay/sam0/systick_counter.c \
  src/ASF/sam0/drivers/extint/extint_callback.c \
  src/ASF/sam0/drivers/extint/extint_sam_d_r_h/extint.c \
  src/ASF/sam0/drivers/nvm/nvm.c \
  src/ASF/sam0/drivers/port/port.c \
  src/ASF/sam0/drivers/rtc/rtc_sam_d_r_h/rtc_count.c \
  src/ASF/sam0/drivers/rtc/rtc_sam_d_r_h/rtc_count_interrupt.c \
  src/ASF/sam0/drivers/sercom/sercom.c \
  src/ASF/sam0/drivers/sercom/sercom_interrupt.c \
  src/ASF/sam0/drivers/sercom/usart/usart.c \
  src/ASF/sam0/drivers/sercom/usart/usart_interrupt.c \
  src/ASF/sam0/drivers/system/clock/clock_samd21_r21_da_ha1/clock.c \
  src/ASF/sam0/drivers/system/clock/clock_samd21_r21_da_ha1/gclk.c \
  src/ASF/sam0/drivers/system/interrupt/system_interrupt.c \
  src/ASF/sam0/drivers/system/pinmux/pinmux.c \
  src/ASF/sam0/drivers/system/system.c \
  src/ASF/sam0/drivers/tc/tc_sam_d_r_h/tc.c \
  src/ASF/sam0/drivers/tcc/tcc.c \
  src/ASF/sam0/drivers/usb/stack_interface/usb_device_udd.c \
  src/ASF/sam0/drivers/usb/stack_interface/usb_dual.c \
  src/ASF/sam0/drivers/usb/usb_sam_d_r/usb.c \
  src/ASF/sam0/services/eeprom/emulator/rwwee_array/rww_eeprom.c \
  src/ASF/sam0/utils/cmsis/samd21/source/gcc/startup_samd21.c \
  src/ASF/sam0/utils/cmsis/samd21/source/system_samd21.c \
  src/ASF/sam0/utils/syscalls/gcc/syscalls.c

OBJS := $(addprefix $(BUILD_DIR)/, $(SRCS:.c=.o))
DEPS := $(OBJS:.o=.d)

# ---- Defines ----------------------------------------------------------------
DEFINES := \
  -DNDEBUG \
  -DBOARD=SAMD21_XPLAINED_PRO \
  -D__SAMD21J18A__ \
  -DEXTINT_CALLBACK_MODE=true \
  -DUDD_ENABLE \
  -DARM_MATH_CM0PLUS=true \
  -DUSB_DEVICE_LPM_SUPPORT \
  -DUSART_CALLBACK_MODE=true \
  -DSYSTICK_MODE \
  -DRTC_COUNT_ASYNC=true \
  -DTC_ASYNC=false \
  -DTCC_ASYNC=false

# ---- Includes ---------------------------------------------------------------
INCLUDES := \
  -Isrc \
  -Isrc/config \
  -Isrc/ASF/common/boards \
  -Isrc/ASF/common/services/sleepmgr \
  -Isrc/ASF/common/services/usb \
  -Isrc/ASF/common/services/usb/class/cdc \
  -Isrc/ASF/common/services/usb/class/cdc/device \
  -Isrc/ASF/common/services/usb/class/composite/device \
  -Isrc/ASF/common/services/usb/class/hid \
  -Isrc/ASF/common/services/usb/class/hid/device \
  -Isrc/ASF/common/services/usb/class/hid/device/kbd \
  -Isrc/ASF/common/services/usb/udc \
  -Isrc/ASF/common/utils \
  -Isrc/ASF/common2/services/delay \
  -Isrc/ASF/common2/services/delay/sam0 \
  -Isrc/ASF/sam0/boards \
  -Isrc/ASF/sam0/boards/samd21_xplained_pro \
  -Isrc/ASF/sam0/drivers/extint \
  -Isrc/ASF/sam0/drivers/nvm \
  -Isrc/ASF/sam0/drivers/port \
  -Isrc/ASF/sam0/drivers/rtc \
  -Isrc/ASF/sam0/drivers/rtc/rtc_sam_d_r_h \
  -Isrc/ASF/sam0/drivers/sercom \
  -Isrc/ASF/sam0/drivers/sercom/usart \
  -Isrc/ASF/sam0/drivers/system \
  -Isrc/ASF/sam0/drivers/system/clock \
  -Isrc/ASF/sam0/drivers/system/clock/clock_samd21_r21_da_ha1 \
  -Isrc/ASF/sam0/drivers/system/interrupt \
  -Isrc/ASF/sam0/drivers/system/interrupt/system_interrupt_samd21 \
  -Isrc/ASF/sam0/drivers/system/pinmux \
  -Isrc/ASF/sam0/drivers/system/power \
  -Isrc/ASF/sam0/drivers/system/power/power_sam_d_r_h \
  -Isrc/ASF/sam0/drivers/system/reset \
  -Isrc/ASF/sam0/drivers/system/reset/reset_sam_d_r_h \
  -Isrc/ASF/sam0/drivers/tc \
  -Isrc/ASF/sam0/drivers/tc/tc_sam_d_r_h \
  -Isrc/ASF/sam0/drivers/tcc \
  -Isrc/ASF/sam0/drivers/usb \
  -Isrc/ASF/sam0/drivers/usb/stack_interface \
  -Isrc/ASF/sam0/drivers/usb/usb_sam_d_r \
  -Isrc/ASF/sam0/services/eeprom/emulator/rwwee_array \
  -Isrc/ASF/sam0/utils \
  -Isrc/ASF/sam0/utils/cmsis/samd21/include \
  -Isrc/ASF/sam0/utils/cmsis/samd21/source \
  -Isrc/ASF/sam0/utils/header_files \
  -Isrc/ASF/sam0/utils/preprocessor \
  -Isrc/ASF/thirdparty/CMSIS/Include \
  -Isrc/ASF/thirdparty/CMSIS/Lib/GCC \
  -Isrc/ASF/thirdparty/qtouch/devspecific/sam0/samd \
  -Isrc/ASF/thirdparty/qtouch/devspecific/sam0/samd/include

# ---- Flags ------------------------------------------------------------------
ARCH_FLAGS := -mcpu=cortex-m0plus -mthumb

CFLAGS := $(ARCH_FLAGS) \
  -Os \
  -ffunction-sections -fdata-sections \
  -pipe -fno-strict-aliasing -std=gnu99 \
  -Wall -Wstrict-prototypes -Wmissing-prototypes \
  -Werror-implicit-function-declaration -Wpointer-arith \
  -Wchar-subscripts -Wcomment -Wformat=2 -Wimplicit-int -Wmain \
  -Wparentheses -Wsequence-point -Wreturn-type -Wswitch -Wtrigraphs \
  -Wunused -Wuninitialized -Wunknown-pragmas -Wfloat-equal -Wundef \
  -Wshadow -Wbad-function-cast -Wwrite-strings -Wsign-compare \
  -Waggregate-return -Wmissing-declarations -Wformat \
  -Wmissing-format-attribute -Wno-deprecated-declarations -Wpacked \
  -Wredundant-decls -Wnested-externs -Wlong-long -Wunreachable-code \
  -Wcast-align --param max-inline-insns-single=500 \
  -MMD -MP \
  $(DEFINES) $(INCLUDES)

LIB_DIRS := \
  -Lsrc/ASF/thirdparty/CMSIS/Lib/GCC \
  -Lsrc/ASF/thirdparty/qtouch/devspecific/sam0/samd/lib/gcc

LIBS := -lsamd21_qt_gcc -larm_cortexM0l_math -lm

LDFLAGS := $(ARCH_FLAGS) \
  --specs=nano.specs \
  -Wl,--entry=Reset_Handler \
  -Wl,--cref \
  -Wl,--gc-sections \
  -Wl,-Map=$(MAP) \
  -T$(LDSCRIPT)

# ---- Rules ------------------------------------------------------------------
.PHONY: all clean uf2 size flash-info
.DEFAULT_GOAL := uf2

all: $(ELF) $(HEX) $(BIN)

uf2: $(UF2) size

$(BUILD_DIR)/%.o: %.c
	@mkdir -p $(dir $@)
	$(CC) $(CFLAGS) -c $< -o $@

$(ELF): $(OBJS) $(LDSCRIPT)
	@mkdir -p $(dir $@)
	$(CC) $(OBJS) $(LDFLAGS) $(LIB_DIRS) $(LIBS) -o $@

$(HEX): $(ELF)
	$(OBJCOPY) -O ihex $< $@

$(BIN): $(ELF)
	$(OBJCOPY) -O binary $< $@

$(UF2): $(HEX)
	$(PYTHON) $(UF2CONV) --family $(UF2_FAMILY) --convert --output $@ $<

size: $(ELF)
	@$(SIZE) -A -d $(ELF) | awk 'BEGIN{t=0} /^\.text|^\.data|^\.rodata/{t+=$$2} END{printf "Flash used (.text+.data+.rodata): %d bytes (limit 57344 = 56 KB)\n", t}'
	@$(SIZE) -B $(ELF)

clean:
	rm -rf $(BUILD_DIR)

flash-info:
	@echo "1. Hold the bottom-right button while plugging the badge into USB."
	@echo "2. Wait for it to mount as a USB drive (something like 'DC29BOOT')."
	@echo "3. Drag $(UF2) onto that drive. The badge will reflash and reboot."
	@echo
	@echo "If the badge keeps rebooting into bootloader: do NOT hold any button"
	@echo "during the next replug — see CLAUDE memory note about the button-during-"
	@echo "reboot trap."

-include $(DEPS)
```

---

## 7. Build, flash, verify

From the repo root after cloning on macOS:

```bash
cd Firmware/Source/DC29

make             # produces build/DC29.elf, .hex, .bin, .uf2, .map and prints size
make size        # re-print size summary
make clean       # remove build/
make flash-info  # print the manual flashing steps
```

**Sanity check on size.** The size target prints the flash usage and the 56 KB
limit. If `.text + .data + .rodata > 57344` the firmware will not fit; back off
to a smaller change or drop a feature. The `.map` file at `build/DC29.map` is
the place to investigate symbol bloat.

**Flashing the .uf2.**

1. Unplug the badge.
2. Hold the **bottom-right button** while plugging into USB.
3. The badge appears as a USB mass-storage drive.
4. `cp build/DC29.uf2 /Volumes/<bootloader-drive>/` — or drag and drop in Finder.
5. The badge reflashes and reboots into the new firmware.

**Verify.** Open a serial terminal to the badge's CDC port (any baud — auto-negotiated),
press Enter, and the main menu should appear. To check the Issue #5 modifier
fix specifically, follow the steps in `BUILD_NOTES.md` §"Verify the Fix".

---

## 8. Troubleshooting

**`arm-none-eabi-gcc: command not found`**
Toolchain isn't on `PATH`. Re-run `brew install --cask gcc-arm-embedded`, or
`echo $PATH` and confirm the toolchain `bin/` is included.

**`cannot find -lsamd21_qt_gcc` or `-larm_cortexM0l_math`**
The `-L` paths in `LIB_DIRS` are wrong relative to the Makefile's working
directory. The Makefile must live at `Firmware/Source/DC29/Makefile` so those
relative paths resolve. Check `ls src/ASF/thirdparty/CMSIS/Lib/GCC/libarm_cortexM0l_math.a`
returns a file.

**Linker error: section overflow / region `rom` overflowed**
The image exceeds 56 KB. Either you're building with the wrong linker script
(verify `LDSCRIPT := src/samd21g16b_flash.ld`) or the change actually doesn't
fit. Inspect `build/DC29.map`.

**`undefined reference to _sbrk` / `_write` / `_close` etc.**
The Makefile compiles `src/ASF/sam0/utils/syscalls/gcc/syscalls.c` which
provides newlib syscalls stubs. If you removed it, restore it.

**Binary builds but board does not enumerate as USB device after flash**
Most likely the linker script is wrong (e.g. missing the bootloader offset of
`0x2000`) and the reset vector lands in bootloader-owned flash. Confirm
`src/samd21g16b_flash.ld` has `ORIGIN = 0x00000000+0x2000` for the `rom` region.

**The badge is stuck in bootloader after a flash that should have worked**
Per `~/.claude/.../feedback_button_during_reboot.md`: holding the bottom-right
button across a power cycle traps the badge in bootloader regardless of the
firmware. Replug the badge with no buttons held before assuming the firmware
is broken.

**Build works on Mac, but downstream PR review wants the cproj/Microchip Studio
build to keep working too**
This Makefile is additive — it does not edit `DC29.cproj`. The Windows IDE
build path is unchanged.

---

## 9. What this plan does *not* cover

- **Debugging.** Microchip Studio's J-Link integration is not replicated. For
  on-target debugging from macOS you'd add `openocd` or `pyocd` plus a
  `gdbserver` invocation; that's out of scope here. Print-via-CDC (`comms.c`)
  remains the easiest debug channel.
- **The Atmel Studio project file.** `DC29.cproj` and `Defcon29.atsln` are
  untouched. Windows users continue to use Microchip Studio.
- **Bootloader (`dc29boot.hex`).** Not built from source in this repo; the
  prebuilt hex in `Firmware/Compiled/` is flashed once via SWD/J-Link by the
  badge maker. macOS doesn't need to rebuild it.

---

## 10. Validation status

This plan was authored on Windows by inspecting the project structure and
extracting build settings from `DC29.cproj` (Release config, lines 367–577).
**The Makefile has not been compiled and run end-to-end on macOS yet** — that
is the user's first task on the new machine. Likely first-build hiccups:

- Newer `arm-none-eabi-gcc` (13+) may surface new warnings the cproj's warning
  set treats as fatal in some transitive header. Fix is to soften specific
  `-Werror` triggers, not to disable `-Wall`.
- One or two ASF includes might be unused on this exact device variant and
  emit "unused" warnings; harmless under `-Wno-unused-*` if needed.
- If `make` reports duplicate symbols at link time, an ASF source has been
  added to `SRCS` that the cproj actually excludes — re-check against the
  cproj `<Compile Include>` list in §5.

When the first successful Mac build produces a `.uf2` that's identical-or-close
in size to a known-good Windows build of the same commit, the plan is
validated. Document any deltas you had to apply at the bottom of this file
under a "macOS build deltas" section so future builds are reproducible.
