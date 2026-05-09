# F08 — Stay Awake (mouse jiggler with Amphetamine-style UX)

> Status: **planned** · Risk: **medium** · Owner: firmware + bridge + TUI

## Goal

Ship an **Amphetamine-for-Mac-style** "Stay Awake" feature: pick a duration (30 min / 1h / 4h / 8h / indefinite), badge keeps the host awake via HID-level mouse jiggles for the selected window, with a live countdown and selectable LED visualization. Stoppable any time. Works on any host OS because the jiggling is HID-level, indistinguishable from a real mouse, and immune to MDM software-jiggler kill-switches.

## Why this is more than just "mouse HID"

The original spec was a raw "jiggler firmware mode." User feedback redirected scope: the jiggler is the *plumbing*, the actual feature is **a polished session-management UX** that mirrors Amphetamine.app — pick a time, see the countdown, optionally show LED feedback, stop early.

This means F08 is split conceptually into two layers:

- **F08a — firmware**: USB Mouse HID interface + raw jiggle commands. This is the smallest possible firmware change — just enough plumbing.
- **F08b — bridge + TUI**: A new bridge that owns the session timer, a new "Stay Awake" TUI tab, a CLI surface, and LED visualization options.

Both must ship together to satisfy the success criteria below. Internally we can write/test F08a first since F08b is meaningless without it, but they sign off as one feature.

## Success criteria

### F08a — firmware (plumbing)

- [ ] Composite USB descriptor extended: HID-Keyboard (existing) + HID-Mouse (new) + CDC (existing). Endpoint count stays within SAMD21 limits (5 / 8 used).
- [ ] No regression to existing HID-Keyboard. Buttons still type.
- [ ] No regression to existing CDC console. `dc29 diagnose` still works.
- [ ] Protocol command `0x01 'j' 'M'` — fire **one** jiggle pulse (single +1/-1 X-axis pair). The bridge calls this on its own schedule.
- [ ] Protocol command `0x01 'j' 'I' <unix_le32>` — bridge tells the badge "I'm alive, stay-awake until this UTC second." Badge stores end-time in RAM. If the bridge dies and end-time hasn't passed, **badge keeps jiggling autonomously** at a default 30 s interval until end-time elapses.  *(This is the safety-net that survives bridge crashes — see "autonomous mode" below.)*
- [ ] Protocol command `0x01 'j' 'X'` — cancel autonomous mode (used on graceful shutdown).
- [ ] No EEPROM writes from F08a; all jiggler state is RAM-only.
- [ ] LED behavior: F08a does **not** touch LEDs. F08b owns visualization.

### F08b — bridge + TUI

- [ ] New bridge `dc29.bridges.stay_awake.StayAwakeBridge` registered in `manifest.py` as `stay-awake`. Off by default; gated start via TUI/CLI rather than `--enable`.
- [ ] **Session state machine**: idle → active(end_time, mode) → idle. Single active session at a time.
- [ ] **Quick-start presets**: 30 min, 1 h, 2 h, 4 h, 8 h, indefinite (no end-time).
- [ ] **Custom duration**: free-form HH:MM input via TUI text field.
- [ ] **Live countdown**: TUI shows `HH:MM:SS` remaining + projected end-time wall clock (e.g. "ends 4:23 PM"). Updates every second.
- [ ] **LED visualization options** (one selected at a time):
  - `Off` — bridge does not touch LEDs.
  - `Cyan pulse on LED 1` — slow 0.5 Hz sine on LED 1, leaves LEDs 2–4 alone.
  - `Progress bar` — 4 LEDs encode `elapsed / total` (left-to-right fill, dim cyan; suppressed during meetings on LED 4).
  - `Use existing effect mode` — sub-select 1..7 from the existing effect modes; sends `0x01 'E' n` at start, restores `0` at stop.
- [ ] **CLI surface**:
  - `dc29 awake start <duration>` — durations: `30m`, `1h`, `4h`, `8h`, `forever`, `1h30m`, etc.
  - `dc29 awake stop`
  - `dc29 awake status` — prints active/idle, time remaining, mode.
- [ ] **TUI tab**: new "Stay Awake" tab (slot 9), layout per ASCII mockup below.
- [ ] **Heartbeat**: bridge fires one `0x01 'j' 'M'` jiggle every 30 s during active session AND refreshes the firmware-side end-time every 60 s (`0x01 'j' 'I' <new_end>`). If the bridge dies, badge runs autonomously until original end-time.
- [ ] **Teams yield**: when in a Teams meeting (`mute_state != NOT_IN_MEETING`), Stay Awake LED visualization releases LEDs 1–4 entirely and lets the Teams bridge own LED 4. Jiggling continues — meetings absolutely benefit from awake-state.
- [ ] **Persistence**: last-used duration + LED mode preference persisted to `~/.dc29/stay_awake.toml` (host-side, not EEPROM).
- [ ] **Auto-stop**: when end-time passes, bridge sends `0x01 'j' 'X'`, restores prior LED state (effect mode 0 or whatever was set), notifies TUI which transitions to idle.
- [ ] **Graceful shutdown**: if the bridge process is stopped (Ctrl+C, kill), it sends `0x01 'j' 'X'` on the way out so badge stops jiggling.

## TUI mockup — "Stay Awake" tab (slot 9)

```
┌── Stay Awake ────────────────────────────────────────────────┐
│                                                              │
│   Status:  ▓▓▓▓▓▓▓▓▓▓▓▓▓░░░░░░░░░░░░░░░░░░░  62% elapsed     │
│                                                              │
│   ●  ACTIVE                                                  │
│       Time remaining:  03:42:18                              │
│       Will end at:     4:23 PM today                         │
│       Started:         12:41 PM (4 hour session)             │
│                                                              │
│   ┌─ Quick start ─────────────────────────────────────┐      │
│   │ [ 30 min ]  [ 1 hour ]  [ 2 hour ]  [ 4 hour ]    │      │
│   │ [ 8 hour ]  [ Indefinite ]    Custom: [ __:__ ] G │      │
│   └───────────────────────────────────────────────────┘      │
│                                                              │
│   ┌─ While awake, show on LEDs… ──────────────────────┐      │
│   │  ( ) Off (don't touch LEDs)                       │      │
│   │  ( ) Slow cyan pulse on LED 1 only                │      │
│   │  (•) Progress bar across all 4 LEDs               │      │
│   │  ( ) Effect mode  [ rainbow chase ▾ ]             │      │
│   └───────────────────────────────────────────────────┘      │
│                                                              │
│   [ Stop now ]                                               │
│                                                              │
│   Last started:  yesterday at 9:14 AM (8 hour session)       │
└──────────────────────────────────────────────────────────────┘
```

When idle, the top row shows `○ idle` and the [ Stop now ] button is replaced by a hint: `Click a quick-start above or type Custom:`. Quick-start buttons commit immediately on click.

## Test plan

### F08a — firmware

1. **Build + flash + regression**:
   - `system_profiler SPUSBDataType | grep -A 30 "DC29"` shows two HID interfaces (Keyboard, Mouse) and one CDC.
   - Macros still type via existing buttons.
   - `dc29 diagnose` connects.
2. **Single jiggle**: send `0x01 'j' 'M'` over CDC. Cursor briefly twitches +1/-1 (visible via macOS Accessibility "Shake to find cursor").
3. **Autonomous mode**:
   - Send `0x01 'j' 'I' <now+60>`. Disconnect/kill the bridge.
   - Watch system idle. After 60 s the cursor stops twitching (autonomous mode expired).
4. **Cancel**: `0x01 'j' 'X'` while autonomous mode is active. Twitching stops within 30 s (next scheduled internal jiggle).
5. **No EEPROM writes**: confirm `FIRMWARE_VERSION` unchanged from F07.

### F08b — bridge + TUI

6. **CLI smoke**:
   - `dc29 awake start 1m`, `dc29 awake status` shows ~1 min remaining, watch macOS not sleep.
   - `dc29 awake stop` → status reports idle.
7. **Quick start**:
   - Open TUI, click "1 hour". Status flips to ACTIVE, countdown begins.
   - Click "Stop now". Returns to idle.
8. **Duration accuracy**:
   - Start a 5 min session. Wait 5 min. Confirm auto-stop fires within ±10 s of expiration.
9. **Awake test (the actual point)**:
   - Configure macOS "Sleep display after 1 minute" and "Sleep computer after 2 minutes."
   - `dc29 awake start 30m`. Walk away for 10 min. Computer is still awake on return.
10. **LED modes** (each tested independently):
    - **Off**: start session with mode=Off. LEDs untouched. Confirm prior state persists.
    - **Cyan pulse**: LED 1 visibly pulses ~0.5 Hz. LEDs 2–4 unchanged.
    - **Progress bar**: at 0% → all LEDs dim cyan; at 50% → 2 LEDs full, 2 dim; at 100% → all off momentarily before auto-stop. Visual sanity check at 25%, 50%, 75%.
    - **Effect mode**: select effect 1 (rainbow-chase). Effect runs during session. On stop, LEDs revert to mode 0.
11. **Teams yield**:
    - With Teams meeting active and Stay Awake "Cyan pulse" mode: enter meeting → LED 1 stops pulsing, LED 4 shows mute state. Leave meeting → cyan pulse resumes.
12. **Bridge crash recovery**:
    - Start a 10 min session. Forcibly kill the `dc29` process.
    - macOS does not sleep for the full 10 min (badge runs autonomously).
    - Restart `dc29 awake status` → reports "no active session" (host-side state lost; firmware will end naturally).
13. **Graceful shutdown**:
    - Start a session. Ctrl+C the bridge. Confirm `0x01 'j' 'X'` is logged sent.
14. **Persistence**:
    - Quit TUI, restart. Last-used duration ("4 hour") and LED mode preselected.

## Cross-cutting design

> Cross-cutting decisions live in [`DESIGN.md`](../DESIGN.md). F08-specific bits below.

### Protocol commands (final)

Per [DESIGN.md §1](../DESIGN.md#1-protocol-command-letter-allocation), updated for the Stay Awake redesign:

```
0x01 'j' 'M'                       # fire single jiggle pulse (one (+1, -1) X-axis pair)
0x01 'j' 'I' <unix_le32:4>         # set autonomous-mode end-time (UTC seconds since epoch)
0x01 'j' 'X'                       # cancel autonomous mode (clear end-time)
0x01 'j' 'S'                       # query state -> reply 0x01 'b' 'J' <state:1> <end_le32:4>
                                   #   state: 0=idle, 1=active. end_le32: 0 if idle.
```

Old commands from the original spec (`'j' '0'`, `'j' '1'`, `'j' 'P' <interval>`) are **dropped** — replaced by the simpler "one-shot pulse + end-time" model. Cleaner, no firmware-side period state.

### Firmware behavior

- `'M'` → emit one jiggle pulse via `udi_hid_mouse`. Always allowed regardless of autonomous-mode state.
- `'I' <end>` → store `autonomous_end_unix = end`. Reset autonomous-mode state machine. End-time is compared against a wall-clock that the bridge sets via the F09 `0x01 'o' 'T' <unix_le32>` command (shared time-sync).
- Autonomous mode tick: in main loop, if `autonomous_end_unix > 0` and `(autonomous_end_unix > badge_clock_unix)`, every 30 s emit a jiggle pulse. When end-time passes, clear `autonomous_end_unix` to 0.
- `'X'` → set `autonomous_end_unix = 0`.

This keeps F08a's firmware additions tiny (~150 LOC) and reuses the F09 time-sync command for free.

### LED ownership during sessions

Stay Awake bridge participates in the existing LED-ownership pattern:
- Calls `set_button_flash(False)` on session start to suppress takeover animation (so progress-bar / effect-mode renders survive button presses).
- Calls `set_button_flash(True)` on stop.
- Yields LED 4 entirely if Teams meeting active.
- Yields all LEDs to audio-reactive bridge if `audio-reactive` is enabled (audio bridge has higher claim per existing convention). Stay Awake just does jiggling silently.

### Bridge architecture

```python
# dc29/bridges/stay_awake.py

class StayAwakeBridge(BaseBridge):
    target_app_names = ("stay-awake",)  # not focus-driven

    async def run(self) -> None:
        while True:
            session = self._session  # set by TUI/CLI
            if session is None or session.expired():
                await self._idle_tick()
                await asyncio.sleep(0.5)
                continue

            await self._jiggle_tick(session)        # 1 pulse if 30s elapsed since last
            await self._heartbeat_tick(session)     # refresh end-time on badge if 60s elapsed
            await self._led_tick(session)            # render selected LED mode
            await asyncio.sleep(0.1)
```

Sessions and mode preferences live in a singleton `StayAwakeState` accessible to both the bridge and the TUI/CLI surfaces. This is the same pattern used by other bridges that expose user-controllable state.

### TUI tab structure

New file `dc29/tui/stay_awake_tab.py`. Mirrors the structure of `BridgesTab` and `LEDsTab` (Container with reactive countdown via `set_interval(1.0, self._tick)`). Registered in `app.py`'s `TabbedContent` at slot 9 (after LEDs).

### CLI surface

New file `dc29/cli_awake.py` (or a subcommand group in `cli.py`). Talks to a running bridge via the existing `BadgeAPI` socket / file-based IPC pattern (whatever the other bridges use for state — needs verification at implementation time).

If no bridge is running, `dc29 awake start` either:
- (a) Spawns one (cleanest UX, Amphetamine-like — start regardless of dc29 status), OR
- (b) Errors with "Run `dc29 start` first."

**Default: (a)** — minimal-friction. Match Amphetamine's "click and forget" feel.

### Persistence (host-side)

`~/.dc29/stay_awake.toml`:

```toml
[last_session]
duration_minutes = 240
led_mode = "progress_bar"

[history]   # last 5 sessions, oldest first
- { started = "2026-05-08T09:14:00Z", duration_min = 480, led_mode = "rainbow_chase" }
```

Used by TUI to preselect the last-used quick-start + LED mode. History is tracked just for the "Last started" footer line in the TUI mockup.

### Files touched

**New:**
- `Firmware/Source/DC29/src/jiggler.c/.h` — autonomous-mode state machine (~150 LOC)
- `dc29/bridges/stay_awake.py` — bridge (~250 LOC)
- `dc29/tui/stay_awake_tab.py` — TUI tab (~300 LOC, includes ASCII mockup logic + countdown)
- `dc29/cli_awake.py` — CLI subcommand group (~120 LOC)

**Modified:**
- `config/conf_usb.h` — add HID-Mouse interface, bump endpoint + interface counts + bcdDevice
- (likely vendored from upstream ASF) `ASF/.../udi_hid_mouse.c/.h`
- `serialconsole.c` — `'j'` parser branch with sub-commands (M, I, X, S)
- `main.c` — call `jiggler_tick()` from main loop; declare wall-clock variable
- `dc29/protocol.py` — `awake_pulse()`, `awake_set_end(unix)`, `awake_cancel()`, `awake_query()` helpers
- `dc29/bridges/manifest.py` — register `stay-awake`
- `dc29/tui/app.py` — register the new tab in `TabbedContent`
- `dc29/cli.py` — wire up the `awake` subcommand group

**Estimated flash impact:** ~700 bytes (mouse driver) + ~200 bytes (autonomous timer). Total ~900 bytes. Well within headroom.

### Open questions

<a id="f08-q1-cli-auto-spawn"></a>
#### Q1 — CLI auto-spawn

`dc29 awake start <duration>` auto-spawns a bridge process if none is running (Amphetamine-feel)?

- [x] ✅ Approve as proposed (auto-spawn)
- [ ] ❌ Reject — error with "Run `dc29 start` first"
- [ ] 🔄 Modify (see comments)

**Comments:**

**Reviewed by:** dallan (default-accepted)   **Date:** 2026-05-09

---

<a id="f08-q2-indefinite-soft-cap"></a>
#### Q2 — Indefinite session soft cap

"Indefinite" sessions have no end-time (proposed). Soft-cap at e.g. 24h to prevent forgotten sessions?

- [x] ✅ Approve as proposed (no cap)
- [ ] ❌ Reject — soft-cap at 24h
- [ ] 🔄 Modify — different cap (specify in comments)

**Comments:**

**Reviewed by:** dallan (default-accepted)   **Date:** 2026-05-09

---

<a id="f08-q3-auto-pause-on-lid-close"></a>
#### Q3 — Auto-pause on lid close / display sleep

Skip auto-pause logic in v1 (proposed) — user manually stops if needed?

- [x] ✅ Approve as proposed (skip auto-pause)
- [ ] ❌ Reject — implement IOKit lid-close detection
- [ ] 🔄 Modify (see comments)

**Comments:**

**Reviewed by:** dallan (default-accepted)   **Date:** 2026-05-09

---

<a id="f08-q4-effect-mode-submenu"></a>
#### Q4 — Effect-mode submenu scope

Show all 7 effect modes in the LED-mode dropdown (proposed) vs. curate to calm ones (breathe, gradient)?

- [x] ✅ Approve as proposed (all 7 modes)
- [ ] ❌ Reject — curate to calm modes only
- [ ] 🔄 Modify (see comments)

**Comments:**

**Reviewed by:** dallan (default-accepted)   **Date:** 2026-05-09

---

<a id="f08-q5-heartbeat-interval"></a>
#### Q5 — Heartbeat interval

30 s jiggle pulse, 60 s end-time refresh (2× headroom over 1-min macOS sleep floor)?

- [x] ✅ Approve as proposed (30 s / 60 s)
- [ ] ❌ Reject — different intervals (specify in comments)
- [ ] 🔄 Modify (see comments)

**Comments:**

**Reviewed by:** dallan (default-accepted)   **Date:** 2026-05-09

---

<a id="f08-q6-custom-duration-max"></a>
#### Q6 — Custom duration max

TUI custom field accepts 1m to 24h (proposed)?

- [x] ✅ Approve as proposed (1m–24h)
- [ ] ❌ Reject — different range (specify in comments)
- [ ] 🔄 Modify (see comments)

**Comments:**

**Reviewed by:** dallan (default-accepted)   **Date:** 2026-05-09

---

<a id="f08-q7-tab-slot"></a>
#### Q7 — TUI tab slot

Place "Stay Awake" tab at slot 9 (after LEDs)?

- [x] ✅ Approve as proposed (slot 9, after LEDs)
- [ ] ❌ Reject — place at a more prominent slot (e.g., slot 4 alongside Effects)
- [ ] 🔄 Modify (see comments)

**Comments:**

**Reviewed by:** dallan (default-accepted)   **Date:** 2026-05-09

## Implementation notes

_Will be filled in as code lands, after design sign-off._

## Testing notes

_To be filled in after manual verification._

## Sign-off

### F08a — firmware sub-feature

#### Design phase

- [ ] Open questions above resolved
- [x] Implementation may begin

**Design approved by:** dallan (default-accepted)   **Date:** 2026-05-09

#### Implementation phase

- [ ] Code complete
- [ ] Build passes (≤ 56 KB)
- [ ] Composite USB descriptor enumerates on macOS (HID-KB + HID-Mouse + CDC)
- [ ] No regression: existing keymaps still type
- [ ] Manual hardware test passed (jiggle + autonomous mode)

**Implementation reviewed by:** _ _   **Date:** _ _

### F08b — bridge + TUI sub-feature

#### Design phase

- [ ] TUI mockup approved (see ASCII layout above)
- [ ] CLI surface approved
- [x] Implementation may begin

**Design approved by:** dallan (default-accepted)   **Date:** 2026-05-09

#### Implementation phase

- [ ] Bridge code complete
- [ ] TUI tab complete
- [ ] CLI subcommand group complete
- [ ] Manual full-flow test passed (all items in Test plan)
- [ ] Implementation notes filled in
- [ ] Testing notes filled in

**Implementation reviewed by:** _ _   **Date:** _ _

### Final sign-off (F08 as a whole)

- [ ] Feature accepted

**Final approved by:** _ _   **Date:** _ _   **Verdict:** _ _
