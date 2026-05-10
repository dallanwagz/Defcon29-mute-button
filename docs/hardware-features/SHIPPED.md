# Shipped — 11-feature batch wrap-up

> Companion to [`README.md`](README.md) and [`DESIGN.md`](DESIGN.md).
> Captures what actually shipped, what deviated from the original spec
> and why, what's still pending, and the artifact map for future
> debugging.

**Dates:** 2026-05-09 → 2026-05-10
**Branch landed on:** `main` (`myfork`, `dallanwagz/Defcon29-mute-button`)
**Final firmware size:** 52772 / 57344 B (3.4 KB headroom under the
56 KB cap), bss 6784 / 8192 B.
**EEPROM:** v3 layout (single bump for F07 + F09 combined; documented
in [DESIGN.md §3](DESIGN.md#3-eeprom-layout--single-bump-strategy)).

## What shipped

| F   | Feature                                                                          | Verification                                                                                                                                                                                  | Commit |
|-----|----------------------------------------------------------------------------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|--------|
| F01 | [Tap-count + long-press](features/F01-tap-count-long-press.md)                   | All four kinds confirmed via `tools/test_input_modifiers.py` (single fast-path, single slow-path, double, triple, long).                                                                       | `7baee62` + `3d6086d` |
| F02 | [Chords](features/F02-chords.md)                                                 | B1+B2 chord fired the EXT chord event.                                                                                                                                                         | `7baee62` + `3d6086d` |
| F03 | [Haptic confirmation](features/F03-haptic-confirmation.md)                       | Audible 1500 Hz / 15 ms click on every press in bridge-managed-LED mode (initial 4 kHz tuning was inaudible — buzzer cv formula `15625/freq` clamps cv ≤ 3 above 2 kHz).                       | `332d5a7` |
| F04 | [Beep signatures](features/F04-beep-signatures.md)                               | All 8 patterns audibly distinct; SILENCE cancels mid-pattern; pattern-preempts-pattern works; takeover-cancels-pattern works.  Implements DESIGN.md §2 buzzer arbitration via `buzzer_owner_t`. | `71886ab` |
| F05 | [Beat-doubler](features/F05-beat-doubler.md)                                     | KICK pulse audible via 8-pulse synthetic test at ~150 BPM.  Music-driven sync deferred (BlackHole + Multi-Output Device routing not producing audible playback during test window).             | `0cfa6fd` |
| F06 | [HID burst](features/F06-hid-burst.md)                                           | 256 distinct chars typed byte-perfect into TextEdit; mid-burst cancel works.  Per-frame guard tightened from 10 ms → 2 ms to match the HID-Kbd descriptor's `bInterval`.                        | `cc6931c` |
| F07 | [Rubber-ducky vault](features/F07-rubber-ducky-vault.md)                         | Write/list/fire/clear all confirmed; over-length write rejected; slots persisted across re-flash.  Bumped `FIRMWARE_VERSION` 2 → 3 (single bump for F07 + F09; DESIGN.md §3).                   | `0edc9a5` |
| F08a| [Stay Awake firmware](features/F08-mouse-jiggler.md)                             | Single pulse drops macOS `HIDIdleTime` 681 s → 0.52 s; 75 s autonomous mode keeps idle bounded < 31 s; cancel works.  Path-2-lite — keyboard-modifier wake pulse instead of HID-Mouse.          | `5e892d7` |
| F08b| [Stay Awake bridge + TUI + CLI](features/F08-mouse-jiggler.md)                   | CLI smoke + full TUI walkthrough (variant A from the mockups).                                                                                                                                  | `771dcae` + `f762e75` |
| F09 | [TOTP token](features/F09-totp-token.md)                                         | All 4 RFC 6238 Appendix B golden vectors typed byte-perfect (`287082 081804 005924 279037`).                                                                                                    | `0d59f75` |
| F10 | [HID class switch](features/F10-hid-class-switch.md)                             | Default + KBD-only (B1) + CDC-only (B3) + DFU recovery (B4).  Mode resets per power-cycle.                                                                                                      | `5de2960` |
| F11 | [Browser config UI](features/F11-webusb-config-ui.md)                            | End-to-end via Chrome on macOS: Connect → vault list/write/fire → LED color picker → beep auditioner → Stay Awake.  WebUSB descriptors reverted (auto-suggest UX wasn't worth firmware-↔-URL coupling). | `4dbc63b` + `a7a82e1` |

## Test artifacts (re-runnable)

| Tool | What it exercises |
|---|---|
| `tools/test_input_modifiers.py` | F01 + F02 — single/double/triple/long/chord events via CDC |
| `tools/test_haptic_click.py`    | F03 — 3-phase audible test (haptic-on / both-off / takeover-restored) |
| `tools/test_beep_patterns.py`   | F04 — 4-phase test (each pattern + SILENCE-cancel + pattern-preempt + takeover-cancel) |
| `tools/test_stay_awake.py`      | F08a — single-pulse + autonomous + mid-session cancel against macOS `HIDIdleTime` |
| `tools/test_hid_burst.py`       | F06 — 18-char + 256-char + cancel test into a focused text field |
| `dc29/totp_test.py`             | F09 — RFC 6238 host-side reference vs. firmware diff (`--firmware [PORT]` for live diff) |

CLI surface added by this batch:
`dc29 awake start/stop/status`, `dc29 vault write/fire/clear/list`,
`dc29 totp provision/fire/list`.

Web app: `https://dallanwagz.github.io/Defcon29-mute-button/`
(deployed by `.github/workflows/pages.yml` on every push to `main`
that touches `web/dc29-config/**`).

## Deviations from the original spec — and why

| Spec item | Deviation | Reason |
|---|---|---|
| F08a — HID-Mouse interface for real cursor jiggle | **Path-2-lite: no-op LeftShift modifier as the wake pulse.** macOS treats any HID input as user activity, so the host stays awake without any composite-descriptor surgery. | Adding HID-Mouse during the autonomous "while you're away" session would have risked breaking enumeration with no recovery path. Path 2 was explicitly endorsed as a fallback in the F08 spec. |
| F08a — `'I'` takes absolute UTC end-time via F09 time-sync | **Relative duration in seconds (LE32).** | F09 wasn't shipped yet at F08a time; sidestepped the dependency.  The bridge translates abs ↔ rel at its layer. |
| F08 — full path-1 (HID-Mouse + descriptor surgery) | Reserved as future work; B2 in the F10 mode picker is the natural slot for it. | See above. |
| F11 — WebUSB descriptors + auto-suggest URL | **WebUSB descriptors reverted; web app uses WebSerial only.** Stage 1 firmware code was implemented, flashed, and verified, then the BOS / MS-OS 2.0 descriptors were removed after we evaluated the trade-off (auto-suggest toast wasn't worth coupling firmware to a hardcoded landing URL). | The actual data path was always going to be WebSerial in our hybrid design; WebUSB only added the polish-grade auto-suggest.  The user navigates via bookmark instead. |
| F11 — vendor EP0 control-transfer command for raw protocol bytes | Not needed once we pivoted to WebSerial. | WebSerial talks to the existing CDC port directly. |
| F10 — Mode 3 trigger = B1+B4 chord at boot | **Single-button hold per mode (B1 / B2 / B3); B4 stays as DFU.** | User redesign — uses unused middle button instead of competing with the bootloader trigger. |
| F10 — Mode 2 (HID-Kbd + HID-Mouse) | **Reserved, not implemented.** B2 still flashes LED 2 so the user knows the sample landed; descriptor falls back to default. | We never built HID-Mouse (see F08 above).  Slot is wired for future work. |
| F07 — 4 vault slots × 32 (mod, key) pairs | **2 slots × 16 pairs.**  Locked in [DESIGN.md §3](DESIGN.md#3-eeprom-layout--single-bump-strategy). | EEPROM cap (260 B) is binding once you also reserve F09's TOTP slot. |
| F09 — 2 TOTP slots × 16-char label | **1 slot × 4-char label.**  Same EEPROM cap. | See above. |
| F06 — "256 chars in ~512 ms" (1 ms / frame, per HID poll) | **256 chars in ~2.6 s** (BURST_FRAME_MS = 2 + transmit-flag wait). | Going below 2 ms risks the host missing reports per the HID descriptor's `bInterval = 2`.  Reaching 1 ms requires changing `bInterval` itself (out of scope). |
| F11 — WebUSB success criteria checks (Chrome auto-suggest, etc.) | Replaced with WebSerial pair flow. | Per the architecture pivot. |

## Cross-cutting decisions that locked in mid-flight

- **DESIGN.md §2 buzzer arbitration** shipped exactly as designed — F03 / F04 / takeover share a single `buzzer_owner_t` enum with strict priority.  F05 is a Python bridge that drives F04, no firmware-side audio mixing needed.
- **DESIGN.md §3 single EEPROM bump** worked — F07 reserved F09's space when it bumped `FIRMWARE_VERSION` 2 → 3, so F09 added zero new EEPROM bytes and required no second wipe.
- **DESIGN.md §5 burst-path sharing** worked — F07 (`vault_fire`) and F09 (`totp_fire`) both call `hid_burst()` (F06) directly with no per-feature retry / locking on top.

## What's still pending

| Item | Status |
|---|---|
| F05 music-driven smoke test | Pending user-side: needs the macOS Sound output set to a Multi-Output Device that includes BlackHole.  Once that's working, `dc29 start --enable beat-buzzer` should just play. |
| F11 web — F01/F02 EXT event types in activity log | **Resolved by Tier 3.1** (web modifier-table editor lets the user register mappings without `tools/test_input_modifiers.py`).  End-to-end test still pending — see Tier 3 row below. |
| F11 web — Tier 3 ports (modifier-table editor, shareable URLs, macro recorder) | **Shipped, not yet tested on hardware.**  Code reviewed by eye, JS parsed cleanly, GH Pages deploy succeeded.  User test deferred 2026-05-10 (end of session).  Test plan in commit `5d1c3ed` message. |
| Cross-platform F10 testing (Windows / Linux) | Not run.  bcdDevice rotation is in place per spec, so Windows should re-enumerate fresh on first plug-in per mode — but this remains untested. |
| F10 Mode 2 (HID-Kbd + HID-Mouse) | Reserved.  Adding HID-Mouse is its own descriptor-surgery task; would also retroactively give F08 a path-1 option. |
| `dc29 mode` CLI | Out of scope for F10 v1.  Could be added later by parsing `system_profiler` output. |
| F10 persistent mode override (`dc29 mode set <X>`) | Out of scope per F10 Q4 default-accept.  Every plug-in decides freshly. |

## Lessons + things that almost bit us

- **`reply[12]` array silently dropped its 13th initializer** in the F07 vault-list reply (we initialized 13 elements in a 12-byte array, GCC dropped the last one without a default-on warning).  Surfaced because the slot-1 reply started mid-stream and corrupted parsing.  Caught when `dc29 vault list` returned only slot 0.  Worth remembering: array size vs. initializer count is a class of bug `-Wall` doesn't surface.
- **HID drops on identical-key rapid bursts**: macOS coalesces too-rapid identical key down/up events at the input layer.  Phase 3 of the F06 test (200 'X's in 200 ms) showed only 1 visible 'x'.  Phase 2 (256 *distinct* chars) was perfect.  Real F06 use cases (passphrases, TOTP codes, vault macros) use distinct keys, so this never matters in practice.
- **Initial F03 frequency was inaudible**: 4 kHz with the buzzer cv formula `15625/freq` yields cv ≈ 3, below the piezo's effective drive range.  Settled on 1500 Hz / 15 ms (matches the JOY personality click).
- **Textual buttons + Horizontal layout silently clip the last child's label** when no explicit `width:` is set.  Caught during F08b TUI walkthrough — the "Indefinite" / "Forever" button rendered as a hover-able blank box.  Fixed with `width: 11; min-width: 11;` on the row's buttons.
- **iOS Safari does not support Web Serial.** F11 web app loads on iOS but `Connect` throws.  Documented in the README.
- **Cwd persistence across Bash tool calls** caused a couple of "✗ no UF2" false alarms when an earlier `cd Firmware/Source/DC29` carried into a later `cp` with a relative path.  Always use absolute paths or `cd /Users/dallan/repo/Defcon29-mute-button &&` prefixes.

## Artifact map (for future me)

```
docs/hardware-features/
  README.md          — top-level tracker (status table updated)
  DESIGN.md          — cross-cutting decisions (unchanged)
  REVIEW.md          — design-review checklist (unchanged)
  SHIPPED.md         — this file
  features/F01..F11.md — per-feature spec + sign-off

Firmware/Source/DC29/src/
  input.{h,c}        — F01/F02 input state machine
  jiggler.{h,c}      — F08a-lite Stay Awake firmware
  totp.{h,c}         — F09 SHA-1 + HMAC-SHA1 + RFC 6238
  usb_modes.{h,c}    — F10 boot-time descriptor switch
  pwm.{h,c}          — F03/F04 buzzer arbitration + pattern engine
  keys.{h,c}         — F06 hid_burst, F07 vault_*
  serialconsole.c    — escape-byte parser (states 0..7) for all features
  main.c             — boot flow: usb_select_mode_at_boot → udc_start →
                       pwm_init → usb_mode_led_feedback → main loop with
                       input_tick + jiggler_tick + beep_pattern_tick +
                       hid_burst_tick

dc29/
  protocol.py        — all CMD_* + EVT_* + size constants
  badge.py           — BadgeAPI surface (keymap, vault, totp, awake, beep, hid_burst, …)
  awake.py           — F08b shared state singleton + JSON pointer/prefs
  bridges/
    stay_awake.py    — F08b bridge
    beat_buzzer.py   — F05 bridge
  tui/
    stay_awake_tab.py — F08b TUI tab (variant A)
    app.py           — tab registration, slot 9
  cli.py             — awake / vault / totp subcommand groups
  totp_test.py       — F09 host-side reference + RFC 6238 vectors

tools/
  test_input_modifiers.py
  test_haptic_click.py
  test_beep_patterns.py
  test_stay_awake.py
  test_hid_burst.py

web/dc29-config/
  index.html         — F11 vanilla-JS single-page web app
  protocol.js        — JS port of dc29/protocol.py constants + RX state machine

.github/workflows/
  pages.yml          — auto-deploy web/dc29-config to GitHub Pages
```
