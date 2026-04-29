# TUI Guide

← Back to [User Guide](README.md)

The DC29 badge has a terminal user interface (TUI) for interactive configuration and monitoring. Launch it with:

```bash
dc29 ui
```

---

## Main Screen Layout

When you launch the TUI and connect to your badge, you see a dashboard like this:

```
┌─────────────────────────────────────────────────────────────┐
│  DC29 Badge Dashboard                            v1.0.0      │
├──────────────────────┬──────────────────────────────────────┤
│  BUTTONS             │  LED COLORS                          │
│  ┌─────────────────┐ │  ┌──────────────────────────────┐   │
│  │ BTN  MODIFIER  KEY│ │  │ LED  COLOR         HEX       │   │
│  │  1   ctrl+shift m │ │  │  1   [RED   ]      ff0000    │   │
│  │  2   media    mute│ │  │  2   [GREEN ]      00ff00    │   │
│  │  3   shift    ;   │ │  │  3   [BLUE  ]      0000ff    │   │
│  │  4   ctrl+alt m   │ │  │  4   [WHITE ]      7f7f7f    │   │
│  └─────────────────┘ │  └──────────────────────────────┘   │
│                      │                                       │
│  EFFECT MODE         │  MUTE STATE                          │
│  [ off          ↕ ]  │  [ NOT IN MEETING ]                  │
│                      │                                       │
├──────────────────────┴──────────────────────────────────────┤
│  EVENT LOG                                                   │
│  10:45:02  button 2 pressed  (media mute)                   │
│  10:45:07  chord: short — effect mode → rainbow-chase       │
│  10:46:01  mute state: MUTED                                │
│  10:46:08  mute state: UNMUTED                              │
└─────────────────────────────────────────────────────────────┘
│ [Q] Quit  [R] Refresh  [C] Connect  [S] Save               │
└─────────────────────────────────────────────────────────────┘
```

---

## Connecting to the Badge

When the TUI opens, it shows a port selection. Either:
- It auto-detects your badge and connects
- Or it shows a dropdown/input to enter your port path

If the connection fails, check that:
1. The badge is plugged in
2. No other program (like a serial terminal) is holding the port open
3. The port path is correct (`ls /dev/tty.usbmodem*` on macOS)

---

## Buttons Panel

The **BUTTONS** panel shows the current keymap for each of the 4 badge buttons:

| Column | What it shows |
|--------|---------------|
| BTN | Button number (1–4) |
| MODIFIER | Modifier keys (ctrl, shift, alt, gui, media) |
| KEY | The key that's sent |

### Editing a keymap

1. Click (or navigate to) the button row you want to change
2. Press Enter or click the Edit button
3. A dialog appears with fields for modifier and keycode
4. Type the modifier combination (e.g., `ctrl+shift`) and key (e.g., `m`)
5. Press Enter to save — the new keymap is written to EEPROM immediately

The change is saved to the badge's EEPROM and persists across power cycles.

---

## LED Colors Panel

The **LED COLORS** panel shows the current color of each LED. These are the idle colors (what the LED shows when no button is pressed).

### Changing an LED color

1. Click on the LED row you want to change
2. A color picker or R/G/B input appears
3. You can:
   - Type a named color: `red`, `green`, `blue`, `cyan`, `purple`, `orange`, `white`, `off`
   - Type an RGB value: `255,0,128`
4. Press Enter to apply — the LED changes immediately but is **not** saved to EEPROM (RAM only)
5. Click **Save** or press `S` to save to EEPROM

Note: LED 4's color here is overridden by the Teams bridge when a meeting is active. When not running the Teams bridge, LED 4 shows its idle color.

---

## Effect Mode Selector

The **EFFECT MODE** dropdown lets you pick the firmware LED animation:

| Mode | What it looks like |
|------|--------------------|
| `off` | LEDs show their configured idle colors, no animation |
| `rainbow-chase` | One LED lit at a time, cycling through LEDs 1–3, color sweeps through the rainbow |
| `breathe` | All three LEDs (1–3) fade in and out together, slowly shifting color |

Select a mode and it takes effect immediately. The mode is not saved to EEPROM — it resets to `off` on power cycle.

You can also trigger effect cycling physically: hold all 4 buttons for about half a second, then release. This cycles through the modes without opening any software.

---

## Mute State Display

The **MUTE STATE** panel shows what the Teams bridge is currently reporting:

| Display | Meaning |
|---------|---------|
| `NOT IN MEETING` | No active meeting (LED 4 off) |
| `UNMUTED` | In a meeting, mic active (LED 4 green) |
| `MUTED` | In a meeting, mic off (LED 4 red) |
| `DISCONNECTED` | Teams bridge not running |

This panel is read-only — mute state is driven by Teams, not the TUI.

---

## Event Log

The **EVENT LOG** shows real-time events from the badge:

| Event | What triggered it |
|-------|------------------|
| `button N pressed` | You pressed a badge button |
| `chord: short` | All 4 buttons held 300ms–2s, released |
| `chord: long` | All 4 buttons held ≥2s |
| `mute state: X` | Teams bridge reported a new state |
| `effect mode: N` | Effect mode changed (chord or command) |

The log scrolls. Older entries scroll off the top.

---

## Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `Q` | Quit |
| `R` | Refresh — re-query all button keymaps and LED colors |
| `C` | Connect / reconnect to badge |
| `S` | Save current LED colors to EEPROM |
| `Tab` | Move focus between panels |
| `Enter` | Edit the selected item |
| `Esc` | Cancel / close dialog |

---

## Next Steps

- [Customizing keymaps and LED colors in depth →](customizing.md)
- [Troubleshooting →](faq.md)
