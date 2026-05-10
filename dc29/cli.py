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
    """Parse an effect mode argument: integer 0..34 or any name from EFFECT_NAMES."""
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
        f"Use a number 0..{max(EFFECT_NAMES)} or one of: {', '.join(EFFECT_NAMES.values())}.",
        err=True,
    )
    raise typer.Exit(1)


def _apply_bridge_enable_flags(
    cfg,
    enable: Optional[list[str]],
    enable_all: bool,
) -> None:
    """Translate CLI ``--enable`` / ``--enable-all`` flags into config overrides.

    If ``--enable-all`` is passed, every bridge in the manifest is turned on.
    Otherwise, each ``--enable <name>`` is added to the enabled set on top of
    whatever the config file specified.  When neither flag is passed, the
    config file's ``[bridges] enabled = [...]`` is the source of truth (which
    defaults to empty — nothing runs).

    Unknown names are reported but not fatal.
    """
    from dc29.bridges.manifest import all_bridge_names, find_spec

    if enable_all:
        cfg.enabled_bridges = set(all_bridge_names())
        return

    if not enable:
        return

    current = set(cfg.enabled_bridges)
    for raw in enable:
        for piece in raw.split(","):
            name = piece.strip().lower()
            if not name:
                continue
            if find_spec(name) is None:
                typer.echo(
                    f"Warning: --enable {name!r} — no such bridge.  "
                    f"Run `dc29 bridges list` for available names.",
                    err=True,
                )
                continue
            current.add(name)
    cfg.enabled_bridges = current


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
        help="Disable the LED ripple animation on button press.",
    ),
    sticky_leds: Optional[bool] = typer.Option(
        None, "--sticky-leds/--no-sticky-leds",
        help=(
            "Keep the last-focused page's LED colors lit when no app is focused. "
            "Default reads from [badge] sticky_focus_leds in config.toml (off if unset)."
        ),
    ),
    slider: Optional[bool] = typer.Option(
        None, "--slider/--no-slider",
        help=(
            "Enable or disable the capacitive touch slider's volume up/down injection. "
            "Default reads from [badge] slider_enabled in config.toml (on if unset)."
        ),
    ),
    splash: Optional[bool] = typer.Option(
        None, "--splash/--no-splash",
        help=(
            "Enable or disable the interactive splash-on-press animation that fires "
            "when you poke a button while a light show is running. Default reads "
            "from [badge] splash_on_press (on if unset)."
        ),
    ),
    enable: Optional[list[str]] = typer.Option(
        None, "--enable",
        help=(
            "Enable a bridge by name (repeatable, e.g. --enable teams --enable vscode). "
            "Default: every bridge is OFF; nothing runs unless explicitly enabled here, "
            "via --enable-all, or the [bridges] enabled list in config.toml. "
            "Run `dc29 bridges list` to see all available names."
        ),
    ),
    enable_all: bool = typer.Option(
        False, "--enable-all",
        help="Enable every bridge in the manifest. Useful for first-time setup.",
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Debug logging."),
) -> None:
    """Run all bridges concurrently — the full context-aware shortcut experience.

    Buttons automatically switch context based on which app is in focus.
    A brief brand-color flash signals each context switch.

    \b
    In a Teams meeting  → Teams page  (mute / video / hand / leave call)
    Slack in focus      → Slack page  (unreads / mentions / switch / huddle)
    Outlook in focus    → Outlook page (delete / reply / reply-all / forward)
    VS Code / Cursor    → editor shortcuts (close / terminal / find / save)
    Figma               → design shortcuts (delete / hide / find / duplicate)
    Notion              → workspace shortcuts
    JIRA / Linear       → issue tracker shortcuts
    Confluence / GitHub → web app shortcuts
    Chrome              → browser shortcuts (close / refresh / reopen / new tab)
    No special app      → normal EEPROM key macros

    Priority: Teams meeting > focused native app > focused web app > EEPROM fallback.
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
    if sticky_leds is not None:
        cfg.sticky_focus_leds = sticky_leds
    if slider is not None:
        cfg.slider_enabled = slider
    if splash is not None:
        cfg.splash_on_press = splash
    _apply_bridge_enable_flags(cfg, enable, enable_all)

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
    """Run enabled bridges via :class:`BridgeManager` on one badge.

    The manager handles startup, hot-toggle (no-op here without a TUI), and
    teardown.  The flow runs until SIGINT.
    """
    from dc29.badge import BadgeAPI
    from dc29.bridges.manager import BridgeManager
    from dc29.config import get_config

    cfg = get_config()

    log = logging.getLogger(__name__)
    if not cfg.enabled_bridges:
        log.warning(
            "No bridges are enabled — nothing will happen.  "
            "Enable some with --enable <name> (e.g. --enable teams --enable vscode), "
            "or --enable-all, or set [bridges] enabled = [...] in config.toml."
        )

    badge = BadgeAPI(port, brightness=brightness)
    if not button_flash:
        badge.send_raw(bytes([0x01, ord("F"), 0]))
    # Mirror the configured slider state to the badge — firmware always boots
    # with the slider on, so we only need to send when the user wants it off,
    # but we always send to be defensive against firmware version drift.
    badge.set_slider_enabled(cfg.slider_enabled)
    badge.set_splash_on_press(cfg.splash_on_press)

    manager = BridgeManager(badge, cfg)
    started, _ = manager.reconcile()

    log.info(
        "Started %d bridge(s): %s",
        len(started),
        ", ".join(started) or "(none)",
    )

    from dc29.stats import stats_save_loop, get_stats
    stats_task = asyncio.create_task(stats_save_loop(), name="stats-save")

    try:
        # Run until cancelled (SIGINT triggers a CancelledError here).
        await asyncio.Event().wait()
    finally:
        stats_task.cancel()
        try:
            await stats_task
        except (asyncio.CancelledError, Exception):
            pass
        get_stats().save(force=True)
        await manager.stop_all()
        badge.close()


# ---------------------------------------------------------------------------
# start command — TUI + all bridges in one process
# ---------------------------------------------------------------------------


@app.command()
def start(
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
        help="Disable the LED ripple animation on button press.",
    ),
    sticky_leds: Optional[bool] = typer.Option(
        None, "--sticky-leds/--no-sticky-leds",
        help=(
            "Keep the last-focused page's LED colors lit when no app is focused. "
            "Default reads from [badge] sticky_focus_leds in config.toml (off if unset). "
            "Toggleable live in the TUI Effects tab."
        ),
    ),
    slider: Optional[bool] = typer.Option(
        None, "--slider/--no-slider",
        help=(
            "Enable or disable the capacitive touch slider's volume up/down injection. "
            "Default reads from [badge] slider_enabled in config.toml (on if unset). "
            "Toggleable live in the TUI Bridges & Inputs tab."
        ),
    ),
    splash: Optional[bool] = typer.Option(
        None, "--splash/--no-splash",
        help=(
            "Enable or disable the interactive splash-on-press animation. "
            "Default reads from [badge] splash_on_press (on if unset). "
            "Toggleable live in the TUI Effects tab."
        ),
    ),
    enable: Optional[list[str]] = typer.Option(
        None, "--enable",
        help=(
            "Enable a bridge by name (repeatable). "
            "Default: every bridge is OFF — toggle them on here, with --enable-all, "
            "in config.toml ([bridges] enabled = [...]), or live in the TUI Bridges tab."
        ),
    ),
    enable_all: bool = typer.Option(
        False, "--enable-all",
        help="Enable every bridge in the manifest.",
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Debug logging."),
) -> None:
    """Run all bridges + TUI in a single command (recommended).

    Combines dc29 flow and dc29 ui into one process sharing a single serial
    connection.  The TUI shows live context (active app profile, button meanings,
    badge status) while all bridges run in the background.

    \b
    Press q in the TUI to stop everything cleanly.

    Prerequisites (same as dc29 flow):
    \b
    * pip install 'dc29-badge[tui,hotkey]'
    * Run dc29 clear-keys once to remove EEPROM macros (prevents double-injection)
    * macOS: grant Accessibility permission to your terminal app
    """
    try:
        from dc29.tui.app import BadgeTUI  # noqa: F401 — validate import early
    except ImportError:
        typer.echo(
            "The TUI requires Textual: pip install 'dc29-badge[tui]'",
            err=True,
        )
        raise typer.Exit(1)

    # Root logger level only — no basicConfig. Actual output goes to the TUI
    # Log tab via TuiLogHandler installed in _run_start. Writing to stderr here
    # would fight with Textual's terminal rendering.
    logging.getLogger().setLevel(logging.DEBUG if verbose else logging.INFO)

    from dc29.config import get_config

    cfg = get_config()
    resolved_port = _resolve_port(port or cfg.badge_port)
    resolved_hotkey = hotkey if hotkey is not None else cfg.teams_toggle_hotkey
    if sticky_leds is not None:
        cfg.sticky_focus_leds = sticky_leds
    if slider is not None:
        cfg.slider_enabled = slider
    if splash is not None:
        cfg.splash_on_press = splash
    _apply_bridge_enable_flags(cfg, enable, enable_all)

    try:
        asyncio.run(
            _run_start(
                port=resolved_port,
                toggle_hotkey=resolved_hotkey or None,
                brightness=cfg.badge_brightness,
                button_flash=not no_button_flash,
            )
        )
    except KeyboardInterrupt:
        pass


async def _run_start(
    port: str,
    toggle_hotkey: Optional[str],
    brightness: float,
    button_flash: bool,
) -> None:
    """Run TUI + enabled bridges sharing one BadgeAPI instance.

    The TUI receives the :class:`BridgeManager` so toggling a bridge in the
    Bridges tab triggers a live ``manager.reconcile()`` — no restart.
    """
    from dc29.badge import BadgeAPI
    from dc29.bridges.manager import BridgeManager
    from dc29.config import get_config
    from dc29.tui.app import BadgeTUI

    _log = logging.getLogger(__name__)

    cfg = get_config()

    badge = BadgeAPI(port, brightness=brightness)
    if not button_flash:
        badge.send_raw(bytes([0x01, ord("F"), 0]))
    badge.set_slider_enabled(cfg.slider_enabled)
    badge.set_splash_on_press(cfg.splash_on_press)

    # Pre-wire TUI badge callbacks NOW so the TUI is the fallback receiver
    # for any button press not claimed by a registered handler.  Bridges
    # added later via the manager register handlers in front of this slot.
    loop = asyncio.get_running_loop()
    manager = BridgeManager(badge, cfg)
    tui = BadgeTUI(badge, pre_wire_loop=loop, bridge_manager=manager)

    # Route all Python logging into the TUI Log tab so stderr stays clean.
    log_handler = tui.install_log_handler(loop, level=logging.getLogger().level)

    started, _ = manager.reconcile()
    _log.info(
        "Starting TUI with %d bridge(s): %s",
        len(started),
        ", ".join(started) or "(none — toggle them on in the Bridges tab)",
    )

    from dc29.stats import stats_save_loop, get_stats
    stats_task = asyncio.create_task(stats_save_loop(), name="stats-save")

    try:
        await tui.run_async()
    finally:
        stats_task.cancel()
        try:
            await stats_task
        except (asyncio.CancelledError, Exception):
            pass
        get_stats().save(force=True)
        tui.remove_log_handler(log_handler)
        await manager.stop_all()
        badge.close()


# ---------------------------------------------------------------------------
# clear-keys command
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# bridges subcommand group
# ---------------------------------------------------------------------------

bridges_app = typer.Typer(
    help=(
        "List, enable, and disable bridges that ship with dc29.\n\n"
        "Bridges are off by default. Use `dc29 flow --enable <name>` for one-shot, "
        "or persist via `[bridges] enabled = [...]` in ~/.config/dc29/config.toml."
    ),
)
app.add_typer(bridges_app, name="bridges")


# ---------------------------------------------------------------------------
# scenes subcommand group — agent-facing entry points for light shows
# ---------------------------------------------------------------------------

scenes_app = typer.Typer(
    help=(
        "Authorable LED scenes — static colors, keyframe animations, or pointers "
        "at firmware effect modes.  Scenes are TOML files an agent or human can "
        "edit directly; see dc29/scenes.py for the schema."
    ),
)
app.add_typer(scenes_app, name="scene")


@scenes_app.command("list")
def scene_list() -> None:
    """List all scenes saved under ~/.config/dc29/scenes/."""
    from dc29.scenes import DEFAULT_SCENE_DIR, list_scenes, load_scene
    paths = list_scenes()
    if not paths:
        typer.echo(f"No scenes in {DEFAULT_SCENE_DIR}")
        typer.echo("Save one with: dc29 scene save <name> --static r,g,b r,g,b r,g,b r,g,b")
        return
    typer.echo(f"Scenes in {DEFAULT_SCENE_DIR}:")
    for p in paths:
        try:
            s = load_scene(p)
            kind = s.kind()
            desc = f" — {s.description}" if s.description else ""
            typer.echo(f"  {p.stem:20} [{kind}]{desc}")
        except Exception as exc:
            typer.echo(f"  {p.stem:20} [ERROR: {exc}]", err=True)


def _parse_color_arg(s: str, *, where: str) -> tuple[int, int, int]:
    """Parse a 'r,g,b' or 'r g b' or '#rrggbb' color string into a tuple."""
    s = s.strip()
    if s.startswith("#"):
        h = s[1:]
        if len(h) != 6:
            raise typer.BadParameter(f"{where}: hex must be #rrggbb (got {s!r})")
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
    parts = [p for p in s.replace(",", " ").split() if p]
    if len(parts) != 3:
        raise typer.BadParameter(f"{where}: expected 3 components, got {s!r}")
    try:
        triple = tuple(int(p) for p in parts)
    except ValueError as exc:
        raise typer.BadParameter(f"{where}: {exc}") from exc
    if not all(0 <= c <= 255 for c in triple):
        raise typer.BadParameter(f"{where}: components must be 0..255")
    return triple  # type: ignore[return-value]


@scenes_app.command("save")
def scene_save(
    name: str = typer.Argument(..., help="Scene name; also becomes the filename slug."),
    static: Optional[list[str]] = typer.Option(
        None, "--static",
        help="Four 'r,g,b' (or '#rrggbb') colors for LEDs 1..4. Repeat 4 times.",
    ),
    firmware: Optional[str] = typer.Option(
        None, "--firmware",
        help=(
            "Firmware effect-mode name or numeric mode 0..34. "
            "See `dc29 list-effects` for the full catalog."
        ),
    ),
    description: str = typer.Option("", "--description", "-d"),
    brightness: float = typer.Option(1.0, "--brightness", "-b", min=0.0, max=1.0),
) -> None:
    """Author a static or firmware scene from the shell.

    For keyframe animations, write the TOML directly — the schema is
    documented in `dc29/scenes.py`.
    """
    from dc29.scenes import (
        Scene, StaticPayload, FirmwarePayload, save_scene,
    )
    from dc29.protocol import EFFECT_NAMES

    s: Scene
    if static and firmware:
        raise typer.BadParameter("--static and --firmware are mutually exclusive")
    if static:
        if len(static) != 4:
            raise typer.BadParameter("--static needs exactly 4 colors (one per LED)")
        c1, c2, c3, c4 = (_parse_color_arg(v, where=f"LED{i+1}") for i, v in enumerate(static))
        s = Scene(
            name=name, description=description, brightness=brightness,
            static=StaticPayload(c1, c2, c3, c4),
        )
    elif firmware:
        rev = {v: k for k, v in EFFECT_NAMES.items()}
        try:
            mode = int(firmware)
        except ValueError:
            mode = rev.get(firmware.lower(), -1)
        if mode not in EFFECT_NAMES:
            raise typer.BadParameter(
                f"--firmware must be 0..{max(EFFECT_NAMES)} or one of "
                f"{sorted(rev)}; got {firmware!r}"
            )
        s = Scene(
            name=name, description=description, brightness=brightness,
            firmware=FirmwarePayload(mode=mode),
        )
    else:
        raise typer.BadParameter("Pass either --static or --firmware (or hand-write TOML)")

    path = save_scene(s)
    typer.echo(f"✓ Saved {s.name!r} ({s.kind()}) → {path}")


@scenes_app.command("play")
def scene_play(
    target: str = typer.Argument(..., help="Scene name (lookup in default dir) or path to .toml file."),
    port: Optional[str] = typer.Option(
        None, "--port", "-p", help="Badge serial port. Auto-detected if omitted.",
        envvar="DC29_PORT",
    ),
    once: bool = typer.Option(False, "--once", help="Run keyframe animation once and exit (overrides scene's loop=true)."),
) -> None:
    """Play a scene on the badge until Ctrl-C.

    Static and firmware scenes apply once and hold; animation scenes loop
    (or play once with `--once`) until interrupted.
    """
    import asyncio
    from pathlib import Path
    from dc29.badge import BadgeAPI
    from dc29.scenes import (
        DEFAULT_SCENE_DIR, load_scene, SceneRunner,
    )

    candidate = Path(target)
    if not candidate.exists():
        candidate = DEFAULT_SCENE_DIR / f"{target}.toml"
    if not candidate.exists():
        typer.echo(f"Scene not found: {target} (also looked at {candidate})", err=True)
        raise typer.Exit(2)

    scene = load_scene(candidate)
    if once and scene.animation is not None:
        scene.animation.loop = False

    resolved_port = _resolve_port(port)
    badge = BadgeAPI(resolved_port)
    deadline = time.monotonic() + 5.0
    while not badge.connected and time.monotonic() < deadline:
        time.sleep(0.05)
    if not badge.connected:
        typer.echo(f"Could not open {resolved_port}", err=True)
        raise typer.Exit(1)

    runner = SceneRunner(badge, scene)
    typer.echo(f"▶ Playing {scene.name!r} ({scene.kind()}) on {resolved_port}. Ctrl-C to stop.")
    try:
        asyncio.run(runner.run())
    except KeyboardInterrupt:
        typer.echo("\n■ Stopped.")
    finally:
        badge.close()


# ---------------------------------------------------------------------------
# audio subcommand group — for the audio-reactive bridge
# ---------------------------------------------------------------------------

audio_app = typer.Typer(
    help=(
        "Live audio-reactive LED show.  Uses a virtual loopback device "
        "(BlackHole on macOS) to capture system audio without a microphone, "
        "then runs FFT + beat detection in Python.  Setup: "
        "`brew install blackhole-2ch`, then create a Multi-Output Device in "
        "Audio MIDI Setup combining your speakers + BlackHole.  Run "
        "`dc29 audio status` to confirm BlackHole is detected."
    ),
)
app.add_typer(audio_app, name="audio")


@audio_app.command("status")
def audio_status() -> None:
    """List input-capable audio devices and confirm BlackHole is present."""
    from dc29.audio import HAS_AUDIO, find_blackhole, list_input_devices

    if not HAS_AUDIO:
        typer.echo(
            "Audio extras not installed.  Run:\n"
            "  pip install 'dc29-badge[audio]'\n"
            "(installs sounddevice + numpy)",
            err=True,
        )
        raise typer.Exit(1)

    devices = list_input_devices()
    bh = find_blackhole()
    if not devices:
        typer.echo("No input devices detected (audio system error?).", err=True)
        raise typer.Exit(1)

    typer.echo("Audio input devices:")
    for d in devices:
        marker = "  ⭐ "  if d["index"] == bh else "     "
        typer.echo(f"{marker}[{d['index']:>2}] {d['name']}  ({d['channels']} ch)")
    typer.echo("")
    if bh is None:
        typer.echo(
            "BlackHole not found.  Install with:\n"
            "  brew install blackhole-2ch\n\n"
            "Then in Audio MIDI Setup, create a Multi-Output Device combining\n"
            "your speakers/AirPods + BlackHole, and select it as system output.\n"
            "(Audio plays through your speakers AND we capture it via BlackHole.)",
            err=True,
        )
    else:
        typer.echo(f"✓ BlackHole detected at index {bh}.")


@audio_app.command("test")
def audio_test(
    seconds: int = typer.Option(10, "--seconds", "-s", min=1, max=120,
                                help="How long to capture before stopping."),
    device: Optional[str] = typer.Option(None, "--device", "-d",
                                         help="Substring of input device name."),
) -> None:
    """Capture audio for N seconds and print live RMS / band / beat state.

    Useful for confirming BlackHole is wired up correctly: play music,
    run this, watch the bars dance.
    """
    from dc29.audio import HAS_AUDIO, AudioCapture
    if not HAS_AUDIO:
        typer.echo("Audio extras not installed: pip install 'dc29-badge[audio]'", err=True)
        raise typer.Exit(1)

    last_print = 0.0
    beats_seen = 0

    def on_features(f) -> None:
        nonlocal last_print, beats_seen
        if f.beat:
            beats_seen += 1
        # Throttle prints to ~10 Hz so the terminal doesn't melt.
        now = time.monotonic()
        if now - last_print < 0.1:
            return
        last_print = now

        def bar(v: float, width: int = 20) -> str:
            n = int(max(0.0, min(1.0, v)) * width)
            return "█" * n + "░" * (width - n)

        beat_marker = "♪" if f.beat else " "
        typer.echo(
            f"\rrms {bar(f.rms, 10)}  bass {bar(f.bass, 10)}  "
            f"mid {bar(f.mid, 10)}  treble {bar(f.treble, 10)}  "
            f"{beat_marker} beats={beats_seen}    ",
            nl=False,
        )

    cap = AudioCapture(device=device, on_features=on_features)
    try:
        cap.start()
    except Exception as exc:
        typer.echo(f"Capture failed: {exc}", err=True)
        raise typer.Exit(1)
    try:
        time.sleep(seconds)
    except KeyboardInterrupt:
        pass
    finally:
        cap.stop()
    typer.echo(f"\n\nTotal beats detected over {seconds}s: {beats_seen}")


# ---------------------------------------------------------------------------
# spotify subcommand group — auth + status for the reactive bridge
# ---------------------------------------------------------------------------

spotify_app = typer.Typer(
    help=(
        "Connect dc29 to Spotify so the badge LEDs can react to whatever "
        "you're listening to. One-time setup: register a free Spotify dev "
        "app at https://developer.spotify.com/dashboard, add this redirect "
        "URI: http://localhost:8754/callback, paste the Client ID into "
        "~/.config/dc29/config.toml under [spotify] client_id, then run "
        "`dc29 spotify auth`."
    ),
)
app.add_typer(spotify_app, name="spotify")


@spotify_app.command("auth")
def spotify_auth() -> None:
    """Run the OAuth flow and save a long-lived refresh token.

    Opens a browser, waits for you to consent, captures the redirect, and
    persists the token at ~/.dc29_spotify_token (mode 0600).  Run once;
    subsequent dc29 invocations reuse the token until you revoke it on
    the Spotify side.
    """
    from dc29.config import get_config
    from dc29.spotify import authenticate

    cfg = get_config()
    client_id = cfg.spotify_client_id
    if not client_id:
        typer.echo(
            "No Spotify client_id configured.  Add this to "
            "~/.config/dc29/config.toml:\n\n"
            "    [spotify]\n"
            '    client_id = "your-client-id-here"\n\n'
            "Get a client ID from https://developer.spotify.com/dashboard "
            "(free, takes ~2 minutes).  Add http://localhost:8754/callback "
            "to your app's Redirect URIs.",
            err=True,
        )
        raise typer.Exit(2)

    try:
        authenticate(client_id, cfg.spotify_redirect_uri)
    except Exception as exc:
        typer.echo(f"Auth failed: {exc}", err=True)
        raise typer.Exit(1)
    typer.echo("✓ Authenticated.  Token saved to ~/.dc29_spotify_token.")
    typer.echo("  Now enable the bridge:  dc29 flow --enable spotify-reactive")


@spotify_app.command("status")
def spotify_status() -> None:
    """Show the current Spotify connection state and what's playing."""
    from dc29.config import get_config
    from dc29.spotify import ANALYSIS_CACHE_DIR, SpotifyClient, TOKEN_PATH, TokenSet

    cfg = get_config()
    client_id = cfg.spotify_client_id
    if not client_id:
        typer.echo("[spotify] client_id not configured — see `dc29 spotify auth --help`.")
        return

    typer.echo(f"client_id: {client_id}")
    typer.echo(f"redirect_uri: {cfg.spotify_redirect_uri}")
    typer.echo(f"token file: {TOKEN_PATH} ({'present' if TOKEN_PATH.exists() else 'absent'})")
    cache_count = len(list(ANALYSIS_CACHE_DIR.glob("*.json"))) if ANALYSIS_CACHE_DIR.exists() else 0
    typer.echo(f"analysis cache: {cache_count} track(s) at {ANALYSIS_CACHE_DIR}")

    tokens = TokenSet.load()
    if not tokens:
        typer.echo("No tokens — run `dc29 spotify auth`.")
        return

    expires_in = tokens.expires_at - time.time()
    typer.echo(
        f"access token: {'valid' if expires_in > 30 else 'expired'} "
        f"({int(expires_in)}s until expiry)"
    )

    client = SpotifyClient(client_id, cfg.spotify_redirect_uri)
    try:
        playing = client.currently_playing()
    except Exception as exc:
        typer.echo(f"Failed to fetch currently-playing: {exc}", err=True)
        return

    if playing is None:
        typer.echo("Nothing currently playing.")
    else:
        typer.echo(
            f"Now playing: {playing.artist} — {playing.track_name} "
            f"[{'▶' if playing.is_playing else '⏸'} "
            f"{playing.progress_ms // 1000}s/{playing.duration_ms // 1000}s]"
        )
        typer.echo(f"track id: {playing.track_id}")


# ---------------------------------------------------------------------------
# totp subcommand group — F09 RFC 6238 TOTP token
# ---------------------------------------------------------------------------

totp_app = typer.Typer(
    help=(
        "Provision and fire RFC 6238 TOTP codes from the badge.  One slot, "
        "20-byte raw key + 4-char label.  Codes are 6 digits, 30-second "
        "window.  Fire = type the current code into the focused window via "
        "the F06 HID-burst path.\n\n"
        "WARNING: TOTP secrets are stored in *plaintext* EEPROM and can be "
        "dumped via UF2.  Use only for low-stakes accounts or demos."
    ),
)
app.add_typer(totp_app, name="totp")


@totp_app.command("provision")
def totp_provision_cmd(
    slot: int = typer.Argument(0, help="Slot number (only 0 supported in v3 EEPROM layout)."),
    label: str = typer.Option(..., "--label", "-l", help="Short label, max 4 chars."),
    secret: str = typer.Option(..., "--secret", "-s",
        help="Base32-encoded TOTP secret (e.g. JBSWY3DPEHPK3PXP).  Whitespace and dashes are stripped."),
    port: Optional[str] = typer.Option(None, "--port", "-p", envvar="DC29_PORT"),
) -> None:
    """Provision a TOTP slot.  Decodes the base32 secret host-side and pushes
    the raw 20-byte key to the badge."""
    from dc29.badge import BadgeAPI
    from dc29.protocol import TOTP_KEY_LEN, TOTP_LABEL_LEN, TOTP_SLOTS
    from dc29.totp_test import base32_decode

    if not (0 <= slot < TOTP_SLOTS):
        typer.echo(f"slot must be 0..{TOTP_SLOTS - 1}", err=True)
        raise typer.Exit(2)

    try:
        raw = base32_decode(secret)
    except Exception as exc:
        typer.echo(f"could not decode --secret as base32: {exc}", err=True)
        raise typer.Exit(2)

    # Pad / truncate to TOTP_KEY_LEN.  Most consumer TOTP secrets decode
    # to 10–32 bytes; SHA-1 HMAC operates on whatever length you hand it,
    # but the firmware fixed-width slot expects exactly 20 bytes (matches
    # the SHA-1 block-aligned key length used by RFC 6238 §A.2).
    if len(raw) < TOTP_KEY_LEN:
        raw = raw.ljust(TOTP_KEY_LEN, b"\x00")
    elif len(raw) > TOTP_KEY_LEN:
        raw = raw[:TOTP_KEY_LEN]
        typer.echo(
            f"note: secret was {len(raw)} bytes after base32 decode; truncated to "
            f"{TOTP_KEY_LEN}.  RFC 6238 §A.2 reference uses 20-byte keys.",
            err=True,
        )

    if len(label) > TOTP_LABEL_LEN:
        typer.echo(f"label truncated to {TOTP_LABEL_LEN} chars", err=True)
        label = label[:TOTP_LABEL_LEN]

    resolved_port = _resolve_port(port)
    badge = BadgeAPI(resolved_port)
    try:
        import time as _t
        for _ in range(20):
            if badge.connected: break
            _t.sleep(0.1)
        if not badge.connected:
            typer.echo("Could not connect to badge.", err=True)
            raise typer.Exit(1)
        badge.totp_provision(slot, label, raw)
        _t.sleep(0.2)
    finally:
        badge.close()
    typer.echo(f"Provisioned slot {slot} with label '{label}' (key: {len(raw)} bytes).")


@totp_app.command("fire")
def totp_fire_cmd(
    slot: int = typer.Argument(0),
    delay: float = typer.Option(3.0, "--delay", "-d",
        help="Seconds to wait before firing (so you can switch focus to the target window)."),
    port: Optional[str] = typer.Option(None, "--port", "-p", envvar="DC29_PORT"),
) -> None:
    """Sync the badge clock and fire — types the current 6-digit code into the focused window.

    Always re-syncs the badge clock from the host *immediately* before firing
    (badge clock is RAM-only, so the bridge owns time).
    """
    from dc29.badge import BadgeAPI
    from dc29.protocol import TOTP_SLOTS

    if not (0 <= slot < TOTP_SLOTS):
        typer.echo(f"slot must be 0..{TOTP_SLOTS - 1}", err=True)
        raise typer.Exit(2)

    resolved_port = _resolve_port(port)
    badge = BadgeAPI(resolved_port)
    try:
        import time as _t
        for _ in range(20):
            if badge.connected: break
            _t.sleep(0.1)
        if not badge.connected:
            typer.echo("Could not connect to badge.", err=True)
            raise typer.Exit(1)

        if delay > 0:
            for s in range(int(delay), 0, -1):
                typer.echo(f"firing slot {slot} in {s} s — switch focus to your target window")
                _t.sleep(1.0)

        badge.totp_sync_time()
        _t.sleep(0.05)
        badge.totp_fire(slot)
        _t.sleep(0.5)   # allow burst to complete before closing port
    finally:
        badge.close()
    typer.echo(f"Fired slot {slot}.")


@totp_app.command("list")
def totp_list_cmd(
    port: Optional[str] = typer.Option(None, "--port", "-p", envvar="DC29_PORT"),
) -> None:
    """List provisioned TOTP slots (label only — never echoes the key)."""
    from dc29.badge import BadgeAPI

    resolved_port = _resolve_port(port)
    badge = BadgeAPI(resolved_port)
    try:
        import time as _t
        for _ in range(20):
            if badge.connected: break
            _t.sleep(0.1)
        if not badge.connected:
            typer.echo("Could not connect to badge.", err=True)
            raise typer.Exit(1)
        entries = badge.totp_list(timeout=1.0)
    finally:
        badge.close()
    if not entries:
        typer.echo("No reply from badge (timeout).")
        return
    for slot, label in entries:
        # Strip trailing zero / 0xFF padding for a friendly display.
        clean = label.rstrip(b"\x00\xff").decode("ascii", errors="replace")
        if not clean:
            typer.echo(f"  slot {slot}: empty (never provisioned)")
        else:
            typer.echo(f"  slot {slot}: label='{clean}'  (raw bytes: {label.hex()})")


# ---------------------------------------------------------------------------
# vault subcommand group — F07 rubber-ducky vault
# ---------------------------------------------------------------------------

vault_app = typer.Typer(
    help=(
        "Store + fire pre-recorded keystroke macros from the badge's EEPROM.\n\n"
        "Two slots, each up to 16 (modifier, key) pairs (~32 plain ASCII chars).\n"
        "WARNING: vault contents are stored in *plaintext* EEPROM and can be "
        "dumped via UF2.  Use only for stage-demo strings, never real "
        "credentials."
    ),
)
app.add_typer(vault_app, name="vault")


@vault_app.command("write")
def vault_write_cmd(
    slot: int = typer.Argument(..., help="Slot number, 0 or 1."),
    text: Optional[str] = typer.Option(
        None, "--text", "-t",
        help="ASCII text to pack and store.  Converted via the same HID "
             "table as `dc29 type`.  Mutually exclusive with --pairs.",
    ),
    port: Optional[str] = typer.Option(
        None, "--port", "-p",
        help="Badge serial port.  Auto-detected if omitted.",
        envvar="DC29_PORT",
    ),
) -> None:
    """Write a vault slot.

    Example:

    \b
        dc29 vault write 0 --text "hello world"
    """
    from dc29.badge import BadgeAPI
    from dc29.protocol import VAULT_MAX_PAIRS, VAULT_SLOTS

    if not (0 <= slot < VAULT_SLOTS):
        typer.echo(f"slot must be 0..{VAULT_SLOTS - 1}", err=True)
        raise typer.Exit(2)
    if text is None:
        typer.echo("--text is required (or --pairs in a future version)", err=True)
        raise typer.Exit(2)

    resolved_port = _resolve_port(port)
    badge = BadgeAPI(resolved_port)
    try:
        import time as _t
        for _ in range(20):
            if badge.connected:
                break
            _t.sleep(0.1)
        if not badge.connected:
            typer.echo("Could not connect to badge.", err=True)
            raise typer.Exit(1)
        try:
            n = badge.vault_write_text(slot, text)
        except ValueError as exc:
            typer.echo(f"vault write rejected: {exc}", err=True)
            raise typer.Exit(2)
    finally:
        badge.close()
    typer.echo(f"Wrote {n} pairs to slot {slot}.")


@vault_app.command("fire")
def vault_fire_cmd(
    slot: int = typer.Argument(..., help="Slot number, 0 or 1."),
    port: Optional[str] = typer.Option(
        None, "--port", "-p",
        help="Badge serial port.  Auto-detected if omitted.",
        envvar="DC29_PORT",
    ),
) -> None:
    """Fire (type) the macro stored in *slot* into the focused window."""
    from dc29.badge import BadgeAPI
    from dc29.protocol import VAULT_SLOTS

    if not (0 <= slot < VAULT_SLOTS):
        typer.echo(f"slot must be 0..{VAULT_SLOTS - 1}", err=True)
        raise typer.Exit(2)

    resolved_port = _resolve_port(port)
    badge = BadgeAPI(resolved_port)
    try:
        import time as _t
        for _ in range(20):
            if badge.connected:
                break
            _t.sleep(0.1)
        if not badge.connected:
            typer.echo("Could not connect to badge.", err=True)
            raise typer.Exit(1)
        badge.vault_fire(slot)
        # Give the firmware time to actually drive the burst before we close
        # the CDC port (16 pairs × ~10 ms = ~160 ms; pad to 500 ms).
        _t.sleep(0.5)
    finally:
        badge.close()
    typer.echo(f"Fired slot {slot}.")


@vault_app.command("clear")
def vault_clear_cmd(
    slot: int = typer.Argument(..., help="Slot number, 0 or 1."),
    port: Optional[str] = typer.Option(
        None, "--port", "-p",
        help="Badge serial port.  Auto-detected if omitted.",
        envvar="DC29_PORT",
    ),
) -> None:
    """Clear (zero out) a vault slot."""
    from dc29.badge import BadgeAPI
    from dc29.protocol import VAULT_SLOTS

    if not (0 <= slot < VAULT_SLOTS):
        typer.echo(f"slot must be 0..{VAULT_SLOTS - 1}", err=True)
        raise typer.Exit(2)

    resolved_port = _resolve_port(port)
    badge = BadgeAPI(resolved_port)
    try:
        import time as _t
        for _ in range(20):
            if badge.connected:
                break
            _t.sleep(0.1)
        if not badge.connected:
            typer.echo("Could not connect to badge.", err=True)
            raise typer.Exit(1)
        badge.vault_clear(slot)
    finally:
        badge.close()
    typer.echo(f"Cleared slot {slot}.")


@vault_app.command("list")
def vault_list_cmd(
    port: Optional[str] = typer.Option(
        None, "--port", "-p",
        help="Badge serial port.  Auto-detected if omitted.",
        envvar="DC29_PORT",
    ),
) -> None:
    """List all vault slots with length + first-8-byte preview."""
    from dc29.badge import BadgeAPI

    resolved_port = _resolve_port(port)
    badge = BadgeAPI(resolved_port)
    try:
        import time as _t
        for _ in range(20):
            if badge.connected:
                break
            _t.sleep(0.1)
        if not badge.connected:
            typer.echo("Could not connect to badge.", err=True)
            raise typer.Exit(1)
        entries = badge.vault_list(timeout=1.0)
    finally:
        badge.close()
    if not entries:
        typer.echo("No reply from badge (timeout).")
        return
    for slot, length, preview in entries:
        if length == 0:
            typer.echo(f"  slot {slot}: empty")
        else:
            preview_hex = " ".join(f"{b:02X}" for b in preview)
            typer.echo(f"  slot {slot}: {length} pairs  (preview: {preview_hex})")


# ---------------------------------------------------------------------------
# awake subcommand group — F08b Stay Awake
# ---------------------------------------------------------------------------

awake_app = typer.Typer(
    help=(
        "Keep the host awake (Amphetamine-style) by having the badge emit "
        "periodic no-op HID wake pulses.\n\n"
        "When `dc29 start` is running, this subcommand mutates the in-process "
        "session so the TUI countdown stays in sync.  When run standalone, it "
        "talks to the badge directly and writes a tiny pointer file so a later "
        "`dc29 awake status` can still report the projected end time."
    ),
)
app.add_typer(awake_app, name="awake")


def _parse_duration_arg(value: str) -> int:
    """Parse a CLI duration argument into seconds, or raise BadParameter."""
    from dc29.tui.stay_awake_tab import _parse_custom_duration  # reuse parser
    if value.lower() in ("inf", "indef", "indefinite", "forever"):
        from dc29.awake import INDEFINITE_SECS
        return INDEFINITE_SECS
    secs = _parse_custom_duration(value)
    if secs is None or secs <= 0:
        raise typer.BadParameter(
            f"could not parse {value!r} — try '90m', '1h30m', '4h', or 'forever'"
        )
    return secs


@awake_app.command("start")
def awake_start(
    duration: str = typer.Argument(
        ...,
        help="Duration: '90m', '1h30m', '4h', '8h', 'forever'.",
    ),
    led_mode: str = typer.Option(
        "off", "--led", "-l",
        help="LED visualization: off | cyan_pulse | progress_bar | effect_mode",
    ),
    effect_id: int = typer.Option(
        1, "--effect-id",
        help="Effect mode index (1..8), only used when --led=effect_mode",
    ),
    port: Optional[str] = typer.Option(
        None, "--port", "-p",
        help="Badge serial port.  Auto-detected if omitted.",
        envvar="DC29_PORT",
    ),
) -> None:
    """Start a Stay Awake session for *duration*.

    Examples:

    \b
        dc29 awake start 1h
        dc29 awake start 30m --led cyan_pulse
        dc29 awake start forever --led progress_bar
    """
    from dc29.awake import LedMode, get_state, write_pointer
    from dc29.badge import BadgeAPI

    secs = _parse_duration_arg(duration)
    mode = LedMode.parse(led_mode)

    # Always update the in-process state — when a `dc29 start` process is
    # running on the same machine the bridge there will pick this up via
    # the singleton (via shared module import).  But we can't actually
    # share state across processes that way; the singleton is per-process.
    # For headless invocation, we write the pointer file + drive the badge
    # directly.  When `dc29 start` is running, it has its own state and
    # the user should toggle from the TUI instead.  We still update local
    # state so a follow-up `dc29 awake status` from the same shell works.
    state = get_state()
    session = state.start_session(secs, led_mode=mode, effect_mode_id=effect_id)
    write_pointer(session)

    resolved_port = _resolve_port(port)
    badge = BadgeAPI(resolved_port)
    try:
        # Wait briefly for CDC to come up, then send the autonomous timer.
        import time as _t
        for _ in range(20):
            if badge.connected:
                break
            _t.sleep(0.1)
        if not badge.connected:
            typer.echo("Could not connect to badge.", err=True)
            raise typer.Exit(1)
        badge.awake_set_duration(secs)
        # Fire one immediate pulse so idle resets right away.
        badge.awake_pulse()
    finally:
        badge.close()

    if session.is_indefinite():
        typer.echo("Stay Awake started — indefinite session.")
    else:
        from datetime import datetime
        end = datetime.fromtimestamp(session.end_ts).strftime("%-I:%M %p")
        typer.echo(f"Stay Awake started — {secs // 60} min, ends ~{end}.")
    if mode != LedMode.OFF:
        typer.echo(
            "Note: --led visualization runs only in `dc29 start` (the bridge "
            "process renders LEDs).  Headless `awake start` only sets the "
            "wake timer."
        )


@awake_app.command("stop")
def awake_stop(
    port: Optional[str] = typer.Option(
        None, "--port", "-p",
        help="Badge serial port.  Auto-detected if omitted.",
        envvar="DC29_PORT",
    ),
) -> None:
    """Stop the active Stay Awake session immediately."""
    from dc29.awake import clear_pointer, get_state
    from dc29.badge import BadgeAPI

    get_state().stop_session()
    clear_pointer()

    resolved_port = _resolve_port(port)
    badge = BadgeAPI(resolved_port)
    try:
        import time as _t
        for _ in range(20):
            if badge.connected:
                break
            _t.sleep(0.1)
        if badge.connected:
            badge.awake_cancel()
    finally:
        badge.close()

    typer.echo("Stay Awake stopped.")


@awake_app.command("status")
def awake_status() -> None:
    """Report whether a Stay Awake session is active and its projected end."""
    from dc29.awake import read_pointer

    session = read_pointer()
    if session is None:
        typer.echo("Stay Awake: idle.")
        return

    if session.is_indefinite():
        typer.echo("Stay Awake: ACTIVE — indefinite session.")
        return

    from datetime import datetime
    end_str = datetime.fromtimestamp(session.end_ts).strftime("%-I:%M %p")
    started_str = datetime.fromtimestamp(session.started_ts).strftime("%-I:%M %p")
    remaining = int(session.remaining_secs())
    h, rem = divmod(remaining, 3600)
    m, s = divmod(rem, 60)
    if h > 0:
        rem_label = f"{h}h {m:02d}m"
    elif m > 0:
        rem_label = f"{m}m {s:02d}s"
    else:
        rem_label = f"{s}s"
    typer.echo(
        f"Stay Awake: ACTIVE — {rem_label} remaining "
        f"(started {started_str}, ends ~{end_str}, LED {session.led_mode.value})."
    )


# ---------------------------------------------------------------------------
# stats subcommand group — local nerd-fuel
# ---------------------------------------------------------------------------

stats_app = typer.Typer(
    help=(
        "Local-only fun stats: emails deleted, Teams meetings joined, mute "
        "toggles, button thumps, etc. Stored at ~/.config/dc29/stats.toml — "
        "never sent anywhere. Edit or delete the file at will."
    ),
)
app.add_typer(stats_app, name="stats")


@stats_app.callback(invoke_without_command=True)
def stats_default(ctx: typer.Context) -> None:
    """Show all collected stats (default action when no subcommand given)."""
    if ctx.invoked_subcommand is not None:
        return
    from dc29.stats import render_summary
    typer.echo(render_summary())


@stats_app.command("show")
def stats_show() -> None:
    """Show all collected stats."""
    from dc29.stats import render_summary
    typer.echo(render_summary())


@stats_app.command("reset")
def stats_reset(
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation."),
) -> None:
    """Wipe all stats. Sets a fresh 'tracking since' timestamp."""
    from dc29.stats import get_stats
    if not yes:
        typer.echo("This will wipe every counter and unique-set lifetime tally.")
        confirm = typer.confirm("Continue?")
        if not confirm:
            typer.echo("Cancelled.")
            return
    get_stats().reset()
    typer.echo("✓ Stats reset.")


@stats_app.command("export")
def stats_export() -> None:
    """Print the full stats snapshot as JSON to stdout."""
    import json
    from dc29.stats import get_stats
    typer.echo(json.dumps(get_stats().snapshot(), indent=2, default=str))


# ---------------------------------------------------------------------------


@scenes_app.command("delete")
def scene_delete(
    name: str = typer.Argument(..., help="Scene name (without .toml)."),
) -> None:
    """Delete a saved scene from ~/.config/dc29/scenes/."""
    from dc29.scenes import DEFAULT_SCENE_DIR
    path = DEFAULT_SCENE_DIR / f"{name}.toml"
    if not path.exists():
        typer.echo(f"No such scene: {path}", err=True)
        raise typer.Exit(2)
    path.unlink()
    typer.echo(f"✓ Deleted {path}")


# ---------------------------------------------------------------------------


@bridges_app.command("list")
def bridges_list() -> None:
    """List every bridge with its name, description, and current enabled state."""
    from dc29.bridges.manifest import BRIDGE_MANIFEST
    from dc29.config import get_config

    enabled = get_config().enabled_bridges
    for spec in BRIDGE_MANIFEST:
        marker = "✓" if spec.name in enabled else " "
        typer.echo(f"  [{marker}] {spec.name:14} — {spec.description}")
    if not enabled:
        typer.echo("\n  (none enabled — pass --enable to flow/start, or edit config.toml)")


@app.command("clear-keys")
def clear_keys(
    port: Optional[str] = typer.Option(
        None, "--port", "-p",
        help="Badge serial port.  Auto-detected if omitted.",
        envvar="DC29_PORT",
    ),
) -> None:
    """Clear all EEPROM key macros — set buttons 1–4 to no-op.

    When dc29 flow is running, Python bridges inject shortcuts via pynput.
    Any non-zero EEPROM macro fires as a HID keypress at the same time,
    causing double-injection (two keystrokes reach macOS per button press).

    Run this once after setting up dc29 flow.  The badge still sends button
    events over serial so Python bridges work normally; it just won't inject
    its own HID keystrokes on top.

    To restore a keymap, use dc29 set-key.
    """
    import threading
    from dc29.badge import BadgeAPI

    resolved_port = _resolve_port(port)
    badge = BadgeAPI(resolved_port)

    deadline = time.monotonic() + 5.0
    while not badge.connected and time.monotonic() < deadline:
        time.sleep(0.05)

    if not badge.connected:
        typer.echo(f"Could not open {resolved_port}.", err=True)
        badge.close()
        raise typer.Exit(1)

    ack_count = [0]
    ack_event = threading.Event()

    def _on_ack(n: int) -> None:
        typer.echo(f"  Button {n} cleared")
        ack_count[0] += 1
        if ack_count[0] >= 4:
            ack_event.set()

    badge.on_key_ack = _on_ack

    typer.echo("Clearing EEPROM keymaps for buttons 1–4…")
    for btn in range(1, 5):
        badge.set_key(btn, 0, 0)
        time.sleep(0.1)

    if ack_event.wait(timeout=5.0):
        typer.echo("\nAll keymaps cleared.  Firmware will no longer inject HID keypresses.")
        typer.echo("Run 'dc29 flow' — shortcuts are now handled exclusively by the bridges.")
    else:
        typer.echo(
            f"\nReceived {ack_count[0]}/4 ACKs within 5 s.  "
            "Commands were sent; badge may need newer firmware for full ACK support.",
            err=True,
        )

    badge.close()


# ---------------------------------------------------------------------------
# diagnose command
# ---------------------------------------------------------------------------


@app.command()
def diagnose(
    port: Optional[str] = typer.Option(
        None, "--port", "-p",
        help="Badge serial port.  Auto-detected if omitted.",
        envvar="DC29_PORT",
    ),
    watch: bool = typer.Option(
        False, "--watch", "-w",
        help="After the summary, stream button events until Ctrl-C.",
    ),
) -> None:
    """Diagnose badge configuration: keymaps, focused app, and button events.

    Prints a snapshot of EEPROM keymaps and the currently focused app, then
    optionally streams button events with decoded HID payloads.

    Typical troubleshooting workflow:

    \b
    1. dc29 diagnose               — check for leftover EEPROM macros
    2. dc29 clear-keys             — zero them out (eliminates double-injection)
    3. dc29 diagnose --watch       — press each button; verify only serial events fire
    4. dc29 flow -v                — run all bridges; watch shortcut-injection log lines
    """
    import threading
    from dc29.badge import BadgeAPI
    from dc29.bridges.focus import _get_active_app

    resolved_port = _resolve_port(port)

    # --- EEPROM keymap query ---
    console.rule("[bold]EEPROM Keymaps")
    results: dict[int, tuple[int, int]] = {}
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
        time.sleep(0.05)

    deadline_r = time.monotonic() + 4.0
    for btn in range(1, 5):
        remaining = max(0.0, deadline_r - time.monotonic())
        events[btn].wait(timeout=remaining)

    has_macros = False
    table = Table(box=box.SIMPLE_HEAD)
    table.add_column("Button", style="bold cyan", justify="center")
    table.add_column("Modifier", style="yellow")
    table.add_column("Keycode", style="green")
    table.add_column("Status")

    for btn in range(1, 5):
        if btn in results:
            mod, kc = results[btn]
            mod_str = modifier_name(mod)
            kc_str = keycode_name(kc, mod)
            if mod == 0 and kc == 0:
                status = "[dim]no-op (safe)[/dim]"
            else:
                has_macros = True
                status = "[red bold]⚠ ACTIVE — will double-inject![/red bold]"
            table.add_row(str(btn), mod_str, kc_str, status)
        else:
            table.add_row(str(btn), "—", "—", "[dim]no reply[/dim]")

    console.print(table)

    if has_macros:
        console.print(
            "[yellow]One or more buttons have EEPROM macros that will fire as HID\n"
            "keypresses alongside dc29 flow's pynput injection.\n"
            "Fix: run  [bold]dc29 clear-keys[/bold]  then restart dc29 flow.[/yellow]\n"
        )
    else:
        console.print("[green]✓ No active EEPROM macros — no double-injection risk.[/green]\n")

    # --- Focused app ---
    console.rule("[bold]Active App Detection")
    app_name, win_title = _get_active_app()
    console.print(f"  Process : [cyan]{app_name or '(empty)'}[/cyan]")
    console.print(f"  Window  : [cyan]{win_title or '(empty)'}[/cyan]\n")

    if not watch:
        badge.close()
        return

    # --- Watch mode ---
    console.rule("[bold]Button Watch  (press Ctrl-C to stop)")
    console.print("Press badge buttons — events will appear here.\n")

    def _on_button(n: int, mod: int, kc: int) -> None:
        app_now, title_now = _get_active_app()
        mod_str = modifier_name(mod)
        kc_str = keycode_name(kc, mod)
        if mod == 0 and kc == 0:
            hid_str = "[dim]no HID keypress[/dim]"
        else:
            hid_str = f"[red]HID → {mod_str}+{kc_str}[/red]"
        console.print(
            f"  [bold cyan]B{n}[/bold cyan]  {hid_str}"
            f"  |  app=[yellow]{app_now}[/yellow]  win=[dim]{title_now[:50]}[/dim]"
        )

    badge.on_button_press = _on_button

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
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
        help="Effect mode: integer 0..34 or any name from EFFECT_NAMES (off, rainbow-chase, pacifica, sinelon, etc.).",
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
# set-wled command — runtime knobs for WLED-ported effects (modes 19+)
# ---------------------------------------------------------------------------


def _parse_palette(value: str) -> int:
    """Parse a palette argument: integer 0..7 or any name from WLED_PALETTE_NAMES."""
    from dc29.protocol import WLED_PALETTE_NAMES
    try:
        n = int(value, 0)
        if n in WLED_PALETTE_NAMES:
            return n
        raise ValueError
    except ValueError:
        pass
    low = value.lower().strip()
    rev = {v: k for k, v in WLED_PALETTE_NAMES.items()}
    if low in rev:
        return rev[low]
    typer.echo(
        f"Unknown palette {value!r}.  "
        f"Use a number 0..{max(WLED_PALETTE_NAMES)} or one of: {', '.join(WLED_PALETTE_NAMES.values())}.",
        err=True,
    )
    raise typer.Exit(1)


@app.command("set-wled")
def set_wled(
    palette: Optional[str] = typer.Option(
        None, "--palette",
        help="Palette name or index 0..7 (rainbow, heat, ocean, lava, pacifica, sunset, forest, party).",
    ),
    speed: Optional[int] = typer.Option(
        None, "--speed", min=0, max=255,
        help="Effect timebase, 0..255 (firmware default 128).",
    ),
    intensity: Optional[int] = typer.Option(
        None, "--intensity", min=0, max=255,
        help="Per-effect 'amount' knob, 0..255 (firmware default 128).",
    ),
    port: Optional[str] = typer.Option(
        None, "--port", "-p",
        help="Badge serial port.  Auto-detected if omitted.",
        envvar="DC29_PORT",
    ),
) -> None:
    """Set WLED runtime knobs (palette, speed, intensity).

    Mirrors WLED's /win&FP=&SX=&IX= API.  Affects WLED-ported effects only
    (modes 19+); hand-rolled effects (1–18) ignore these knobs.

    Any flag you omit defaults to 128 (speed/intensity) or rainbow
    (palette) since the firmware doesn't expose its current values back
    to us — pass all three for predictable results.

    Examples:

    \b
      dc29 set-wled --palette pacifica
      dc29 set-wled --palette sunset --speed 180 --intensity 200
      dc29 set-wled --palette 5 --speed 64       # numeric forms also work
    """
    from dc29.badge import BadgeAPI
    from dc29.protocol import WLED_PALETTE_NAMES

    if palette is None and speed is None and intensity is None:
        typer.echo("Pass at least one of --palette / --speed / --intensity.", err=True)
        raise typer.Exit(1)

    pal_idx  = _parse_palette(palette) if palette is not None else 0
    speed_v  = speed     if speed     is not None else 128
    inten_v  = intensity if intensity is not None else 128

    resolved_port = _resolve_port(port)
    badge = BadgeAPI(resolved_port)
    deadline = time.monotonic() + 5.0
    while not badge.connected and time.monotonic() < deadline:
        time.sleep(0.05)
    if not badge.connected:
        typer.echo(f"Could not open {resolved_port}.", err=True)
        badge.close()
        raise typer.Exit(1)

    badge.set_wled(speed=speed_v, intensity=inten_v, palette=pal_idx)
    time.sleep(0.1)
    badge.close()
    typer.echo(
        f"WLED knobs set: palette={WLED_PALETTE_NAMES.get(pal_idx, pal_idx)} "
        f"speed={speed_v} intensity={inten_v}"
    )


# ---------------------------------------------------------------------------
# list-effects / list-palettes — cheat-sheet commands
# ---------------------------------------------------------------------------


@app.command("list-effects")
def list_effects() -> None:
    """List every available effect mode with its description."""
    from dc29.protocol import EFFECT_NAMES, EFFECT_DESCRIPTIONS
    for mode_id, name in EFFECT_NAMES.items():
        kind = "static" if mode_id == 0 else ("hand-rolled" if mode_id <= 18 else "WLED port")
        desc = EFFECT_DESCRIPTIONS.get(mode_id, "")
        typer.echo(f"  {mode_id:>2}  {name:<18}  [{kind:<11}]  {desc}")


@app.command("list-palettes")
def list_palettes() -> None:
    """List every available WLED palette with a 16-block color preview."""
    from dc29.protocol import WLED_PALETTE_NAMES, WLED_PALETTE_LUTS
    for pid, pname in WLED_PALETTE_NAMES.items():
        lut = WLED_PALETTE_LUTS[pid]
        # Render with ANSI 24-bit color escape codes for terminal preview
        swatch = "".join(f"\033[48;2;{r};{g};{b}m  \033[0m" for r, g, b in lut)
        typer.echo(f"  {pid}  {swatch} {pname}")


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
