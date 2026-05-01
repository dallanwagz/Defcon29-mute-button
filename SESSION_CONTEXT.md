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
> "let's go Option A — Enforce strict positional semantics (safety first) → muscle memory value is worth the imperfect semantic fit"

**Layout updated 2026-05-01:** Red moved from top-left (B1) to bottom-right
(B4) — "i want the red button to always be in the bottom right." This put the
mute indicators (Teams B4 toggle-mute, Slack B4 huddle-mute) on the
positional red slot, eliminating the previous "B4 is the only sanctioned
exception" carveout.

**What this means:** Every page, every app, every context — the four button positions always carry the same color family. You build muscle memory across all 15+ apps, not per-app. Slightly imperfect semantic fits are acceptable; breaking the positional rule is not.

| Button | Position      | Color family | Semantic |
|--------|---------------|--------------|----------|
| B1     | Top-left      | Green        | Create / save / confirm / generate |
| B2     | Top-right     | Cool blue    | Status / visibility / toggle / communicate |
| B3     | Bottom-left   | Amber        | Navigate / find / search / jump |
| B4     | Bottom-right  | Warm red     | Destructive / exit / undo / close |

Teams toggle-mute and Slack huddle-mute live on B4 by design — the dynamic
mute-state LED (red=muted, green=live) is now naturally aligned with the red
slot rather than overriding it. Leave-call on Teams B1 keeps a red LED
override (destructive action in the only Teams slot remaining) — minor
positional violation, retained for ergonomics.

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
- Delete (originally B1, moved to B4 in the 2026-05-01 swap) LED changed from warm red `(220, 35, 0)` → pure red `(220, 0, 0)`.
- After delete keypress, plays an ascending two-tone Tink jingle via `afplay` (macOS only): rate 0.85 then rate 1.4, 70ms apart. Runs as a background asyncio task so it doesn't block the button handler.
- Implementation in `dc29/bridges/outlook.py`: `_play_delete_sound()` async method + `asyncio.create_task()` in `handle_button`.

---

## Session 3 (2026-05-01) — feature explosion

### Positional swap: red moves to bottom-right

User: *"i want the red button to always be in the bottom right"*

`POSITION_ACTIVE`/`POSITION_DIM` swapped 1↔4 in `colors.py`; all 15 PageDefs in
`registry.py` had `button_actions[1]` swapped with `button_actions[4]`; Outlook
delete moved from B1 → B4 with its breathe-pulse animation rewritten to sweep
LEDs 1–3 instead of 2–4.  Teams's mute indicator on B4 went from "the only
sanctioned exception" to *naturally aligned* with the new positional rule.

| Button | Position | Color | Semantic |
|---|---|---|---|
| B1 | Top-left | Green | Create / save / confirm |
| B2 | Top-right | Cool blue | Status / visibility |
| B3 | Bottom-left | Amber | Navigate / find |
| B4 | Bottom-right | Warm red | Destructive / delete |

### LED4 freed from "reserved for mute"

Old design hard-reserved LED4 — `update_effects()` skipped it.  Refactored so
all firmware effects animate all four LEDs.  Bridges that need exclusive
control of LED4 (Teams toggle-mute, Slack huddle-mute) now suspend the
effect via `set_effect_mode(0)` on engagement and restore on release.
Removed "LED 4 reserved" language from CLAUDE.md, all spine docs, all branch
docs, code comments.

### Bridge architecture: manifest + manager + hot-reload

The whole bridge layer was refactored from "hardcoded list in `_run_flow`" to
a registry-driven system supporting live add/remove of bridges from the TUI.

* **`dc29/bridges/manifest.py`** — single source of truth for available
  bridges.  18 → now 20 entries (15 generic + Slack/Outlook/Teams + audio-reactive + beat-strobe).
* **`dc29/bridges/manager.py`** — `BridgeManager.reconcile()` diffs running
  set vs `cfg.enabled_bridges` and starts/stops asyncio tasks accordingly.
  Cleanly cancels stopped bridges so their `finally` blocks (LED clear,
  hook removal) actually run before the serial port closes.
* **`BadgeAPI` priority handler registry** — replaced the linked-list
  button-hook chain (couldn't safely add/remove middle nodes) with a
  priority-ordered list of `_ButtonHandler` records.  Reader thread
  snapshots under a lock and dispatches in priority order; first claim
  wins, falls through to `on_button_press` callback otherwise.
* **Default: every bridge is OFF.**  User opts in via CLI `--enable <name>`
  (repeatable) or `--enable-all`, config `[bridges] enabled = [...]`, or
  the TUI Bridges & Inputs tab (live toggle = live reconcile).

### Sticky focus LEDs

User: *"its annoying having the lights go off when an app isnt in focus for me"*

New `Config.sticky_focus_leds` (default off).  When on, `FocusBridge` skips
`_clear_page_leds()` on focus loss — last app's colors persist until
another bridged app gains focus.  Toggleable via `--sticky-leds` CLI,
config, or TUI checkbox.

### Slider + splash control surfaces

Two new RAM-only firmware toggles, both default-on:

* **`0x01 'S' 0/1`** — disable/enable capacitive touch slider's HID
  volume-up/down injection.  Slider keeps scanning so the position cache
  stays consistent; only the keystroke is gated.
* **`0x01 'I' 0/1`** — disable/enable interactive splash-on-press.

`badge.set_slider_enabled()` and `badge.set_splash_on_press()` mirror these.

### Splash-on-press fidget animation (firmware)

User: *"if button is pressed that color freezes slightly and sprays out across the
other LEDs in a 300ms espque animation… imagine this is a mobile mini DJ
wannabe lighthow for himself and himself only lol"*

`splash_start(src_0)` + `splash_tick()` in `pwm.c` — captures the pressed
LED's *currently displayed* color from `ledvalues[]` (so it picks up the
running effect's hue), freezes for 60 ms, sprays at 100% to source / 90% to
adjacents / 50% to opposite, then settles back to resting via cross-fade.
Works on battery without USB.  Wired into `main.c` button-press path so
button presses during effect modes fire the splash, regardless of USB.

### Atomic paint-all firmware command

User asked how fast we could push frames.  Measured: ~600 fps before host
write-buffer saturates the firmware CDC reader.

`0x01 'P' r1 g1 b1 r2 g2 b2 r3 g3 b3 r4 g4 b4` — 13 bytes paints all four
LEDs in one main-loop iteration.  Halves bandwidth vs four `L` commands and
prevents inter-LED tearing during animation streams.  `escape_args` buffer
bumped from 4 → 12 to fit the payload.  Python wrapper:
`BadgeAPI.set_all_leds(c1, c2, c3, c4)`.

### 5 new firmware effect modes + particles

Bumped `NUM_EFFECT_MODES` from 3 → 9.  All operate on the 4-LED grid; all
respect the Teams/FocusBridge handoff via `set_effect_mode(0)`.

| Mode | Name | Description |
|---|---|---|
| 3 | Wipe | A single hue rolls across LEDs 1→4, wipes off, new hue |
| 4 | Twinkle | xorshift8 sparkles — one LED at a time at random brightness |
| 5 | Gradient | Smooth scrolling 4-LED hue gradient |
| 6 | Theater | Marquee alternating odd/even LEDs |
| 7 | Cylon | Knight-Rider sweep with dim trail |
| **8** | **Particles** | **2D physics: two color blobs drift through the 2×2 grid, bounce off walls, hue shifts on bounce** |

The 2x2 grid layout drove the particles design:

```
LED1 ─ LED2     (top row)
LED3 ─ LED4     (bottom row)
```

Particles are int16 (x,y) in [0,255] with int16 (vx,vy) per-tick velocities.
Each LED-corner accumulates contributions from each particle weighted by
manhattan distance with falloff radius 200/510.  No floats, no fixed-point
math — small enough the math fits in int16.

### Scene library (`dc29/scenes.py`)

User: *"if we build out the architecture for it we can then have an agent iterate
on creating essentially light shows lol"*

Authorable TOML scene format with three payload kinds:

* **Static** — 4 LED colors, applied once and held.
* **Animation** — keyframe list with `t`/`leds` entries, linear or step
  interpolation, optional loop, fps capped at 60.
* **Firmware** — pointer at one of the 9 effect modes.

Stored at `~/.config/dc29/scenes/<slug>.toml`.  Hand-rolled TOML emitter
keeps the format predictable for agents.  CLI: `dc29 scene save/play/list/delete`.

### Stats module (`dc29/stats.py`)

User: *"funny stats like emails deleted, unique teams meetings joined, mute mic
button presses… stats for a nerd that they dont need but secretly want"*

Singleton thread-safe counter / unique-set store, atomic TOML save every 30s
+ on shutdown.  Privacy-preserving (local only, never sent anywhere) at
`~/.config/dc29/stats.toml`.  Wired into Outlook delete, Teams meeting
join + mute toggle, button presses (in `BadgeAPI._dispatch_rx`), focus
changes, bridge starts, Spotify track plays.  CLI: `dc29 stats / reset / export`.
TUI: dedicated Stats tab (#6) with auto-refresh.

### Audio reactive (BlackHole + FFT)

Spotify's `/audio-analysis` endpoint we'd planned to use returned 403 — they
deprecated it for new dev apps on 2024-11-27.  Pivoted to live FFT via
[BlackHole](https://github.com/ExistentialAudio/BlackHole) virtual audio
loopback driver.

* **`dc29/audio.py`** — `AudioCapture` runs PortAudio callback, rolls 2048-
  sample buffer, computes windowed real-FFT every 23 ms.  Output:
  `AudioFeatures(rms, bass, mid, treble, beat, chroma[12])` at ~43 fps.
  Beat detector: rolling-window energy threshold on the bass band (1.5σ +
  absolute floor, 250 ms minimum interval = 240 BPM ceiling).
* **`dc29/bridges/audio_reactive.py`** — main reactive bridge.  60 fps
  render loop emits one `set_all_leds` per frame.  Maps `chroma` low/high
  halves → LED2/3, `bass` → LED1, `treble` → LED4.  `loudness` → brightness
  scalar.  Auto-engages on RMS > 0.02; releases after 1.5s of silence.
* **`dc29/bridges/beat_strobe.py`** — DJ-rig sibling.  On each beat, fires a
  50 ms strobe burst at 200 Hz alternating saturated palette → white → off.
  Idle baseline: dim purple-ish.
* **Spotify metadata as palette context** — kept the `SpotifyClient`
  for `/me/player/currently-playing` only (still 200s).  Audio-reactive
  bridge polls every 10s and shifts its palette per artist (stable hash
  → consistent hue family).  Live FFT drives reactivity, Spotify drives mood.

### Paint mode TUI ("Effects & Paint")

Rebuilt EffectsTab as a full WYSIWYG surface:

* 4 clickable LED swatches showing live colors with selected-LED border.
* RGB integer inputs + hex input (synced via `Input.Changed` with
  `prevent(...)` to avoid feedback loops).
* "Apply to all LEDs" + "All off" buttons using `set_all_leds`.
* All 9 effect modes as RadioSet entries with descriptions from
  `EFFECT_DESCRIPTIONS`.
* Saved-scenes dropdown with Play/Stop/Refresh.
* Brightness scalar input.
* Toggles for splash on press, button flash, sticky focus LEDs.
* **Auto-grab paint mode** — touching any input silently disables every
  bridge + suspends effect, snapshotting prior state.  Yellow banner shows
  "Paint mode active".  Restored from log button or by re-enabling bridges.
* **Teams safety carve-out** — if `mute_state != NOT_IN_MEETING`, paint
  mode shows a red "🔒 Paint mode locked" banner and refuses LED writes.
  The mute LED on B4 always wins during a meeting.

### TUI tab structure (final)

| Key | Tab |
|---|---|
| 1 | Dashboard |
| 2 | Keys |
| 3 | LEDs (legacy slider view) |
| 4 | Effects & Paint |
| 5 | Bridges & Inputs (auto-rendered from manifest) |
| 6 | Stats |
| 7 | Log |

### Demo bridges (the "flex" pieces)

User: *"flex our muscles, show off our ability to optimize both the software
and the hardware"*

Two demos shipped:

* **Particles** (firmware mode 8) — runs without host, on battery.
* **beat-strobe** (Python bridge) — 200 Hz strobe stabs synced to live
  audio beats.  Hot-toggleable.  Auto-engages on first beat, releases on
  silence.

### Build + flash tooling

* **`BUILD_MACOS.md`** — full Makefile-based macOS build path replacing
  Microchip Studio.  Uses extracted Homebrew toolchain at
  `~/opt/arm-gnu-toolchain/`.  The Makefile (`Firmware/Source/DC29/Makefile`)
  needs `__SAMD21G16B__` define, `samd21g16b_flash.ld` linker script,
  `-fcommon` (GCC 10+ default change), `-flto` (so we fit in 56 KB on GCC 15).
* **`/flash-badge` slash command** at `.claude/commands/flash-badge.md` —
  build → poll `/Volumes/*/INFO_UF2.TXT` → copy → verify CDC re-enumeration.
  Documented gotchas (button-during-reboot trap, J18A vs G16B header drift).
* **`Firmware/Source/DC29/scripts/`** — `flash.sh` / `console.sh` /
  `dev.sh` for users who prefer shell over the slash command.

### Final firmware size

**41,168 / 57,344 bytes** (~28% headroom).  Built with GCC 15 + LTO via the
macOS Makefile.

---

## Current working state (as of 2026-05-01, end of session 3)

### What works end-to-end

```bash
dc29 start --enable-all              # TUI + every bridge
dc29 start --enable teams --enable audio-reactive   # selective
dc29 flow -v --enable-all            # headless, every bridge
dc29 set-effect 8                    # firmware particles
dc29 scene play sunrise              # play a saved scene
dc29 stats                           # show local nerd-fuel
dc29 audio status                    # confirm BlackHole detected
dc29 spotify auth                    # one-time OAuth flow
dc29 bridges list                    # discover what's enable-able
```

**Bridges (default off, opt-in):**
- 15 generic FocusBridge apps (Chrome, VSCode, Figma, Notion, JIRA, GitHub, Linear, …)
- Outlook (delete + Tink jingle, B4)
- Slack (huddle mute indicator on B4)
- Teams (full meeting page, mute indicator on B4)
- audio-reactive (BlackHole + FFT, sweeping color reactivity)
- beat-strobe (200 Hz strobe stabs on detected beats)

**Firmware effects (live on the badge):**
- 9 modes: off, rainbow-chase, breathe, wipe, twinkle, gradient, theater, cylon, particles
- All 4 LEDs animated; bridges suspend the active mode while they own LEDs
- Splash-on-press fidget animation works on battery without USB
- Atomic 4-LED paint command for animation streams (~600 fps measured ceiling)

**TUI tabs:** Dashboard / Keys / LEDs / Effects & Paint / Bridges & Inputs / Stats / Log

### Known limitations / not yet tested

- `dc29 autostart install` still runs `dc29 teams` only — needs an update to support `dc29 start` with `--enable-all` and a TUI-aware launcher script.
- Slack huddle mute detection not validated end-to-end.
- Windows platform untested — most of the bridge stack is platform-agnostic but pynput/AppleScript/BlackHole are Mac-specific.
- BlackHole on Windows: not investigated.  VB-Cable is the rough equivalent; would require swapping the device-detection logic in `dc29/audio.py`.
- Teams + Spotify tokens persist at `~/.dc29_teams_token` and `~/.dc29_spotify_token` (mode 0600).  No token rotation logic if the user revokes access — bridge will fail silently and re-auth is a manual `dc29 spotify auth` / Teams pairing dance.

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
