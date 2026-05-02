"""
dc29/tui/app.py — Textual TUI for the DEF CON 29 badge macro-keypad.


Layout (single screen, tabbed):

  ┌─ DC29 Badge  ●  /dev/tty.usbmodem14201 ─────────────── v1.0.0  ?=help  q=quit ─┐
  │ [1] Dash [2] Keys [3] WLED [4] Effects [5] Bridges [6] Stats [7] Log [8] LEDs │
  ├─────────────────────────────────────────────────────────────────────────────────┤
  │  (tab content)                                                                  │
  └─────────────────────────────────────────────────────────────────────────────────┘

Keyboard shortcuts (global):
  1-8   Switch tabs
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

from textual import events, on
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
    ListItem,
    ListView,
    RadioButton,
    RadioSet,
    RichLog,
    Rule,
    Select,
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
            yield Label("  [yellow]1-8[/]   Switch tabs (Dashboard / Keys / WLED / Effects / Bridges / Stats / Log / LEDs)", markup=True, classes="help-row")
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
    """Tab 4: Effects & Paint — full WYSIWYG LED control surface.

    Sections:
      * Paint banner — surfaces when manual paint has auto-grabbed control
        (silently disabling bridges + effect; restorable with one click).
      * LED swatches — 4 colored cells you click to focus.
      * RGB / hex inputs — synced to the focused LED, drive live updates.
      * Built-in scenes — radio set of all firmware effect modes.
      * Saved scenes — Select dropdown + Play button for TOML scenes
        from ``~/.config/dc29/scenes/``.
      * Toggles — splash on press, button flash, sticky focus LEDs.
      * Brightness — global multiplier slider (Input).
    """

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
    EffectsTab .paint-banner {
        background: $warning 30%;
        color: $warning;
        text-style: bold;
        padding: 0 2;
        margin-bottom: 1;
        height: 3;
        border: solid $warning;
        display: none;
    }
    EffectsTab .paint-banner.-active {
        display: block;
    }
    EffectsTab .paint-banner.-locked {
        background: $error 30%;
        color: $error;
        border: solid $error;
    }
    EffectsTab #swatch-row {
        height: 5;
        margin-bottom: 1;
    }
    EffectsTab .led-swatch {
        width: 1fr;
        height: 5;
        border: solid $panel-lighten-2;
        text-align: center;
        content-align: center middle;
    }
    EffectsTab .led-swatch.-selected {
        border: thick $accent;
    }
    EffectsTab #color-controls {
        height: auto;
        padding: 1;
        border: solid $panel-lighten-1;
        margin-bottom: 1;
    }
    EffectsTab #color-controls Input {
        width: 12;
    }
    EffectsTab #color-controls Label {
        width: 4;
        content-align: right middle;
    }
    EffectsTab #color-controls Horizontal {
        height: 3;
        margin-bottom: 0;
    }
    EffectsTab #hex-input {
        width: 14;
    }
    EffectsTab #scene-section {
        margin-top: 1;
    }
    EffectsTab RadioSet {
        margin-bottom: 1;
        border: solid $panel-lighten-1;
        padding: 1;
        height: auto;
    }
    EffectsTab #toggles-section {
        margin-top: 2;
    }
    EffectsTab #brightness-row {
        height: 3;
        margin-top: 1;
    }
    EffectsTab .scene-row {
        height: 3;
        margin-bottom: 1;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        # Per-LED current color cache (TUI-side mirror; updated on any paint).
        self._led_colors: dict[int, tuple[int, int, int]] = {
            1: (0, 0, 0), 2: (0, 0, 0), 3: (0, 0, 0), 4: (0, 0, 0),
        }
        self._selected_led: int = 1

    def compose(self) -> ComposeResult:
        # Paint-mode banner — hidden by default, shown when paint engages.
        yield Label("", id="paint-banner", classes="paint-banner")

        yield Label("PAINT", classes="section-title")
        yield Label(
            "Click an LED to focus, then drag the RGB inputs or type a hex code. "
            "Updates apply live.  Press 'Apply to all' to slap the picked color "
            "on every LED at once.",
            classes="desc",
        )
        with Horizontal(id="swatch-row"):
            yield Static("LED 1\n\n", id="swatch-1", classes="led-swatch -selected")
            yield Static("LED 2\n\n", id="swatch-2", classes="led-swatch")
            yield Static("LED 3\n\n", id="swatch-3", classes="led-swatch")
            yield Static("LED 4\n\n", id="swatch-4", classes="led-swatch")

        with Vertical(id="color-controls"):
            with Horizontal():
                yield Label("R")
                yield Input(value="0", id="rgb-r", type="integer", restrict=r"[0-9]*")
                yield Label("G")
                yield Input(value="0", id="rgb-g", type="integer", restrict=r"[0-9]*")
                yield Label("B")
                yield Input(value="0", id="rgb-b", type="integer", restrict=r"[0-9]*")
            with Horizontal():
                yield Label("Hex")
                yield Input(value="#000000", id="hex-input")
                yield Button("Apply to all LEDs", id="apply-all", variant="primary")
                yield Button("All off", id="all-off")

        yield Rule()

        with Vertical(id="scene-section"):
            yield Label("BUILT-IN SCENES (firmware effect modes)", classes="section-title")
            yield Label(
                "Animations that run on the badge itself, no host needed. "
                "Selecting a scene auto-suspends bridges (Teams meeting excepted).",
                classes="desc",
            )
            with RadioSet(id="effect-radio"):
                yield RadioButton("Off", id="eff-0", value=True)
                yield RadioButton("Rainbow Chase", id="eff-1")
                yield RadioButton("Breathe", id="eff-2")
                yield RadioButton("Wipe", id="eff-3")
                yield RadioButton("Twinkle", id="eff-4")
                yield RadioButton("Gradient", id="eff-5")
                yield RadioButton("Theater", id="eff-6")
                yield RadioButton("Cylon", id="eff-7")
                yield RadioButton("Particles (2D physics)", id="eff-8")
            yield Label(
                "Static EEPROM colors — no animation.",
                id="effect-desc", classes="desc",
            )
            yield Button("Apply Scene", id="apply-effect", variant="primary")

        yield Rule()

        yield Label("SAVED SCENES (TOML)", classes="section-title")
        yield Label(
            "Scenes saved under ~/.config/dc29/scenes/.  Build new ones from "
            "the shell with `dc29 scene save` or write the TOML directly.",
            classes="desc",
        )
        with Horizontal(classes="scene-row"):
            yield Select(
                [("(refresh to load)", "")],
                id="scene-select",
                allow_blank=False,
                prompt="Pick a saved scene",
            )
            yield Button("Play", id="play-scene", variant="primary")
            yield Button("Stop", id="stop-scene")
            yield Button("Refresh", id="refresh-scenes")

        yield Rule()

        with Vertical(id="toggles-section"):
            yield Label("TOGGLES", classes="section-title")
            yield Checkbox("Splash on press (fidget toy: poke during a light show)", id="splash-toggle", value=True)
            yield Checkbox("Button flash (long takeover on key send)", id="flash-toggle", value=True)
            yield Checkbox("Sticky focus LEDs (keep last page colors on focus loss)", id="sticky-toggle", value=False)
            with Horizontal(id="brightness-row"):
                yield Label("Brightness:")
                yield Input(value="100", id="brightness-input", type="integer", restrict=r"[0-9]*")
                yield Label("% (0–100)", classes="desc")
                yield Button("Apply", id="apply-brightness")

    # ------------------------------------------------------------------
    # Compose lifecycle
    # ------------------------------------------------------------------

    def on_mount(self) -> None:
        self._refresh_scene_list()
        self._render_swatches()

    def _refresh_scene_list(self) -> None:
        from dc29.scenes import list_scenes
        try:
            paths = list_scenes()
        except Exception:
            paths = []
        sel = self.query_one("#scene-select", Select)
        if not paths:
            sel.set_options([("(no scenes saved)", "")])
        else:
            sel.set_options([(p.stem, str(p)) for p in paths])

    # ------------------------------------------------------------------
    # Swatch + RGB sync
    # ------------------------------------------------------------------

    def _render_swatches(self) -> None:
        for n in (1, 2, 3, 4):
            try:
                sw = self.query_one(f"#swatch-{n}", Static)
            except NoMatches:
                continue
            r, g, b = self._led_colors[n]
            # Style the cell's background to its color.
            sw.styles.background = Color(r, g, b)
            # Pick a contrasting label color.
            lum = 0.299 * r + 0.587 * g + 0.114 * b
            sw.styles.color = "white" if lum < 128 else "black"
            sel = " (selected)" if n == self._selected_led else ""
            sw.update(f"LED {n}{sel}\n#{r:02X}{g:02X}{b:02X}")

    def _sync_inputs_to_color(self, color: tuple[int, int, int]) -> None:
        r, g, b = color
        for sid, v in (("rgb-r", r), ("rgb-g", g), ("rgb-b", b)):
            inp = self.query_one(f"#{sid}", Input)
            with inp.prevent(Input.Changed, Input.Submitted):
                inp.value = str(v)
        hexin = self.query_one("#hex-input", Input)
        with hexin.prevent(Input.Changed, Input.Submitted):
            hexin.value = f"#{r:02X}{g:02X}{b:02X}"

    @on(events.Click, ".led-swatch")
    def _select_swatch(self, event: events.Click) -> None:
        sid = (event.widget.id if event.widget else "") or ""
        if not sid.startswith("swatch-"):
            return
        try:
            n = int(sid.split("-")[1])
        except ValueError:
            return
        # Update selected state visually
        for k in (1, 2, 3, 4):
            try:
                w = self.query_one(f"#swatch-{k}", Static)
                if k == n:
                    w.add_class("-selected")
                else:
                    w.remove_class("-selected")
            except NoMatches:
                pass
        self._selected_led = n
        self._sync_inputs_to_color(self._led_colors[n])
        self._render_swatches()

    def _current_input_color(self) -> Optional[tuple[int, int, int]]:
        try:
            r = int(self.query_one("#rgb-r", Input).value or "0")
            g = int(self.query_one("#rgb-g", Input).value or "0")
            b = int(self.query_one("#rgb-b", Input).value or "0")
        except ValueError:
            return None
        if not all(0 <= c <= 255 for c in (r, g, b)):
            return None
        return (r, g, b)

    @on(Input.Changed, "#rgb-r,#rgb-g,#rgb-b")
    def _rgb_changed(self, event: Input.Changed) -> None:
        color = self._current_input_color()
        if color is None:
            return
        # Sync hex display
        hexin = self.query_one("#hex-input", Input)
        with hexin.prevent(Input.Changed, Input.Submitted):
            hexin.value = f"#{color[0]:02X}{color[1]:02X}{color[2]:02X}"
        # Live paint
        self._led_colors[self._selected_led] = color
        self._render_swatches()
        self.app.post_message(_PaintLEDMessage(self._selected_led, color))

    @on(Input.Submitted, "#hex-input")
    @on(Input.Changed, "#hex-input")
    def _hex_changed(self, event) -> None:
        val = self.query_one("#hex-input", Input).value.strip()
        if not val.startswith("#") or len(val) != 7:
            return
        try:
            r = int(val[1:3], 16); g = int(val[3:5], 16); b = int(val[5:7], 16)
        except ValueError:
            return
        # Sync RGB inputs
        for sid, v in (("rgb-r", r), ("rgb-g", g), ("rgb-b", b)):
            inp = self.query_one(f"#{sid}", Input)
            with inp.prevent(Input.Changed, Input.Submitted):
                inp.value = str(v)
        self._led_colors[self._selected_led] = (r, g, b)
        self._render_swatches()
        self.app.post_message(_PaintLEDMessage(self._selected_led, (r, g, b)))

    @on(Button.Pressed, "#apply-all")
    def _apply_all(self) -> None:
        color = self._current_input_color()
        if color is None:
            return
        for n in (1, 2, 3, 4):
            self._led_colors[n] = color
        self._render_swatches()
        self.app.post_message(_PaintAllMessage(color, color, color, color))

    @on(Button.Pressed, "#all-off")
    def _all_off(self) -> None:
        for n in (1, 2, 3, 4):
            self._led_colors[n] = (0, 0, 0)
        self._render_swatches()
        self._sync_inputs_to_color((0, 0, 0))
        self.app.post_message(_PaintAllMessage((0, 0, 0), (0, 0, 0), (0, 0, 0), (0, 0, 0)))

    # ------------------------------------------------------------------
    # Scene controls
    # ------------------------------------------------------------------

    @on(RadioSet.Changed, "#effect-radio")
    def _radio_changed(self, event: RadioSet.Changed) -> None:
        from dc29.protocol import EFFECT_DESCRIPTIONS, EffectMode
        idx = event.radio_set.pressed_index
        desc = EFFECT_DESCRIPTIONS.get(idx, "")
        self.query_one("#effect-desc", Label).update(desc)

    @on(Button.Pressed, "#apply-effect")
    def _apply_effect(self) -> None:
        radio = self.query_one("#effect-radio", RadioSet)
        idx = radio.pressed_index
        self.app.post_message(_ApplyEffectMessage(idx))

    @on(Button.Pressed, "#play-scene")
    def _play_scene(self) -> None:
        sel = self.query_one("#scene-select", Select)
        path = sel.value
        if not path:
            return
        self.app.post_message(_PlaySceneMessage(path=str(path)))

    @on(Button.Pressed, "#stop-scene")
    def _stop_scene(self) -> None:
        self.app.post_message(_StopSceneMessage())

    @on(Button.Pressed, "#refresh-scenes")
    def _refresh_scenes(self) -> None:
        self._refresh_scene_list()

    @on(Button.Pressed, "#apply-brightness")
    def _apply_brightness(self) -> None:
        try:
            pct = int(self.query_one("#brightness-input", Input).value or "100")
        except ValueError:
            return
        pct = max(0, min(100, pct))
        self.app.post_message(_SetBrightnessMessage(pct / 100.0))

    # ------------------------------------------------------------------
    # Toggle handlers — dispatch the existing TUI messages
    # ------------------------------------------------------------------

    @on(Checkbox.Changed, "#flash-toggle")
    def _flash_toggle(self, event: Checkbox.Changed) -> None:
        self.app.post_message(_SetFlashMessage(event.value))

    @on(Checkbox.Changed, "#splash-toggle")
    def _splash_toggle(self, event: Checkbox.Changed) -> None:
        self.app.post_message(_SetSplashMessage(event.value))

    @on(Checkbox.Changed, "#sticky-toggle")
    def _sticky_toggle_eff(self, event: Checkbox.Changed) -> None:
        self.app.post_message(_SetStickyMessage(event.value))

    # ------------------------------------------------------------------
    # External — called by BadgeTUI to keep TUI state in sync
    # ------------------------------------------------------------------

    def set_led_color(self, n: int, color: tuple[int, int, int]) -> None:
        """Reflect a remote LED change (e.g. bridge update) into the swatches."""
        if n in self._led_colors:
            self._led_colors[n] = color
            self._render_swatches()
            if n == self._selected_led:
                self._sync_inputs_to_color(color)

    def set_effect_display(self, mode: int) -> None:
        try:
            radio = self.query_one("#effect-radio", RadioSet)
            radio.pressed_index = max(0, min(7, mode))
        except Exception:
            pass

    def set_paint_banner(self, *, active: bool, locked: bool = False, message: str = "") -> None:
        """Show or hide the paint-mode banner.

        Args:
            active:  ``True`` to show.
            locked:  ``True`` to render as the "locked by Teams meeting" variant
                     (red accent instead of warning yellow).
            message: Optional text to display in the banner.
        """
        try:
            banner = self.query_one("#paint-banner", Label)
        except NoMatches:
            return
        if active:
            banner.add_class("-active")
        else:
            banner.remove_class("-active")
        if locked:
            banner.add_class("-locked")
        else:
            banner.remove_class("-locked")
        banner.update(message)

    def set_sticky_display(self, enabled: bool) -> None:
        try:
            cb = self.query_one("#sticky-toggle", Checkbox)
            with cb.prevent(Checkbox.Changed):
                cb.value = enabled
        except Exception:
            pass

    def set_splash_display(self, enabled: bool) -> None:
        try:
            cb = self.query_one("#splash-toggle", Checkbox)
            with cb.prevent(Checkbox.Changed):
                cb.value = enabled
        except Exception:
            pass

    @on(Checkbox.Changed, "#sticky-toggle")
    def _sticky_toggle(self, event: Checkbox.Changed) -> None:
        self.app.post_message(_SetStickyMessage(event.value))

    def set_sticky_display(self, enabled: bool) -> None:
        """Update the checkbox to reflect the current config value (no message dispatch)."""
        try:
            cb = self.query_one("#sticky-toggle", Checkbox)
            with cb.prevent(Checkbox.Changed):
                cb.value = enabled
        except Exception:
            pass

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


class _SetStickyMessage(Message):
    def __init__(self, enabled: bool) -> None:
        super().__init__()
        self.enabled = enabled


class _SetBridgeEnabledMessage(Message):
    def __init__(self, name: str, enabled: bool) -> None:
        super().__init__()
        self.name = name
        self.enabled = enabled


class _SetSliderEnabledMessage(Message):
    def __init__(self, enabled: bool) -> None:
        super().__init__()
        self.enabled = enabled


class _SetSplashMessage(Message):
    def __init__(self, enabled: bool) -> None:
        super().__init__()
        self.enabled = enabled


class _PaintLEDMessage(Message):
    """Paint a single LED — fired by RGB/hex input changes."""
    def __init__(self, led: int, color: tuple[int, int, int]) -> None:
        super().__init__()
        self.led = led
        self.color = color


class _PaintAllMessage(Message):
    """Paint all four LEDs atomically — fired by 'Apply to all' button."""
    def __init__(
        self,
        c1: tuple[int, int, int],
        c2: tuple[int, int, int],
        c3: tuple[int, int, int],
        c4: tuple[int, int, int],
    ) -> None:
        super().__init__()
        self.colors = (c1, c2, c3, c4)


class _PlaySceneMessage(Message):
    """Play a saved scene from a file path."""
    def __init__(self, path: str) -> None:
        super().__init__()
        self.path = path


class _StopSceneMessage(Message):
    """Stop the currently playing scene."""
    pass


class _SetBrightnessMessage(Message):
    """Set the BadgeAPI brightness scalar (0.0..1.0)."""
    def __init__(self, scale: float) -> None:
        super().__init__()
        self.scale = scale


class _ApplyWledMessage(Message):
    """Apply a WLED runtime knob change (palette/speed/intensity).

    Any field set to ``None`` means "leave unchanged"; the host handler
    holds the current values and only writes a 0x01 'W' command when at
    least one field is non-None.
    """
    def __init__(
        self,
        palette: int | None = None,
        speed: int | None = None,
        intensity: int | None = None,
    ) -> None:
        super().__init__()
        self.palette = palette
        self.speed = speed
        self.intensity = intensity


# ---------------------------------------------------------------------------
# WLED Tab — pick effect, pick palette, tweak the knobs
# ---------------------------------------------------------------------------


class WledTab(Container):
    """WLED-inspired control surface — effect grid, palette grid, knobs.

    Inspired by the WLED web UI: a scrollable list of every effect mode
    (0–34, including hand-rolled and WLED ports), a column of palette
    swatches showing the actual colors, and Speed/Intensity knobs with
    typed input + nudge buttons + visual fill bars.

    Selecting an effect or palette applies it instantly to the badge.
    Nudging a knob debounces through ``_ApplyWledMessage`` so the badge
    isn't spammed on rapid clicks.

    Hand-rolled effects (modes 1–18) ignore the palette + knob settings —
    they're hard-coded.  WLED-ported effects (19–34) honor all three.
    The footer summary calls this out so you don't think the palette
    selector is broken when it doesn't change a hand-rolled effect.
    """

    DEFAULT_CSS = """
    WledTab {
        padding: 1 2;
    }
    WledTab .section-title {
        color: $accent;
        text-style: bold;
        margin-bottom: 1;
    }
    WledTab .desc {
        color: $text-muted;
        margin-bottom: 1;
    }
    WledTab #effect-list {
        height: 1fr;
        min-height: 14;
        border: solid $panel-lighten-1;
        margin-bottom: 1;
    }
    WledTab #effect-list ListItem {
        padding: 0 1;
    }
    WledTab #effect-list ListItem.--highlight {
        background: $accent 20%;
    }
    WledTab #effect-list ListItem.-active {
        background: $accent 40%;
        text-style: bold;
    }
    WledTab #lower-row {
        height: 18;
    }
    WledTab #palette-section {
        width: 38;
        border: solid $panel-lighten-1;
        padding: 1;
        margin-right: 1;
    }
    WledTab #palette-list {
        height: 1fr;
        min-height: 10;
    }
    WledTab #palette-list ListItem {
        padding: 0 1;
    }
    WledTab #palette-list ListItem.-active {
        background: $accent 40%;
        text-style: bold;
    }
    WledTab #knobs-section {
        width: 1fr;
        border: solid $panel-lighten-1;
        padding: 1;
    }
    WledTab .knob-row {
        height: 3;
        margin-bottom: 1;
    }
    WledTab .knob-row Label {
        width: 12;
        content-align: left middle;
    }
    WledTab .knob-row Input {
        width: 7;
    }
    WledTab .knob-row Button {
        width: 5;
        margin-left: 0;
    }
    WledTab .knob-bar {
        margin-left: 1;
        color: $accent;
    }
    WledTab #status-line {
        margin-top: 1;
        padding: 0 1;
        color: $text-muted;
    }
    WledTab #effect-desc {
        color: $text-muted;
        padding: 0 1;
        margin-bottom: 1;
        height: 1;
    }
    """

    # Internal state — kept here so the host's _ApplyWledMessage handler
    # only has to read the message, not look up the current sliders.
    _speed: int = 128
    _intensity: int = 128
    _palette: int = 0
    _effect: int = 0

    def compose(self) -> ComposeResult:
        from dc29.protocol import (
            EFFECT_NAMES,
            EFFECT_DESCRIPTIONS,
            WledPalette,
            WLED_PALETTE_NAMES,
            palette_swatch_markup,
        )

        yield Label("WLED — pick an effect, pick a color scheme, tweak the knobs.", classes="desc")
        yield Label(
            "Inspired by the WLED web UI.  Hand-rolled modes (1–18) ignore the "
            "palette + knobs; WLED ports (19–34) honor all three.",
            classes="desc",
        )

        yield Label("EFFECT", classes="section-title")
        effect_items: list[ListItem] = []
        for mode_id, name in EFFECT_NAMES.items():
            kind = "hand-rolled" if 1 <= mode_id <= 18 else ("WLED port" if mode_id >= 19 else "static")
            label = f"{mode_id:>2}  {name:<18}  [dim]{kind}[/]"
            item = ListItem(Label(label), id=f"wled-eff-{mode_id}")
            if mode_id == 0:
                item.add_class("-active")
            effect_items.append(item)
        yield ListView(*effect_items, id="effect-list", initial_index=0)
        yield Label(EFFECT_DESCRIPTIONS.get(0, ""), id="effect-desc")

        with Horizontal(id="lower-row"):
            with Vertical(id="palette-section"):
                yield Label("PALETTE (color scheme)", classes="section-title")
                yield Label(
                    "Click to apply.  Swatches are sampled from the firmware LUT.",
                    classes="desc",
                )
                palette_items: list[ListItem] = []
                for pid, pname in WLED_PALETTE_NAMES.items():
                    swatch = palette_swatch_markup(pid, blocks=8)
                    label = f"{swatch}  {pname}"
                    item = ListItem(Label(label), id=f"wled-pal-{pid}")
                    if pid == WledPalette.RAINBOW:
                        item.add_class("-active")
                    palette_items.append(item)
                yield ListView(*palette_items, id="palette-list", initial_index=0)

            with Vertical(id="knobs-section"):
                yield Label("KNOBS", classes="section-title")
                yield Label(
                    "Speed = timebase.  Intensity = effect-specific 'amount' "
                    "(fade rate, sparkle density, wave width).",
                    classes="desc",
                )

                with Horizontal(classes="knob-row"):
                    yield Label("Speed:")
                    yield Input(value="128", id="speed-input", restrict=r"[0-9]*")
                    yield Button("-25", id="speed-dec25")
                    yield Button(" -1", id="speed-dec1")
                    yield Button(" +1", id="speed-inc1")
                    yield Button("+25", id="speed-inc25")
                yield Static(self._render_bar(128), id="speed-bar", classes="knob-bar")

                with Horizontal(classes="knob-row"):
                    yield Label("Intensity:")
                    yield Input(value="128", id="intensity-input", restrict=r"[0-9]*")
                    yield Button("-25", id="intensity-dec25")
                    yield Button(" -1", id="intensity-dec1")
                    yield Button(" +1", id="intensity-inc1")
                    yield Button("+25", id="intensity-inc25")
                yield Static(self._render_bar(128), id="intensity-bar", classes="knob-bar")

                yield Static(self._render_status(), id="status-line")

    # ------------------------------------------------------------------
    # Visual helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _render_bar(value: int, width: int = 32) -> str:
        """Return a Unicode fill bar showing where ``value`` sits in 0..255."""
        v = max(0, min(255, int(value)))
        filled = (v * width) // 255
        return f"[$accent]{'█' * filled}[/][dim]{'░' * (width - filled)}[/]  {v:>3}/255"

    def _render_status(self) -> str:
        from dc29.protocol import EFFECT_NAMES, WLED_PALETTE_NAMES
        eff_name = EFFECT_NAMES.get(self._effect, str(self._effect))
        pal_name = WLED_PALETTE_NAMES.get(self._palette, str(self._palette))
        is_wled = self._effect >= 19
        marker = "[green]●[/] honors palette + knobs" if is_wled else "[yellow]○[/] ignores palette + knobs"
        return (
            f"[bold]Active:[/] effect [cyan]#{self._effect}[/] [dim]({eff_name})[/]  "
            f"·  palette [cyan]{pal_name}[/]  ·  speed {self._speed}  ·  intensity {self._intensity}\n"
            f"      {marker}"
        )

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    @on(ListView.Selected, "#effect-list")
    def _effect_selected(self, event: ListView.Selected) -> None:
        item_id = event.item.id or ""
        if not item_id.startswith("wled-eff-"):
            return
        try:
            mode = int(item_id.removeprefix("wled-eff-"))
        except ValueError:
            return
        self._set_active("effect", mode)
        self._effect = mode
        from dc29.protocol import EFFECT_DESCRIPTIONS
        self.query_one("#effect-desc", Label).update(EFFECT_DESCRIPTIONS.get(mode, ""))
        self.query_one("#status-line", Static).update(self._render_status())
        self.app.post_message(_ApplyEffectMessage(mode))

    @on(ListView.Selected, "#palette-list")
    def _palette_selected(self, event: ListView.Selected) -> None:
        item_id = event.item.id or ""
        if not item_id.startswith("wled-pal-"):
            return
        try:
            pid = int(item_id.removeprefix("wled-pal-"))
        except ValueError:
            return
        self._set_active("palette", pid)
        self._palette = pid
        self.query_one("#status-line", Static).update(self._render_status())
        self.app.post_message(_ApplyWledMessage(palette=pid))

    @on(Input.Submitted, "#speed-input")
    def _speed_submitted(self, event: Input.Submitted) -> None:
        self._apply_knob_input("speed", event.value)

    @on(Input.Submitted, "#intensity-input")
    def _intensity_submitted(self, event: Input.Submitted) -> None:
        self._apply_knob_input("intensity", event.value)

    @on(Button.Pressed)
    def _knob_button(self, event: Button.Pressed) -> None:
        bid = event.button.id or ""
        # Button IDs are encoded as "<knob>-<signed_delta>", e.g. "speed--25",
        # "speed--1", "speed-+1", "speed-+25".  Strip the knob prefix and look
        # the suffix up in the delta map.
        if bid.startswith("speed-"):
            self._nudge("speed", bid.removeprefix("speed-"))
        elif bid.startswith("intensity-"):
            self._nudge("intensity", bid.removeprefix("intensity-"))

    # ------------------------------------------------------------------
    # Internal — knob plumbing
    # ------------------------------------------------------------------

    def _nudge(self, knob: str, suffix: str) -> None:
        """Apply +1 / -1 / +25 / -25 to the named knob and re-emit.

        ``suffix`` is the part of the button id after ``"<knob>-"``, e.g.
        ``dec25``, ``dec1``, ``inc1``, ``inc25``.
        """
        delta_map = {"dec25": -25, "dec1": -1, "inc1": 1, "inc25": 25}
        if suffix not in delta_map:
            return
        delta = delta_map[suffix]
        if knob == "speed":
            self._speed = max(0, min(255, self._speed + delta))
            self._refresh_knob("speed", self._speed)
            self.app.post_message(_ApplyWledMessage(speed=self._speed))
        else:
            self._intensity = max(0, min(255, self._intensity + delta))
            self._refresh_knob("intensity", self._intensity)
            self.app.post_message(_ApplyWledMessage(intensity=self._intensity))

    def _apply_knob_input(self, knob: str, raw: str) -> None:
        """Handle user typing a value into a knob's Input box."""
        try:
            v = int(raw)
        except ValueError:
            return
        v = max(0, min(255, v))
        if knob == "speed":
            self._speed = v
            self._refresh_knob("speed", v)
            self.app.post_message(_ApplyWledMessage(speed=v))
        else:
            self._intensity = v
            self._refresh_knob("intensity", v)
            self.app.post_message(_ApplyWledMessage(intensity=v))

    def _refresh_knob(self, knob: str, value: int) -> None:
        try:
            inp = self.query_one(f"#{knob}-input", Input)
            with inp.prevent(Input.Changed, Input.Submitted):
                inp.value = str(value)
            self.query_one(f"#{knob}-bar", Static).update(self._render_bar(value))
            self.query_one("#status-line", Static).update(self._render_status())
        except NoMatches:
            pass

    def _set_active(self, kind: str, item_id: int) -> None:
        """Move the .-active class to the newly selected item."""
        list_id = "#effect-list" if kind == "effect" else "#palette-list"
        prefix = "wled-eff-" if kind == "effect" else "wled-pal-"
        try:
            lv = self.query_one(list_id, ListView)
            for child in lv.children:
                if isinstance(child, ListItem):
                    child.remove_class("-active")
            target = self.query_one(f"#{prefix}{item_id}", ListItem)
            target.add_class("-active")
        except NoMatches:
            pass

    # ------------------------------------------------------------------
    # External API — host calls these to keep the TUI in sync
    # ------------------------------------------------------------------

    def set_effect_display(self, mode: int) -> None:
        """Reflect a remote effect change (chord cycle, CLI, etc.)."""
        from dc29.protocol import EFFECT_NAMES, EFFECT_DESCRIPTIONS
        if mode not in EFFECT_NAMES:
            return
        self._effect = mode
        try:
            self._set_active("effect", mode)
            lv = self.query_one("#effect-list", ListView)
            # Find index of the selected mode and scroll/highlight it
            for idx, child in enumerate(lv.children):
                if isinstance(child, ListItem) and child.id == f"wled-eff-{mode}":
                    lv.index = idx
                    break
            self.query_one("#effect-desc", Label).update(EFFECT_DESCRIPTIONS.get(mode, ""))
            self.query_one("#status-line", Static).update(self._render_status())
        except NoMatches:
            pass

    def set_wled_display(self, *, palette: int | None = None, speed: int | None = None, intensity: int | None = None) -> None:
        """Reflect a remote WLED-knob change without re-emitting it."""
        if palette is not None:
            self._palette = palette
            self._set_active("palette", palette)
        if speed is not None:
            self._speed = max(0, min(255, speed))
            self._refresh_knob("speed", self._speed)
        if intensity is not None:
            self._intensity = max(0, min(255, intensity))
            self._refresh_knob("intensity", self._intensity)
        try:
            self.query_one("#status-line", Static).update(self._render_status())
        except NoMatches:
            pass


# ---------------------------------------------------------------------------
# Bridges & Inputs Tab
# ---------------------------------------------------------------------------


class BridgesTab(Container):
    """Tab 5: Per-bridge enable/disable list + hardware input toggles.

    Bridges hot-reload via :class:`BridgeManager` when toggled.  Hardware
    inputs (currently the capacitive touch slider) hot-reload via direct
    firmware commands — no restart needed for either kind.
    """

    DEFAULT_CSS = """
    BridgesTab {
        padding: 1 2;
    }
    BridgesTab .section-title {
        color: $accent;
        text-style: bold;
        margin-bottom: 1;
    }
    BridgesTab .desc {
        color: $text-muted;
        margin-bottom: 1;
        padding-left: 2;
    }
    BridgesTab .restart-hint {
        color: $warning;
        text-style: italic;
        margin-bottom: 1;
        padding-left: 2;
    }
    BridgesTab .bridge-row {
        height: auto;
    }
    """

    def compose(self) -> ComposeResult:
        from dc29.bridges.manifest import BRIDGE_MANIFEST
        from dc29.config import get_config

        cfg = get_config()
        enabled_bridges = cfg.enabled_bridges

        yield Label("BRIDGES", classes="section-title")
        yield Label(
            "Each bridge is an integration with one app. Bridges are off by default — "
            "enable only what you actually use to keep the focus poll budget small.",
            classes="desc",
        )
        yield Label(
            "⟳  Toggling here starts or stops the bridge live — no restart needed.",
            classes="restart-hint",
        )
        yield Rule()
        for spec in BRIDGE_MANIFEST:
            with Vertical(classes="bridge-row"):
                yield Checkbox(
                    f"{spec.name}  —  {spec.description}",
                    id=f"bridge-{spec.name}",
                    value=spec.name in enabled_bridges,
                )

        yield Rule()
        yield Label("HARDWARE INPUTS", classes="section-title")
        yield Label(
            "Firmware-level inputs.  Toggles here send a serial command to the "
            "badge live; settings are RAM-only on the firmware side and reset "
            "to the config default on every power cycle.",
            classes="desc",
        )
        yield Checkbox(
            "Capacitive touch slider — volume up / volume down",
            id="input-slider",
            value=cfg.slider_enabled,
        )

    @on(Checkbox.Changed)
    def _toggle(self, event: Checkbox.Changed) -> None:
        cb_id = event.checkbox.id or ""
        if cb_id.startswith("bridge-"):
            name = cb_id[len("bridge-"):]
            self.app.post_message(_SetBridgeEnabledMessage(name, event.value))
        elif cb_id == "input-slider":
            self.app.post_message(_SetSliderEnabledMessage(event.value))

    def refresh_from_config(self) -> None:
        """Sync every checkbox to the current Config (used after CLI/env loads)."""
        from dc29.bridges.manifest import BRIDGE_MANIFEST
        from dc29.config import get_config

        cfg = get_config()
        enabled_bridges = cfg.enabled_bridges
        for spec in BRIDGE_MANIFEST:
            try:
                cb = self.query_one(f"#bridge-{spec.name}", Checkbox)
                with cb.prevent(Checkbox.Changed):
                    cb.value = spec.name in enabled_bridges
            except Exception:
                pass
        try:
            cb = self.query_one("#input-slider", Checkbox)
            with cb.prevent(Checkbox.Changed):
                cb.value = cfg.slider_enabled
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Stats Tab
# ---------------------------------------------------------------------------


class StatsTab(Container):
    """Tab 6: Local-only fun stats — emails deleted, mute toggles, button thumps, etc.

    Reads :func:`dc29.stats.get_stats` and renders a friendly snapshot with a
    refresh button (plus auto-refresh every 5 seconds while the tab is mounted).
    A Reset button calls :meth:`_Stats.reset` after confirmation.
    """

    DEFAULT_CSS = """
    StatsTab {
        padding: 1 2;
    }
    StatsTab .section-title {
        color: $accent;
        text-style: bold;
        margin-bottom: 1;
    }
    StatsTab .desc {
        color: $text-muted;
        margin-bottom: 1;
        padding-left: 2;
    }
    StatsTab #stats-display {
        height: auto;
        padding: 1 2;
        border: solid $panel-lighten-1;
    }
    StatsTab #stats-controls {
        height: 3;
        margin-top: 1;
    }
    """

    def compose(self) -> ComposeResult:
        yield Label("LOCAL STATS", classes="section-title")
        yield Label(
            "Lifetime tally of nerd-fuel.  Stored at ~/.config/dc29/stats.toml. "
            "Never sent anywhere. Auto-saves every 30 seconds while dc29 runs.",
            classes="desc",
        )
        yield Static("(loading…)", id="stats-display")
        with Horizontal(id="stats-controls"):
            yield Button("Refresh", id="stats-refresh")
            yield Button("Reset all", id="stats-reset", variant="error")

    def on_mount(self) -> None:
        self.refresh_display()
        # Auto-refresh every 5 seconds.
        self.set_interval(5.0, self.refresh_display)

    def refresh_display(self) -> None:
        from dc29.stats import render_summary
        try:
            self.query_one("#stats-display", Static).update(render_summary())
        except NoMatches:
            pass

    @on(Button.Pressed, "#stats-refresh")
    def _refresh(self) -> None:
        self.refresh_display()

    @on(Button.Pressed, "#stats-reset")
    def _reset(self) -> None:
        # Confirm with a small modal pattern — for now, single-click reset
        # with the warning baked into the button styling.  Could promote to
        # a real ConfirmModal later if folks delete-by-accident.
        from dc29.stats import get_stats
        get_stats().reset()
        self.refresh_display()
        self.app.post_message(_StatsResetMessage())


class _StatsResetMessage(Message):
    """Posted by StatsTab after a reset, so BadgeTUI can log it."""
    pass


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
        Binding("3", "switch_tab('wled')", "WLED", show=False),
        Binding("4", "switch_tab('effects')", "Effects", show=False),
        Binding("5", "switch_tab('bridges')", "Bridges", show=False),
        Binding("6", "switch_tab('stats')", "Stats", show=False),
        Binding("7", "switch_tab('log')", "Log", show=False),
        Binding("8", "switch_tab('leds')", "LEDs", show=False),
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
        bridge_manager=None,
    ) -> None:
        super().__init__()
        self._badge = badge
        self._bridge_manager = bridge_manager
        """Optional :class:`BridgeManager` for live hot-toggle of bridges.

        Provided by ``dc29 start``; absent in ``dc29 ui`` mode.  When absent,
        bridge toggles still update the live :class:`Config` but the user has
        to restart for the change to take effect — surface that in the UI.
        """
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
        # Paint mode state — engaged when the user starts painting/picking
        # scenes manually.  Saves the suspended state for restore.
        self._paint_mode_active: bool = False
        self._paint_saved_bridges: set = set()
        self._paint_saved_effect: int = 0
        # Currently-playing scene task, if any (set by _handle_play_scene).
        self._active_scene_task = None
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
            with TabPane("WLED [3]", id="wled"):
                yield WledTab()
            with TabPane("Effects [4]", id="effects"):
                yield EffectsTab()
            with TabPane("Bridges & Inputs [5]", id="bridges"):
                yield BridgesTab()
            with TabPane("Stats [6]", id="stats"):
                yield StatsTab()
            with TabPane("Log [7]", id="log"):
                yield LogTab()
            with TabPane("LEDs [8]", id="leds"):
                yield LEDsTab()
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
        # Sync the Sticky-LEDs checkbox to whatever was set by CLI flag or config file.
        try:
            from dc29.config import get_config
            self.query_one(EffectsTab).set_sticky_display(get_config().sticky_focus_leds)
        except Exception:
            pass

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

    # _handle_apply_effect superseded by paint-aware version below.
    # See the @on(_ApplyEffectMessage) handler under "Paint mode + scenes".

    @on(_SetFlashMessage)
    def _handle_set_flash(self, event: _SetFlashMessage) -> None:
        self._flash_enabled = event.enabled
        self._badge.set_button_flash(event.enabled)
        state = "on" if event.enabled else "off"
        self._log_event(f"[dim]◈ Button flash:[/] {state}")

    @on(_SetStickyMessage)
    def _handle_set_sticky(self, event: _SetStickyMessage) -> None:
        from dc29.config import get_config
        get_config().sticky_focus_leds = event.enabled
        state = "on (LEDs persist after focus loss)" if event.enabled else "off (LEDs clear on focus loss)"
        self._log_event(f"[dim]◈ Sticky focus LEDs:[/] {state}")

    @on(_SetSliderEnabledMessage)
    def _handle_set_slider(self, event: _SetSliderEnabledMessage) -> None:
        from dc29.config import get_config
        get_config().slider_enabled = event.enabled
        self._badge.set_slider_enabled(event.enabled)
        state = "enabled (volume keys live)" if event.enabled else "disabled (no volume injection)"
        self._log_event(f"[dim]◈ Slider:[/] {state}")

    @on(_SetBridgeEnabledMessage)
    def _handle_set_bridge_enabled(self, event: _SetBridgeEnabledMessage) -> None:
        from dc29.config import get_config
        get_config().set_bridge_enabled(event.name, event.enabled)
        verb = "enabled" if event.enabled else "disabled"
        if self._bridge_manager is not None:
            started, stopped = self._bridge_manager.reconcile()
            if event.name in started:
                hint = "[dim](running now)[/]"
            elif event.name in stopped:
                hint = "[dim](stopped)[/]"
            else:
                hint = ""
        else:
            hint = "[dim](takes effect on next start — no bridge manager attached)[/]"
        self._log_event(
            f"[dim]◈ Bridge[/] [bold]{event.name}[/] {verb} {hint}".rstrip()
        )

    # ------------------------------------------------------------------
    # Paint mode + scenes — auto-grab control with Teams safety carve-out
    # ------------------------------------------------------------------

    def _engage_paint_mode(self) -> bool:
        """Suspend bridges + effect mode so manual paint owns the LEDs.

        Idempotent.  Returns ``True`` if paint mode is now (or already) live;
        ``False`` if blocked by a Teams meeting (the only hard exception).
        """
        from dc29.config import get_config
        from dc29.protocol import MuteState

        # Hard carve-out: never wrest LED4 from Teams during an active meeting.
        # The mute indicator is safety-critical — a clobbered LED4 could make
        # the user think they're muted when they aren't (or vice versa).
        if self._badge.state.mute_state != MuteState.NOT_IN_MEETING:
            try:
                eff = self.query_one(EffectsTab)
                eff.set_paint_banner(
                    active=True, locked=True,
                    message="🔒 Paint mode locked — Teams meeting active.  "
                            "Mute indicator owns LED 4 until the call ends.",
                )
            except Exception:
                pass
            return False

        if self._paint_mode_active:
            return True

        cfg = get_config()
        # Snapshot current state for restore.
        self._paint_saved_bridges = set(cfg.enabled_bridges)
        self._paint_saved_effect = self._badge.state.effect_mode
        self._paint_mode_active = True

        # Stop all bridges (silently — they can be restored).
        if self._bridge_manager is not None and cfg.enabled_bridges:
            cfg.enabled_bridges = set()
            self._bridge_manager.reconcile()

        # Suspend effect mode.
        if self._paint_saved_effect != 0:
            self._badge.set_effect_mode(0)

        try:
            eff = self.query_one(EffectsTab)
            eff.set_paint_banner(
                active=True, locked=False,
                message="🎨 Paint mode active — bridges + effect paused.  Click [Restore] in the log when done.",
            )
        except Exception:
            pass
        self._log_event(
            "[dim]◈ Paint mode engaged[/] — "
            f"{len(self._paint_saved_bridges)} bridge(s) suspended, "
            f"effect mode {self._paint_saved_effect} saved."
        )
        return True

    def _restore_from_paint_mode(self) -> None:
        if not self._paint_mode_active:
            return
        from dc29.config import get_config

        cfg = get_config()
        cfg.enabled_bridges = self._paint_saved_bridges
        if self._bridge_manager is not None:
            self._bridge_manager.reconcile()
        if self._paint_saved_effect != 0:
            self._badge.set_effect_mode(self._paint_saved_effect)

        self._paint_mode_active = False
        self._paint_saved_bridges = set()
        self._paint_saved_effect = 0

        try:
            eff = self.query_one(EffectsTab)
            eff.set_paint_banner(active=False)
        except Exception:
            pass
        self._log_event("[dim]◈ Paint mode released[/] — bridges + effect restored.")

    @on(_PaintLEDMessage)
    def _handle_paint_led(self, event: _PaintLEDMessage) -> None:
        if not self._engage_paint_mode():
            return
        self._badge.set_led(event.led, *event.color)

    @on(_PaintAllMessage)
    def _handle_paint_all(self, event: _PaintAllMessage) -> None:
        if not self._engage_paint_mode():
            return
        self._badge.set_all_leds(*event.colors)

    @on(_ApplyEffectMessage)
    def _handle_apply_effect(self, event: _ApplyEffectMessage) -> None:
        from dc29.protocol import EFFECT_NAMES
        if event.mode != 0:
            # Picking a built-in effect implicitly engages paint mode (the
            # user is taking the badge out of normal-app context).
            self._engage_paint_mode()
        self._badge.set_effect_mode(event.mode)
        self._effect_mode = event.mode
        name = EFFECT_NAMES.get(event.mode, str(event.mode))
        self._log_event(f"[magenta]◎ Effect set:[/] {name}")
        try:
            self.query_one(DashboardTab).update_effect(event.mode)
        except NoMatches:
            pass
        # Mirror the change into WledTab so its highlight tracks even when
        # the user picks an effect from the Effects tab radio set.
        try:
            self.query_one(WledTab).set_effect_display(event.mode)
        except NoMatches:
            pass

    @on(_ApplyWledMessage)
    def _handle_apply_wled(self, event: _ApplyWledMessage) -> None:
        """WLED knob change — palette / speed / intensity.

        Reads any previously-set values from the WledTab so a partial
        update (e.g. palette only) still emits a complete 0x01 'W' command
        with the current speed + intensity preserved.
        """
        from dc29.protocol import WLED_PALETTE_NAMES
        try:
            wt = self.query_one(WledTab)
        except NoMatches:
            return
        speed     = event.speed     if event.speed     is not None else wt._speed
        intensity = event.intensity if event.intensity is not None else wt._intensity
        palette   = event.palette   if event.palette   is not None else wt._palette
        self._badge.set_wled(speed=speed, intensity=intensity, palette=palette)
        # Log the change with whichever field actually changed (or "all" if multiple).
        bits = []
        if event.speed     is not None: bits.append(f"speed={speed}")
        if event.intensity is not None: bits.append(f"intensity={intensity}")
        if event.palette   is not None: bits.append(f"palette={WLED_PALETTE_NAMES.get(palette, palette)}")
        if bits:
            self._log_event(f"[magenta]◎ WLED:[/] {', '.join(bits)}")

    @on(_PlaySceneMessage)
    def _handle_play_scene(self, event: _PlaySceneMessage) -> None:
        import asyncio
        from pathlib import Path
        from dc29.scenes import load_scene, SceneRunner
        if not self._engage_paint_mode():
            return
        try:
            scene = load_scene(Path(event.path))
        except Exception as exc:
            self._log_event(f"[red]Scene load failed:[/] {exc}")
            return
        # Cancel any previous scene task.
        if self._active_scene_task is not None and not self._active_scene_task.done():
            self._active_scene_task.cancel()
        runner = SceneRunner(self._badge, scene)
        self._active_scene_task = asyncio.create_task(runner.run(), name=f"scene:{scene.name}")
        self._log_event(f"[dim]▶ Playing scene[/] [bold]{scene.name}[/] ({scene.kind()})")

    @on(_StopSceneMessage)
    def _handle_stop_scene(self, event: _StopSceneMessage) -> None:
        if self._active_scene_task is not None and not self._active_scene_task.done():
            self._active_scene_task.cancel()
            self._active_scene_task = None
            self._log_event("[dim]■ Scene stopped[/]")
        # Also turn off any firmware effect.
        self._badge.set_effect_mode(0)

    @on(_SetBrightnessMessage)
    def _handle_set_brightness(self, event: _SetBrightnessMessage) -> None:
        # BadgeAPI keeps brightness as a public attribute; setting it scales
        # all subsequent set_led / set_all_leds emissions.
        self._badge.brightness = event.scale
        self._log_event(f"[dim]◈ Brightness →[/] {int(event.scale * 100)}%")

    @on(_StatsResetMessage)
    def _handle_stats_reset(self, event: _StatsResetMessage) -> None:
        self._log_event("[dim]◈ Stats reset[/] — fresh start.")

    @on(_SetSplashMessage)
    def _handle_set_splash(self, event: _SetSplashMessage) -> None:
        from dc29.config import get_config
        get_config().splash_on_press = event.enabled
        self._badge.set_splash_on_press(event.enabled)
        state = "on" if event.enabled else "off"
        self._log_event(f"[dim]◈ Splash on press:[/] {state}")

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
