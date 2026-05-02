# Porting WLED to a DEF CON 29 Badge

A writeup of how we got 16 [WLED](https://github.com/Aircoookie/WLED) effects running on the DC29 badge, what the
"translation engine" actually looks like, and how to port your own.

The implementation is in two files:

- [`Firmware/Source/DC29/src/wled_fx.h`](../Firmware/Source/DC29/src/wled_fx.h) (205 lines, public API)
- [`Firmware/Source/DC29/src/wled_fx.c`](../Firmware/Source/DC29/src/wled_fx.c) (634 lines, the engine plus 16 ported effects)

## The hardware

The DC29 badge shipped at DEF CON in August 2021. Inside is an ATSAMD21G16B, an ARM
Cortex-M0+ at 48 MHz with 8 KB of RAM and 64 KB of flash. The bootloader takes the first
8 KB, so the application has 56 KB to play with. There's no FPU. There are four RGB LEDs
arranged as a 2×2 grid.

| Resource | Available | Practical impact |
|---|---|---|
| CPU | Cortex-M0+ @ 48 MHz | Fine for 60 fps |
| Flash | 56 KB usable | Hundreds of bytes per effect, not thousands |
| RAM | 8 KB | No malloc, no per-effect heap |
| FPU | none | Integer math only |
| LEDs | 4 | The hard constraint |

WLED was designed for ESP32/ESP8266 controllers driving strips of dozens to thousands of
LEDs. Its `FX.cpp` is around 11,000 lines and contains over 200 effects. Most of those
effects assume floating-point intermediates, hundreds of pixels of spatial resolution,
and heap-allocated scratch buffers. None of that is available here.

## The trick that made it work

If you take a WLED effect, set `SEGLEN = 4`, and let it write directly to four physical
LEDs, anything spatial looks broken. A "running lights" wave reduces to one pixel that
blinks. A color wipe is a four-step shuffle. The problem is that WLED effects encode
motion *spatially*, across many adjacent pixels. Four pixels just can't carry it.

The fix is to render every effect to a virtual 16-pixel strip in RAM, then box-average
each quartile of that strip down to one of the four physical LEDs.

```c
crgb_t vstrip[16];   /* 48 bytes in BSS */

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

That's the whole downsampler. Forty-eight bytes of RAM, one linear pass per frame,
and the visual consequence is that *temporal motion is preserved*. A wave moving across
the virtual strip becomes a wave moving across the physical LEDs, just at lower spatial
resolution. Each physical LED is a smooth blend of four virtual pixels' worth of motion.
Pacifica still looks like Pacifica, just downsampled.

For effects whose visual is purely temporal (every pixel the same color at any given
moment, modulated over time), the downsampling is mathematically exact. Pride 2015,
breath, the BPM effect: those look identical to WLED. For effects whose visual depends
on spatial detail across many pixels (running lights, sinelon, juggle), some detail is
lost in the box average, but the character of the motion survives.

The important part is that effect code never knows about the downsampling. It writes
to `SEGMENT.setPixelColor(i, c)` for `i = 0..15` exactly like it would on a real
WLED strip. The `vstrip_render()` call happens once at the end of every effect tick.

## The compatibility shim

WLED effects depend on a specific runtime contract: a small set of math primitives, a
particular RNG, a beat clock, and a "segment" struct that holds user knobs and per-effect
scratch state. To make WLED source code compile and behave correctly here, we reproduce
all of that.

Critically, the math primitives are bit-identical to the FastLED canonical implementations
that WLED uses. This isn't a stylistic choice. WLED effects are tuned around specific
waveforms. Pride 2015 squares the output of `sin8` to get its "bright peaks, dim valleys"
brightness envelope. If our `sin8` peak is even slightly less sharp than FastLED's, the
effect goes from "shimmering rainbow fire" to "pulsing rainbow." The same applies to
`scale8` rounding, the LCG random sequence, and the beat-clock phase calculation.

### sin8 (FastLED's 33-entry quarter-wave LUT)

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

Eight bytes of LUT, a quarter-wave mirrored four ways via two bit-tests, about
25 cycles on the M0+. Output is bit-identical to FastLED.

### scale8 (the FASTLED_SCALE8_FIXED form)

```c
static inline uint8_t scale8(uint8_t i, uint8_t s) {
    return (uint8_t)(((uint16_t)i * (1 + (uint16_t)s)) >> 8);
}
```

The `+1` matters. It makes `scale8(255, 255) == 255` exactly. The naive form
(`i * s >> 8`) gives 254. WLED's brightness ramps and gamma curves assume the
fixed form, and using the naive form will round-trip an apparently-clean
255 down to 254 in places it shouldn't.

### Random (FastLED's LCG)

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

Constants `2053` and `13849` are the canonical FastLED LCG. Effects that lean on
random sequences (confetti, twinkles, fire) produce the same pixel choices here
as on a real WLED controller from the same seed.

### Beat clock

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

WLED uses BPM as the natural way to express slow oscillations. `beatsin8(11, 60, 130)`
means "oscillate between 60 and 130 at 11 beats per minute," which is shorthand for
the kind of slow color drift you see in Pacifica. The one deviation from WLED's API
is that we pass `now` (the millis timestamp) explicitly instead of fetching it from
a global. It keeps the time source visible, and lets these helpers stay
header-inline without an extern.

### SEGMENT and SEGENV

WLED has a `Segment` class that holds per-segment user knobs (`speed`, `intensity`,
`palette`) and free-form scratch state (`aux0`, `aux1`, `step`, `data`, plus a
call counter `call`). We mirror it as a single global struct:

```c
typedef struct {
    uint8_t  speed;
    uint8_t  intensity;
    uint8_t  palette;
    uint8_t  custom1;
    uint16_t aux0, aux1;
    uint32_t step;
    uint32_t call;        /* zero on the first frame after a mode change */
    uint8_t  data[24];    /* replaces SEGENV.allocateData() heap calls */
} wled_seg_t;

extern wled_seg_t wled_seg;
#define SEGMENT  wled_seg
#define SEGENV   wled_seg
#define SEGLEN   16
```

`SEGENV.call == 0` is the WLED idiom for "first frame after a mode change, do
your one-time init." Our dispatcher zeros `call` on every mode change so any
`if (SEGENV.call == 0)` block ports across cleanly. The 24-byte `data` field
replaces `SEGENV.allocateData(N)`, which would normally allocate from the heap.
Twenty-four bytes covers everything we've ported so far. If a future port needs
more, the buffer grows.

### Palettes

WLED ships about 70 built-in palettes. We ship eight: rainbow, heat, ocean, lava,
pacifica, sunset, forest, party. Each is a 16-entry RGB table totaling 48 bytes
of flash. Pacifica's first layer, copied verbatim from `FX.cpp:4194`:

```c
static const crgb_t pal_pacifica1[16] = {
    {0x00,0x05,0x07},{0x00,0x04,0x09},{0x00,0x03,0x0B},{0x00,0x03,0x0D},
    {0x00,0x02,0x10},{0x00,0x02,0x12},{0x00,0x01,0x14},{0x00,0x01,0x17},
    {0x00,0x00,0x19},{0x00,0x00,0x1C},{0x00,0x00,0x26},{0x00,0x00,0x31},
    {0x00,0x00,0x3B},{0x00,0x00,0x46},{0x14,0x55,0x4B},{0x28,0xAA,0x50}
};
```

Lookup matches WLED's `ColorFromPalette(pal, idx, bri, LINEARBLEND)`:

```c
crgb_t palette_lookup_arr(const crgb_t pal[16], uint8_t idx, uint8_t bri) {
    uint8_t hi = (uint8_t)(idx >> 4);
    uint8_t lo = (uint8_t)(idx & 0x0F);
    uint8_t f  = (uint8_t)(lo << 4);
    crgb_t a = pal[hi];
    crgb_t b = pal[(hi + 1) & 0x0F];
    crgb_t o;
    o.r = scale8(blend8(a.r, b.r, f), bri);
    o.g = scale8(blend8(a.g, b.g, f), bri);
    o.b = scale8(blend8(a.b, b.b, f), bri);
    return o;
}
```

The `bri` parameter lets effects modulate the palette without changing the
hue. Running lights, for example, looks up the same palette index at every
LED but multiplies the result by a sin-shaped brightness envelope.

## A real port: WLED's `mode_breath`

Here is the original from `FX.cpp:432`:

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

To port it, run the source through this find-and-replace table:

| WLED                                          | Badge                                              |
|-----------------------------------------------|----------------------------------------------------|
| `SEGMENT.setPixelColor(i, c)`                 | `vstrip_set(i, c)`                                 |
| `SEGMENT.color_from_palette(i, true, ...)`    | `palette_lookup(SEGMENT.palette, idx, bri)` with `idx = (i*255)/SEGLEN` |
| `SEGCOLOR(1)`                                 | drop (we don't have user color slots) and modulate the palette by lum directly |
| `sin16(x) / 103`                              | `sin8(x>>8)` and remap into the 0..225 range |
| `strip.now`                                   | `millis` |
| `return FRAMETIME`                            | drop, the dispatcher paces frames |
| (add at end)                                  | `vstrip_render()` |

Result, live in `wled_fx.c`:

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

About 15 lines of C, around 150 bytes of flash. Visual matches WLED: slow palette
breath, never quite to black, never washed out.

The find-and-replace was *mechanical*. There was no judgment about how breath
should look on 4 LEDs versus 16 versus 100. The virtual strip and the box-average
do that work invisibly. We didn't have to be experts in LED effect design to
ship this; we just had to do the translation.

## The dispatcher

```c
void wled_fx_dispatch(uint8_t mode_id) {
    if (mode_id >= WLED_FX_COUNT) return;
    static uint32_t last_frame = 0;
    uint32_t now = millis;
    if ((now - last_frame) < WLED_FRAME_MS) return;
    last_frame = now;
    mode_table[mode_id]();
    SEGENV.call++;
}
```

`mode_table` is an array of function pointers, currently 16 entries. The badge's
main loop calls `wled_fx_dispatch(effect_mode - 19)` whenever the user is on a
WLED-mode effect (modes 19 through 34). Adding a new effect means appending one
line to `mode_table[]` and bumping `WLED_FX_COUNT`.

## What works on 4 LEDs and what doesn't

| Category | Result | Why |
|---|---|---|
| Slow color wash (breath, pacifica, pride, lake, bpm) | Identical to WLED | Every pixel gets the same color at any moment, so the box-average is exact |
| Spatial waves (running_lights, plasma, gradient, palette_flow) | Recognizable, smooth | The virtual strip preserves wave motion; quartile averaging blends it across physical LEDs |
| Moving dot with trail (sinelon, comet, meteor) | Works, slightly chunky | The dot moves through quartiles smoothly and the fade trail comes through |
| Sparkle (confetti, glitter, twinkles) | Works, less dense | Fewer simultaneous sparkles than on a 100-pixel strip, but the character holds |
| 2D effects (`mode_2D_*`) | Skipped for now | Would need a 4×4 virtual grid; the engine has clean room for it |
| Effects using `inoise8` (Perlin noise) | Skipped for now | Would add about 1 KB of flash for the gradient table; not worth it for a single port |
| Multiple SEGCOLOR slots (primary/secondary/tertiary user colors) | Simplified | We use the active palette as the color source instead |

The skipped items are not technical impossibilities. They just haven't been
necessary for the ports we've shipped. The engine has clean extension points
for each.

## Memory budget

The latest build:

```
   text     data      bss      dec      hex   filename
  47472        0     5580    53052     cf3c   build/DC29.elf
```

Flash is at 47,472 of 57,344 available bytes (83%). BSS is at 5,580 of 8,192
(68%). Headroom is roughly 9.8 KB of flash and 2.5 KB of RAM.

Per-effect cost varies. Trivial effects like breath or confetti cost about
150 bytes of flash and zero RAM. Medium-complexity ports (running lights,
juggle, lake) cost around 250 bytes. Heavy ones (Pacifica with whitecaps,
Pride 2015 with all its `beatsin88` calls) cost about 500 bytes. Each new
palette is another 48 bytes.

Total cost of the entire WLED layer (the shim, eight palettes, virtual strip,
dispatcher, sixteen ported effects) is about 3.4 KB on top of the original
firmware. There's room for roughly 25 more effect ports, or two substantial
features like a 2D framebuffer plus a Perlin noise table, before flash gets tight.

## Importing your own WLED effect

The whole point of the engine is that this is fast and mechanical.

1. Browse [`wled00/FX.cpp`](https://github.com/Aircoookie/WLED/blob/main/wled00/FX.cpp).
   Pick an effect. Functions starting with `mode_` are the ones you want.

2. Copy the function body into `wled_fx.c`, just above the dispatch table. Convert
   the signature from `uint16_t mode_xxx()` returning `FRAMETIME` to
   `static void mode_xxx(void)`. Drop the `return FRAMETIME` lines; the
   dispatcher handles pacing.

3. Run the source through this table:

   | WLED                                          | Badge                                              |
   |-----------------------------------------------|----------------------------------------------------|
   | `SEGMENT.setPixelColor(i, c)`                 | `vstrip_set(i, c)`                                 |
   | `SEGMENT.fade_out(r)` or `fadeToBlackBy(r)`   | `vstrip_fade_to_black_by(r)`                       |
   | `SEGMENT.fill(c)`                             | `vstrip_fill_solid(c)`                             |
   | `SEGMENT.blur(amount)`                        | `vstrip_blur(amount)`                              |
   | `SEGMENT.color_from_palette(i, true, ..., m)` | `palette_lookup(SEGMENT.palette, (i*255)/SEGLEN, m)` |
   | `CHSV(h,s,v)`                                 | `chsv_to_rgb(h,s,v)`                               |
   | `CRGB(r,g,b)` or `CRGB::Black`                | `(crgb_t){r,g,b}` or `(crgb_t){0,0,0}`             |
   | `strip.now`                                   | `millis`                                           |
   | `sin16(x)`                                    | `sin8(x>>8)` (accept the resolution loss)          |
   | `beatsin88(bpm88, lo, hi)`                    | `beatsin88(bpm88, lo, hi, millis)`                 |
   | `random8(lim)`                                | `random8_max(lim)`                                 |
   | `SEGENV.allocateData(N)`                      | use `SEGENV.data` (24 byte fixed buffer)           |

4. Wire the dispatch. Append your function to `mode_table[]` in `wled_fx.c`.
   Bump `WLED_FX_COUNT` in `wled_fx.h`. Bump `NUM_EFFECT_MODES` in `main.h`.

5. Add Python bindings in `dc29/protocol.py`: an `EffectMode` enum entry, a
   name in `EFFECT_NAMES`, and a description in `EFFECT_DESCRIPTIONS`. The
   TUI and CLI pick it up from there.

6. Build (`make` in `Firmware/Source/DC29/`), flash (`/flash-badge` or drop
   the `.uf2` on the bootloader drive), test.

If something looks frozen, your timebase probably overflowed (often a
`uint16_t` cast). If it's too fast or too slow, the `SEGMENT.speed`
derivation needs a tweak. If the palette selector doesn't change anything,
you forgot to route a color through `palette_lookup`.

Most ports run about ten minutes from "I want this effect" to "it's running
on the badge."

## The four layers

The engine is four independent layers:

1. **Math, random, beat clock** in `wled_fx.h`, all `static inline`. FastLED-canonical
   implementations of the primitives WLED expects. Adding a new primitive is one
   inline function.

2. **Virtual strip, palettes, dispatcher** in `wled_fx.c`, around 250 lines. The
   16-pixel framebuffer, the box-average renderer, the 60 fps gate, the palette
   LUTs, and the lookup function. Stable interface; you don't touch this when
   adding effects.

3. **Per-effect implementations** in `wled_fx.c`, around 350 lines for 16 effects.
   Each effect is 10 to 40 lines. This is the layer that grows.

4. **Protocol and UI integration** in `dc29/protocol.py`, `dc29/tui/app.py`, and
   `dc29/cli.py`. Python-side enum, TUI tab, CLI commands. Adding an effect
   touches three lines here.

Layers 1 and 2 are infrastructure and don't change. Layer 3 is where new effects
land. Layer 4 is purely about exposing effects to humans. Cost per added effect
stays roughly flat because the surface area each effect touches is small and
well-defined.

## Closing thought

The DC29 badge is from 2021. The ATSAMD21G16B is a 2014-era chip. The Pride
2015 effect we ported is older than the chip. None of that matters. The
shim layer means every new effect that lands in WLED's main branch is a
candidate for ten more minutes of porting work. Whatever WLED looks like
in 2031, this badge can probably run it.

## Acknowledgements

- [WLED](https://github.com/Aircoookie/WLED) by Christian Schwinne and contributors. Licensed under EUPL v1.2. We re-implement the API surface and reference algorithmic ideas; we don't redistribute their source.
- [FastLED](https://github.com/FastLED/FastLED) for the underlying math primitives (`sin8`, `scale8`, the LCG, the beat clock, the canonical palettes), reproduced bit-identically.
- Mark Kriegsman for the timeless effects that anchor the catalog (Pride 2015, Pacifica, Sinelon, Confetti, Juggle).
- Mike (compukidmike) for the original DC29 badge firmware that we forked.

## See also

- [`docs/WLED_PORTING_GUIDE.md`](./WLED_PORTING_GUIDE.md), the practical cheat sheet (find-and-replace table, color profiles, memory budget). If this page is the "why," that one is the "how."
- [`Firmware/Source/DC29/src/wled_fx.h`](../Firmware/Source/DC29/src/wled_fx.h), the public API
- [`Firmware/Source/DC29/src/wled_fx.c`](../Firmware/Source/DC29/src/wled_fx.c), the engine and the 16 ported effects
- [`dc29/protocol.py`](../dc29/protocol.py), the Python-side enums and palette mirror
- [`dc29/tui/app.py`](../dc29/tui/app.py), the WLED-inspired TUI tab (`WledTab` class)
