# F06 — Hyper-fast HID burst

> Status: **planned** · Risk: **low** · Owner: firmware

## Goal

Add a protocol command that fires a sequence of HID reports back-to-back at the maximum rate the USB stack will accept — useful for stress-testing macro receivers, replay-defense detection, and as a building block for F07 (rubber-ducky vault).

## Success criteria

- [ ] Protocol command `0x01 'H' <n_le16> <mod1> <key1> <mod2> <key2> ...` where:
  - `<n_le16>` is a little-endian 16-bit count of `(mod, key)` pairs to follow.
  - Pairs follow the same encoding as the existing keymap byte format.
- [ ] Maximum burst length: 256 pairs per command (sized to fit in one read of the CDC RX buffer; document the hard cap in `protocol.py`).
- [ ] Burst fires at the badge's HID polling rate (1 ms intervals on full-speed USB) — i.e., 256 keystrokes in ~512 ms (press + release per char).
- [ ] No keystroke drop or order-swap under steady-state. Verified by typing into a buffer-and-diff target.
- [ ] Burst is **synchronous** — the firmware blocks new commands until the burst completes, but the main loop is *not* blocked (LED ticks, button reads keep going).
- [ ] Cancellable via `0x01 'H' 0x00 0x00` (zero-length burst).
- [ ] No interaction with F03 click — clicks are suppressed during a burst (would be unbearable at 1 kHz).

## Test plan

1. **Build + flash + regression**.
2. **Tiny burst**: fire `0x01 'H' 5 hello` to type "hello" into a focused text field. Confirm correct output.
3. **Full burst**: fire 256 chars (mix of letters + symbols). Diff received text vs sent. Should be byte-identical.
4. **Order**: send a sequence with monotonic counter (e.g., "0123456789" repeated). Confirm output is monotonic.
5. **Throughput**: time the 256-char burst end-to-end. Should be ≤ 600 ms (safety margin around the 512 ms ideal).
6. **Cancel**: fire a long burst, immediately fire the zero-length cancel. Confirm output stops within ~5 ms.
7. **Concurrent input**: while burst is running, press B1. Confirm the button event is queued and fires *after* the burst (no interleave that would corrupt receiving applications).
8. **LED concurrency**: while burst is running, send `0x01 'M'`. Confirm LED 4 turns red without dropping any burst chars.

## Design proposal (review before code lands)

> Cross-cutting decisions live in [`DESIGN.md`](../DESIGN.md). F06 is the foundational primitive that F07 (vault) and F09 (TOTP) reuse — see [DESIGN.md §5](../DESIGN.md#5-burst-path-sharing-f06--f07--f09).

### Protocol letter (final)

Per [DESIGN.md §1](../DESIGN.md#1-protocol-command-letter-allocation):

```
0x01 'h' <n_le16:2> <mod1> <key1> ... <modN> <keyN>
```

`n_le16 == 0` → cancel any in-progress burst.

### Public C entrypoint (used by F07, F09)

```c
// keys.h
typedef enum {
    BURST_OK = 0,
    BURST_BUSY,            // already running
    BURST_TOO_LONG,        // n > MAX_BURST_PAIRS
} burst_result_t;

burst_result_t hid_burst(const uint8_t *pairs, uint16_t n_pairs);
```

`pairs` is a flat array of `mod, key, mod, key, ...`. The burst is **synchronous from the caller's perspective** but the main loop continues to tick (LED state updates, button polling). Implementation: walks the array, for each pair calls `udi_hid_kbd_modifier_down/up` + `udi_hid_kbd_down/up` with the existing 10 ms inter-frame guard.

### Concurrency policy

Per [DESIGN.md §5](../DESIGN.md#5-burst-path-sharing-f06--f07--f09): non-reentrant. A second `hid_burst()` call while one is running returns `BURST_BUSY`, which surfaces as a `0x01 'e' 'h' 'B'` decline event over CDC and a F03 decline-pattern beep (if F04 shipped).

### MAX_BURST_PAIRS = 256

Sized to fit one read of the CDC RX buffer. Document in `keys.h`. Larger payloads (vault macros, TOTP) decompose into chunks that fit.

### Suppress F03 click during burst

Per [DESIGN.md §2](../DESIGN.md#2-buzzer-arbitration), F03 haptic clicks are suppressed when buzzer_owner != BZO_IDLE / BZO_HAPTIC_CLICK. The burst path doesn't take buzzer ownership — instead, it sets a `burst_in_progress` flag that F03 checks before firing. Cleaner separation of concerns.

### Files touched

**New:**
- (none — `keys.c` adds the entrypoint inline)

**Modified:**
- `keys.h` — `hid_burst()` declaration, `burst_result_t`, `MAX_BURST_PAIRS`
- `keys.c` — `hid_burst()` implementation
- `serialconsole.c` — `'h'` parser branch (length-prefixed)
- `dc29/protocol.py` — `hid_burst(pairs)` helper that splits >256-pair payloads automatically

**Estimated flash impact:** ~250 bytes.

### Open questions

<a id="f06-q1-cancel-semantics"></a>
#### Q1 — Cancel semantics

Zero-length `n_le16 == 0` cancels an in-progress burst (proposed)?

- [ ] ✅ Approve as proposed (zero-length cancel)
- [ ] ❌ Reject — use a dedicated cancel sub-command
- [ ] 🔄 Modify (see comments)

**Comments:**

**Reviewed by:** _ _   **Date:** _ _

---

<a id="f06-q2-bursts-during-meetings"></a>
#### Q2 — Bursts during Teams meetings

Fire bursts regardless of meeting state (proposed) — bursts are user-initiated; Teams LED is independent?

- [ ] ✅ Approve as proposed (fire regardless)
- [ ] ❌ Reject — yield (skip burst) during meetings
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
