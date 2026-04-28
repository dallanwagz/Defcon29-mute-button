# Teams Mute Indicator — Setup Guide

End-to-end setup for the DC29 badge as a Microsoft Teams mute-state indicator.
The badge button toggles Teams mute via a normal `[ctrl][shift]m` macro (set
through the serial console), and the badge's LED 4 reflects the **actual**
Teams mute state — green when the mic is open, red when muted, off when not
in a meeting. State is reported back from Teams over its Local API, so the
LED stays correct regardless of how you toggled (badge button, Teams UI,
keyboard shortcut, push-to-talk, etc.).

## What's in the build

The firmware running on the badge (already flashed) listens on USB CDC for a
two-byte status command:

| Bytes        | Effect                          |
|--------------|---------------------------------|
| `0x01` `'M'` | LED 4 → red (muted)             |
| `0x01` `'U'` | LED 4 → green (unmuted)         |
| `0x01` `'X'` | LED 4 → off (cleared / no mtg)  |

`0x01` is reserved as the escape prefix; it's never produced by macro entry
or menu navigation, so this side-channel is safe to run while you're also
using the macro editor interactively.

LEDs 1–3 are unaffected by the indicator and continue to work normally
(including the press-flash that briefly turns them white when their button
fires a macro).

## Prerequisites (do these on the Mac)

### 1. Enable Teams Local API

Open Teams desktop client → **Settings** → **Privacy** → **Manage API**.
Toggle on **"Enable third-party API"** (the label has changed across Teams
versions — also seen as "Third-party app permission" or "Allow API"). Save
and restart Teams if prompted.

If you don't see that setting:
- Confirm Teams version 1.6.x or newer (Help → About).
- Some corporate tenants block the local API via admin policy. Check with
  your IT admin if the toggle is missing or greyed out.

### 2. Install Python dependencies

```bash
python3 -m pip install websockets pyserial
```

(Python 3.10+ recommended. macOS ships with `python3` preinstalled.)

### 3. Find the badge's serial port

Plug the badge in and run:

```bash
ls /dev/tty.usbmodem*
```

The badge appears as something like `/dev/tty.usbmodem14201`. The exact
suffix changes between USB ports / reboots — re-check after replug.

### 4. Clone or pull this repo on the Mac

```bash
git clone https://github.com/dallanwagz/Defcon29-mute-button.git
cd Defcon29-mute-button
git checkout playground
```

(Or `git pull` if already cloned.)

## First run (pairing)

```bash
python3 tools/teams_mute_indicator.py --port /dev/tty.usbmodem14201
```

On first connection, **Teams shows a dialog** asking whether to allow
`DC29 / DefconBadgeMacropad / MuteIndicator` to connect. Click **Allow**.
Teams sends a token back, which the script saves to
`~/.dc29_teams_token` for subsequent runs. After that, no dialog —
the script just connects.

If the script logs `Disconnected: ConnectionRefusedError`, the API is not
enabled in Teams (see Prerequisites step 1) or Teams isn't running.

## Test plan

With the script running and the badge plugged in, work through these
scenarios. Each transition should reflect on LED 4 within ~1 second.

| Step | Action                                                  | Expected LED 4   |
|------|---------------------------------------------------------|------------------|
| 1    | Outside any meeting                                     | Off (CLEAR)      |
| 2    | Join a Teams meeting muted                              | Red              |
| 3    | Unmute via Teams UI (click mic icon)                    | Green            |
| 4    | Mute via `Cmd+Shift+M` (Teams' Mac shortcut)            | Red              |
| 5    | Set badge key 4 macro to `[ctrl][shift]m` then press it | Toggles, LED follows actual Teams state |
| 6    | Leave the meeting                                       | Off (CLEAR)      |
| 7    | Unplug + replug badge while script runs                 | Brief error log, then recovers |

Step 5 is the key correctness test: the LED is driven by the script reading
state *from Teams*, not by tracking button presses. So even if the badge
button gets out of sync (push-to-talk, focus loss, click-to-unmute in the
Teams UI, network glitch), the LED still tells you the real state.

> **Note on the Mac shortcut**: Teams uses `Cmd+Shift+M` on macOS. If you
> set the badge to send `[ctrl][shift]m`, that fires Ctrl+Shift+M which
> is the **Windows** Teams shortcut and won't toggle Teams mute on Mac.
> For a Mac-side macro, use `[gui][shift]m` (Cmd+Shift+M).

## Autostart (optional)

To run the script at login on macOS, the simplest path is `launchd`:

1. Save this as `~/Library/LaunchAgents/com.local.dc29-teams-mute.plist`
   (replace `/dev/tty.usbmodemXXXXX` with your badge's port and the script
   path with your actual repo location):

   ```xml
   <?xml version="1.0" encoding="UTF-8"?>
   <!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
   <plist version="1.0">
   <dict>
       <key>Label</key>
       <string>com.local.dc29-teams-mute</string>
       <key>ProgramArguments</key>
       <array>
           <string>/usr/bin/python3</string>
           <string>/Users/YOU/Defcon29-mute-button/tools/teams_mute_indicator.py</string>
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

2. Load it:

   ```bash
   launchctl load ~/Library/LaunchAgents/com.local.dc29-teams-mute.plist
   ```

The `KeepAlive` directive will respawn the script if it crashes. Logs go
to `/tmp/dc29-teams-mute.log` and `/tmp/dc29-teams-mute.err`.

The major fragility here is the COM port path — if you replug into a
different USB port, the device path may change and the launchd job will
fail until you update the plist. A more robust approach is to look up the
port by USB VID/PID inside the Python script, but that's not implemented
yet.

## Troubleshooting

**Script says `Connection refused`**: Teams API isn't enabled, or Teams
isn't running. Check Teams Settings → Privacy → Manage API.

**Script connects but no Teams permission dialog appears**: an older token
in `~/.dc29_teams_token` might already be paired but invalidated.
`rm ~/.dc29_teams_token` and re-run to trigger pairing.

**LED 4 never changes**: confirm the badge is plugged in and the script
log shows `State -> MUTED/UNMUTED/CLEAR` lines on each Teams change.
If the script reports state but LED doesn't update, the badge serial port
might be open in another program (close any serial console that's holding
the port).

**LED 4 stuck on a color when not in a meeting**: the script writes
`CLEAR` on `isInMeeting=false`, but Teams sometimes delays this event.
Leave the meeting cleanly (don't just close the window).

**Permission dialog never appears in Teams**: some Teams builds require
restarting the desktop client after enabling the API. Quit Teams fully
(Cmd+Q) and reopen.
