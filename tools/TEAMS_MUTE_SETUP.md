# Teams Mute Indicator — Setup Guide

End-to-end setup for the DC29 badge as a Microsoft Teams mute-state indicator using the `dc29-badge` Python package.

Button 4 toggles Teams mute and shows the **actual** Teams mute state — green when the mic is open, red when muted, off when not in a meeting. State is read from the Teams Local API, so the LED stays correct regardless of how you toggled (badge button, Teams UI, keyboard shortcut, push-to-talk, etc.).

## Prerequisites

### 1. Install the dc29-badge package

From the repo root:

```bash
pip install -e ".[hotkey]"
```

### 2. Enable Teams Local API

Open Teams desktop → **Settings** → **Privacy** → **Third-party app API** (also seen as "Manage API" or "Allow API" depending on Teams version).

Toggle **Enable third-party API** on. Restart Teams if prompted.

If the toggle is missing or greyed out, your IT admin may have disabled the Local API via tenant policy.

### 3. Kill Elgato Stream Deck (if installed)

Stream Deck connects to the same Teams API port (`localhost:8124`). Only one client is allowed at a time — Stream Deck will block dc29.

```bash
killall "Stream Deck"
```

You'll need to do this each time before running dc29 flow, unless you disable Stream Deck's Teams integration in its settings.

### 4. Clear any stale token and Teams API device entry

If you've connected before and need to re-pair:

```bash
rm ~/.dc29_teams_token
```

Then in Teams → Settings → Privacy → Third-party app API, if **DC29: MuteIndicator** appears in the Allowed or Blocked list, remove it entirely. (Block it first if needed — Teams requires blocking before removing.)

---

## First run (pairing)

**Pairing only works during an active Teams meeting.** The `canPair` permission is `false` when not in a call, so Teams won't show the authorization dialog outside of a meeting.

1. Join a Teams meeting (or start a test call via Calendar → Meet now)
2. Run:
   ```bash
   dc29 flow -v
   ```
3. Watch for a **"New connection request"** popup in Teams: `DC29: MuteIndicator — Allow / Block`
4. Click **Allow**
5. The token is saved to `~/.dc29_teams_token` — subsequent runs connect automatically without needing to be in a meeting

---

## Normal use

```bash
dc29 flow -v
```

Or with the full TUI:

```bash
dc29 start
```

`dc29 flow` runs all bridges concurrently: Teams mute indicator, Slack huddle detection, Outlook email shortcuts, and 15 app-specific shortcut pages. The badge LEDs reflect the active context at all times.

---

## Test plan

With `dc29 flow -v` running and the badge plugged in:

| Step | Action | Expected LED 4 |
|------|--------|----------------|
| 1 | Outside any meeting | Off |
| 2 | Join a Teams meeting muted | Red |
| 3 | Unmute via Teams UI | Green |
| 4 | Mute via Cmd+Shift+M (Teams Mac shortcut) | Red |
| 5 | Press badge Button 4 | Toggles; LED follows actual Teams state |
| 6 | Leave the meeting | Off |

Button 4 sends `toggle-mute` directly to the Teams WebSocket — no HID keymap needed. If badge buttons previously had EEPROM keymaps set, run `dc29 clear-keys` to avoid double-injection.

---

## Troubleshooting

**`timed out during opening handshake`**
Teams API port is held by another process, usually Stream Deck. Run `killall "Stream Deck"` and retry.

**No pairing dialog appears**
- Are you in an active Teams meeting? Pairing only works in-call.
- Is DC29: MuteIndicator still in the Teams Allowed or Blocked list? Remove it entirely, delete `~/.dc29_teams_token`, and retry.
- Is another process holding port 8124? Check with `lsof -i :8124`.

**`Connection refused`**
Teams isn't running, or the Local API isn't enabled (Settings → Privacy → Third-party app API).

**LED 4 correct in Teams but turns off when Outlook is open**
This was a bug (fixed): Teams reconnect cycles were clearing LEDs owned by other bridges. Update to the latest code.

**Button 4 fires Teams mute AND something else**
EEPROM has a keymap stored for button 4. Run `dc29 clear-keys` to zero all keymaps. Use `dc29 diagnose` to confirm they're cleared.

**Pairing dialog appeared but dc29 didn't save the token**
The probe script (`python3 /tmp/teams_probe3.py`) captures the token manually. Save it:
```bash
echo -n "<token-from-probe>" > ~/.dc29_teams_token && chmod 600 ~/.dc29_teams_token
```

---

## Autostart

```bash
dc29 autostart install
```

Installs a launchd agent that starts `dc29 flow` at login. The agent uses the badge's USB serial port (auto-detected by VID/PID). Check status with:

```bash
dc29 autostart status
dc29 autostart logs
```
