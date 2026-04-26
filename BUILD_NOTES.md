# Build Notes — Active Session

This file exists to hand off context between Claude Code sessions.
**New session: read this first, then check `CLAUDE.md` for full architecture context.**

---

## What We're Doing

Building the Issue #5 modifier key fix for the DEF CON 29 badge firmware to test
it before the upstream PR is merged.

## Repo / Branch

```
Repo:   https://github.com/dallanwagz/Defcon29-mute-button
Branch: fix/issue-5-modifier-keys
Commit: c7c1e78
```

This branch contains exactly ONE change: the modifier key parser fix in
`Firmware/Source/DC29/src/serialconsole.c`. No other files touched.

## What the Fix Does

Modifier tokens like `[ctrl]p` in the badge's keymap macro editor were broken.
They produced wrong modifier keys because the parser stored modifier tokens as
standalone bytes, misaligning the 2-byte `{modifier, keycode}` pairs that
`send_keys()` reads with a fixed stride. The fix introduces a `pending_modifier`
accumulator that collects modifier tokens and applies them atomically to the next
keystroke. Full analysis in `docs/BUG_ANALYSIS_ISSUE5.md`.

## Build Environment

- **IDE**: Microchip Studio 7.0 (Windows)
- **Architecture pack installed**: SAM (ATSAMD21G16B is ARM Cortex-M0+)
- **Solution file**: `Firmware/Source/Defcon29.atsln`
- **Build config**: Release (not Debug — debug no longer fits in 56KB flash)
- **Expected output**: `Firmware/Source/DC29/Release/DC29.hex`

## Build Steps

1. Open `Firmware/Source/Defcon29.atsln` in Microchip Studio 7
2. Switch configuration dropdown from Debug → **Release**
3. Build → Build Solution (F7)
4. If it succeeds: convert + flash (see below)
5. If it fails: note the exact error output and start troubleshooting

## Flash Steps (after successful build)

Convert `.hex` to `.uf2`:
```bash
python3 uf2conv.py --family 0x68ed2b88 --convert \
  --output dc29_issue5fix.uf2 \
  Firmware/Source/DC29/Release/DC29.hex
```
(`uf2conv.py` is in `utils/` in this repo, or get it from microsoft/uf2)

Flash:
1. Hold **bottom-right button** while plugging USB
2. Badge mounts as mass storage drive
3. Drag `dc29_issue5fix.uf2` onto it

## Verify the Fix

1. Open serial terminal to badge (any baud — CDC serial auto-negotiates)
2. Press Enter → main menu appears
3. Press `2` → choose a key → type `[ctrl]p` → Enter
4. Press that button → should send Ctrl+P to the host
5. Also test `[ctrl][shift]p` (previously both modifiers were silently dropped)

**Before fix:** `[ctrl]p` sent LEFT_CTRL + LEFT_SHIFT + RIGHT_CTRL (wrong)
**After fix:** `[ctrl]p` sends Ctrl+P (correct)

## Known Flash Budget Constraint

`#define DEBUG 0` is intentional — debug build no longer fits in 56KB. Do not
change this. Release build is the only valid build.

## PR Status

Open at: https://github.com/compukidmike/Defcon29/pull/7
From: `dallanwagz/Defcon29-mute-button:fix/issue-5-modifier-keys`
Against: `compukidmike/Defcon29:main`

## Local Mac Repo State (for reference)

The Mac has the full working tree at `/Users/dallan/repo/Defcon29` tracking
`compukidmike/Defcon29` (upstream) as `origin`. All bug fixes (5 confirmed bugs
+ Issue #5) are uncommitted on `main`. The `fix/issue-5-modifier-keys` branch
is pushed to `dallanwagz/Defcon29-mute-button` with only the Issue #5 fix.
