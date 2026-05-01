"""
dc29.stats — Local-only fun stats for nerds who secretly want them.

A privacy-preserving counter / unique-set tracker that records the trivia of
your DC29 badge usage: emails deleted, Teams meetings joined, mute presses,
button thumps, splash interactions, scenes played, etc.  Persists to
``~/.config/dc29/stats.toml``.  **Never sends data anywhere.**

Usage from anywhere in the codebase
-----------------------------------

.. code-block:: python

    from dc29.stats import record

    record.email_deleted()
    record.teams_meeting_joined("meeting-id-from-spotify-api")
    record.mute_toggle()
    record.button_press(3)

The convenience helpers in :class:`StatRecorder` keep the call sites short
and the counter names consistent across the codebase.

Adding a new stat
-----------------

1. Add a method to :class:`StatRecorder` that calls
   ``self._stats.increment(...)`` or ``self._stats.add_unique(...)``.
2. Call the new method from wherever the event happens.
3. Optionally add a friendly label to :data:`STAT_LABELS` for the CLI/TUI.

The TOML schema is versioned (``meta.schema_version``) so we can migrate
existing user files when the shape changes.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# tomllib for read (3.11+); tomli for older Pythons.  Optional — stats just
# starts empty if neither is available, which is fine for first run.
try:
    import tomllib as _tomllib
except ImportError:  # pragma: no cover
    try:
        import tomli as _tomllib  # type: ignore[no-redef]
    except ImportError:  # pragma: no cover
        _tomllib = None  # type: ignore[assignment]

log = logging.getLogger(__name__)


SCHEMA_VERSION = 1
DEFAULT_STATS_PATH: Path = Path.home() / ".config" / "dc29" / "stats.toml"


# Friendly labels for the TUI / `dc29 stats` output.  Anything not in this
# table is shown with its raw key name.
STAT_LABELS: dict[str, str] = {
    "emails_deleted":          "📧 Emails deleted",
    "teams_meetings_joined":   "🎥 Teams meetings joined",
    "teams_meeting_minutes":   "⏱  Total minutes in Teams meetings",
    "mute_toggles":            "🎙  Mute mic button presses",
    "button_press_total":      "🔘 Total button presses",
    "button_press_b1":         "  ↳ B1 (top-left)",
    "button_press_b2":         "  ↳ B2 (top-right)",
    "button_press_b3":         "  ↳ B3 (bottom-left)",
    "button_press_b4":         "  ↳ B4 (bottom-right)",
    "splash_fired":            "💦 Splash fidget interactions",
    "scenes_played":           "🎨 Scenes played",
    "effect_modes_started":    "✨ Firmware effects activated",
    "outlook_delete_jingles":  "🔔 Tink jingles played",
    "bridge_starts":           "🔌 Bridge starts (lifetime)",
    "uptime_seconds":          "⏰ Total uptime (seconds, all sessions)",
}


# Sets are tracked separately — the count we report is len(set).
SET_LABELS: dict[str, str] = {
    "unique_teams_meetings":   "🎥 Unique Teams meetings (lifetime)",
    "unique_focused_apps":     "🪟 Unique apps focused (lifetime)",
    "unique_tracks_heard":     "🎵 Unique Spotify tracks heard (lifetime)",
}


class _Stats:
    """The singleton store.  Don't instantiate directly — use :func:`get_stats`."""

    def __init__(self, path: Path = DEFAULT_STATS_PATH) -> None:
        self._path = path
        self._counters: dict[str, int] = {}
        self._sets: dict[str, set[str]] = {}
        self._first_seen: dict[str, str] = {}
        self._last_seen: dict[str, str] = {}
        self._created_at: Optional[str] = None
        self._lock = threading.Lock()
        self._dirty = False
        self._load()

    # ------------------------------------------------------------------
    # Mutation API
    # ------------------------------------------------------------------

    def increment(self, name: str, delta: int = 1) -> None:
        """Atomically increment ``name`` by ``delta`` (default 1)."""
        with self._lock:
            self._counters[name] = self._counters.get(name, 0) + delta
            self._touch(name)
            self._dirty = True

    def add_unique(self, set_name: str, value: str) -> bool:
        """Add ``value`` to the named set.  Returns ``True`` if it was new."""
        with self._lock:
            s = self._sets.setdefault(set_name, set())
            if value in s:
                return False
            s.add(value)
            self._touch(set_name)
            self._dirty = True
            return True

    def _touch(self, name: str) -> None:
        """Update first/last-seen timestamps. Caller must hold the lock."""
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        if name not in self._first_seen:
            self._first_seen[name] = now
        self._last_seen[name] = now

    # ------------------------------------------------------------------
    # Read API
    # ------------------------------------------------------------------

    def get(self, name: str) -> int:
        with self._lock:
            return self._counters.get(name, 0)

    def get_set_size(self, name: str) -> int:
        with self._lock:
            return len(self._sets.get(name, set()))

    def snapshot(self) -> dict:
        """Return a fully-decoupled snapshot for display.

        Returns a dict with keys:
          counters, set_sizes, first_seen, last_seen, schema_version,
          created_at, path
        """
        with self._lock:
            return {
                "counters": dict(self._counters),
                "set_sizes": {k: len(v) for k, v in self._sets.items()},
                "first_seen": dict(self._first_seen),
                "last_seen": dict(self._last_seen),
                "schema_version": SCHEMA_VERSION,
                "created_at": self._created_at,
                "path": str(self._path),
            }

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def reset(self) -> None:
        """Wipe all stats.  The file on disk is overwritten on next save()."""
        with self._lock:
            self._counters.clear()
            self._sets.clear()
            self._first_seen.clear()
            self._last_seen.clear()
            self._created_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
            self._dirty = True
        self.save(force=True)

    def save(self, force: bool = False) -> bool:
        """Atomically write to disk if dirty.  Returns ``True`` if written.

        Atomicity: writes to ``<path>.tmp`` then ``os.replace()`` to the real
        path.  No partial writes on crash.
        """
        with self._lock:
            if not (self._dirty or force):
                return False
            payload = self._render_toml_locked()
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_suffix(self._path.suffix + ".tmp")
            tmp.write_text(payload, encoding="utf-8")
            tmp.replace(self._path)
        except OSError:
            log.exception("stats: failed to save to %s", self._path)
            return False
        with self._lock:
            self._dirty = False
        return True

    def _render_toml_locked(self) -> str:
        """Render to TOML.  Caller must hold the lock."""
        if self._created_at is None:
            self._created_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        out = []
        out.append("# dc29 badge — local stats.  Never sent anywhere; edit or delete at will.")
        out.append("")
        out.append("[meta]")
        out.append(f"schema_version = {SCHEMA_VERSION}")
        out.append(f'created_at = "{self._created_at}"')
        out.append(f'last_save = "{now}"')
        out.append("")
        if self._counters:
            out.append("[counters]")
            for k in sorted(self._counters):
                out.append(f"{k} = {self._counters[k]}")
            out.append("")
        if self._sets:
            out.append("[sets]")
            for k in sorted(self._sets):
                vals = ", ".join(f'"{_escape(v)}"' for v in sorted(self._sets[k]))
                out.append(f"{k} = [{vals}]")
            out.append("")
        if self._first_seen:
            out.append("[first_seen]")
            for k in sorted(self._first_seen):
                out.append(f'{k} = "{self._first_seen[k]}"')
            out.append("")
        if self._last_seen:
            out.append("[last_seen]")
            for k in sorted(self._last_seen):
                out.append(f'{k} = "{self._last_seen[k]}"')
            out.append("")
        return "\n".join(out).rstrip() + "\n"

    def _load(self) -> None:
        if not self._path.exists() or _tomllib is None:
            return
        try:
            with open(self._path, "rb") as fh:
                raw = _tomllib.load(fh)
        except Exception:
            log.exception("stats: failed to load %s", self._path)
            return
        meta = raw.get("meta", {})
        self._created_at = meta.get("created_at")
        # Counters
        for k, v in raw.get("counters", {}).items():
            try:
                self._counters[str(k)] = int(v)
            except (TypeError, ValueError):
                continue
        # Sets
        for k, v in raw.get("sets", {}).items():
            if isinstance(v, list):
                self._sets[str(k)] = {str(x) for x in v}
        # Timestamps (best-effort, stored as strings)
        for k, v in raw.get("first_seen", {}).items():
            self._first_seen[str(k)] = str(v)
        for k, v in raw.get("last_seen", {}).items():
            self._last_seen[str(k)] = str(v)


def _escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


# ---------------------------------------------------------------------------
# Singleton + convenience recorder
# ---------------------------------------------------------------------------


_singleton: Optional[_Stats] = None
_singleton_lock = threading.Lock()


def get_stats() -> _Stats:
    """Return the process-wide :class:`_Stats` singleton."""
    global _singleton
    with _singleton_lock:
        if _singleton is None:
            _singleton = _Stats()
        return _singleton


class StatRecorder:
    """High-level convenience methods for recording common events.

    Indirection layer so call sites don't reach into ``get_stats().increment(...)``
    with a magic string — the names are typed methods here, the strings live
    in one place.
    """

    @property
    def _stats(self) -> _Stats:
        return get_stats()

    # ---- Outlook --------------------------------------------------------

    def email_deleted(self) -> None:
        self._stats.increment("emails_deleted")
        self._stats.increment("outlook_delete_jingles")

    # ---- Teams ----------------------------------------------------------

    def teams_meeting_joined(self, meeting_id: Optional[str] = None) -> None:
        self._stats.increment("teams_meetings_joined")
        if meeting_id:
            self._stats.add_unique("unique_teams_meetings", meeting_id)

    def teams_meeting_minute(self) -> None:
        """Call once per minute while in a Teams meeting (cheap accumulator)."""
        self._stats.increment("teams_meeting_minutes")

    def mute_toggle(self) -> None:
        self._stats.increment("mute_toggles")

    # ---- Buttons + slider ----------------------------------------------

    def button_press(self, n: int) -> None:
        if 1 <= n <= 4:
            self._stats.increment(f"button_press_b{n}")
            self._stats.increment("button_press_total")

    # ---- Effects + scenes ----------------------------------------------

    def splash_fired(self) -> None:
        self._stats.increment("splash_fired")

    def effect_started(self, mode: int) -> None:
        if mode != 0:
            self._stats.increment("effect_modes_started")

    def scene_played(self, name: str) -> None:
        self._stats.increment("scenes_played")
        self._stats.add_unique("unique_scenes_played", name)

    # ---- Bridges + focus -----------------------------------------------

    def bridge_started(self, name: str) -> None:
        self._stats.increment("bridge_starts")
        self._stats.add_unique(f"unique_bridges_started", name)

    def app_focused(self, app_name: str) -> None:
        if app_name:
            self._stats.add_unique("unique_focused_apps", app_name)

    # ---- Spotify (future use) ------------------------------------------

    def spotify_track_heard(self, track_id: str) -> None:
        if track_id:
            self._stats.add_unique("unique_tracks_heard", track_id)

    # ---- Uptime --------------------------------------------------------

    def uptime_tick(self, seconds: int) -> None:
        if seconds > 0:
            self._stats.increment("uptime_seconds", delta=seconds)


# Module-level instance — `from dc29.stats import record` is the canonical use.
record = StatRecorder()


# ---------------------------------------------------------------------------
# Async save loop helper — mount in long-running CLI commands
# ---------------------------------------------------------------------------


async def stats_save_loop(interval_s: float = 30.0) -> None:
    """Periodically flush stats to disk; cancel to stop.

    Use in ``dc29 flow`` / ``dc29 start`` so counters survive ungraceful
    shutdowns within ``interval_s``.  An additional ``save(force=True)`` in
    the parent's ``finally`` block guarantees a final flush on clean exit.
    """
    import asyncio
    stats = get_stats()
    try:
        while True:
            await asyncio.sleep(interval_s)
            stats.save()
    except asyncio.CancelledError:
        stats.save(force=True)
        raise


def render_summary() -> str:
    """Return a human-readable stats summary for ``dc29 stats``."""
    snap = get_stats().snapshot()

    lines: list[str] = []
    lines.append("📊 dc29 badge — local stats")
    lines.append(f"   stored at {snap['path']}")
    if snap["created_at"]:
        lines.append(f"   tracking since {snap['created_at']}")
    lines.append("")

    counters = snap["counters"]
    set_sizes = snap["set_sizes"]

    if not counters and not set_sizes:
        lines.append("   (no stats yet — go press some buttons)")
        return "\n".join(lines)

    # Render labelled stats first, in the canonical order from STAT_LABELS.
    rendered: set[str] = set()
    for key, label in STAT_LABELS.items():
        if key in counters:
            lines.append(f"   {label}: {counters[key]:,}")
            rendered.add(key)
    for key, label in SET_LABELS.items():
        if key in set_sizes:
            lines.append(f"   {label}: {set_sizes[key]:,}")
            rendered.add(key)

    # Catch-all for stats not yet listed in STAT_LABELS / SET_LABELS.
    extras_c = sorted(k for k in counters if k not in rendered)
    extras_s = sorted(k for k in set_sizes if k not in rendered)
    if extras_c or extras_s:
        lines.append("")
        lines.append("   (other counters)")
        for k in extras_c:
            lines.append(f"     {k}: {counters[k]:,}")
        for k in extras_s:
            lines.append(f"     {k} (unique): {set_sizes[k]:,}")

    return "\n".join(lines)
