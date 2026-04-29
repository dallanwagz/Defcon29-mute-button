# Customizing Your Badge

← Back to [User Guide](README.md)

## Button Keymaps

Each of the 4 buttons can be set to send any keyboard shortcut or media key. Changes are saved to the badge's EEPROM and persist across power cycles and unplugging.

### Using the CLI

```bash
dc29 set-key BUTTON MODIFIER KEYCODE --port PORT
```

Examples:

```bash
# Button 1: Ctrl+Shift+M (Teams mute, Windows)
dc29 set-key 1 0x03 0x10 --port /dev/tty.usbmodem14201

# Button 1: Cmd+Shift+M (Teams mute, macOS)
dc29 set-key 1 0x0A 0x10 --port /dev/tty.usbmodem14201

# Button 2: Media mute key (hardware mute — works in any app)
dc29 set-key 2 0xF0 0xE2 --port /dev/tty.usbmodem14201

# Button 3: Volume up
dc29 set-key 3 0xF0 0xE9 --port /dev/tty.usbmodem14201

# Button 4: Play/Pause
dc29 set-key 4 0xF0 0xCD --port /dev/tty.usbmodem14201
```

### Using the TUI

```bash
dc29 ui
```

Navigate to the Buttons panel, select the button to change, press Enter, and type the new mapping.

### View current keymaps

```bash
dc29 info --port /dev/tty.usbmodem14201
```

---

## Modifier Reference

| What you want | Value | Notes |
|---------------|-------|-------|
| No modifier | `0x00` | Just the key |
| Ctrl | `0x01` | Left Control |
| Shift | `0x02` | Left Shift |
| Alt | `0x04` | Left Alt |
| Cmd / Win | `0x08` | Left GUI (Cmd on Mac, Windows key on PC) |
| Ctrl+Shift | `0x03` | Windows Teams mute |
| Ctrl+Alt | `0x05` | |
| Shift+Cmd | `0x0A` | macOS Teams mute |
| Media key | `0xF0` | Use with media keycodes below |

---

## Common Keycodes

### Letters

Letters `a`–`z` map to `0x04`–`0x1D`. To find any letter: `0x04 + position in alphabet (0-based)`.

| Letter | Code | Letter | Code |
|--------|------|--------|------|
| a | `0x04` | m | `0x10` |
| b | `0x05` | n | `0x11` |
| c | `0x06` | z | `0x1D` |

### Numbers and special keys

| Key | Code |
|-----|------|
| 1–9 | `0x1E`–`0x26` |
| 0 | `0x27` |
| Enter | `0x28` |
| Escape | `0x29` |
| Space | `0x2C` |
| F1–F12 | `0x3A`–`0x45` |
| Up/Down/Left/Right | `0x52`/`0x51`/`0x50`/`0x4F` |

### Media keycodes (use with modifier `0xF0`)

| Action | Code |
|--------|------|
| Mute microphone | `0xE2` |
| Volume up | `0xE9` |
| Volume down | `0xEA` |
| Play/Pause | `0xCD` |
| Next track | `0xB5` |
| Previous track | `0xB6` |

---

## LED Colors

### Change a button's LED color (via CLI)

```bash
dc29 set-led 1 255 0 0 --port /dev/tty.usbmodem14201   # red
dc29 set-led 2 0 255 0 --port /dev/tty.usbmodem14201   # green
dc29 set-led 3 0 0 255 --port /dev/tty.usbmodem14201   # blue
dc29 set-led 4 160 0 255 --port /dev/tty.usbmodem14201 # purple
```

**Note:** LED colors set via CLI or TUI are RAM-only — they reset to EEPROM values on power cycle unless you save them. Use the TUI's Save function or see [developer docs](../developer/api-reference.md) for EEPROM color saving.

### Named colors

The CLI accepts named colors as well as RGB values:

```bash
dc29 set-led 1 red --port /dev/tty.usbmodem14201
dc29 set-led 2 cyan --port /dev/tty.usbmodem14201
dc29 set-led 3 purple --port /dev/tty.usbmodem14201
```

Available names: `red`, `green`, `blue`, `white`, `cyan`, `purple`, `orange`, `yellow`, `off`

---

## LED Effect Modes

### Cycle effects with a button chord

Hold all 4 buttons simultaneously for about half a second, then release. The effect cycles:
- off → rainbow-chase → breathe → off → ...

Hold all 4 buttons for 2 seconds or longer to reset back to off immediately.

### Set effect via CLI

```bash
dc29 set-effect 0 --port /dev/tty.usbmodem14201   # off
dc29 set-effect 1 --port /dev/tty.usbmodem14201   # rainbow-chase
dc29 set-effect 2 --port /dev/tty.usbmodem14201   # breathe
```

**Note:** Effect mode is not saved to EEPROM — it resets to off on power cycle.

---

## Default Keymap

The badge ships with these defaults:

| Button | Keymap | What it does |
|--------|--------|-------------|
| 1 | Ctrl+Shift+M | Windows Teams mute toggle |
| 2 | Media mute | Hardware microphone mute (works in any app) |
| 3 | `:)` (Shift+; then Shift+0) | Types a smiley face |
| 4 | Ctrl+Alt+M | Legacy Teams shortcut |
| Slider up | Volume up | |
| Slider down | Volume down | |

To reset to defaults:

```bash
# Not yet a direct CLI command — use the TUI or reflash firmware
dc29 ui
# In the TUI: use Reset to Defaults option
```
