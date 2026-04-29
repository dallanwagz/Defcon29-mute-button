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
    # Which button does which Teams action in a meeting.
    # Values: toggle-mute | toggle-video | toggle-hand |
    #         toggle-background-blur | leave-call
    [teams.buttons]
    1 = "leave-call"
    2 = "toggle-video"
    3 = "toggle-hand"
    4 = "toggle-mute"

    [slack]
    # Slack shortcuts are injected as HID keycodes (requires pynput).
    # Values: toggle-mute | toggle-video | leave-call | raise-hand
    [slack.buttons]
    1 = "leave-call"
    2 = "toggle-video"
    3 = "raise-hand"
    4 = "toggle-mute"
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

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
        "buttons": {
            1: "leave-call",
            2: "toggle-video",
            3: "toggle-hand",
            4: "toggle-mute",
        },
    },
    "slack": {
        "buttons": {
            1: "leave-call",
            2: "toggle-video",
            3: "raise-hand",
            4: "toggle-mute",
        },
    },
}


# ---------------------------------------------------------------------------
# Config class
# ---------------------------------------------------------------------------

class Config:
    """Parsed and merged dc29 configuration.

    Usage::

        cfg = Config.load()
        port = cfg.badge_port          # None if not set
        brightness = cfg.badge_brightness
        hotkey = cfg.teams_toggle_hotkey
        actions = cfg.teams_button_actions  # {1: "leave-call", ...}
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
        """Serial port path, or ``None`` to auto-detect."""
        return self._raw.get("badge", {}).get("port") or None

    @property
    def badge_brightness(self) -> float:
        """Global LED brightness scalar in [0.0, 1.0]."""
        v = self._raw.get("badge", {}).get("brightness", 1.0)
        return max(0.0, min(1.0, float(v)))

    # ------------------------------------------------------------------
    # Teams section
    # ------------------------------------------------------------------

    @property
    def teams_toggle_hotkey(self) -> str | None:
        """pynput hotkey string for Teams mute toggle, or ``None``."""
        return self._raw.get("teams", {}).get("toggle_hotkey") or None

    @property
    def teams_button_actions(self) -> dict[int, str]:
        """Map of button number (1–4) → Teams API action string.

        Valid actions: ``toggle-mute``, ``toggle-video``, ``toggle-hand``,
        ``toggle-background-blur``, ``leave-call``.
        """
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
        """Map of button number (1–4) → Slack shortcut action string."""
        defaults = dict(_DEFAULTS["slack"]["buttons"])
        raw_btns = self._raw.get("slack", {}).get("buttons", {})
        for k, v in raw_btns.items():
            defaults[int(k)] = str(v)
        return defaults

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def as_toml(self) -> str:
        """Render the *effective* (defaults + overrides) config as a TOML string."""
        teams_btns = self.teams_button_actions
        slack_btns = self.slack_button_actions
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
        lines += [
            "",
            "[slack.buttons]",
        ]
        for btn, action in sorted(slack_btns.items()):
            lines.append(f'{btn} = "{action}"')
        return "\n".join(lines) + "\n"


# Module-level singleton, loaded lazily.
_config: Config | None = None


def get_config(reload: bool = False) -> Config:
    """Return the module-level :class:`Config` singleton, loading it on first call."""
    global _config
    if _config is None or reload:
        _config = Config.load()
    return _config
