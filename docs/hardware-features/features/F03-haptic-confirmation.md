# F03 — Haptic-style action confirmation (buzzer)

> Status: **planned** · Risk: **low** · Owner: firmware

## Goal

Fire a brief (~10 ms) buzzer click on every successful macro send so the user gets a non-visual confirmation that the keystroke fired — useful when focus jumps or the macro target is off-screen.

## Success criteria

- [ ] After every `send_keys()` invocation that emits at least one HID report, a click fires.
- [ ] Click duration ≤ 15 ms; not audible enough to disturb others (configurable click-volume duty cycle).
- [ ] Toggleable at runtime via protocol command `0x01 'K' 0/1` (default **on** per locked decision in [README](../README.md), RAM-only — does not survive reboot).
- [ ] Persistent toggle via existing serial console menu entry, written to EEPROM.
- [ ] The click does not block button-press dispatch — buzzer must run from a non-blocking timer / state machine, not a `delay_ms()`.
- [ ] No regression to badge-game audio (Simon Says / Whack-a-Mole still beep correctly).

## Test plan

1. **Build + flash + regression**.
2. **Default-on**: tap B1 with default keymap. Hear a faint click. Press B2, B3, B4. All click.
3. **Toggle off**: send `0x01 'K' 0` over CDC. Tap B1. No click. Confirm keystroke still fires.
4. **Toggle on**: send `0x01 'K' 1`. Tap B1. Click returns.
5. **Boot persistence (negative)**: power-cycle the badge after toggling off. Confirm default-on returns (RAM-only toggle).
6. **EEPROM persistence**: enter serial console, set click default = off, save. Power-cycle. Tap B1. Confirm no click. Restore via console.
7. **Timing**: while playing Simon Says, tap a Simon button. Confirm both the game tone *and* the action click fire correctly (or document that game mode suppresses the click).
8. **Stress**: hold B1 for a typing burst (autorepeat off — only a single send_keys per press). Confirm exactly one click per press, no buzzer hang.

## Design proposal (review before code lands)

> Status: **proposed** — awaiting user sign-off.

### Hardware already does most of the work

`pwm.c` already exposes `buzzer_play(freq_hz, duration_ms)` — non-blocking, ticked from the main loop, managed off TCC2 in MATCH_FREQ mode. The takeover animation (`takeover_start`) already fires a personality-specific click during phase 1 of every button press (`buzzer_play(PP[pers].click_hz, PP[pers].click_ms)` in `pwm.c:503`).

### Insight: F03 only needs to fill the gap when takeover is disabled

Bridges call `badge.set_button_flash(False)` when they take over LEDs. That suppresses the takeover animation **and** its built-in click. F03's job is therefore tighter than originally written: **fire a buzzer click after `send_keys()` returns, but only when the takeover wasn't going to fire one anyway.**

```c
// in send_keys() (or just after its return path in main.c), at the end:
if (haptic_click_enabled && !button_flash_enabled) {
    buzzer_play(HAPTIC_CLICK_HZ, HAPTIC_CLICK_MS);
}
```

This avoids double-clicks when both takeover and F03 are on, and gives bridge users (the most common case for shared-LED setups) the haptic feedback they're missing today.

### Protocol letter conflict — `'K'` is taken

Original proposal: `0x01 'K' 0/1` to toggle. Reading `serialconsole.c` shows `'K'` is already the **set_button_keymap** command (3 args). New letter: **`'k'` (lowercase)**. Single-byte arg.

Updated commands:

```
0x01 'k' 0    # disable haptic click (RAM-only)
0x01 'k' 1    # enable haptic click
```

Default = on, per locked decision in [README](../README.md).

### Tunables (in `keys.h` or a new `audio.h`)

| Constant            | Default | Notes |
|---------------------|---------|-------|
| `HAPTIC_CLICK_HZ`   | 1200 Hz | Crisp, slightly above the takeover CLASSIC click (800 Hz) so it reads as a different sound when both are off and one fires |
| `HAPTIC_CLICK_MS`   | 8 ms    | Short enough to be inaudible-ish across rooms; long enough to feel |

### Files touched

**Modified:**
- `Firmware/Source/DC29/src/keys.c` — call `buzzer_play()` at the end of `send_keys()` when conditions are met. ~5 LOC.
- `Firmware/Source/DC29/src/serialconsole.c` — add `'k'` parser branch. ~5 LOC.
- `Firmware/Source/DC29/src/main.c` — declare `haptic_click_enabled = true` near the other RAM toggles. 1 line.
- `dc29/protocol.py` — add `set_haptic_click(enabled)` helper.

**Estimated flash impact:** < 100 bytes. Negligible.

### Coexistence with F04 patterns

When F04 ships, a long-running beep pattern is "owning" the buzzer. If F03 clicks during a pattern, the click `buzzer_play()` call would override the current pattern note's compare value mid-note. **Decision: F03 click is suppressed while a pattern is playing** (check the pattern engine's "in-progress" flag). Patterns are short (a few hundred ms tops), so the dropped click is barely noticeable.

### Game-mode coexistence

Simon Says / Whack-a-Mole drive the buzzer for game tones. Game mode bypasses `send_keys()` entirely, so F03 never fires during games. No change needed.

### EEPROM persistence (deferred)

The original spec asked for a persisted toggle via the serial console menu. **Deferred to a later cleanup PR** — this feature ships RAM-only (default-on), bridges can re-enable trivially on connect, and skipping the EEPROM write keeps F03 inside its budget.

Documented as a known gap in the success-criteria checkbox. If you want EEPROM persistence as a hard requirement for F03 sign-off, say so before code lands.

### Open questions

<a id="f03-q1-click-frequency"></a>
#### Q1 — Click frequency

1200 Hz crisp click (proposed) vs. softer 600 Hz "thud"?

- [ ] ✅ Approve as proposed (1200 Hz crisp)
- [ ] ❌ Reject — use 600 Hz thud
- [ ] 🔄 Modify — different value (specify in comments)

**Comments:**

**Reviewed by:** _ _   **Date:** _ _

---

<a id="f03-q2-click-duration"></a>
#### Q2 — Click duration

8 ms (more "tap" than "click") vs. 15 ms (more audible)?

- [ ] ✅ Approve as proposed (8 ms)
- [ ] ❌ Reject — use 15 ms
- [ ] 🔄 Modify (see comments)

**Comments:**

**Reviewed by:** _ _   **Date:** _ _

---

<a id="f03-q3-eeprom-persistence"></a>
#### Q3 — EEPROM persistence deferred to follow-up?

Ship F03 RAM-only first, EEPROM toggle persistence in a later cleanup PR?

- [ ] ✅ Approve as proposed (defer)
- [ ] ❌ Reject — require EEPROM persistence in F03
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
