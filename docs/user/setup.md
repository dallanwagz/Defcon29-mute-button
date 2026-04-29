# Setup Guide

← Back to [User Guide](README.md)

## What You Need

- Your DC29 badge
- A USB cable (Micro-B, the same kind used for older Android phones)
- Python 3.10 or newer
- macOS or Windows

---

## Step 1: Install Python (if needed)

**macOS:** Python 3 is usually already installed. Run `python3 --version` to check. If you need it, install from [python.org](https://python.org) or via Homebrew (`brew install python3`).

**Windows:** Download from [python.org](https://python.org). During install, check **"Add Python to PATH"**.

---

## Step 2: Install dc29-badge

Open a terminal (macOS: Terminal.app; Windows: Command Prompt or PowerShell) and run:

```bash
pip install dc29-badge
```

If you want the optional Teams toggle hotkey (intercept a keyboard shortcut):

```bash
pip install "dc29-badge[hotkey]"
```

Verify it installed:

```bash
dc29 --help
```

You should see a list of commands.

---

## Step 3: Connect the Badge

1. Find the **SW5 power switch** on the badge and flip it to ON (if your badge has one)
2. Plug the badge into your computer's USB port
3. Watch the badge run its startup LED sequence — the four LEDs sweep red → green → blue across all corners
4. The badge shows up as two things: a keyboard (handled automatically by your OS) and a serial port

### Find the serial port

**macOS:**
```bash
ls /dev/tty.usbmodem*
```
You'll see something like `/dev/tty.usbmodem14201`. That's the port name you'll use.

**Windows:**
Open **Device Manager** → expand **Ports (COM & LPT)**. Look for "USB Serial Device". Note the number, e.g. `COM3`.

If nothing appears on Windows, you may need to install the CDC driver. Browse to `Firmware/Source/DC29/` in the repository and point Windows to the `atmel_devices_cdc.inf` file.

---

## Step 4: Enable the Teams Local API

This is a one-time Teams setting.

1. Open Microsoft Teams
2. Go to **Settings** → **Privacy** → **Manage API**
3. Toggle on **"Enable third-party API"** (may also be labeled "Allow API" or "Third-party app permission" depending on your Teams version)
4. Restart Teams if it prompts you

If you don't see this setting, your organization's IT policy may be blocking it. Teams version 1.6.x or newer is required.

---

## Step 5: Run the Teams Bridge

```bash
# macOS / Linux
dc29 teams --port /dev/tty.usbmodem14201

# Windows
dc29 teams --port COM3
```

**First run only:** Microsoft Teams will show a dialog asking whether to allow "DC29 / DefconBadgeMacropad / MuteIndicator" to connect. Click **Allow**. The pairing token is saved to `~/.dc29_teams_token` — you won't see this dialog again.

You should see log output like:
```
10:45:01 INFO Connecting to Teams Local API...
10:45:02 INFO Connected. Listening for meeting updates...
```

Now join a Teams meeting. The badge's LED 4 (bottom-right) should change color to reflect your mute state.

---

## Step 6 (Optional): Set Up the Mute Toggle Button

You can configure badge **BUTTON 4** (bottom-right) to toggle Teams mute directly:

**macOS** — Teams uses Cmd+Shift+M:
```bash
dc29 set-key 4 0x0A 0x10 --port /dev/tty.usbmodem14201
```

**Windows** — Teams uses Ctrl+Shift+M:
```bash
dc29 set-key 4 0x03 0x10 --port COM3
```

This saves the keymap to the badge's EEPROM. The setting persists after power cycle.

When you press button 4, it sends the keyboard shortcut to Teams. Teams then toggles your mute state and reports the new state back to the badge, keeping LED 4 accurate.

---

## Step 7 (Optional): Autostart on macOS

To run the Teams bridge automatically whenever you log in:

1. Find your `dc29` command path: `which dc29`
2. Note your badge's serial port from Step 3
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

Replace `/dev/tty.usbmodemXXXXX` with your actual port and `/usr/local/bin/dc29` with the output of `which dc29`.

4. Load the agent:
```bash
launchctl load ~/Library/LaunchAgents/com.local.dc29-teams-mute.plist
```

Check the logs: `tail -f /tmp/dc29-teams-mute.log`

---

## You're Done

The badge is running. LED 4 reflects your Teams state. Buttons 1–4 send keystrokes.

Next steps:
- [Customize your button keymaps →](customizing.md)
- [Learn the TUI dashboard →](tui-guide.md)
- [Troubleshoot problems →](faq.md)
