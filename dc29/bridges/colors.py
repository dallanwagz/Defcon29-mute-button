"""
dc29.bridges.colors — Positional color semantics (Option A).

Four positions, four color families — always consistent across every page:

  B1  Warm red    — destructive / exit / leave / delete
  B2  Cool blue   — status / visibility / communication
  B3  Amber       — navigate / find / search / reach out
  B4  Green       — positive / create / connect / confirm

The positional hue is a promise to muscle memory.  Even when the semantic fit
isn't perfect (Slack "all-unreads" on B1 isn't destructive), the reliable
warm-red signal on B1 is worth more than perfectly matching copy.

Intentional exception: Teams B4 (toggle-mute).  Red when muted, green when
live.  Mute status is too safety-critical to subordinate to position rules —
the real-time state IS the semantics.
"""

from __future__ import annotations

# Full-brightness active colors per position.
POSITION_ACTIVE: dict[int, tuple[int, int, int]] = {
    1: (220, 35,   0),   # warm red
    2: (0,   80,  220),  # cool blue
    3: (200, 140,   0),  # amber
    4: (0,  175,   50),  # green
}

# Dim variants — same hue family, ~15% brightness, for "off but aware" states.
POSITION_DIM: dict[int, tuple[int, int, int]] = {
    1: (40,  6,   0),
    2: (0,   15,  40),
    3: (35,  25,  0),
    4: (0,   30,  9),
}

# Application brand colors — used for the context-switch flash animation.
# Tuned for LED visibility, not exact brand hex matching.
BRAND_COLORS: dict[str, tuple[int, int, int]] = {
    "teams":   (100,  80, 220),   # Teams indigo
    "slack":   (160,  30, 160),   # Slack aubergine (brightened for LEDs)
    "outlook": (0,   120, 212),   # Microsoft Fluent blue
}
