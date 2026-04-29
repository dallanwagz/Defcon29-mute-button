# DC29 Badge — Extending the Platform

> **docs/spine/** is the authoritative source of truth.

← Back to [Project Overview](00-overview.md)

## Overview

The DC29 badge exposes a clean protocol over USB CDC serial, a Python package
with a typed API, and an extensibility model built around **bridge pages**.
You can build on it from multiple angles:

1. **Use BadgeAPI standalone** — write a Python script that talks to the badge
2. **Write a new bridge** — connect Zoom, Slack, OBS, or any app to the badge buttons and LEDs
3. **Add a new CLI command** — extend the `dc29` Typer CLI
4. **Write a new firmware effect** — add a new LED animation in C

---

## Using BadgeAPI Standalone

```python
from dc29.badge import BadgeAPI
from dc29.protocol import MuteState

badge = BadgeAPI("/dev/tty.usbmodem14201", brightness=0.8)

# LED control
badge.set_led(1, 255, 80, 0)               # LED 1 orange
badge.set_mute_state(MuteState.MUTED)      # LED 4 red
badge.set_mute_state(MuteState.UNMUTED)    # LED 4 green

# Firmware effects
badge.set_effect_mode(1)                   # rainbow-chase (LEDs 1-3)
badge.set_effect_mode(0)                   # off

# EEPROM keymap
badge.set_key(button=1, modifier=0x08, keycode=0x10)  # GUI+M
badge.query_key(button=1)                  # fires on_key_reply callback

# Events
badge.on_button_press = lambda btn, mod, kc: print(f"Button {btn}")
badge.on_chord        = lambda t: print("short chord" if t == 1 else "long chord")
badge.on_state_change = lambda state: print(state)   # unified feed

badge.close()
```

---

## Bridge Pages

The bridge page model is the key extensibility pattern.  A page is a named
set of button behaviors that a bridge activates while it is running.

```
Without a bridge:  buttons 1-4 fire EEPROM-stored HID keycodes
With a bridge:     buttons the bridge claims → handled by the bridge
                   buttons the bridge doesn't claim → still fire EEPROM
```

This means a Slack bridge can claim all 4 buttons during a call while not
interfering with a coding-focused button layout when Slack is idle.

---

## Writing a New Bridge

Subclass `dc29.bridges.base.BaseBridge`, implement `page` and `run`, override
`handle_button`.

### Minimal bridge template

```python
# dc29/bridges/myservice.py
import asyncio
from dc29.badge import BadgeAPI
from dc29.bridges.base import BaseBridge, BridgePage, PageButton


class MyServiceBridge(BaseBridge):

    @property
    def page(self) -> BridgePage:
        return BridgePage(
            name="myservice",
            description="My Service — meeting controls",
            buttons={
                1: PageButton("leave-call",   led=(200, 0, 0)),
                2: PageButton("toggle-video", led=(0, 60, 180)),
                3: PageButton("raise-hand",   led=(180, 160, 0)),
                4: PageButton("toggle-mute",  led=(180, 0, 0)),
            },
        )

    async def handle_button(self, btn: int) -> None:
        action_map = {1: "leave", 2: "video", 3: "hand", 4: "mute"}
        action = action_map.get(btn)
        if action:
            await self._dispatch_action(action)

    async def run(self) -> None:
        self._install_button_hook()
        try:
            while True:
                try:
                    await self._connect_and_run()
                except Exception as exc:
                    print(f"Disconnected: {exc}. Retrying in 5s…")
                    self._clear_page_leds()
                    await asyncio.sleep(5)
        finally:
            self._uninstall_button_hook()
            self._clear_page_leds()

    async def _connect_and_run(self) -> None:
        # Connect to your service's API here
        # When connected, call self._apply_page_leds() to light up buttons
        # Keep running until disconnected
        ...

    async def _dispatch_action(self, action: str) -> None:
        # Send the action to your service's API
        ...
```

### Zoom bridge skeleton

```python
# Zoom doesn't have a public local API — use keyboard shortcuts via pynput
from pynput.keyboard import Key, Controller as KeyController

keyboard = KeyController()

ZOOM_SHORTCUTS = {
    "toggle-mute":  lambda: keyboard.press(Key.cmd) or ...,   # Cmd+Shift+A
    "toggle-video": lambda: ...,
    "leave-call":   lambda: ...,
}

async def handle_button(self, btn: int) -> None:
    action = self._button_actions.get(btn)
    shortcut = ZOOM_SHORTCUTS.get(action)
    if shortcut:
        shortcut()
```

### Slack bridge skeleton

```python
# Slack uses keyboard shortcuts; inject them via pynput on macOS/Windows
# Slack call shortcuts (macOS):
#   Toggle mute:  Cmd+Shift+Space
#   Toggle video: Cmd+Shift+V (in Slack Huddle)
#   Leave call:   (no universal shortcut — close the window)
```

### OBS bridge skeleton

```python
import aiohttp

# OBS WebSocket API (obs-websocket plugin)
OBS_HOST = "localhost"
OBS_PORT = 4455

async def _connect_and_run(self) -> None:
    async with aiohttp.ClientSession() as session:
        async with session.ws_connect(f"ws://{OBS_HOST}:{OBS_PORT}") as ws:
            self._ws = ws
            async for msg in ws:
                await self._handle_obs_event(msg.data)

async def _dispatch_action(self, action: str) -> None:
    if action == "toggle-mute":
        await self._ws.send_json({
            "op": 6,
            "d": {"requestType": "ToggleInputMute", "requestData": {"inputName": "Mic"}}
        })
```

---

## Adding a CLI Command

Add a `@app.command()` to `dc29/cli.py`.  Use the `_resolve_port()` helper
and instantiate `BadgeAPI` for serial access:

```python
@app.command()
def my_command(
    port: Optional[str] = typer.Option(None, "--port", "-p", envvar="DC29_PORT"),
) -> None:
    """My new command."""
    from dc29.badge import BadgeAPI
    from dc29.protocol import ESCAPE

    resolved_port = _resolve_port(port)
    badge = BadgeAPI(resolved_port)
    # ... do things with badge ...
    badge.close()
```

For async commands (bridges):

```python
@app.command()
def myservice(port: Optional[str] = ...) -> None:
    """Run the MyService bridge."""
    import asyncio
    from dc29.badge import BadgeAPI
    from dc29.bridges.myservice import MyServiceBridge

    badge = BadgeAPI(_resolve_port(port))
    bridge = MyServiceBridge(badge)
    try:
        asyncio.run(bridge.run())
    except KeyboardInterrupt:
        pass
    finally:
        badge.close()
```

---

## Adding a Firmware LED Effect

Effects run entirely in the badge firmware.  The host side sees only the
`EVT_EFFECT_MODE` event when modes change.

Steps:

1. Define a new `#define EFFECT_MY_PATTERN  3` in `src/main.h`
2. Increment `NUM_EFFECT_MODES` in `src/main.h`
3. Add a case in `update_effects()` in `src/main.c`:

```c
case EFFECT_MY_PATTERN:
    if ((millis - effect_timer) >= MY_STEP_MS) {
        effect_timer = millis;
        // drive LEDs 1-3 only
        uint8_t r, g, b;
        hsv_to_rgb(effect_hue, 255, &r, &g, &b);
        led_set_color(1, (uint8_t[]){r, g, b});
        effect_hue += 16;
    }
    break;
```

4. Update the Python side: add `MY_PATTERN = 3` to `EffectMode` in
   `dc29/protocol.py` and add it to `EFFECT_NAMES`.

5. Rebuild and reflash (see [Firmware Build](03-firmware.md)).

The 4-button chord (short press) cycles through all modes automatically since
it uses `(effect_mode + 1) % NUM_EFFECT_MODES`.

---

## Configuration Extension

Add new sections to `~/.config/dc29/config.toml` and read them in
`dc29/config.py`:

```python
@property
def myservice_button_actions(self) -> dict[int, str]:
    defaults = {1: "leave", 4: "mute"}
    raw = self._raw.get("myservice", {}).get("buttons", {})
    return {**defaults, **{int(k): str(v) for k, v in raw.items()}}
```
