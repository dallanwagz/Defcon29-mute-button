/* wled_fx.h — WLED-compatible effect framework for the DC29 badge.
 *
 * This header provides a thin shim over the WLED / FastLED API surface so
 * effects can be ported from Aircoookie/WLED's wled00/FX.cpp with mostly-
 * mechanical edits (see docs/WLED_PORTING_GUIDE.md).  All math primitives
 * are bit-identical to the FastLED lib8tion canonical implementations, so a
 * sin8(t) call here returns the same value as a sin8(t) call in WLED.
 *
 * Pipeline:
 *   1. Effect writes to a 16-pixel "virtual strip" via vstrip_set(...).
 *   2. After the effect finishes, vstrip_render() box-averages each quartile
 *      down to one of the four physical LEDs.
 *   3. Effects whose visual is purely temporal (breath, pacifica) skip the
 *      virtual strip and write the four physical LEDs directly.
 *
 * Memory: 48 B for the virtual framebuffer + ~40 B for SEGENV state.
 *
 * Reference:
 *   - WLED FX.cpp / FX.h on Aircoookie/WLED@main
 *   - FastLED lib8tion (sin8 LUT, scale8 fixed-point, beat clock)
 */

#ifndef WLED_FX_H
#define WLED_FX_H

#include <stdint.h>
#include <stdbool.h>

/* Virtual-strip length.  16 = good motion fidelity, downsamples 4:1 to the
 * physical LEDs.  Don't change without auditing vstrip_render(). */
#define WLED_VSTRIP_LEN  16
#define WLED_PHYS_LEDS    4
#define WLED_FRAME_MS    16   /* ~60 fps tick — same as WLED FRAMETIME */

typedef struct { uint8_t r, g, b; } crgb_t;

/* Built-in palettes.  Indices match the order in palette_table[] in wled_fx.c.
 * Add new palettes by appending here AND to palette_table[] — nothing else. */
typedef enum {
	WLED_PAL_RAINBOW   = 0,
	WLED_PAL_HEAT      = 1,
	WLED_PAL_OCEAN     = 2,
	WLED_PAL_LAVA      = 3,
	WLED_PAL_PACIFICA  = 4,
	WLED_PAL_SUNSET    = 5,
	WLED_PAL_FOREST    = 6,
	WLED_PAL_PARTY     = 7,
	WLED_PAL_COUNT     = 8
} wled_palette_t;

/* SEGMENT/SEGENV — single global mirroring WLED's per-segment state.
 * speed/intensity/palette are user-tunable via 0x01 'W' commands (TBD).
 * Defaults in wled_fx.c. */
typedef struct {
	uint8_t  speed;        /* 0..255 — most effects derive their timebase from this */
	uint8_t  intensity;    /* 0..255 — per-effect "amount" (fade rate, spark count, etc.) */
	uint8_t  palette;      /* wled_palette_t */
	uint8_t  custom1;      /* spare for effects that want a third knob */

	uint16_t aux0;         /* free-form 16-bit state (preserved across frames) */
	uint16_t aux1;
	uint32_t step;         /* free-form 32-bit state */
	uint32_t call;         /* per-mode call counter — ==0 on first call after mode change */

	uint8_t  data[24];     /* small persistent buffer (replaces SEGENV.data heap) */
} wled_seg_t;

extern wled_seg_t wled_seg;

/* WLED naming: SEGMENT and SEGENV both expand to the current segment.  We
 * keep them as macros so ported effect source compiles unchanged. */
#define SEGMENT       wled_seg
#define SEGENV        wled_seg
#define SEGLEN        WLED_VSTRIP_LEN
#define FRAMETIME     WLED_FRAME_MS
#define SEGPALETTE    wled_seg.palette

/* ─── Math primitives (FastLED lib8tion, canonical) ────────────────────────
 * All static inline so the compiler can fold constants and avoid call
 * overhead on Cortex-M0+.  Math choices match FastLED's FASTLED_SCALE8_FIXED
 * mode, which is the convention WLED ships with. */

static inline uint8_t qadd8(uint8_t a, uint8_t b) {
	uint16_t t = (uint16_t)a + b;
	return t > 255 ? 255 : (uint8_t)t;
}
static inline uint8_t qsub8(uint8_t a, uint8_t b) {
	return a > b ? (uint8_t)(a - b) : 0;
}
/* scale8(i, s) = i * (s+1) / 256 — exact 255*255→255, FASTLED_SCALE8_FIXED form. */
static inline uint8_t scale8(uint8_t i, uint8_t s) {
	return (uint8_t)(((uint16_t)i * (1 + (uint16_t)s)) >> 8);
}
/* scale8_video(i, s) = scale8 but never returns 0 if both inputs nonzero. */
static inline uint8_t scale8_video(uint8_t i, uint8_t s) {
	uint8_t j = (uint8_t)(((uint16_t)i * s) >> 8);
	return j + (uint8_t)((i && s) ? 1 : 0);
}
static inline void nscale8x3_video(uint8_t *r, uint8_t *g, uint8_t *b, uint8_t s) {
	*r = scale8_video(*r, s); *g = scale8_video(*g, s); *b = scale8_video(*b, s);
}
/* lerp8by8(a, b, frac) = a + (b-a)*(frac+1)/256, FastLED canonical. */
static inline uint8_t lerp8by8(uint8_t a, uint8_t b, uint8_t f) {
	int16_t d = (int16_t)b - (int16_t)a;
	return (uint8_t)((int16_t)a + ((d * (1 + (int16_t)f)) >> 8));
}
/* blend8 — same math as lerp8by8 in FASTLED_SCALE8_FIXED. */
static inline uint8_t blend8(uint8_t a, uint8_t b, uint8_t amt) {
	return lerp8by8(a, b, amt);
}

/* ─── Random (FastLED LCG: x = 2053*x + 13849) ──────────────────────────── */
extern uint16_t wled_rand16seed;
static inline uint16_t random16(void) {
	wled_rand16seed = (uint16_t)(2053u * wled_rand16seed + 13849u);
	return wled_rand16seed;
}
static inline uint8_t random8(void) {
	uint16_t r = random16();
	return (uint8_t)((r & 0xFF) + (r >> 8));
}
static inline uint8_t random8_max(uint8_t lim) {
	return (uint8_t)(((uint16_t)random8() * lim) >> 8);
}
static inline uint16_t random16_max(uint16_t lim) {
	return (uint16_t)(((uint32_t)random16() * lim) >> 16);
}
static inline uint8_t random8_range(uint8_t lo, uint8_t hi) {
	return lo + random8_max(hi - lo);
}

/* ─── Trig (FastLED canonical sin8 LUT, 33-entry quarter wave) ──────────── */
uint8_t sin8(uint8_t theta);
static inline uint8_t cos8(uint8_t theta) { return sin8(theta + 64); }

/* ─── Waveforms (FastLED lib8tion) ──────────────────────────────────────── */
static inline uint8_t triwave8(uint8_t in) {
	if (in & 0x80) in = 255 - in;
	return (uint8_t)(in << 1);
}
static inline uint8_t ease8InOutQuad(uint8_t i) {
	uint8_t j = i;
	if (j & 0x80) j = 255 - j;
	uint8_t jj  = scale8(j, j);
	uint8_t jj2 = (uint8_t)(jj << 1);
	if (i & 0x80) jj2 = 255 - jj2;
	return jj2;
}
static inline uint8_t ease8InOutCubic(uint8_t i) {
	uint8_t ii  = scale8(i, i);
	uint8_t iii = scale8(ii, i);
	uint16_t r1 = (3 * (uint16_t)ii) - (2 * (uint16_t)iii);
	return (uint8_t)(r1 > 255 ? 255 : r1);
}
static inline uint8_t quadwave8(uint8_t in)  { return ease8InOutQuad(triwave8(in)); }
static inline uint8_t cubicwave8(uint8_t in) { return ease8InOutCubic(triwave8(in)); }

/* ─── Beat clock (FastLED beat.h) ──────────────────────────────────────────
 * `now` is millis from main.c.  bpm88 is bpm in 8.8 fixed-point.            */
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

/* ─── Color helpers ─────────────────────────────────────────────────────── */
crgb_t palette_lookup(wled_palette_t pal, uint8_t idx, uint8_t bri);
/* Same as palette_lookup but takes a raw 16-entry palette pointer.  Useful
 * for effects (e.g. pacifica) that ship their own inline palette tables. */
crgb_t palette_lookup_arr(const crgb_t pal[16], uint8_t idx, uint8_t bri);
crgb_t chsv_to_rgb(uint8_t h, uint8_t s, uint8_t v);
crgb_t color_blend(crgb_t a, crgb_t b, uint8_t amt);   /* 0=all a, 255=all b */

/* ─── beatsin88 (uint16 bpm in 8.8 fixed-point, returns scaled into [lo,hi]) ───
 * Provided as a function (not inline) because it's only used by faithful
 * WLED ports — keeping it out of the header trims compile times. */
uint16_t beatsin88(uint16_t bpm88, uint16_t lo, uint16_t hi, uint32_t now);

/* ─── Virtual strip framebuffer ─────────────────────────────────────────── */
void vstrip_set(uint16_t i, crgb_t c);
crgb_t vstrip_get(uint16_t i);
void vstrip_fill_solid(crgb_t c);
void vstrip_fade_to_black_by(uint8_t amount);
void vstrip_blur(uint8_t amount);
void vstrip_render(void);   /* downsample 16 → 4 physical LEDs */

/* ─── Dispatch ─────────────────────────────────────────────────────────── */
/* mode_id: 0..N-1 within the WLED-effect namespace (caller subtracts the
 * base offset, e.g., 19, before dispatching).  Increments SEGENV.call. */
void wled_fx_dispatch(uint8_t mode_id);

/* Reset SEGENV state — called from set_effect_mode() so each WLED effect
 * sees SEGENV.call == 0 on its first frame. */
void wled_fx_reset_state(void);

/* Number of WLED-ported effects available. */
#define WLED_FX_COUNT 16

#endif /* WLED_FX_H */
