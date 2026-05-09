# Review Tracker

Single-page master checklist for the entire 11-feature batch. Every checkbox links to the question/section it represents in the underlying design docs. Tick boxes here as you resolve them in the source docs (or tick them here and let me update the source docs to match).

> **How to use this file:**
> - In the GitHub web UI, click any `[ ]` to toggle it (works on rendered markdown views and inside PRs).
> - Use the matrix at the bottom for at-a-glance status; details live in each linked file.
> - When all open questions for a feature are resolved, mark its row in the Sign-off matrix.

## Cross-cutting questions ([`DESIGN.md §9`](DESIGN.md#9-open-cross-cutting-questions)) ✅ all resolved 2026-05-09

- [x] [Q1 — EEPROM-cap policy](DESIGN.md#q1-eeprom-cap-policy) → reduced sizing accepted
- [x] [Q2 — F10 MIDI mode scope](DESIGN.md#q2-f10-midi-mode-scope) → **MIDI dropped**
- [x] [Q3 — F10 implementation path](DESIGN.md#q3-f10-implementation-path) → runtime first
- [x] [Q4 — Lowercase letter namespace](DESIGN.md#q4-lowercase-letter-namespace) → approved
- [x] [Q5 — Single FIRMWARE_VERSION bump for F07+F09](DESIGN.md#q5-single-firmware-version-bump) → approved
- [x] [Q6 — F03 default-on under bridge takeover](DESIGN.md#q6-f03-default-on-under-bridge-takeover) → always click
- [x] [Q7 — F04 pattern interruption](DESIGN.md#q7-f04-pattern-interruption) → preempt
- [x] ~~Q8 — F08 jiggler default state~~ — *resolved by F08 redesign*

## Per-feature open questions

### F01 — Tap-count + long-press ([file](features/F01-tap-count-long-press.md))

- [x] [Q1 — Long-press semantics](features/F01-tap-count-long-press.md#f01-q1-long-press-semantics)
- [x] [Q2 — Multi-tap window default](features/F01-tap-count-long-press.md#f01-q2-tap-count-window)
- [x] [Q3 — Event report-back format](features/F01-tap-count-long-press.md#f01-q3-event-report-format)
- [x] [Q4 — RAM-only modifier table for first cut](features/F01-tap-count-long-press.md#f01-q4-ram-only-first-cut)

### F02 — Chord shortcuts ([file](features/F02-chords.md))

- [x] [Q1 — Three-finger fumble policy](features/F02-chords.md#f02-q1-three-finger-fumble)
- [x] [Q2 — Chord vs. long-press collision](features/F02-chords.md#f02-q2-chord-vs-long-press)

### F03 — Haptic confirmation ([file](features/F03-haptic-confirmation.md))

- [x] [Q1 — Click frequency](features/F03-haptic-confirmation.md#f03-q1-click-frequency)
- [x] [Q2 — Click duration](features/F03-haptic-confirmation.md#f03-q2-click-duration)
- [x] [Q3 — EEPROM persistence deferred?](features/F03-haptic-confirmation.md#f03-q3-eeprom-persistence)

### F04 — Beep signatures ([file](features/F04-beep-signatures.md))

- [x] [Q1 — Pattern resume after takeover click](features/F04-beep-signatures.md#f04-q1-pattern-resume-behavior)

### F05 — Beat-doubler ([file](features/F05-beat-doubler.md))

- [x] [Q1 — KICK pattern frequency](features/F05-beat-doubler.md#f05-q1-kick-pattern-frequency)

### F06 — HID burst ([file](features/F06-hid-burst.md))

- [x] [Q1 — Cancel semantics](features/F06-hid-burst.md#f06-q1-cancel-semantics)
- [x] [Q2 — Bursts during Teams meetings](features/F06-hid-burst.md#f06-q2-bursts-during-meetings)

### F07 — Rubber-ducky vault ([file](features/F07-rubber-ducky-vault.md))

- [x] ~~Q1 — Reduced sizing~~ → resolved via DESIGN Q1
- [x] [Q2 — Wipe vs. migrate EEPROM](features/F07-rubber-ducky-vault.md#f07-q2-wipe-vs-migrate)

### F08 — Stay Awake ([file](features/F08-mouse-jiggler.md))

- [x] [Q1 — CLI auto-spawn](features/F08-mouse-jiggler.md#f08-q1-cli-auto-spawn)
- [x] [Q2 — Indefinite session soft cap](features/F08-mouse-jiggler.md#f08-q2-indefinite-soft-cap)
- [x] [Q3 — Auto-pause on lid close](features/F08-mouse-jiggler.md#f08-q3-auto-pause-on-lid-close)
- [x] [Q4 — Effect-mode submenu scope](features/F08-mouse-jiggler.md#f08-q4-effect-mode-submenu)
- [x] [Q5 — Heartbeat interval](features/F08-mouse-jiggler.md#f08-q5-heartbeat-interval)
- [x] [Q6 — Custom duration max](features/F08-mouse-jiggler.md#f08-q6-custom-duration-max)
- [x] [Q7 — TUI tab slot](features/F08-mouse-jiggler.md#f08-q7-tab-slot)

### F09 — TOTP token ([file](features/F09-totp-token.md))

- [x] ~~Q1 — One slot only~~ → resolved via DESIGN Q1
- [x] [Q2 — TOTP digit count](features/F09-totp-token.md#f09-q2-digit-count)

### F10 — HID class switch ([file](features/F10-hid-class-switch.md))

- [x] ~~Q1 — Implementation path~~ → resolved via DESIGN Q3
- [x] ~~Q2 — MIDI mode scope~~ → resolved via DESIGN Q2 (**dropped**)
- [x] [Q3 — Mode 3 chord button assignment](features/F10-hid-class-switch.md#f10-q3-mode-4-chord)
- [x] [Q4 — Persistent mode override (defer?)](features/F10-hid-class-switch.md#f10-q4-persistent-mode-override)

### F11 — WebUSB config UI ([file](features/F11-webusb-config-ui.md))

- [x] [Q1 — GitHub Pages URL](features/F11-webusb-config-ui.md#f11-q1-github-pages-url)
- [x] [Q2 — Deployment mechanism](features/F11-webusb-config-ui.md#f11-q2-deploy-mechanism)
- [x] [Q3 — Web-app feature scope](features/F11-webusb-config-ui.md#f11-q3-web-app-scope)
- [x] [Q4 — Origin allowlist](features/F11-webusb-config-ui.md#f11-q4-origin-allowlist)

---

## Sign-off matrix

Status snapshot. Tick the cell once the corresponding phase is complete in each feature's file.

| Feature | Design approved | Built ≤ 56 KB | Hardware tested | Final sign-off |
|---------|:---------------:|:-------------:|:---------------:|:--------------:|
| F01 — Tap-count + long-press      | [x] | [ ] | [ ] | [ ] |
| F02 — Chords                       | [x] | [ ] | [ ] | [ ] |
| F03 — Haptic confirmation          | [x] | [ ] | [ ] | [ ] |
| F04 — Beep signatures              | [x] | [ ] | [ ] | [ ] |
| F05 — Beat-doubler                 | [x] |  n/a (Python) | [ ] | [ ] |
| F06 — HID burst                    | [x] | [ ] | [ ] | [ ] |
| F07 — Rubber-ducky vault           | [x] | [ ] | [ ] | [ ] |
| F08a — Mouse HID firmware          | [x] | [ ] | [ ] | [ ] |
| F08b — Stay Awake bridge + TUI     | [x] |  n/a (Python) | [ ] | [ ] |
| F09 — TOTP token                   | [x] | [ ] | [ ] | [ ] |
| F10 — HID class switch             | [x] | [ ] | [ ] | [ ] |
| F11 — WebUSB config UI             | [ ] | [ ] | [ ] | [ ] |

## How sign-off cascades

Per the [README](README.md#sign-off-pairs), features are gated in pairs:

| Pair | Features                               | Gate condition |
|------|----------------------------------------|----------------|
| A    | F01 + F02                              | both `Hardware tested` ticked |
| B    | F03 + F04                              | both `Hardware tested` ticked |
| C    | F05 + F06                              | both `Hardware tested` ticked |
| D    | F07 + F08                              | both `Hardware tested` ticked |
| E    | F09 + F10                              | both `Hardware tested` ticked |
| F    | F11                                    | `Hardware tested` ticked      |

Implementation of the next pair only begins after the previous pair's gate ticks.

---

## How to leave detailed feedback

For nuanced feedback that doesn't fit Approve/Reject/Modify, write it in the **Comments:** field directly under the question. The same applies to all sign-off blocks.

If you'd rather paste a long discussion or compare options, drop a fenced code block:

````
```
Discussion
==========
- I'd prefer 220 ms multi-tap window because ...
```
````

I treat anything in **Comments** as authoritative; if it conflicts with the proposal, I'll update the design doc to match and ask back if anything still needs resolving.
