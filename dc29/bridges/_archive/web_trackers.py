"""Archived: ServiceNow + Linear PageDefs.

Removed from the active registry on 2026-05-09. To re-enable, copy the
PageDef(s) back into ``dc29/bridges/registry.py`` and append to
``ALL_PAGES`` in the web-apps section.
"""

from __future__ import annotations

from dc29.bridges.generic import ActionDef, PageDef


def _a(label, mac_mods, mac_key, win_mods, win_key):
    return ActionDef(label, (mac_mods, mac_key), (win_mods, win_key))


def _same(label, mods, key):
    return ActionDef(label, (mods, key), (mods, key))


SERVICENOW = PageDef(
    name="servicenow",
    description="ServiceNow — portal shortcuts",
    match_names=["servicenow"],
    match_window_title=True,
    brand_color=(111, 42, 134),
    button_actions={
        1: _a("new-tab",         ["cmd"], "t",   ["ctrl"], "t"),
        2: _a("refresh",         ["cmd"], "r",   [], "f5"),
        3: _a("find",            ["cmd"], "f",   ["ctrl"], "f"),
        4: _a("back",            ["cmd"], "[",   ["alt"], "left"),
    },
)

LINEAR = PageDef(
    name="linear",
    description="Linear — issue tracker shortcuts",
    match_names=["linear"],
    match_window_title=True,
    brand_color=(90, 81, 255),
    button_actions={
        1: _same("create-issue", [], "c"),
        2: _same("assign-me",    [], "a"),
        3: _same("filter",       [], "f"),
        4: _same("archive-issue", [], "backspace"),
    },
)
