# FAQ and Troubleshooting

← Back to [User Guide](README.md)

---

## Badge / Serial Port Issues

### No serial port appears when I plug in the badge

**macOS:** Run `ls /dev/tty.usbmodem*`. If nothing appears:
- Make sure SW5 (the power switch) is ON
- Try a different USB cable — some cables are charge-only and don't have data lines
- Try a different USB port

**Windows:** Open Device Manager → Universal Serial Bus devices. If you see an unknown device with a yellow exclamation mark:
1. Right-click → Update Driver → Browse my computer for drivers
2. Navigate to `Firmware/Source/DC29/`
3. Select `atmel_devices_cdc.inf` and install

After driver install, the badge should appear under Ports (COM & LPT).

### The port disappears partway through use

The badge may be entering standby sleep. It sleeps after 1 second of inactivity when not connected to USB power. Make sure the badge is fully USB-connected (not just charging from a USB charger).

If the port disappears while the badge is plugged in to a computer: this is a known issue with some USB hubs. Try plugging directly into the computer.

### Wrong port name — how do I find it?

The port suffix changes when you plug into a different USB port on macOS.

```bash
# List all modem-style serial ports
ls /dev/tty.usbmodem*

# If multiple devices appear, unplug the badge and run again
# to see which one disappears
```

---

## Teams Issues

### Script says "Connection refused" when connecting to Teams

The Teams Local API is not accepting connections. Check:
1. **Is Teams running?** The API only works while Teams is open.
2. **Is the API enabled?** Teams → Settings → Privacy → Manage API → Enable third-party API
3. **Did you restart Teams** after enabling the setting? Some versions require a restart.

### No authorization dialog appeared in Teams

Teams may have connected silently using a previously-saved token. Check `~/.dc29_teams_token`. If the file exists but Teams rejects the connection, delete it and re-run:

```bash
rm ~/.dc29_teams_token
dc29 teams --port /dev/tty.usbmodem14201
```

A new pairing dialog should appear.

### The authorization dialog disappeared before I clicked Allow

Dismiss and re-run the script. The dialog reappears.

### LED 4 never changes color during meetings

Run the script with `--verbose` to see what's happening:

```bash
dc29 teams --port /dev/tty.usbmodem14201 --verbose
```

Look for lines like `State -> MUTED` or `State -> CLEAR`. If you see these but LED 4 doesn't change, the serial port write may be failing — check that no other program is holding the port open (TUI, terminal, etc.).

If you don't see state change lines, the Teams API isn't sending updates. Check that you're actually in a Teams meeting (not Zoom, Google Meet, etc. — the bridge only talks to Teams).

### LED 4 stays on after leaving a meeting

Teams sometimes delays the `isInMeeting = false` event. Leave the meeting cleanly using the Teams "Leave" button rather than just closing the window. The LED should clear within a few seconds.

### I'm on macOS but the Teams mute shortcut doesn't work from the badge

macOS Teams uses **Cmd+Shift+M**, not Ctrl+Shift+M. Reconfigure button 4:

```bash
dc29 set-key 4 0x0A 0x10 --port /dev/tty.usbmodem14201
```

`0x0A` = Shift+Cmd, `0x10` = the letter M.

---

## macOS Permission Issues

### Hotkey feature says "Could not start hotkey listener"

The pynput global hotkey requires Accessibility permission:

1. **System Settings → Privacy & Security → Accessibility**
2. Find your terminal application in the list (Terminal.app, iTerm2, Warp, etc.)
3. Toggle it ON
4. Quit and relaunch your terminal
5. Re-run `dc29 teams`

If your terminal app isn't in the list: click the `+` button and navigate to `/Applications/Utilities/Terminal.app` (or wherever your terminal lives).

### I see a permission error accessing /dev/tty.usbmodem...

On macOS Sequoia (15.x), new USB device permission prompts may appear. Click Allow in the system dialog.

---

## Keymap Issues

### I set a new keymap but the button still sends the old key

Wait a second — keymap changes write to EEPROM which takes a brief moment. You should hear/see the badge send `ACK` (the script logs it). Try the button again.

If it still sends the wrong key, query the button to confirm what's stored:

```bash
dc29 get-key 1 --port /dev/tty.usbmodem14201
```

### The badge is sending keys I didn't configure

The badge may still have factory keymaps. Run `dc29 info --port PORT` to see all 4 button keymaps. Use `dc29 set-key` to change them.

### Buttons aren't sending any keys at all

Buttons only send HID keystrokes when connected via USB to a computer that accepts HID. The badge must be connected to a host that has enumerated its USB HID interface. The USB CDC serial port appearing is not sufficient — the USB HID interface must also be active.

If you see the serial port but buttons don't work: try opening a text editor and pressing badge buttons. On some hosts, the HID interface takes a few seconds to enumerate after the CDC port appears.

---

## LED Issues

### LED 4 color is wrong (stuck red or green)

LED 4 is controlled by the Teams bridge. If the bridge isn't running, LED 4 shows its EEPROM idle color (default: dim white). If it's stuck red or green, the bridge may have set the color and then crashed before clearing it.

Run `dc29 set-led 4 0 0 0 --port PORT` to manually clear it.

### LED colors look dim or wrong

LED brightness is set per-component in the `set-led` command. Full brightness is `255`. Try:

```bash
dc29 set-led 1 255 0 0 --port PORT   # full-brightness red
```

---

## General

### How do I reset the badge to factory defaults?

The simplest way is to reflash the firmware — see [docs/hacker/flashing.md](../hacker/flashing.md). Reflashing itself does not reset EEPROM, but the firmware version check on boot will reset EEPROM if it detects a version mismatch.

To reset keymaps and LED colors without reflashing, use the TUI's reset function.

### The badge is stuck in DFU mode (flashing red LED, mounts as drive)

You held BUTTON4 too long while plugging in. The badge is in bootloader mode.

Fix: unplug, release all buttons, plug back in normally. The badge should boot normally.

If you accidentally started a bad firmware flash, you may need to drag a known-good `.uf2` onto the drive while it's still mounted.

### I accidentally overwrote my firmware

Pre-compiled `.uf2` files for the original DC29 firmware are in `Firmware/Compiled/`. Identify your badge type (Human, Creator, Artist, Vendor, Speaker, Goon, Press) and drag the corresponding `.uf2` onto the DFU drive to restore.
