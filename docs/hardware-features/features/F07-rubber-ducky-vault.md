# F07 — Rubber-ducky vault (EEPROM keystroke macros)

> Status: **planned** · Risk: **medium** · Owner: firmware + bridges

## Goal

Store N multi-keystroke macros (longer than the 4-entry per-button keymap) in EEPROM so the badge can type pre-recorded passphrases / SSH keys / boilerplate sigfiles on demand without a host-side bridge.

## Security note

This is **not a secure secrets store** — the EEPROM is plaintext, the badge is unprotected, and anyone with physical access can dump the flash via UF2. Document loudly in user docs that vault entries should be treated like a password written on a sticky note. The intent is convenience for stage demos and ephemeral boilerplate, not real credential storage.

## Success criteria

- [ ] EEPROM layout extended with a vault region: 4 macros × 64 bytes/macro = 256 bytes. Stays under the 260-byte EEPROM cap.
- [ ] `FIRMWARE_VERSION` bumped — old EEPROM is wiped on first boot. Documented in this file's migration section.
- [ ] Protocol commands:
  - `0x01 'V' 'W' <slot> <len> <payload>` — write macro slot `0..3`, payload is a sequence of `(mod, key)` pairs.
  - `0x01 'V' 'F' <slot>` — fire macro slot.
  - `0x01 'V' 'C' <slot>` — clear macro slot (zero out).
  - `0x01 'V' 'L'` — list slots (returns over CDC: slot, length, first 8 bytes of each).
- [ ] Bridge command `dc29 vault write <slot> --text "..."` and `dc29 vault fire <slot>` for human-friendly use.
- [ ] Each vault slot can hold up to 64 keystrokes (32 `(mod, key)` pairs).
- [ ] Firing uses the F06 burst path internally — must depend on F06 being signed off.
- [ ] List command never echoes payload bytes beyond the first 8 (privacy minor — discourages casual screen-shoulder leakage).
- [ ] Confirm/decline beep (F04) on write success / write failure if F04 is shipped.

## Test plan

1. **Pre-req**: F06 signed-off.
2. **EEPROM migration**: confirm `dc29 diagnose` shows the bumped firmware version and that an existing keymap is wiped (or migrated, if we choose to migrate). Document chosen behavior.
3. **Write + fire**:
   - `dc29 vault write 0 --text "hello world"`.
   - Open a focused text field. `dc29 vault fire 0`. Confirm "hello world" appears.
4. **All 4 slots**: write distinct payloads to slots 0–3. Fire each. Verify each.
5. **List**: `dc29 vault list`. Confirm 4 slots reported with correct lengths and truncated previews.
6. **Clear**: `dc29 vault clear 2`. Fire slot 2. Confirm nothing is typed.
7. **Power-cycle persistence**: write slots, unplug, replug. Fire. Macros survive.
8. **Length boundary**: write a 64-keystroke macro. Fire. Verify all 64 chars.
9. **Over-length reject**: write a 65-keystroke macro. Confirm firmware rejects with a decline beep / error response on CDC.
10. **Tap-to-fire integration** (optional cherry-on-top): map B1 long-press (F01) to fire vault slot 0. Hold B1 ≥ 500 ms. Confirm payload fires.

## Migration

EEPROM layout change:

| Offset (decimal) | Size | Field                    |
|------------------|------|--------------------------|
| existing 0..N    | N    | existing keymap fields   |
| (next free)      | 1    | vault_slot0_len          |
| ...              | 64   | vault_slot0_payload      |
| ...              | 1    | vault_slot1_len          |
| ...              | 64   | vault_slot1_payload      |
| ...              | 1+64 | vault_slot2              |
| ...              | 1+64 | vault_slot3              |

Total added: 4 × 65 = 260 bytes — at the EEPROM cap. If the keymap region pushes us over, we cut vault to 3 slots × 64 bytes = 195 bytes. Final layout decided at implementation time and recorded in this file.

## Design proposal (review before code lands)

> Cross-cutting decisions live in [`DESIGN.md`](../DESIGN.md). F07 owns the **single FIRMWARE_VERSION bump** for this batch (see [DESIGN.md §3](../DESIGN.md#3-eeprom-layout--single-bump-strategy) and [§8](../DESIGN.md#8-firmware_version-versioning--migration)). EEPROM layout is reserved up front for F09 too, so F09 can land later without a second wipe.

### Reduced sizing (vs. original spec)

The original spec called for **4 slots × 32 (mod, key) pairs**. Per the EEPROM layout in DESIGN.md §3, the 260-byte cap forces us to **2 slots × 16 pairs (32 bytes payload + 1 length byte each)**. This is the open question #1 in DESIGN.md — flag if you want a different trade.

Each slot holds up to 16 (mod, key) pairs = 16 keystrokes including modifier presses. For plain ASCII, that's ~32 typed characters (each char is press-down + release = effectively two HID frames internally, but counts as one pair in the vault format).

### Protocol commands (final)

Per [DESIGN.md §1](../DESIGN.md#1-protocol-command-letter-allocation):

```
0x01 'v' 'W' <slot:0-1> <len:1-16> <pair1_mod> <pair1_key> ... <pairN_mod> <pairN_key>
0x01 'v' 'F' <slot:0-1>
0x01 'v' 'C' <slot:0-1>
0x01 'v' 'L'                       # list -> replies via 0x01 'b' 'V' <slot> <len>
```

### EEPROM layout (final, copied from DESIGN.md §3)

| Offset | Size | Field |
|--------|------|-------|
| 167    | 1    | vault_slot0_len  |
| 168–199 | 32  | vault_slot0_payload |
| 200    | 1    | vault_slot1_len |
| 201–232 | 32  | vault_slot1_payload |

Slot count: 2. Per-slot capacity: 16 (mod, key) pairs.

### Fire path

`vault_fire(slot)` → reads EEPROM into a local 32-byte buffer → calls `hid_burst(buffer, len)` from F06. **F07 hard-depends on F06 having shipped.**

### Bridge integration

```bash
dc29 vault write 0 --text "hello world"
dc29 vault write 0 --pairs "00:hid_h,00:hid_e,..."   # raw form for advanced users
dc29 vault fire 0
dc29 vault list
dc29 vault clear 1
```

`--text` does the ASCII-to-HID conversion host-side and packs into the (mod, key) format.

### List-command privacy

`vault list` returns slot, length, and the **first 8 bytes** of each payload (~4 keystrokes preview). Never the full payload. Matches F09's TOTP list policy.

### Migration impact

`FIRMWARE_VERSION` 2 → 3. **All EEPROM is wiped**, including:
- LED resting + pressed colors → revert to firmware defaults
- Brightness → default
- Keymap → default (Teams hotkey on B4)

Document loudly in user-facing release notes.

### Files touched

**Modified:**
- `main.h` — `FIRMWARE_VERSION` 2 → 3, new `EEP_VAULT_*` constants, new `EEP_FLAGS_BYTE`, shrink `EEP_KEY_MAP` size
- `keys.c` — `vault_write`, `vault_fire`, `vault_clear`, `vault_list_preview`
- `serialconsole.c` — `'v'` parser branch with sub-commands
- `dc29/protocol.py` — `vault_*` helpers + `--text` packer
- `dc29/cli.py` — `dc29 vault` subcommand group

### Open questions

<a id="f07-q1-reduced-sizing"></a>
#### Q1 — Reduced sizing ✅ resolved

**Resolution:** Vault is **2 slots × 16 (mod, key) pairs**. Per [DESIGN.md Q1](../DESIGN.md#q1-eeprom-cap-policy--resolved) (2026-05-09).

---

<a id="f07-q2-wipe-vs-migrate"></a>
#### Q2 — Wipe vs. migrate EEPROM

Wipe all EEPROM on FIRMWARE_VERSION bump (per locked README policy), vs. one-shot migration preserving keymap + LED colors?

- [ ] ✅ Approve as proposed (wipe)
- [ ] ❌ Reject — write the migration
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
- [ ] FIRMWARE_VERSION bump verified — fresh boot wipes EEPROM cleanly
- [ ] Manual hardware test passed (all items in Test plan above)
- [ ] Implementation notes filled in
- [ ] Testing notes filled in

**Implementation reviewed by:** _ _   **Date:** _ _

### Final sign-off

- [ ] Feature accepted

**Final approved by:** _ _   **Date:** _ _   **Verdict:** _ _
