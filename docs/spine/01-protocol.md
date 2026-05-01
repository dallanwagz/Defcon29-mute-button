# DC29 Badge — Protocol Reference

> **docs/spine/** is the authoritative source of truth. This document is the ground truth for anyone writing code against the badge.

← Back to [Project Overview](00-overview.md)

## Overview

The badge firmware reserves byte `0x01` as an **escape prefix**. Every protocol message is two or more bytes starting with `0x01`, followed by a single ASCII letter identifying the command or event type, followed by zero or more argument bytes.

`0x01` never appears in normal serial-console traffic (interactive menu input, macro entry), so protocol commands can be safely injected while the console is also open.

**Transport:** USB CDC serial port, 9600 baud, 8N1.

**Direction convention:**
- **Host → Badge**: commands sent by the Python host to the badge
- **Badge → Host**: events emitted by the badge to the Python host

---

## Host → Badge Commands

### `0x01 M` — Set LED 4 Muted (red)

| Byte | Value | Description |
|------|-------|-------------|
| 0 | `0x01` | Escape prefix |
| 1 | `0x4D` (`'M'`) | Command byte |

Sets LED 4 to full red (`255, 0, 0`). Indicates microphone is muted.

**Example byte sequence:** `01 4D`

---

### `0x01 U` — Set LED 4 Unmuted (green)

| Byte | Value | Description |
|------|-------|-------------|
| 0 | `0x01` | Escape prefix |
| 1 | `0x55` (`'U'`) | Command byte |

Sets LED 4 to full green (`0, 255, 0`). Indicates microphone is active.

**Example byte sequence:** `01 55`

---

### `0x01 X` — Clear LED 4 (off)

| Byte | Value | Description |
|------|-------|-------------|
| 0 | `0x01` | Escape prefix |
| 1 | `0x58` (`'X'`) | Command byte |

Turns LED 4 off (`0, 0, 0`). Indicates not in a meeting or status unknown.

**Example byte sequence:** `01 58`

---

### `0x01 K n mod key` — Set Button Keymap

| Byte | Value | Description |
|------|-------|-------------|
| 0 | `0x01` | Escape prefix |
| 1 | `0x4B` (`'K'`) | Command byte |
| 2 | `n` | Button number: 1–4 (buttons), 5–6 (slider) |
| 3 | `mod` | HID modifier byte (see [Modifier Bytes](#hid-modifier-bytes)) |
| 4 | `key` | HID keycode (see [Keycodes](#hid-keycodes)) |

Writes a single-key macro for button `n` directly to EEPROM. The previous multi-key chain for that button is replaced with a single `[mod, key]` pair.

The badge responds with `EVT_KEY_ACK` (`0x01 A n`).

**Notes:**
- Setting `mod = 0xF0` (media key) with a consumer-control `key` sends a media event rather than a keyboard event.
- Changes persist across power cycles (EEPROM).

**Example:** Set button 1 to Ctrl+Shift+M (Windows Teams mute):
```
01 4B 01 03 10
```
- `03` = `MOD_CTRL | MOD_SHIFT`
- `10` = HID keycode for `m`

---

### `0x01 Q n` — Query Button Keymap

| Byte | Value | Description |
|------|-------|-------------|
| 0 | `0x01` | Escape prefix |
| 1 | `0x51` (`'Q'`) | Command byte |
| 2 | `n` | Button number: 1–6 |

Requests the current keymap for button `n`. The badge responds with `EVT_KEY_REPLY` (`0x01 R n mod key`).

**Example byte sequence (query button 4):** `01 51 04`

---

### `0x01 L n r g b` — Set LED Color (RAM)

| Byte | Value | Description |
|------|-------|-------------|
| 0 | `0x01` | Escape prefix |
| 1 | `0x4C` (`'L'`) | Command byte |
| 2 | `n` | LED number: 1–4 |
| 3 | `r` | Red component 0–255 |
| 4 | `g` | Green component 0–255 |
| 5 | `b` | Blue component 0–255 |

Sets the color of LED `n` immediately. **Not saved to EEPROM** — color reverts to EEPROM value on next power cycle. Used for idle animations and the mute-state indicator.

**Example:** Set LED 2 to cyan (`0, 200, 255`):
```
01 4C 02 00 C8 FF
```

**Timing note:** The badge applies the color immediately in the main loop on the next `updateSerialConsole()` call (~1 ms latency). Do not send L commands faster than every 10 ms; the serial buffer is small.

---

### `0x01 F v` — Button Flash Enable/Disable

| Byte | Value | Description |
|------|-------|-------------|
| 0 | `0x01` | Escape prefix |
| 1 | `0x46` (`'F'`) | Command byte |
| 2 | `v` | `0x00` = disable, `0x01` = enable |

Enables or disables the brief white LED flash that occurs when a button is pressed. **RAM only** — resets to enabled on power cycle.

Default state: **enabled**.

**Example (disable flash):** `01 46 00`

---

### `0x01 E n` — Set LED Effect Mode

| Byte | Value | Description |
|------|-------|-------------|
| 0 | `0x01` | Escape prefix |
| 1 | `0x45` (`'E'`) | Command byte |
| 2 | `n` | Effect mode: `0` = off, `1` = rainbow-chase, `2` = breathe |

Sets the firmware-driven LED effect mode. The mode value is taken modulo 3, so values > 2 wrap around.

When `n > 0`, the firmware animates all four LEDs internally. Python-side idle animations should be suppressed to avoid conflicting LED writes. The badge emits `EVT_EFFECT_MODE` when the mode changes.

**Effect modes:**
- `0` — Off: all four LEDs return to their EEPROM resting colors
- `1` — Rainbow chase: one LED lit at a time, cycling through LEDs 1–4, hue advances 16 steps per cycle (step interval: 150 ms)
- `2` — Breathe: all four LEDs fade in and out together with slow hue drift (step interval: 8 ms)

Bridges that need exclusive control of an LED (e.g. Teams toggle-mute on LED 4, FocusBridge while a target app has focus) must suspend the effect by sending `0x01 'E' 0` while they hold ownership and restore the prior mode when they release. See `dc29/bridges/teams.py` and `dc29/bridges/focus.py` for the save/restore pattern.

**Example (enable breathe):** `01 45 02`

---

## Badge → Host Events

### `0x01 B n mod key` — Button Pressed

| Byte | Value | Description |
|------|-------|-------------|
| 0 | `0x01` | Escape prefix |
| 1 | `0x42` (`'B'`) | Event byte |
| 2 | `n` | Button number: 1–4 |
| 3 | `mod` | HID modifier byte that was sent |
| 4 | `key` | HID keycode that was sent |

Emitted after the debounce window (200 ms) when button `n` is pressed and a HID report is sent. The `mod` and `key` fields reflect the first keymap entry for that button (even if the keymap contains multiple entries).

**Example (button 2 pressed, sends media mute):** `01 42 02 F0 20`

---

### `0x01 R n mod key` — Query Reply

| Byte | Value | Description |
|------|-------|-------------|
| 0 | `0x01` | Escape prefix |
| 1 | `0x52` (`'R'`) | Event byte |
| 2 | `n` | Button number that was queried |
| 3 | `mod` | HID modifier byte stored in EEPROM |
| 4 | `key` | HID keycode stored in EEPROM |

Response to a `CMD_QUERY_KEY` (`0x01 Q n`) request.

**Example (button 1 is set to Ctrl+Shift+M):** `01 52 01 03 10`

---

### `0x01 A n` — ACK (Keymap Set)

| Byte | Value | Description |
|------|-------|-------------|
| 0 | `0x01` | Escape prefix |
| 1 | `0x41` (`'A'`) | Event byte |
| 2 | `n` | Button number whose keymap was updated |

Acknowledgement sent after a `CMD_SET_KEY` (`0x01 K n mod key`) command completes and the EEPROM write commits.

**Example (button 3 keymap updated):** `01 41 03`

---

### `0x01 V n` — Effect Mode Changed

| Byte | Value | Description |
|------|-------|-------------|
| 0 | `0x01` | Escape prefix |
| 1 | `0x56` (`'V'`) | Event byte |
| 2 | `n` | New effect mode: `0`, `1`, or `2` |

Emitted when the firmware's effect mode changes — either from a `CMD_SET_EFFECT` command or from a chord gesture. The Python host should use this to synchronize its idle-animation authorization state.

**Example (mode set to rainbow-chase):** `01 56 01`

---

### `0x01 C n` — Chord Fired

| Byte | Value | Description |
|------|-------|-------------|
| 0 | `0x01` | Escape prefix |
| 1 | `0x43` (`'C'`) | Event byte |
| 2 | `n` | Chord type: `1` = short, `2` = long |

Emitted when the user fires a 4-button chord gesture (see [Chord Gestures](#chord-gestures)).

**Example (long chord):** `01 43 02`

---

## Chord Gestures

Holding all four buttons simultaneously triggers firmware effects without requiring a USB connection.

| Gesture | Description | Firmware action | Serial event |
|---------|-------------|-----------------|--------------|
| Short chord | All 4 buttons held 300 ms – 2 s, then released | Cycles effect mode: `(current + 1) % 3` | `0x01 V n`, then `0x01 C 1` |
| Long chord | All 4 buttons held ≥ 2 s | Resets effect mode to 0 immediately | `0x01 V 0`, then `0x01 C 2` |

**Implementation detail:** While any chord is pending, individual button press flags are cleared so no HID keystrokes fire. The chord timer starts when all four buttons are simultaneously detected low. The long chord fires while the buttons are still held; the short chord fires on release.

---

## HID Modifier Bytes

The modifier byte is a bitmask of the following flags:

| Constant | Value | Meaning |
|----------|-------|---------|
| `MOD_CTRL` | `0x01` | Left Control |
| `MOD_SHIFT` | `0x02` | Left Shift |
| `MOD_ALT` | `0x04` | Left Alt |
| `MOD_GUI` | `0x08` | Left GUI (Windows key / Cmd) |
| `MOD_CTRL_SHIFT` | `0x03` | Control + Shift |
| `MOD_CTRL_ALT` | `0x05` | Control + Alt |
| `MOD_CTRL_GUI` | `0x09` | Control + GUI |
| `MOD_SHIFT_ALT` | `0x06` | Shift + Alt |
| `MOD_SHIFT_GUI` | `0x0A` | Shift + GUI |
| `MOD_ALT_GUI` | `0x0C` | Alt + GUI |
| `MOD_CTRL_SHIFT_ALT` | `0x07` | Control + Shift + Alt |
| `MOD_CTRL_SHIFT_GUI` | `0x0B` | Control + Shift + GUI |
| `MOD_CTRL_ALT_GUI` | `0x0D` | Control + Alt + GUI |
| `MOD_SHIFT_ALT_GUI` | `0x0E` | Shift + Alt + GUI |
| `MOD_CTRL_SHIFT_ALT_GUI` | `0x0F` | All four |
| `MOD_MEDIA` | `0xF0` | Special: media / consumer-control key |

When `mod = 0xF0`, the `key` byte is a USB HID consumer-control usage ID rather than a standard keyboard keycode. The badge sends a consumer-control report instead of a keyboard report.

---

## HID Keycodes (Common)

Standard keyboard keycodes follow the USB HID specification (Usage Page 0x07):

| Keycode | Value | Keycode | Value |
|---------|-------|---------|-------|
| `a` | `0x04` | `z` | `0x1D` |
| `1` | `0x1E` | `0` | `0x27` |
| `enter` | `0x28` | `esc` | `0x29` |
| `backspace` | `0x2A` | `tab` | `0x2B` |
| `space` | `0x2C` | `f1` | `0x3A` |
| `f2` | `0x3B` | `f12` | `0x45` |
| `right` | `0x4F` | `left` | `0x50` |
| `down` | `0x51` | `up` | `0x52` |
| `home` | `0x4A` | `end` | `0x4D` |
| `page_up` | `0x4B` | `page_down` | `0x4E` |
| `delete` | `0x4C` | | |

**Letters a–z map to `0x04`–`0x1D`.** To find any letter's keycode: `0x04 + (ord(letter) - ord('a'))`.

### Media Keycodes (consumer-control, `mod = 0xF0`)

| Name | Value |
|------|-------|
| `mute` | `0xE2` |
| `vol_up` | `0xE9` |
| `vol_down` | `0xEA` |
| `play_pause` | `0xCD` |
| `next_track` | `0xB5` |
| `prev_track` | `0xB6` |

---

## Keymap Format (Internal / EEPROM)

The full keymap is stored in EEPROM starting at offset `EEP_KEY_MAP` (offset 26) as a packed byte array.

```
[length_byte] [button1_sentinel] [mod] [key] [mod] [key] ... 
              [button2_sentinel] [mod] [key] ...
              ...
```

Sentinel bytes mark the start of each button's entries:

| Sentinel | Button |
|----------|--------|
| `250` (`0xFA`) | Button 1 |
| `251` (`0xFB`) | Button 2 |
| `252` (`0xFC`) | Button 3 |
| `253` (`0xFD`) | Button 4 |
| `254` (`0xFE`) | Slider up |
| `255` (`0xFF`) | Slider down |

The `CMD_SET_KEY` protocol command (`0x01 K`) always sets a single `[mod, key]` pair per button, discarding any previous multi-key chain. The EEPROM keymap supports multiple `[mod, key]` pairs per button for complex macros — these can only be written by constructing the full keymap byte array directly.

### Default Keymap

```c
{
    21,                    // total length
    250, 3, 16,            // button 1: Ctrl+Shift+M (Windows Teams mute)
    251, 240, 32,          // button 2: media mute key
    252, 2, 51, 2, 39,     // button 3: :) — Shift+; then Shift+0
    253, 5, 16,            // button 4: Ctrl+Alt+M
    254, 240, 64,          // slider up: volume up
    255, 240, 128          // slider down: volume down
}
```

---

## Protocol State Machine (Host Parser)

The host parser must maintain a state machine to decode multi-byte messages:

```
State 0 (IDLE):
    receive 0x01 → go to State 1

State 1 (GOT_ESCAPE):
    receive cmd byte → store cmd, go to State 2 or dispatch immediately
    'M', 'U', 'X' → dispatch immediately, back to State 0
    'K' → need 3 more bytes, go to State 2
    'Q' → need 1 more byte, go to State 2
    'L' → need 4 more bytes, go to State 2
    'F' → need 1 more byte, go to State 2
    'E' → need 1 more byte, go to State 2
    'B' → need 3 more bytes, go to State 2
    'R' → need 3 more bytes, go to State 2
    'A' → need 1 more byte, go to State 2
    'V' → need 1 more byte, go to State 2
    'C' → need 1 more byte, go to State 2
    unknown → back to State 0

State 2 (COLLECTING_ARGS):
    accumulate arg bytes until count reached
    dispatch complete message, back to State 0
```

The reference implementation is in `tools/teams_mute_indicator.py` (`BadgeWriter._parse_rx`) and the firmware in `Firmware/Source/DC29/src/serialconsole.c`.

---

## Platform-Specific Notes

### macOS Teams shortcut

Teams on macOS uses `Cmd+Shift+M` to toggle mute. The badge must be configured with:
- modifier: `0x0A` (`MOD_SHIFT_GUI`)
- keycode: `0x10` (`m`)

The Windows shortcut `Ctrl+Shift+M` (modifier `0x03`, keycode `0x10`) does **not** work on macOS Teams.

### Serial port names

| Platform | Pattern | Example |
|----------|---------|---------|
| macOS | `/dev/tty.usbmodem*` | `/dev/tty.usbmodem14201` |
| Linux | `/dev/ttyACM*` | `/dev/ttyACM0` |
| Windows | `COM*` | `COM3` |

The port suffix changes between USB ports and power cycles on macOS. Always re-check with `ls /dev/tty.usbmodem*` after replug.
