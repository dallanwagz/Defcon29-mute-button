# WLED → DC29 Badge Effect Porting Guide

This guide explains how to port effects from
[Aircoookie/WLED](https://github.com/Aircoookie/WLED)'s `wled00/FX.cpp` to
the badge with minimal effort. The badge runs a small WLED-compatible API
shim (`Firmware/Source/DC29/src/wled_fx.{h,c}`) so most effects port with
mechanical find-and-replace edits.

If you remember nothing else: **find an effect you like in WLED's `FX.cpp`,
copy the `mode_xxx` function body, run it through the rewrite table below,
add a dispatch entry, build, flash. ~10 minutes per effect.**

---

## What the shim provides

The shim mirrors the WLED + FastLED runtime contract closely enough that
existing effect source compiles with only the rewrites in §3 below.

### Math & utilities (FastLED-canonical, bit-identical)
```
sin8, cos8, triwave8, quadwave8, cubicwave8, ease8InOutQuad, ease8InOutCubic
qadd8, qsub8, scale8, scale8_video, nscale8x3_video
blend8, lerp8by8
random8, random8_max, random8_range, random16, random16_max
beat8, beat88, beatsin8, beatsin88
```
All `static inline` in `wled_fx.h`. The `sin8` LUT is the FastLED 33-entry
quarter-wave table — same waveform as WLED. Random uses the FastLED LCG
`x = 2053·x + 13849`.

### Color & palettes
```
crgb_t                          // {r,g,b} struct (no alpha, no white channel)
chsv_to_rgb(h, s, v)            // CHSV → CRGB
color_blend(a, b, amt)          // 0=all a, 255=all b
palette_lookup(pal, idx, bri)   // ColorFromPalette(pal, idx, bri, LINEARBLEND)
palette_lookup_arr(arr16, idx, bri)
```
Five 16-entry palettes: `WLED_PAL_RAINBOW`, `_HEAT`, `_OCEAN`, `_LAVA`,
`_PACIFICA`. Add more by extending `palette_table[]` in `wled_fx.c`.

### SEGMENT / SEGENV
A single global `wled_seg_t` aliased as `SEGMENT` and `SEGENV`. Fields:
- `speed`, `intensity`, `palette`, `custom1` — user knobs (0..255 each)
- `aux0`, `aux1` — uint16 free-form state
- `step` — uint32 free-form state
- `call` — call counter (==0 on first frame after a mode change; standard
  WLED idiom for one-time init)
- `data[24]` — small persistent buffer (replaces WLED's heap-allocated
  `SEGENV.data`)

### Virtual strip framebuffer
`SEGLEN == 16` virtual pixels. After your effect writes `vstrip_set(i, c)`
for i in 0..15, `vstrip_render()` box-averages each quartile down to one of
the 4 physical LEDs. This is the magic that makes spatial-motion effects
(running_lights, juggle, sinelon) look right on 4 LEDs.
```
vstrip_set, vstrip_get, vstrip_fill_solid
vstrip_fade_to_black_by, vstrip_blur, vstrip_render
```

---

## When does a WLED effect "work" on 4 LEDs?

| Spatial pattern | Will it work? | Strategy |
|------|------|------|
| Effect sets every pixel to the same color (breath, pacifica, hue cycle) | Yes, looks identical to WLED | Direct port |
| Effect has a slow spatial wave (running_lights, plasma, gradient) | Yes, with virtual strip | Port verbatim, render at SEGLEN=16 |
| Effect has a moving "head" (sinelon, comet, single dot) | Mostly yes | Virtual strip; the head moves through quartiles smoothly |
| Effect is a single sparkle/blink (confetti, twinkle, fireworks) | Yes | Render to physical strip directly via SEGLEN=4 if you want, otherwise virtual strip is fine |
| 2D effects (`mode_2D_*` family in WLED) | Skip for now | Would need a 4×4 virtual grid; future work |
| Effects that need `inoise8` / Perlin | Skip for now | `inoise8` LUT is large; add only if needed |
| Effects relying on `SEGMENT.beat88` / `sin16` for fine spatial detail | Yes, but expect downsampled fidelity | Acceptable on 4 LEDs |

If unsure: try it. Worst case it looks bad and you delete the dispatch
entry; nothing else is harmed.

---

## The Porting Recipe

### Step 1 — Find an effect you want

Browse [`wled00/FX.cpp`](https://github.com/Aircoookie/WLED/blob/main/wled00/FX.cpp).
Each effect is a function whose name starts with `mode_`. The
[WLED effects docs](https://kno.wled.ge/features/effects/) describe what
each looks like; cross-reference by name (e.g. "Two Dots" = `mode_two_dots`).

### Step 2 — Copy the function body into `wled_fx.c`

Add it just above the dispatch table at the bottom of the file. Convert
the signature:
```cpp
// WLED:
uint16_t mode_xxx() { ... return FRAMETIME; }
```
to:
```c
// badge:
static void mode_xxx(void) { ... }
```
Drop the `return FRAMETIME` lines. The dispatcher already paces frames.

### Step 3 — Run it through the find-and-replace table

| WLED / FastLED | DC29 badge | Notes |
|---|---|---|
| `SEGMENT.setPixelColor(i, color)` | `vstrip_set(i, color)` | `color` becomes `crgb_t` |
| `SEGMENT.fade_out(rate)` / `fadeToBlackBy(rate)` | `vstrip_fade_to_black_by(rate)` | |
| `SEGMENT.fill(color)` | `vstrip_fill_solid(color)` | |
| `SEGMENT.blur(amount)` | `vstrip_blur(amount)` | |
| `SEGMENT.color_from_palette(i, true, …, mcol)` | `palette_lookup((wled_palette_t)SEGMENT.palette, idx, mcol)` | `idx = (i*255)/SEGLEN` if `mapping=true` |
| `SEGCOLOR(0..2)` | hard-code `crgb_t {0,0,0}` (or add a user-color slot if you need it) | We don't carry per-segment user colors yet |
| `SEGPALETTE` | `(wled_palette_t)SEGMENT.palette` | |
| `CRGB(r,g,b)` | `crgb_t c = {r, g, b}` | |
| `CRGB::Black` | `(crgb_t){0,0,0}` | |
| `CHSV(h,s,v)` | `chsv_to_rgb(h, s, v)` | |
| `strip.now` | `millis` (extern from main.c — already imported in wled_fx.c) | |
| `SEGENV.allocateData(N)` | use `SEGENV.data` (24 B) — error out if effect needs more | |
| `sin16(x)` | `sin8(x >> 8)` upscaled if needed: `((sin8((x)>>8) << 8) - 0x8000)` | Acceptable on 4 LEDs |
| `beatsin88(bpm88, lo, hi)` | `beatsin88(bpm88, lo, hi, millis)` | Pass `millis` explicitly |
| `beatsin8(bpm, lo, hi)` | `beatsin8(bpm, lo, hi, millis)` | Pass `millis` explicitly |
| `random8(lim)` | `random8_max(lim)` | |
| `random8(lo, hi)` | `random8_range(lo, hi)` | |
| `is_2D()` checks | not supported — pick a non-2D effect | |

If your effect uses helpers we don't have (`inoise8`, `gamma8`, etc.),
either implement them or skip the effect.

### Step 4 — Wire the dispatch entry

In `wled_fx.c`, append your function pointer to `mode_table[]`. Bump
`WLED_FX_COUNT` in `wled_fx.h`. Bump `NUM_EFFECT_MODES` in `main.h`.

In `dc29/protocol.py`, add:
- An `EffectMode` enum entry with the next ID (e.g. `MY_FX = 25`)
- An `EFFECT_NAMES[MY_FX] = "my-fx"` line
- An `EFFECT_DESCRIPTIONS[MY_FX] = "..."` line

### Step 5 — Build & flash

```sh
cd Firmware/Source/DC29
make            # text size should still be under ~57 KB
```
Use `/flash-badge` to flash. Cycle through effects with the long-press
chord, or send `0x01 'E' <id>` over USB CDC.

### Step 6 — Sanity-check the visual

Most ports look right on first try. If the effect:
- **Looks frozen** — your timebase probably overflowed. WLED uses `uint16_t`
  for `strip.now`-derived counters; we use `millis` (uint32). If you see
  `(uint16_t)(strip.now - sLastFrame)`, mirror that cast.
- **Looks too fast / too slow** — adjust the `SEGMENT.speed` derivation.
  Defaults are speed=128, intensity=128.
- **Looks dim** — check you're not accidentally double-fading
  (`fade_to_black_by` followed by `palette_lookup` with low `bri`).

---

## Worked example: porting WLED's `mode_breath`

WLED source (`FX.cpp:432`):
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

After the recipe (the actual code in `wled_fx.c`):
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

Mechanical changes only:
- `setPixelColor` → `vstrip_set`
- `color_blend(SEGCOLOR(1), …, lum)` → drop the blend, just modulate the
  palette color by lum (we don't have SEGCOLOR slot 1 yet)
- `color_from_palette(i, true, …)` → `palette_lookup(palette, idx, bri)`
  with `idx = (i * 255) / SEGLEN`
- `sin16(counter) / 103` → `sin8(counter)` and remap to 0..225 range
- Add `vstrip_render()` at the end

That's it. Visual is faithful: slow breath, palette-colored, never quite
to black.

---

## Color profiles (palettes & runtime knobs)

WLED segments have three runtime knobs — `palette`, `speed`, `intensity` —
that the user can change without restarting the effect. The badge mirrors
this: every WLED-ported effect (mode 19+) honors these three knobs.

### Setting them from Python
```python
from dc29 import Badge
from dc29.protocol import WledPalette, EffectMode

badge = Badge()                              # opens /dev/tty.usbmodem*
badge.set_effect_mode(EffectMode.PACIFICA)   # 21
badge.set_wled(speed=180, intensity=200, palette=WledPalette.OCEAN)
```

### Setting them from raw bytes (any tool that can write to USB CDC)
```
0x01 'E' 21                          → switch to pacifica
0x01 'W' 0xB4 0xC8 0x02              → speed=180, intensity=200, palette=OCEAN
```

### The 8 built-in palettes
| ID | Name | Look |
|----|------|------|
| 0 | RAINBOW | Full spectrum, FastLED canonical |
| 1 | HEAT | Black → red → orange → yellow → white |
| 2 | OCEAN | Navy → cyan → sky |
| 3 | LAVA | Black → deep red → orange → yellow → white |
| 4 | PACIFICA | WLED's hand-tuned ocean |
| 5 | SUNSET | Yellow → orange → magenta → indigo |
| 6 | FOREST | Deep greens with brown highlights |
| 7 | PARTY | Saturated pinks/oranges/yellows/blues |

### Adding a new palette

1. In `wled_fx.h`, append `WLED_PAL_MYNAME = N` to the `wled_palette_t`
   enum; bump `WLED_PAL_COUNT`.
2. In `wled_fx.c`, define a `static const crgb_t pal_myname[16] = {...}` and
   append a pointer to `palette_table[]`.
3. In `dc29/protocol.py`, add `MYNAME = N` to `WledPalette` and a name to
   `WLED_PALETTE_NAMES`.

That's it — every WLED-ported effect picks it up automatically because
they all read `SEGMENT.palette` via `palette_lookup()`.

### When porting, make your effect palette-aware

Replace any `CHSV(h,s,v)` or `color_wheel(idx)` with:
```c
palette_lookup((wled_palette_t)SEGMENT.palette, idx, bri)
```
Hard-coded palettes are fine when they're part of an effect's identity
(e.g. pacifica must use the pacifica palette). For everything else, route
through `SEGMENT.palette` so users get the WLED experience: pick an
effect, then pick a color profile.

### Effect that ignores palette? Not a bug.

Modes 1–18 (the hand-rolled effects) and the pacifica/pride ports use
fixed colors by design. If you want palette-controlled versions, port the
hand-rolled effect into `wled_fx.c` and route its color through
`palette_lookup`.

---

## Memory budget

After 16 ported effects + 8 palettes, the firmware uses
**47,472 / 57,344 flash bytes** and **5,580 / 8,192 RAM bytes**.
Headroom: ~9.9 KB flash + 2.5 KB RAM.

Per-effect cost (rough):
- Trivial effect (breath, confetti): ~150 B flash, 0 B RAM
- Medium (running_lights, juggle): ~250 B flash, 0 B RAM
- Heavy (pacifica, pride): ~500 B flash, 0 B RAM (uses `SEGENV.aux*/step`)
- Effect with new palette: +48 B flash per palette

So we have headroom for ~25–40 more effects before flash gets tight, and
RAM is essentially free (vstrip + SEGENV are already allocated).

---

## Future work (not yet implemented)

- **`inoise8` / `inoise16`** — Perlin noise, used by ~20% of WLED effects.
  Adds ~1 KB flash for the gradient table. Worth it once we want
  `mode_noisefire`, `mode_polar_lights`, etc.
- **2D framebuffer** — for `mode_2D_*` effects. Allocate `crgb_t v2d[4][4]`
  (48 B) and a `v2d_render()` that maps the 4 corners to the 4 physical
  LEDs.
- **Multiple SEGCOLOR slots** — let the user pick base/secondary colors
  via a `0x01 'W' c0 r g b` command. Many effects use `SEGCOLOR(0)` and
  `SEGCOLOR(1)` for "primary" and "background".
- **Speed/intensity/palette runtime control** — add `0x01 'W' s i p` to
  set `SEGMENT.speed/intensity/palette` on the fly. Currently they sit
  at compile-time defaults (128/128/RAINBOW).

---

## Reference

- WLED source: <https://github.com/Aircoookie/WLED>
- FastLED math primitives: <https://github.com/FastLED/FastLED/blob/master/src/lib8tion.h>
- WLED effect docs: <https://kno.wled.ge/features/effects/>
- Mark Kriegsman's effect demos: <https://gist.github.com/kriegsman>
