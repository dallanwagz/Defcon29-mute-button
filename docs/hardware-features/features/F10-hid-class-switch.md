# F10 — HID class switch at plug-in

> Status: **planned** · Risk: **high** · Owner: firmware

## Goal

At boot, before USB enumeration, sample the button matrix to choose which composite descriptor set to expose to the host:

| Held button at plug-in | Enumerated interfaces                  |
|------------------------|----------------------------------------|
| (none, default)        | HID-Keyboard + HID-Mouse + CDC         |
| B1                     | HID-Keyboard only                      |
| B2                     | HID-Keyboard + HID-Mouse               |
| B3                     | MIDI + CDC                             |
| B4                     | CDC only (debug / lockdown machines)   |

Useful on locked-down corporate hosts that refuse to enumerate composite devices, or on audio rigs that want pure MIDI.

## Why this is the highest firmware risk

The descriptor selection happens *before* USB init, before the main loop runs. Mistakes brick enumeration and force a bootloader-mode reflash to recover.

## Success criteria

- [ ] At-boot button sample completes within 50 ms of power-up. No false positives from button bounce on cold start.
- [ ] All five descriptor variants enumerate cleanly on macOS + Windows + Linux (Linux verified via `lsusb -v`).
- [ ] LED feedback: at boot, the LED corresponding to the held button flashes white twice to confirm the chosen mode. Default mode flashes LED 1.
- [ ] Selection survives only the current power cycle. Unplug + plug-in with no button held → defaults to mode 0.
- [ ] No regression to F08 mouse jiggler (mode 0 includes it). No regression to keyboard macros in any mode that includes HID-Keyboard.
- [ ] Recovery path documented: any mode is bootloader-recoverable via the standard "hold B4 + plug in" trick (B4 here means the bootloader trigger, which must remain unconditional and run before our mode-selection logic).
- [ ] Build still fits in 56 KB even with multiple descriptor sets.

## Test plan

1. **Bootloader still works** (highest priority — failing this means brick risk):
   - Hold B4 + plug in. Confirm DC29 mass-storage drive mounts. Release B4.
   - This must always work, regardless of mode-selection logic.
2. **Default mode**: plug in with no buttons held. Confirm LED 1 flashes 2x white. Verify keyboard + mouse + CDC enumerate (`system_profiler SPUSBDataType`).
3. **Mode 1 — keyboard only**: hold B1, plug in. Confirm LED 1 flashes; keyboard works; no mouse interface; no CDC. (CDC absence = `dc29 diagnose` fails to find the badge — expected.)
4. **Mode 2 — keyboard + mouse**: hold B2, plug in. Confirm LED 2 flashes; both HID interfaces enumerate; no CDC.
5. **Mode 3 — MIDI + CDC**: hold B3, plug in. Confirm LED 3 flashes; badge enumerates as MIDI device (visible in Audio MIDI Setup); CDC works.
6. **Mode 4 — CDC only**: hold B4 momentarily after bootloader window. (Caveat: B4 also triggers bootloader — needs careful timing or a different button assignment.) Confirm LED 4 flashes; only CDC enumerates.
7. **Cross-platform**:
   - macOS (already covered above).
   - Windows: Device Manager shows the expected interfaces in each mode.
   - Linux: `lsusb -v` matches descriptor expectations.
8. **Recovery**: in any mode, hold B4 + plug in. Drive mounts. Re-flash via UF2. Mode selection logic continues to work.

## Risks + mitigations

| Risk | Mitigation |
|------|-----------|
| B4 conflicts with bootloader trigger | Move CDC-only mode to a **chord** at boot (e.g., B1+B4) so a single B4 hold reaches the bootloader before our logic runs. |
| Windows caches descriptor by VID:PID | Use a different `bcdDevice` per mode so Windows treats each as a distinct device. |
| Cold-start button bounce | Read button state at t=10 ms, t=30 ms, t=50 ms; require all three samples to agree. |
| Brick by failed enumeration | Bootloader path is untouched — recovery is always one UF2 drag away. |

## Design proposal (review before code lands)

> Cross-cutting decisions live in [`DESIGN.md`](../DESIGN.md). F10 is the **highest-risk firmware change** — it modifies the descriptor system itself and runs before the main loop.

### Modes (final, from DESIGN.md §4)

| Mode | Held button at plug-in | bcdDevice | Interfaces | Endpoints |
|------|------------------------|-----------|------------|-----------|
| 0    | (none, default)        | 0x0100    | CDC + HID-KB + HID-Mouse + WebUSB | 5 |
| 1    | B1                     | 0x0101    | HID-KB | 1 |
| 2    | B2                     | 0x0102    | HID-KB + HID-Mouse | 2 |
| 3    | B3                     | 0x0103    | CDC + MIDI | 4 |
| 4    | B1+B4 chord at boot    | 0x0104    | CDC | 3 |

### Why Mode 4 is a chord at boot

Holding B4 alone triggers the **bootloader DFU mode** (current behavior, must not be touched per CLAUDE.md). To address open-question on F10 about reaching CDC-only mode, we use **B1+B4 chord** — both must be held when USB enumerates. The bootloader-DFU path is unaffected because it triggers before our descriptor-mode logic runs.

### MIDI mode contingent on ASF

If `udi_midi.c/.h` is not in our local ASF tree, **Mode 3 is dropped** and we ship modes 0/1/2/4 only. This is per DESIGN.md open-question #2 — flag if you'd rather keep MIDI as a hard requirement (will require vendoring the driver, ~1.5 KB extra).

### Path: runtime descriptor selector (path ii from DESIGN.md §4)

```c
// usb_descriptors.c (NEW)
typedef enum { MODE_DEFAULT = 0, MODE_KBD, MODE_KBD_MOUSE, MODE_MIDI_CDC, MODE_CDC_ONLY } usb_mode_t;

extern const usb_descriptor_set_t USB_DESC_DEFAULT;
extern const usb_descriptor_set_t USB_DESC_KBD;
// etc.

usb_mode_t usb_select_mode_at_boot(void) {
    // 3-sample debounce on power-up:
    // sample at t=10ms, t=30ms, t=50ms; require all three to agree
    // returns MODE_DEFAULT if held buttons don't match any non-default mode
}

void usb_init_with_mode(usb_mode_t mode);   // called instead of udc_start()
```

ASF's static descriptor tables are patched to indirect through a runtime pointer set in `usb_init_with_mode()`. **The ASF patch is the riskiest sub-task.** If it proves intractable in <1 day of effort, fall back to multi-build (path i from DESIGN.md §4) and update F10's success criteria.

### LED feedback at boot

Per spec: the LED corresponding to the held button flashes white twice (~150 ms each, ~100 ms gap) immediately after mode selection. Default (mode 0) flashes LED 1.

### Cross-platform expectation

- **macOS**: enumerates fine in all modes (per ASF maturity).
- **Windows**: requires `bcdDevice` rotation (already planned). May need INF reload on first plug-in per mode.
- **Linux**: tolerant — `lsusb -v` should match expected interface count per mode.

### Bootloader-recovery invariant

The bootloader trigger (B4 alone, no firmware running) must remain unconditional. Our mode-selection logic runs **after** the bootloader has decided not to enter DFU. Untested-on-hardware risk: if we accidentally affect early boot behavior, recovery still works because the bootloader is in a separate flash region and reads B4 in its own startup code.

### Files touched

**New:**
- `usb_descriptors.c/.h` — descriptor sets per mode + boot-time selector

**Modified:**
- `config/conf_usb.h` — switch from compile-time interface count to runtime
- ASF (small patch) — descriptor tables become non-`const`, pointer indirection via setter
- `main.c` — call `usb_select_mode_at_boot()` + `usb_init_with_mode()` before main loop
- `dc29/cli.py` — add `dc29 mode` command that prints the active mode (parsed from descriptors via libusb / system_profiler)

**Estimated flash impact:** ~2.5 KB (multiple descriptor tables + boot logic). Possibly tight. If we exceed budget, drop Mode 3 (MIDI).

### Open questions

<a id="f10-q1-path-runtime-vs-multibuild"></a>
#### Q1 — Implementation path

Try runtime descriptor selector (path ii) first, fall back to multi-build (path i)?

> Cross-cuts to [DESIGN.md Q3](../DESIGN.md#q3-f10-implementation-path).

- [ ] ✅ Approve as proposed (runtime first)
- [ ] ❌ Reject — go straight to multi-build
- [ ] 🔄 Modify (see comments)

**Comments:**

**Reviewed by:** _ _   **Date:** _ _

---

<a id="f10-q2-midi-scope"></a>
#### Q2 — MIDI mode scope

Drop MIDI if ASF lacks driver (proposed)?

> Cross-cuts to [DESIGN.md Q2](../DESIGN.md#q2-f10-midi-mode-scope).

- [ ] ✅ Approve as proposed (drop if missing)
- [ ] ❌ Reject — vendor the driver to keep MIDI
- [ ] 🔄 Modify (see comments)

**Comments:**

**Reviewed by:** _ _   **Date:** _ _

---

<a id="f10-q3-mode-4-chord"></a>
#### Q3 — Mode 4 chord button assignment

CDC-only mode triggered by B1+B4 chord at boot (avoids B4-alone bootloader conflict)?

- [ ] ✅ Approve as proposed (B1+B4 chord)
- [ ] ❌ Reject — pick different button(s) (specify in comments)
- [ ] 🔄 Modify (see comments)

**Comments:**

**Reviewed by:** _ _   **Date:** _ _

---

<a id="f10-q4-persistent-mode-override"></a>
#### Q4 — Persistent mode override

Out of scope for v1 — every plug-in decides freshly. Add `dc29 mode set <X>` follow-up later?

- [ ] ✅ Approve as proposed (defer to follow-up)
- [ ] ❌ Reject — include persistent override in F10
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
- [ ] Build passes (≤ 56 KB) for all enabled modes
- [ ] Bootloader recovery still works (B4-alone hold mounts DFU drive)
- [ ] All declared modes enumerate cleanly on macOS
- [ ] Cross-platform test passed where applicable (Windows / Linux)

**Implementation reviewed by:** _ _   **Date:** _ _

### Final sign-off

- [ ] Feature accepted

**Final approved by:** _ _   **Date:** _ _   **Verdict:** _ _
