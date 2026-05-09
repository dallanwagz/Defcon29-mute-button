"""
dc29.bridges.manifest — Single source of truth for available bridges.

Every bridge that can be enabled in ``dc29 flow`` or ``dc29 start`` is listed
here.  Adding a new bridge means:

1. Implement the bridge class (typically extending :class:`FocusBridge` or
   :class:`BaseBridge`).
2. Append a :class:`BridgeSpec` entry below in canonical priority order.
3. That's it — CLI flags, the TUI checkbox list, and config persistence
   discover it automatically.

Default: every bridge is **disabled**.  Users opt-in via the CLI flag
``--enable <name>`` (repeatable), ``--enable-all`` , the
``[bridges] enabled = [...]`` config key, or the TUI Bridges tab.

Priority order
--------------
The list order determines hook-chain priority.  First-installed = innermost
(lowest priority).  Last-installed = outermost (highest priority — wins
when multiple bridges claim the same button).

Today: generic FocusBridges first → Slack → Outlook → Teams (highest).  The
TeamsBridge wraps everything else because mute-state during a meeting must
override any focused app's bindings.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional, TYPE_CHECKING

from dc29.bridges.registry import ALL_PAGES

if TYPE_CHECKING:
    from dc29.badge import BadgeAPI
    from dc29.bridges.base import BaseBridge
    from dc29.config import Config


@dataclass(frozen=True)
class BridgeSpec:
    """Static metadata for a bridge that can be enabled/disabled.

    Args:
        name:        Slug used in CLI flags, config keys, and TUI checkboxes.
                     Must be unique across the manifest.
        description: One-line human label for the TUI and ``--help`` output.
        factory:     Callable taking ``(badge, config)`` and returning the
                     bridge instance.  Constructed lazily so a disabled
                     bridge never imports its dependencies.
    """

    name: str
    description: str
    factory: Callable[["BadgeAPI", "Config"], "BaseBridge"]


def _make_teams(badge: "BadgeAPI", cfg: "Config") -> "BaseBridge":
    from dc29.bridges.teams import TeamsBridge
    return TeamsBridge(badge, toggle_hotkey=cfg.teams_toggle_hotkey)


def _make_slack(badge: "BadgeAPI", cfg: "Config") -> "BaseBridge":
    from dc29.bridges.slack import SlackBridge
    return SlackBridge(badge)


def _make_outlook(badge: "BadgeAPI", cfg: "Config") -> "BaseBridge":
    from dc29.bridges.outlook import OutlookBridge
    return OutlookBridge(badge)


def _make_audio_reactive(badge: "BadgeAPI", cfg: "Config") -> "BaseBridge":
    from dc29.bridges.audio_reactive import AudioReactiveBridge
    return AudioReactiveBridge(badge, cfg)


def _make_beat_strobe(badge: "BadgeAPI", cfg: "Config") -> "BaseBridge":
    from dc29.bridges.beat_strobe import BeatStrobeBridge
    return BeatStrobeBridge(badge, cfg)


def _make_stay_awake(badge: "BadgeAPI", cfg: "Config") -> "BaseBridge":
    from dc29.bridges.stay_awake import StayAwakeBridge
    return StayAwakeBridge(badge, cfg)


def _make_generic(page_def):
    """Closure over a PageDef to produce a factory."""
    from dc29.bridges.generic import GenericFocusBridge

    def _factory(badge: "BadgeAPI", cfg: "Config") -> "BaseBridge":
        return GenericFocusBridge(badge, page_def)

    return _factory


# Canonical priority order: generic apps first (lowest), then native apps,
# Teams last (highest).  When iterating to start bridges, install in this
# order so the hook chain ends up correct.
BRIDGE_MANIFEST: list[BridgeSpec] = [
    *[
        BridgeSpec(
            name=p.name,
            description=p.description,
            factory=_make_generic(p),
        )
        for p in ALL_PAGES
    ],
    BridgeSpec(
        name="slack",
        description="Slack — productivity shortcuts + huddle mute indicator",
        factory=_make_slack,
    ),
    BridgeSpec(
        name="outlook",
        description="Outlook — email shortcuts + delete pulse",
        factory=_make_outlook,
    ),
    BridgeSpec(
        name="audio-reactive",
        description="Live audio-reactive LED show (BlackHole + FFT, optional Spotify palette)",
        factory=_make_audio_reactive,
    ),
    BridgeSpec(
        name="beat-strobe",
        description="Tight 200 Hz beat strobe — DJ booth vibe (BlackHole + FFT)",
        factory=_make_beat_strobe,
    ),
    BridgeSpec(
        name="stay-awake",
        description="Stay Awake — keep the host awake on a timer with optional LED viz",
        factory=_make_stay_awake,
    ),
    BridgeSpec(
        name="teams",
        description="Microsoft Teams — meeting page + mute indicator (highest priority)",
        factory=_make_teams,
    ),
]


def all_bridge_names() -> list[str]:
    """Return every bridge name in canonical priority order."""
    return [spec.name for spec in BRIDGE_MANIFEST]


def find_spec(name: str) -> Optional[BridgeSpec]:
    """Look up a :class:`BridgeSpec` by name (case-insensitive)."""
    needle = name.lower()
    for spec in BRIDGE_MANIFEST:
        if spec.name.lower() == needle:
            return spec
    return None
