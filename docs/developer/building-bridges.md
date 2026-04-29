# Building Custom Bridges

← Back to [Developer Guide](README.md)

A **bridge** connects an external application (Teams, Zoom, Slack, OBS, etc.)
to the badge buttons and LEDs.  Bridges use the **bridge page** model: when
active, the bridge claims ownership of specific buttons and drives their LEDs.

---

## Bridge Page Model

```
Normal (no bridge):   buttons → EEPROM keymaps → HID keystrokes
Bridge active:        owned buttons → intercepted → bridge.handle_button()
                      unowned buttons → still fire EEPROM HID keymaps
```

This lets you run a "Teams page" during a meeting without losing your other
button shortcuts.

---

## Quick Start — Subclass BaseBridge

```python
from dc29.badge import BadgeAPI
from dc29.bridges.base import BaseBridge, BridgePage, PageButton
import asyncio


class MyBridge(BaseBridge):

    @property
    def page(self) -> BridgePage:
        return BridgePage(
            name="myservice",
            description="My Service call controls",
            buttons={
                1: PageButton("end-call",     led=(200, 0, 0)),
                2: PageButton("toggle-video", led=(0, 60, 180)),
                3: PageButton("raise-hand",   led=(180, 160, 0)),
                4: PageButton("toggle-mute",  led=(180, 0, 0)),
            },
        )

    async def handle_button(self, btn: int) -> None:
        actions = {1: "end_call", 2: "video", 3: "hand", 4: "mute"}
        if btn in actions:
            await self._send_to_my_service(actions[btn])

    async def run(self) -> None:
        self._install_button_hook()
        try:
            while True:
                try:
                    await self._connect_and_run()
                except Exception as exc:
                    print(f"Disconnected: {exc}. Retrying…")
                    self._clear_page_leds()
                    await asyncio.sleep(5)
        finally:
            self._uninstall_button_hook()
            self._clear_page_leds()

    async def _connect_and_run(self) -> None:
        # Connect to your service.  Light up buttons when in a session.
        self._apply_page_leds()
        # ... run until disconnect ...

    async def _send_to_my_service(self, action: str) -> None:
        print(f"Sending {action} to MyService")


# Usage:
badge = BadgeAPI("/dev/tty.usbmodem14201")
bridge = MyBridge(badge)
asyncio.run(bridge.run())
```

---

## BaseBridge API Reference

```python
class BaseBridge(ABC):
    # Required:
    @property
    def page(self) -> BridgePage: ...
    async def run(self) -> None: ...

    # Optional override — default does nothing:
    async def handle_button(self, btn: int) -> None: ...

    # Lifecycle helpers for use inside run():
    def _install_button_hook(self) -> None:
        """Intercept button presses for buttons in page.buttons."""
    def _uninstall_button_hook(self) -> None:
        """Restore previous button handler."""
    def _apply_page_leds(self) -> None:
        """Light up all page buttons with their defined .led color."""
    def _clear_page_leds(self) -> None:
        """Turn off all page button LEDs."""

    # Attributes:
    self._badge: BadgeAPI
    self._loop: asyncio.AbstractEventLoop   # set by _install_button_hook
    self.on_state_change: Callable | None   # optional callback
```

---

## Minimal Bridge (no subclassing)

If you just need LED state without button interception:

```python
from dc29.badge import BadgeAPI
from dc29.protocol import MuteState

badge = BadgeAPI("/dev/tty.usbmodem14201")
# Drive LED 4 directly:
badge.set_mute_state(MuteState.MUTED)    # red
badge.set_mute_state(MuteState.UNMUTED)  # green
badge.set_mute_state(MuteState.NOT_IN_MEETING)  # off
# Or use set_led for full control:
badge.set_led(2, 0, 60, 180)  # LED 2 blue
badge.close()
```

---

## Platform Examples

### Teams — WebSocket API

See `dc29/bridges/teams.py` for the complete implementation.  Teams exposes a
local WebSocket on `ws://localhost:8124`.  Actions: `toggle-mute`,
`toggle-video`, `toggle-hand`, `toggle-background-blur`, `leave-call`.

### Zoom — keyboard shortcuts via pynput

Zoom has no public local API.  Inject keyboard shortcuts:

```python
from pynput.keyboard import Controller, Key, KeyCode

_kb = Controller()

def _press_chord(*keys):
    for k in keys: _kb.press(k)
    for k in reversed(keys): _kb.release(k)

ZOOM_ACTIONS = {
    "toggle-mute":  lambda: _press_chord(Key.cmd, Key.shift, KeyCode.from_char('a')),
    "toggle-video": lambda: _press_chord(Key.cmd, Key.shift, KeyCode.from_char('v')),
    "leave-call":   lambda: _press_chord(Key.cmd, Key.shift, KeyCode.from_char('h')),
    "raise-hand":   lambda: _press_chord(Key.alt, KeyCode.from_char('y')),
}

async def handle_button(self, btn: int) -> None:
    action = self._button_actions.get(btn)
    if action and action in ZOOM_ACTIONS:
        ZOOM_ACTIONS[action]()
```

### Slack — keyboard shortcuts via pynput

```python
SLACK_ACTIONS = {
    "toggle-mute":  lambda: _press_chord(Key.cmd, Key.shift, KeyCode.from_char('m')),
    "toggle-video": lambda: _press_chord(Key.cmd, Key.shift, KeyCode.from_char('v')),
    "leave-call":   lambda: _press_chord(Key.cmd, Key.shift, KeyCode.from_char('h')),
    "raise-hand":   lambda: _press_chord(Key.cmd, Key.shift, KeyCode.from_char('k')),
}
```

### OBS — obs-websocket

```python
import json, asyncio
import websockets

OBS_URL = "ws://localhost:4455"

async def _dispatch_action(self, action: str) -> None:
    if action == "toggle-mute":
        await self._ws.send(json.dumps({
            "op": 6,
            "d": {
                "requestType": "ToggleInputMute",
                "requestId": "1",
                "requestData": {"inputName": "Desktop Audio"},
            }
        }))
```

---

## Adding to the CLI

Add a `dc29 myservice` command in `dc29/cli.py`:

```python
@app.command()
def myservice(
    port: Optional[str] = typer.Option(None, "--port", "-p", envvar="DC29_PORT"),
) -> None:
    """Run the MyService bridge."""
    import asyncio
    from dc29.badge import BadgeAPI
    from dc29.bridges.myservice import MyBridge

    badge = BadgeAPI(_resolve_port(port))
    try:
        asyncio.run(MyBridge(badge).run())
    except KeyboardInterrupt:
        pass
    finally:
        badge.close()
```
