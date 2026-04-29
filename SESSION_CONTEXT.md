# DC29 Badge — Session Context & Vision

This document captures the exact user statements and design decisions from the development sessions that shaped the current system. It exists so future contributors (human or AI) can understand the spirit and intent behind every architectural choice — not just what was built, but *why* and *for whom*.

---

## Vision statements (verbatim)

> **"we want this to be a tool built by the people, for the people... something that's a really awesome and inviting user experience that is an actual productivity boost. not just a desk gimmick"**

> **"oh baby let's roll forward with everything now!"**

> **"the tui should be seen as the 'user guide', where the intended usecase is to create a tab in iterm that always has the tui open for explanations of what page you are on and what each action is doing. this should sync between the tui, the badge and the apis. its the, RTFM, but a user friendly one that people actually want"**

> **"this TUI should be the 'streamdeck companion app' FOSS version cyberpunk. it should be the companion app to the 4 button streamdeck"**

---

## Design decisions and rationale

### Color semantics — Option A (positional, strict)

**User prompt:**
> "let's go Option A — Enforce strict positional semantics (safety first) → button 1 always has a warm/red tint even if the action isn't dangerous — the muscle memory value is worth the imperfect semantic fit"

**What this means:** Every page, every app, every context — the four button positions always carry the same color family. You build muscle memory across all 15+ apps, not per-app. Slightly imperfect semantic fits are acceptable; breaking the positional rule is not.

| Button | Color family | Semantic |
|--------|-------------|----------|
| B1 | Warm red | Destructive / exit / undo / close |
| B2 | Cool blue | Status / visibility / toggle / communicate |
| B3 | Amber | Navigate / find / search / jump |
| B4 | Green | Create / save / confirm / generate |

Exception: Teams B4 mute indicator is safety-critical — red=muted, green=live overrides positional green. This is intentional and the only sanctioned exception.

---

### Multi-app bridge system (15 apps, `dc29 flow`)

**User prompt:**
> "oh baby let's roll forward with everything now!"

The full Phase 1–4 plan was executed in one shot:
- Window title matching for web apps (Jira, GitHub, ChatGPT, Claude, etc.)
- `GenericFocusBridge` + `PageDef` data-driven pattern — no Python subclass needed for new apps
- 15-app registry in `dc29/bridges/registry.py`
- `dc29 flow` command loads all bridges concurrently via `asyncio.TaskGroup`
- Hook chain priority: Chrome (lowest) → web apps → native desktop apps → Teams (highest)

**Chrome generic page prompt:**
> "maybe a generic chrome page if we arent on jira on something more specific. with a button for refresh, duplicate, and maybe the split operation as well"

Chrome is the fallback browser page (lowest priority), overridden when a specific web app's window title matches.

---

### Firmware button press animation (ripple effect)

**User prompt:**
> "each button press should satisfyingly shoot out its color and cause some sort of fun and unexpected interaction of the color of the leds around it - sometimes mixing rgb values, sometimes getting overridden by the color from the pressing (sending) button... again, we want this to be satisfying to use. pressing a button and getting visual feedback is satisfying to a human. remember we should be doing as much processing in firmware as possible, especially these animations if those could be handled with much quicker resolution for more immersive interactions at the firmware level vs at the python level which isn't as quick"

**Implementation:** `led_ripple_start()` / `led_ripple_finish()` in `pwm.c`. Key design:
- Pressed LED: boosted +55 brightness splash
- Adjacent LEDs (circular 1-2-3-4-1): **additive blend** — creates color surprises (red button + blue neighbor = blue-violet)
- Opposite LED: 25% echo of pressed color
- 40ms hold → midpoint crossfade → full restore (~200ms total
- All in firmware, no Python latency

The "unexpected color interactions" are intentional — additive blending creates emergent colors that are satisfying and slightly unpredictable, which was the explicit design goal.

---

### TUI as StreamDeck companion app

**User prompts:**
> "the tui should be seen as the 'user guide', where the intended usecase is to create a tab in iterm that always has the tui open for explanations of what page you are on and what each action is doing. this should sync between the tui, the badge and the apis. its the, RTFM, but a user friendly one that people actually want"

> "this TUI should be the 'streamdeck companion app' FOSS version cyberpunk. it should be the companion app to the 4 button streamdeck"

**What this means:**
- The TUI Dashboard is not a config tool — it's a live reference you keep open permanently in a split pane / iTerm tab
- The "ACTIVE PROFILE" pane is the direct analogue of StreamDeck's profile display
- Switching apps in the OS updates the pane in real time: app name (in brand color), 4 button cards glowing with their LED colors, action labels
- The "cyberpunk" aesthetic: dark terminal, colored glows, positional color system
- It's open-source, no proprietary hardware, no subscription — built by hackers for hackers

---

## Architecture overview (current state)

```
dc29/
├── badge.py            — Thread-safe serial API to the badge hardware
├── protocol.py         — Wire protocol constants and types
├── cli.py              — `dc29` CLI: flow, tui, autostart, config
├── config.py           — TOML config (~/.config/dc29/config.toml)
├── bridges/
│   ├── base.py         — BaseBridge, BridgePage, PageButton
│   ├── colors.py       — Positional color system + brand colors
│   ├── focus.py        — FocusBridge: window-focus polling, context flash
│   ├── generic.py      — PageDef / ActionDef / GenericFocusBridge
│   ├── registry.py     — 15-app registry + ALL_PAGES priority list
│   ├── teams.py        — Teams Local API WebSocket bridge
│   ├── slack.py        — Slack focus bridge
│   └── outlook.py      — Outlook focus bridge
├── tui/
│   └── app.py          — Textual TUI: Dashboard (StreamDeck view), Keys, LEDs, Effects, Log
└── docs/               — Spine/branch documentation system

Firmware/Source/DC29/src/
├── main.c              — Superloop: buttons, slider, USB CDC, sleep
├── keys.c              — send_keys(): EEPROM keymap replay + ripple hook
├── pwm.c               — LED PWM + led_ripple_start/finish animation
├── serialconsole.c     — USB CDC menu + status indicator side-channel
└── comms.c / games.c  — Badge-to-badge UART, Simon Says, Whack-a-Mole
```

### Key flow: button press in `dc29 flow` mode

1. User presses B3
2. Badge firmware fires ripple animation (circular additive color blend, ~200ms, all in C)
3. Badge sends `0x01 'B' 3 <mod> <kc>` over USB CDC
4. `badge.py` reader thread parses → calls `on_button_press(3, mod, kc)`
5. The installed hook chain checks: is this button owned + `_should_handle_button()` true?
6. If yes → `loop.call_soon_threadsafe(handle_button(3))` → bridge fires pynput shortcut
7. If no → EEPROM keymap HID keystroke fires normally
8. `on_page_change` → `PageChangeMessage` → TUI `ContextPane` updates

### Hook chain priority (outermost to innermost)

```
Teams (only active when in_meeting=True)
  ↓ else falls through to:
FocusBridges (active when focused AND not in meeting):
  VSCODE → CURSOR → FIGMA → NOTION → WORD → EXCEL
  → LINEAR → JIRA → CONFLUENCE → GITHUB → CLAUDE
  → CHATGPT → SERVICENOW → SHAREPOINT → CHROME
  ↓ else falls through to:
Badge EEPROM keymap (default HID keystroke)
```

---

## The `/dc29-add-app` skill

A wizard skill at `~/.claude/skills/dc29-add-app/SKILL.md`. Run `/dc29-add-app <AppName>` to:
1. Classify the app (native vs web)
2. Propose 4 actions following positional semantics
3. Choose brand color, match strings
4. Preview the `PageDef` registry entry
5. Get user approval before writing to `registry.py`

Enforces the positional semantics checklist and drift-prevention rules so every new app stays consistent with the system.

---

## What "not a desk gimmick" means in practice

- **Positional muscle memory** — 15 apps, same 4 button positions, same color families. After a week you stop reading the TUI and just press buttons.
- **Context-aware switching** — no mode buttons, no profile selection. The system figures out what you're doing and adapts.
- **Satisfying physics** — the ripple animation exists because pressing a physical button and getting visual feedback is intrinsically satisfying to humans. This is not decorative.
- **Open loop** — the TUI is always there. You don't go looking for it. It tells you what the badge is doing without asking.
- **Firmware-first** — animation, debounce, HID all happen in the MCU. Python handles semantics and APIs. Nothing slow in the hot path.
