"""
dc29.bridges.manager — Live start/stop coordinator for bridge tasks.

The :class:`BridgeManager` owns the asyncio task for every running bridge
and reconciles that set against :attr:`Config.enabled_bridges` whenever
:meth:`reconcile` is called.  Use cases:

1. ``dc29 flow`` / ``dc29 start`` startup: build the manager, call
   ``reconcile()`` once to bring up the user's enabled bridges.
2. TUI Bridges tab: when the user toggles a checkbox, the TUI updates
   :class:`Config` and then calls ``reconcile()`` — the manager diffs
   the running set against the new wanted set and starts or cancels the
   delta.

Hot-toggle correctness depends on:

* The button-handler registry on :class:`BadgeAPI` — handlers are added
  and removed by name, so a stopped bridge cleanly deregisters via its
  ``finally`` block in :meth:`FocusBridge.run`.
* Each bridge's run-loop ``finally`` clearing its LEDs and uninstalling
  its hook on ``CancelledError``.

Hot-toggle limits — known and acceptable:

* Restarting a bridge mid-meeting may briefly clear LED state until the
  bridge's first focus poll completes (~500 ms).
* If a bridge crashed (task ended with an exception), it stays stopped
  until the user disables/re-enables it; we don't auto-restart.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional, TYPE_CHECKING

from dc29.bridges.manifest import BRIDGE_MANIFEST, find_spec

if TYPE_CHECKING:
    from dc29.badge import BadgeAPI
    from dc29.config import Config

log = logging.getLogger(__name__)


# Manifest position → priority value.  Multiplied so future inserts can
# squeeze between existing entries without re-sorting all of them.
_PRIORITY_STEP = 10


def _priority_for(name: str) -> int:
    """Higher = called first in the button-handler chain.

    Manifest order is canonical: earlier entries (generic bridges) get
    lower priority, later entries (Slack → Outlook → Teams) get higher.
    """
    for i, spec in enumerate(BRIDGE_MANIFEST):
        if spec.name == name:
            return i * _PRIORITY_STEP
    return 0


class BridgeManager:
    """Owns the live set of bridge asyncio tasks for one BadgeAPI.

    Always paired with a :class:`Config` instance — the manager reads
    :attr:`Config.enabled_bridges` to decide what should be running, and
    the user mutates that set via CLI flags or TUI checkboxes.
    """

    def __init__(self, badge: "BadgeAPI", cfg: "Config") -> None:
        self._badge = badge
        self._cfg = cfg
        self._tasks: dict[str, asyncio.Task] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def running(self) -> set[str]:
        """Names of bridges currently running (task created and not done)."""
        return {name for name, t in self._tasks.items() if not t.done()}

    def reconcile(self) -> tuple[list[str], list[str]]:
        """Diff running set vs ``cfg.enabled_bridges`` and start/stop the delta.

        Returns ``(started, stopped)`` lists for logging.  Safe to call
        repeatedly; idempotent when no changes are needed.
        """
        wanted = set(self._cfg.enabled_bridges)
        running = self.running
        to_stop = sorted(running - wanted)
        to_start = sorted(
            wanted - running,
            key=_priority_for,  # start lower-priority first so chain order matches manifest
        )

        for name in to_stop:
            self._stop(name)
        for name in to_start:
            self._start(name)

        if to_start or to_stop:
            log.info(
                "Bridge reconcile: started=%s stopped=%s now-running=%s",
                to_start, to_stop, sorted(self.running),
            )
        return to_start, to_stop

    async def stop_all(self) -> None:
        """Cancel every running bridge task and wait for cleanup.

        Use in the ``finally`` of ``_run_flow`` / ``_run_start`` so cleanup
        (LED clear, hook removal, set_current_page(None)) actually completes
        before the BadgeAPI serial port is closed.
        """
        for name in list(self._tasks):
            self._stop(name)
        if self._tasks:
            await asyncio.gather(*self._tasks.values(), return_exceptions=True)
            self._tasks.clear()

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _start(self, name: str) -> None:
        if name in self._tasks and not self._tasks[name].done():
            return  # already running
        spec = find_spec(name)
        if spec is None:
            log.warning("BridgeManager.start: no bridge named %r in manifest", name)
            return
        try:
            bridge = spec.factory(self._badge, self._cfg)
        except Exception:
            log.exception("BridgeManager.start: factory for %r raised", name)
            return
        # Priority is read by base.py's _install_button_hook when the run
        # loop calls it — set the attribute before the task starts so the
        # first hook installation gets the correct priority.
        bridge._priority_value = _priority_for(name)
        self._tasks[name] = asyncio.create_task(bridge.run(), name=f"bridge:{name}")
        try:
            from dc29.stats import record
            record.bridge_started(name)
        except Exception:
            pass

    def _stop(self, name: str) -> None:
        task = self._tasks.pop(name, None)
        if task is None:
            return
        if not task.done():
            task.cancel()
        # We deliberately do NOT await here — reconcile() is sync.  The
        # task's finally block runs asynchronously and cleans up its hook
        # and LEDs.  stop_all() is the awaited counterpart for shutdown.
