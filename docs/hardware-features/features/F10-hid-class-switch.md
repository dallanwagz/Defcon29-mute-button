# F10 — HID class switch at plug-in

> Status: **hardware-verified end-to-end on macOS** (single-button-hold variant; Mode 2 reserved/not implemented) · Risk: **high** · Owner: firmware

## Goal

At boot, before USB enumeration, sample the button matrix to choose which composite descriptor set to expose to the host:

| Held button at plug-in | Enumerated interfaces                  |
|------------------------|----------------------------------------|
| (none, default)        | HID-Keyboard + HID-Mouse + CDC         |
| B1                     | HID-Keyboard only                      |
| B2                     | HID-Keyboard + HID-Mouse               |
| B1+B4 (chord at boot)  | CDC only (debug / lockdown machines)   |

Useful on locked-down corporate hosts that refuse to enumerate composite devices.

> MIDI mode was previously planned. **Dropped** per [DESIGN.md Q2](../DESIGN.md#q2-f10-midi-mode-scope--resolved-drop-midi) (2026-05-09) — vendoring the ASF MIDI driver isn't worth the complexity for this batch.

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
5. **Mode 3 — CDC only**: hold B1+B4 chord at plug-in (avoids the B4-alone bootloader trigger). Confirm LEDs 1+4 flash white; only CDC enumerates (no HID interfaces visible to the host).
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
| 3    | B1+B4 chord at boot    | 0x0103    | CDC | 3 |

### Why Mode 3 is a chord at boot

Holding B4 alone triggers the **bootloader DFU mode** (current behavior, must not be touched per CLAUDE.md). To address reaching CDC-only mode, we use **B1+B4 chord** — both must be held when USB enumerates. The bootloader-DFU path is unaffected because it triggers before our descriptor-mode logic runs.

### Path: runtime descriptor selector (path ii from DESIGN.md §4)

```c
// usb_descriptors.c (NEW)
typedef enum { MODE_DEFAULT = 0, MODE_KBD, MODE_KBD_MOUSE, MODE_CDC_ONLY } usb_mode_t;

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

**Estimated flash impact:** ~1.8 KB (4 descriptor tables + boot logic). Comfortable in the ~9 KB headroom.

### Open questions

<a id="f10-q1-path-runtime-vs-multibuild"></a>
#### Q1 — Implementation path ✅ resolved

**Resolution:** Runtime descriptor selector first, fall back to multi-build with criteria amendment if it proves intractable. Per [DESIGN.md Q3](../DESIGN.md#q3-f10-implementation-path--resolved) (2026-05-09).

---

<a id="f10-q2-midi-scope"></a>
#### Q2 — MIDI mode scope ✅ resolved (dropped)

**Resolution:** MIDI mode dropped from F10 entirely. Ship 4 modes (default / kbd / kbd+mouse / cdc-only). Per [DESIGN.md Q2](../DESIGN.md#q2-f10-midi-mode-scope--resolved-drop-midi) (2026-05-09).

---

<a id="f10-q3-mode-4-chord"></a>
#### Q3 — Mode 3 (CDC-only) chord button assignment

CDC-only mode triggered by B1+B4 chord at boot (avoids B4-alone bootloader conflict)?

- [x] ✅ Approve as proposed (B1+B4 chord)
- [ ] ❌ Reject — pick different button(s) (specify in comments)
- [ ] 🔄 Modify (see comments)

**Comments:**

**Reviewed by:** dallan (default-accepted)   **Date:** 2026-05-09

---

<a id="f10-q4-persistent-mode-override"></a>
#### Q4 — Persistent mode override

Out of scope for v1 — every plug-in decides freshly. Add `dc29 mode set <X>` follow-up later?

- [x] ✅ Approve as proposed (defer to follow-up)
- [ ] ❌ Reject — include persistent override in F10
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

- [x] Code complete (`Firmware/Source/DC29/src/usb_modes.{c,h}` + main.c boot-time integration)
- [x] Build passes (≤ 56 KB) — text 52280 → 52772 B (+492 B)
- [x] Bootloader recovery still works — verified post-flash 2026-05-10: B4-alone hold mounts the DC29Badge drive; the final test re-flash itself was a recovery cycle.
- [x] All declared modes enumerate cleanly on macOS — Default (CDC + HID-Kbd, vault list returns both slots), KBD-only (no CDC, B2 still produces system-mute media key, vault list correctly fails with "no badge serial port"), CDC-only (CDC works, HID gone), mode resets per power-cycle.
- [ ] Cross-platform test passed where applicable (Windows / Linux) — **not run**, but bcdDevice rotation is in place per spec, so Windows should re-enumerate fresh on first plug-in per mode.

**F10 deviations from original spec (recorded here):**
- **Single-button holds** (B1 / B2 / B3) instead of the spec's B1+B4 chord for Mode 3.  Cleaner UX since B4 is reserved for DFU and we have an unused middle button anyway.  Per user redesign 2026-05-10.
- **Mode 2 (HID-Kbd + HID-Mouse) is reserved, not implemented.**  Triggered by B2 hold but currently falls back to default mode (LED 2 still flashes so the user knows B2 was sampled).  We never built an HID-Mouse interface — F08 used the keyboard-wake-pulse fallback specifically to avoid the descriptor surgery.  Adding HID-Mouse later would slot cleanly into B2 without further mode-selection work.
- **No `dc29 mode` CLI** — out of scope; the active mode is implicit (which interfaces enumerate).  Could be added later by parsing `system_profiler` output.
- **Persistent mode override** explicitly out of scope per F10 Q4 default-accept.

**Implementation notes:**
- `udi_composite_desc.c` (vendored ASF file) is left untouched.  Default mode uses its descriptor exactly as before.
- Alt-mode descriptors are hand-rolled in `usb_modes.c` as packed structs — KBD-only descriptor sets `bInterfaceNumber = 0` directly (the default `UDI_HID_KBD_DESC` macro bakes interface number 2 in via `UDI_HID_KBD_IFACE_NUMBER`, which is compile-time, so we built a parallel descriptor instead of fighting the macro).
- CDC-only mode reuses the existing `UDI_CDC_*_DESC_0` macros since CDC was already at interface 0+1; we just drop the HID-Kbd block and shrink `wTotalLength` + `bNumInterfaces`.
- `udc_config.confdev_lsfs` and `udc_config.conf_lsfs` are written at runtime in `usb_install_mode()` before `udc_start()`.  ASF tolerates this because `udc_config` itself is in RAM (only the const descriptor data is in flash).
- 3-sample debounce at boot: ~10 ms / ~30 ms / ~50 ms.  All three samples must agree before committing to a non-default mode; bounce defaults to safe (mode 0).

**Implementation reviewed by:** _ _   **Date:** _ _

### Final sign-off

- [ ] Feature accepted

**Final approved by:** _ _   **Date:** _ _   **Verdict:** _ _
