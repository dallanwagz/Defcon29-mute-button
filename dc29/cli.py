"""
dc29.cli — Command-line interface for the DC29 badge macro-keypad.

Entry point: ``dc29`` (configured in pyproject.toml).

Run ``dc29 --help`` for a list of commands.
"""

from __future__ import annotations

import asyncio
import glob
import logging
import sys
import time
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table
from rich import box

from dc29.protocol import (
    EFFECT_NAMES,
    BUILTIN_COLORS,
    MuteState,
    EffectMode,
    parse_color,
    modifier_name,
    keycode_name,
    MOD_CTRL,
    MOD_SHIFT,
    MOD_ALT,
    MOD_GUI,
)

app = typer.Typer(
    name="dc29",
    help=(
        "CLI tools for the DEF CON 29 badge macro-keypad.\n\n"
        "The badge is an ATSAMD21G16B that presents itself as a USB CDC serial\n"
        "port and a USB HID keyboard.  Use these commands to configure key\n"
        "macros, set LED colors, run the Teams mute indicator, or monitor badge\n"
        "events in real time.\n\n"
        "Common workflow:\n\n"
        "  1. Plug in the badge and note the serial port:\n"
        "       ls /dev/tty.usbmodem*   (macOS)\n\n"
        "  2. Check what keymaps are currently configured:\n"
        "       dc29 info --port /dev/tty.usbmodem14201\n\n"
        "  3. Set button 1 to Cmd+Shift+M (Teams mute on macOS):\n"
        "       dc29 set-key 1 gui+shift m --port /dev/tty.usbmodem14201\n\n"
        "  4. Start the Teams mute indicator:\n"
        "       dc29 teams --port /dev/tty.usbmodem14201"
    ),
    no_args_is_help=True,
)

console = Console()
err_console = Console(stderr=True)


# ---------------------------------------------------------------------------
# Port auto-detection
# ---------------------------------------------------------------------------


def _find_port() -> Optional[str]:
    """Return the single badge serial port or raise a user-facing error."""
    import platform

    if platform.system() == "Windows":
        patterns = ["COM*"]
    else:
        patterns = ["/dev/tty.usbmodem*", "/dev/ttyACM*"]

    candidates: list[str] = []
    for pattern in patterns:
        candidates.extend(glob.glob(pattern))

    if len(candidates) == 1:
        return candidates[0]
    if len(candidates) == 0:
        typer.echo(
            "No badge serial port found.  Is the badge plugged in?\n"
            "  macOS: ls /dev/tty.usbmodem*\n"
            "  Windows: check Device Manager for a COM port",
            err=True,
        )
        raise typer.Exit(1)
    # Multiple ports found — list them and bail.
    typer.echo("Multiple serial ports found.  Specify one with --port:", err=True)
    for p in sorted(candidates):
        typer.echo(f"  {p}", err=True)
    raise typer.Exit(1)


def _resolve_port(port: Optional[str]) -> str:
    """Return *port* if given, otherwise auto-detect."""
    if port:
        return port
    found = _find_port()
    assert found is not None
    return found


# ---------------------------------------------------------------------------
# Modifier / keycode argument parsers
# ---------------------------------------------------------------------------

def _parse_modifier(value: str) -> int:
    """Parse a modifier argument from the CLI.

    Accepts a decimal integer (e.g. ``5``) or a ``+``-separated list of
    modifier names (e.g. ``ctrl+alt``).  Names: ctrl, shift, alt, gui.
    """
    value = value.strip()
    # Try plain integer first.
    try:
        return int(value, 0)
    except ValueError:
        pass
    # Parse name list.
    mod = 0
    for part in value.lower().split("+"):
        part = part.strip()
        if part == "ctrl":
            mod |= MOD_CTRL
        elif part == "shift":
            mod |= MOD_SHIFT
        elif part == "alt":
            mod |= MOD_ALT
        elif part == "gui":
            mod |= MOD_GUI
        elif part == "none" or part == "":
            pass
        else:
            typer.echo(
                f"Unknown modifier name {part!r}.  Use ctrl/shift/alt/gui or a decimal byte.",
                err=True,
            )
            raise typer.Exit(1)
    return mod


def _parse_keycode(value: str) -> int:
    """Parse a keycode argument from the CLI.

    Accepts a decimal / hex integer (e.g. ``0x10``) or a single ASCII letter
    that is mapped to its USB HID keycode (a=0x04 … z=0x1D).
    """
    value = value.strip()
    try:
        return int(value, 0)
    except ValueError:
        pass
    # Single letter → HID keycode.
    if len(value) == 1 and value.isalpha():
        kc = ord(value.lower()) - ord("a") + 0x04
        return kc
    typer.echo(
        f"Cannot parse keycode {value!r}.  "
        "Use a decimal byte, 0x-prefixed hex byte, or a single letter.",
        err=True,
    )
    raise typer.Exit(1)


def _parse_effect_mode(value: str) -> int:
    """Parse an effect mode argument: 0/1/2 or off/rainbow/breathe."""
    try:
        mode = int(value, 0)
        if mode not in EFFECT_NAMES:
            raise ValueError
        return mode
    except ValueError:
        pass
    low = value.lower().strip()
    rev = {v: k for k, v in EFFECT_NAMES.items()}
    if low in rev:
        return rev[low]
    # Friendly alias: "rainbow" → "rainbow-chase"
    if low == "rainbow":
        return EffectMode.RAINBOW_CHASE
    typer.echo(
        f"Unknown effect mode {value!r}.  "
        f"Use 0/1/2 or {'/'.join(EFFECT_NAMES.values())}.",
        err=True,
    )
    raise typer.Exit(1)


# ---------------------------------------------------------------------------
# ui command
# ---------------------------------------------------------------------------


@app.command()
def ui(
    port: Optional[str] = typer.Option(
        None, "--port", "-p",
        help="Badge serial port.  Auto-detected if omitted.",
        envvar="DC29_PORT",
    ),
) -> None:
    """Launch the interactive TUI (terminal user interface)."""
    try:
        from dc29.tui.app import BadgeTUI
    except ImportError:
        typer.echo(
            "The TUI requires Textual: pip install 'dc29-badge[tui]'",
            err=True,
        )
        raise typer.Exit(1)

    from dc29.badge import BadgeAPI
    resolved_port = _resolve_port(port)
    badge = BadgeAPI(resolved_port)
    try:
        BadgeTUI(badge).run()
    finally:
        badge.close()


# ---------------------------------------------------------------------------
# teams command
# ---------------------------------------------------------------------------


@app.command()
def teams(
    port: Optional[str] = typer.Option(
        None, "--port", "-p",
        help="Badge serial port.  Auto-detected if omitted.",
        envvar="DC29_PORT",
    ),
    hotkey: Optional[str] = typer.Option(
        None,
        "--toggle-hotkey",
        help=(
            "Global hotkey (pynput format) for mute toggle, e.g. '<ctrl>+<alt>+m'.\n"
            "Overrides teams.toggle_hotkey in config.  Pass '' to disable."
        ),
        envvar="DC29_TOGGLE_HOTKEY",
    ),
    brightness: float = typer.Option(
        None, "--brightness",
        help="LED brightness 0.0–1.0.  Overrides badge.brightness in config.",
    ),
    no_button_flash: bool = typer.Option(
        False, "--no-button-flash",
        help="Disable the white LED flash on button press.",
    ),
    verbose: bool = typer.Option(
        False, "--verbose", "-v",
        help="Enable debug-level logging.",
    ),
) -> None:
    """Run the Teams meeting-controls bridge (headless service).

    Connects to the Microsoft Teams Local API WebSocket on localhost:8124 and
    drives badge LEDs to reflect meeting state.  While in a meeting the full
    Teams page is active:

    \b
    Button 1 — leave call     (red)
    Button 2 — toggle video   (blue = on / dim = off)
    Button 3 — raise hand     (yellow = raised / dim = lowered)
    Button 4 — toggle mute    (red = muted / green = live)

    Button layout is configurable in ~/.config/dc29/config.toml.

    First run triggers a Teams pairing dialog.  The auth token is saved to
    ~/.dc29_teams_token and reused on subsequent runs.

    Prerequisites:
    \b
    * Teams: Settings → Privacy → Manage API → enable "Enable third-party API"
    * macOS: grant Accessibility permission for the terminal app (for hotkey)
    * pip install pynput  (optional, for --toggle-hotkey)
    """
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    from dc29.config import get_config
    cfg = get_config()

    resolved_port = _resolve_port(port or cfg.badge_port)
    resolved_brightness = brightness if brightness is not None else cfg.badge_brightness
    resolved_hotkey = hotkey if hotkey is not None else cfg.teams_toggle_hotkey

    try:
        asyncio.run(
            _run_teams_supervise(
                port=resolved_port,
                toggle_hotkey=resolved_hotkey or None,
                brightness=resolved_brightness,
                button_flash=not no_button_flash,
            )
        )
    except KeyboardInterrupt:
        pass


async def _run_teams_supervise(
    port: str,
    toggle_hotkey: Optional[str],
    brightness: float,
    button_flash: bool,
) -> None:
    from dc29.badge import BadgeAPI
    from dc29.bridges.teams import TeamsBridge

    badge = BadgeAPI(port, brightness=brightness)

    if not button_flash:
        badge.send_raw(bytes([0x01, ord("F"), 0]))

    bridge = TeamsBridge(badge, toggle_hotkey=toggle_hotkey)

    try:
        await bridge.run()
    finally:
        badge.close()


# ---------------------------------------------------------------------------
# slack command
# ---------------------------------------------------------------------------


@app.command()
def slack(
    port: Optional[str] = typer.Option(
        None, "--port", "-p",
        help="Badge serial port.  Auto-detected if omitted.",
        envvar="DC29_PORT",
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Debug logging."),
) -> None:
    """Run the Slack productivity bridge (headless service).

    Activates 4 Slack shortcuts when the Slack desktop app has focus.
    Shortcuts are injected as keyboard events (requires pynput).

    \b
    Button 1 — All Unreads       (blue)
    Button 2 — Mentions          (purple)
    Button 3 — Quick Switcher    (cyan)
    Button 4 — Toggle Huddle     (green)

    Configurable in ~/.config/dc29/config.toml under [slack.buttons]
    and [slack.colors].  Requires: pip install 'dc29-badge[hotkey]'
    """
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )
    from dc29.badge import BadgeAPI
    from dc29.bridges.slack import SlackBridge
    from dc29.config import get_config

    cfg = get_config()
    badge = BadgeAPI(_resolve_port(port or cfg.badge_port), brightness=cfg.badge_brightness)
    try:
        asyncio.run(SlackBridge(badge).run())
    except KeyboardInterrupt:
        pass
    finally:
        badge.close()


# ---------------------------------------------------------------------------
# outlook command
# ---------------------------------------------------------------------------


@app.command()
def outlook(
    port: Optional[str] = typer.Option(
        None, "--port", "-p",
        help="Badge serial port.  Auto-detected if omitted.",
        envvar="DC29_PORT",
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Debug logging."),
) -> None:
    """Run the Outlook email bridge (headless service).

    Activates 4 Outlook shortcuts when Outlook has focus.  Button 1 is
    Delete — bright red, with a satisfying LED pulse after each press.

    \b
    Button 1 — Delete email    (red — with satisfaction pulse)
    Button 2 — Reply           (blue)
    Button 3 — Reply All       (yellow)
    Button 4 — Forward         (purple)

    Configurable in ~/.config/dc29/config.toml under [outlook.buttons]
    and [outlook.colors] (including 'pulse' key for the animation color).
    Requires: pip install 'dc29-badge[hotkey]'
    """
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )
    from dc29.badge import BadgeAPI
    from dc29.bridges.outlook import OutlookBridge
    from dc29.config import get_config

    cfg = get_config()
    badge = BadgeAPI(_resolve_port(port or cfg.badge_port), brightness=cfg.badge_brightness)
    try:
        asyncio.run(OutlookBridge(badge).run())
    except KeyboardInterrupt:
        pass
    finally:
        badge.close()


# ---------------------------------------------------------------------------
# flow command — run Teams + Slack + Outlook concurrently
# ---------------------------------------------------------------------------


@app.command()
def flow(
    port: Optional[str] = typer.Option(
        None, "--port", "-p",
        help="Badge serial port.  Auto-detected if omitted.",
        envvar="DC29_PORT",
    ),
    hotkey: Optional[str] = typer.Option(
        None, "--toggle-hotkey",
        help="Global hotkey for Teams mute toggle (pynput format).",
        envvar="DC29_TOGGLE_HOTKEY",
    ),
    no_button_flash: bool = typer.Option(
        False, "--no-button-flash",
        help="Disable the white LED flash on button press.",
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Debug logging."),
) -> None:
    """Run all bridges concurrently: Teams + Slack + Outlook.

    This is the recommended production mode.  Buttons automatically
    switch context based on which app is in focus:

    \b
    In a Teams meeting  → Teams page (mute / video / hand / leave call)
    Slack in focus      → Slack page (unreads / mentions / switch / huddle)
    Outlook in focus    → Outlook page (delete / reply / reply-all / forward)
    No special app      → normal EEPROM key macros

    Priority: Teams meeting > focused app > EEPROM fallback.
    Requires: pip install 'dc29-badge[hotkey]' for shortcut injection.
    """
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )
    from dc29.config import get_config

    cfg = get_config()
    resolved_port = _resolve_port(port or cfg.badge_port)
    resolved_hotkey = hotkey if hotkey is not None else cfg.teams_toggle_hotkey

    try:
        asyncio.run(
            _run_flow(
                port=resolved_port,
                toggle_hotkey=resolved_hotkey or None,
                brightness=cfg.badge_brightness,
                button_flash=not no_button_flash,
            )
        )
    except KeyboardInterrupt:
        pass


async def _run_flow(
    port: str,
    toggle_hotkey: Optional[str],
    brightness: float,
    button_flash: bool,
) -> None:
    """Run Teams + Slack + Outlook bridges concurrently on one badge."""
    from dc29.badge import BadgeAPI
    from dc29.bridges.teams import TeamsBridge
    from dc29.bridges.slack import SlackBridge
    from dc29.bridges.outlook import OutlookBridge

    badge = BadgeAPI(port, brightness=brightness)
    if not button_flash:
        badge.send_raw(bytes([0x01, ord("F"), 0]))

    # Install in priority order: Teams (innermost) → Slack → Outlook (outermost)
    # Outlook wraps Slack wraps Teams; each bridge only intercepts when active.
    teams_bridge = TeamsBridge(badge, toggle_hotkey=toggle_hotkey)
    slack_bridge = SlackBridge(badge)
    outlook_bridge = OutlookBridge(badge)

    try:
        async with asyncio.TaskGroup() as tg:
            tg.create_task(teams_bridge.run(),   name="teams")
            tg.create_task(slack_bridge.run(),   name="slack")
            tg.create_task(outlook_bridge.run(), name="outlook")
    except* Exception as eg:
        for exc in eg.exceptions:
            logging.getLogger(__name__).error("Bridge error: %s", exc)
    finally:
        badge.close()


# ---------------------------------------------------------------------------
# set-key command
# ---------------------------------------------------------------------------


@app.command("set-key")
def set_key(
    button: int = typer.Argument(
        ...,
        help="Button number to configure (1–4, or 5–6 for slider directions).",
        metavar="BUTTON",
    ),
    modifier: str = typer.Argument(
        ...,
        help=(
            "HID modifier byte: decimal integer (e.g. 5), hex (e.g. 0x05), "
            "or name list (e.g. ctrl+alt).  Valid names: ctrl, shift, alt, gui."
        ),
        metavar="MODIFIER",
    ),
    keycode: str = typer.Argument(
        ...,
        help=(
            "HID keycode byte: decimal/hex integer or a single letter (a-z → 0x04-0x1D)."
        ),
        metavar="KEYCODE",
    ),
    port: Optional[str] = typer.Option(
        None, "--port", "-p",
        help="Badge serial port.  Auto-detected if omitted.",
        envvar="DC29_PORT",
    ),
) -> None:
    """Set the key macro for a badge button and save to EEPROM.

    The badge acknowledges the command and the tool exits.

    Examples:

    \b
      # Button 1 → Cmd+Shift+M  (Teams mute on macOS)
      dc29 set-key 1 gui+shift m

    \b
      # Button 2 → Ctrl+Alt+Delete
      dc29 set-key 2 ctrl+alt 0x4C

    \b
      # Button 3 → media play/pause
      dc29 set-key 3 0xF0 0xCD
    """
    from dc29.badge import BadgeAPI

    resolved_port = _resolve_port(port)
    mod_byte = _parse_modifier(modifier)
    kc_byte = _parse_keycode(keycode)

    if not (1 <= button <= 6):
        typer.echo("Button must be 1–6.", err=True)
        raise typer.Exit(1)

    ack_event = __import__("threading").Event()

    badge = BadgeAPI(resolved_port)
    badge.on_key_ack = lambda n: ack_event.set() if n == button else None

    # Give the port a moment to open.
    deadline = time.monotonic() + 5.0
    while not badge.connected and time.monotonic() < deadline:
        time.sleep(0.05)

    if not badge.connected:
        typer.echo(f"Could not open {resolved_port}.", err=True)
        badge.close()
        raise typer.Exit(1)

    badge.set_key(button, mod_byte, kc_byte)

    # Wait up to 3 s for the ACK.
    if ack_event.wait(timeout=3.0):
        typer.echo(
            f"Button {button} set: modifier={modifier_name(mod_byte)} "
            f"keycode={keycode_name(kc_byte, mod_byte)}"
        )
    else:
        typer.echo(
            f"No ACK received within 3 s.  "
            f"Command was sent; badge may need newer firmware for ACK support.",
            err=True,
        )
    badge.close()


# ---------------------------------------------------------------------------
# get-key command
# ---------------------------------------------------------------------------


@app.command("get-key")
def get_key(
    button: int = typer.Argument(
        ...,
        help="Button number to query (1–6).",
        metavar="BUTTON",
    ),
    port: Optional[str] = typer.Option(
        None, "--port", "-p",
        help="Badge serial port.  Auto-detected if omitted.",
        envvar="DC29_PORT",
    ),
) -> None:
    """Query and print the current keymap for a badge button.

    Sends a query to the badge and waits for the reply, then prints a table
    with the modifier and keycode.
    """
    from dc29.badge import BadgeAPI

    resolved_port = _resolve_port(port)

    if not (1 <= button <= 6):
        typer.echo("Button must be 1–6.", err=True)
        raise typer.Exit(1)

    reply_event = __import__("threading").Event()
    reply_data: list[tuple[int, int, int]] = []

    badge = BadgeAPI(resolved_port)

    def _on_reply(n: int, mod: int, kc: int) -> None:
        if n == button:
            reply_data.append((n, mod, kc))
            reply_event.set()

    badge.on_key_reply = _on_reply

    deadline = time.monotonic() + 5.0
    while not badge.connected and time.monotonic() < deadline:
        time.sleep(0.05)

    if not badge.connected:
        typer.echo(f"Could not open {resolved_port}.", err=True)
        badge.close()
        raise typer.Exit(1)

    badge.query_key(button)

    if reply_event.wait(timeout=3.0) and reply_data:
        n, mod, kc = reply_data[0]
        table = Table(title=f"Button {n} keymap", box=box.SIMPLE)
        table.add_column("Field")
        table.add_column("Byte")
        table.add_column("Name")
        table.add_row("Modifier", f"0x{mod:02X}", modifier_name(mod))
        table.add_row("Keycode",  f"0x{kc:02X}",  keycode_name(kc, mod))
        console.print(table)
    else:
        typer.echo(
            "No reply received within 3 s.  "
            "Is the badge plugged in and running current firmware?",
            err=True,
        )
        badge.close()
        raise typer.Exit(1)

    badge.close()


# ---------------------------------------------------------------------------
# set-led command
# ---------------------------------------------------------------------------


@app.command("set-led")
def set_led(
    n: int = typer.Argument(..., help="LED number (1–4).", metavar="N"),
    r: int = typer.Argument(..., help="Red component (0–255).", metavar="R"),
    g: int = typer.Argument(..., help="Green component (0–255).", metavar="G"),
    b: int = typer.Argument(..., help="Blue component (0–255).", metavar="B"),
    port: Optional[str] = typer.Option(
        None, "--port", "-p",
        help="Badge serial port.  Auto-detected if omitted.",
        envvar="DC29_PORT",
    ),
) -> None:
    """Set an LED color immediately (RAM only, resets on power cycle).

    Examples:

    \b
      dc29 set-led 1 255 0 0     # LED 1 red
      dc29 set-led 4 0 255 0     # LED 4 green
      dc29 set-led 2 0 0 0       # LED 2 off
    """
    from dc29.badge import BadgeAPI

    if not (1 <= n <= 4):
        typer.echo("LED number must be 1–4.", err=True)
        raise typer.Exit(1)
    for name, val in (("R", r), ("G", g), ("B", b)):
        if not (0 <= val <= 255):
            typer.echo(f"{name} must be 0–255.", err=True)
            raise typer.Exit(1)

    resolved_port = _resolve_port(port)
    badge = BadgeAPI(resolved_port)

    deadline = time.monotonic() + 5.0
    while not badge.connected and time.monotonic() < deadline:
        time.sleep(0.05)

    if not badge.connected:
        typer.echo(f"Could not open {resolved_port}.", err=True)
        badge.close()
        raise typer.Exit(1)

    badge.set_led(n, r, g, b)
    time.sleep(0.1)  # brief flush window
    badge.close()
    typer.echo(f"LED {n} set to ({r}, {g}, {b})")


# ---------------------------------------------------------------------------
# set-effect command
# ---------------------------------------------------------------------------


@app.command("set-effect")
def set_effect(
    mode: str = typer.Argument(
        ...,
        help="Effect mode: 0/off, 1/rainbow-chase, or 2/breathe.",
        metavar="MODE",
    ),
    port: Optional[str] = typer.Option(
        None, "--port", "-p",
        help="Badge serial port.  Auto-detected if omitted.",
        envvar="DC29_PORT",
    ),
) -> None:
    """Set the firmware LED effect mode.

    Examples:

    \b
      dc29 set-effect off
      dc29 set-effect rainbow
      dc29 set-effect 2
    """
    from dc29.badge import BadgeAPI

    resolved_port = _resolve_port(port)
    mode_int = _parse_effect_mode(mode)

    badge = BadgeAPI(resolved_port)

    deadline = time.monotonic() + 5.0
    while not badge.connected and time.monotonic() < deadline:
        time.sleep(0.05)

    if not badge.connected:
        typer.echo(f"Could not open {resolved_port}.", err=True)
        badge.close()
        raise typer.Exit(1)

    badge.set_effect_mode(mode_int)
    time.sleep(0.1)
    badge.close()
    typer.echo(f"Effect mode set to {mode_int} ({EFFECT_NAMES.get(mode_int, 'unknown')})")


# ---------------------------------------------------------------------------
# info command
# ---------------------------------------------------------------------------


@app.command()
def info(
    port: Optional[str] = typer.Option(
        None, "--port", "-p",
        help="Badge serial port.  Auto-detected if omitted.",
        envvar="DC29_PORT",
    ),
) -> None:
    """Query all button keymaps and print a summary table.

    Connects to the badge, queries the keymap for buttons 1–4, and prints
    a Rich table.  Exits after printing.
    """
    import threading
    from dc29.badge import BadgeAPI

    resolved_port = _resolve_port(port)

    results: dict[int, tuple[int, int]] = {}  # button → (mod, kc)
    events = {btn: threading.Event() for btn in range(1, 5)}

    badge = BadgeAPI(resolved_port)

    def _on_reply(n: int, mod: int, kc: int) -> None:
        results[n] = (mod, kc)
        if n in events:
            events[n].set()

    badge.on_key_reply = _on_reply

    deadline = time.monotonic() + 5.0
    while not badge.connected and time.monotonic() < deadline:
        time.sleep(0.05)

    if not badge.connected:
        typer.echo(f"Could not open {resolved_port}.", err=True)
        badge.close()
        raise typer.Exit(1)

    for btn in range(1, 5):
        badge.query_key(btn)
        time.sleep(0.05)  # small gap between queries

    # Wait for all replies (up to 4 s total).
    deadline_replies = time.monotonic() + 4.0
    for btn in range(1, 5):
        remaining = max(0.0, deadline_replies - time.monotonic())
        events[btn].wait(timeout=remaining)

    badge.close()

    table = Table(
        title=f"DC29 Badge keymap — {resolved_port}",
        box=box.SIMPLE_HEAD,
    )
    table.add_column("Button", style="bold cyan", justify="center")
    table.add_column("Modifier byte", justify="center")
    table.add_column("Modifier name", style="yellow")
    table.add_column("Keycode byte", justify="center")
    table.add_column("Keycode name", style="green")

    for btn in range(1, 5):
        if btn in results:
            mod, kc = results[btn]
            table.add_row(
                str(btn),
                f"0x{mod:02X}",
                modifier_name(mod),
                f"0x{kc:02X}",
                keycode_name(kc, mod),
            )
        else:
            table.add_row(str(btn), "—", "—", "—", "[dim]no reply[/dim]")

    console.print(table)

    missing = [btn for btn in range(1, 5) if btn not in results]
    if missing:
        typer.echo(
            f"Warning: no reply received for button(s) {missing}.  "
            "Is the badge running current firmware?",
            err=True,
        )


# ---------------------------------------------------------------------------
# monitor command
# ---------------------------------------------------------------------------


@app.command()
def monitor(
    port: Optional[str] = typer.Option(
        None, "--port", "-p",
        help="Badge serial port.  Auto-detected if omitted.",
        envvar="DC29_PORT",
    ),
) -> None:
    """Stream badge events to stdout (for debugging and scripting).

    Press Ctrl-C to exit.  Output lines are tab-separated for easy parsing:

    \b
      BUTTON   <n>  <modifier_byte>  <keycode_byte>
      KEY_ACK  <n>
      KEY_REPLY <n>  <modifier_byte>  <keycode_byte>
      EFFECT   <mode>
      CHORD    <type>
      CONNECT
      DISCONNECT
    """
    from dc29.badge import BadgeAPI

    resolved_port = _resolve_port(port)
    typer.echo(f"Monitoring {resolved_port} — press Ctrl-C to exit", err=True)

    badge = BadgeAPI(resolved_port)

    badge.on_button_press = lambda btn, mod, kc: print(
        f"BUTTON\t{btn}\t0x{mod:02X}\t0x{kc:02X}", flush=True
    )
    badge.on_key_ack = lambda n: print(f"KEY_ACK\t{n}", flush=True)
    badge.on_key_reply = lambda n, mod, kc: print(
        f"KEY_REPLY\t{n}\t0x{mod:02X}\t0x{kc:02X}", flush=True
    )
    badge.on_effect_mode = lambda mode: print(
        f"EFFECT\t{mode}\t{EFFECT_NAMES.get(mode, 'unknown')}", flush=True
    )
    badge.on_chord = lambda t: print(
        f"CHORD\t{t}\t{'long' if t == 2 else 'short'}", flush=True
    )
    badge.on_connect = lambda: print("CONNECT", flush=True)
    badge.on_disconnect = lambda: print("DISCONNECT", flush=True)

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        badge.close()


# ---------------------------------------------------------------------------
# config command group
# ---------------------------------------------------------------------------

config_app = typer.Typer(
    name="config",
    help="View and manage dc29 configuration (~/.config/dc29/config.toml).",
    no_args_is_help=True,
)
app.add_typer(config_app, name="config")


@config_app.command("show")
def config_show() -> None:
    """Print the effective configuration (defaults + any saved overrides)."""
    from dc29.config import get_config
    cfg = get_config()
    console.print(cfg.as_toml(), markup=False, highlight=False)


@config_app.command("init")
def config_init(
    force: bool = typer.Option(False, "--force", help="Overwrite existing config."),
) -> None:
    """Create a default config file at ~/.config/dc29/config.toml."""
    from dc29.config import _DEFAULT_CONFIG_PATH, Config
    path = _DEFAULT_CONFIG_PATH
    if path.exists() and not force:
        typer.echo(f"Config already exists at {path}.  Use --force to overwrite.", err=True)
        raise typer.Exit(1)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(Config({}).as_toml())
    typer.echo(f"Created {path}")
    typer.echo("Edit it with your preferred text editor, then run 'dc29 config show' to verify.")


# ---------------------------------------------------------------------------
# autostart command group
# ---------------------------------------------------------------------------

autostart_app = typer.Typer(
    name="autostart",
    help="Install or remove the dc29 teams bridge as a system service.",
    no_args_is_help=True,
)
app.add_typer(autostart_app, name="autostart")


@autostart_app.command("install")
def autostart_install(
    port: Optional[str] = typer.Option(
        None, "--port", "-p",
        help="Badge serial port.  Uses auto-detection if omitted.",
        envvar="DC29_PORT",
    ),
    hotkey: Optional[str] = typer.Option(
        None, "--toggle-hotkey",
        help="Global hotkey for mute toggle (pynput format).",
    ),
) -> None:
    """Install the Teams bridge as an auto-start service.

    \b
    macOS  — installs a launchd plist in ~/Library/LaunchAgents/
    Linux  — installs a systemd user unit in ~/.config/systemd/user/
    Windows — installs a Task Scheduler task (requires admin)
    """
    import platform
    import shutil
    import sys

    dc29_bin = shutil.which("dc29") or sys.executable + " -m dc29"
    args = ["teams"]
    if port:
        args += ["--port", port]
    if hotkey:
        args += ["--toggle-hotkey", hotkey]

    system = platform.system()

    if system == "Darwin":
        _install_launchd(dc29_bin, args)
    elif system == "Linux":
        _install_systemd(dc29_bin, args)
    elif system == "Windows":
        _install_wintask(dc29_bin, args)
    else:
        typer.echo(f"Unsupported platform: {system}", err=True)
        raise typer.Exit(1)


@autostart_app.command("remove")
def autostart_remove() -> None:
    """Remove the auto-start service installed by 'dc29 autostart install'."""
    import platform

    system = platform.system()
    if system == "Darwin":
        _remove_launchd()
    elif system == "Linux":
        _remove_systemd()
    elif system == "Windows":
        _remove_wintask()
    else:
        typer.echo(f"Unsupported platform: {system}", err=True)
        raise typer.Exit(1)


# ------------------------------------------------------------------
# Platform autostart helpers
# ------------------------------------------------------------------

_LAUNCHD_LABEL = "com.dc29-badge.teams"
_SYSTEMD_UNIT = "dc29-teams.service"
_WIN_TASK = "DC29-Teams-Bridge"


def _install_launchd(dc29_bin: str, args: list[str]) -> None:
    from pathlib import Path

    plist_dir = Path.home() / "Library" / "LaunchAgents"
    plist_dir.mkdir(parents=True, exist_ok=True)
    plist_path = plist_dir / f"{_LAUNCHD_LABEL}.plist"

    program_args = [dc29_bin] + args
    prog_args_xml = "\n".join(f"        <string>{a}</string>" for a in program_args)

    plist = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
    "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{_LAUNCHD_LABEL}</string>
    <key>ProgramArguments</key>
    <array>
{prog_args_xml}
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>{Path.home()}/.dc29_teams.log</string>
    <key>StandardErrorPath</key>
    <string>{Path.home()}/.dc29_teams.log</string>
</dict>
</plist>
"""
    plist_path.write_text(plist)
    typer.echo(f"Wrote {plist_path}")

    import subprocess
    subprocess.run(["launchctl", "load", str(plist_path)], check=False)
    typer.echo(f"Loaded launchd agent {_LAUNCHD_LABEL}  (logs → ~/.dc29_teams.log)")


def _remove_launchd() -> None:
    from pathlib import Path
    import subprocess

    plist_path = Path.home() / "Library" / "LaunchAgents" / f"{_LAUNCHD_LABEL}.plist"
    if not plist_path.exists():
        typer.echo("No launchd plist found — nothing to remove.")
        return
    subprocess.run(["launchctl", "unload", str(plist_path)], check=False)
    plist_path.unlink()
    typer.echo(f"Removed {plist_path}")


def _install_systemd(dc29_bin: str, args: list[str]) -> None:
    from pathlib import Path
    import subprocess

    unit_dir = Path.home() / ".config" / "systemd" / "user"
    unit_dir.mkdir(parents=True, exist_ok=True)
    unit_path = unit_dir / _SYSTEMD_UNIT

    exec_line = " ".join([dc29_bin] + args)
    unit = f"""[Unit]
Description=DC29 Badge Teams Bridge
After=network.target

[Service]
ExecStart={exec_line}
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
"""
    unit_path.write_text(unit)
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=False)
    subprocess.run(["systemctl", "--user", "enable", "--now", _SYSTEMD_UNIT], check=False)
    typer.echo(f"Installed and started systemd unit {_SYSTEMD_UNIT}")


def _remove_systemd() -> None:
    from pathlib import Path
    import subprocess

    unit_path = Path.home() / ".config" / "systemd" / "user" / _SYSTEMD_UNIT
    subprocess.run(["systemctl", "--user", "disable", "--now", _SYSTEMD_UNIT], check=False)
    if unit_path.exists():
        unit_path.unlink()
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=False)
    typer.echo(f"Removed systemd unit {_SYSTEMD_UNIT}")


def _install_wintask(dc29_bin: str, args: list[str]) -> None:
    import subprocess
    import sys

    cmd_str = " ".join([f'"{dc29_bin}"'] + args)
    ps_cmd = (
        f'$action = New-ScheduledTaskAction -Execute "{dc29_bin}" '
        f'-Argument "{" ".join(args)}"; '
        f'$trigger = New-ScheduledTaskTrigger -AtLogOn; '
        f'Register-ScheduledTask -TaskName "{_WIN_TASK}" '
        f'-Action $action -Trigger $trigger -RunLevel Highest -Force'
    )
    result = subprocess.run(
        ["powershell", "-Command", ps_cmd],
        capture_output=True, text=True,
    )
    if result.returncode == 0:
        typer.echo(f"Registered Task Scheduler task '{_WIN_TASK}'")
    else:
        typer.echo(f"Failed to register task: {result.stderr}", err=True)
        raise typer.Exit(1)


def _remove_wintask() -> None:
    import subprocess

    result = subprocess.run(
        ["powershell", "-Command", f'Unregister-ScheduledTask -TaskName "{_WIN_TASK}" -Confirm:$false'],
        capture_output=True, text=True,
    )
    if result.returncode == 0:
        typer.echo(f"Removed Task Scheduler task '{_WIN_TASK}'")
    else:
        typer.echo(f"Failed to remove task: {result.stderr}", err=True)
        raise typer.Exit(1)
