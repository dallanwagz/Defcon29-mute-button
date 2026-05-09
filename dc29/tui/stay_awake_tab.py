"""dc29.tui.stay_awake_tab — F08b "Stay Awake" tab (variant A layout).

Shows live session status, quick-start duration buttons, custom HH:MM
duration field, LED visualization radio group, and a Stop button.

Wires directly into :mod:`dc29.awake` for state mutations.  No bridge
manager required — the StayAwakeBridge polls the same singleton.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Optional

from textual import on
from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.css.query import NoMatches
from textual.widgets import Button, Input, Label, RadioButton, RadioSet, Select, Static

from dc29.awake import (
    INDEFINITE_SECS,
    MAX_TUI_DURATION_SECS,
    AwakeSession,
    LedMode,
    get_state,
)
from dc29.protocol import EffectMode

log = logging.getLogger(__name__)


_PROGRESS_BAR_CELLS = 30


def _format_remaining(secs: float, *, indefinite: bool = False) -> str:
    if indefinite:
        return "Indefinite"
    secs = max(0, int(round(secs)))
    h, rem = divmod(secs, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def _format_clock(ts: float) -> str:
    return datetime.fromtimestamp(ts).strftime("%-I:%M %p")


def _format_started(session: AwakeSession) -> str:
    started = _format_clock(session.started_ts)
    if session.is_indefinite():
        return f"{started} (indefinite)"
    secs = session.duration_secs
    if secs % 3600 == 0:
        label = f"{secs // 3600} hour{'s' if secs // 3600 != 1 else ''}"
    elif secs % 60 == 0:
        label = f"{secs // 60} min"
    else:
        label = f"{secs} s"
    return f"{started} ({label} session)"


def _progress_bar(progress: float, width: int = _PROGRESS_BAR_CELLS) -> str:
    filled = int(round(max(0.0, min(1.0, progress)) * width))
    return "▓" * filled + "░" * (width - filled)


def _parse_custom_duration(text: str) -> Optional[int]:
    """Parse a free-form duration string into seconds.

    Accepts:
      * ``"90"`` or ``"90m"`` → 90 minutes
      * ``"1:30"`` or ``"1h30m"`` or ``"1h 30m"`` → 90 minutes
      * ``"4h"`` → 4 hours
      * ``"30s"`` → 30 seconds (CLI-only intent, but allowed for testing)
    Returns None on parse failure.
    """
    s = text.strip().lower().replace(" ", "")
    if not s:
        return None

    # HH:MM colon form.
    if ":" in s:
        try:
            h_str, m_str = s.split(":", 1)
            return max(0, int(h_str)) * 3600 + max(0, int(m_str)) * 60
        except ValueError:
            return None

    # Suffix form: 1h30m, 30m, 30s, 4h.
    total = 0
    matched_any = False
    cur = ""
    for ch in s + "X":  # sentinel
        if ch.isdigit():
            cur += ch
        else:
            if cur and ch in ("h", "m", "s", "X"):
                try:
                    n = int(cur)
                except ValueError:
                    return None
                if ch == "h":
                    total += n * 3600
                elif ch == "m":
                    total += n * 60
                elif ch == "s":
                    total += n
                else:  # bare digits (e.g. "90") → treat as minutes
                    total += n * 60
                cur = ""
                matched_any = True
            elif ch == "X" and not cur:
                continue
            else:
                return None
    if not matched_any:
        return None
    return total


_QUICK_PRESETS: list[tuple[str, str, int]] = [
    # (button_id, label, duration_secs)
    ("qs-30m", "30 min", 30 * 60),
    ("qs-1h", "1 hour", 1 * 3600),
    ("qs-2h", "2 hour", 2 * 3600),
    ("qs-4h", "4 hour", 4 * 3600),
    ("qs-8h", "8 hour", 8 * 3600),
    ("qs-inf", "Indefinite", INDEFINITE_SECS),
]


class StayAwakeTab(Container):
    """Variant A layout — see docs/hardware-features/features/F08b-tui-mockups.md."""

    DEFAULT_CSS = """
    StayAwakeTab {
        padding: 1 2;
    }
    StayAwakeTab .section-title {
        color: $accent;
        text-style: bold;
        margin-bottom: 1;
    }
    StayAwakeTab .hint {
        color: $text-muted;
        margin-bottom: 1;
    }
    StayAwakeTab #status-line {
        height: auto;
        margin-bottom: 1;
    }
    StayAwakeTab #status-detail {
        height: auto;
        padding-left: 2;
        margin-bottom: 1;
    }
    StayAwakeTab #quick-box {
        height: auto;
        border: solid $panel-lighten-1;
        padding: 1 2;
        margin-bottom: 1;
    }
    StayAwakeTab #quick-row {
        height: 3;
        margin-bottom: 1;
    }
    StayAwakeTab #quick-row Button {
        margin-right: 1;
    }
    StayAwakeTab #custom-row {
        height: 3;
    }
    StayAwakeTab #custom-row Input {
        width: 16;
        margin-right: 1;
    }
    StayAwakeTab #custom-row Button {
        width: auto;
    }
    StayAwakeTab #led-box {
        height: auto;
        border: solid $panel-lighten-1;
        padding: 1 2;
        margin-bottom: 1;
    }
    StayAwakeTab #led-effect-row {
        height: 3;
        margin-top: 1;
    }
    StayAwakeTab #led-effect-row Select {
        width: 32;
    }
    StayAwakeTab #stop-row {
        height: 3;
        margin-bottom: 1;
    }
    StayAwakeTab #footer-row {
        height: auto;
        color: $text-muted;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self._state = get_state()

    # ------------------------------------------------------------------
    # Compose
    # ------------------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield Label("STAY AWAKE", classes="section-title")

        yield Static("", id="status-line")
        yield Static("", id="status-detail")

        with Vertical(id="quick-box"):
            yield Label("Quick start")
            with Horizontal(id="quick-row"):
                for btn_id, label, _ in _QUICK_PRESETS:
                    yield Button(f"[ {label} ]", id=btn_id)
            with Horizontal(id="custom-row"):
                yield Label("Custom: ")
                yield Input(placeholder="HH:MM or 1h30m", id="custom-input")
                yield Button("Go", id="qs-go", variant="primary")

        with Vertical(id="led-box"):
            yield Label("While awake, show on LEDs…")
            with RadioSet(id="led-radio"):
                yield RadioButton("Off (don't touch LEDs)", id="led-off", value=True)
                yield RadioButton("Slow cyan pulse on LED 1 only", id="led-cyan")
                yield RadioButton("Progress bar across all 4 LEDs", id="led-bar")
                yield RadioButton("Effect mode", id="led-effect")
            with Horizontal(id="led-effect-row"):
                yield Label("Effect: ")
                yield Select(
                    [(m.name.replace("_", " ").title(), m.value) for m in EffectMode if m.value > 0],
                    id="led-effect-select",
                    value=1,
                    allow_blank=False,
                )

        with Horizontal(id="stop-row"):
            yield Button("Stop now", id="stop-btn", variant="error")

        yield Static("", id="footer-row")

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def on_mount(self) -> None:
        # Apply persisted preferences to the radio group.
        prefs = self._state.prefs
        try:
            radio_id = {
                LedMode.OFF: "led-off",
                LedMode.CYAN_PULSE: "led-cyan",
                LedMode.PROGRESS_BAR: "led-bar",
                LedMode.EFFECT_MODE: "led-effect",
            }[prefs.last_led_mode]
            self.query_one(f"#{radio_id}", RadioButton).value = True
        except (NoMatches, KeyError):
            pass
        try:
            self.query_one("#led-effect-select", Select).value = prefs.last_effect_mode_id
        except NoMatches:
            pass

        # Refresh once immediately, then every second while mounted.
        self._refresh()
        self.set_interval(1.0, self._refresh)

    # ------------------------------------------------------------------
    # Refresh
    # ------------------------------------------------------------------

    def _refresh(self) -> None:
        session = self._state.session
        try:
            status = self.query_one("#status-line", Static)
            detail = self.query_one("#status-detail", Static)
            footer = self.query_one("#footer-row", Static)
            stop_btn = self.query_one("#stop-btn", Button)
        except NoMatches:
            return

        if session is None:
            status.update("○  idle")
            detail.update("    Click a quick-start above or type a Custom duration.")
            stop_btn.disabled = True
        else:
            now = time.time()
            indefinite = session.is_indefinite()
            progress = session.progress(now)
            bar = _progress_bar(progress)
            pct = "—" if indefinite else f"{int(round(progress * 100))}%"
            status.update(f"Status:  {bar}  {pct} elapsed")

            remaining = _format_remaining(session.remaining_secs(now), indefinite=indefinite)
            end_label = "—" if indefinite else _format_clock(session.end_ts)
            detail.update(
                "●  ACTIVE\n"
                f"    Time remaining:  {remaining}\n"
                f"    Will end at:     {end_label}\n"
                f"    Started:         {_format_started(session)}"
            )
            stop_btn.disabled = False

        # Footer: last-started hint (uses prefs).
        prefs = self._state.prefs
        if prefs.last_duration_secs >= INDEFINITE_SECS // 2:
            label = "Indefinite"
        elif prefs.last_duration_secs % 3600 == 0:
            h = prefs.last_duration_secs // 3600
            label = f"{h} hour{'s' if h != 1 else ''}"
        else:
            label = f"{prefs.last_duration_secs // 60} min"
        footer.update(f"Last started:  {label} session")

    # ------------------------------------------------------------------
    # Button + input handlers
    # ------------------------------------------------------------------

    @on(Button.Pressed)
    def _on_button(self, event: Button.Pressed) -> None:
        bid = event.button.id or ""
        if bid == "stop-btn":
            self._state.stop_session()
            self._refresh()
            return
        if bid == "qs-go":
            self._start_from_custom()
            return
        for btn_id, _, secs in _QUICK_PRESETS:
            if bid == btn_id:
                self._start_session(secs)
                return

    @on(Input.Submitted, "#custom-input")
    def _on_custom_submit(self, _event: Input.Submitted) -> None:
        self._start_from_custom()

    def _start_from_custom(self) -> None:
        try:
            inp = self.query_one("#custom-input", Input)
        except NoMatches:
            return
        secs = _parse_custom_duration(inp.value)
        if secs is None or secs <= 0:
            inp.placeholder = "invalid — try '1h30m' or '90m'"
            inp.value = ""
            return
        if secs > MAX_TUI_DURATION_SECS:
            inp.placeholder = f"max 24h via TUI ({MAX_TUI_DURATION_SECS // 3600}h)"
            inp.value = ""
            return
        inp.value = ""
        self._start_session(secs)

    def _start_session(self, duration_secs: int) -> None:
        led_mode = self._read_selected_led_mode()
        effect_id = self._read_selected_effect_id()
        try:
            self._state.start_session(duration_secs, led_mode=led_mode, effect_mode_id=effect_id)
        except ValueError as exc:
            log.warning("start_session rejected: %s", exc)
            return
        self._refresh()

    def _read_selected_led_mode(self) -> LedMode:
        try:
            for rid, mode in (
                ("led-off", LedMode.OFF),
                ("led-cyan", LedMode.CYAN_PULSE),
                ("led-bar", LedMode.PROGRESS_BAR),
                ("led-effect", LedMode.EFFECT_MODE),
            ):
                if self.query_one(f"#{rid}", RadioButton).value:
                    return mode
        except NoMatches:
            pass
        return LedMode.OFF

    def _read_selected_effect_id(self) -> int:
        try:
            sel = self.query_one("#led-effect-select", Select)
            v = sel.value
            return int(v) if isinstance(v, int) else 1
        except NoMatches:
            return 1
