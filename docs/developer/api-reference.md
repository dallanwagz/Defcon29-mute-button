# BadgeAPI Reference

← Back to [Developer Guide](README.md)

The primary Python API lives in `tools/teams_mute_indicator.py`. The protocol constants are in `dc29/protocol.py`.

---

## `dc29.protocol` — Constants Module

`dc29/protocol.py` is a pure-Python, import-safe constants module. No I/O, no side effects.

### Escape Byte

```python
ESCAPE: int = 0x01
```

The byte that prefixes every badge protocol message.

### Command Constants (Host → Badge)

| Constant | Value | Description |
|----------|-------|-------------|
| `CMD_MUTED` | `0x4D` (`'M'`) | Set LED 4 red |
| `CMD_UNMUTED` | `0x55` (`'U'`) | Set LED 4 green |
| `CMD_CLEAR` | `0x58` (`'X'`) | Turn LED 4 off |
| `CMD_SET_KEY` | `0x4B` (`'K'`) | Write keymap to EEPROM |
| `CMD_QUERY_KEY` | `0x51` (`'Q'`) | Query keymap |
| `CMD_SET_LED` | `0x4C` (`'L'`) | Set LED color (RAM) |
| `CMD_BUTTON_FLASH` | `0x46` (`'F'`) | Enable/disable button flash |
| `CMD_SET_EFFECT` | `0x45` (`'E'`) | Set LED effect mode |

### Event Constants (Badge → Host)

| Constant | Value | Description |
|----------|-------|-------------|
| `EVT_BUTTON` | `0x42` (`'B'`) | Button pressed |
| `EVT_KEY_REPLY` | `0x52` (`'R'`) | Reply to Q query |
| `EVT_KEY_ACK` | `0x41` (`'A'`) | ACK after K command |
| `EVT_EFFECT_MODE` | `0x56` (`'V'`) | Effect mode changed |
| `EVT_CHORD` | `0x43` (`'C'`) | Chord fired |

### Enums

```python
class MuteState(IntEnum):
    NOT_IN_MEETING = 0
    UNMUTED = 1
    MUTED = 2

class EffectMode(IntEnum):
    OFF = 0
    RAINBOW_CHASE = 1
    BREATHE = 2
```

### HID Modifier Constants

```python
MOD_CTRL       = 0x01   # Left Control
MOD_SHIFT      = 0x02   # Left Shift
MOD_ALT        = 0x04   # Left Alt
MOD_GUI        = 0x08   # Left GUI (Win key / Cmd)
MOD_CTRL_SHIFT = 0x03   # Control + Shift
MOD_SHIFT_GUI  = 0x0A   # Shift + GUI (macOS Teams mute)
MOD_MEDIA      = 0xF0   # Media / consumer-control key
# ... (see protocol.py for full list)
```

### Helper Functions

#### `parse_color(s: str) -> Color`

Parse a color string into `(r, g, b)`:

```python
from dc29.protocol import parse_color

parse_color("cyan")          # (0, 200, 255)
parse_color("255,80,0")      # (255, 80, 0)
parse_color("red")           # (255, 0, 0)
```

Raises `ValueError` for unrecognized input.

#### `modifier_name(mod: int) -> str`

```python
from dc29.protocol import modifier_name

modifier_name(0x03)   # "ctrl+shift"
modifier_name(0x0A)   # "shift+gui"
modifier_name(0xF0)   # "media"
```

#### `keycode_name(kc: int, mod: int = 0) -> str`

```python
from dc29.protocol import keycode_name

keycode_name(0x10)          # "m"
keycode_name(0xE2, 0xF0)    # "mute"
keycode_name(0x28)          # "enter"
```

---

## `BadgeWriter` Class

`BadgeWriter` in `tools/teams_mute_indicator.py` is the serial port abstraction.

### Constructor

```python
BadgeWriter(port_name: str, brightness: float = 1.0)
```

| Parameter | Type | Description |
|-----------|------|-------------|
| `port_name` | `str` | Serial port path, e.g. `/dev/tty.usbmodem14201` |
| `brightness` | `float` | LED brightness scale, 0.0–1.0, applied to all `set_led` calls |

The constructor does **not** open the serial port. The port opens lazily on the first write call.

### Properties / Callbacks

```python
badge.on_button4_press: Callable[[], None] | None
badge.on_effect_mode:   Callable[[int], None] | None
badge.on_chord_long:    Callable[[], None] | None
```

These are called from the **reader thread**. Use `loop.call_soon_threadsafe()` if you need to interact with an asyncio event loop:

```python
import asyncio

loop = asyncio.get_running_loop()
badge.on_button4_press = lambda: loop.call_soon_threadsafe(
    my_queue.put_nowait, "button4"
)
badge.on_effect_mode = lambda mode: loop.call_soon_threadsafe(
    effect_queue.put_nowait, mode
)
```

### Methods

#### `write(cmd: bytes) -> None`

Send raw bytes to the badge. Deduplicates: if `cmd` is identical to the last call, it is a no-op.

```python
badge.write(bytes([0x01, ord('M')]))   # muted
badge.write(b"\x01U")                  # unmuted
```

#### `set_led(n: int, r: int, g: int, b: int) -> None`

Set LED `n` (1–4) to color `(r, g, b)`. Brightness scaling is applied.

```python
badge.set_led(1, 255, 0, 0)    # LED 1 red
badge.set_led(4, 0, 200, 0)    # LED 4 green
badge.set_led(2, 0, 0, 0)      # LED 2 off
```

**Not saved to EEPROM.**

#### `set_keymap(button: int, modifier: int, keycode: int) -> None`

Write a single-key macro for button `button` (1–6) to EEPROM.

```python
badge.set_keymap(1, 0x03, 0x10)   # button 1: Ctrl+Shift+M
badge.set_keymap(2, 0xF0, 0xE2)   # button 2: media mute
```

The badge responds with ACK (`0x01 A n`), logged to stderr.

#### `query_keymap(button: int) -> None`

Ask the badge for the current keymap of button `button`. Response is logged.

```python
badge.query_keymap(4)   # logs: "Badge button 4 keymap: modifier=0x05 keycode=0x10"
```

---

## `LedAnimator` Class

Drives LED animation patterns as asyncio tasks. Must be used inside a running asyncio event loop.

### Constructor

```python
LedAnimator(badge: BadgeWriter)
```

### Methods

#### `start_chase(color=(0, 100, 255), speed_ms=150, leds=(1, 2, 3)) -> None`

Start a chase animation: one LED lit at a time, cycling through `leds`.

```python
animator.start_chase(color=(0, 200, 255), speed_ms=100)
```

#### `start_rainbow_chase(speed_ms=150, leds=(1, 2, 3)) -> None`

Chase with hue advancing through the full spectrum each step.

```python
animator.start_rainbow_chase(speed_ms=200)
```

#### `start_solid(color=(0, 100, 255), leds=(1, 2, 3)) -> None`

Set all specified LEDs to the same static color (synchronous, no task).

```python
animator.start_solid(color=(160, 0, 255))
```

#### `stop(leds=(1, 2, 3)) -> None`

Cancel the running animation and turn off the specified LEDs.

```python
animator.stop()
```

### Example

```python
import asyncio
from tools.teams_mute_indicator import BadgeWriter, LedAnimator

async def main():
    badge = BadgeWriter("/dev/tty.usbmodem14201")
    animator = LedAnimator(badge)

    animator.start_rainbow_chase(speed_ms=150)
    await asyncio.sleep(5)
    animator.stop()

asyncio.run(main())
```

---

## `supervise()` Function

Top-level async function that runs the Teams bridge with automatic reconnection.

```python
async def supervise(
    port_name: str,
    toggle_hotkey: str | None,
    idle_animation: str | None = None,
    idle_color: Color = (0, 200, 255),
    idle_speed: int = 150,
    brightness: float = 1.0,
    button_flash: bool = True,
    effects: bool = True,
) -> None
```

| Parameter | Description |
|-----------|-------------|
| `port_name` | Serial port path |
| `toggle_hotkey` | pynput hotkey string like `"<ctrl>+<alt>+m"`, or `None` to disable |
| `idle_animation` | `"chase"`, `"rainbow"`, or `None` |
| `idle_color` | RGB tuple for idle animation color |
| `idle_speed` | Animation step interval in ms |
| `brightness` | LED brightness 0.0–1.0 |
| `button_flash` | Whether to send the button press white flash |
| `effects` | Whether Python idle animations are authorized |

This function never returns normally — it loops forever reconnecting to Teams.

---

## `run_once()` Function

Single WebSocket connection lifecycle:

```python
async def run_once(
    badge: BadgeWriter,
    toggle_queue: asyncio.Queue,
    tracker: _MeetingTracker,
    animator: LedAnimator | None = None,
    idle_animation: str | None = None,
    idle_color: Color = (0, 200, 255),
    idle_speed: int = 150,
    effects_queue: asyncio.Queue | None = None,
    effects_enabled: list[bool] | None = None,
) -> None
```

Use this if you want finer control than `supervise()` provides.
