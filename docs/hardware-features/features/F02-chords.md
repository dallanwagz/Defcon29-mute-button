# F02 — Chord shortcuts

> Status: **planned** · Risk: **low** · Owner: firmware

## Goal

Recognize **two-button chords** (e.g., B1+B2 pressed within ~80 ms) as distinct actions, adding 6 chord slots on top of the 4 solo buttons.

## Success criteria

- [ ] All six 2-button combinations are addressable: B1+B2, B1+B3, B1+B4, B2+B3, B2+B4, B3+B4.
- [ ] Chord detection window: 80 ms between first press and second press. Tunable constant in `keys.h`.
- [ ] When a chord fires, **neither solo action** for the participating buttons fires.
- [ ] When the chord window expires without a second press, the solo action fires (so unmapped chords don't break solo behavior).
- [ ] Latency: solo-press latency increases by at most the chord window (80 ms) for buttons that have chord mappings; buttons with *no* chord mappings keep current latency.
- [ ] `dc29 diagnose --watch` prints chord events as `chord:1+2`, `chord:2+3`, etc.
- [ ] Compatible with F01: chord detection wins over multi-tap (a B1+B2 press shouldn't accidentally register as a B1 double-tap).

## Test plan

1. **Build + flash + regression** (as in F01).
2. **Solo unchanged**: with no chord mappings, press each button. Confirm solo actions fire with no perceptible extra latency (chord window suppressed when no mapping exists).
3. **Single chord**:
   - Configure chord B1+B2 = `cmd+space` (Spotlight). Press both within 80 ms. Verify Spotlight opens.
   - Confirm neither B1's nor B2's solo action fired.
4. **All 6 chords**: configure each, fire each, verify each.
5. **Negative — late second press**: press B1, wait ≥ 100 ms, then press B2. Confirm B1's solo fires (after window expiry) and B2's solo fires on its own.
6. **Negative — interaction with F01**: configure B1 single-tap + B1+B2 chord. Tap B1 once cleanly. Confirm single-tap fires after chord window. Press B1+B2. Confirm chord wins.
7. **Three-finger guard**: press B1+B2+B3 simultaneously. Document the behavior — recommend: fire the highest-priority chord we have a mapping for; suppress all others. Verify no duplicate keystrokes.

## Design proposal (review before code lands)

> Status: **proposed** — depends on F01's input state machine. Read [F01's design proposal](F01-tap-count-long-press.md#design-proposal-review-before-code-lands) first; this doc only captures chord-specific deltas.

### Chord detection in the state machine

When a button transitions IDLE → PRESSED_WAITING, start a **chord window** of 80 ms (`CHORD_WINDOW`). If a *second* button enters PRESSED_WAITING within that window:

1. Cancel both buttons' multi-tap state machines (return them to a "consumed" state).
2. Look up the action via `action_chord[a][b]` where `a < b` are the 0-based button indices.
3. If a mapping exists: fire it via the F06 burst path (or single-shot send), emit `0x01 'b' 'C' <btn_a> <btn_b>` event.
4. If no mapping exists: discard the chord window and let both buttons run their normal SM (single-tap eventually fires for each).
5. Both buttons remain "consumed" until they're released — so a long-held chord doesn't repeat-fire.

### Latency penalty: scoped to participating buttons

A button only pays the 80 ms chord-window penalty if **at least one chord mapping references it**. Without any chord mapping, the button's SM short-circuits exactly as in F01's fast path — single-tap fires immediately on press.

This means: setting `chord(B1, B2)` adds 80 ms to solo-press latency for both B1 *and* B2. B3 and B4 stay fast.

Document this trade-off in user-facing docs so power users can keep their fastest buttons unencumbered.

### Three-finger guard

If a third button enters PRESSED_WAITING while a 2-button chord is already armed:
- **Chosen behavior:** ignore the third button entirely (consume it as no-op until released). The user obviously wanted the 2-chord; the third press is finger-fumble.
- **Alternative considered:** treat as 3-button chord. Rejected — explodes the action table from 6 entries to 10+, and 3-finger chords on 4 buttons are awkward to physically execute.

### Storage

Single-purpose 4×4 table `action_chord[a][b]`. Memory cost: 16 × 2 bytes = 32 bytes. Only the upper triangle (a < b) is meaningful; the rest is padding for indexing simplicity.

### Protocol command (already specified in F01)

```
0x01 'A' 'C' <btn_a:1-4> <btn_b:1-4> <mod> <key>
```

Firmware enforces `btn_a < btn_b` and rejects malformed entries with a `0x01 'b' 'E'` error event (decline-beep if F03 is shipped).

### No additional files

All chord logic lives inside `input.c` (added in F01) and `serialconsole.c`'s `'A' 'C'` parser branch. No new files.

### Open questions

<a id="f02-q1-three-finger-fumble"></a>
#### Q1 — Three-finger fumble policy

3rd-button press while a 2-button chord is armed: ignore the third button (consume as no-op until released)?

- [x] ✅ Approve as proposed (ignore)
- [ ] ❌ Reject — treat as 3-button chord (expands action table)
- [ ] 🔄 Modify (see comments)

**Comments:**

**Reviewed by:** dallan (default-accepted)   **Date:** 2026-05-09

---

<a id="f02-q2-chord-vs-long-press"></a>
#### Q2 — Chord vs. long-press collision

Hold B1 alone for 500 ms, then press B2: chord window has expired → long-press fires on B1 release, B2 fires solo. Acceptable?

- [x] ✅ Approve as proposed (sequential — long-press + solo)
- [ ] ❌ Reject — B2-during-B1-hold should reset to chord-attempt
- [ ] 🔄 Modify (see comments)

**Comments:**

**Reviewed by:** dallan (default-accepted)   **Date:** 2026-05-09

## Implementation notes

_Will be filled in as code lands, after design sign-off._

## Testing notes

_To be filled in after manual verification._

## Sign-off

### Design phase

- [x] All open questions above resolved
- [x] Implementation may begin

**Design approved by:** dallan (default-accepted)   **Date:** 2026-05-09

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
