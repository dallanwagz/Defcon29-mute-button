"""
dc29.config — User configuration for the dc29-badge toolchain.

Config file is stored at ``~/.config/dc29/config.toml`` (or the path given by
the ``DC29_CONFIG`` environment variable).  All sections are optional; sensible
defaults are used when a key is absent.

Example ``config.toml``::

    [badge]
    port       = "/dev/tty.usbmodem14201"
    brightness = 0.8

    [teams]
    toggle_hotkey = "<ctrl>+<alt>+m"
    [teams.buttons]
    1 = "leave-call"
    2 = "toggle-video"
    3 = "toggle-hand"
    4 = "toggle-mute"

    [slack.buttons]
    1 = "all-unreads"
    2 = "mentions"
    3 = "quick-switch"
    4 = "huddle"
    [slack.colors]
    all-unreads  = "0,60,200"
    mentions     = "120,0,200"
    quick-switch = "0,180,160"
    huddle       = "0,160,0"

    [outlook.buttons]
    1 = "delete"
    2 = "reply"
    3 = "reply-all"
    4 = "forward"
    [outlook.colors]
    delete    = "220,0,0"
    reply     = "0,60,180"
    reply-all = "180,160,0"
    forward   = "100,0,180"
    pulse     = "255,0,0"
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional

# Use tomllib (stdlib, 3.11+) or fallback to tomli (pip install tomli)
try:
    import tomllib
except ImportError:
    try:
        import tomli as tomllib  # type: ignore[no-redef]
    except ImportError:
        tomllib = None  # type: ignore[assignment]

_DEFAULT_CONFIG_PATH = Path.home() / ".config" / "dc29" / "config.toml"

# ---------------------------------------------------------------------------
# Default values
# ---------------------------------------------------------------------------

_DEFAULTS: dict[str, Any] = {
    "badge": {
        "port": None,
        "brightness": 1.0,
    },
    "teams": {
        "toggle_hotkey": None,
        "buttons": {1: "leave-call", 2: "toggle-video", 3: "toggle-hand", 4: "toggle-mute"},
    },
    "slack": {
        "buttons": {1: "all-unreads", 2: "mentions", 3: "quick-switch", 4: "huddle"},
        "colors": {},
    },
    "outlook": {
        "buttons": {1: "delete", 2: "reply", 3: "reply-all", 4: "forward"},
        "colors": {},
    },
}


def _parse_color(s: str) -> Optional[tuple[int, int, int]]:
    """Parse 'r,g,b' string → (r, g, b) or None on failure."""
    try:
        parts = [int(x.strip()) for x in s.split(",")]
        if len(parts) == 3 and all(0 <= v <= 255 for v in parts):
            return (parts[0], parts[1], parts[2])
    except (ValueError, AttributeError):
        pass
    return None


# ---------------------------------------------------------------------------
# Config class
# ---------------------------------------------------------------------------

class Config:
    """Parsed and merged dc29 configuration.

    Usage::

        cfg = Config.load()
        port = cfg.badge_port
        actions = cfg.teams_button_actions   # {1: "leave-call", ...}
        colors  = cfg.slack_led_colors       # {action: (r,g,b), ...}
    """

    def __init__(self, raw: dict[str, Any]) -> None:
        self._raw = raw

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def load(cls, path: Path | None = None) -> "Config":
        """Load configuration from *path* (defaults to ``~/.config/dc29/config.toml``).

        Missing file → all defaults.  Unknown keys are silently ignored.
        """
        if path is None:
            path = Path(os.environ.get("DC29_CONFIG", str(_DEFAULT_CONFIG_PATH)))

        raw: dict[str, Any] = {}
        if path.exists():
            if tomllib is None:
                import warnings
                warnings.warn(
                    "tomllib/tomli not available; config file ignored. "
                    "Install tomli: pip install tomli",
                    stacklevel=2,
                )
            else:
                with open(path, "rb") as fh:
                    raw = tomllib.load(fh)
        return cls(raw)

    # ------------------------------------------------------------------
    # Badge section
    # ------------------------------------------------------------------

    @property
    def badge_port(self) -> str | None:
        return self._raw.get("badge", {}).get("port") or None

    @property
    def badge_brightness(self) -> float:
        v = self._raw.get("badge", {}).get("brightness", 1.0)
        return max(0.0, min(1.0, float(v)))

    # ------------------------------------------------------------------
    # Teams section
    # ------------------------------------------------------------------

    @property
    def teams_toggle_hotkey(self) -> str | None:
        return self._raw.get("teams", {}).get("toggle_hotkey") or None

    @property
    def teams_button_actions(self) -> dict[int, str]:
        defaults = dict(_DEFAULTS["teams"]["buttons"])
        raw_btns = self._raw.get("teams", {}).get("buttons", {})
        for k, v in raw_btns.items():
            defaults[int(k)] = str(v)
        return defaults

    # ------------------------------------------------------------------
    # Slack section
    # ------------------------------------------------------------------

    @property
    def slack_button_actions(self) -> dict[int, str]:
        defaults = dict(_DEFAULTS["slack"]["buttons"])
        raw_btns = self._raw.get("slack", {}).get("buttons", {})
        for k, v in raw_btns.items():
            defaults[int(k)] = str(v)
        return defaults

    @property
    def slack_led_colors(self) -> dict[str, tuple[int, int, int]]:
        """Map of action name → (r, g, b) color overrides from config."""
        result: dict[str, tuple[int, int, int]] = {}
        for action, val in self._raw.get("slack", {}).get("colors", {}).items():
            color = _parse_color(str(val))
            if color:
                result[str(action)] = color
        return result

    # ------------------------------------------------------------------
    # Outlook section
    # ------------------------------------------------------------------

    @property
    def outlook_button_actions(self) -> dict[int, str]:
        defaults = dict(_DEFAULTS["outlook"]["buttons"])
        raw_btns = self._raw.get("outlook", {}).get("buttons", {})
        for k, v in raw_btns.items():
            defaults[int(k)] = str(v)
        return defaults

    @property
    def outlook_led_colors(self) -> dict[str, tuple[int, int, int]]:
        """Map of action name → (r, g, b) color overrides from config."""
        result: dict[str, tuple[int, int, int]] = {}
        raw = self._raw.get("outlook", {}).get("colors", {})
        for action, val in raw.items():
            if action == "pulse":
                continue
            color = _parse_color(str(val))
            if color:
                result[str(action)] = color
        return result

    @property
    def outlook_pulse_color(self) -> Optional[tuple[int, int, int]]:
        """RGB color for the Outlook delete satisfaction pulse."""
        raw = self._raw.get("outlook", {}).get("colors", {}).get("pulse")
        if raw:
            return _parse_color(str(raw))
        return None

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def as_toml(self) -> str:
        """Render the effective (defaults + overrides) config as a TOML string."""
        teams_btns = self.teams_button_actions
        slack_btns = self.slack_button_actions
        outlook_btns = self.outlook_button_actions
        lines = [
            "[badge]",
            f'port       = "{self.badge_port or ""}"',
            f"brightness = {self.badge_brightness}",
            "",
            "[teams]",
            f'toggle_hotkey = "{self.teams_toggle_hotkey or ""}"',
            "",
            "[teams.buttons]",
        ]
        for btn, action in sorted(teams_btns.items()):
            lines.append(f'{btn} = "{action}"')
        lines += ["", "[slack.buttons]"]
        for btn, action in sorted(slack_btns.items()):
            lines.append(f'{btn} = "{action}"')
        lines += [
            "",
            "# Slack LED colors (r,g,b per action)",
            "# [slack.colors]",
            '# all-unreads  = "0,60,200"',
            '# mentions     = "120,0,200"',
            '# quick-switch = "0,180,160"',
            '# huddle       = "0,160,0"',
            "",
            "[outlook.buttons]",
        ]
        for btn, action in sorted(outlook_btns.items()):
            lines.append(f'{btn} = "{action}"')
        lines += [
            "",
            "# Outlook LED colors and delete-pulse color (r,g,b)",
            "# [outlook.colors]",
            '# delete    = "220,0,0"',
            '# reply     = "0,60,180"',
            '# reply-all = "180,160,0"',
            '# forward   = "100,0,180"',
            '# pulse     = "255,0,0"   # delete satisfaction pulse',
        ]
        return "\n".join(lines) + "\n"


# Module-level singleton, loaded lazily.
_config: Config | None = None


def get_config(reload: bool = False) -> Config:
    """Return the module-level :class:`Config` singleton, loading it on first call."""
    global _config
    if _config is None or reload:
        _config = Config.load()
    return _config
