# DC29 Badge Firmware — macOS/Linux build
# Requires: brew install arm-none-eabi-gcc
# Usage:
#   make          — build DC29.uf2 in build/
#   make flash    — build + copy to DFU drive (auto-detects mount point)
#   make size     — show section sizes of last build
#   make clean    — remove build/

# ---------------------------------------------------------------------------
# Toolchain
# ---------------------------------------------------------------------------
CC      := arm-none-eabi-gcc
OBJCOPY := arm-none-eabi-objcopy
SIZE    := arm-none-eabi-size

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BUILD   := build
SRCROOT := src

UF2CONV := $(shell command -v uf2conv.py 2>/dev/null || \
           ([ -f ../../../uf2conv.py ] && echo ../../../uf2conv.py) || \
           ([ -f uf2conv.py ] && echo uf2conv.py) || echo "")

# ---------------------------------------------------------------------------
# Defines  (from cproj Release AssemblerFlags + __SAMD21G16B__)
# ---------------------------------------------------------------------------
DEFS  = -DARM_MATH_CM0PLUS=true
DEFS += -DBOARD=SAMD21_XPLAINED_PRO
DEFS += -DEXTINT_CALLBACK_MODE=true
DEFS += -DUDD_ENABLE
DEFS += -DUSB_DEVICE_LPM_SUPPORT
DEFS += -D__SAMD21G16B__
DEFS += -DUSART_CALLBACK_MODE=true
DEFS += -DSYSTICK_MODE
DEFS += -DRTC_COUNT_ASYNC=true
DEFS += -DTC_ASYNC=false
DEFS += -DTCC_ASYNC=false

# ---------------------------------------------------------------------------
# Include paths  (derived from cproj + header location mapping)
# ---------------------------------------------------------------------------
INCS  = -I$(SRCROOT)
INCS += -I$(SRCROOT)/config
# CMSIS device + core
INCS += -I$(SRCROOT)/ASF/sam0/utils/cmsis/samd21/include
INCS += -I$(SRCROOT)/ASF/sam0/utils/cmsis/samd21/source
INCS += -I$(SRCROOT)/ASF/thirdparty/CMSIS/Include
# SAM0 utilities (compiler.h, status_codes.h, preprocessor.h, io.h)
INCS += -I$(SRCROOT)/ASF/sam0/utils
INCS += -I$(SRCROOT)/ASF/sam0/utils/preprocessor
INCS += -I$(SRCROOT)/ASF/sam0/utils/header_files
# Common utilities (parts.h, interrupt.h)
INCS += -I$(SRCROOT)/ASF/common/utils
INCS += -I$(SRCROOT)/ASF/common/utils/interrupt
# Board headers
INCS += -I$(SRCROOT)/ASF/common/boards
INCS += -I$(SRCROOT)/ASF/sam0/boards
INCS += -I$(SRCROOT)/ASF/sam0/boards/samd21_xplained_pro
# Peripheral drivers
INCS += -I$(SRCROOT)/ASF/sam0/drivers/extint
INCS += -I$(SRCROOT)/ASF/sam0/drivers/extint/extint_sam_d_r_h
INCS += -I$(SRCROOT)/ASF/sam0/drivers/nvm
INCS += -I$(SRCROOT)/ASF/sam0/drivers/port
INCS += -I$(SRCROOT)/ASF/sam0/drivers/rtc
INCS += -I$(SRCROOT)/ASF/sam0/drivers/rtc/rtc_sam_d_r_h
INCS += -I$(SRCROOT)/ASF/sam0/drivers/sercom
INCS += -I$(SRCROOT)/ASF/sam0/drivers/sercom/usart
INCS += -I$(SRCROOT)/ASF/sam0/drivers/tc
INCS += -I$(SRCROOT)/ASF/sam0/drivers/tc/tc_sam_d_r_h
INCS += -I$(SRCROOT)/ASF/sam0/drivers/tcc
INCS += -I$(SRCROOT)/ASF/sam0/drivers/usb
INCS += -I$(SRCROOT)/ASF/sam0/drivers/usb/stack_interface
INCS += -I$(SRCROOT)/ASF/sam0/drivers/usb/usb_sam_d_r
# System driver (system.h, clock.h, gclk.h, pinmux.h, power.h, reset.h)
INCS += -I$(SRCROOT)/ASF/sam0/drivers/system
INCS += -I$(SRCROOT)/ASF/sam0/drivers/system/clock
INCS += -I$(SRCROOT)/ASF/sam0/drivers/system/clock/clock_samd21_r21_da_ha1
INCS += -I$(SRCROOT)/ASF/sam0/drivers/system/interrupt
INCS += -I$(SRCROOT)/ASF/sam0/drivers/system/interrupt/system_interrupt_samd21
INCS += -I$(SRCROOT)/ASF/sam0/drivers/system/pinmux
INCS += -I$(SRCROOT)/ASF/sam0/drivers/system/power
INCS += -I$(SRCROOT)/ASF/sam0/drivers/system/power/power_sam_d_r_h
INCS += -I$(SRCROOT)/ASF/sam0/drivers/system/reset
INCS += -I$(SRCROOT)/ASF/sam0/drivers/system/reset/reset_sam_d_r_h
# EEPROM emulator
INCS += -I$(SRCROOT)/ASF/sam0/services/eeprom/emulator/rwwee_array
# Common services
INCS += -I$(SRCROOT)/ASF/common/services/sleepmgr
INCS += -I$(SRCROOT)/ASF/common/services/sleepmgr/samd
INCS += -I$(SRCROOT)/ASF/common2/services/delay
INCS += -I$(SRCROOT)/ASF/common2/services/delay/sam0
# USB stack
INCS += -I$(SRCROOT)/ASF/common/services/usb
INCS += -I$(SRCROOT)/ASF/common/services/usb/udc
INCS += -I$(SRCROOT)/ASF/common/services/usb/class/cdc
INCS += -I$(SRCROOT)/ASF/common/services/usb/class/cdc/device
INCS += -I$(SRCROOT)/ASF/common/services/usb/class/composite/device
INCS += -I$(SRCROOT)/ASF/common/services/usb/class/hid/device
INCS += -I$(SRCROOT)/ASF/common/services/usb/class/hid
INCS += -I$(SRCROOT)/ASF/common/services/usb/class/hid/device
INCS += -I$(SRCROOT)/ASF/common/services/usb/class/hid/device/kbd
# qtouch
INCS += -I$(SRCROOT)/ASF/thirdparty/qtouch/devspecific/sam0/samd/include
INCS += -I$(SRCROOT)/qtouch

# ---------------------------------------------------------------------------
# CPU / arch flags
# ---------------------------------------------------------------------------
MCU := -mcpu=cortex-m0plus -mthumb

# ---------------------------------------------------------------------------
# Compiler flags
# ---------------------------------------------------------------------------
CFLAGS  = $(MCU)
CFLAGS += $(DEFS)
CFLAGS += $(INCS)
CFLAGS += -Os
CFLAGS += -std=gnu99
CFLAGS += -ffunction-sections
CFLAGS += -fdata-sections
CFLAGS += -fno-strict-aliasing
CFLAGS += -pipe
# GCC 13 emits new warnings on old ASF code (register keyword, implicit-int
# patterns, etc.). Suppress all to get a clean first build; re-enable
# selectively once confirmed working.
CFLAGS += -Wall -Wextra -Wno-unused-parameter -Wno-sign-compare -Wno-pointer-sign -Wno-unused-but-set-variable -Wno-unused-function

# ---------------------------------------------------------------------------
# Linker flags
# ---------------------------------------------------------------------------
# LDFLAGS intentionally left empty — link command is spelled out explicitly in
# the DC29.elf rule so that -l flags come after object files (GCC requirement).

# ---------------------------------------------------------------------------
# Sources  (from DC29.cproj <Compile> items)
# ---------------------------------------------------------------------------
SRCS := \
    $(SRCROOT)/ASF/common/services/sleepmgr/samd/sleepmgr.c \
    $(SRCROOT)/ASF/common/services/usb/class/cdc/device/udi_cdc.c \
    $(SRCROOT)/ASF/common/services/usb/class/composite/device/udi_composite_desc.c \
    $(SRCROOT)/ASF/common/services/usb/class/hid/device/kbd/udi_hid_kbd.c \
    $(SRCROOT)/ASF/common/services/usb/class/hid/device/udi_hid.c \
    $(SRCROOT)/ASF/common/services/usb/udc/udc.c \
    $(SRCROOT)/ASF/common/utils/interrupt/interrupt_sam_nvic.c \
    $(SRCROOT)/ASF/common2/services/delay/sam0/systick_counter.c \
    $(SRCROOT)/ASF/sam0/drivers/extint/extint_callback.c \
    $(SRCROOT)/ASF/sam0/drivers/extint/extint_sam_d_r_h/extint.c \
    $(SRCROOT)/ASF/sam0/drivers/nvm/nvm.c \
    $(SRCROOT)/ASF/sam0/drivers/port/port.c \
    $(SRCROOT)/ASF/sam0/drivers/rtc/rtc_sam_d_r_h/rtc_count.c \
    $(SRCROOT)/ASF/sam0/drivers/rtc/rtc_sam_d_r_h/rtc_count_interrupt.c \
    $(SRCROOT)/ASF/sam0/drivers/sercom/sercom.c \
    $(SRCROOT)/ASF/sam0/drivers/sercom/sercom_interrupt.c \
    $(SRCROOT)/ASF/sam0/drivers/sercom/usart/usart.c \
    $(SRCROOT)/ASF/sam0/drivers/sercom/usart/usart_interrupt.c \
    $(SRCROOT)/ASF/sam0/drivers/system/clock/clock_samd21_r21_da_ha1/clock.c \
    $(SRCROOT)/ASF/sam0/drivers/system/clock/clock_samd21_r21_da_ha1/gclk.c \
    $(SRCROOT)/ASF/sam0/drivers/system/interrupt/system_interrupt.c \
    $(SRCROOT)/ASF/sam0/drivers/system/pinmux/pinmux.c \
    $(SRCROOT)/ASF/sam0/drivers/system/system.c \
    $(SRCROOT)/ASF/sam0/drivers/tc/tc_sam_d_r_h/tc.c \
    $(SRCROOT)/ASF/sam0/drivers/tcc/tcc.c \
    $(SRCROOT)/ASF/sam0/drivers/usb/stack_interface/usb_device_udd.c \
    $(SRCROOT)/ASF/sam0/drivers/usb/stack_interface/usb_dual.c \
    $(SRCROOT)/ASF/sam0/drivers/usb/usb_sam_d_r/usb.c \
    $(SRCROOT)/ASF/sam0/services/eeprom/emulator/rwwee_array/rww_eeprom.c \
    $(SRCROOT)/ASF/sam0/utils/cmsis/samd21/source/gcc/startup_samd21.c \
    $(SRCROOT)/ASF/sam0/utils/cmsis/samd21/source/system_samd21.c \
    $(SRCROOT)/ASF/sam0/utils/syscalls/gcc/syscalls.c \
    $(SRCROOT)/comms.c \
    $(SRCROOT)/input.c \
    $(SRCROOT)/jiggler.c \
    $(SRCROOT)/keys.c \
    $(SRCROOT)/main.c \
    $(SRCROOT)/pwm.c \
    $(SRCROOT)/qtouch/touch.c \
    $(SRCROOT)/serialconsole.c \
    $(SRCROOT)/usb_webusb.c \
    $(SRCROOT)/wled_fx.c

# Derive object file paths (preserving source subdirectory structure in build/)
OBJS := $(patsubst %.c,$(BUILD)/%.o,$(SRCS))

# ---------------------------------------------------------------------------
# Targets
# ---------------------------------------------------------------------------
.PHONY: all hex uf2 size flash clean

all: $(BUILD)/DC29.uf2

$(BUILD)/DC29.elf: $(OBJS)
	$(CC) $(MCU) -T$(SRCROOT)/samd21g16b_flash.ld \
	    -Wl,--entry=Reset_Handler -Wl,--cref -Wl,--gc-sections \
	    -specs=nano.specs \
	    -Wl,-Map=$(BUILD)/DC29.map \
	    -o $@ $(OBJS) \
	    -L$(SRCROOT)/ASF/thirdparty/qtouch/devspecific/sam0/samd/lib/gcc \
	    -lsamd21_qt_gcc
	@echo ""
	@$(SIZE) --format=berkeley $@

$(BUILD)/DC29.hex: $(BUILD)/DC29.elf
	$(OBJCOPY) -O ihex $< $@
	@echo "HEX: $@"

$(BUILD)/DC29.uf2: $(BUILD)/DC29.hex
	@if [ -z "$(UF2CONV)" ]; then \
	    echo ""; \
	    echo "ERROR: uf2conv.py not found."; \
	    echo "  Download it (plus uf2families.json) from:"; \
	    echo "    https://github.com/microsoft/uf2/blob/master/utils/uf2conv.py"; \
	    echo "    https://github.com/microsoft/uf2/blob/master/utils/uf2families.json"; \
	    echo "  Place both files alongside this Makefile or on PATH, then re-run."; \
	    exit 1; \
	fi
	python3 $(UF2CONV) $(BUILD)/DC29.hex --convert --output $(BUILD)/DC29.uf2
	@echo "UF2: $(BUILD)/DC29.uf2  ($$(wc -c < "$(BUILD)/DC29.uf2" | tr -d ' ') bytes)"

hex: $(BUILD)/DC29.hex

uf2: $(BUILD)/DC29.uf2

size: $(BUILD)/DC29.elf
	$(SIZE) --format=berkeley $<

flash: $(BUILD)/DC29.uf2
	@DRIVE=""; \
	for d in /Volumes/*/; do \
	    if [ -f "$$d/INFO_UF2.TXT" ]; then DRIVE="$$d"; break; fi; \
	done; \
	if [ -z "$$DRIVE" ]; then \
	    echo "No UF2 bootloader drive found."; \
	    echo "To enter DFU mode: hold BUTTON4, plug USB, release as soon as the drive mounts."; \
	    exit 1; \
	fi; \
	echo "Flashing to $$DRIVE ..."; \
	cp $(BUILD)/DC29.uf2 "$$DRIVE"; \
	echo "Done — drive will disappear as badge reboots."

clean:
	rm -rf $(BUILD)

# ---------------------------------------------------------------------------
# Compile rule  (create output directory as needed)
# ---------------------------------------------------------------------------
$(BUILD)/%.o: %.c
	@mkdir -p $(dir $@)
	$(CC) $(CFLAGS) -c $< -o $@
