# F01 — Tap-count + long-press modifiers

> Status: **planned** · Risk: **low** · Owner: firmware

## Goal

Expand the effective key count of the badge from 4 (one action per button) to ~16 by detecting **single-tap, double-tap, triple-tap, and long-press** as four distinct actions per button.

## Why this first

It's a pure input-layer firmware change in `keys.c` + `main.c`. No USB-descriptor risk, no EEPROM layout change required if we encode modifier-by-button-position. Foundational because F02 (chords) reuses the same debounced press-event stream.

## Success criteria

- [ ] Each of buttons 1–4 supports four distinct actions: `tap`, `double-tap`, `triple-tap`, `long-press`.
- [ ] Tap dispatch latency ≤ 220 ms for the single-tap case (200 ms debounce + ≤ 20 ms detection overhead). Single-tap latency is unchanged from baseline when no double/triple is configured for that button.
- [ ] Multi-tap window: 250 ms between releases. Tunable constant in `keys.h`.
- [ ] Long-press threshold: 500 ms held. Tunable constant in `keys.h`.
- [ ] Existing single-action keymaps continue to work — buttons with no modifier-mapped entries fire on press exactly as today.
- [ ] EEPROM layout either unchanged, or `FIRMWARE_VERSION` bumped *intentionally* with a documented migration in this file.
- [ ] `dc29 diagnose --watch` reports the modifier kind in the button event (`tap`, `double`, `triple`, `long`).
- [ ] Build still fits in 56 KB Release.

## Test plan

1. **Build**: `cd Firmware/Source/DC29 && make`. Confirm flash-usage line stays under 56 KB.
2. **Flash**: `/flash-badge`. Verify CDC re-enumerates.
3. **Regression** (must pass before testing the new behavior):
   - Press each button once with default keymap; confirm the same keystroke as before-this-feature ships.
   - Confirm Teams mute LED still works (`dc29 flow -v` while in a meeting).
4. **Single-tap** (default action):
   - Configure B1 single-tap = `cmd+s`. Open a text editor. Press B1 once. Verify save fires within ~220 ms of release.
5. **Double-tap**:
   - Configure B1 double-tap = `cmd+shift+s` (save-as). Press B1 twice quickly. Verify save-as fires.
   - Press B1 once and wait > 250 ms. Verify single-tap action fires.
6. **Triple-tap**:
   - Configure B1 triple-tap = `cmd+opt+s`. Press B1 three times quickly. Verify the triple action.
7. **Long-press**:
   - Configure B1 long-press = `cmd+w`. Hold B1 ≥ 500 ms. Verify long-press action fires *on release*, not on threshold cross (so users can abort by holding longer or releasing early — pick one and document).
8. **Latency probe**: in `dc29 diagnose --watch`, confirm event timestamps match user expectations within ±50 ms.
9. **Stress**: rapid-fire 100 single-taps via mechanical actuator (or fast finger). Confirm no missed events and no stuck-modifier states.

## Design proposal (review before code lands)

> Status: **proposed** — awaiting user sign-off on design before implementation.

### Why a refactor is unavoidable

The current input layer is fundamentally **press-only**: each button has a falling-edge EXTINT ISR that sets a `volatile bool buttonN = true` after debounce. The main loop reads the flag, fires `send_keys(n)`, clears the flag. There is **no release detection and no press-duration tracking** — neither tap-counting nor long-press can be implemented on top of this without restructuring.

### Chosen architecture: pure polling state machine

Three options were considered:

| Option | Description | Verdict |
|--------|-------------|---------|
| A. Both-edge ISR + state machine | ISRs timestamp press + release; main loop runs SM | Rejected — extra volatile/ordering complexity for no real-time benefit at human-scale event rates. |
| B. Pure polling in main loop | Each iteration reads GPIO, software debounces, advances SM | **Chosen.** Matches existing slider-poll pattern, kills ISR/main-loop sync concerns, easier to debug. |
| C. Both-edge ISR feeding event queue | ISR pushes raw events to ring buffer; main loop drains + runs SM | Rejected — overkill for 4 buttons. |

Risks of polling: a CDC-bound main-loop iteration could stretch to tens of ms, missing a fast tap-release-tap. Mitigation: SM works off `millis` timestamps, not iteration count, so a slow tick still produces correct event detection — only the *latency* degrades.

### Per-button state machine

```
       ┌─────┐  press detected      ┌──────────────────┐
       │IDLE ├─────────────────────▶│PRESSED_WAITING   │
       └─────┘                      │(timing held dur) │
          ▲                         └──────┬───────────┘
          │                                │
          │ tap-count window expires       │ release before LP threshold
          │ (250ms after last release)     ▼
          │                         ┌──────────────────┐
          │                         │RELEASED_WAITING_ │
          │                         │TAPCOUNT          │
          │                         └──────┬───────────┘
          │                                │
          │  next press inside window      │  window expires →
          │  (increments tap_count)        │  fire (tap_count)-tap action
          └────────────────────────────────┘
```

Long-press path: `PRESSED_WAITING` measures held duration. On release with `held >= 500 ms`, fires long-press action and returns to `IDLE`. Releases under threshold drop into `RELEASED_WAITING_TAPCOUNT` as normal.

### Tunable constants (in `keys.h`)

| Constant            | Default | Purpose |
|---------------------|---------|---------|
| `DEBOUNCE_TIME`     | 200 ms (existing) | Min interval between accepted press-edge detections |
| `MULTI_TAP_WINDOW`  | 250 ms  | Max gap between releases that still counts as same multi-tap chain |
| `LONG_PRESS_THRESH` | 500 ms  | Min held duration to register as long-press |
| `CHORD_WINDOW`      | 80 ms   | (F02) Max gap between presses to register as a chord |

### Fast-path for backwards compat

If no modifier mapping is set for a button (default state on every boot), the SM short-circuits: press → fire single-tap action immediately on press detection (matching today's behavior). Multi-tap latency is **only** incurred when a double or triple mapping exists for that button. This preserves muscle-memory for users who don't opt into the new modifiers.

### Long-press: fire on release, not on threshold cross

Two options:
- **A. Fire at threshold cross (500 ms held).** Pro: feels snappy. Con: user can't abort.
- **B. Fire on release if held ≥ 500 ms.** Pro: abortable by holding-then-releasing-fast (will instead trigger single-tap). Con: feels less immediate.

**Chosen: B.** Aborting is more important than perceived speed for a destructive long-press action like "delete" or "lock screen."

### Modifier dispatch table (RAM-only)

EEPROM is too tight to hold 4 buttons × 4 event kinds + 6 chord pairs without rearranging the existing 230-byte keymap region. Decision: **store modifier mappings in RAM only, populated by bridges on startup**, mirroring the existing pattern for `splash_on_press_enabled`, `slider_enabled`, `button_flash_enabled`.

```c
typedef struct {
    uint8_t mod;
    uint8_t key;
} action_t;

action_t action_double[4];   // [button index 0-3]
action_t action_triple[4];
action_t action_long[4];
action_t action_chord[4][4]; // [a][b], only a < b populated  (used by F02)
```

A `(0, 0)` entry means "no mapping → fall through to single-tap action from EEPROM keymap." Total RAM cost: 12 + 16 = 28 `action_t` = 56 bytes.

EEPROM-backed persistence is deferred to a follow-up that bumps `FIRMWARE_VERSION` (per the locked wipe-on-bump policy). Out of scope for F01.

### Protocol additions

The existing `0x01 'M'` / `'U'` / `'X'` letters are taken (Teams mute). New top-level letter `'A'` (action-modifier) introduces a sub-command space:

```
0x01 'A' 'D' <button:1-4> <mod> <key>          # set Double-tap action
0x01 'A' 'T' <button:1-4> <mod> <key>          # set Triple-tap action
0x01 'A' 'L' <button:1-4> <mod> <key>          # set Long-press action
0x01 'A' 'C' <btn_a:1-4> <btn_b:1-4> <mod> <key>  # set Chord (a < b enforced)  — F02
0x01 'A' 'X'                                   # clear all RAM mappings
```

Setting `<mod> = 0` and `<key> = 0` clears that specific entry.

### Event report-back over CDC

Today, `send_keys` writes back `0x01 'B' <button> <mod> <key>` (5 bytes). To preserve backwards compatibility, single-tap continues to use that exact format. Extended events use a **lowercase** `'b'` to namespace cleanly:

```
0x01 'b' '2' <button>                # double-tap event
0x01 'b' '3' <button>                # triple-tap event
0x01 'b' 'L' <button>                # long-press event
0x01 'b' 'C' <btn_a> <btn_b>         # chord event (F02)
```

`dc29 diagnose --watch` parses both 'B' (legacy) and 'b' (extended) and prints the kind.

### Files touched

**New:**
- `Firmware/Source/DC29/src/input.h` — state machine public API
- `Firmware/Source/DC29/src/input.c` — implementation (~300 LOC)

**Modified:**
- `Firmware/Source/DC29/src/main.c` — replace `if(button1)` flag block with `input_tick(millis)` and event dispatch
- `Firmware/Source/DC29/src/keys.c` / `keys.h` — add `send_keys_action(button, event_kind)` and helper to look up modifier action; preserve `send_keys()` for slider directions
- `Firmware/Source/DC29/src/serialconsole.c` — `0x01 'A' ...` parser
- `dc29/protocol.py` — add `set_action_*` helpers and `parse_extended_button_event`
- `dc29/badge.py` (or `BadgeAPI`) — expose Python wrappers for the new commands

**Estimated flash impact:** +1.5 KB (input.c + protocol parsing). Headroom: ~9 KB. Comfortable.

### Test-rig scaffolding

To meet the success criterion "no missed events under 100 rapid taps," add a host-side smoke runner: `tools/input_smoke.py` that listens to `'b'` events on CDC and counts them while the user mashes a button. Lives in `tools/`, not shipped in the package.

### Open questions

<a id="f01-q1-long-press-semantics"></a>
#### Q1 — Long-press semantics

Fire on release (proposed: yes — abortable by holding-then-releasing-fast) vs. fire at threshold cross (snappier but not abortable)?

- [ ] ✅ Approve as proposed (fire on release)
- [ ] ❌ Reject — fire at threshold cross
- [ ] 🔄 Modify (see comments)

**Comments:**

**Reviewed by:** _ _   **Date:** _ _

---

<a id="f01-q2-tap-count-window"></a>
#### Q2 — Multi-tap window default

250 ms between releases counts as same multi-tap chain. Power-typists may trip false double-taps. Acceptable?

- [ ] ✅ Approve as proposed (250 ms)
- [ ] ❌ Reject — pick a different value (specify in comments)
- [ ] 🔄 Modify (see comments)

**Comments:**

**Reviewed by:** _ _   **Date:** _ _

---

<a id="f01-q3-event-report-format"></a>
#### Q3 — Event report-back format

Use lowercase `'b'` namespace for new event kinds (`'b' '2'` double, `'b' '3'` triple, `'b' 'L'` long, `'b' 'C'` chord) and preserve legacy `'B'` for solo single-tap?

- [ ] ✅ Approve as proposed (lowercase `'b'`)
- [ ] ❌ Reject — extend existing `'B'` with a kind byte (breaks compat)
- [ ] 🔄 Modify (see comments)

**Comments:**

**Reviewed by:** _ _   **Date:** _ _

---

<a id="f01-q4-ram-only-first-cut"></a>
#### Q4 — RAM-only modifier table for first cut

Modifier mappings live in RAM, populated by bridges on connect, lost on power-cycle. EEPROM persistence is a follow-up that bumps `FIRMWARE_VERSION` later.

- [ ] ✅ Approve as proposed (RAM-only first)
- [ ] ❌ Reject — require EEPROM persistence in F01 (will bump FIRMWARE_VERSION earlier than F07)
- [ ] 🔄 Modify (see comments)

**Comments:**

**Reviewed by:** _ _   **Date:** _ _

## Implementation notes

_Will be filled in as code lands, after design sign-off._

## Testing notes

_To be filled in after manual verification._

## Sign-off

### Design phase

- [ ] All open questions above resolved
- [ ] Implementation may begin

**Design approved by:** _ _   **Date:** _ _

### Implementation phase

- [ ] Code complete
- [ ] Build passes (≤ 56 KB)
- [ ] Manual hardware test passed (all items in Test plan above)
- [ ] Implementation notes filled in
- [ ] Testing notes filled in

**Implementation reviewed by:** _ _   **Date:** _ _

### Final sign-off

- [ ] Feature accepted

**Final approved by:** _ _   **Date:** _ _   **Verdict:** _ _
