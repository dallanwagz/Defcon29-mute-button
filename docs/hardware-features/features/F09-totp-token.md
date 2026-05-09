# F09 — TOTP token (HMAC-SHA1 + RTC)

> Status: **planned** · Risk: **medium** · Owner: firmware + bridges

## Goal

Implement RFC 6238 TOTP entirely in firmware: store base32-encoded secrets in EEPROM, sync wall-clock from the host, and on a button gesture, type the current 6-digit code as keyboard HID input. Tap-to-OTP poor-man's Yubikey.

## Security note

Same caveat as F07: EEPROM is plaintext. Anyone with physical access can dump secrets via UF2. Document explicitly. Not a replacement for a real hardware token; useful for low-stakes shared accounts and demos.

## Success criteria

- [ ] HMAC-SHA1 + base32 decoder + 30-second TOTP window implemented in firmware. Code size budget ≤ 4 KB.
- [ ] EEPROM stores up to 2 secrets × 20 bytes (raw key after base32 decode) + 16-byte label per slot. Total ≤ 72 bytes added to EEPROM.
- [ ] `FIRMWARE_VERSION` bumped if EEPROM layout changes.
- [ ] Protocol commands:
  - `0x01 'O' 'W' <slot> <label_16> <key_20>` — write secret (raw bytes).
  - `0x01 'O' 'T' <unix_le32>` — set wall-clock (seconds since epoch UTC).
  - `0x01 'O' 'F' <slot>` — fire: types current 6-digit code at the focused field.
  - `0x01 'O' 'L'` — list: returns slot, label, last-used-time. **Never returns the key bytes.**
- [ ] Bridge command `dc29 totp provision <slot> --label X --secret BASE32SECRET` — handles base32 decode host-side, sends raw bytes to badge.
- [ ] Bridge command `dc29 totp fire <slot>` — sends time-sync (using host clock) immediately followed by fire command, so the badge always types using a recently-synced clock.
- [ ] Codes match `oathtool` reference output for the same secret + timestamp. Tested as a CI / unit test (golden vector).
- [ ] LED feedback: brief green flash on LED 4 when typed. Yields to Teams during meetings.

## Test plan

1. **Pre-req**: F06 signed-off (we use the burst path to type the code atomically).
2. **Crypto golden vectors**:
   - RFC 6238 Appendix B test vectors: secret `12345678901234567890` (ASCII) → known codes at known timestamps. Verify firmware produces the same 6-digit codes.
   - Run `python -m dc29.totp_test` (host-side calculator that exercises the same vectors and lets us diff).
3. **Real provisioning**:
   - Generate a base32 secret.
   - `dc29 totp provision 0 --label github --secret JBSWY3DPEHPK3PXP` (example).
   - Confirm `dc29 totp list` shows `slot=0 label=github`.
   - Add the same secret to a TOTP app (Authy, Google Authenticator).
4. **Fire**:
   - Open a focused text field.
   - `dc29 totp fire 0`.
   - Confirm the typed 6-digit code matches the Authy app's current code.
5. **30-second window**: fire, wait 31 s, fire again. The two codes must differ.
6. **Time drift**: skew host clock by +60 s, fire. Code should now match what Authy shows for "now + 60 s" — proving badge uses the synced timestamp.
7. **List privacy**: `dc29 totp list`. Confirm output never contains the raw secret.
8. **Power-cycle**: provision, unplug, replug, sync, fire. Code still valid.
9. **Two slots**: provision slot 0 = github, slot 1 = aws. Fire each. Codes match each provider.

## Risks

- **Crypto correctness**: HMAC-SHA1 is small but easy to get wrong. Mitigation: golden-vector test; build a host-side reference and diff every test secret.
- **RTC accuracy**: SAMD21 RTC drifts; documenting that the bridge re-syncs on every `fire` command means we never trust the badge clock for more than the 30-second window.

## Design proposal (review before code lands)

> Cross-cutting decisions live in [`DESIGN.md`](../DESIGN.md). F09 reuses F06's burst path and the EEPROM region pre-reserved by F07 — **no second `FIRMWARE_VERSION` bump**.

### Reduced sizing (vs. original spec)

Original spec: 2 slots × 20-byte key × 16-byte label. Per [DESIGN.md §3](../DESIGN.md#3-eeprom-layout--single-bump-strategy), the 260-byte cap forces us to **1 slot × 20-byte key × 4-char label**. This is the open question #1 in DESIGN.md.

For the typical user — one important account they'd want a hardware-typed TOTP for — one slot is fine. If you need more, that's option (i) or (ii) from DESIGN.md §3.

### Protocol commands (final)

Per [DESIGN.md §1](../DESIGN.md#1-protocol-command-letter-allocation):

```
0x01 'o' 'W' <slot:0> <label_4:4-bytes> <key_20:20-bytes>   # provision
0x01 'o' 'T' <unix_le32:4>                                  # time-sync (UTC seconds)
0x01 'o' 'F' <slot:0>                                       # fire 6-digit code
0x01 'o' 'L'                                                # list -> reply 0x01 'b' 'O' <slot> <label_4>
```

Bridge always sends `'T'` immediately before `'F'` — the badge clock is treated as a write-once-per-fire scratch register. Eliminates RTC drift concerns.

### Crypto budget

| Component | Estimated bytes |
|-----------|-----------------|
| HMAC-SHA1 (block size 64, 5 × 32-bit state) | ~1.2 KB |
| Base32 decoder (host-side; firmware just stores raw 20-byte key) | 0 (host) |
| TOTP wrapper (counter from time, modulus, decimal extract) | ~200 |
| Protocol + bridge stitching | ~150 |

Total firmware impact: **~1.5 KB**. Comfortable in the ~9 KB headroom.

### Fire path

```c
void totp_fire(uint8_t slot) {
    uint8_t code[6];
    rfc6238(eep_read_key(slot), wall_clock_unix, code);  // ASCII '0'..'9'
    uint8_t pairs[12];
    for (int i = 0; i < 6; i++) {
        pairs[i*2 + 0] = 0;             // no modifier
        pairs[i*2 + 1] = ascii_to_hid(code[i]);
    }
    hid_burst(pairs, 6);                 // F06 path
    led_pulse(LED4_GREEN, 150);          // visual confirm (yields to Teams)
}
```

**Hard depends on F06 having shipped.**

### Wall-clock storage

`uint32_t totp_wall_clock_unix` lives in BSS (RAM-only). Set via `'T'`. Stale by next power-cycle. The bridge always re-syncs before fire, so this is fine.

### Test vector verification

Add `dc29/totp_test.py` with the RFC 6238 Appendix B vectors:

```python
def test_rfc6238_vectors():
    secret = b"12345678901234567890"  # 20 ASCII bytes
    cases = [
        (59,          "94287082"),
        (1111111109,  "07081804"),
        (1234567890,  "89005924"),
    ]
    # Note: RFC 6238 appendix uses 8-digit codes; firmware uses 6-digit (truncate to 6).
```

Bridge ships with a host-side reference TOTP implementation that we diff the firmware's output against. Golden-vector mismatch fails the test loudly.

### List-command privacy

`vault list`-style: returns slot, label, **never the key bytes**. Matches F07.

### Files touched

**Modified:**
- `main.h` — `EEP_TOTP_*` constants (already reserved by F07's bump)
- New file `Firmware/Source/DC29/src/totp.c/.h` — HMAC-SHA1 + RFC 6238 (~400 LOC)
- `keys.c` — `totp_fire()` calls `hid_burst()`
- `serialconsole.c` — `'o'` parser branch
- `dc29/protocol.py` — `totp_provision`, `totp_fire`, `totp_list`, time-sync helpers
- `dc29/cli.py` — `dc29 totp` subcommand group
- `dc29/totp_test.py` — golden-vector test harness

### Open questions

<a id="f09-q1-one-slot-only"></a>
#### Q1 — One TOTP slot only ✅ resolved

**Resolution:** **1 slot × 20-byte key × 4-char label.** Per [DESIGN.md Q1](../DESIGN.md#q1-eeprom-cap-policy--resolved) (2026-05-09).

---

<a id="f09-q2-digit-count"></a>
#### Q2 — TOTP digit count

6 digits (proposed, matches consumer 2FA apps) vs. 8 digits (RFC 6238 default test vectors)?

- [ ] ✅ Approve as proposed (6 digits)
- [ ] ❌ Reject — 8 digits
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
- [ ] RFC 6238 golden vectors match (host-side test diff)
- [ ] Manual hardware test passed (provision + fire + Authy diff)

**Implementation reviewed by:** _ _   **Date:** _ _

### Final sign-off

- [ ] Feature accepted

**Final approved by:** _ _   **Date:** _ _   **Verdict:** _ _
