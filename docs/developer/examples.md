# Code Examples

← Back to [Developer Guide](README.md)

All examples assume the badge is connected at the specified serial port. Adjust the port for your system.

---

## Example 1: Blink LED 4 Three Times

```python
#!/usr/bin/env python3
"""Blink LED 4 red three times."""
import time
import serial

PORT = "/dev/tty.usbmodem14201"

with serial.Serial(PORT, 9600) as s:
    for _ in range(3):
        s.write(b"\x01M")   # red
        time.sleep(0.3)
        s.write(b"\x01X")   # off
        time.sleep(0.3)

print("Done")
```

---

## Example 2: Color Cycle All LEDs

```python
#!/usr/bin/env python3
"""Cycle all 4 LEDs through a color sequence."""
import time
import serial

PORT = "/dev/tty.usbmodem14201"

COLORS = [
    (255, 0, 0),    # red
    (0, 255, 0),    # green
    (0, 0, 255),    # blue
    (255, 165, 0),  # orange
    (160, 0, 255),  # purple
    (0, 200, 255),  # cyan
    (255, 255, 0),  # yellow
    (0, 0, 0),      # off
]

def set_led(s, n: int, r: int, g: int, b: int):
    s.write(bytes([0x01, ord('L'), n, r, g, b]))

with serial.Serial(PORT, 9600) as s:
    for r, g, b in COLORS:
        for led in (1, 2, 3, 4):
            set_led(s, led, r, g, b)
        time.sleep(0.5)

print("Done")
```

---

## Example 3: Monitor Badge Events

```python
#!/usr/bin/env python3
"""Print all escape-byte events from the badge."""
import serial
from dc29.protocol import (
    ESCAPE, EVT_BUTTON, EVT_KEY_REPLY, EVT_KEY_ACK,
    EVT_EFFECT_MODE, EVT_CHORD, modifier_name, keycode_name, EFFECT_NAMES
)

PORT = "/dev/tty.usbmodem14201"

EVENT_ARGS = {
    EVT_BUTTON: 3,      # n, mod, key
    EVT_KEY_REPLY: 3,   # n, mod, key
    EVT_KEY_ACK: 1,     # n
    EVT_EFFECT_MODE: 1, # mode
    EVT_CHORD: 1,       # type
}

def decode_event(cmd: int, args: list[int]) -> str:
    c = chr(cmd)
    if c == 'B':
        return f"BUTTON {args[0]} pressed: {modifier_name(args[1])}+{keycode_name(args[2], args[1])}"
    elif c == 'R':
        return f"KEYMAP reply button {args[0]}: {modifier_name(args[1])}+{keycode_name(args[2], args[1])}"
    elif c == 'A':
        return f"ACK: keymap set for button {args[0]}"
    elif c == 'V':
        return f"EFFECT MODE: {EFFECT_NAMES.get(args[0], args[0])}"
    elif c == 'C':
        return f"CHORD: {'long' if args[1] == 2 else 'short'}"
    return f"UNKNOWN cmd=0x{cmd:02X} args={args}"

print(f"Monitoring {PORT} — press Ctrl+C to stop")
with serial.Serial(PORT, 9600, timeout=None) as s:
    state = 0
    cmd = 0
    args = []
    args_needed = 0

    while True:
        b = s.read(1)[0]
        if state == 0:
            if b == ESCAPE:
                state = 1
        elif state == 1:
            cmd = b
            args = []
            args_needed = EVENT_ARGS.get(b, 0)
            if args_needed == 0:
                print(f"EVENT: {decode_event(cmd, [])}")
                state = 0
            else:
                state = 2
        elif state == 2:
            args.append(b)
            if len(args) >= args_needed:
                print(f"EVENT: {decode_event(cmd, args)}")
                state = 0
```

---

## Example 4: Set All Buttons to Custom Keymaps

```python
#!/usr/bin/env python3
"""Configure button keymaps for a specific workflow."""
import time
import serial
from dc29.protocol import ESCAPE, CMD_SET_KEY, MOD_CTRL, MOD_SHIFT, MOD_GUI, MOD_MEDIA

PORT = "/dev/tty.usbmodem14201"

# Keymaps: (button, modifier, keycode)
KEYMAPS = [
    (1, MOD_SHIFT | MOD_GUI, 0x10),  # button 1: Shift+Cmd+M (macOS Teams mute)
    (2, MOD_MEDIA, 0xE2),             # button 2: media mute
    (3, MOD_MEDIA, 0xE9),             # button 3: volume up
    (4, MOD_MEDIA, 0xEA),             # button 4: volume down
]

with serial.Serial(PORT, 9600) as s:
    for button, mod, key in KEYMAPS:
        cmd = bytes([ESCAPE, CMD_SET_KEY, button, mod, key])
        s.write(cmd)
        print(f"Set button {button}: mod=0x{mod:02X} key=0x{key:02X}")
        time.sleep(0.2)   # brief pause between EEPROM writes

print("All keymaps updated")
```

---

## Example 5: Asyncio Event Loop Integration

```python
#!/usr/bin/env python3
"""
Integrate BadgeWriter with asyncio.
Badge events arrive on the reader thread; we forward them to the event loop.
"""
import asyncio
from tools.teams_mute_indicator import BadgeWriter

PORT = "/dev/tty.usbmodem14201"

async def main():
    badge = BadgeWriter(PORT)
    loop = asyncio.get_running_loop()

    event_queue: asyncio.Queue = asyncio.Queue()

    # Wire up callbacks (called from reader thread → safely forward to loop)
    badge.on_button4_press = lambda: loop.call_soon_threadsafe(
        event_queue.put_nowait, ("button4",)
    )
    badge.on_effect_mode = lambda mode: loop.call_soon_threadsafe(
        event_queue.put_nowait, ("effect_mode", mode)
    )
    badge.on_chord_long = lambda: loop.call_soon_threadsafe(
        event_queue.put_nowait, ("chord_long",)
    )

    print("Listening for badge events — press buttons or hold all 4 for a chord")
    print("Ctrl+C to stop")

    try:
        while True:
            event = await event_queue.get()
            if event[0] == "button4":
                print("Button 4 pressed!")
                # Example: toggle between muted/unmuted for testing
                badge.write(b"\x01M")
                await asyncio.sleep(0.5)
                badge.write(b"\x01U")
            elif event[0] == "effect_mode":
                print(f"Effect mode changed to: {event[1]}")
            elif event[0] == "chord_long":
                print("Long chord! Effects reset.")
    except KeyboardInterrupt:
        badge.write(b"\x01X")
        print("\nExiting")

asyncio.run(main())
```

---

## Example 6: Build a Status Dashboard

```python
#!/usr/bin/env python3
"""
Simple status display: show CPU usage on LEDs 1-3.
Green = low, yellow = medium, red = high.
"""
import asyncio
import psutil
from tools.teams_mute_indicator import BadgeWriter

PORT = "/dev/tty.usbmodem14201"

def cpu_to_color(percent: float) -> tuple[int, int, int]:
    if percent < 33:
        return (0, 200, 0)     # green: low
    elif percent < 66:
        return (200, 150, 0)   # yellow: medium
    else:
        return (200, 0, 0)     # red: high

async def cpu_monitor(badge: BadgeWriter):
    while True:
        # psutil.cpu_percent returns average over the interval
        percents = psutil.cpu_percent(interval=1, percpu=True)
        # Use first 3 CPU cores for LEDs 1-3
        for led_n, core_pct in enumerate(percents[:3], start=1):
            r, g, b = cpu_to_color(core_pct)
            badge.set_led(led_n, r, g, b)

async def main():
    badge = BadgeWriter(PORT)
    badge.write(b"\x01X")   # clear LED 4

    print("CPU monitor running — LEDs 1-3 show core usage")
    print("Press Ctrl+C to stop")

    try:
        await cpu_monitor(badge)
    except KeyboardInterrupt:
        for n in range(1, 5):
            badge.set_led(n, 0, 0, 0)
        print("\nExiting")

asyncio.run(main())
```

Requires `pip install psutil`.

---

## Example 7: Simple Toggle Script (No asyncio)

```python
#!/usr/bin/env python3
"""Toggle LED 4 between muted/unmuted on each run."""
import sys
import serial
from pathlib import Path

PORT = sys.argv[1] if len(sys.argv) > 1 else "/dev/tty.usbmodem14201"
STATE_FILE = Path.home() / ".dc29_mute_state"

# Read current state from file
current = STATE_FILE.read_text().strip() if STATE_FILE.exists() else "clear"

# Toggle
next_state = "muted" if current != "muted" else "unmuted"
cmd = {"muted": b"\x01M", "unmuted": b"\x01U", "clear": b"\x01X"}[next_state]

with serial.Serial(PORT, 9600, timeout=1) as s:
    s.write(cmd)

STATE_FILE.write_text(next_state)
print(f"LED 4: {current} → {next_state}")
```

Run from a keyboard shortcut or script to toggle the badge LED without running the full Teams bridge.
