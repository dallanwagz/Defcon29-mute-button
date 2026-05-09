"""Archived: Figma + Notion PageDefs.

Removed from the active registry on 2026-05-09. Niche per-user apps that
weren't pulling their weight in the default profile set. To re-enable, copy
the PageDef(s) back into ``dc29/bridges/registry.py`` and append to
``ALL_PAGES`` (native-app section, highest priority).
"""

from __future__ import annotations

from dc29.bridges.generic import ActionDef, PageDef


def _a(label, mac_mods, mac_key, win_mods, win_key):
    return ActionDef(label, (mac_mods, mac_key), (win_mods, win_key))


def _same(label, mods, key):
    return ActionDef(label, (mods, key), (mods, key))


FIGMA = PageDef(
    name="figma",
    description="Figma — design shortcuts",
    match_names=["figma"],
    brand_color=(162, 89, 255),
    button_actions={
        1: _a("duplicate",       ["cmd"], "d",   ["ctrl"], "d"),
        2: _a("toggle-ui",       ["cmd"], "\\",  ["ctrl"], "\\"),
        3: _a("find-replace",    ["cmd"], "f",   ["ctrl"], "f"),
        4: _same("delete-layer",  [], "backspace"),
    },
)

NOTION = PageDef(
    name="notion",
    description="Notion — workspace shortcuts",
    match_names=["notion"],
    brand_color=(255, 255, 255),
    button_actions={
        1: _same("insert-block", [], "/"),
        2: _a("toggle-sidebar",  ["cmd"], "\\",  ["ctrl"], "\\"),
        3: _a("quick-find",      ["cmd"], "p",   ["ctrl"], "p"),
        4: _a("undo",            ["cmd"], "z",   ["ctrl"], "z"),
    },
)
