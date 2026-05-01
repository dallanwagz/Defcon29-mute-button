"""
dc29.bridges.colors — Positional color semantics (Option A).

Four positions, four color families — always consistent across every page:

  B1  Green       — positive / create / connect / confirm   (top-left)
  B2  Cool blue   — status / visibility / communication     (top-right)
  B3  Amber       — navigate / find / search / reach out    (bottom-left)
  B4  Warm red    — destructive / exit / leave / delete     (bottom-right)

The positional hue is a promise to muscle memory.  Red sits in the
bottom-right because that's the natural "danger zone" — the button you reach
last, the one you commit to.  Even when the semantic fit isn't perfect, the
reliable warm-red signal on B4 is worth more than perfectly matching copy.

Teams toggle-mute and Slack huddle-mute live on B4 by design — the mute-state
LED (red=muted, green=live) is now positionally aligned with the red slot
rather than overriding it.
"""

from __future__ import annotations

# Full-brightness active colors per position.
POSITION_ACTIVE: dict[int, tuple[int, int, int]] = {
    1: (0,  175,   50),  # green       (top-left)
    2: (0,   80,  220),  # cool blue   (top-right)
    3: (200, 140,   0),  # amber       (bottom-left)
    4: (220, 35,   0),   # warm red    (bottom-right)
}

# Dim variants — same hue family, ~15% brightness, for "off but aware" states.
POSITION_DIM: dict[int, tuple[int, int, int]] = {
    1: (0,   30,  9),
    2: (0,   15, 40),
    3: (35,  25,  0),
    4: (40,   6,  0),
}

# Application brand colors — used for the context-switch flash animation.
# Tuned for LED visibility, not exact brand hex matching.
BRAND_COLORS: dict[str, tuple[int, int, int]] = {
    "teams":   (100,  80, 220),   # Teams indigo
    "slack":   (160,  30, 160),   # Slack aubergine (brightened for LEDs)
    "outlook": (0,   120, 212),   # Microsoft Fluent blue
}
