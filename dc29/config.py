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
        # Runtime overrides — set by CLI flags or live TUI toggles.
        # Take precedence over values from the config file.
        self._overrides: dict[str, Any] = {}

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

    @property
    def sticky_focus_leds(self) -> bool:
        """Keep the last-focused page's LED colors when no app has focus.

        Default: ``False`` — LEDs go dark when focus leaves all bridged apps,
        which doubles as a visual "this app has a custom page" indicator.

        Set ``True`` to leave the most recent page's colors lit until a
        different bridged app gains focus.  Useful if the dark-when-unfocused
        behavior feels distracting.

        Configurable via ``[badge] sticky_focus_leds = true`` in
        ``~/.config/dc29/config.toml``, the ``--sticky-leds`` CLI flag on
        ``dc29 flow`` / ``dc29 start``, or the Effects tab in the TUI.
        Runtime mutations via the property setter take effect on the next
        focus event.
        """
        if "sticky_focus_leds" in self._overrides:
            return bool(self._overrides["sticky_focus_leds"])
        return bool(self._raw.get("badge", {}).get("sticky_focus_leds", False))

    @sticky_focus_leds.setter
    def sticky_focus_leds(self, value: bool) -> None:
        self._overrides["sticky_focus_leds"] = bool(value)

    @property
    def slider_enabled(self) -> bool:
        """Whether the capacitive touch slider injects HID volume keys.

        Default: ``True`` — preserves the as-shipped behavior.  Disable via
        ``[badge] slider_enabled = false`` in config, the ``--no-slider`` CLI
        flag, or the TUI Bridges & Inputs tab.

        RAM-only on the firmware side: every power cycle starts with the
        slider enabled.  When this property is ``False`` at startup, dc29
        proactively sends the disable command so the user setting persists
        across reboots from the Python side.
        """
        if "slider_enabled" in self._overrides:
            return bool(self._overrides["slider_enabled"])
        return bool(self._raw.get("badge", {}).get("slider_enabled", True))

    @slider_enabled.setter
    def slider_enabled(self, value: bool) -> None:
        self._overrides["slider_enabled"] = bool(value)

    @property
    def splash_on_press(self) -> bool:
        """Whether button presses during a light-show fire the firmware splash.

        Default: ``True`` — the fidget-toy feedback is the whole point of
        having effect modes available, and works on battery without USB.

        RAM-only firmware-side; dc29 re-applies on every startup.  Disable
        via ``[badge] splash_on_press = false``, ``--no-splash`` CLI flag, or
        the TUI Effects tab checkbox.
        """
        if "splash_on_press" in self._overrides:
            return bool(self._overrides["splash_on_press"])
        return bool(self._raw.get("badge", {}).get("splash_on_press", True))

    @splash_on_press.setter
    def splash_on_press(self, value: bool) -> None:
        self._overrides["splash_on_press"] = bool(value)

    # ------------------------------------------------------------------
    # Spotify section
    # ------------------------------------------------------------------

    @property
    def spotify_client_id(self) -> Optional[str]:
        """Spotify Web API client ID — user provides their own dev app's ID.

        Register a free app at https://developer.spotify.com/dashboard, add
        ``http://localhost:8754/callback`` to its Redirect URIs, then put the
        client ID in ``~/.config/dc29/config.toml``::

            [spotify]
            client_id = "..."
        """
        v = self._raw.get("spotify", {}).get("client_id")
        return str(v) if v else None

    @property
    def spotify_redirect_uri(self) -> str:
        """OAuth redirect URI; defaults to ``http://127.0.0.1:8754/callback``.

        Spotify treats raw IP loopback as inherently secure and accepts it
        without HTTPS, so the loopback IP form is preferred over ``localhost``
        (which their dashboard now flags as "not secure" on some accounts).
        Override only if you've registered a different URI on your Spotify app.
        """
        v = self._raw.get("spotify", {}).get("redirect_uri")
        return str(v) if v else "http://127.0.0.1:8754/callback"

    # ------------------------------------------------------------------
    # Audio-reactive section (BlackHole + FFT)
    # ------------------------------------------------------------------

    @property
    def audio_device(self) -> Optional[str]:
        """Substring matched against device names in the audio capture init.

        Default: ``None`` → auto-detect BlackHole (preferred), else the
        system default input device.  Set explicitly via
        ``[audio] device = "BlackHole 2ch"`` if you have multiple loopback
        devices and want to be sure.
        """
        v = self._raw.get("audio", {}).get("device")
        return str(v) if v else None

    @property
    def audio_beat_threshold(self) -> float:
        """How many σ above the rolling bass-energy mean triggers a beat event.

        Default ``1.5``.  Lower (e.g. ``1.0``) for more sensitive beat
        detection on quiet passages; higher (e.g. ``2.0``) for cleaner beats
        on hard-hitting tracks.  ``[audio] beat_threshold = ...`` in config.
        """
        try:
            return float(self._raw.get("audio", {}).get("beat_threshold", 1.5))
        except (TypeError, ValueError):
            return 1.5

    # ------------------------------------------------------------------
    # Spotify section (continued — focus_only is the last property)
    # ------------------------------------------------------------------

    @property
    def spotify_focus_only(self) -> bool:
        """If true, react only when Spotify (or any music player) is focused.

        Default false — reacts whenever Spotify is playing, regardless of
        which app the user has focused.  Useful when you want the LEDs to
        stay quiet during productivity work.
        """
        return bool(self._raw.get("spotify", {}).get("focus_only", False))

    # ------------------------------------------------------------------
    # Bridge enable/disable
    # ------------------------------------------------------------------

    @property
    def enabled_bridges(self) -> set[str]:
        """Set of bridge names the user has opted in to running.

        Default: empty set — every bridge is disabled out of the box.
        Users opt in via:
          * CLI flags (``--enable <name>`` repeatable, ``--enable-all``)
          * The ``[bridges] enabled = ["teams", ...]`` config key
          * The TUI Bridges tab

        Lookup order: in-process overrides (CLI/TUI) take precedence over
        config-file values; if neither is set, the default is empty.
        """
        if "enabled_bridges" in self._overrides:
            return set(self._overrides["enabled_bridges"])
        raw = self._raw.get("bridges", {}).get("enabled", [])
        if isinstance(raw, str):
            raw = [s.strip() for s in raw.split(",") if s.strip()]
        return {str(name).lower() for name in raw}

    @enabled_bridges.setter
    def enabled_bridges(self, value) -> None:
        self._overrides["enabled_bridges"] = {str(n).lower() for n in value}

    def is_bridge_enabled(self, name: str) -> bool:
        """Return ``True`` if the named bridge should be started."""
        return name.lower() in self.enabled_bridges

    def set_bridge_enabled(self, name: str, enabled: bool) -> None:
        """Toggle a single bridge in the enabled set (runtime mutation)."""
        current = set(self.enabled_bridges)
        n = name.lower()
        if enabled:
            current.add(n)
        else:
            current.discard(n)
        self.enabled_bridges = current

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
