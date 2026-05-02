# Porting WLED to a DEF CON 29 Badge

*How an open-source LED library and a six-year-old conference badge meet
in the middle — via 839 lines of compatibility shim and a virtual-strip
trick that makes 4 LEDs feel like 16.*

---

## TL;DR

The DEF CON 29 badge is from 2021. It has an ARM Cortex-M0+ running at 48
MHz, **8 KB of RAM**, **56 KB of usable flash** (after the bootloader),
**no FPU**, and **four** RGB LEDs in a 2×2 grid.

[WLED](https://github.com/Aircoookie/WLED) is a popular open-source
firmware for ESP32/ESP8266 LED controllers. It carries 200+ effects in a
single ~11,000-line `FX.cpp` file. It expects strips of dozens to
hundreds of LEDs running on much beefier silicon.

This document explains how we got 16 WLED effects running on the badge —
**Pacifica**, **Pride 2015**, **Bouncing Balls / Sinelon**, **Plasma**,
**Lake**, **Confetti**, **Juggle**, the works — at 60 fps, with the
firmware sitting at **83% of available flash** and **~10 KB headroom**.
And it explains the *translation engine* we built so any future WLED
effect can be ported in roughly ten minutes.

The interesting bit isn't really the porting. It's that the architectural
move at the heart of it — **render to a virtual high-resolution strip,
then box-average down to physical pixels** — turns the 4-LED constraint
from a fundamental limit into a downsampling step. Once you accept the
downsampling, *most* WLED effects look the way WLED intended.

The full implementation lives in:

- [`Firmware/Source/DC29/src/wled_fx.h`](../Firmware/Source/DC29/src/wled_fx.h) — 205 lines, public API
- [`Firmware/Source/DC29/src/wled_fx.c`](../Firmware/Source/DC29/src/wled_fx.c) — 634 lines, 16 effect ports + the engine

---

## The hardware constraint, concretely

| Resource | Available | What that means |
|---|---|---|
| Cortex-M0+ @ 48 MHz | ~48 MIPS | Comfortably 60 fps for any effect we care about |
| Flash | 56 KB | Hundreds of bytes per effect, not thousands |
| RAM | 8 KB | No `malloc`, no per-effect heap state, no big lookup tables |
| FPU | None | All arithmetic must be integer / fixed-point |
| LEDs | 4 RGB | The hard constraint |

The badge has been a USB macropad / Teams mute indicator for the past few
years; the LED side of things was 8 hand-rolled animation modes (rainbow
chase, breathe, twinkle, cylon, etc.) totaling maybe 1.5 KB of code. Plenty
of room to grow.

WLED, by contrast, expects to talk to up to 1,500 LEDs on one segment,
with floating-point intermediate math, optional Perlin noise lookup tables,
heap-allocated per-segment scratch buffers, and an HTTP API for live
control. Most of that doesn't fit. Some of it doesn't apply (we can't
really meaningfully render a "running lights" effect across 4 pixels).
But the *math* and the *visual ideas* are universal.

---

## The architectural move that made it work

### Naive approach: render directly to 4 pixels

The first instinct is to take a WLED effect, change its `SEGLEN` to 4,
and let it write to the 4 physical LEDs. **This produces awful results
for anything spatial.** A "running light" sweeping across a strip is just
a single pixel that blinks. A "color wipe" is a 1-pixel-at-a-time
shuffle. A "sinelon" dot tracing a sine wave is reduced to two pixels
flickering. The motion that gives WLED effects their character lives in
the *spatial* domain across many adjacent pixels, and 4 pixels can't
resolve it.

### Better approach: virtual strip + downsample

The trick is to **render to a virtual 16-pixel strip in RAM** (`crgb_t
vstrip[16]`, 48 bytes), let the effect think it's painting a normal
strip, and then **box-average each quartile down to one of the 4
physical LEDs**.

```c
void vstrip_render(void) {
    for (uint8_t led = 0; led < 4; led++) {
        uint16_t sr = 0, sg = 0, sb = 0;
        for (uint8_t k = 0; k < 4; k++) {
            crgb_t c = vstrip[led * 4 + k];
            sr += c.r; sg += c.g; sb += c.b;
        }
        uint8_t out[3] = { (uint8_t)(sr >> 2), (uint8_t)(sg >> 2), (uint8_t)(sb >> 2) };
        led_set_color(led + 1, out);
    }
}
```

That's the entire downsampler. 9 bytes of state, maybe 30 instructions
per call.

The visual consequence is that **temporal motion is preserved**. A wave
of color sweeping across the virtual 16-pixel strip becomes a wave of
color sweeping across the 4 physical LEDs, just at lower spatial
resolution. Each physical LED is a smoothly-blended composite of 4
virtual pixels' worth of motion. It looks *right* — recognizable as the
same WLED effect you'd see on a 16-LED strip, downsampled.

For effects whose visual is purely temporal (e.g. *breath*, *pacifica*,
*pride 2015* — same color across all pixels at any moment, modulated over
time), the downsampling is a no-op: all 4 quartiles get the same value,
and the box-average is exact. These effects look identical to WLED.

### The cost-benefit

- **48 bytes of RAM** for the virtual framebuffer
- **One linear pass** at the end of every frame
- **Identical fidelity** for temporal effects
- **Recognizable, smooth motion** for spatial effects
- **Zero changes** required to ported effect code — they write to
  `SEGMENT.setPixelColor(i, c)` for `i = 0..15` exactly like WLED

This is the single most important decision in the project. Without it,
you're writing 4-pixel-specific re-implementations of every effect.
With it, you're running WLED's actual algorithms.

---

## The compatibility shim

The goal of the shim is simple to state:

> **A WLED effect's source code, copied from `FX.cpp` and run through a
> mechanical find-and-replace table, should compile and behave correctly
> on the badge.**

That requires reproducing the WLED runtime contract. WLED effects depend
on roughly four categories of thing:

1. **Math primitives** (FastLED's `lib8tion` library): `sin8`, `cos8`,
   `scale8`, `qadd8`, `qsub8`, `blend8`, `lerp8by8`, `triwave8`,
   `quadwave8`, `cubicwave8`, `ease8InOutQuad`, `ease8InOutCubic`.
2. **Random**: `random8()`, `random8(max)`, `random16()` — using a
   specific linear congruential generator.
3. **Beat clock**: `beat8(bpm)`, `beat88(bpm88)`, `beatsin8(bpm, lo, hi)`
   — phase ramps and sinusoids derived from `millis()`, locked to BPM.
4. **Segment state**: `SEGMENT.speed`, `SEGMENT.intensity`,
   `SEGMENT.palette`, `SEGENV.aux0`, `SEGENV.aux1`, `SEGENV.step`,
   `SEGENV.call`, `SEGLEN`, `FRAMETIME`.

We reproduced all of these. **Crucially, the math primitives are
bit-identical to FastLED's canonical implementations.** This isn't a
nicety — WLED effects are tuned around specific waveforms and rounding
behavior. An "approximate" `sin8` produces visibly different effects.
The same `sin8(64)` must equal 255 here as it does in FastLED.

Why bit-identical? Pride 2015 (Mark Kriegsman's classic) advances a
brightness theta by `beatsin88(thetainc16)` and squares the resulting
sine for a "bright peaks, dim valleys" envelope. If `sin8` peaks aren't
sharp enough, or `scale8` rounds differently, the brightness modulation
loses its character — the effect goes from "this is shimmering rainbow
fire" to "this is some pulsing rainbow." Subtle but huge.

### The math: sin8 (FastLED's 33-entry quarter-wave)

```c
static const uint8_t b_m16_interleave[] = {
      0, 49,
     49, 41,
     90, 27,
    117, 10
};
uint8_t sin8(uint8_t theta) {
    uint8_t offset = theta;
    if (theta & 0x40) offset = (uint8_t)(255 - offset);
    offset &= 0x3F;
    uint8_t secoffset = offset & 0x0F;
    if (theta & 0x40) secoffset++;
    uint8_t section  = (uint8_t)(offset >> 4);
    const uint8_t *p = b_m16_interleave + section * 2;
    uint8_t b   = *p++;
    uint8_t m16 = *p;
    uint8_t mx  = (uint8_t)((m16 * secoffset) >> 4);
    int8_t  y   = (int8_t)mx + (int8_t)b;
    if (theta & 0x80) y = (int8_t)(-y);
    return (uint8_t)(y + 128);
}
```

Eight bytes of LUT. A quarter-wave mirrored four times via two bit-tests.
About 25 cycles on Cortex-M0+. Returns a sine wave in `[0, 255]`,
bit-identical to FastLED.

### The math: scale8 (FASTLED_SCALE8_FIXED form)

```c
static inline uint8_t scale8(uint8_t i, uint8_t s) {
    return (uint8_t)(((uint16_t)i * (1 + (uint16_t)s)) >> 8);
}
```

The `+1` matters: it makes `scale8(255, 255) == 255` exactly. The naive
form (`i * s >> 8`) gives 254. WLED's gamma curves and brightness ramps
assume the fixed form.

### The math: random (FastLED LCG)

```c
extern uint16_t wled_rand16seed;
static inline uint16_t random16(void) {
    wled_rand16seed = (uint16_t)(2053u * wled_rand16seed + 13849u);
    return wled_rand16seed;
}
static inline uint8_t random8(void) {
    uint16_t r = random16();
    return (uint8_t)((r & 0xFF) + (r >> 8));
}
```

Constants `2053` and `13849` are FastLED's canonical LCG. Effects that
seed from a known initial state (e.g. confetti, twinkles) produce the
same sequence of pixels here as on a real WLED controller.

### The beat clock

WLED expresses periodic motion in BPM. `beat8(bpm)` returns an 8-bit
phase ramp that completes one cycle per beat at `bpm` beats per minute,
derived from `millis()`. `beatsin8(bpm, lo, hi)` runs that through `sin8`
and remaps to `[lo, hi]`. Effects use this for everything from "color
saturation oscillates between 220 and 250 over many seconds" to "this
dot moves back and forth through the strip."

```c
static inline uint16_t beat88(uint16_t bpm88, uint32_t now) {
    return (uint16_t)((now * (uint32_t)bpm88 * 280u) >> 16);
}
static inline uint8_t beat8(uint8_t bpm, uint32_t now) {
    return (uint8_t)(beat88((uint16_t)bpm << 8, now) >> 8);
}
static inline uint8_t beatsin8(uint8_t bpm, uint8_t lo, uint8_t hi, uint32_t now) {
    uint8_t b = beat8(bpm, now);
    uint8_t s = sin8(b);
    return lo + scale8(s, hi - lo);
}
```

The one deviation from WLED: `now` (the millis timestamp) is passed
explicitly rather than fetched from a global. WLED uses a `strip.now`
global; passing it in lets us inline these in the header without forcing
an extern, and keeps the embedded constraints visible (you can't
accidentally drift the time source).

### Segment state: SEGMENT and SEGENV

WLED has a `Segment` class with per-segment user knobs and scratch state.
We mirror it as one global struct:

```c
typedef struct {
    uint8_t  speed;        /* 0..255 — most effects derive their timebase from this */
    uint8_t  intensity;    /* 0..255 — per-effect "amount" knob */
    uint8_t  palette;      /* index into palette_table[] */
    uint8_t  custom1;
    uint16_t aux0, aux1;   /* free-form 16-bit scratch */
    uint32_t step;         /* free-form 32-bit scratch */
    uint32_t call;         /* call counter — ==0 on first call after mode change */
    uint8_t  data[24];     /* small persistent buffer (replaces SEGENV.data heap) */
} wled_seg_t;

extern wled_seg_t wled_seg;
#define SEGMENT  wled_seg
#define SEGENV   wled_seg     /* WLED uses both names; both alias the same object */
#define SEGLEN   16           /* virtual strip length */
```

`SEGENV.call == 0` is WLED's canonical first-frame init signal. Effects
do things like:

```c
if (SEGENV.call == 0) { SEGENV.aux0 = millis; }   /* init last-frame timestamp */
```

We zero `SEGENV.call` on every mode change so this idiom works. The
`data[24]` buffer replaces WLED's `SEGENV.allocateData(N)` heap call —
24 bytes is enough for everything in our ported set, and it lives in
BSS, allocated once at boot.

### Palettes

WLED ships ~70 palettes; we ship 8: rainbow, heat, ocean, lava, pacifica,
sunset, forest, party. Each is a 16-entry RGB table:

```c
static const crgb_t pal_pacifica1[16] = {
    {0x00,0x05,0x07},{0x00,0x04,0x09},{0x00,0x03,0x0B},{0x00,0x03,0x0D},
    {0x00,0x02,0x10},{0x00,0x02,0x12},{0x00,0x01,0x14},{0x00,0x01,0x17},
    {0x00,0x00,0x19},{0x00,0x00,0x1C},{0x00,0x00,0x26},{0x00,0x00,0x31},
    {0x00,0x00,0x3B},{0x00,0x00,0x46},{0x14,0x55,0x4B},{0x28,0xAA,0x50}
};
```

That's the actual pacifica layer-1 palette from `FX.cpp:4194`, copied
verbatim. 48 bytes of flash per palette × 8 palettes = 384 bytes total.

Linear-blended lookup matches WLED's `ColorFromPalette(pal, idx, bri,
LINEARBLEND)`:

```c
crgb_t palette_lookup_arr(const crgb_t pal[16], uint8_t idx, uint8_t bri) {
    uint8_t hi = (uint8_t)(idx >> 4);          /* entry 0..15 */
    uint8_t lo = (uint8_t)(idx & 0x0F);
    uint8_t f  = (uint8_t)(lo << 4);            /* blend fraction 0..240 */
    crgb_t a = pal[hi];
    crgb_t b = pal[(hi + 1) & 0x0F];
    crgb_t o;
    o.r = scale8(blend8(a.r, b.r, f), bri);
    o.g = scale8(blend8(a.g, b.g, f), bri);
    o.b = scale8(blend8(a.b, b.b, f), bri);
    return o;
}
```

The `bri` modulation lets effects fade the palette out (e.g. running
lights uses sin-shaped brightness modulation; the palette color stays
constant, only intensity changes).

---

## A real port: WLED's `mode_breath`

Let me walk through one concrete port end to end. WLED's source
(`FX.cpp:432`):

```cpp
uint16_t mode_breath() {
  uint16_t var = 0;
  uint16_t counter = (strip.now * ((SEGMENT.speed >> 3) + 10));
  counter = (counter >> 2) + (counter >> 4);
  if (counter < 16384) {
    if (counter > 8192) counter = 8192 - (counter - 8192);
    var = sin16(counter) / 103;
  }
  uint8_t lum = 30 + var;
  for (int i = 0; i < SEGLEN; i++) {
    SEGMENT.setPixelColor(i,
      color_blend(SEGCOLOR(1),
                  SEGMENT.color_from_palette(i, true, PALETTE_SOLID_WRAP, 0),
                  lum));
  }
  return FRAMETIME;
}
```

Apply the porting recipe:

| WLED                            | Badge                                   |
|---------------------------------|-----------------------------------------|
| `SEGMENT.setPixelColor(i, c)`   | `vstrip_set(i, c)` (writes virtual strip) |
| `SEGMENT.color_from_palette(i, true, …, mcol)` | `palette_lookup(palette, idx, bri)`, with `idx = (i*255)/SEGLEN` |
| `SEGCOLOR(1)`                   | We don't have user color slots → drop the blend, modulate palette by lum directly |
| `sin16(x) / 103`                | `sin8(x>>8)` and remap to 0..225 (we don't have `sin16`; the resolution loss is invisible after downsampling to 4 LEDs) |
| `strip.now`                     | `millis` (extern from main.c)           |
| `return FRAMETIME`              | drop — dispatcher paces frames          |
| add at end                      | `vstrip_render()`                        |

Result (live in `wled_fx.c`):

```c
static void mode_breath(void) {
    uint16_t counter = (uint16_t)(((uint32_t)millis * ((SEGMENT.speed >> 3) + 10)) >> 6);
    uint8_t  s   = sin8((uint8_t)counter);
    uint16_t lum = 30u + ((uint16_t)s * 225u >> 8);
    if (lum > 255) lum = 255;
    for (uint16_t i = 0; i < SEGLEN; i++) {
        uint8_t pidx = (uint8_t)((i * 255) / SEGLEN);
        vstrip_set(i, palette_lookup((wled_palette_t)SEGMENT.palette, pidx, (uint8_t)lum));
    }
    vstrip_render();
}
```

That's a faithful port. About 15 lines of C, ~150 bytes of flash. The
visual matches WLED — slow palette breath, never quite to black, never
washed out.

The find-and-replace was *mechanical*: there was no judgment about how
breath should look on 4 LEDs vs N LEDs, no rewriting of the algorithm, no
re-tuning of constants. The `SEGLEN=16` virtual strip + downsampler does
all that work invisibly.

---

## The dispatcher

```c
void wled_fx_dispatch(uint8_t mode_id) {
    if (mode_id >= WLED_FX_COUNT) return;
    static uint32_t last_frame = 0;
    uint32_t now = millis;
    if ((now - last_frame) < WLED_FRAME_MS) return;   /* 60 fps gate */
    last_frame = now;
    mode_table[mode_id]();
    SEGENV.call++;                                     /* WLED contract */
}
```

`mode_table` is a `wled_mode_fn_t mode_table[WLED_FX_COUNT]` array of
function pointers — 16 entries currently, indexed 0..15 (which map to
firmware effect modes 19..34). The badge's main loop calls
`wled_fx_dispatch(effect_mode - 19)` whenever the user is on a WLED
mode.

Adding an effect = appending one line to `mode_table[]` and bumping
`WLED_FX_COUNT`. Two-line change.

---

## What works on 4 LEDs vs what doesn't

| Category | Verdict | Why |
|---|---|---|
| Slow color wash (breath, pacifica, pride, lake, bpm) | **Identical to WLED** | Every pixel gets the same color at any moment; downsampling is exact |
| Spatial waves (running_lights, plasma, gradient, palette_flow) | **Recognizable, smooth** | Virtual strip preserves wave motion; quartile averaging blends adjacent virtual pixels into each physical LED |
| Moving dot with trail (sinelon, comet, meteor) | **Works, slightly chunky** | Dot moves through quartiles smoothly; trail fades correctly |
| Sparkle effects (confetti, glitter, twinkles) | **Works, less dense** | 16 → 4 means fewer simultaneous sparkles, but the random-pixel-fade-to-black character survives |
| 2D effects (`mode_2D_*` family) | **Skipped for now** | Need a 4×4 virtual grid; future work |
| Effects using `inoise8` (Perlin noise) | **Skipped for now** | Adds ~1 KB flash for the gradient table; not worth it until we want 5+ such effects |
| Multiple SEGCOLOR slots (primary/secondary/tertiary) | **Simplified** | We use the palette as the color source; effects that needed a hardcoded "background color" got it folded into the palette logic |

The "skipped for now" items aren't technical impossibilities; they're
just not necessary for the dozen-and-a-half effects we shipped. The
shim has clean extension points for each.

---

## Memory budget — the actual receipts

```
   text     data      bss      dec      hex   filename
  47472        0     5580    53052     cf3c   build/DC29.elf
```

- **Flash (text):** 47,472 / 57,344 bytes (82.8% — **9.8 KB headroom**)
- **RAM (BSS):** 5,580 / 8,192 bytes (68.1% — **2.5 KB headroom**)

Per-effect cost (rough):
- Trivial (breath, confetti): ~150 B flash, 0 B RAM
- Medium (running_lights, juggle, lake): ~250 B flash, 0 B RAM
- Heavy (pacifica with whitecaps, pride2015 with all the beatsin88s): ~500 B flash, 0 B RAM
- New palette: +48 B flash

The whole WLED engine — shim, palettes, virtual strip, 16 effects —
landed in about **3.4 KB of additional flash** on top of the original
firmware. Budget remaining is enough for **roughly 25 more effect ports
or two more substantial features (2D framebuffer + Perlin LUT).**

---

## Importing a new WLED effect — the 10-minute recipe

This is the workflow we built the engine for. Step by step:

**1. Find the effect.** Browse [`wled00/FX.cpp`](https://github.com/Aircoookie/WLED/blob/main/wled00/FX.cpp).
Each effect is a function whose name starts with `mode_`. Pick one.

**2. Copy the function body** into `wled_fx.c`, just above the dispatch
table. Convert the signature:

```cpp
// WLED:
uint16_t mode_xxx() { ... return FRAMETIME; }
```

becomes

```c
// badge:
static void mode_xxx(void) { ... }
```

(Drop `return FRAMETIME` everywhere — the dispatcher paces frames.)

**3. Run it through the find-and-replace table:**

| WLED                                          | DC29 badge                                             |
|-----------------------------------------------|--------------------------------------------------------|
| `SEGMENT.setPixelColor(i, c)`                 | `vstrip_set(i, c)`                                     |
| `SEGMENT.fade_out(rate)` / `fadeToBlackBy(r)` | `vstrip_fade_to_black_by(r)`                           |
| `SEGMENT.fill(c)`                             | `vstrip_fill_solid(c)`                                 |
| `SEGMENT.blur(amount)`                        | `vstrip_blur(amount)`                                  |
| `SEGMENT.color_from_palette(i, true, …, m)`   | `palette_lookup(SEGMENT.palette, (i*255)/SEGLEN, m)`   |
| `CHSV(h, s, v)`                               | `chsv_to_rgb(h, s, v)`                                 |
| `CRGB(r, g, b)` / `CRGB::Black`               | `(crgb_t){r, g, b}` / `(crgb_t){0,0,0}`                |
| `strip.now`                                   | `millis`                                               |
| `sin16(x)`                                    | `sin8(x >> 8)` — accept the resolution loss            |
| `beatsin88(bpm88, lo, hi)`                    | `beatsin88(bpm88, lo, hi, millis)`                     |
| `random8(lim)`                                | `random8_max(lim)`                                     |
| `SEGENV.allocateData(N)`                      | use `SEGENV.data` (24-byte fixed buffer) — error if bigger |

**4. Wire the dispatch.** Append your function pointer to
`mode_table[]` in `wled_fx.c`. Bump `WLED_FX_COUNT` in `wled_fx.h`. Bump
`NUM_EFFECT_MODES` in `main.h`.

**5. Add Python bindings** (`dc29/protocol.py`): add an `EffectMode`
enum entry, a name in `EFFECT_NAMES`, and a description in
`EFFECT_DESCRIPTIONS`. The TUI and CLI pick it up automatically.

**6. Build & flash.** `make` in `Firmware/Source/DC29/`, then
`/flash-badge` (or `cp DC29.uf2 /Volumes/DC29Badge/`). About 30 seconds.

**7. Sanity-check the visual.** If it looks frozen, your timebase
overflowed (often a `uint16_t` cast issue). If it looks too fast, the
`SEGMENT.speed` derivation isn't honoring the user knob. If the palette
selector doesn't change anything, you forgot to route through
`palette_lookup`.

That's the whole loop. Most ports take less than 10 minutes from "I want
this effect" to "it's running on the badge."

---

## The four-layer architecture, restated

The engine has four layers, each independent:

1. **Math/random/beat shim** (`wled_fx.h`, `static inline`). Header-only.
   FastLED-canonical implementations of the primitives WLED expects.
   Adding a new primitive = one inline function.

2. **Virtual strip + dispatcher + palettes** (`wled_fx.c`, ~250 lines).
   The 16-pixel framebuffer, the box-average renderer, the 60 fps gate,
   the palette LUTs and lookup. Stable interface — you don't touch this
   when adding effects.

3. **Per-effect implementations** (`wled_fx.c`, ~350 lines for 16
   effects). Each effect is 10-40 lines. This is the layer that grows
   when you port more.

4. **Protocol/UI integration** (`dc29/protocol.py`, `dc29/tui/app.py`,
   `dc29/cli.py`). Python-side enum, TUI tab, CLI commands. Adding an
   effect = three lines here.

Layers 1 and 2 are *infrastructure* and don't change. Layer 3 is where
new effects land. Layer 4 is purely about exposing them to humans. This
is what makes the cost of "one more effect" stay roughly constant — it
doesn't compound, because the surface area each effect touches is small
and well-defined.

---

## Why this matters

A few things, in roughly increasing order of how-cool-is-this:

**1. Open source compounds across hardware boundaries.** WLED was written
for ESPs running with orders of magnitude more resources than this
badge. The community-developed effect catalog represents thousands of
person-hours of design, taste, and tuning. With ~840 lines of
compatibility shim, almost any WLED effect that doesn't depend on
features we don't have (Perlin noise, 2D framebuffer, multiple color
slots) is a 10-minute port. *We did not have to be good at LED effects
to ship Pacifica.* We just had to be good at translation.

**2. A six-year-old conference badge running 2024-era LED firmware.** The
DC29 badge shipped in August 2021. The ATSAMD21G16B is from 2014. The
Pride 2015 effect we ported is older than the chip, sure — but the
*pipeline* lets us track WLED's main branch indefinitely. Every new
effect Christian Schwinne and the WLED contributors merge becomes a
candidate for ten more minutes of porting work. The badge is ten years
old in 2031, and it still runs current effects.

**3. The 4-LED constraint stopped being a constraint.** Once you accept
the virtual-strip-downsample idea, "this badge has 4 LEDs" stops being
*the* limit. It's a downsampling step at the very end of the pipeline.
The badge could have 1 LED or 100; the engine doesn't really care.
Pacifica looks good at 4 because it's a slow color wash; running lights
look good at 4 because the wave motion survives the box-average. The
badge is a *low-resolution display*, not a fundamentally-different
device.

**4. The translation engine is portable.** Nothing in `wled_fx.c` is
SAMD21-specific other than `extern void led_set_color(...)`. Drop the
shim onto another small badge with another small LED count, point
`led_set_color` at its driver, and you've got the same port pipeline.

---

## Acknowledgements

- **WLED** ([Aircoookie/WLED](https://github.com/Aircoookie/WLED)) — the
  effect library and the API we shimmed. Licensed under EUPL v1.2; we
  do not redistribute their source, only re-implement the API surface
  and reference their algorithmic ideas.
- **FastLED** ([FastLED/FastLED](https://github.com/FastLED/FastLED)) —
  the underlying math primitives (sin8, scale8, the LCG, beat clock,
  the canonical color palettes). We replicate their algorithms
  bit-identically.
- **Mark Kriegsman** for the timeless effects that anchor the catalog
  (Pride 2015, Pacifica, Sinelon, Confetti, Juggle).
- **Mike (compukidmike)** for the original DC29 badge firmware that we
  forked to add the macropad + WLED layer.

---

## See also

- [`docs/WLED_PORTING_GUIDE.md`](./WLED_PORTING_GUIDE.md) — the *practical* porting cheat-sheet (find-and-replace table, color profile system, memory budget). If this document is the "why," that one is the "how."
- [`Firmware/Source/DC29/src/wled_fx.h`](../Firmware/Source/DC29/src/wled_fx.h) — the public API header
- [`Firmware/Source/DC29/src/wled_fx.c`](../Firmware/Source/DC29/src/wled_fx.c) — the engine + 16 ported effects
- [`dc29/protocol.py`](../dc29/protocol.py) — `EffectMode`, `WledPalette`, `WLED_PALETTE_LUTS`, the `0x01 'W'` command
- [`dc29/tui/app.py`](../dc29/tui/app.py) — the WLED-inspired TUI tab (`WledTab` class, ~280 lines)
