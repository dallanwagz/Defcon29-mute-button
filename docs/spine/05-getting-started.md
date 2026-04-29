# DC29 Badge — Getting Started

> **docs/spine/** is the authoritative source of truth.

← Back to [Project Overview](00-overview.md)

## Requirements

- DC29 badge (hardware)
- USB cable (Micro-B or whatever the badge uses)
- Python 3.10 or newer
- macOS or Windows

---

## Step 1: Install the Python Tooling

```bash
pip install dc29-badge
```

This installs the `dc29` command and all dependencies (pyserial, websockets, typer, rich, textual).

For the Teams toggle hotkey feature (optional):

```bash
pip install "dc29-badge[hotkey]"
```

This adds `pynput` for global keyboard hotkey interception.

### Verify the install

```bash
dc29 --help
```

You should see a list of subcommands: `ui`, `teams`, `set-key`, `get-key`, `set-led`, `set-effect`, `info`, `monitor`.

---

## Step 2: Connect the Badge

1. Flip the **SW5 power switch** to ON (if present on your badge)
2. Plug the badge into a USB port
3. The badge runs a startup LED sequence (red → green → blue sweep across all 4 LEDs)
4. Two devices should appear:
   - A USB HID keyboard device (handled by the OS automatically)
   - A USB CDC serial port

### Find the serial port

**macOS:**
```bash
ls /dev/tty.usbmodem*
```
Example output: `/dev/tty.usbmodem14201`

**Linux:**
```bash
ls /dev/ttyACM*
```
Example output: `/dev/ttyACM0`

**Windows:**
Open Device Manager → Ports (COM & LPT). Look for "USB Serial Device". Note the `COMx` number.

If no serial port appears, the CDC driver may not be installed. On Windows, install the Microchip CDC driver from `Firmware/Source/DC29/atmel_devices_cdc.inf`.

---

## Step 3: Run the Teams Mute Indicator

### Enable the Teams Local API (one time)

Open Microsoft Teams → **Settings** → **Privacy** → **Manage API**. Enable **"Enable third-party API"**. Restart Teams if prompted.

If you don't see this option:
- Teams version 1.6.x or newer is required
- Some corporate tenants disable this via admin policy — check with IT

### Run the bridge

```bash
# macOS / Linux
dc29 teams --port /dev/tty.usbmodem14201

# Windows
dc29 teams --port COM3
```

**First run only:** Teams shows an authorization dialog for "DC29 / DefconBadgeMacropad / MuteIndicator". Click **Allow**. The token is saved to `~/.dc29_teams_token`. Subsequent runs skip the dialog.

### Verify it works

| Situation | LED 4 state |
|-----------|------------|
| Not in a meeting | Off |
| In a meeting, muted | Red |
| In a meeting, unmuted | Green |

---

## Step 4: Optional — Run the TUI

The TUI lets you view and change keymaps, LED colors, and test the badge interactively.

```bash
dc29 ui
```

The TUI connects to the badge on the port you select and shows:
- Current keymap for all 4 buttons
- Live LED color display
- Current effect mode
- Event log (button presses, chord events)

---

## macOS-Specific Notes

### pynput Accessibility Permission

The `--toggle-hotkey` feature in `dc29 teams` uses `pynput` to intercept a global keyboard shortcut. macOS requires Accessibility permission for this:

1. Open **System Settings → Privacy & Security → Accessibility**
2. Find your terminal app (Terminal.app, iTerm2, etc.) and enable it
3. Restart the terminal app

If permission is not granted, the Teams bridge will log a warning and disable the hotkey, but the mute indicator still works.

### macOS Teams Mute Shortcut

Teams on macOS uses **Cmd+Shift+M** to toggle mute. Configure badge button 4 for this:

```bash
dc29 set-key 4 0x0A 0x10
```

- `0x0A` = `MOD_SHIFT_GUI` (Shift + Cmd)
- `0x10` = keycode for `m`

Do **not** use `Ctrl+Shift+M` (modifier `0x03`) — that is the Windows shortcut and does nothing on macOS Teams.

### Serial Port Persistence

The `/dev/tty.usbmodem*` port suffix changes when you plug into a different USB port. This matters for autostart scripts — use the specific port path that appears at your preferred USB port.

---

## Windows-Specific Notes

### CDC Driver

Windows may need the CDC driver on first plug-in:
1. Open Device Manager → Universal Serial Bus devices
2. If you see an unknown device, right-click → Update Driver → Browse my computer → point to `Firmware/Source/DC29/`
3. The `atmel_devices_cdc.inf` driver file is in that directory

### Teams Mute Shortcut

Windows Teams uses **Ctrl+Shift+M**. Configure badge button 4:

```bash
dc29 set-key 4 0x03 0x10
```

- `0x03` = `MOD_CTRL_SHIFT`
- `0x10` = keycode for `m`

---

## Autostart on macOS (launchd)

To run the Teams bridge automatically at login:

1. Find your badge's serial port: `ls /dev/tty.usbmodem*`
2. Find your Python path: `which python3` (or the path inside your venv)
3. Create `~/Library/LaunchAgents/com.local.dc29-teams-mute.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.local.dc29-teams-mute</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/local/bin/dc29</string>
        <string>teams</string>
        <string>--port</string>
        <string>/dev/tty.usbmodemXXXXX</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>/tmp/dc29-teams-mute.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/dc29-teams-mute.err</string>
</dict>
</plist>
```

4. Load the agent:
```bash
launchctl load ~/Library/LaunchAgents/com.local.dc29-teams-mute.plist
```

5. Check it started:
```bash
tail -f /tmp/dc29-teams-mute.log
```

To stop or unload:
```bash
launchctl unload ~/Library/LaunchAgents/com.local.dc29-teams-mute.plist
```

**Fragility note:** If you plug into a different USB port, the device path changes and launchd will fail. Update the plist with the new port path and reload.

---

## Quick Reference: CLI Commands

```bash
dc29 ui                             # launch TUI
dc29 teams --port PORT              # run Teams bridge
dc29 set-key BUTTON MOD KEY         # set a button's keymap
dc29 get-key BUTTON                 # query a button's keymap
dc29 set-led N R G B                # set LED color (RAM, not saved)
dc29 set-effect MODE                # set effect mode (0/1/2)
dc29 info                           # show all keymaps
dc29 monitor                        # stream raw badge events
```

All commands accept `--port PORT` to specify the serial port. Many also support `--help` for full option documentation.
