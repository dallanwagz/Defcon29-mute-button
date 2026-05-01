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

**Implementation:** `takeover_start(src_0)` / `takeover_tick()` in `pwm.c` (non-blocking; called each main-loop iteration). Key design:
- Pressed LED: boosted +55 brightness splash
- Adjacent LEDs (circular 1-2-3-4-1): **additive blend** — creates color surprises (red button + blue neighbor = blue-violet)
- Opposite LED: 25% echo of pressed color
- 40ms hold → midpoint crossfade → full restore (~200ms total)
- All in firmware, no Python latency
- LED colors are set via `led_set_resting_color()` — a shadow value that survives the animation and is restored when the takeover finishes

The "unexpected color interactions" are intentional — additive blending creates emergent colors that are satisfying and slightly unpredictable, which was the explicit design goal.

**Python bridge interaction:** When a FocusBridge or TeamsBridge takes ownership of LEDs, it calls `badge.set_button_flash(False)` to disable the firmware takeover animation. This prevents the firmware from overwriting bridge-managed colors on button press. Flash is re-enabled when the bridge loses focus or the meeting ends.

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
├── keys.c              — send_keys(): EEPROM keymap replay + takeover_start hook
├── pwm.c               — LED PWM + takeover_start/tick animation + led_set_resting_color
├── serialconsole.c     — USB CDC menu + status indicator side-channel
└── comms.c / games.c  — Badge-to-badge UART, Simon Says, Whack-a-Mole
```

### Key flow: button press in `dc29 flow` mode

1. User presses B3
2. Badge firmware fires takeover animation (circular additive color blend, ~200ms, all in C)
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

---

## Bugs fixed (session 2 — 2026-04-30)

### 1. Teams WebSocket timing out during opening handshake

**Symptom:** `dc29 flow -v` showed `timed out during opening handshake` exactly at 10s.

**Root cause:** All 15+ `FocusBridge` instances called `subprocess.run(["osascript", ...])` synchronously at startup, blocking the asyncio event loop for several seconds — right during the Teams WebSocket handshake.

**Fix 1:** Changed `_check_focus()` call in `FocusBridge.run()` to use `run_in_executor` so it runs in a thread pool without blocking the loop.

**Fix 2:** Added a module-level TTL cache in `dc29/bridges/focus.py` (`_get_active_app()`) with a `threading.Lock`. 15+ concurrent thread-pool calls all submitted `osascript` simultaneously to macOS System Events → all timed out at 1.5s. The cache serializes them: one real call per 350ms window, all others return immediately from cache.

**Fix 3:** Added `open_timeout=30` to `websockets.connect()` in `teams.py`.

---

### 2. Teams pairing — no authorization dialog appeared

**Symptom:** Bridge connected, `canPair: false`, no dialog in Teams.

**Root causes:**
- `canPair` is only `true` during an active Teams meeting. Connecting outside a call returns all-false permissions.
- The bridge must send `{"action": "pair"}` explicitly after connecting without a token — just connecting is not enough.
- If the device appears in Teams → Settings → Privacy → Third-party app API (Allowed OR Blocked list), Teams silently suppresses the dialog. Must remove it entirely.
- Elgato Stream Deck holds port 8124 exclusively — only one client at a time. Must `killall "Stream Deck"` before dc29.

**Working pairing procedure:**
1. `killall "Stream Deck"`
2. `rm ~/.dc29_teams_token`
3. Teams → Settings → Privacy → Third-party app API: block DC29, then remove it entirely
4. Join a Teams meeting
5. `dc29 flow -v` → accept the "New connection request" dialog in Teams
6. Token saved to `~/.dc29_teams_token` — subsequent runs connect automatically

---

### 3. Teams bridge clobbering Outlook/Slack LEDs every 5 seconds

**Symptom:** Outlook page loaded correctly; as soon as the first `Teams WebSocket disconnected: [Errno 61]` warning appeared (~5s after launch), LED 4 turned off.

**Root cause:** `TeamsBridge._set_meeting_state(NOT_IN_MEETING)` was called unconditionally after every failed reconnect, which called `_clear_page_leds()` and `badge.set_mute_state(NOT_IN_MEETING)` (sends `0x01 X` → firmware turns LED 4 off). Teams not being open is a normal condition; wiping other bridges' LEDs was wrong.

**Fix:** Two guards added in `teams.py`:
- `if was_in_meeting:` before `_clear_page_leds()` and `set_current_page(None)`
- `if was_in_meeting or now_in_meeting:` before `badge.set_mute_state()`

Only touch LEDs when actually transitioning into or out of a meeting.

---

### 4. Outlook bridge LED and delete UX

**Changes:**
- Delete (B1) LED changed from warm red `(220, 35, 0)` → pure red `(220, 0, 0)`.
- After delete keypress, plays an ascending two-tone Tink jingle via `afplay` (macOS only): rate 0.85 then rate 1.4, 70ms apart. Runs as a background asyncio task so it doesn't block the button handler.
- Implementation in `dc29/bridges/outlook.py`: `_play_delete_sound()` async method + `asyncio.create_task()` in `handle_button`.

---

## Current working state (as of 2026-05-01)

### What works end-to-end

```bash
dc29 start        # TUI + all bridges: Teams, Slack, Outlook, 15 app pages
dc29 flow -v      # Headless, all bridges, verbose logs
dc29 diagnose     # Show EEPROM keymaps + active app
dc29 clear-keys   # Zero EEPROM macros (run once to eliminate double-injection)
```

- Teams mute indicator: LED 4 red/green/off tracks live meeting state
- Focus bridges: Outlook, Slack, VS Code, Cursor, Figma, Notion, Jira, GitHub, Chrome, + 6 more
- Outlook delete: pure red + ascending Tink jingle feedback
- Button press animation: firmware takeover ripple (additive color blend, ~200ms)
- TUI: live companion showing active page name, button colors, action labels

### Known limitations / not yet tested

- `dc29 autostart install` runs `dc29 teams` only (headless Teams bridge). Does **not** run Slack/Outlook/generic pages and does **not** include the TUI. The TUI requires a terminal.
  - **Recommended:** Add `dc29 start` to login items manually (System Settings → General → Login Items) pointing at a shell script that opens a new iTerm2 tab.
  - Or edit the generated launchd plist at `~/Library/LaunchAgents/com.dc29badge.teams.plist` to change `teams` → `flow`.
- Slack huddle mute detection not yet validated end-to-end.
- Windows platform untested with the new bridge stack.

### Install from scratch (new machine)

```bash
git clone https://github.com/dallanwagz/Defcon29-mute-button.git
cd Defcon29-mute-button
pip install -e ".[tui,hotkey]"

# First time: clear any firmware EEPROM macros
dc29 clear-keys

# Run everything
dc29 start

# First Teams pairing (must be IN a meeting):
#   - killall "Stream Deck"
#   - rm ~/.dc29_teams_token
#   - Remove DC29 from Teams → Settings → Privacy → Third-party app API
#   - Join a meeting, run dc29 flow -v, click Allow in Teams
```

### macOS permissions required

- **Accessibility** (System Settings → Privacy & Security → Accessibility → enable your terminal app) — required for pynput shortcut injection and focus detection
- Teams Local API must be enabled: Teams → Settings → Privacy → Third-party app API → Enable third-party API
