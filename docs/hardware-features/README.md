# Hardware Feature Tracker

Source-of-truth tracker for the 11 hardware-layer features being added to expand the badge's "stream-deck-without-a-screen" feature surface. Each feature is defined upfront with **Goal**, **Success criteria**, and **Test plan**, and is updated with **Implementation notes** and **Testing notes** as work proceeds. The user gives manual sign-off at the end of each feature before the next one starts.

> 👉 **Reviewing the design? Start at [`REVIEW.md`](REVIEW.md)** — it's the single-page master checklist with clickable boxes that link into every open question.

## Cross-cutting design

Read [`DESIGN.md`](DESIGN.md) before any feature's code lands. It captures decisions that span multiple features so per-feature work doesn't stomp on each other:

- Protocol command-letter allocation (single source of truth)
- Buzzer arbitration (priority + ownership across F03/F04/F05/takeover/games)
- EEPROM layout — single bump for F07+F09 combined
- USB endpoints + descriptor strategy (F08/F10/F11)
- Burst-path sharing (F06/F07/F09)
- Input state machine (F01/F02)
- Persistence policy summary
- `FIRMWARE_VERSION` migration

## Conventions

- Each feature lives in [`features/F##-slug.md`](features/) and is self-contained.
- **Goal** = one-sentence outcome.
- **Success criteria** = checklist the feature must satisfy to be considered done.
- **Test plan** = manual + automated steps the user runs to verify the feature on real hardware.
- **Implementation notes** = what was actually changed and why; updated by Claude as code lands.
- **Testing notes** = what was actually run and what was observed; updated as we test.
- **Sign-off** = user's manual approval (date + verdict). Empty until reviewed.
- All firmware changes go in `Firmware/Source/DC29/src/`. All bridge changes go in `dc29/`. Protocol additions get an entry in `dc29/protocol.py`.

## Status

| ID  | Feature                                         | Status      | Risk   | Sign-off |
|-----|-------------------------------------------------|-------------|--------|----------|
| F01 | [Tap-count + long-press modifiers](features/F01-tap-count-long-press.md)         | **verified** | low    | 2026-05-09 |
| F02 | [Chord shortcuts](features/F02-chords.md)                                        | **verified** | low    | 2026-05-09 |
| F03 | [Haptic confirmation (buzzer)](features/F03-haptic-confirmation.md)              | **verified** | low    | 2026-05-09 |
| F04 | [Beep signatures per event](features/F04-beep-signatures.md)                     | **verified** | low    | 2026-05-09 |
| F05 | [Beat-doubler (audio→buzzer)](features/F05-beat-doubler.md)                      | **verified** (synthetic; music sync deferred — BlackHole routing) | low    | 2026-05-09 |
| F06 | [Hyper-fast HID burst](features/F06-hid-burst.md)                                | **verified** | low    | 2026-05-09 |
| F07 | [Rubber-ducky vault](features/F07-rubber-ducky-vault.md)                         | **verified** | medium | 2026-05-09 |
| F08 | [Stay Awake (Amphetamine-style jiggler + TUI)](features/F08-mouse-jiggler.md)    | **verified** (path-2-lite — keyboard wake instead of HID-Mouse; full TUI walkthrough done) | medium | 2026-05-10 |
| F09 | [TOTP token](features/F09-totp-token.md)                                         | **verified** (RFC 6238 Appendix B golden vectors all match byte-perfect) | medium | 2026-05-10 |
| F10 | [HID class switch at plug-in](features/F10-hid-class-switch.md)                  | **verified** (single-button-hold variant; Mode 2 reserved for future HID-Mouse) | high   | 2026-05-10 |
| F11 | [Browser config UI](features/F11-webusb-config-ui.md)                            | **verified** (WebSerial-only; WebUSB descriptors reverted) | high   | 2026-05-10 |

Status values: `planned` → `in-progress` → `built` → `flashed` → `verified` → `signed-off`.

**🎉 All 11 features verified end-to-end on hardware.** See [`SHIPPED.md`](SHIPPED.md) for the wrap-up summary, deviations from the original spec, and what's still pending.

## Decisions (locked-in 2026-05-09)

- **Sign-off cadence**: pairs of features per gate. Pair structure below.
- **Commit cadence**: one commit per feature on `main`.
- **EEPROM migration policy**: bumping `FIRMWARE_VERSION` wipes EEPROM. Documented loudly in any feature that bumps it (F07, F09 likely).
- **F03 buzzer default**: click default-on; toggleable at runtime + persistable via serial console.

### Sign-off pairs

| Pair | Features                                | Sign-off after |
|------|-----------------------------------------|----------------|
| A    | F01 + F02 (input layer)                 | both built + flashed |
| B    | F03 + F04 (buzzer)                      | both built + flashed |
| C    | F05 + F06 (bridge + HID burst)          | both built + flashed |
| D    | F07 + F08 (vault + mouse)               | both built + flashed |
| E    | F09 + F10 (TOTP + class switch)         | both built + flashed |
| F    | F11 (alone)                             | built + flashed |

## Implementation order + rationale

Ordering is intentional — easy/foundational firmware changes first, biggest USB-stack risks last.

1. **F01, F02** — pure input-layer firmware. They share a common debounce/state-machine refactor in `main.c` and `keys.c`. Doing both back-to-back avoids touching the same code twice.
2. **F03, F04** — buzzer features. Small additions, used by F05 and as a quality-of-life upgrade for every macro fire.
3. **F05** — Python bridge that consumes F04. No firmware change; lowest-risk demo of the feature stack.
4. **F06** — small firmware addition; useful to validate the protocol-extension pattern before F07.
5. **F07** — EEPROM layout extension. Risky if we get the layout wrong (bumps `FIRMWARE_VERSION`, wipes existing macros). Done before any USB-descriptor changes so we can recover via UF2 if it goes wrong.
6. **F08** — first composite-USB descriptor change. Adds Mouse HID.
7. **F09** — TOTP. Crypto + RTC sync, but no USB-stack changes. Independent of F08/F10.
8. **F10** — boot-time HID class selection. Modifies the composite descriptor system itself. Highest firmware risk.
9. **F11** — WebUSB descriptors + a small static web app. New attack surface; gated behind sign-off of every prior feature.

## Build + flash workflow per feature

For every firmware feature:

1. Edit code in `Firmware/Source/DC29/src/`.
2. `cd Firmware/Source/DC29 && make` to verify the build fits in 56 KB.
3. Run `/flash-badge` to flash. Confirm CDC re-enumerates and the existing Teams mute behavior still works.
4. Execute the feature's **Test plan**.
5. Update **Implementation notes** + **Testing notes** in the feature file.
6. Wait for user sign-off before moving on.

## Regression checks (run after every flash)

These are baseline behaviors that must not regress regardless of which feature we just shipped:

- LED 4 still responds to `0x01 'M' / 'U' / 'X'` (Teams mute).
- All 4 buttons still send their EEPROM-stored keymaps in solo press (unless overridden by F01/F02).
- Capacitive slider still reports up/down via buttons 5/6 (unless explicitly disabled via `0x01 'S' 0`).
- `dc29 diagnose` shows the badge connected and prints button events live.
- Firmware version string in `dc29 diagnose` matches `FIRMWARE_VERSION` in `main.h`.

## Feature-set FAQ

- **Why a single tracker?** Because the user signs off feature by feature, and reviewing one consolidated index is faster than hunting through PRs.
- **Why upfront goals + criteria?** So the bar for "done" is fixed before implementation starts. Saves both the user and Claude from scope-creeping mid-feature.
- **Why isn't there a CHANGELOG?** Git history is authoritative; this tracker captures the *why* and the test artifacts that the commit messages don't.
