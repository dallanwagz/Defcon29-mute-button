# LED Takeover Animation — Design

Per-button-press LED takeover animation, 2.5 seconds, ASMR-relief vibe. Pairs with [2-30am dallan_prompt.md](2-30am%20dallan_prompt.md) — this is the worked-out design from that ask.

> **Status:** Decisions locked in 2026-04-29. Ready for implementation. All open questions resolved by user; this doc is now an implementation spec, not a proposal.

---

## TL;DR

Press any button → its color *invades* the other three LEDs in a deliberate, 2.5-second four-phase animation: ignition flash → sequential clockwise alternating invasion → rotating dominance chase → blackout-then-restore. **35 frame transitions. Four auto-selected personalities** (Classic, Devil, Zen, Joy) tune the feel based on the invader color. **Buzzer accents** punctuate ignition and the blackout. Toggleable via the existing `button_flash_enabled` flag (already wired through the `0x01 F` protocol command). Re-pressing during an animation **restarts cleanly from frame 1** — fluid stacking, mash-friendly.

---

## Why a takeover animation, not a "fancier ripple"

The current [pwm.c](Firmware/Source/DC29/src/pwm.c) ripple is a 2-frame circular blend that fires-and-forgets. It registers as "the LED blinked," not "something happened." The brain's pattern-completion circuitry only locks on after ~600–800 ms of structured visual stimulus — anything shorter feels like an event, not an experience.

A satisfying 2.5-second arc has three properties the brain is wired to enjoy:
1. **Anticipation** — a beat of *something is starting* before the main action.
2. **Build** — visible progression through phases the user can mentally narrate.
3. **Release** — a definitive ending that resets the visual field, not a fade-to-nothing.

The takeover delivers all three. It's a tiny piece of music played in light, with a buzzer accent at each apex.

---

## Hardware constraints baked into the design

| Constraint | Source | Design impact |
|---|---|---|
| 2×2 LED grid (LED1=TL, LED2=TR, LED3=BL, LED4=BR) | [hardware-ref.md](docs/hacker/hardware-ref.md) | Invasion uses **sequential clockwise** order — same direction from any source |
| White translucent keycaps over each LED | physical | Pure RGB shows clean; alternations between two colors look crisp through the diffuser; off-state reads as cream/off-white, distinct from any colored state |
| Global brightness multiplier | upstream commit `9427079` | Animation never asks for >100% — peaks are achieved by **dimming everyone else**, not boosting the source. Works at any brightness setting. (Joy personality is the exception — see below.) |
| LED4 normally reserved for mute indicator | [hardware-ref.md](docs/hacker/hardware-ref.md):44 | **Suspended for the duration of every takeover.** Animation drives all 4 LEDs unconditionally. Mute state restored at end. |
| Piezo buzzer on PIN_PB22 (TCC output) | [hardware-ref.md](docs/hacker/hardware-ref.md):50 | Two accent points: ignition click + blackout thud, tuned per personality |
| ~16 KB application flash headroom (current build 40,204 / 57,344) | last build size | Animation is procedural with small per-personality parameter table. Estimated ~1.5 KB. |
| Existing `update_effects()` runs every main-loop tick | [main.c:631](Firmware/Source/DC29/src/main.c) | Takeover hooks the same tick — no new timer needed |

---

## The four-phase arc

| Phase | Duration | Frames | Feel |
|---|---|---|---|
| 1. Ignition | 300 ms | 3 | "Something just happened." |
| 2. Invasion (sequential CW, 3 victims × 7 sub-frames × 50 ms) | 1050 ms | 21 | "It's spreading. The LEDs are losing — one at a time, in order." |
| 3. Dominance (CW chase, 2 rotations) | 800 ms | 8 | "Total takeover. Watch it strut." |
| 4. Resolution | 350 ms | 3 | "The world snaps back." |
| **Total** | **2500 ms** | **35 frames** | |

### Phase 1 — IGNITION (300 ms, 3 frames)

The pressed LED announces itself. The other three are still at rest — this is the moment the user's eye locks on.

| Frame | Source LED | Other 3 | Hold | Why |
|---|---|---|---|---|
| F1 | invader@100% | resting | 80 ms | Initial pop. **Buzzer click fires here.** |
| F2 | OFF | resting | 60 ms | The disappearance is more attention-grabbing than the appearance |
| F3 | invader@100% | resting | 160 ms | Re-strikes harder; reads as confident, not flickery |

The brief OFF is the trick — a single black frame at the right moment makes the surrounding two ON frames feel emphatic. Same principle as the silence before a drum hit. The buzzer click on F1 lands ~5–10 ms before the brain registers the LED change (audio latency < visual), priming attention.

### Phase 2 — INVASION (1050 ms, 21 sub-frames)

The takeover spreads **sequentially clockwise** around the 2×2 ring. The CW ring order is **TL → TR → BR → BL → TL** (LED indices 0 → 1 → 3 → 2 → 0). For each source LED, the three victims are the next three positions in this ring:

| Source | Victim 1 | Victim 2 | Victim 3 |
|---|---|---|---|
| LED1 (TL) | LED2 (TR) | LED4 (BR) | LED3 (BL) |
| LED2 (TR) | LED4 (BR) | LED3 (BL) | LED1 (TL) |
| LED4 (BR) | LED3 (BL) | LED1 (TL) | LED2 (TR) |
| LED3 (BL) | LED1 (TL) | LED2 (TR) | LED4 (BR) |

Sequential rather than parallel because the user wants to *recognize the pattern*. Watching one LED at a time fall to the invader, in order, is more narratable than two-at-a-once: "First the TR went, then BR, then BL — and now they're all blue." Pattern recognition is the entry point to ASMR satisfaction. Parallel-then-diagonal would shave 350 ms but at the cost of legibility.

While victim N is mid-alternation, already-invaded LEDs hold the invader color and not-yet-invaded LEDs hold their resting color. The source LED holds invader@100% throughout invasion (the conqueror).

**Per-victim alternation, 7 sub-frames totaling 350 ms:**

| Sub-frame | Color | Hold | Reads as |
|---|---|---|---|
| 1 | invader@100% | 60 ms | First strike |
| 2 | victim@100% | 50 ms | Holds ground |
| 3 | invader@100% | 50 ms | Counter-strike |
| 4 | victim@60% | 50 ms | Weakening |
| 5 | invader@100% | 50 ms | Strong push |
| 6 | victim@20% | 40 ms | Last gasp |
| 7 | invader@100% (locked) | 50 ms | Final dominance |

The victim's brightness *decays* across alternations (100% → 60% → 20%) while the invader stays at 100%. Visually this reads as "the previous color is losing its grip" — exactly the takeover narrative. Pure on/off alternation looked symmetric in early sketches; the asymmetric decay is what gives it directionality.

Sub-frame timing of 40–60 ms is well above the 30 Hz flicker fusion threshold, so the alternation is *visible* not blurred. That's the whole point.

### Phase 3 — DOMINANCE (800 ms, 8 frames at 100 ms each)

All 4 LEDs are now invader color. They could just sit there, but that's where the energy dies. Instead: a comet chase rotates around the 2×2 ring in the same CW order as the invasion (**TL → TR → BR → BL → TL**), with the comet position at full brightness and the other 3 dimmed to 40%.

- 8 frames × 100 ms = 800 ms = **2 full rotations** (clean, not mid-cycle)
- Starts on the source LED's CW position (so the source gets the first dominance pulse — like it's leading the parade)
- Direction matches the invasion direction so the eye reads it as continuation, not a new motif

Why a chase, not a synchronized pulse: a synchronized pulse at 2 Hz feels like a heartbeat — calming but passive. A rotating chase reads as **the takeover walking around showing off**. Different verb.

100 ms per step is fast but not blurry. The eye sees the moving brightness peak as a coherent object traversing the ring — same neural mechanic that makes loading spinners satisfying to watch.

### Phase 4 — RESOLUTION (350 ms, 3 frames)

Hard ending, not a fade. Fades feel uncertain; the user wants closure.

| Frame | All 4 LEDs | Hold | Why |
|---|---|---|---|
| F1 | invader@100% (synchronized) | 100 ms | Crescendo — every LED at full invader color, no chase. The triumphant one-frame freeze. |
| F2 | OFF (all four black) | 100 ms | The hush. **Buzzer thud fills this 100 ms.** Audio replaces light so the moment isn't empty. |
| F3 | each LED's **current** resting color | 150 ms | Reality returns. Short hold so quick re-presses feel snappy, not delayed. |

The 100 ms full-blackout in F2 is the most important frame in the whole animation. It's what makes the return feel *new*, not anticlimactic. The keycaps will momentarily look like cream-white tiles before the colors come back. The buzzer thud during the visual blackout is the signature moment — the badge "exhales" and you hear it.

F3 at 150 ms (down from an earlier 300 ms draft) was confirmed by the user as the right cadence. Short enough that mashing the same button feels fluid; long enough that the resting colors are unambiguously visible before any retrigger.

---

## Source-color and victim-color semantics

- **Invader color** = the source button's *resting* color at the instant of press, unchanged for the whole animation.
- **Victim colors** during invasion = each LED's resting color at the instant of press (snapshot once at start, used in alternation sub-frames).
- **Restoration colors** at end of resolution = each LED's resting color at the instant the animation *ends*. So if the host updated a LED's color via `0x01 L` mid-animation, the new color is what comes back. This matters for LED4 specifically (mute toggles).

---

## Mute LED (LED4) handling — animation wins, by design

The rule "LED4 is the Teams mute indicator. Never drive it from firmware effects" is **suspended for the duration of every takeover, on every press, including presses of buttons other than B4**. The animation drives all 4 LEDs unconditionally.

Decision rationale (locked in by user, not a tradeoff being weighed): during the 2.5 s window the user is admiring the badge to enjoy the takeover, not glancing at LED4 to check mute state. Mute-state accuracy comes back the moment the animation ends.

How it works:
- `0x01 M/U/X` updates from the host arrive during the animation are written to the underlying mute state variable and **not rendered** until the animation ends.
- At the end of Phase 4 F3, LED4 renders the *latest* mute state, whatever that is at that moment.
- If the host sent multiple updates during the animation (mute → unmute → mute), only the last one is shown — intermediate states are not played back.

No mute-update queueing or replay. The simplicity is the point.

---

## Re-press during animation — fluid stacking

A second press during a running takeover **restarts the animation from frame 1 with the new source**. No queueing, no overlay, no blend.

Rationale (locked in by user as "fluid stacking"): if the user mashes the same button or jumps between buttons, the badge should respond *immediately* to each press with a fresh animation. The previous animation is discarded mid-frame. The HID action is sent regardless — the animation is purely cosmetic feedback.

The "fluid stacking" feeling comes from the fact that each press starts a fresh ignition (Phase 1) which begins with the source LED at full invader color — meaning every press, regardless of what was happening on screen before, starts with a confident strike on the pressed LED. No matter when in the previous animation the new press lands, the new animation begins decisively.

The buzzer also restarts: any ongoing buzzer tone is cut, and the new ignition click fires.

---

## TUI toggle

Re-use the existing `button_flash_enabled` flag, which is already:
- Stored in firmware state (in [main.c](Firmware/Source/DC29/src/main.c))
- Settable via the existing `0x01 F <0|1>` protocol command (commit `93d82a6`)
- Persisted to EEPROM (verify in implementation)

When `button_flash_enabled == false`, button presses send keys silently with no animation and no buzzer. The previous tier-2 ripple (the current code) is replaced wholesale by the takeover; we don't keep two tiers.

If a second toggle is wanted later (e.g., separate buzzer-mute control independent of visual animation), add `0x01 B <0|1>` for buzzer-only toggle.

---

## Per-button personality (v1)

The animation pattern above is the **Classic** personality — the default, every button feels equally satisfying. v1 also ships **three additional personalities**, auto-selected from the source LED's color at press time. They tune Phase 2 alternation feel, Phase 3 chase feel, Phase 4 resolution flash, and the buzzer accents.

| Personality | Triggers when source color is | Phase 2 (invasion) | Phase 3 (dominance) | Phase 4 F1 (crescendo) | Buzzer ignition / blackout |
|---|---|---|---|---|---|
| **Classic** | Default (no other match) | 7 sub-frames per victim, decay alternation as in the table above | CW chase, comet 100% / others 40% | Invader@100% solid | 30 ms / 800 Hz click, 60 ms / 200 Hz thud |
| **Devil** | R dominant (R > G + B + 30) | 7 sub-frames, **40 ms each** (faster), no decay — pure on/off battle | **CCW chase** (reverse direction), comet 100% / others 20% (sharper) | Invader@100% solid + 1 frame of pure white flicker mid-hold | 25 ms / 1200 Hz sharp click, 80 ms / 120 Hz growl |
| **Zen** | B dominant (B > R + G + 20) | 7 sub-frames, **70 ms each** (slower), sinusoidal brightness instead of step-decay | CW chase **with overlap** — previous comet position fades over 50 ms while next rises | Invader@100% solid, no flicker | 40 ms / 440 Hz pad, 70 ms / 220 Hz pad |
| **Joy** | G dominant (G > R + B + 20) | 7 sub-frames with **accelerating** periods 60→55→50→45→40→35→30 ms — bouncy | CW chase **with overshoot**: comet briefly hits 120% by dimming others to **0** between steps | Invader@100% with quick double-pulse (100% → 50% → 100%) | 25 ms / 1500 Hz blip, then 50 ms / 600 Hz blip + 50 ms / 800 Hz blip |

**Cool** (cyan-ish: B and G both > R, neither dominant) is reserved for v2 — too niche for color auto-detection, and the design intent is for a future explicit assignment protocol command.

**Auto-detection logic** (firmware, fast — runs once at `takeover_start()`):
```c
typedef enum { PERS_CLASSIC, PERS_DEVIL, PERS_ZEN, PERS_JOY } Personality;

static Personality personality_for(uint8_t r, uint8_t g, uint8_t b) {
    if ((int)r > (int)g + (int)b + 30) return PERS_DEVIL;
    if ((int)g > (int)r + (int)b + 20) return PERS_JOY;
    if ((int)b > (int)r + (int)g + 20) return PERS_ZEN;
    return PERS_CLASSIC;
}
```

Personality is computed once at `takeover_start()` and held for the entire animation. Recomputing per-frame isn't necessary because the invader color is fixed at start.

**Why color-based auto-detection vs explicit per-button assignment?**
- Zero EEPROM cost for v1 — invader color drives personality directly
- Plays naturally with the bridge system: when the Mac sets B4 to red for "Outlook delete" via `0x01 L`, the next press auto-gets Devil personality. No second protocol command needed.
- v2 can add `0x01 N <button> <personality>` for explicit override if context wants something other than the color-implied feel (e.g., "make this blue button feel devilish for unsubscribe-spam mode")

**Email-deletion devil note:** when LED4 is set to red (mute=muted, or context-driven email-delete red), pressing it triggers Devil personality automatically. Faster sub-frames + reversed chase + pure white flicker mid-crescendo + sharp click + 120 Hz growl during blackout. This is the "naughty anti-corporation devil on your shoulder" feel from the original prompt.

---

## Buzzer accents (v1)

Two accent points per animation, tuned per personality:

- **Phase 1 F1 (ignition click):** a short tone that punctuates the visual flash. Heard before the eye registers the LED change because audio latency is shorter than visual. Sets up the takeover. Duration 25–40 ms — fits inside the 80 ms F1 hold.
- **Phase 4 F2 (blackout thud/pad/growl):** a longer tone that fills the 100 ms blackout window. Audio fills the visual silence — the brain experiences a *complete* moment instead of a void. Duration 50–80 ms.

**Implementation hooks:**
- A non-blocking `buzzer_play(freq_hz, duration_ms)` function — uses a TC timer to drive the TCC output for the duration, then silences. Returns immediately so the main loop continues.
- Called from `takeover_start()` (the ignition click) and from inside `takeover_tick()` at the F1→F2 boundary detection (the blackout thud).
- Re-press during an animation: cancel any in-flight tone, fire the new ignition click. (`buzzer_cancel()` then `buzzer_play()`.)

**No `buzzer_enabled` flag in v1.** The buzzer is part of the takeover UX and tracks `button_flash_enabled`. If the user wants silent visuals, that's a v2 feature: add `0x01 B <0|1>` and a `buzzer_enabled` byte in EEPROM.

---

## Implementation outline

```c
typedef struct {
    bool        active;
    uint32_t    start_ms;
    uint8_t     source_idx;          // 0..3
    Personality personality;         // computed once at start
    uint8_t     invader_rgb[3];
    uint8_t     victim_snapshot[4][3];  // colors at press time, used for alternation
    bool        blackout_buzzed;     // true once F2 thud has fired (avoid double-play)
} TakeoverAnim;

static TakeoverAnim takeover;

// CW ring order on the 2x2 grid: TL=0, TR=1, BR=3, BL=2
// (Note: hardware indexing has LED1=0, LED2=1, LED3=2, LED4=3, but the CW
// ring order is logical, not hardware index order.)
static const uint8_t cw_ring[4] = {0, 1, 3, 2};  // TL, TR, BR, BL

// Lookup: source LED -> 3 victim LEDs in CW order (hardware indices)
static const uint8_t cw_invade_order[4][3] = {
    /* source 0 (TL) -> */ {1, 3, 2},
    /* source 1 (TR) -> */ {3, 2, 0},
    /* source 2 (BL) -> */ {0, 1, 3},
    /* source 3 (BR) -> */ {2, 0, 1},
};

// Personality timing/feel parameters (one row per personality)
typedef struct {
    uint8_t  invasion_subframe_ms;   // 40 (Devil) / 50 (Classic) / 70 (Zen) / accel (Joy uses curve)
    bool     invasion_decay;         // false for Devil (no brightness decay)
    bool     dominance_ccw;          // true for Devil
    uint8_t  dominance_other_pct;    // 40 (Classic/Zen) / 20 (Devil) / 0 (Joy overshoot)
    bool     crescendo_white_flick;  // true for Devil
    bool     crescendo_double_pulse; // true for Joy
    uint16_t click_hz; uint8_t  click_ms;
    uint16_t thud_hz;  uint8_t  thud_ms;
} PersonalityParams;

static const PersonalityParams personality_table[4] = {
    /* CLASSIC */ {50, true,  false, 40, false, false,  800, 30, 200, 60},
    /* DEVIL   */ {40, false, true,  20, true,  false, 1200, 25, 120, 80},
    /* ZEN     */ {70, true,  false, 40, false, false,  440, 40, 220, 70},
    /* JOY     */ { 0, true,  false,  0, false, true,  1500, 25, 600, 50}, // Joy uses curve
};

void takeover_start(uint8_t button_idx) {
    if (!button_flash_enabled) return;
    buzzer_cancel();  // cancel any in-flight tone from a previous animation
    takeover.active = true;
    takeover.start_ms = millis;
    takeover.source_idx = button_idx;
    takeover.personality = personality_for(/* current resting RGB of button_idx */);
    takeover.blackout_buzzed = false;
    /* snapshot invader_rgb and victim_snapshot[] from led_resting */
    /* fire ignition click for this personality */
    PersonalityParams p = personality_table[takeover.personality];
    buzzer_play(p.click_hz, p.click_ms);
}

bool takeover_tick(void) {
    if (!takeover.active) return false;
    uint32_t t = millis - takeover.start_ms;
    if (t >= 2500) {
        takeover.active = false;
        for (int i = 0; i < 4; i++) led_render(i, led_resting[i]);
        return true;
    }
    if (t < 300)  ignition_render(t);
    else if (t < 1350) invasion_render(t - 300);    // 1050 ms invasion
    else if (t < 2150) dominance_render(t - 1350);  //  800 ms dominance
    else {
        resolution_render(t - 2150);                //  350 ms resolution
        // Fire blackout thud once at F2 boundary (t = 2150 + 100 = 2250)
        if (!takeover.blackout_buzzed && (t - 2150) >= 100) {
            PersonalityParams p = personality_table[takeover.personality];
            buzzer_play(p.thud_hz, p.thud_ms);
            takeover.blackout_buzzed = true;
        }
    }
    return true;
}
```

**Files touched:**
- [pwm.c](Firmware/Source/DC29/src/pwm.c) — replace `led_ripple_start`/`led_ripple_finish` with the takeover state machine, four phase renderers, personality table, and color→personality detector
- [pwm.h](Firmware/Source/DC29/src/pwm.h) — exported declarations
- [keys.c](Firmware/Source/DC29/src/keys.c) — call `takeover_start(button_idx)` on press (replacing existing `led_ripple_start`)
- [main.c](Firmware/Source/DC29/src/main.c) — `update_effects()` calls `takeover_tick()` first; if it returns true, skip the existing `effect_mode` rendering this tick. Remove the LED4-reservation comment on line 629–630.
- [comms.c](Firmware/Source/DC29/src/comms.c) — no protocol changes (existing `0x01 F` toggle reused). Confirm `0x01 M/U/X` writes to a shadow variable that LED4 rendering reads, so animations can override transparently.
- **NEW** buzzer driver — either added to pwm.c or split into a small `buzzer.c`/`.h`. TCC channel for PIN_PB22; non-blocking single-tone playback with cancel.

**Estimated cost:**
- Flash: ~1500 bytes (state machine + 4 phase renderers + personality table + auto-detect + buzzer driver)
- RAM: ~32 bytes for `TakeoverAnim` struct + ~16 bytes for buzzer state
- Total over current build: ~41,700 / 57,344 bytes (~73%)

**No EEPROM layout change.** `FIRMWARE_VERSION` stays at 2.

---

## Verification approach

The animation needs to be felt, not specified. Useful instrumentation to ship with v1:

1. **Serial fake-press command** — `0x01 P n` triggers `takeover_start(n)` without an actual button press. Lets the Mac drive a press for video capture or remote testing. ~30 bytes of code.
2. **TUI demo mode** — cycle through all 4 sources with 3 s gaps, lets the user evaluate without USB-keystroking themselves. Mac-side TUI feature; no firmware change.
3. **(Debug-only)** Per-phase serial tag — `TKO IGN→INV`, `TKO INV→DOM`, etc. Useful during initial bring-up; remove or gate behind a debug flag before release.

---

## Decisions locked in (2026-04-29)

| # | Question | Decision |
|---|---|---|
| 1 | Adjacent-then-diagonal vs sequential CW invasion? | **Sequential CW.** Pattern recognition is the entry point to ASMR satisfaction. |
| 2 | Re-press: restart vs ignore? | **Restart from frame 1** ("fluid stacking") — fresh ignition every press. |
| 3 | Resolution F3 hold duration | **150 ms** (down from 300 ms draft). Snappy retrigger, still long enough to register resting colors. |
| 4 | Per-button personality scope in v1 | **All four personalities ship in v1**, auto-selected from invader color (Devil/Zen/Joy/Classic). Cool reserved for v2 with explicit assignment. |
| 5 | Buzzer accent | **Yes, included in v1.** Per-personality click on ignition + thud during blackout. |
| (resolved earlier) | LED4 mute reservation during animation | **Suspended for the full 2.5 s.** Animation drives all 4 LEDs. Mute state restored post-animation. |

Implementation estimate: 3–5 hours of firmware work + on-badge tuning, including the buzzer driver. Recommend implementing in this order:
1. Base state machine + Classic personality (no buzzer yet) — verify visual feel on hardware
2. Add buzzer driver + Classic accents — verify audio fits
3. Add Devil personality — verify the "email-deleter" feel is achieved
4. Add Zen and Joy
5. Color auto-detection + final wiring
6. `0x01 P n` fake-press command for the Mac TUI demo mode
