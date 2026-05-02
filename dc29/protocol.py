"""
dc29.protocol — Authoritative protocol reference for the DC29 badge USB CDC interface.

The badge firmware uses byte ``0x01`` as an escape prefix.  Every command or
event starts with that escape byte followed by a single ASCII letter that
identifies the message type, then zero or more argument bytes.

Host → badge commands
---------------------
All commands are sent as raw bytes over the USB CDC serial port (9600 baud).

Badge → host events
-------------------
Events arrive unsolicited from the badge whenever a button is pressed or an
internal state changes.  The host protocol parser must buffer incoming bytes
and dispatch when a complete message is assembled.

Normal serial-console traffic (interactive menu input) never contains ``0x01``,
so status commands can be safely injected while the console is open.
"""

from __future__ import annotations

from enum import IntEnum
from typing import TypeAlias

# ---------------------------------------------------------------------------
# Fundamental constants
# ---------------------------------------------------------------------------

ESCAPE: int = 0x01
"""Escape byte that prefixes every badge protocol message."""

BUTTONS: tuple[int, ...] = (1, 2, 3, 4)
"""Valid button numbers on the badge."""

LED_COUNT: int = 4
"""Number of RGB LEDs on the badge."""

# ---------------------------------------------------------------------------
# Type aliases
# ---------------------------------------------------------------------------

Color: TypeAlias = tuple[int, int, int]
"""An (R, G, B) color tuple where each component is in the range 0–255."""

# ---------------------------------------------------------------------------
# Host → badge command bytes (the byte that follows ESCAPE)
# ---------------------------------------------------------------------------

CMD_MUTED: int = ord("M")
"""
``0x01 'M'`` — Set LED 4 to red, indicating the microphone is muted.

No argument bytes.  LED 4 is always driven at full brightness regardless of
the global brightness setting, so the mute indicator is never accidentally
dimmed to invisibility.
"""

CMD_UNMUTED: int = ord("U")
"""
``0x01 'U'`` — Set LED 4 to green, indicating the microphone is active.

No argument bytes.
"""

CMD_CLEAR: int = ord("X")
"""
``0x01 'X'`` — Turn LED 4 off (not in a meeting / status unknown).

No argument bytes.
"""

CMD_SET_KEY: int = ord("K")
"""
``0x01 'K' n mod key`` — Write a single-key macro for button *n* to EEPROM.

Arguments (3 bytes):
  * ``n``    — button number, 1–4 (or 5–6 for slider directions)
  * ``mod``  — HID modifier byte (see ``MOD_*`` constants)
  * ``key``  — HID keycode; use ``0`` with modifier ``0xF0`` for a media key

The badge acknowledges with ``EVT_KEY_ACK``.
"""

CMD_QUERY_KEY: int = ord("Q")
"""
``0x01 'Q' n`` — Query the current keymap for button *n*.

Arguments (1 byte):
  * ``n`` — button number, 1–6

The badge replies with ``EVT_KEY_REPLY``.
"""

CMD_SET_LED: int = ord("L")
"""
``0x01 'L' n r g b`` — Set the color of LED *n* immediately (RAM only, not saved).

Arguments (4 bytes):
  * ``n`` — LED number, 1–4
  * ``r`` — red component 0–255
  * ``g`` — green component 0–255
  * ``b`` — blue component 0–255

This command is used for the idle animation and the mute-state indicator.
"""

CMD_BUTTON_FLASH: int = ord("F")
"""
``0x01 'F' v`` — Enable (``v=1``) or disable (``v=0``) the white LED flash on button press.

Arguments (1 byte):
  * ``v`` — ``0`` to disable, ``1`` to enable (firmware default is enabled)
"""

CMD_SET_EFFECT: int = ord("E")
"""
``0x01 'E' n`` — Set the firmware-driven LED effect mode.

Arguments (1 byte):
  * ``n`` — effect mode index; see :class:`EffectMode` for the full list (0=off through 18=juggle)

When the firmware is running an effect (mode > 0), Python-side idle
animations should be suppressed to avoid conflicting LED writes.  The badge
will emit ``EVT_EFFECT_MODE`` when the mode changes internally (e.g., after a
long-press chord).
"""

CMD_FIRE_TAKEOVER: int = ord("T")
"""
``0x01 'T' n`` — Trigger the firmware takeover ripple animation for button *n*.

Fires the same 4-phase personality-based animation that runs on a button press
when ``button_flash`` is enabled, but without requiring a physical press.  Use
this from the host to give satisfying visual feedback for app-handled actions
(e.g. an Outlook delete via the bridge) when ``button_flash`` is suppressed
because Python is managing the LEDs.

Arguments (1 byte):
  * ``n`` — button index, 1–4. Out-of-range values are silently ignored by firmware.
"""

CMD_PAINT_ALL: int = ord("P")
"""
``0x01 'P' r1 g1 b1 r2 g2 b2 r3 g3 b3 r4 g4 b4`` — Paint all four LEDs atomically.

12-byte payload sets every LED in one packet.  Use this for animation streams
where atomicity matters (no inter-LED tearing) and bandwidth matters (one
13-byte packet vs four 6-byte ``L`` commands per frame).

The firmware applies all four colors via :func:`led_set_resting_color` so the
takeover-animation defer-and-restore logic works correctly.
"""

CMD_SET_SPLASH: int = ord("I")
"""
``0x01 'I' v`` — Enable (``v=1``) or disable (``v=0``) the interactive
splash-on-press animation.

When enabled, pressing a button while a firmware effect mode is running
fires a ~300 ms localized color-spray animation that captures the pressed
LED's current displayed color and sprays it outward.  Designed as a fidget
interaction for "RGB toy" mode — works on battery without USB.

RAM-only: setting is not persisted to EEPROM and resets to enabled on each
power-on / firmware boot.

Arguments (1 byte):
  * ``v`` — ``0`` to disable, ``1`` to enable (firmware default is enabled)
"""

CMD_SET_SLIDER: int = ord("S")
"""
``0x01 'S' v`` — Enable (``v=1``) or disable (``v=0``) the capacitive touch slider.

When disabled, the slider's position-change events no longer inject HID
volume-up / volume-down keystrokes.  The firmware still scans the slider so
the position cache stays accurate; only the keystroke injection is gated.

RAM-only: setting is not persisted to EEPROM and resets to enabled on each
power-on / firmware boot.

Arguments (1 byte):
  * ``v`` — ``0`` to disable, ``1`` to enable (firmware default is enabled)
"""

CMD_WLED_SET: int = ord("W")
"""
``0x01 'W' speed intensity palette`` — Set the WLED-effect knobs in one shot.

Mirrors WLED's ``/win&SX=&IX=&FP=`` HTTP API.  All three values are written
atomically to the firmware's segment state, so the next frame of any
WLED-ported effect (modes 19+) will use the new values.  Effects in the
hand-rolled range (modes 1–18) ignore these knobs.

Arguments (3 bytes):
  * ``speed``     — 0–255, controls the timebase for most effects (firmware default 128)
  * ``intensity`` — 0–255, per-effect "amount" knob (firmware default 128)
  * ``palette``   — :class:`WledPalette` index; out-of-range values wrap modulo
    the palette count, so the host doesn't have to track the count itself.

RAM-only: settings reset to defaults on each power-on / firmware boot.
"""

# ---------------------------------------------------------------------------
# Badge → host event bytes (the byte that follows ESCAPE)
# ---------------------------------------------------------------------------

EVT_BUTTON: int = ord("B")
"""
``0x01 'B' n mod key`` — A button was pressed.

Payload (3 bytes):
  * ``n``   — button number, 1–4
  * ``mod`` — HID modifier byte that was sent
  * ``key`` — HID keycode that was sent

This event fires after the debounce window; it always reflects what the badge
actually transmitted over USB HID.
"""

EVT_KEY_REPLY: int = ord("R")
"""
``0x01 'R' n mod key`` — Reply to a ``CMD_QUERY_KEY`` request.

Payload (3 bytes):
  * ``n``   — button number that was queried
  * ``mod`` — HID modifier byte stored in EEPROM
  * ``key`` — HID keycode stored in EEPROM
"""

EVT_KEY_ACK: int = ord("A")
"""
``0x01 'A' n`` — Acknowledgement for a ``CMD_SET_KEY`` command.

Payload (1 byte):
  * ``n`` — button number whose keymap was updated
"""

EVT_EFFECT_MODE: int = ord("V")
"""
``0x01 'V' n`` — The firmware LED effect mode changed.

Payload (1 byte):
  * ``n`` — new effect mode index; see :class:`EffectMode` (0=off through 18=juggle)

Emitted when the user triggers a long-press chord or when the mode is changed
via ``CMD_SET_EFFECT``.
"""

EVT_CHORD: int = ord("C")
"""
``0x01 'C' n`` — A button chord was fired.

Payload (1 byte):
  * ``n`` — chord type: ``1`` = short press, ``2`` = long press

Long-press chords (n=2) are used to cycle through firmware LED effects.
"""

# ---------------------------------------------------------------------------
# Mute / meeting state
# ---------------------------------------------------------------------------


class MuteState(IntEnum):
    """Represents the Teams meeting mute state reflected on LED 4."""

    NOT_IN_MEETING = 0
    """No active meeting; LED 4 is off."""

    UNMUTED = 1
    """In a meeting with microphone active; LED 4 is green."""

    MUTED = 2
    """In a meeting with microphone muted; LED 4 is red."""


# ---------------------------------------------------------------------------
# Effect modes
# ---------------------------------------------------------------------------


class EffectMode(IntEnum):
    """Firmware-driven LED effect modes (used with ``CMD_SET_EFFECT``).

    All modes animate every LED.  Bridges that need exclusive control of an
    LED (Teams toggle-mute on B4, FocusBridge during target-app focus) call
    ``set_effect_mode(0)`` to suspend the effect while they hold ownership.
    """

    OFF = 0
    """All LEDs return to their EEPROM resting colors; no firmware animation."""

    RAINBOW_CHASE = 1
    """One LED lit at a time cycling through all four, hue advances per step."""

    BREATHE = 2
    """All four LEDs fade in and out together with slow hue drift."""

    WIPE = 3
    """A single hue rolls across LEDs 1→4, wipes back to off, then a new hue."""

    TWINKLE = 4
    """Pseudo-random sparkles — each tick, one LED flickers at a random brightness."""

    GRADIENT = 5
    """Smooth hue gradient across the four LEDs, scrolling slowly."""

    THEATER = 6
    """Theater-chase: alternating odd/even LEDs lit, hue drifts across cycles."""

    CYLON = 7
    """Knight-Rider-style sweep — bright bouncing LED with dim trail."""

    PARTICLES = 8
    """Two physics particles drifting through the 2x2 LED grid, colors blending on proximity."""

    FIRE = 9
    """Fire 2012-style flicker — per-LED heat with bottom row burning hotter."""

    LIGHTNING = 10
    """Long dark gaps punctuated by bright white flash bursts on random LEDs."""

    POLICE = 11
    """Emergency-vehicle strobe — left half (LED1,3) red, right half (LED2,4) blue."""

    PLASMA = 12
    """Smoothly-blending hue field — each LED is the average of two sine waves."""

    HEARTBEAT = 13
    """Lub-dub red double-pulse with rest gap — like a resting heartbeat."""

    AURORA = 14
    """Slow drift through cool-spectrum hues (cyan→blue→purple), per-LED phase offsets."""

    CONFETTI = 15
    """Sparkle and fade — random LEDs flash random hues against a fading background."""

    STROBE = 16
    """Rapid full-on / full-off across all LEDs with slow hue cycle."""

    METEOR = 17
    """Bright LED travels 1→4 leaving a fading trail, then restarts with a new hue."""

    JUGGLE = 18
    """Three sine-wave dots at different speeds and base hues, blended across the LEDs."""

    BREATH_WLED = 19
    """WLED port: ``mode_breath`` — palette breathing, 30..255 envelope, sin8-driven."""

    PRIDE = 20
    """WLED port: ``mode_pride_2015`` — Mark Kriegsman's hue+brightness rainbow waves."""

    PACIFICA = 21
    """WLED port: ``mode_pacifica`` — layered ocean palette with whitecaps."""

    RUNNING_LIGHTS = 22
    """WLED port: ``mode_running_lights`` — sine-wave pulse traveling across the strip."""

    JUGGLE_WLED = 23
    """WLED port: FastLED ``juggle()`` — 8 sine-wave dots at coprime BPMs, blended."""

    CONFETTI_WLED = 24
    """WLED port: Mark Kriegsman ``confetti()`` — random sparkles over a slowly-drifting hue."""

    RAINBOW_WLED = 25
    """WLED port: ``mode_rainbow`` — whole strip cycles through the active palette together."""

    PALETTE_FLOW = 26
    """Palette readout scrolling along the strip — cleanest showcase of a new palette."""

    BPM = 27
    """WLED port: ``mode_bpm`` — Mark Kriegsman BPM-driven palette breath."""

    GLITTER = 28
    """Palette scroll background with random white sparkles; intensity controls density."""

    COLOR_WIPE = 29
    """WLED port: palette color fills the strip, then a black wipe sweeps it back, repeat."""

    TWO_DOTS = 30
    """WLED port: ``mode_two_dots`` — two palette-colored dots oscillating at slightly different rates."""

    LAKE = 31
    """WLED port: ``mode_lake`` — interfering wave fields of palette color, like a still lake."""

    DANCING_SHADOWS = 32
    """Three palette-colored spotlights drift independently, blending where they overlap."""

    COLORTWINKLES = 33
    """WLED port: ``mode_colortwinkles`` — palette pixels twinkle on and off independently."""

    SINELON = 34
    """WLED port: ``mode_sinelon`` — palette dot traces a sine path leaving a fade trail."""


EFFECT_NAMES: dict[int, str] = {
    EffectMode.OFF: "off",
    EffectMode.RAINBOW_CHASE: "rainbow-chase",
    EffectMode.BREATHE: "breathe",
    EffectMode.WIPE: "wipe",
    EffectMode.TWINKLE: "twinkle",
    EffectMode.GRADIENT: "gradient",
    EffectMode.THEATER: "theater",
    EffectMode.CYLON: "cylon",
    EffectMode.PARTICLES: "particles",
    EffectMode.FIRE: "fire",
    EffectMode.LIGHTNING: "lightning",
    EffectMode.POLICE: "police",
    EffectMode.PLASMA: "plasma",
    EffectMode.HEARTBEAT: "heartbeat",
    EffectMode.AURORA: "aurora",
    EffectMode.CONFETTI: "confetti",
    EffectMode.STROBE: "strobe",
    EffectMode.METEOR: "meteor",
    EffectMode.JUGGLE: "juggle",
    EffectMode.BREATH_WLED: "breath-wled",
    EffectMode.PRIDE: "pride",
    EffectMode.PACIFICA: "pacifica",
    EffectMode.RUNNING_LIGHTS: "running-lights",
    EffectMode.JUGGLE_WLED: "juggle-wled",
    EffectMode.CONFETTI_WLED: "confetti-wled",
    EffectMode.RAINBOW_WLED: "rainbow-wled",
    EffectMode.PALETTE_FLOW: "palette-flow",
    EffectMode.BPM: "bpm",
    EffectMode.GLITTER: "glitter",
    EffectMode.COLOR_WIPE: "color-wipe",
    EffectMode.TWO_DOTS: "two-dots",
    EffectMode.LAKE: "lake",
    EffectMode.DANCING_SHADOWS: "dancing-shadows",
    EffectMode.COLORTWINKLES: "colortwinkles",
    EffectMode.SINELON: "sinelon",
}
"""Human-readable names for each :class:`EffectMode`."""

EFFECT_DESCRIPTIONS: dict[int, str] = {
    EffectMode.OFF:           "Static EEPROM colors — no animation.",
    EffectMode.RAINBOW_CHASE: "One LED at a time cycles around the row, hue rotating.",
    EffectMode.BREATHE:       "All four LEDs fade in and out together with hue drift.",
    EffectMode.WIPE:          "A single color paints across LEDs 1→4, wipes off, then a new hue.",
    EffectMode.TWINKLE:       "Random sparkles — like distant stars or fireflies.",
    EffectMode.GRADIENT:      "A smooth hue gradient that slowly scrolls across the row.",
    EffectMode.THEATER:       "Marquee-style alternating dot pattern shifting across the LEDs.",
    EffectMode.CYLON:         "Knight Rider sweep — a bright LED bounces back and forth.",
    EffectMode.PARTICLES:     "Two physics-driven particles drift through the 2x2 grid, colors blending and bouncing off walls.",
    EffectMode.FIRE:          "Flickering flames — each LED holds its own heat value, bottom row burns hotter.",
    EffectMode.LIGHTNING:     "Mostly dark, with sudden bursts of bright white flashes on random LEDs.",
    EffectMode.POLICE:        "Emergency strobe — left side red, right side blue, alternating with a double-flash per side.",
    EffectMode.PLASMA:         "Smoothly-blending hue field; each LED averages two sine waves at different frequencies.",
    EffectMode.HEARTBEAT:     "Lub-dub red double-pulse with a long rest gap — feels like a resting heartbeat.",
    EffectMode.AURORA:        "Slow drift through cool blues, cyans, and purples — each LED swirls on its own phase.",
    EffectMode.CONFETTI:      "Random sparkles fall on random LEDs and fade out over the next few ticks.",
    EffectMode.STROBE:        "Rapid full-on / full-off flashing across all LEDs while the strobe color slowly hue-cycles.",
    EffectMode.METEOR:        "A bright LED travels across the row leaving a fading trail behind it.",
    EffectMode.JUGGLE:        "Three sine-wave dots at different speeds and base hues, summed and blended across the LEDs.",
    EffectMode.BREATH_WLED:    "WLED port — palette breathing with a 30..255 sine envelope, like the badge taking slow breaths.",
    EffectMode.PRIDE:          "WLED port (Pride 2015) — slowly-shifting hue and brightness waves; classic Mark Kriegsman rainbow.",
    EffectMode.PACIFICA:       "WLED port — layered ocean-palette waves with brighter whitecaps where waves overlap.",
    EffectMode.RUNNING_LIGHTS: "WLED port — a sine-wave pulse travels across the strip, palette-colored.",
    EffectMode.JUGGLE_WLED:    "WLED port (FastLED juggle) — 8 colorful dots tracing sine paths at coprime BPMs.",
    EffectMode.CONFETTI_WLED:  "WLED port (FastLED confetti) — random sparkles over a slowly-drifting base hue.",
    EffectMode.RAINBOW_WLED:    "WLED port (rainbow) — whole strip cycles through the active palette together.",
    EffectMode.PALETTE_FLOW:    "Pure palette readout scrolling along the strip — cleanest way to see a new palette.",
    EffectMode.BPM:             "WLED port (Mark Kriegsman BPM) — palette breathes with a sin-shaped brightness pulse.",
    EffectMode.GLITTER:         "Palette scroll with random white sparkles; intensity controls sparkle density.",
    EffectMode.COLOR_WIPE:      "WLED port — palette color fills the strip, then a black wipe sweeps it back to off, repeat.",
    EffectMode.TWO_DOTS:        "WLED port — two palette-colored dots oscillating at slightly different rates over a fading background.",
    EffectMode.LAKE:            "WLED port — two interfering wave fields of palette color, like reflections on a still lake.",
    EffectMode.DANCING_SHADOWS: "Three palette-colored spotlights drift independently across the strip and blend where they overlap.",
    EffectMode.COLORTWINKLES:   "WLED port — palette pixels twinkle on and off independently with random spawn timing.",
    EffectMode.SINELON:         "WLED port — a palette-colored dot traces a sine path through the strip, leaving a fade trail.",
}
"""Short human-readable descriptions for the TUI scene grid + ``dc29 set-effect --help``."""


# ---------------------------------------------------------------------------
# WLED-effect color profiles (palettes) and runtime knobs
# ---------------------------------------------------------------------------


class WledPalette(IntEnum):
    """Color palettes available to the WLED-ported effects (modes 19+).

    Set via :data:`CMD_WLED_SET` (``0x01 'W' speed intensity palette``).  The
    indices match the firmware's ``palette_table[]`` in ``wled_fx.c`` — keep
    them in lockstep.  Effects in the hand-rolled range (modes 1–18) ignore
    the palette setting; only WLED-ported effects honor it.
    """

    RAINBOW = 0
    """Full-spectrum rainbow — FastLED ``RainbowColors_p``."""

    HEAT = 1
    """Black → red → orange → yellow → white — FastLED ``HeatColors_p``, classic flame palette."""

    OCEAN = 2
    """Deep navy → cyan → sky blue — cool, watery palette."""

    LAVA = 3
    """Black → deep red → orange → yellow → white — like molten lava cooling."""

    PACIFICA = 4
    """Hand-tuned ocean palette from WLED's ``mode_pacifica`` (FX.cpp:4194)."""

    SUNSET = 5
    """Yellow → orange → magenta → indigo, like a real sunset gradient."""

    FOREST = 6
    """Deep greens with brown highlights — forest canopy at midday."""

    PARTY = 7
    """Saturated pinks, oranges, yellows, blues — FastLED-style party palette."""


WLED_PALETTE_NAMES: dict[int, str] = {
    WledPalette.RAINBOW:  "rainbow",
    WledPalette.HEAT:     "heat",
    WledPalette.OCEAN:    "ocean",
    WledPalette.LAVA:     "lava",
    WledPalette.PACIFICA: "pacifica",
    WledPalette.SUNSET:   "sunset",
    WledPalette.FOREST:   "forest",
    WledPalette.PARTY:    "party",
}
"""Lower-case slug names for each :class:`WledPalette`, used by the TUI and CLI."""


# ---------------------------------------------------------------------------
# HID modifier byte constants
# ---------------------------------------------------------------------------

MOD_CTRL: int = 0x01
"""HID Left Control modifier."""

MOD_SHIFT: int = 0x02
"""HID Left Shift modifier."""

MOD_ALT: int = 0x04
"""HID Left Alt modifier."""

MOD_GUI: int = 0x08
"""HID Left GUI (Windows / Command) modifier."""

MOD_CTRL_SHIFT: int = 0x03
"""HID Control + Shift."""

MOD_CTRL_ALT: int = 0x05
"""HID Control + Alt."""

MOD_CTRL_GUI: int = 0x09
"""HID Control + GUI."""

MOD_SHIFT_ALT: int = 0x06
"""HID Shift + Alt."""

MOD_SHIFT_GUI: int = 0x0A
"""HID Shift + GUI."""

MOD_ALT_GUI: int = 0x0C
"""HID Alt + GUI."""

MOD_CTRL_SHIFT_ALT: int = 0x07
"""HID Control + Shift + Alt."""

MOD_CTRL_SHIFT_GUI: int = 0x0B
"""HID Control + Shift + GUI."""

MOD_CTRL_ALT_GUI: int = 0x0D
"""HID Control + Alt + GUI."""

MOD_SHIFT_ALT_GUI: int = 0x0E
"""HID Shift + Alt + GUI."""

MOD_CTRL_SHIFT_ALT_GUI: int = 0x0F
"""HID Control + Shift + Alt + GUI."""

MOD_MEDIA: int = 0xF0
"""
Special pseudo-modifier indicating a media / consumer-control key.

When ``mod == MOD_MEDIA``, the keycode is a USB HID consumer-control usage
ID rather than a standard keyboard keycode.
"""

_MOD_NAMES: dict[int, str] = {
    0x00: "",
    MOD_CTRL: "ctrl",
    MOD_SHIFT: "shift",
    MOD_ALT: "alt",
    MOD_GUI: "gui",
    MOD_CTRL_SHIFT: "ctrl+shift",
    MOD_CTRL_ALT: "ctrl+alt",
    MOD_CTRL_GUI: "ctrl+gui",
    MOD_SHIFT_ALT: "shift+alt",
    MOD_SHIFT_GUI: "shift+gui",
    MOD_ALT_GUI: "alt+gui",
    MOD_CTRL_SHIFT_ALT: "ctrl+shift+alt",
    MOD_CTRL_SHIFT_GUI: "ctrl+shift+gui",
    MOD_CTRL_ALT_GUI: "ctrl+alt+gui",
    MOD_SHIFT_ALT_GUI: "shift+alt+gui",
    MOD_CTRL_SHIFT_ALT_GUI: "ctrl+shift+alt+gui",
    MOD_MEDIA: "media",
}

# ---------------------------------------------------------------------------
# Built-in colors
# ---------------------------------------------------------------------------

BUILTIN_COLORS: dict[str, Color] = {
    "red":    (255, 0,   0),
    "green":  (0,   255, 0),
    "blue":   (0,   0,   255),
    "white":  (255, 255, 255),
    "cyan":   (0,   200, 255),
    "purple": (160, 0,   255),
    "orange": (255, 80,  0),
    "yellow": (255, 200, 0),
    "off":    (0,   0,   0),
}
"""Named colors available for use in CLI arguments and the TUI color picker."""

# ---------------------------------------------------------------------------
# HID keycode names (partial — covers ASCII printables + common special keys)
# ---------------------------------------------------------------------------

_KEYCODE_NAMES: dict[int, str] = {
    0x00: "(none)",
    0x04: "a", 0x05: "b", 0x06: "c", 0x07: "d", 0x08: "e", 0x09: "f",
    0x0A: "g", 0x0B: "h", 0x0C: "i", 0x0D: "j", 0x0E: "k", 0x0F: "l",
    0x10: "m", 0x11: "n", 0x12: "o", 0x13: "p", 0x14: "q", 0x15: "r",
    0x16: "s", 0x17: "t", 0x18: "u", 0x19: "v", 0x1A: "w", 0x1B: "x",
    0x1C: "y", 0x1D: "z",
    0x1E: "1", 0x1F: "2", 0x20: "3", 0x21: "4", 0x22: "5",
    0x23: "6", 0x24: "7", 0x25: "8", 0x26: "9", 0x27: "0",
    0x28: "enter", 0x29: "esc", 0x2A: "backspace", 0x2B: "tab", 0x2C: "space",
    0x2D: "-", 0x2E: "=", 0x2F: "[", 0x30: "]", 0x31: "\\",
    0x33: ";", 0x34: "'", 0x35: "`", 0x36: ",", 0x37: ".", 0x38: "/",
    0x39: "caps_lock",
    0x3A: "f1", 0x3B: "f2", 0x3C: "f3", 0x3D: "f4", 0x3E: "f5",
    0x3F: "f6", 0x40: "f7", 0x41: "f8", 0x42: "f9", 0x43: "f10",
    0x44: "f11", 0x45: "f12",
    0x4F: "right", 0x50: "left", 0x51: "down", 0x52: "up",
    0x4A: "home", 0x4B: "page_up", 0x4C: "delete", 0x4D: "end", 0x4E: "page_down",
    # Media / consumer-control usage IDs (used when mod == MOD_MEDIA)
    0xE2: "mute", 0xE9: "vol_up", 0xEA: "vol_down",
    0xB5: "next_track", 0xB6: "prev_track", 0xCD: "play_pause",
}


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def parse_color(s: str) -> Color:
    """Parse a color string into an (R, G, B) tuple.

    Accepts either a named color from :data:`BUILTIN_COLORS` (e.g. ``"cyan"``)
    or a comma-separated RGB triplet (e.g. ``"0,200,255"``).

    Args:
        s: The color string to parse.

    Returns:
        A :data:`Color` tuple with components in the range 0–255.

    Raises:
        ValueError: If the string is not a recognised named color or valid
            RGB triplet.
    """
    low = s.strip().lower()
    if low in BUILTIN_COLORS:
        return BUILTIN_COLORS[low]
    parts = low.split(",")
    if len(parts) == 3:
        try:
            r, g, b = (int(p.strip()) for p in parts)
            if all(0 <= v <= 255 for v in (r, g, b)):
                return (r, g, b)
        except ValueError:
            pass
    raise ValueError(
        f"Invalid color {s!r}. Use 'r,g,b' (0–255 each) or one of: "
        + ", ".join(BUILTIN_COLORS)
    )


def modifier_name(mod: int) -> str:
    """Return a human-readable string for a HID modifier byte.

    Args:
        mod: HID modifier byte (0x00–0xFF).

    Returns:
        A string like ``"ctrl+shift"`` or ``"media"``.  Returns a hex
        representation for unrecognised values.
    """
    if mod in _MOD_NAMES:
        return _MOD_NAMES[mod] or "(none)"
    # Build from individual bit flags for unknown combos.
    parts = []
    if mod & MOD_CTRL:
        parts.append("ctrl")
    if mod & MOD_SHIFT:
        parts.append("shift")
    if mod & MOD_ALT:
        parts.append("alt")
    if mod & MOD_GUI:
        parts.append("gui")
    remainder = mod & ~(MOD_CTRL | MOD_SHIFT | MOD_ALT | MOD_GUI)
    if remainder:
        parts.append(f"0x{remainder:02X}")
    return "+".join(parts) if parts else "(none)"


def keycode_name(kc: int, mod: int = 0) -> str:
    """Return a human-readable string for a HID keycode.

    When *mod* is :data:`MOD_MEDIA` and *kc* is ``0``, the modifier itself
    encodes a media key action and the keycode is not meaningful; this is
    indicated in the return value.

    Args:
        kc:  HID keycode byte (0x00–0xFF).
        mod: Optional modifier byte, used to detect media-key context.

    Returns:
        A descriptive string such as ``"m"``, ``"enter"``, or ``"vol_up"``.
    """
    if mod == MOD_MEDIA and kc == 0:
        return "(media — see modifier)"
    if kc in _KEYCODE_NAMES:
        return _KEYCODE_NAMES[kc]
    return f"0x{kc:02X}"
