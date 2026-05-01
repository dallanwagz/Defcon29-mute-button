---
name: regen-docs
description: Regenerate all branch documentation (user/, developer/, hacker/) from the spine source-of-truth files and current code. Run this after editing docs/spine/ or after changing dc29/ Python code or firmware source files.
---

You are regenerating the branch documentation for the DC29 badge project. Follow these steps precisely.

## What This Skill Does

The documentation system has two layers:
- **`docs/spine/`** — SOURCE OF TRUTH, written by humans, NEVER regenerated or overwritten
- **`docs/user/`**, **`docs/developer/`**, **`docs/hacker/`** — GENERATED branches, derived from spine + code

Your job is to regenerate the branch docs to be consistent with the current spine and code. You must NEVER modify anything in `docs/spine/`.

## Step 1: Read the Current State

Read all of the following files to understand the current ground truth:

**Spine documents (source of truth):**
- `docs/spine/00-overview.md`
- `docs/spine/01-protocol.md`
- `docs/spine/02-architecture.md`
- `docs/spine/03-firmware.md`
- `docs/spine/04-hardware.md`
- `docs/spine/05-getting-started.md`
- `docs/spine/06-extending.md`

**Python source (current API surface):**
- `dc29/protocol.py` — protocol constants, enums, helper functions
- `dc29/tui/__init__.py` — TUI exports (if exists)
- Any `dc29/*.py` files present

**Firmware source (ground truth for C behavior):**
- `Firmware/Source/DC29/src/serialconsole.c` — protocol implementation
- `Firmware/Source/DC29/src/main.h` — constants, EEPROM offsets, pin defines
- `Firmware/Source/DC29/src/main.c` — superloop, effects, chord logic (if changed)

**Package config:**
- `pyproject.toml` — package name, version, dependencies, CLI entry points

## Step 2: Identify What Changed

Before regenerating, compare the spine/code against the existing branch docs to identify:
- New protocol commands or events added since last regen
- Changed EEPROM offsets or new fields
- New CLI commands or API methods
- New effect modes
- Changed timing constants
- New hardware details

Note these changes — you'll report them at the end.

## Step 3: Regenerate Branch Files

Regenerate ALL of these files. Do not skip any, even if they seem unchanged — regeneration ensures consistency.

### docs/user/ (target: non-technical user who just got the badge)

- `docs/user/README.md` — landing page, quick summary, links to pages, badges
- `docs/user/setup.md` — install, connect, run Teams bridge, macOS and Windows
- `docs/user/tui-guide.md` — TUI walkthrough with ASCII art layout
- `docs/user/customizing.md` — keymaps and LED colors, modifier/keycode tables
- `docs/user/faq.md` — common issues, troubleshooting

Style for user/ docs:
- No protocol byte values in running text (use human descriptions)
- Step-by-step numbered instructions
- Concrete example commands with actual port paths
- Call out macOS vs Windows differences
- No firmware or Python internals

### docs/developer/ (target: Python developer extending the tooling)

- `docs/developer/README.md` — overview, architecture summary, quick start
- `docs/developer/api-reference.md` — BadgeWriter class, all methods, protocol constants, LedAnimator
- `docs/developer/building-bridges.md` — templates for new bridges with runnable examples
- `docs/developer/cli-extensions.md` — how to add Typer commands
- `docs/developer/examples.md` — 5+ runnable code examples

Style for developer/ docs:
- Full method signatures with type annotations
- All protocol constants with hex values
- Code examples that actually run (use correct imports)
- Thread model and asyncio integration explained
- Note when something is RAM-only vs EEPROM-persisted

### docs/hacker/ (target: firmware hacker)

- `docs/hacker/README.md` — welcome, what you can hack, firmware overview
- `docs/hacker/protocol.md` — byte-level protocol table (compact reference)
- `docs/hacker/firmware-build.md` — complete build instructions, critical settings, troubleshooting
- `docs/hacker/flashing.md` — DFU mode procedure, timing pitfall, recovery
- `docs/hacker/adding-effects.md` — step-by-step: add a new effect in C with full code
- `docs/hacker/hardware-ref.md` — pin table, EEPROM layout table, flash map, timing constants

Style for hacker/ docs:
- C code examples with correct syntax
- Hex values for everything
- Direct references to source file names and line regions
- Explicit warnings about the three critical build settings
- NEVER touch LED 4 — repeat this constraint clearly

## Step 4: Consistency Checks

After regenerating, verify these things are consistent across all branch files:
- Protocol command bytes match `dc29/protocol.py` CMD_* and EVT_* values
- EEPROM offsets match `main.h` EEP_* constants
- Pin assignments match `main.h` BUTTON*/LED*PIN defines
- Effect mode count matches `NUM_EFFECT_MODES`
- Modifier constants match `dc29/protocol.py` MOD_* values
- Firmware version matches `FIRMWARE_VERSION` in `main.h`
- Package name and version match `pyproject.toml`
- macOS vs Windows shortcut advice is correct (Cmd+Shift+M vs Ctrl+Shift+M)

## Step 5: Report Changes

After regenerating, output a summary:

```
## Regen Complete

### Files regenerated:
- docs/user/README.md
- docs/user/setup.md
... (list all)

### Changes from previous version:
- [what changed and why]

### Spine files (not touched):
- docs/spine/00-overview.md
- docs/spine/01-protocol.md
... (confirm these were not modified)

### Consistency issues found (if any):
- [any discrepancies between spine and code]
```

## Important Constraints

- NEVER modify anything in `docs/spine/`
- NEVER skip regenerating a file even if you think it hasn't changed
- DO preserve the note at the top of each branch file that says it is generated by this skill
- DO use relative links between pages (e.g., `[setup](setup.md)` not absolute paths)
- DO include breadcrumb headers (`← Back to [Section] README`)
- DO add the generated-note header: `> **Note:** This directory is regenerated from docs/spine/ by the /regen-docs Claude Code skill. Do not hand-edit files here.`
- DO NOT add the generated-note to spine files
