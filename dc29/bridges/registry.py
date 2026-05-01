"""
dc29.bridges.registry — Page definitions for all supported apps.

Every entry is a :class:`~dc29.bridges.generic.PageDef` that describes:
  - which app to watch for (process name or window-title substring)
  - 4 shortcuts mapped to the 4 button positions
  - brand color for the context-switch flash animation

Positional semantics (always):
  B1 warm-red  — destructive / exit / undo / delete
  B2 cool-blue — status / visibility / toggle / communicate
  B3 amber     — navigate / find / search / jump
  B4 green     — create / save / confirm / generate

Native apps use process-name matching.  Web apps use window-title matching
(``match_window_title=True``) — the substring appears in the browser tab title.
"""

from __future__ import annotations

from dc29.bridges.generic import ActionDef, PageDef

# Shorthand helpers: _a(label, mac_mods, mac_key, win_mods, win_key)
def _a(
    label: str,
    mac_mods: list[str],
    mac_key: str,
    win_mods: list[str],
    win_key: str,
) -> ActionDef:
    return ActionDef(label, (mac_mods, mac_key), (win_mods, win_key))

def _same(label: str, mods: list[str], key: str) -> ActionDef:
    """Same shortcut on both platforms."""
    return ActionDef(label, (mods, key), (mods, key))


# ---------------------------------------------------------------------------
# Native desktop apps
# ---------------------------------------------------------------------------

VSCODE = PageDef(
    name="vscode",
    description="VS Code — editor controls",
    match_names=["code", "visual studio code"],
    brand_color=(0, 120, 212),   # VS Code blue
    button_actions={
        1: _a("save",            ["cmd"], "s",   ["ctrl"], "s"),
        2: _a("terminal",        ["ctrl"], "`",  ["ctrl"], "`"),
        3: _a("quick-open",      ["cmd"], "p",   ["ctrl"], "p"),
        4: _a("close-tab",       ["cmd"], "w",   ["ctrl"], "w"),
    },
)

CURSOR = PageDef(
    name="cursor",
    description="Cursor — AI editor",
    match_names=["cursor"],
    brand_color=(90, 90, 90),    # Cursor dark-grey
    button_actions={
        1: _a("ai-chat",         ["cmd"], "k",   ["ctrl"], "k"),
        2: _a("terminal",        ["ctrl"], "`",  ["ctrl"], "`"),
        3: _a("quick-open",      ["cmd"], "p",   ["ctrl"], "p"),
        4: _a("close-tab",       ["cmd"], "w",   ["ctrl"], "w"),
    },
)

FIGMA = PageDef(
    name="figma",
    description="Figma — design shortcuts",
    match_names=["figma"],
    brand_color=(162, 89, 255),  # Figma purple
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
    brand_color=(255, 255, 255),  # Notion white (will flash subtle)
    button_actions={
        1: _same("insert-block", [], "/"),
        2: _a("toggle-sidebar",  ["cmd"], "\\",  ["ctrl"], "\\"),
        3: _a("quick-find",      ["cmd"], "p",   ["ctrl"], "p"),
        4: _a("undo",            ["cmd"], "z",   ["ctrl"], "z"),
    },
)

WORD = PageDef(
    name="word",
    description="Microsoft Word — document shortcuts",
    match_names=["microsoft word"],
    brand_color=(43, 87, 151),   # Word blue
    button_actions={
        1: _a("save",            ["cmd"], "s",   ["ctrl"], "s"),
        2: _a("bold",            ["cmd"], "b",   ["ctrl"], "b"),
        3: _a("find",            ["cmd"], "f",   ["ctrl"], "f"),
        4: _a("undo",            ["cmd"], "z",   ["ctrl"], "z"),
    },
)

EXCEL = PageDef(
    name="excel",
    description="Microsoft Excel — spreadsheet shortcuts",
    match_names=["microsoft excel"],
    brand_color=(33, 115, 70),   # Excel green
    button_actions={
        1: _a("save",            ["cmd"], "s",   ["ctrl"], "s"),
        2: _a("toggle-filter",   ["ctrl", "shift"], "l",  ["ctrl", "shift"], "l"),
        3: _a("find",            ["cmd"], "f",   ["ctrl"], "f"),
        4: _a("undo",            ["cmd"], "z",   ["ctrl"], "z"),
    },
)


# ---------------------------------------------------------------------------
# Web apps — match browser window title (match_window_title=True)
# ---------------------------------------------------------------------------

JIRA = PageDef(
    name="jira",
    description="Jira — issue tracker shortcuts",
    match_names=["jira"],
    match_window_title=True,
    brand_color=(0, 82, 204),    # Atlassian blue
    button_actions={
        1: _same("create-issue", [], "c"),
        2: _same("assign-me",    [], "i"),
        3: _same("search",       [], "/"),
        4: _same("cancel",       [], "escape"),
    },
)

CONFLUENCE = PageDef(
    name="confluence",
    description="Confluence — wiki shortcuts",
    match_names=["confluence"],
    match_window_title=True,
    brand_color=(0, 82, 204),    # Atlassian blue
    button_actions={
        1: _same("edit-page",    [], "e"),
        2: _same("watch-page",   [], "w"),
        3: _a("find",            ["cmd"], "f",   ["ctrl"], "f"),
        4: _same("cancel",       [], "escape"),
    },
)

LINEAR = PageDef(
    name="linear",
    description="Linear — issue tracker shortcuts",
    match_names=["linear"],
    match_window_title=True,
    brand_color=(90, 81, 255),   # Linear indigo
    button_actions={
        1: _same("create-issue", [], "c"),
        2: _same("assign-me",    [], "a"),
        3: _same("filter",       [], "f"),
        4: _same("archive-issue", [], "backspace"),
    },
)

CHROME = PageDef(
    name="chrome",
    description="Chrome — browser shortcuts",
    match_names=["google chrome", "chrome"],
    brand_color=(66, 133, 244),   # Chrome blue
    button_actions={
        1: _a("new-tab",          ["cmd"], "t",   ["ctrl"], "t"),
        2: _a("refresh",          ["cmd"], "r",   ["ctrl"], "r"),
        3: _a("reopen-tab",       ["cmd", "shift"], "t",  ["ctrl", "shift"], "t"),
        4: _a("close-tab",        ["cmd"], "w",   ["ctrl"], "w"),
    },
)

GITHUB = PageDef(
    name="github",
    description="GitHub — repository shortcuts",
    match_names=["github"],
    match_window_title=True,
    brand_color=(36, 41, 47),    # GitHub dark (will flash as dim)
    button_actions={
        1: _same("open-dev",     [], "."),   # opens github.dev
        2: _same("switch-branch", [], "w"),
        3: _same("file-finder",  [], "t"),
        4: _same("close-dialog", [], "escape"),
    },
)

SERVICENOW = PageDef(
    name="servicenow",
    description="ServiceNow — portal shortcuts",
    match_names=["servicenow"],
    match_window_title=True,
    brand_color=(111, 42, 134),  # ServiceNow purple
    button_actions={
        1: _a("new-tab",         ["cmd"], "t",   ["ctrl"], "t"),
        2: _a("refresh",         ["cmd"], "r",   [], "f5"),
        3: _a("find",            ["cmd"], "f",   ["ctrl"], "f"),
        4: _a("back",            ["cmd"], "[",   ["alt"], "left"),
    },
)

SHAREPOINT = PageDef(
    name="sharepoint",
    description="SharePoint — portal shortcuts",
    match_names=["sharepoint"],
    match_window_title=True,
    brand_color=(3, 131, 135),   # SharePoint teal
    button_actions={
        1: _a("new-tab",         ["cmd"], "t",   ["ctrl"], "t"),
        2: _a("refresh",         ["cmd"], "r",   [], "f5"),
        3: _a("find",            ["cmd"], "f",   ["ctrl"], "f"),
        4: _a("back",            ["cmd"], "[",   ["alt"], "left"),
    },
)

CHATGPT = PageDef(
    name="chatgpt",
    description="ChatGPT — AI chat shortcuts",
    match_names=["chatgpt"],
    match_window_title=True,
    brand_color=(16, 163, 127),  # ChatGPT teal-green
    button_actions={
        1: _a("submit",          ["cmd"], "enter", ["ctrl"], "enter"),
        2: _a("back",            ["cmd"], "[",   ["alt"], "left"),
        3: _a("find",            ["cmd"], "f",   ["ctrl"], "f"),
        4: _same("stop",         [], "escape"),
    },
)

CLAUDE = PageDef(
    name="claude",
    description="Claude — AI assistant shortcuts",
    match_names=["claude"],
    match_window_title=True,
    brand_color=(205, 135, 100),  # Claude warm orange
    button_actions={
        1: _a("submit",          ["cmd"], "enter", ["ctrl"], "enter"),
        2: _a("back",            ["cmd"], "[",   ["alt"], "left"),
        3: _a("find",            ["cmd"], "f",   ["ctrl"], "f"),
        4: _same("stop",         [], "escape"),
    },
)


# ---------------------------------------------------------------------------
# Master registry — order determines hook-chain priority (first = lowest)
# ---------------------------------------------------------------------------

ALL_PAGES: list[PageDef] = [
    # Generic browser — lowest priority; specific web apps below override when matched
    CHROME,
    # Web apps (window-title matching) — higher priority than generic Chrome
    SHAREPOINT,
    SERVICENOW,
    CHATGPT,
    CLAUDE,
    GITHUB,
    CONFLUENCE,
    JIRA,
    LINEAR,
    # Native desktop apps — highest priority among focus bridges
    WORD,
    EXCEL,
    NOTION,
    FIGMA,
    CURSOR,
    VSCODE,
]
