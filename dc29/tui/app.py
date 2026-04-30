"""
dc29/tui/app.py — Textual TUI for the DEF CON 29 badge macro-keypad.


Layout (single screen, tabbed):

  ┌─ DC29 Badge  ●  /dev/tty.usbmodem14201 ─────────────── v1.0.0  ?=help  q=quit ─┐
  │ [1] Dashboard  [2] Keys  [3] LEDs  [4] Effects  [5] Log                         │
  ├─────────────────────────────────────────────────────────────────────────────────┤
  │  (tab content)                                                                  │
  └─────────────────────────────────────────────────────────────────────────────────┘

Keyboard shortcuts (global):
  1-5   Switch tabs
  r     Rainbow chase effect
  b     Breathe effect
  o     Effect off
  f     Toggle button flash
  ?     Help overlay
  q / ctrl+c   Quit

Thread-safety: badge callbacks arrive on a reader thread.  We use
``loop.call_soon_threadsafe`` to forward them as Textual Messages so
every handler runs on the event-loop thread.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Optional

from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.color import Color
from textual.containers import Container, Horizontal, ScrollableContainer, Vertical
from textual.css.query import NoMatches
from textual.message import Message
from textual.screen import ModalScreen
from textual.widgets import (
    Button,
    Checkbox,
    DataTable,
    Footer,
    Header,
    Input,
    Label,
    RadioButton,
    RadioSet,
    RichLog,
    Rule,
    Static,
    TabbedContent,
    TabPane,
)

from dc29.badge import BadgeAPI
from dc29.bridges.base import BridgePage
from dc29.protocol import BUILTIN_COLORS, EffectMode, MuteState

# ---------------------------------------------------------------------------
# Version banner shown in the title bar
# ---------------------------------------------------------------------------
_VERSION = "v1.0.0"

# ---------------------------------------------------------------------------
# Human-readable keycode helpers
# ---------------------------------------------------------------------------

# Standard HID keycodes → symbol strings used for display only.
_KEYCODE_NAMES: dict[int, str] = {
    0x00: "—",
    0x04: "a", 0x05: "b", 0x06: "c", 0x07: "d", 0x08: "e",
    0x09: "f", 0x0A: "g", 0x0B: "h", 0x0C: "i", 0x0D: "j",
    0x0E: "k", 0x0F: "l", 0x10: "m", 0x11: "n", 0x12: "o",
    0x13: "p", 0x14: "q", 0x15: "r", 0x16: "s", 0x17: "t",
    0x18: "u", 0x19: "v", 0x1A: "w", 0x1B: "x", 0x1C: "y",
    0x1D: "z",
    0x1E: "1", 0x1F: "2", 0x20: "3", 0x21: "4", 0x22: "5",
    0x23: "6", 0x24: "7", 0x25: "8", 0x26: "9", 0x27: "0",
    0x28: "Enter", 0x29: "Esc", 0x2A: "Bksp", 0x2B: "Tab",
    0x2C: "Space", 0x2D: "-", 0x2E: "=", 0x2F: "[", 0x30: "]",
    0x31: "\\", 0x33: ";", 0x34: "'", 0x36: ",", 0x37: ".",
    0x38: "/",
    0x3A: "F1", 0x3B: "F2", 0x3C: "F3", 0x3D: "F4",
    0x3E: "F5", 0x3F: "F6", 0x40: "F7", 0x41: "F8",
    0x42: "F9", 0x43: "F10", 0x44: "F11", 0x45: "F12",
    0xF0: "(media)",  # sentinel used by firmware for media keys
}

_MOD_BITS = {
    0x01: "ctrl",
    0x02: "shift",
    0x04: "alt",
    0x08: "gui",
}

_MOD_NAMES = {v: k for k, v in _MOD_BITS.items()}


def _modifier_str(mod: int) -> str:
    """Return a human-readable modifier string, e.g. 'ctrl+shift'."""
    parts = [name for bit, name in sorted(_MOD_BITS.items()) if mod & bit]
    return "+".join(parts) if parts else "—"


def _key_name(keycode: int) -> str:
    return _KEYCODE_NAMES.get(keycode, f"0x{keycode:02X}")


def _human_readable(mod: int, keycode: int) -> str:
    m = _modifier_str(mod)
    k = _key_name(keycode)
    if m == "—":
        return k
    if k == "—":
        return m
    return f"{m}+{k}"


# ---------------------------------------------------------------------------
# Default keymap rows shown in the Keys tab before any query replies arrive
# ---------------------------------------------------------------------------
_DEFAULT_KEYMAP: list[tuple[str, int, int]] = [
    ("BTN1", 0x01 | 0x02, 0x10),   # ctrl+shift M  (Teams Win)
    ("BTN2", 0xF0, 0x00),           # media Mute
    ("BTN3", 0x00, 0x00),           # none
    ("BTN4", 0x01 | 0x04, 0x10),   # ctrl+alt M
]

# ---------------------------------------------------------------------------
# Textual Messages — bridge from badge reader thread → event loop
# ---------------------------------------------------------------------------


class ButtonPressMessage(Message):
    """Fired when the badge reports a button press."""

    def __init__(self, button: int, modifier: int, keycode: int) -> None:
        super().__init__()
        self.button = button
        self.modifier = modifier
        self.keycode = keycode


class KeyReplyMessage(Message):
    """Fired when the badge responds to a query_key() call."""

    def __init__(self, button: int, modifier: int, keycode: int) -> None:
        super().__init__()
        self.button = button
        self.modifier = modifier
        self.keycode = keycode


class KeyAckMessage(Message):
    """Fired when the badge acknowledges a set_key() call."""

    def __init__(self, button: int) -> None:
        super().__init__()
        self.button = button


class EffectModeMessage(Message):
    """Fired when the badge reports its current effect mode."""

    def __init__(self, mode: int) -> None:
        super().__init__()
        self.mode = mode


class ChordMessage(Message):
    """Fired on badge chord events (1=short, 2=long)."""

    def __init__(self, chord_type: int) -> None:
        super().__init__()
        self.chord_type = chord_type


class ConnectMessage(Message):
    """Fired when the badge connects."""


class DisconnectMessage(Message):
    """Fired when the badge disconnects."""


class PageChangeMessage(Message):
    """Fired when the active bridge page changes."""

    def __init__(self, page: Optional[BridgePage]) -> None:
        super().__init__()
        self.page = page


class LogLineMessage(Message):
    """Fired by TuiLogHandler to route Python log records into the Log tab."""

    def __init__(self, markup: str, levelno: int) -> None:
        super().__init__()
        self.markup = markup
        self.levelno = levelno


# ---------------------------------------------------------------------------
# TuiLogHandler — routes Python logging into the TUI Log tab
# ---------------------------------------------------------------------------


class TuiLogHandler(logging.Handler):
    """A logging.Handler that posts records as LogLineMessage to a BadgeTUI.

    Install via ``BadgeTUI.install_log_handler()``.  Remove via
    ``BadgeTUI.remove_log_handler()`` or the handler returned from install.
    """

    _LEVEL_MARKUP = {
        logging.DEBUG:    "[dim]",
        logging.INFO:     "",
        logging.WARNING:  "[yellow]",
        logging.ERROR:    "[red]",
        logging.CRITICAL: "[bold red]",
    }
    _LEVEL_MARKUP_CLOSE = {
        logging.DEBUG:    "[/dim]",
        logging.INFO:     "",
        logging.WARNING:  "[/yellow]",
        logging.ERROR:    "[/red]",
        logging.CRITICAL: "[/bold red]",
    }

    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        post_fn,
    ) -> None:
        super().__init__()
        self._loop = loop
        self._post_fn = post_fn
        self.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            open_tag  = self._LEVEL_MARKUP.get(record.levelno, "")
            close_tag = self._LEVEL_MARKUP_CLOSE.get(record.levelno, "")
            markup = f"{open_tag}{msg}{close_tag}" if open_tag else msg
            self._loop.call_soon_threadsafe(
                self._post_fn, LogLineMessage(markup, record.levelno)
            )
        except Exception:
            self.handleError(record)


# ---------------------------------------------------------------------------
# Help Modal
# ---------------------------------------------------------------------------


class HelpScreen(ModalScreen):
    """Overlay showing keyboard shortcuts."""

    DEFAULT_CSS = """
    HelpScreen {
        align: center middle;
    }
    HelpScreen > Container {
        background: $panel;
        border: double $accent;
        padding: 1 3;
        width: 60;
        height: auto;
        max-height: 80%;
    }
    HelpScreen .help-title {
        text-align: center;
        color: $accent;
        text-style: bold;
        margin-bottom: 1;
    }
    HelpScreen .help-row {
        color: $text;
        margin: 0 0;
    }
    HelpScreen .help-key {
        color: $warning;
        text-style: bold;
    }
    HelpScreen .help-sep {
        color: $text-muted;
        margin: 0 0 1 0;
    }
    """

    BINDINGS = [
        Binding("escape", "dismiss", "Close"),
        Binding("?", "dismiss", "Close"),
        Binding("q", "dismiss", "Close"),
    ]

    def compose(self) -> ComposeResult:
        with Container():
            yield Label("⚡  DC29 Badge TUI  ⚡", classes="help-title")
            yield Rule()
            yield Label("  [yellow]1-5[/]   Switch tabs", markup=True, classes="help-row")
            yield Label("  [yellow]r[/]     Rainbow chase effect", markup=True, classes="help-row")
            yield Label("  [yellow]b[/]     Breathe effect", markup=True, classes="help-row")
            yield Label("  [yellow]o[/]     Effect off", markup=True, classes="help-row")
            yield Label("  [yellow]f[/]     Toggle button flash", markup=True, classes="help-row")
            yield Label("  [yellow]?[/]     This help screen", markup=True, classes="help-row")
            yield Label("  [yellow]q[/]     Quit", markup=True, classes="help-row")
            yield Rule()
            yield Label("  [yellow]Enter[/]  Edit selected keymap row (Keys tab)", markup=True, classes="help-row")
            yield Label("  [yellow]c[/]     Clear log (Log tab)", markup=True, classes="help-row")
            yield Rule()
            yield Label("  Press [yellow]Esc[/] or [yellow]?[/] to close", markup=True, classes="help-sep")


# ---------------------------------------------------------------------------
# Edit Keymap Modal
# ---------------------------------------------------------------------------


class EditKeyModal(ModalScreen):
    """Modal for editing a single button's keymap entry."""

    DEFAULT_CSS = """
    EditKeyModal {
        align: center middle;
    }
    EditKeyModal > Container {
        background: $panel;
        border: double $accent;
        padding: 1 3;
        width: 52;
        height: auto;
    }
    EditKeyModal .modal-title {
        text-align: center;
        color: $accent;
        text-style: bold;
        margin-bottom: 1;
    }
    EditKeyModal .field-label {
        color: $text-muted;
        margin: 1 0 0 0;
    }
    EditKeyModal .mod-row {
        height: 3;
        margin-bottom: 1;
    }
    EditKeyModal .btn-row {
        height: 3;
        margin-top: 1;
        align-horizontal: right;
    }
    EditKeyModal Button {
        margin-left: 1;
    }
    """

    def __init__(self, button_idx: int, modifier: int, keycode: int) -> None:
        super().__init__()
        self._button_idx = button_idx   # 1-based
        self._modifier = modifier
        self._keycode = keycode

    class Saved(Message):
        """Emitted when the user saves the edit."""

        def __init__(self, button: int, modifier: int, keycode: int) -> None:
            super().__init__()
            self.button = button
            self.modifier = modifier
            self.keycode = keycode

    def compose(self) -> ComposeResult:
        label = f"Edit BTN{self._button_idx} Keymap"
        with Container():
            yield Label(label, classes="modal-title")
            yield Rule()
            yield Label("Modifiers:", classes="field-label")
            with Horizontal(classes="mod-row"):
                yield Checkbox(
                    "ctrl",
                    id="mod-ctrl",
                    value=bool(self._modifier & 0x01),
                )
                yield Checkbox(
                    "shift",
                    id="mod-shift",
                    value=bool(self._modifier & 0x02),
                )
                yield Checkbox(
                    "alt",
                    id="mod-alt",
                    value=bool(self._modifier & 0x04),
                )
                yield Checkbox(
                    "gui",
                    id="mod-gui",
                    value=bool(self._modifier & 0x08),
                )
            yield Label("Key (hex 0x.. or letter/F1-F12):", classes="field-label")
            initial_key = _key_name(self._keycode)
            if initial_key == "—":
                initial_key = ""
            yield Input(
                value=initial_key,
                placeholder="e.g. m  or  0x10  or  F5",
                id="key-input",
            )
            yield Rule()
            with Horizontal(classes="btn-row"):
                yield Button("Save", variant="primary", id="btn-save")
                yield Button("Cancel", id="btn-cancel")

    def _build_modifier(self) -> int:
        mod = 0
        if self.query_one("#mod-ctrl", Checkbox).value:
            mod |= 0x01
        if self.query_one("#mod-shift", Checkbox).value:
            mod |= 0x02
        if self.query_one("#mod-alt", Checkbox).value:
            mod |= 0x04
        if self.query_one("#mod-gui", Checkbox).value:
            mod |= 0x08
        return mod

    def _parse_key(self, text: str) -> int:
        """Parse a key string to a HID keycode integer."""
        text = text.strip()
        if not text:
            return 0x00
        # Hex literal
        if text.lower().startswith("0x"):
            try:
                return int(text, 16)
            except ValueError:
                return 0x00
        # Single letter a-z → HID code
        if len(text) == 1 and text.isalpha():
            return 0x04 + (ord(text.lower()) - ord("a"))
        # Single digit 1-9 → HID
        if len(text) == 1 and text.isdigit():
            d = int(text)
            return 0x1E + (d - 1) if d >= 1 else 0x27  # 0 maps to 0x27
        # Function keys F1-F12
        if text.lower().startswith("f") and text[1:].isdigit():
            n = int(text[1:])
            if 1 <= n <= 12:
                return 0x39 + n  # F1=0x3A
        # Named keys
        _named = {
            "enter": 0x28, "esc": 0x29, "escape": 0x29,
            "bksp": 0x2A, "backspace": 0x2A,
            "tab": 0x2B, "space": 0x2C,
        }
        return _named.get(text.lower(), 0x00)

    @on(Button.Pressed, "#btn-save")
    def _save(self) -> None:
        mod = self._build_modifier()
        key_text = self.query_one("#key-input", Input).value
        keycode = self._parse_key(key_text)
        self.dismiss(EditKeyModal.Saved(self._button_idx, mod, keycode))

    @on(Button.Pressed, "#btn-cancel")
    def _cancel(self) -> None:
        self.dismiss(None)

    def on_key(self, event) -> None:  # type: ignore[override]
        if event.key == "escape":
            self.dismiss(None)


# ---------------------------------------------------------------------------
# Context Pane — the "StreamDeck profile" display
# ---------------------------------------------------------------------------


class ButtonCard(Container):
    """One button's action card in the active-context grid.

    Background dims the LED color; border brightens it so the card has
    a colored glow that matches what the hardware LED looks like.
    """

    DEFAULT_CSS = """
    ButtonCard {
        width: 1fr;
        height: 6;
        border: solid #333333;
        padding: 1 1;
        margin: 0 0 0 1;
    }
    ButtonCard:first-of-type {
        margin-left: 0;
    }
    ButtonCard .card-num {
        color: #666666;
        text-style: bold;
    }
    ButtonCard .card-action {
        color: #cccccc;
        text-style: bold;
        overflow: hidden;
    }
    """

    def __init__(self, btn_num: int) -> None:
        super().__init__()
        self._n = btn_num

    def compose(self) -> ComposeResult:
        yield Label(f"B{self._n}", classes="card-num")
        yield Label("—", classes="card-action", id=f"card-action-{self._n}")

    def set_action(self, label: str, led: tuple[int, int, int]) -> None:
        r, g, b = led
        self.styles.background = Color(max(r // 6, 6), max(g // 6, 6), max(b // 6, 6))
        self.styles.border = ("solid", Color(r // 2, g // 2, b // 2))
        try:
            self.query_one(f"#card-action-{self._n}", Label).update(label)
        except NoMatches:
            pass

    def clear_action(self) -> None:
        self.styles.background = Color(12, 12, 12)
        self.styles.border = ("solid", Color(40, 40, 40))
        try:
            self.query_one(f"#card-action-{self._n}", Label).update("—")
        except NoMatches:
            pass


class ContextPane(Container):
    """Live 'what is the badge doing right now' panel — the StreamDeck profile view.

    Shows the active app name (in its brand color), description, and a 4-button
    grid where each card's glow matches the physical LED color.  Updated
    automatically when any bridge gains or loses focus.
    """

    DEFAULT_CSS = """
    ContextPane {
        height: 11;
        border: double #555555;
        padding: 1 2;
        margin-bottom: 1;
    }
    ContextPane .ctx-title-row {
        height: 2;
        margin-bottom: 1;
    }
    ContextPane .ctx-app-name {
        color: #00cccc;
        text-style: bold;
        width: auto;
    }
    ContextPane .ctx-sep {
        color: #555555;
        width: 3;
        content-align: center middle;
    }
    ContextPane .ctx-desc {
        color: #888888;
        width: 1fr;
        content-align: left middle;
    }
    ContextPane #ctx-card-row {
        height: 7;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self._cards: list[ButtonCard] = []

    def compose(self) -> ComposeResult:
        with Horizontal(classes="ctx-title-row"):
            yield Label("NO ACTIVE CONTEXT", classes="ctx-app-name", id="ctx-app-name")
            yield Label("  ·  ", classes="ctx-sep")
            yield Label(
                "switch to an app to activate its profile",
                classes="ctx-desc",
                id="ctx-desc",
            )
        with Horizontal(id="ctx-card-row"):
            for i in range(1, 5):
                card = ButtonCard(i)
                self._cards.append(card)
                yield card

    def update_page(self, page: Optional[BridgePage]) -> None:
        """Refresh to reflect a new active page (or ``None`` = no context)."""
        name_w = self.query_one("#ctx-app-name", Label)
        desc_w = self.query_one("#ctx-desc", Label)

        if page is None:
            name_w.update("NO ACTIVE CONTEXT")
            name_w.styles.color = Color(70, 70, 70)
            desc_w.update("switch to an app to activate its profile")
            for card in self._cards:
                card.clear_action()
            return

        name_w.update(page.name.upper())
        if page.brand_color:
            r, g, b = page.brand_color
            name_w.styles.color = Color(r, g, b)
        else:
            name_w.styles.color = Color(0, 200, 200)

        desc_w.update(page.description or "")

        for i, card in enumerate(self._cards, start=1):
            pb = page.buttons.get(i)
            if pb:
                card.set_action(pb.label, pb.led)
            else:
                card.clear_action()


# ---------------------------------------------------------------------------
# Dashboard Tab
# ---------------------------------------------------------------------------


class DashboardTab(Container):
    """Tab 1: StreamDeck-companion overview — active context + badge status."""

    DEFAULT_CSS = """
    DashboardTab {
        padding: 1 2;
    }
    DashboardTab .section-title {
        color: $accent;
        text-style: bold;
        margin-bottom: 1;
    }
    DashboardTab .status-row {
        height: 3;
        margin-bottom: 1;
        align-vertical: middle;
    }
    DashboardTab .status-label {
        width: 20;
        color: $text-muted;
    }
    DashboardTab #quick-actions {
        margin-top: 1;
        height: 3;
    }
    DashboardTab #quick-actions Label {
        color: $text-muted;
        width: 20;
        content-align: left middle;
    }
    DashboardTab #quick-actions Button {
        margin-right: 1;
    }
    DashboardTab #recent-events-title {
        color: $accent;
        text-style: bold;
        margin-bottom: 1;
    }
    """

    _mute_colors = {
        MuteState.NOT_IN_MEETING: ("$text-muted", "NOT IN MEETING"),
        MuteState.UNMUTED: ("green", "UNMUTED"),
        MuteState.MUTED: ("red", "MUTED"),
    }

    def compose(self) -> ComposeResult:
        yield Label("ACTIVE PROFILE", classes="section-title")
        yield ContextPane()

        yield Label("STATUS", classes="section-title")
        with Horizontal(classes="status-row"):
            yield Label("Connection:", classes="status-label")
            yield Static("● CONNECTED", id="conn-status")
        with Horizontal(classes="status-row"):
            yield Label("Effect mode:", classes="status-label")
            yield Static("Off", id="effect-status")
        with Horizontal(classes="status-row"):
            yield Label("Mute state:", classes="status-label")
            yield Static("NOT IN MEETING", id="mute-status")

        yield Rule()
        yield Label("QUICK EFFECTS", classes="section-title")
        with Horizontal(id="quick-actions"):
            yield Label("Effects: ")
            yield Button("Rainbow [r]", id="qa-rainbow", variant="primary")
            yield Button("Breathe [b]", id="qa-breathe")
            yield Button("Off [o]", id="qa-off", variant="error")

        yield Rule()
        yield Label("RECENT EVENTS", id="recent-events-title")
        yield RichLog(id="recent-log", max_lines=5, markup=True, highlight=False)

    def update_context_page(self, page: Optional[BridgePage]) -> None:
        """Update the context pane with the newly active page (or None)."""
        try:
            self.query_one(ContextPane).update_page(page)
        except NoMatches:
            pass

    def update_connection(self, connected: bool) -> None:
        w = self.query_one("#conn-status", Static)
        if connected:
            w.update("● CONNECTED")
            w.styles.color = "green"
        else:
            w.update("● DISCONNECTED")
            w.styles.color = "red"

    def update_effect(self, mode: int) -> None:
        names = {0: "Off", 1: "Rainbow Chase", 2: "Breathe"}
        self.query_one("#effect-status", Static).update(names.get(mode, str(mode)))

    def update_mute(self, state: MuteState) -> None:
        color_name, label = self._mute_colors.get(
            state, ("$text-muted", "UNKNOWN")
        )
        w = self.query_one("#mute-status", Static)
        w.update(label)
        w.styles.color = color_name

    def push_event(self, markup: str) -> None:
        self.query_one("#recent-log", RichLog).write(markup)

    @on(Button.Pressed, "#qa-rainbow")
    def _qa_rainbow(self) -> None:
        self.app.action_rainbow()

    @on(Button.Pressed, "#qa-breathe")
    def _qa_breathe(self) -> None:
        self.app.action_breathe()

    @on(Button.Pressed, "#qa-off")
    def _qa_off(self) -> None:
        self.app.action_effect_off()


# ---------------------------------------------------------------------------
# Keys Tab
# ---------------------------------------------------------------------------


class KeysTab(Container):
    """Tab 2: Keymap editor."""

    DEFAULT_CSS = """
    KeysTab {
        padding: 1 2;
    }
    KeysTab .section-title {
        color: $accent;
        text-style: bold;
        margin-bottom: 1;
    }
    KeysTab .hint {
        color: $text-muted;
        margin-bottom: 1;
    }
    KeysTab DataTable {
        height: 12;
        border: solid $panel-lighten-2;
    }
    """

    # Current keymap data: (button_label, modifier, keycode)
    _rows: list[tuple[str, int, int]]

    def __init__(self) -> None:
        super().__init__()
        self._rows = list(_DEFAULT_KEYMAP)

    def compose(self) -> ComposeResult:
        yield Label("KEYMAP EDITOR", classes="section-title")
        yield Label(
            "Select a row and press Enter to edit. Changes are sent to the badge immediately.",
            classes="hint",
        )
        yield DataTable(id="keymap-table", cursor_type="row")

    def on_mount(self) -> None:
        table = self.query_one("#keymap-table", DataTable)
        table.add_columns("Button", "Modifier", "Key", "Human Readable")
        for label, mod, key in self._rows:
            table.add_row(
                label,
                _modifier_str(mod),
                _key_name(key),
                _human_readable(mod, key),
            )

    def update_row(self, button: int, modifier: int, keycode: int) -> None:
        """Update table row for button (1-based)."""
        if 1 <= button <= 4:
            self._rows[button - 1] = (f"BTN{button}", modifier, keycode)
            table = self.query_one("#keymap-table", DataTable)
            row_key = table.get_row_at(button - 1)
            table.update_cell_at((button - 1, 0), f"BTN{button}")
            table.update_cell_at((button - 1, 1), _modifier_str(modifier))
            table.update_cell_at((button - 1, 2), _key_name(keycode))
            table.update_cell_at((button - 1, 3), _human_readable(modifier, keycode))

    @on(DataTable.RowSelected)
    def _row_selected(self, event: DataTable.RowSelected) -> None:
        row_idx = event.cursor_row
        if 0 <= row_idx < len(self._rows):
            label, mod, key = self._rows[row_idx]
            btn_num = row_idx + 1

            def _handle_result(result) -> None:
                if result is not None and isinstance(result, EditKeyModal.Saved):
                    self.app.post_message(result)

            self.app.push_screen(
                EditKeyModal(btn_num, mod, key),
                _handle_result,
            )


# ---------------------------------------------------------------------------
# LEDs Tab
# ---------------------------------------------------------------------------


class LEDRow(Horizontal):
    """A single LED's color editor row."""

    DEFAULT_CSS = """
    LEDRow {
        height: 5;
        margin-bottom: 1;
        border: solid $panel-lighten-1;
        padding: 0 1;
    }
    LEDRow .led-label {
        width: 6;
        content-align: center middle;
        color: $accent;
        text-style: bold;
    }
    LEDRow .swatch-preview {
        width: 6;
        height: 3;
        margin: 1 2;
        border: solid $panel-lighten-2;
    }
    LEDRow .channel-col {
        width: 16;
        margin-right: 1;
    }
    LEDRow .channel-label {
        color: $text-muted;
        width: 3;
        content-align: right middle;
        margin-right: 1;
    }
    LEDRow .channel-input {
        width: 10;
    }
    LEDRow Button {
        width: 10;
        margin: 1 1;
    }
    """

    def __init__(self, led_num: int) -> None:
        super().__init__()
        self._n = led_num
        self._r = 0
        self._g = 0
        self._b = 0

    def compose(self) -> ComposeResult:
        yield Label(f"LED {self._n}", classes="led-label")
        yield Static("", id=f"prev-{self._n}", classes="swatch-preview")
        with Horizontal(classes="channel-col"):
            yield Label("R", classes="channel-label")
            yield Input("0", id=f"r-{self._n}", classes="channel-input", placeholder="0-255")
        with Horizontal(classes="channel-col"):
            yield Label("G", classes="channel-label")
            yield Input("0", id=f"g-{self._n}", classes="channel-input", placeholder="0-255")
        with Horizontal(classes="channel-col"):
            yield Label("B", classes="channel-label")
            yield Input("0", id=f"b-{self._n}", classes="channel-input", placeholder="0-255")
        yield Button("Apply", id=f"apply-{self._n}", variant="primary")

    def _update_preview(self) -> None:
        try:
            sw = self.query_one(f"#prev-{self._n}", Static)
            sw.styles.background = Color(self._r, self._g, self._b)
        except NoMatches:
            pass

    def _read_channel(self, widget_id: str) -> int:
        try:
            raw = self.query_one(f"#{widget_id}", Input).value.strip()
            val = int(raw)
            return max(0, min(255, val))
        except (ValueError, NoMatches):
            return 0

    @on(Input.Changed)
    def _input_changed(self, event: Input.Changed) -> None:
        n = self._n
        if event.input.id in (f"r-{n}", f"g-{n}", f"b-{n}"):
            self._r = self._read_channel(f"r-{n}")
            self._g = self._read_channel(f"g-{n}")
            self._b = self._read_channel(f"b-{n}")
            self._update_preview()

    @on(Button.Pressed)
    def _apply(self, event: Button.Pressed) -> None:
        if event.button.id == f"apply-{self._n}":
            r = self._read_channel(f"r-{self._n}")
            g = self._read_channel(f"g-{self._n}")
            b = self._read_channel(f"b-{self._n}")
            self.app.post_message(_ApplyLEDMessage(self._n, r, g, b))

    def set_values(self, r: int, g: int, b: int) -> None:
        """Update inputs and preview programmatically (e.g. from a preset)."""
        self._r, self._g, self._b = r, g, b
        try:
            self.query_one(f"#r-{self._n}", Input).value = str(r)
            self.query_one(f"#g-{self._n}", Input).value = str(g)
            self.query_one(f"#b-{self._n}", Input).value = str(b)
        except NoMatches:
            pass
        self._update_preview()


class _ApplyLEDMessage(Message):
    """Internal: apply LED color from LEDRow."""

    def __init__(self, n: int, r: int, g: int, b: int) -> None:
        super().__init__()
        self.n = n
        self.r = r
        self.g = g
        self.b = b


class LEDsTab(Container):
    """Tab 3: LED color editor."""

    # Factory defaults matching reset_eeprom() in firmware/main.c
    _FACTORY_DEFAULTS: dict[int, tuple[int, int, int]] = {
        1: (255, 0, 0),
        2: (0, 255, 0),
        3: (0, 0, 255),
        4: (127, 127, 127),
    }

    DEFAULT_CSS = """
    LEDsTab {
        padding: 1 2;
    }
    LEDsTab .section-title {
        color: $accent;
        text-style: bold;
        margin-bottom: 1;
    }
    LEDsTab .hint {
        color: $text-muted;
        margin-bottom: 1;
    }
    LEDsTab #presets {
        height: 8;
        margin-bottom: 1;
    }
    LEDsTab #presets Label {
        color: $text-muted;
        content-align: left middle;
        margin-right: 1;
        margin-bottom: 1;
    }
    LEDsTab #preset-buttons {
        height: 3;
    }
    LEDsTab #preset-buttons Button {
        margin-right: 1;
    }
    LEDsTab #reset-defaults {
        margin-top: 1;
        width: auto;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self._led_rows: list[LEDRow] = []

    def compose(self) -> ComposeResult:
        yield Label("LED COLOR EDITOR", classes="section-title")
        yield Label(
            "Edit R/G/B values (0-255) then press Apply. Use preset buttons to fill all LEDs.",
            classes="hint",
        )

        with Vertical(id="presets"):
            yield Label("Presets (fill all LEDs):")
            with Horizontal(id="preset-buttons"):
                for name in ("red", "green", "blue", "cyan", "magenta", "yellow", "white", "off"):
                    yield Button(name.capitalize(), id=f"preset-{name}")
            yield Button("↺ Reset to defaults", id="reset-defaults", variant="warning")

        for i in range(1, 5):
            row = LEDRow(i)
            self._led_rows.append(row)
            yield row

    @on(Button.Pressed, "#reset-defaults")
    def _reset_defaults(self) -> None:
        for i, row in enumerate(self._led_rows, start=1):
            rgb = self._FACTORY_DEFAULTS[i]
            row.set_values(*rgb)
            self.app.post_message(_ApplyLEDMessage(i, *rgb))

    @on(Button.Pressed)
    def _preset_pressed(self, event: Button.Pressed) -> None:
        if event.button.id and event.button.id.startswith("preset-"):
            name = event.button.id[7:]
            rgb = BUILTIN_COLORS.get(name, (0, 0, 0))
            for row in self._led_rows:
                row.set_values(*rgb)
            # send to badge
            for i, row in enumerate(self._led_rows, start=1):
                self.app.post_message(_ApplyLEDMessage(i, *rgb))

    @on(_ApplyLEDMessage)
    def _apply_led(self, event: _ApplyLEDMessage) -> None:
        # Bubble up — handled in BadgeTUI
        pass

    def get_row(self, n: int) -> LEDRow | None:
        if 1 <= n <= 4:
            return self._led_rows[n - 1]
        return None


# ---------------------------------------------------------------------------
# Effects Tab
# ---------------------------------------------------------------------------


class EffectsTab(Container):
    """Tab 4: Effect mode selector + button flash toggle."""

    DEFAULT_CSS = """
    EffectsTab {
        padding: 1 2;
    }
    EffectsTab .section-title {
        color: $accent;
        text-style: bold;
        margin-bottom: 1;
    }
    EffectsTab .desc {
        color: $text-muted;
        margin-bottom: 1;
        padding-left: 2;
    }
    EffectsTab RadioSet {
        margin-bottom: 1;
        border: solid $panel-lighten-1;
        padding: 1;
        height: auto;
    }
    EffectsTab #apply-effect {
        margin-top: 1;
    }
    EffectsTab #flash-section {
        margin-top: 2;
    }
    """

    _DESCRIPTIONS = {
        "Off": "All LEDs stay at their set colors. No animation.",
        "Rainbow Chase": "LEDs cycle through the full color wheel in a chasing pattern.",
        "Breathe": "LEDs fade in and out smoothly (breathing effect).",
    }

    def compose(self) -> ComposeResult:
        yield Label("EFFECT MODE", classes="section-title")
        with RadioSet(id="effect-radio"):
            yield RadioButton("Off", id="eff-off", value=True)
            yield RadioButton("Rainbow Chase", id="eff-rainbow")
            yield RadioButton("Breathe", id="eff-breathe")
        yield Label(self._DESCRIPTIONS["Off"], id="effect-desc", classes="desc")
        yield Button("Apply Effect", id="apply-effect", variant="primary")

        yield Rule()
        with Vertical(id="flash-section"):
            yield Label("BUTTON FLASH", classes="section-title")
            yield Label(
                "When enabled, the LED briefly flashes white when you press a button.",
                classes="desc",
            )
            yield Checkbox("Enable button flash", id="flash-toggle", value=True)

    @on(RadioSet.Changed, "#effect-radio")
    def _radio_changed(self, event: RadioSet.Changed) -> None:
        label = str(event.pressed.label)
        desc = self._DESCRIPTIONS.get(label, "")
        self.query_one("#effect-desc", Label).update(desc)

    @on(Button.Pressed, "#apply-effect")
    def _apply(self) -> None:
        radio = self.query_one("#effect-radio", RadioSet)
        idx = radio.pressed_index
        self.app.post_message(_ApplyEffectMessage(idx))

    @on(Checkbox.Changed, "#flash-toggle")
    def _flash_toggle(self, event: Checkbox.Changed) -> None:
        self.app.post_message(_SetFlashMessage(event.value))

    def set_effect_display(self, mode: int) -> None:
        radio = self.query_one("#effect-radio", RadioSet)
        try:
            radio.pressed_index = mode
        except Exception:
            pass


class _ApplyEffectMessage(Message):
    def __init__(self, mode: int) -> None:
        super().__init__()
        self.mode = mode


class _SetFlashMessage(Message):
    def __init__(self, enabled: bool) -> None:
        super().__init__()
        self.enabled = enabled


# ---------------------------------------------------------------------------
# Log Tab
# ---------------------------------------------------------------------------


class LogTab(Container):
    """Tab 5: Real-time badge event log."""

    DEFAULT_CSS = """
    LogTab {
        padding: 1 2;
    }
    LogTab .section-title {
        color: $accent;
        text-style: bold;
        margin-bottom: 1;
    }
    LogTab .hint {
        color: $text-muted;
        margin-bottom: 0;
    }
    LogTab RichLog {
        border: solid $panel-lighten-2;
        height: 1fr;
        padding: 0 1;
    }
    """

    def compose(self) -> ComposeResult:
        yield Label("BADGE EVENT LOG", classes="section-title")
        yield Label("C = clear log", classes="hint")
        yield RichLog(id="event-log", markup=True, highlight=False, auto_scroll=True)

    def write(self, markup: str) -> None:
        self.query_one("#event-log", RichLog).write(markup)

    def clear(self) -> None:
        self.query_one("#event-log", RichLog).clear()

    def on_key(self, event) -> None:  # type: ignore[override]
        if event.key == "c":
            self.clear()
            event.stop()


# ---------------------------------------------------------------------------
# Main Application
# ---------------------------------------------------------------------------


class BadgeTUI(App):
    """
    Textual TUI for the DC29 badge macro-keypad.

    Instantiate with a connected (or connecting) BadgeAPI object:

        badge = BadgeAPI(port="/dev/tty.usbmodem14201")
        app = BadgeTUI(badge)
        app.run()
    """

    TITLE = "DC29 Badge"
    SUB_TITLE = _VERSION

    BINDINGS = [
        Binding("1", "switch_tab('dashboard')", "Dashboard", show=False),
        Binding("2", "switch_tab('keys')", "Keys", show=False),
        Binding("3", "switch_tab('leds')", "LEDs", show=False),
        Binding("4", "switch_tab('effects')", "Effects", show=False),
        Binding("5", "switch_tab('log')", "Log", show=False),
        Binding("r", "rainbow", "Rainbow", show=False),
        Binding("b", "breathe", "Breathe", show=False),
        Binding("o", "effect_off", "Effect Off", show=False),
        Binding("f", "toggle_flash", "Toggle Flash", show=False),
        Binding("question_mark", "help", "Help", show=True),
        Binding("q", "quit", "Quit", show=True),
    ]

    DEFAULT_CSS = """
    /* ---- Global palette ---- */
    App {
        background: #0d0d0d;
        color: #e0e0e0;
    }

    /* ---- Header ---- */
    Header {
        background: #111111;
        color: $accent;
        text-style: bold;
    }

    /* ---- Footer ---- */
    Footer {
        background: #111111;
        color: $text-muted;
    }

    /* ---- TabbedContent bar ---- */
    TabbedContent > Tabs {
        background: #1a1a1a;
    }
    TabbedContent > Tabs > Tab {
        color: #888888;
    }
    TabbedContent > Tabs > Tab.-active {
        color: $accent;
        text-style: bold;
    }
    TabbedContent > ContentSwitcher {
        background: #0d0d0d;
    }

    /* ---- Buttons ---- */
    Button {
        background: #222222;
        border: tall $panel-lighten-1;
        color: $text;
    }
    Button:hover {
        background: #333333;
        border: tall $accent;
    }
    Button.-primary {
        background: #003040;
        border: tall $accent;
        color: $accent;
    }
    Button.-primary:hover {
        background: #004455;
    }
    Button.-error {
        background: #400000;
        border: tall red;
        color: red;
    }

    /* ---- DataTable ---- */
    DataTable {
        background: #111111;
    }
    DataTable > .datatable--header {
        background: #1a1a1a;
        color: $accent;
        text-style: bold;
    }
    DataTable > .datatable--cursor {
        background: #003040;
        color: $accent;
    }

    /* ---- Input ---- */
    Input {
        background: #1a1a1a;
        border: tall $panel-lighten-1;
        color: $text;
    }
    Input:focus {
        border: tall $accent;
    }

    /* ---- Checkbox / RadioButton ---- */
    Checkbox {
        background: transparent;
        color: $text;
        margin: 0 1;
    }
    RadioButton {
        background: transparent;
        color: $text;
    }
    RadioButton.-on {
        color: $accent;
    }

    /* ---- Rule ---- */
    Rule {
        color: #333333;
        margin: 1 0;
    }

    /* ---- Scrollable containers ---- */
    ScrollableContainer {
        background: $background;
    }

    /* ---- Modal ---- */
    ModalScreen {
        background: rgba(0, 0, 0, 0.8);
    }
    """

    # ------------------------------------------------------------------
    # Constructor
    # ------------------------------------------------------------------

    def __init__(
        self,
        badge: BadgeAPI,
        *,
        pre_wire_loop: Optional[asyncio.AbstractEventLoop] = None,
    ) -> None:
        super().__init__()
        self._badge = badge
        self._callbacks_wired: bool = False
        self._flash_enabled: bool = True
        self._effect_mode: int = 0
        # Cache of current LED colors: {1: (r,g,b), ...}
        self._led_colors: dict[int, tuple[int, int, int]] = {
            1: (0, 0, 0),
            2: (0, 0, 0),
            3: (0, 0, 0),
            4: (0, 0, 0),
        }
        # Pre-wire callbacks when a loop is provided (dc29 start mode).
        # This establishes the TUI as the base of the bridge button-hook chain
        # so that bridges installed later can call through to the TUI for logging.
        if pre_wire_loop is not None:
            self._wire_badge_callbacks(loop=pre_wire_loop)

    # ------------------------------------------------------------------
    # Compose
    # ------------------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with TabbedContent(initial="dashboard", id="tabs"):
            with TabPane("Dashboard [1]", id="dashboard"):
                yield DashboardTab()
            with TabPane("Keys [2]", id="keys"):
                yield KeysTab()
            with TabPane("LEDs [3]", id="leds"):
                yield LEDsTab()
            with TabPane("Effects [4]", id="effects"):
                yield EffectsTab()
            with TabPane("Log [5]", id="log"):
                yield LogTab()
        yield Footer()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def on_mount(self) -> None:
        """Wire badge callbacks (if not already pre-wired) and update title."""
        if not self._callbacks_wired:
            self._wire_badge_callbacks()
        self._update_title()
        # Query existing keys from badge if connected
        if self._badge.connected:
            for i in range(1, 5):
                self._badge.query_key(i)

    def _wire_badge_callbacks(
        self, loop: Optional[asyncio.AbstractEventLoop] = None
    ) -> None:
        """Attach all badge callbacks, forwarding to the event loop via call_soon_threadsafe."""
        if loop is None:
            loop = asyncio.get_event_loop()

        def _ts(fn):
            """Wrap fn so it's called on the event loop thread."""
            def wrapper(*args, **kwargs):
                loop.call_soon_threadsafe(fn, *args, **kwargs)
            return wrapper

        @_ts
        def on_button_press(button: int, modifier: int, keycode: int) -> None:
            self.post_message(ButtonPressMessage(button, modifier, keycode))

        @_ts
        def on_key_reply(button: int, modifier: int, keycode: int) -> None:
            self.post_message(KeyReplyMessage(button, modifier, keycode))

        @_ts
        def on_key_ack(button: int) -> None:
            self.post_message(KeyAckMessage(button))

        @_ts
        def on_effect_mode(mode: int) -> None:
            self.post_message(EffectModeMessage(mode))

        @_ts
        def on_chord(chord_type: int) -> None:
            self.post_message(ChordMessage(chord_type))

        @_ts
        def on_connect() -> None:
            self.post_message(ConnectMessage())

        @_ts
        def on_disconnect() -> None:
            self.post_message(DisconnectMessage())

        @_ts
        def on_page_change(page) -> None:
            self.post_message(PageChangeMessage(page))

        self._badge.on_button_press = on_button_press
        self._badge.on_key_reply = on_key_reply
        self._badge.on_key_ack = on_key_ack
        self._badge.on_effect_mode = on_effect_mode
        self._badge.on_chord = on_chord
        self._badge.on_connect = on_connect
        self._badge.on_disconnect = on_disconnect
        self._badge.on_page_change = on_page_change
        self._callbacks_wired = True

    def _update_title(self) -> None:
        status = "●" if self._badge.connected else "○"
        color = "green" if self._badge.connected else "red"
        self.sub_title = f"{_VERSION}  [{color}]{status}[/]  {self._badge.port}"

    # ------------------------------------------------------------------
    # Badge message handlers
    # ------------------------------------------------------------------

    def on_connect_message(self, _: ConnectMessage) -> None:
        self._update_title()
        try:
            self.query_one(DashboardTab).update_connection(True)
        except NoMatches:
            pass
        self._log_event("[green]◉ Badge connected[/]")
        # Query current keys
        for i in range(1, 5):
            self._badge.query_key(i)

    def on_disconnect_message(self, _: DisconnectMessage) -> None:
        self._update_title()
        try:
            self.query_one(DashboardTab).update_connection(False)
        except NoMatches:
            pass
        self._log_event("[red]◌ Badge disconnected[/]")

    def on_button_press_message(self, event: ButtonPressMessage) -> None:
        hr = _human_readable(event.modifier, event.keycode)
        msg = f"[yellow]▶ BTN{event.button}[/] pressed  [dim]({hr})[/]"
        self._log_event(msg)
        try:
            self.query_one(DashboardTab).push_event(msg)
        except NoMatches:
            pass

    def on_key_reply_message(self, event: KeyReplyMessage) -> None:
        try:
            self.query_one(KeysTab).update_row(event.button, event.modifier, event.keycode)
        except NoMatches:
            pass
        hr = _human_readable(event.modifier, event.keycode)
        self._log_event(
            f"[dim]◈ BTN{event.button} keymap:[/] [cyan]{hr}[/]"
        )

    def on_key_ack_message(self, event: KeyAckMessage) -> None:
        self._log_event(f"[dim]✓ BTN{event.button} keymap saved[/]")

    def on_effect_mode_message(self, event: EffectModeMessage) -> None:
        self._effect_mode = event.mode
        names = {0: "Off", 1: "Rainbow Chase", 2: "Breathe"}
        name = names.get(event.mode, str(event.mode))
        self._log_event(f"[magenta]◎ Effect mode:[/] {name}")
        try:
            self.query_one(DashboardTab).update_effect(event.mode)
        except NoMatches:
            pass
        try:
            self.query_one(EffectsTab).set_effect_display(event.mode)
        except NoMatches:
            pass

    def on_chord_message(self, event: ChordMessage) -> None:
        kind = "short" if event.chord_type == 1 else "long"
        self._log_event(f"[cyan]♪ Chord ({kind})[/]")
        try:
            self.query_one(DashboardTab).push_event(f"[cyan]♪ Chord ({kind})[/]")
        except NoMatches:
            pass

    def on_page_change_message(self, event: PageChangeMessage) -> None:
        page = event.page
        try:
            self.query_one(DashboardTab).update_context_page(page)
        except NoMatches:
            pass
        if page is not None:
            self._log_event(f"[cyan]◈ Profile:[/] {page.name.upper()}")
        else:
            self._log_event("[dim]◈ Profile: none[/]")

    def on_log_line_message(self, event: LogLineMessage) -> None:
        self._log_event(event.markup)

    # ------------------------------------------------------------------
    # Internal LED/effect message handlers (from tab widgets)
    # ------------------------------------------------------------------

    @on(_ApplyLEDMessage)
    def _handle_apply_led(self, event: _ApplyLEDMessage) -> None:
        self._led_colors[event.n] = (event.r, event.g, event.b)
        self._badge.set_led(event.n, event.r, event.g, event.b)
        self._log_event(
            f"[dim]◈ LED{event.n} color:[/] "
            f"rgb({event.r}, {event.g}, {event.b})"
        )

    @on(_ApplyEffectMessage)
    def _handle_apply_effect(self, event: _ApplyEffectMessage) -> None:
        self._badge.set_effect_mode(event.mode)
        self._effect_mode = event.mode
        names = {0: "Off", 1: "Rainbow Chase", 2: "Breathe"}
        self._log_event(
            f"[magenta]◎ Effect set:[/] {names.get(event.mode, str(event.mode))}"
        )
        try:
            self.query_one(DashboardTab).update_effect(event.mode)
        except NoMatches:
            pass

    @on(_SetFlashMessage)
    def _handle_set_flash(self, event: _SetFlashMessage) -> None:
        self._flash_enabled = event.enabled
        self._badge.set_button_flash(event.enabled)
        state = "on" if event.enabled else "off"
        self._log_event(f"[dim]◈ Button flash:[/] {state}")

    @on(EditKeyModal.Saved)
    def _handle_key_saved(self, event: EditKeyModal.Saved) -> None:
        self._badge.set_key(event.button, event.modifier, event.keycode)
        try:
            self.query_one(KeysTab).update_row(event.button, event.modifier, event.keycode)
        except NoMatches:
            pass
        hr = _human_readable(event.modifier, event.keycode)
        self._log_event(
            f"[cyan]✎ BTN{event.button} keymap set:[/] {hr}"
        )

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def action_switch_tab(self, tab_id: str) -> None:
        try:
            self.query_one("#tabs", TabbedContent).active = tab_id
        except NoMatches:
            pass

    def action_rainbow(self) -> None:
        self._badge.set_effect_mode(EffectMode.RAINBOW_CHASE)
        self._effect_mode = EffectMode.RAINBOW_CHASE
        self._log_event("[magenta]◎ Effect set:[/] Rainbow Chase")
        try:
            self.query_one(DashboardTab).update_effect(EffectMode.RAINBOW_CHASE)
        except NoMatches:
            pass
        try:
            self.query_one(EffectsTab).set_effect_display(EffectMode.RAINBOW_CHASE)
        except NoMatches:
            pass

    def action_breathe(self) -> None:
        self._badge.set_effect_mode(EffectMode.BREATHE)
        self._effect_mode = EffectMode.BREATHE
        self._log_event("[magenta]◎ Effect set:[/] Breathe")
        try:
            self.query_one(DashboardTab).update_effect(EffectMode.BREATHE)
        except NoMatches:
            pass
        try:
            self.query_one(EffectsTab).set_effect_display(EffectMode.BREATHE)
        except NoMatches:
            pass

    def action_effect_off(self) -> None:
        self._badge.set_effect_mode(EffectMode.OFF)
        self._effect_mode = EffectMode.OFF
        self._log_event("[magenta]◎ Effect set:[/] Off")
        try:
            self.query_one(DashboardTab).update_effect(EffectMode.OFF)
        except NoMatches:
            pass
        try:
            self.query_one(EffectsTab).set_effect_display(EffectMode.OFF)
        except NoMatches:
            pass

    def action_toggle_flash(self) -> None:
        self._flash_enabled = not self._flash_enabled
        self._badge.set_button_flash(self._flash_enabled)
        state = "on" if self._flash_enabled else "off"
        self._log_event(f"[dim]◈ Button flash toggled:[/] {state}")
        try:
            self.query_one("#flash-toggle", Checkbox).value = self._flash_enabled
        except NoMatches:
            pass

    def action_help(self) -> None:
        self.push_screen(HelpScreen())

    def action_quit(self) -> None:
        self._badge.close()
        self.exit()

    # ------------------------------------------------------------------
    # Log handler integration (used by dc29 start)
    # ------------------------------------------------------------------

    def install_log_handler(
        self,
        loop: asyncio.AbstractEventLoop,
        level: int = logging.DEBUG,
    ) -> TuiLogHandler:
        """Attach a TuiLogHandler to the root logger and return it.

        Call this before starting bridges so their log output appears in the
        TUI's Log tab instead of stderr.  Pass the handler to
        ``remove_log_handler`` on shutdown.
        """
        handler = TuiLogHandler(loop, self.post_message)
        handler.setLevel(level)
        logging.getLogger().addHandler(handler)
        return handler

    def remove_log_handler(self, handler: TuiLogHandler) -> None:
        """Detach a previously installed TuiLogHandler from the root logger."""
        logging.getLogger().removeHandler(handler)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _log_event(self, markup: str) -> None:
        """Write a line to the Log tab's RichLog."""
        try:
            self.query_one(LogTab).write(markup)
        except NoMatches:
            pass
