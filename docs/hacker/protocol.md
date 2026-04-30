# Protocol Reference (Hacker Edition)

← Back to [Hacker Guide](README.md)

This is the full byte-level protocol reference. The firmware implementation is in `Firmware/Source/DC29/src/serialconsole.c`.

---

## Transport

- **Interface:** USB CDC serial (device side: SAMD21 USB CDC class)
- **Baud rate:** 9600 (baud rate is technically irrelevant for USB CDC, but the host must match)
- **Escape byte:** `0x01` — never appears in normal menu traffic

## Message Format

All messages: `[0x01] [CMD_BYTE] [0 or more argument bytes]`

## Host → Badge Commands

| Sequence | Args | Description |
|----------|------|-------------|
| `01 4D` | none | LED 4 → red (muted) |
| `01 55` | none | LED 4 → green (unmuted) |
| `01 58` | none | LED 4 → off |
| `01 4B n m k` | 3 | Set button `n` keymap: modifier `m`, keycode `k` |
| `01 51 n` | 1 | Query button `n` keymap |
| `01 4C n r g b` | 4 | Set LED `n` resting color to (r,g,b) — RAM only, survives takeover animation |
| `01 46 v` | 1 | Button flash: `v=1` enable, `v=0` disable |
| `01 45 n` | 1 | Set effect mode: 0=off 1=rainbow-chase 2=breathe |

## Badge → Host Events

| Sequence | Args | Description |
|----------|------|-------------|
| `01 42 n m k` | 3 | Button `n` pressed; modifier=`m`, keycode=`k` |
| `01 52 n m k` | 3 | Query reply for button `n`; modifier=`m`, keycode=`k` |
| `01 41 n` | 1 | ACK: keymap set for button `n` |
| `01 56 n` | 1 | Effect mode changed to `n` |
| `01 43 n` | 1 | Chord: `n=1` short, `n=2` long |

## Chord Timings

- Short: all 4 buttons held 300–2000 ms, released
- Long: all 4 buttons held ≥ 2000 ms (fires while held)

## HID Modifier Byte

| Bit | Mask | Modifier |
|-----|------|---------|
| 0 | `0x01` | Left Ctrl |
| 1 | `0x02` | Left Shift |
| 2 | `0x04` | Left Alt |
| 3 | `0x08` | Left GUI |
| 4-7 | `0xF0` | Media key (special: entire byte = `0xF0`) |

When `modifier == 0xF0`, the keycode is a USB HID consumer-control usage ID.

## Common Media Keycodes

| Code | Action |
|------|--------|
| `0xE2` | Mute |
| `0xE9` | Vol+ |
| `0xEA` | Vol− |
| `0xCD` | Play/Pause |
| `0xB5` | Next track |
| `0xB6` | Prev track |

## EEPROM Keymap Format

Stored at offset 26, packed:

```
[total_length] [sentinel] [mod] [key] [mod] [key] ... [sentinel] ...
```

Sentinels: `0xFA`=btn1, `0xFB`=btn2, `0xFC`=btn3, `0xFD`=btn4, `0xFE`=slider+, `0xFF`=slider−

The `K` command always replaces the entire button's chain with a single `[mod, key]` pair.

## Parser State Machine (Firmware)

```c
// escape_state values:
// 0 = idle (waiting for 0x01)
// 1 = got 0x01, waiting for command byte
// 2 = collecting argument bytes

if (escape_state == 1) {
    // dispatch immediately or set args_needed
}
if (escape_state == 2) {
    escape_args[count++] = data;
    if (count == args_needed) dispatch();
}
if (data == 0x01) escape_state = 1;
```

See `Firmware/Source/DC29/src/serialconsole.c` for the full implementation.

Full protocol documentation with examples: [docs/spine/01-protocol.md](../spine/01-protocol.md)
