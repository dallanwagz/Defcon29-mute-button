# Cross-Cutting Design — All 11 Features

> Companion to [`README.md`](README.md). The per-feature files in [`features/`](features/) capture goal/criteria/test plans + feature-specific implementation notes. **Anything that's shared across features lives here**, so a decision made for F03 doesn't accidentally collide with one made for F09. Read this top-to-bottom before starting any feature's code.

## Table of contents

1. [Protocol command letter allocation](#1-protocol-command-letter-allocation)
2. [Buzzer arbitration](#2-buzzer-arbitration)
3. [EEPROM layout — single bump strategy](#3-eeprom-layout--single-bump-strategy)
4. [USB endpoints + descriptor strategy](#4-usb-endpoints--descriptor-strategy)
5. [Burst-path sharing (F06 / F07 / F09)](#5-burst-path-sharing-f06--f07--f09)
6. [Input state machine (F01 / F02)](#6-input-state-machine-f01--f02)
7. [Persistence policy summary](#7-persistence-policy-summary)
8. [`FIRMWARE_VERSION` versioning + migration](#8-firmware_version-versioning--migration)
9. [Open cross-cutting questions](#9-open-cross-cutting-questions)

---

## 1. Protocol command letter allocation

The CDC escape-byte side-channel uses `0x01` as a prefix followed by a single ASCII letter and zero-or-more arg bytes. The legacy parser is in `serialconsole.c` and is **case-sensitive**, so uppercase and lowercase are independent namespaces. We exploit that to keep all 11 features non-conflicting.

### Already in use (do not reassign)

| Letter | Direction | Args | Meaning                       |
|--------|-----------|------|-------------------------------|
| `M`    | host→badge | 0   | LED 4 red (Teams muted)       |
| `U`    | host→badge | 0   | LED 4 green (Teams unmuted)   |
| `X`    | host→badge | 0   | LED 4 off (not in meeting)    |
| `K`    | host→badge | 3   | set_button_keymap(btn, mod, key) |
| `Q`    | host→badge | 1   | query keymap entry for button |
| `L`    | host→badge | 4   | set LED N color (n, r, g, b)  |
| `P`    | host→badge | 12  | atomic 4-LED paint            |
| `F`    | host→badge | 1   | button-press takeover enable/disable |
| `E`    | host→badge | 1   | effect mode 0..7              |
| `T`    | host→badge | 1   | fire takeover ripple          |
| `S`    | host→badge | 1   | slider enable/disable         |
| `I`    | host→badge | 1   | interactive splash enable     |
| `W`    | host→badge | 3   | (existing) write LED color & save |
| `A`    | badge→host | 1   | ACK after keymap write        |
| `R`    | badge→host | 4   | reply to keymap query         |
| `B`    | badge→host | 3   | button-press event (legacy)   |

### New allocations for this feature batch

Lowercase letters provide a clean, unused namespace. We prefer **lowercase for the new commands** to make it obvious in protocol traces which commands belong to this feature batch vs. the legacy set.

| Letter | Feature | Direction | Args | Meaning |
|--------|---------|-----------|------|---------|
| `m`    | F01/F02 | host→badge | varies (sub-cmd) | modifier-action table (double / triple / long / chord) |
| `b`    | F01/F02 | badge→host | varies (sub-cmd) | extended button event (double, triple, long, chord) |
| `k`    | F03     | host→badge | 1   | haptic click toggle 0/1 |
| `p`    | F04     | host→badge | 1   | play beep pattern by id |
| `h`    | F06     | host→badge | 2 + payload | hyper-fast HID burst (n_le16 + (mod,key) pairs) |
| `v`    | F07     | host→badge | varies (sub-cmd) | vault: write/fire/clear/list |
| `j`    | F08     | host→badge | varies (sub-cmd) | Stay Awake: pulse / set end-time / cancel / query |
| `o`    | F09     | host→badge | varies (sub-cmd) | TOTP: write/fire/list/sync_clock |
| `e`    | (any)   | badge→host | varies | error event (decline beep, etc.) |

F10 (HID class switch) and F11 (WebUSB) do not need new command letters — F10 is a boot-time gesture, F11 uses USB control transfers + WebUSB descriptors.

### Sub-command structure for `m`, `b`, `v`, `j`, `o`

Each of these uses a 1-byte sub-command immediately after the letter:

```
0x01 'm' 'D' <button:1-4> <mod> <key>          # set Double-tap action
0x01 'm' 'T' <button:1-4> <mod> <key>          # set Triple-tap action
0x01 'm' 'L' <button:1-4> <mod> <key>          # set Long-press action
0x01 'm' 'C' <btn_a:1-4> <btn_b:1-4> <mod> <key>  # set Chord (a < b)
0x01 'm' 'X'                                    # clear all RAM modifier mappings

0x01 'b' '2' <button>                           # double-tap event
0x01 'b' '3' <button>                           # triple-tap event
0x01 'b' 'L' <button>                           # long-press event
0x01 'b' 'C' <btn_a> <btn_b>                    # chord event

0x01 'v' 'W' <slot> <len> <payload>            # write vault slot
0x01 'v' 'F' <slot>                             # fire vault slot
0x01 'v' 'C' <slot>                             # clear vault slot
0x01 'v' 'L'                                    # list vault slots (replies via 'b' 'V' ...)

0x01 'j' 'M'                                    # fire one jiggle pulse (single +1/-1 X-axis pair)
0x01 'j' 'I' <unix_le32:4>                      # set autonomous-mode end-time (UTC seconds)
0x01 'j' 'X'                                    # cancel autonomous mode
0x01 'j' 'S'                                    # query state -> reply 0x01 'b' 'J' <state> <end_le32>

0x01 'o' 'W' <slot> <label_16> <key_20>        # provision TOTP
0x01 'o' 'T' <unix_le32>                        # set wall clock
0x01 'o' 'F' <slot>                             # fire TOTP code
0x01 'o' 'L'                                    # list TOTP slots
```

### Letter conflict warnings (changed from initial proposals)

| Originally proposed | Conflict found | Replacement |
|--------------------|----------------|-------------|
| `0x01 'A' ...` (F01 modifier table) | `'A'` is the existing keymap-write ACK | `0x01 'm' ...` |
| `0x01 'K' 0/1` (F03 click toggle)   | `'K'` is `set_button_keymap`            | `0x01 'k' 0/1` |
| `0x01 'B' <pattern>` (F04 beep)     | `'B'` is the legacy button event        | `0x01 'p' <pattern>` |
| `0x01 'B' <args>` (F06 burst)       | same                                    | `0x01 'h' <args>` |
| `0x01 'V' ...` (F07 vault)          | (none — letter free, but lowercase consistent) | `0x01 'v' ...` |
| `0x01 'J' ...` (F08 jiggler)        | (none) | `0x01 'j' ...` |
| `0x01 'O' ...` (F09 TOTP)           | (none) | `0x01 'o' ...` |

Lowercase across the board gives us 26 fresh slots for any future feature without touching legacy.

### `dc29/protocol.py` changes

Add a `Cmd` enum that matches the table, plus per-feature helpers (`set_action_double`, `play_beep_pattern`, `hid_burst`, `vault_write`, `jiggler_set`, `totp_provision`, etc.). One PR per feature, but the enum gets a stub for all 11 in the **first** firmware feature merge so the surface is reserved.

---

## 2. Buzzer arbitration

The buzzer is a single shared resource. Five things want to drive it:

| Source | Origin | Latency tolerance |
|--------|--------|-------------------|
| Takeover animation | `pwm.c:503` (existing) | Strict — synced to LED phase |
| Game tones | `games.c` (existing) | Strict — game gameplay |
| F03 haptic click | new | Best-effort |
| F04 beep pattern | new | Best-effort within 50 ms |
| F05 beat-doubler (Python bridge sends F04 commands) | new | Best-effort within 30 ms |

### Priority order (highest wins)

1. **Game tones** — highest. If `gamemode != IDLE`, suppress everything else.
2. **Takeover animation click + thud** — fires only when `button_flash_enabled` is on.
3. **F04 patterns** — middle. A new pattern preempts a running pattern (cancel + start).
4. **F03 haptic click** — lowest. Suppressed if a pattern is currently playing OR if the takeover would have fired its own click for this press.

### Ownership flag

Add a single `volatile uint8_t buzzer_owner` enum:

```c
typedef enum {
    BZO_IDLE,
    BZO_GAME,
    BZO_TAKEOVER,
    BZO_PATTERN,
    BZO_HAPTIC_CLICK,
} buzzer_owner_t;
```

`buzzer_play()` callers set the owner. The `_buzzer_tick()` function (extended) tracks the owner and refuses lower-priority requests while a higher-priority owner is active. When a duration expires, owner returns to BZO_IDLE.

This lets us add F04 + F05 without rewriting any existing buzzer caller — just teach existing call sites to set the right owner enum, and gate new callers via the priority check.

### F05's role

F05 (beat-doubler) is **a Python bridge that sends `0x01 'p' <kick_pattern_id>` commands to the badge.** No new firmware code beyond F04. The bridge throttles to ≥80 ms between sends and yields to Teams meetings. F04 handles the priority / ownership question on the firmware side.

---

## 3. EEPROM layout — single bump strategy

EEPROM is RWW-emulated, capped at **260 bytes**. Current layout consumes through byte 26+234 = 260 (existing keymap fills to capacity). **We are at the cap today.** Any addition requires either:

- (a) shrinking the existing keymap region, or
- (b) accepting the cap means certain features are RAM-only.

### Decision: single bump for F07 + F09 combined

Rather than bumping `FIRMWARE_VERSION` twice (once for F07, once for F09) — wiping users' state twice — we do **one bump that lays out all EEPROM-resident future state up front**. F07 (vault) lands first; F09 (TOTP) reuses already-reserved space.

Per the locked policy in [README](README.md#decisions-locked-in-2026-05-09), the bump wipes all EEPROM on first boot.

### Proposed new layout (after `FIRMWARE_VERSION` bump from 2 → 3)

| Offset | Size | Field | Notes |
|--------|------|-------|-------|
| 0      | 1    | brightness                    | (existing) |
| 1–12   | 12   | LED 1–4 resting colors        | (existing) |
| 13–24  | 12   | LED 1–4 pressed colors        | (existing) |
| 25     | 1    | settings flags byte           | **NEW**: bit0=haptic_click_default (F03), bit2=splash, bit3=slider_default — replaces scattered RAM defaults. (bit1 reserved; F08 Stay Awake persists host-side instead.) |
| 26     | 1    | keymap length                 | (existing) |
| 27–166 | 140  | keymap region (was 234)       | **shrunk** from 234 → 140 to free room for new state. Still 140 bytes for the 4 buttons + slider 5/6 — plenty for typical usage. |
| 167    | 1    | vault_slot0_len               | F07 |
| 168–199 | 32  | vault_slot0_payload (16 pairs) | F07 |
| 200    | 1    | vault_slot1_len               | F07 |
| 201–232 | 32  | vault_slot1_payload           | F07 |
| 233–252 | 20  | totp_slot0_key                | F09 (raw bytes, post-base32-decode) |
| 253–256 | 4   | totp_slot0_label_short        | F09 (4-char label) |
| 257     | 1   | reserved (future flags)       | |
| 258–259 | 2   | reserved                      | |

**Total: 260 / 260 bytes** — at the cap.

### Trade-offs

- Vault is **2 slots × 16 (mod, key) pairs**, not 4 slots × 32. Half what the F07 spec proposed. **Sufficient for the stage-demo use case** — typical macros are SSH key (large but rare), passphrase (~20 keys), email signature (~30 keys). A 16-keypair payload covers ~16 visible chars including modifiers, ~32 plain ASCII chars.
- TOTP is **1 slot, 4-char label**. Spec said 2 × 16-char. Reduced because the cap is binding. Document explicitly.
- Keymap region shrinks from 234 → 140 bytes. The stock keymap fills ~50 bytes; user customization is typically small. **No actual impact for current users.**
- The `settings flags byte` consolidates currently-RAM-only toggles into EEPROM, fixing a long-standing minor irritation.

### If you want larger vault / TOTP

Two options, neither in scope for this batch:
- (i) Reduce keymap region further. Painful for power users with long keymaps.
- (ii) Move keymap entirely to RAM-on-boot, populated from EEPROM at startup, with the EEPROM region becoming a sparse blob. Larger refactor.

If the user wants the larger spec sizes, it's a config-time decision that needs to be made before F07 ships.

---

## 4. USB endpoints + descriptor strategy

### Current topology (3 interfaces, 4 endpoints)

| Iface | Class | Endpoints used |
|-------|-------|----------------|
| 0 + 1 | CDC (control + data) | EP1 IN (TX), EP2 OUT (RX), EP3 IN (notify) |
| 2     | HID-Keyboard (with Consumer page for media keys) | EP4 IN |

`USB_DEVICE_MAX_EP = 4` in `conf_usb.h`. SAMD21 hardware supports up to **8 endpoints (EP0–EP7)**, so we have 3 unused endpoints (EP5, EP6, EP7).

### Cross-feature impact

- **F08 (Stay Awake)** — adds HID-Mouse interface, needs **1 new IN endpoint (EP5)**. `USB_DEVICE_MAX_EP` → 5. (Bridge + TUI scope additions don't impact USB.)
- **F10 (HID class switch)** — needs to expose **different descriptor sets at boot**. Done by adding a build-time enum-driven descriptor selector in `usb_main.c`-equivalent + bumping `bcdDevice` per mode so Windows re-enumerates fresh.
- **F11 (WebUSB)** — adds Microsoft OS 2.0 + WebUSB BOS descriptors. **Zero new endpoints** (control-transfer based).

Modes selected at boot (from F10):

| Mode | bcdDevice | Interfaces                          | Endpoints |
|------|-----------|-------------------------------------|-----------|
| 0 (default) | 0x0100 | CDC + HID-KB + HID-Mouse + WebUSB | 5 (EP1–EP5) |
| 1 (kbd-only) | 0x0101 | HID-KB                            | 1 (EP4) |
| 2 (kbd+mouse) | 0x0102 | HID-KB + HID-Mouse                | 2 (EP4, EP5) |
| 3 (MIDI+CDC) | 0x0103 | CDC + MIDI                        | 4 (EP1–EP3, EP6) |
| 4 (CDC-only) | 0x0104 | CDC                                | 3 (EP1–EP3) |

Mode 3 (MIDI) is the most invasive — needs the ASF MIDI class driver linked in. **If that driver isn't available in the local ASF tree, we drop MIDI from F10's scope**, list it as a known limitation, and ship modes 0/1/2/4. Verify ASF availability before F10 starts.

### `bcdDevice` rotation

Rotating `bcdDevice` per mode is essential — Windows otherwise caches the descriptor by VID:PID and refuses to re-enumerate when the descriptor changes. macOS and Linux are tolerant.

### Descriptor build-time vs. runtime

ASF's descriptor system is largely compile-time. Two paths for F10:

- (i) **Multi-build**: ship `DC29.uf2`, `DC29-kbd.uf2`, etc. User flashes the one they want. Simple but no boot-time gesture.
- (ii) **Runtime mode**: pre-init reads buttons, picks descriptor pointer, calls `udc_start()`. Requires patching ASF's static descriptor tables to be runtime-selectable. **More invasive but matches the success criteria.**

**Decision: try (ii) first.** If ASF makes it impossibly painful, fall back to (i) and update F10's success criteria explicitly.

---

## 5. Burst-path sharing (F06 / F07 / F09)

F06 (HID burst) provides a primitive that F07 (vault fire) and F09 (TOTP fire) reuse. To avoid three implementations, define one path:

```c
// keys.h
void hid_burst(const uint8_t *pairs, uint16_t n_pairs);
```

`pairs` is a flat array of `(mod, key, mod, key, ...)`. The function iterates, calls `udi_hid_kbd_modifier_down/up` and `udi_hid_kbd_down/up` with the existing 10 ms inter-frame spacing, suppresses F03 haptic click for the duration, and returns when done.

**Order of implementation matters:**

1. F06 lands first, exposes `hid_burst()`.
2. F07's `vault_fire()` calls `hid_burst()` directly.
3. F09's `totp_fire()` builds the 6-digit pair array (one (mod=0, key=HID_0..9) entry per digit), calls `hid_burst()`.

This is the rationale for the F06 → F07 → F09 dependency chain in the README's pair structure.

### Concurrency

A burst is **non-reentrant**. Second calls during a running burst return an error that surfaces as the `'e'` decline event. Bridges have to serialize their burst requests.

---

## 6. Input state machine (F01 / F02)

> Full design lives in [F01-tap-count-long-press.md](features/F01-tap-count-long-press.md#design-proposal-review-before-code-lands). Cross-cutting items only:

- **Polling-based** (not ISR-driven). Polled from the main loop ~ 1 ms tick.
- **Per-button SM** with states: IDLE, PRESSED_WAITING, RELEASED_WAITING_TAPCOUNT, LONG_PRESS_FIRED, CONSUMED_BY_CHORD.
- **Fast path**: buttons without modifier mappings short-circuit to today's behavior (single-tap fires on press, no latency penalty).
- **Modifier table is RAM-only** for first cut (56 bytes). EEPROM persistence deferred.
- **Long-press fires on release**, abortable.
- **Chord window 80 ms**. Penalty applies only to buttons that participate in a chord mapping.
- **3-finger fumble = ignore third button.**

---

## 7. Persistence policy summary

| Feature | RAM only | EEPROM | Notes |
|---------|----------|--------|-------|
| F01 modifier table | ✅ | — | Bridges re-send on connect; deferred to a follow-up if needed. |
| F02 chord table    | ✅ | — | Same. |
| F03 haptic toggle  | ✅ | (default in flags byte) | EEPROM default-on; runtime toggle is RAM-only. |
| F04 patterns       | (in-flash, read-only) | — | Patterns are firmware constants. |
| F05 (Python only)  | n/a | n/a | No badge state. |
| F06 burst          | n/a | n/a | Stateless. |
| F07 vault          | — | ✅ | Persisted across power-cycle. |
| F08 Stay Awake     | (autonomous-end-time RAM) | — | Bridge owns timer; firmware autonomous-mode is RAM-only safety net. Last-used duration + LED mode persisted host-side in `~/.dc29/stay_awake.toml`. |
| F09 TOTP secret    | — | ✅ | Persisted across power-cycle. |
| F10 boot mode      | n/a | n/a | Selected by button gesture each plug-in; not persisted. |
| F11 WebUSB         | n/a | n/a | Pure descriptor + protocol re-use. |

---

## 8. `FIRMWARE_VERSION` versioning + migration

- Current value: `FIRMWARE_VERSION = 2`.
- **Single bump to 3** at the first commit that touches EEPROM layout (will be F07).
- The bump wipes EEPROM. Documented in F07's migration section.
- F08 and F09 land *after* F07 with no further bump — their EEPROM regions are already reserved by the layout in §3 above.
- All changes to EEPROM layout flow through this doc. Any feature that needs to extend EEPROM must update §3 and bump version.

If F07 ends up not needing EEPROM (e.g., we move vault to RAM-only too), the bump is deferred until the first feature that does — likely F09.

---

## 9. Open cross-cutting questions

> Tick a box for each question. Use **🔄 Modify** if you want a tweak rather than a clean approve/reject. Use the master tracker at [`REVIEW.md`](REVIEW.md) to see overall progress.

<a id="q1-eeprom-cap-policy"></a>
### Q1 — EEPROM-cap policy

Accept reduced vault (2 × 16 pairs) and reduced TOTP (1 slot, 4-char label) to avoid blowing the 260-byte EEPROM cap?

- [x ] ✅ Approve as proposed (accept reduced sizes)
- [ ] ❌ Reject — pick alternative (i) or (ii) from §3
- [ ] 🔄 Modify (see comments)

**Comments:**

**Reviewed by:** _ _   **Date:** _ _

---

<a id="q2-f10-midi-mode-scope"></a>
### Q2 — F10 MIDI mode scope

Keep MIDI mode contingent on ASF driver availability (drop only if ASF refuses), or drop now and ship 4 modes (default / kbd / kbd+mouse / cdc)?

- [ ] ✅ Approve as proposed (keep, drop only if ASF refuses)
- [x ] ❌ Drop now — vendor MIDI driver is not worth the complexity
- [ ] 🔄 Modify (see comments)

**Comments:**

**Reviewed by:** _ _   **Date:** _ _

---

<a id="q3-f10-implementation-path"></a>
### Q3 — F10 implementation path

Runtime descriptor selector (path ii) vs. multi-build (path i)?

- [x ] ✅ Approve as proposed (try runtime first; fall back to multi-build with documented criteria amendment)
- [ ] ❌ Reject — go straight to multi-build, ship multiple `.uf2` files
- [ ] 🔄 Modify (see comments)

**Comments:**

**Reviewed by:** _ _   **Date:** _ _

---

<a id="q4-lowercase-letter-namespace"></a>
### Q4 — Lowercase letter namespace

Use lowercase ASCII for new commands (`'m'`, `'b'`, `'k'`, `'p'`, `'h'`, `'v'`, `'j'`, `'o'`)?

- [x ] ✅ Approve as proposed
- [ ] ❌ Reject — use a sub-byte scheme like `0x01 0xFF <feature_id> <subcmd>`
- [ ] 🔄 Modify (see comments)

**Comments:**

**Reviewed by:** _ _   **Date:** _ _

---

<a id="q5-single-firmware-version-bump"></a>
### Q5 — Single FIRMWARE_VERSION bump for F07 + F09

Bump once (wipe EEPROM once, layout reserves space for both F07 and F09)?

- [x ] ✅ Approve as proposed (one bump, one wipe)
- [ ] ❌ Reject — two separate bumps, two wipes
- [ ] 🔄 Modify (see comments)

**Comments:**

**Reviewed by:** _ _   **Date:** _ _

---

<a id="q6-f03-default-on-under-bridge-takeover"></a>
### Q6 — F03 default-on when bridges have taken over LEDs

Click always fires after `send_keys()`, including when bridges have suppressed the takeover animation?

- [x ] ✅ Approve as proposed (always click)
- [ ] ❌ Reject — keep on-device click muted whenever firmware takeover-click fires; only click as a "gap-filler"
- [ ] 🔄 Modify (see comments)

**Comments:**

**Reviewed by:** _ _   **Date:** _ _

---

<a id="q7-f04-pattern-interruption"></a>
### Q7 — F04 pattern interruption

New pattern preempts running pattern (cancel + start fresh), vs. queue?

- [x ] ✅ Approve as proposed (preempt)
- [ ] ❌ Reject — queue patterns
- [ ] 🔄 Modify (see comments)

**Comments:**

**Reviewed by:** _ _   **Date:** _ _

---

<a id="q8-f08-jiggler-default-state"></a>
### Q8 — F08 jiggler default state ✅ resolved

~~**Original question:**~~ off-by-default at power-up vs. honor EEPROM bit.

**Resolution:** Resolved by the F08 Stay Awake redesign — there is no EEPROM bit. Stay Awake sessions are explicit user actions via TUI/CLI; never auto-start at boot. No further action needed.
