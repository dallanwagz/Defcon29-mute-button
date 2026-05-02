/* wled_fx.c — WLED effect framework implementation for the DC29 badge.
 *
 * See wled_fx.h for the public API and pipeline overview.
 * See docs/WLED_PORTING_GUIDE.md for how to port new effects from
 * Aircoookie/WLED's wled00/FX.cpp source.
 */

#include "wled_fx.h"

/* main.c provides led_set_color(led_1based, rgb[3]) and the millis tick. */
extern volatile uint32_t millis;
extern void led_set_color(uint8_t led, uint8_t color[3]);

/* ─── Global SEGENV state + RNG seed ──────────────────────────────────── */
wled_seg_t wled_seg = {
	.speed     = 128,
	.intensity = 128,
	.palette   = WLED_PAL_RAINBOW,
	.custom1   = 0,
	.aux0 = 0, .aux1 = 0, .step = 0, .call = 0,
	.data = {0},
};

uint16_t wled_rand16seed = 0x1337;

/* ─── sin8 — FastLED canonical 33-entry quarter-wave LUT ──────────────────
 *
 * Reference: FastLED platforms/shared/trig8.h.  Returns 0..255 with
 *   sin8(0)   = 128 (midline rising)
 *   sin8(64)  = 255 (peak)
 *   sin8(128) = 128 (midline falling)
 *   sin8(192) = 0   (trough)
 *
 * The b_m16_interleave table is `(base, slope*16)` pairs for 4 quarter-wave
 * sections; together with a quarter-wave mirror trick this reproduces a
 * full-cycle sine in ~25 cycles on Cortex-M0+.  Output is bit-identical to
 * FastLED so any WLED effect that depends on sin8 wave shape ports cleanly. */
static const uint8_t b_m16_interleave[] = {
	  0,49,
	 49,41,
	 90,27,
	117,10
};
uint8_t sin8(uint8_t theta) {
	uint8_t offset = theta;
	if (theta & 0x40) offset = (uint8_t)(255 - offset);
	offset &= 0x3F;
	uint8_t secoffset = offset & 0x0F;
	if (theta & 0x40) secoffset++;
	uint8_t section = (uint8_t)(offset >> 4);
	uint8_t s2      = (uint8_t)(section * 2);
	const uint8_t *p = b_m16_interleave + s2;
	uint8_t b   = *p++;
	uint8_t m16 = *p;
	uint8_t mx  = (uint8_t)((m16 * secoffset) >> 4);
	int8_t  y   = (int8_t)mx + (int8_t)b;
	if (theta & 0x80) y = (int8_t)(-y);
	return (uint8_t)(y + 128);
}

/* ─── beatsin88 (FastLED beat.h / lib8tion.h analog) ──────────────────────
 * bpm88 = bpm in 8.8 fixed point.  Phase loops at exactly bpm88/256 cycles
 * per minute.  For low bpm88 values (under ~256), this oscillates very
 * slowly — multiple seconds per cycle — which is what WLED's slow color
 * drifts (e.g. pride2015's sat oscillation) rely on. */
uint16_t beatsin88(uint16_t bpm88, uint16_t lo, uint16_t hi, uint32_t now) {
	uint16_t beat = beat88(bpm88, now);
	/* Approximate sin16 via sin8: we lose ~7 bits of phase resolution but
	 * 4 LEDs after downsampling can't resolve it anyway. */
	uint8_t  phase8 = (uint8_t)(beat >> 8);
	uint8_t  s      = sin8(phase8);
	uint16_t s16    = (uint16_t)s << 8;            /* 0..65280 */
	uint32_t range  = (uint32_t)hi - (uint32_t)lo;
	return (uint16_t)(lo + ((s16 * range) >> 16));
}

/* ─── HSV → RGB (Adafruit / FastLED rainbow form, full saturation) ────── */
crgb_t chsv_to_rgb(uint8_t h, uint8_t s, uint8_t v) {
	/* Standard 6-region HSV.  Saturation/value scale linearly. */
	uint8_t region = (uint8_t)(h / 43);
	uint8_t rem    = (uint8_t)((h - region * 43) * 6);
	uint8_t p = (uint8_t)(((uint16_t)v * (255 - s)) >> 8);
	uint8_t q = (uint8_t)(((uint16_t)v * (255 - (((uint16_t)s * rem) >> 8))) >> 8);
	uint8_t t = (uint8_t)(((uint16_t)v * (255 - (((uint16_t)s * (255 - rem)) >> 8))) >> 8);
	crgb_t c;
	switch (region) {
		case 0: c.r = v; c.g = t; c.b = p; break;
		case 1: c.r = q; c.g = v; c.b = p; break;
		case 2: c.r = p; c.g = v; c.b = t; break;
		case 3: c.r = p; c.g = q; c.b = v; break;
		case 4: c.r = t; c.g = p; c.b = v; break;
		default:c.r = v; c.g = p; c.b = q; break;
	}
	return c;
}

crgb_t color_blend(crgb_t a, crgb_t b, uint8_t amt) {
	crgb_t o;
	o.r = blend8(a.r, b.r, amt);
	o.g = blend8(a.g, b.g, amt);
	o.b = blend8(a.b, b.b, amt);
	return o;
}

/* ─── Palette LUTs (16 entries each, indexed by wled_palette_t) ──────────
 * Rainbow / Heat / Lava are FastLED canonical palettes; Ocean is a hand-
 * picked WLED-flavor cool palette; Pacifica1 is from FX.cpp:4194 verbatim. */
static const crgb_t pal_rainbow[16] = {
	{0xFF,0x00,0x00},{0xD5,0x2A,0x00},{0xAB,0x55,0x00},{0xAB,0x7F,0x00},
	{0xAB,0xAB,0x00},{0x56,0xD5,0x00},{0x00,0xFF,0x00},{0x00,0xD5,0x2A},
	{0x00,0xAB,0x55},{0x00,0x56,0xAA},{0x00,0x00,0xFF},{0x2A,0x00,0xD5},
	{0x55,0x00,0xAB},{0x7F,0x00,0x81},{0xAB,0x00,0x55},{0xD5,0x00,0x2B}
};
static const crgb_t pal_heat[16] = {
	{0x00,0x00,0x00},{0x33,0x00,0x00},{0x66,0x00,0x00},{0x99,0x00,0x00},
	{0xCC,0x00,0x00},{0xFF,0x00,0x00},{0xFF,0x33,0x00},{0xFF,0x66,0x00},
	{0xFF,0x99,0x00},{0xFF,0xCC,0x00},{0xFF,0xFF,0x00},{0xFF,0xFF,0x33},
	{0xFF,0xFF,0x66},{0xFF,0xFF,0x99},{0xFF,0xFF,0xCC},{0xFF,0xFF,0xFF}
};
static const crgb_t pal_ocean[16] = {
	{0x19,0x19,0x70},{0x00,0x00,0x8B},{0x00,0x00,0xCD},{0x40,0xE0,0xD0},
	{0x00,0xCE,0xD1},{0x5F,0x9E,0xA0},{0x00,0xFF,0xFF},{0xAF,0xEE,0xEE},
	{0xAD,0xD8,0xE6},{0x87,0xCE,0xFA},{0x00,0xBF,0xFF},{0x1E,0x90,0xFF},
	{0x6A,0x5A,0xCD},{0x7B,0x68,0xEE},{0x00,0x00,0xFF},{0x41,0x69,0xE1}
};
static const crgb_t pal_lava[16] = {
	{0x00,0x00,0x00},{0x18,0x00,0x00},{0x40,0x00,0x00},{0x66,0x00,0x00},
	{0x99,0x00,0x00},{0xC0,0x00,0x00},{0xFF,0x00,0x00},{0xFF,0x40,0x00},
	{0xFF,0x80,0x00},{0xFF,0xC0,0x00},{0xFF,0xFF,0x00},{0xFF,0xFF,0x80},
	{0xFF,0xFF,0xCC},{0xFF,0xFF,0xFF},{0xFF,0xFF,0xFF},{0xFF,0xFF,0xFF}
};
static const crgb_t pal_pacifica1[16] = {
	{0x00,0x05,0x07},{0x00,0x04,0x09},{0x00,0x03,0x0B},{0x00,0x03,0x0D},
	{0x00,0x02,0x10},{0x00,0x02,0x12},{0x00,0x01,0x14},{0x00,0x01,0x17},
	{0x00,0x00,0x19},{0x00,0x00,0x1C},{0x00,0x00,0x26},{0x00,0x00,0x31},
	{0x00,0x00,0x3B},{0x00,0x00,0x46},{0x14,0x55,0x4B},{0x28,0xAA,0x50}
};
/* Sunset — warm yellow → orange → magenta → indigo, like a real sunset gradient. */
static const crgb_t pal_sunset[16] = {
	{0xFF,0xE0,0x60},{0xFF,0xC8,0x40},{0xFF,0xA0,0x20},{0xFF,0x78,0x10},
	{0xFF,0x50,0x10},{0xFF,0x30,0x20},{0xE0,0x20,0x40},{0xC0,0x10,0x60},
	{0x90,0x10,0x80},{0x60,0x10,0x80},{0x40,0x10,0x70},{0x20,0x10,0x60},
	{0x10,0x10,0x40},{0x05,0x05,0x20},{0x02,0x02,0x10},{0x00,0x00,0x05}
};
/* Forest — deep greens with brown highlights, like a forest canopy. */
static const crgb_t pal_forest[16] = {
	{0x00,0x40,0x00},{0x00,0x55,0x00},{0x00,0x6B,0x00},{0x00,0x80,0x00},
	{0x00,0x6B,0x00},{0x22,0x55,0x11},{0x44,0x4A,0x22},{0x55,0x40,0x33},
	{0x44,0x4A,0x22},{0x22,0x55,0x11},{0x00,0x6B,0x00},{0x00,0x80,0x00},
	{0x00,0x6B,0x00},{0x00,0x55,0x00},{0x00,0x40,0x00},{0x00,0x2A,0x00}
};
/* Party — saturated pinks, oranges, yellows, blues; FastLED-style party palette. */
static const crgb_t pal_party[16] = {
	{0xB3,0x00,0x83},{0xB3,0x06,0x76},{0xB3,0x0C,0x69},{0xB3,0x12,0x5C},
	{0xB3,0x18,0x4F},{0xB3,0x1F,0x42},{0xB3,0x25,0x35},{0xB3,0x2B,0x28},
	{0xB3,0x33,0x1B},{0xB3,0x4D,0x12},{0xB3,0x6E,0x09},{0xB3,0x90,0x00},
	{0x8C,0x96,0x09},{0x47,0x82,0x12},{0x09,0x6E,0x4D},{0x05,0x4D,0x82}
};

static const crgb_t * const palette_table[WLED_PAL_COUNT] = {
	pal_rainbow, pal_heat, pal_ocean, pal_lava, pal_pacifica1,
	pal_sunset, pal_forest, pal_party
};

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

crgb_t palette_lookup(wled_palette_t pal, uint8_t idx, uint8_t bri) {
	if (pal >= WLED_PAL_COUNT) pal = WLED_PAL_RAINBOW;
	return palette_lookup_arr(palette_table[pal], idx, bri);
}

/* ─── Virtual strip framebuffer (16 px → 4 physical LEDs by quartile avg) ─ */
static crgb_t vstrip[WLED_VSTRIP_LEN];

void vstrip_set(uint16_t i, crgb_t c) {
	if (i < WLED_VSTRIP_LEN) vstrip[i] = c;
}
crgb_t vstrip_get(uint16_t i) {
	if (i < WLED_VSTRIP_LEN) return vstrip[i];
	crgb_t z = {0, 0, 0};
	return z;
}
void vstrip_fill_solid(crgb_t c) {
	for (uint16_t i = 0; i < WLED_VSTRIP_LEN; i++) vstrip[i] = c;
}
void vstrip_fade_to_black_by(uint8_t amount) {
	uint8_t keep = (uint8_t)(255 - amount);
	for (uint16_t i = 0; i < WLED_VSTRIP_LEN; i++) {
		vstrip[i].r = scale8(vstrip[i].r, keep);
		vstrip[i].g = scale8(vstrip[i].g, keep);
		vstrip[i].b = scale8(vstrip[i].b, keep);
	}
}
void vstrip_blur(uint8_t amount) {
	/* 1D box-style blur: each pixel = (1-a)*self + a*0.5*(left+right).
	 * Cheap, no allocation, smooths spatial wave fronts before downsampling. */
	uint8_t a = amount, k = (uint8_t)(255 - amount);
	crgb_t prev = vstrip[0];
	for (uint16_t i = 0; i < WLED_VSTRIP_LEN; i++) {
		crgb_t cur  = vstrip[i];
		crgb_t next = (i + 1 < WLED_VSTRIP_LEN) ? vstrip[i + 1] : vstrip[i];
		uint8_t avg_r = (uint8_t)(((uint16_t)prev.r + next.r) >> 1);
		uint8_t avg_g = (uint8_t)(((uint16_t)prev.g + next.g) >> 1);
		uint8_t avg_b = (uint8_t)(((uint16_t)prev.b + next.b) >> 1);
		vstrip[i].r = (uint8_t)(scale8(cur.r, k) + scale8(avg_r, a));
		vstrip[i].g = (uint8_t)(scale8(cur.g, k) + scale8(avg_g, a));
		vstrip[i].b = (uint8_t)(scale8(cur.b, k) + scale8(avg_b, a));
		prev = cur;
	}
}

void vstrip_render(void) {
	/* Box-average 16→4 quartiles.  Each physical LED gets the mean of 4
	 * virtual pixels — preserves spatial motion fidelity within the
	 * quartile and gives WLED-on-a-16-strip downsampled visuals. */
	for (uint8_t led = 0; led < WLED_PHYS_LEDS; led++) {
		uint16_t sr = 0, sg = 0, sb = 0;
		for (uint8_t k = 0; k < 4; k++) {
			crgb_t c = vstrip[led * 4 + k];
			sr += c.r; sg += c.g; sb += c.b;
		}
		uint8_t out[3] = { (uint8_t)(sr >> 2), (uint8_t)(sg >> 2), (uint8_t)(sb >> 2) };
		led_set_color((uint8_t)(led + 1), out);
	}
}

/* ─── Effect: breath_wled (port of WLED mode_breath, FX.cpp:432) ──────── */
static void mode_breath(void) {
	/* WLED original drives a sin16 envelope at speed-modulated rate; on 4 LEDs
	 * sin8 is plenty.  Lum range 30..255 — never quite to black, never washed.
	 * Palette indexes per virtual pixel so different palettes give different
	 * breath colors. */
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

/* ─── Effect: pride (port of WLED mode_pride_2015, FX.cpp:1997) ───────── */
static void mode_pride(void) {
	if (SEGENV.call == 0) {
		SEGENV.aux0 = (uint16_t)millis;
		SEGENV.aux1 = 0;
		SEGENV.step = 0;
	}
	uint32_t now      = millis;
	uint16_t now16    = (uint16_t)now;
	uint16_t duration = (uint16_t)(now16 - SEGENV.aux0);
	SEGENV.aux0 = now16;

	uint16_t mult = (uint16_t)(SEGMENT.speed / 200 + 1);
	uint8_t  sat8        = (uint8_t)beatsin88((uint16_t)(87  * mult), 220, 250, now);
	uint8_t  brightdepth = (uint8_t)beatsin88((uint16_t)(341 * mult),  96, 224, now);
	uint16_t thetainc16  =          beatsin88((uint16_t)(203 * mult),  25 * 256, 40 * 256, now);
	uint8_t  msmult      = (uint8_t)beatsin88(                     147,  23,  60, now);
	uint16_t hueinc16    =          beatsin88((uint16_t)(113 * mult),    1, 3000, now);
	uint16_t huedrift    =          beatsin88((uint16_t)(400 * mult),    5,    9, now);

	SEGENV.step += (uint32_t)duration * msmult;
	SEGENV.aux1  = (uint16_t)(SEGENV.aux1 + (uint16_t)((uint32_t)duration * huedrift / 256));

	uint16_t hue16    = SEGENV.aux1;
	uint16_t btheta16 = (uint16_t)SEGENV.step;
	for (uint16_t i = 0; i < SEGLEN; i++) {
		hue16    = (uint16_t)(hue16 + hueinc16);
		btheta16 = (uint16_t)(btheta16 + thetainc16);
		uint8_t  b   = sin8((uint8_t)(btheta16 >> 8));
		uint16_t bri = (uint16_t)((uint16_t)b * b >> 8);
		bri = (bri * brightdepth >> 8) + (255 - brightdepth);
		if (bri > 255) bri = 255;
		vstrip_set(i, chsv_to_rgb((uint8_t)(hue16 >> 8), sat8, (uint8_t)bri));
	}
	vstrip_render();
}

/* ─── Effect: pacifica (port of WLED mode_pacifica, FX.cpp:4179) ──────── */
static void pacifica_one_layer(uint16_t cistart, uint16_t bri16, uint8_t ioff) {
	for (uint16_t i = 0; i < SEGLEN; i++) {
		uint16_t  sindex16 = (uint16_t)(cistart + i * 22u + ioff);
		uint8_t   sindex8  = (uint8_t)(sindex16 >> 8);
		uint8_t   wave     = sin8(sindex8);
		uint8_t   bri8     = (uint8_t)(((uint16_t)wave * (bri16 >> 8)) >> 8);
		crgb_t    add      = palette_lookup_arr(pal_pacifica1, sindex8, bri8);
		crgb_t    cur      = vstrip[i];
		cur.r = qadd8(cur.r, add.r);
		cur.g = qadd8(cur.g, add.g);
		cur.b = qadd8(cur.b, add.b);
		vstrip[i] = cur;
	}
}

static void mode_pacifica(void) {
	if (SEGENV.call == 0) {
		SEGENV.aux0 = 0; SEGENV.aux1 = 0; SEGENV.step = 0;
	}
	uint32_t now = millis;

	/* Background: dim teal, like deep ocean shadow. */
	crgb_t bg = {2, 6, 10};
	vstrip_fill_solid(bg);

	/* Two layers (WLED ships four; two is plenty for 4 physical LEDs and saves flash).
	 * Each layer's color-index-start drifts at its own slow rate. */
	SEGENV.aux0 = (uint16_t)(SEGENV.aux0 + beatsin8(11,  8, 13, now));
	SEGENV.aux1 = (uint16_t)(SEGENV.aux1 - beatsin8( 8,  5,  7, now));

	pacifica_one_layer(SEGENV.aux0, beatsin88(10 * 256,  60 * 256, 130 * 256, now),  0);
	pacifica_one_layer(SEGENV.aux1, beatsin88( 6 * 256,  80 * 256, 160 * 256, now), 64);

	/* Whitecaps: brighten pixels that have already accumulated lots of light.
	 * On 4 LEDs this gives the illusion of foam where waves overlap. */
	for (uint16_t i = 0; i < SEGLEN; i++) {
		crgb_t c = vstrip[i];
		uint16_t total = (uint16_t)c.r + c.g + c.b;
		if (total > 240) {
			uint8_t over = (uint8_t)((total - 240) >> 1);
			c.r = qadd8(c.r, over);
			c.g = qadd8(c.g, over);
			c.b = qadd8(c.b, over);
			vstrip[i] = c;
		}
	}
	vstrip_render();
}

/* ─── Effect: running_lights (port of WLED mode_running_lights, FX.cpp:594) ─ */
static void mode_running_lights(void) {
	uint8_t  x_scale = (uint8_t)(SEGMENT.intensity >> 2);
	uint32_t counter = ((uint32_t)millis * SEGMENT.speed) >> 9;
	for (uint16_t i = 0; i < SEGLEN; i++) {
		uint8_t a = (uint8_t)(i * x_scale - (uint8_t)counter);
		uint8_t s = sin8(a);
		/* Top half of sine, doubled — gives a one-way travelling pulse. */
		uint8_t b = (s > 128) ? (uint8_t)((s - 128) * 2) : 0;
		crgb_t base = palette_lookup((wled_palette_t)SEGMENT.palette,
		                              (uint8_t)((i * 255) / SEGLEN), 255);
		crgb_t lit  = { scale8(base.r, b), scale8(base.g, b), scale8(base.b, b) };
		vstrip_set(i, lit);
	}
	vstrip_render();
}

/* ─── Effect: juggle_wled (FastLED juggle demo) ────────────────────────── */
static void mode_juggle_wled(void) {
	vstrip_fade_to_black_by(20);
	uint32_t now = millis;
	uint8_t  dothue = 0;
	for (uint8_t i = 0; i < 8; i++) {
		uint16_t pos = beatsin8((uint8_t)(i + 7), 0, SEGLEN - 1, now);
		crgb_t add = chsv_to_rgb(dothue, 200, 255);
		crgb_t cur = vstrip_get(pos);
		cur.r = qadd8(cur.r, add.r);
		cur.g = qadd8(cur.g, add.g);
		cur.b = qadd8(cur.b, add.b);
		vstrip_set(pos, cur);
		dothue = (uint8_t)(dothue + 32);
	}
	vstrip_render();
}

/* ─── Effect: confetti_wled (Mark Kriegsman classic) ───────────────────── */
static void mode_confetti_wled(void) {
	vstrip_fade_to_black_by(10);
	uint8_t  pos = random8_max(SEGLEN);
	uint8_t  hue = (uint8_t)(SEGENV.aux0 + random8_max(64));
	crgb_t   add = chsv_to_rgb(hue, 200, 255);
	crgb_t   cur = vstrip_get(pos);
	cur.r = qadd8(cur.r, add.r);
	cur.g = qadd8(cur.g, add.g);
	cur.b = qadd8(cur.b, add.b);
	vstrip_set(pos, cur);
	SEGENV.aux0 += 1;            /* slowly drift base hue */
	vstrip_render();
}

/* ═══════════════════════════════════════════════════════════════════════════
 * Pass-2 ports — 10 more WLED effects.  All palette-aware so swapping the
 * palette via 0x01 'W' s i p changes their look immediately.
 * ═════════════════════════════════════════════════════════════════════════ */

/* ─── Effect: rainbow_wled (port of WLED mode_rainbow, FX.cpp:401) ────── */
static void mode_rainbow_wled(void) {
	/* Whole strip cycles through the active palette together.  Intensity
	 * blends with white toward 0 (washing the palette out into pastel). */
	uint32_t counter = ((uint32_t)millis * ((SEGMENT.speed >> 2) + 2)) >> 8;
	uint8_t  hue     = (uint8_t)counter;
	crgb_t   c       = palette_lookup((wled_palette_t)SEGMENT.palette, hue, 255);
	if (SEGMENT.intensity < 128) {
		uint8_t blend = (uint8_t)(128 - SEGMENT.intensity);
		crgb_t  white = {255, 255, 255};
		c = color_blend(c, white, (uint8_t)(blend << 1));
	}
	vstrip_fill_solid(c);
	vstrip_render();
}

/* ─── Effect: palette_flow — palette scrolls along the strip ──────────── */
static void mode_palette_flow(void) {
	/* Pure palette readout, scrolling at speed.  Best showcase for a new
	 * palette — stand still and watch one full sweep go by. */
	uint8_t shift = (uint8_t)(((uint32_t)millis * SEGMENT.speed) >> 8);
	for (uint16_t i = 0; i < SEGLEN; i++) {
		uint8_t idx = (uint8_t)(((i * 256) / SEGLEN) - shift);
		vstrip_set(i, palette_lookup((wled_palette_t)SEGMENT.palette, idx, 255));
	}
	vstrip_render();
}

/* ─── Effect: bpm (port of WLED mode_bpm, FX.cpp:3286) ────────────────── */
static void mode_bpm(void) {
	uint8_t stp  = (uint8_t)(millis / 20);
	uint8_t beat = beatsin8((uint8_t)(SEGMENT.speed | 1), 64, 255, millis);
	for (uint16_t i = 0; i < SEGLEN; i++) {
		uint8_t idx = (uint8_t)(stp + i * 2);
		vstrip_set(i, palette_lookup((wled_palette_t)SEGMENT.palette, idx, beat));
	}
	vstrip_render();
}

/* ─── Effect: glitter (FastLED palette + sparkle) ─────────────────────── */
static void mode_glitter(void) {
	/* Palette scroll background + occasional white sparkle. Intensity
	 * controls sparkle density, speed controls scroll rate. */
	uint8_t shift = (uint8_t)(((uint32_t)millis * SEGMENT.speed) >> 9);
	for (uint16_t i = 0; i < SEGLEN; i++) {
		uint8_t idx = (uint8_t)(shift + i * 16);
		vstrip_set(i, palette_lookup((wled_palette_t)SEGMENT.palette, idx, 200));
	}
	if (random8() < SEGMENT.intensity) {
		uint8_t pos = random8_max(SEGLEN);
		crgb_t  cur = vstrip_get(pos);
		cur.r = qadd8(cur.r, 120);
		cur.g = qadd8(cur.g, 120);
		cur.b = qadd8(cur.b, 120);
		vstrip_set(pos, cur);
	}
	vstrip_render();
}

/* ─── Effect: color_wipe (port of WLED color_wipe, FX.cpp:457, simplified) ─ */
static void mode_color_wipe(void) {
	/* Palette color fills the strip front-to-back, then a black wipe
	 * sweeps it back to off, then a new palette color fills.  Cycle
	 * period derives from speed. */
	uint32_t cycle_ms = 750u + (255u - SEGMENT.speed) * 30u;   /* 750..8400 ms */
	uint32_t perc     = millis % cycle_ms;
	uint16_t prog     = (uint16_t)((perc * 65535u) / cycle_ms);
	uint8_t  back     = (prog > 32767);
	if (back) prog   -= 32768;
	uint16_t ledIndex = (uint16_t)(((uint32_t)prog * (SEGLEN + 1)) >> 15);
	uint8_t  hue      = (uint8_t)(((uint32_t)millis / cycle_ms) * 37);
	crgb_t   fillc    = palette_lookup((wled_palette_t)SEGMENT.palette, hue, 255);
	crgb_t   off      = {0, 0, 0};
	for (uint16_t i = 0; i < SEGLEN; i++) {
		crgb_t c;
		if (i < ledIndex) c = back ? off    : fillc;
		else              c = back ? fillc  : off;
		vstrip_set(i, c);
	}
	vstrip_render();
}

/* ─── Effect: two_dots (port of WLED mode_two_dots, FX.cpp:636) ───────── */
static void mode_two_dots(void) {
	/* Two palette-colored dots oscillate at slightly different rates so
	 * they cross and separate over time.  Intensity = trail fade rate. */
	vstrip_fade_to_black_by((uint8_t)((SEGMENT.intensity >> 2) + 16));
	uint8_t bpm  = (uint8_t)((SEGMENT.speed >> 4) | 1);
	uint8_t pos1 = beatsin8(bpm,         0, SEGLEN - 1, millis);
	uint8_t pos2 = beatsin8(bpm + 1, 0, SEGLEN - 1, millis + 1000);
	crgb_t  c1   = palette_lookup((wled_palette_t)SEGMENT.palette,   0, 255);
	crgb_t  c2   = palette_lookup((wled_palette_t)SEGMENT.palette, 128, 255);
	crgb_t  cur1 = vstrip_get(pos1);
	cur1.r = qadd8(cur1.r, c1.r); cur1.g = qadd8(cur1.g, c1.g); cur1.b = qadd8(cur1.b, c1.b);
	vstrip_set(pos1, cur1);
	crgb_t  cur2 = vstrip_get(pos2);
	cur2.r = qadd8(cur2.r, c2.r); cur2.g = qadd8(cur2.g, c2.g); cur2.b = qadd8(cur2.b, c2.b);
	vstrip_set(pos2, cur2);
	vstrip_render();
}

/* ─── Effect: lake (port of WLED mode_lake, FX.cpp ~3389) ─────────────── */
static void mode_lake(void) {
	/* Two interfering wave fields of palette color, dim background.
	 * Looks like reflections on a lake.  Speed controls wave rate. */
	uint8_t sp     = (uint8_t)((SEGMENT.speed / 10) + 1);
	int8_t  wave1  = (int8_t)((int16_t)beatsin8(sp + 2, 0, 128, millis) - 64);
	int8_t  wave2  = (int8_t)((int16_t)beatsin8(sp + 1, 0, 128, millis) - 64);
	uint8_t wave3  = beatsin8((uint8_t)(sp + 2), 0, 80, millis);
	for (uint16_t i = 0; i < SEGLEN; i++) {
		uint8_t arg1  = (uint8_t)((i * 15) + (uint8_t)wave1);
		uint8_t arg2  = (uint8_t)((i * 23) + (uint8_t)wave2);
		uint8_t index = (uint8_t)((cos8(arg1) >> 1) + (cubicwave8(arg2) >> 1));
		uint8_t lum   = (index > wave3) ? (uint8_t)(index - wave3) : 0;
		vstrip_set(i, palette_lookup((wled_palette_t)SEGMENT.palette, index, lum));
	}
	vstrip_render();
}

/* ─── Effect: dancing_shadows (3 moving palette spotlights) ───────────── */
static void mode_dancing_shadows(void) {
	/* Three palette-colored "spotlights" drift independently, blended
	 * additively where they overlap.  Background goes dark between them. */
	vstrip_fill_solid((crgb_t){0, 0, 0});
	uint32_t now = millis;
	for (uint8_t s = 0; s < 3; s++) {
		uint8_t bpm = (uint8_t)((s + 1) * 4 + (SEGMENT.speed >> 5));
		uint8_t pos = beatsin8(bpm, 0, SEGLEN - 1, now + s * 7000u);
		uint8_t idx = (uint8_t)(s * 85 + (now >> 5));
		crgb_t  spot = palette_lookup((wled_palette_t)SEGMENT.palette, idx, 255);
		for (int8_t off = -2; off <= 2; off++) {
			int16_t p = (int16_t)pos + off;
			if (p < 0 || p >= (int16_t)SEGLEN) continue;
			uint8_t dist   = (uint8_t)(off < 0 ? -off : off);
			uint8_t weight = (uint8_t)(255 >> dist);
			crgb_t  cur    = vstrip_get((uint16_t)p);
			cur.r = qadd8(cur.r, scale8(spot.r, weight));
			cur.g = qadd8(cur.g, scale8(spot.g, weight));
			cur.b = qadd8(cur.b, scale8(spot.b, weight));
			vstrip_set((uint16_t)p, cur);
		}
	}
	vstrip_render();
}

/* ─── Effect: colortwinkles (port of WLED mode_colortwinkles, ~FX.cpp:3431) ─
 *
 * Per-pixel state machine in SEGENV.data[i] (1 byte per virtual pixel):
 *   0          = idle (off, may spawn next tick)
 *   1..127     = fading in
 *   128..255   = fading out
 * SEGENV.data is 24 B; we use 16 of those (one per virtual pixel). */
static void mode_colortwinkles(void) {
	if (SEGENV.call == 0) {
		for (uint8_t i = 0; i < 16; i++) SEGENV.data[i] = 0;
	}
	uint8_t spawn_chance = (uint8_t)((SEGMENT.intensity >> 2) + 1);
	uint8_t fade_speed   = (uint8_t)((SEGMENT.speed >> 5) + 2);
	for (uint16_t i = 0; i < SEGLEN; i++) {
		uint8_t ph = SEGENV.data[i];
		if (ph == 0) {
			if (random8() < spawn_chance) ph = 1;
		} else if (ph < 128) {
			uint16_t np = ph + fade_speed;
			ph = (np >= 128) ? 128 : (uint8_t)np;
		} else {
			uint16_t np = ph + fade_speed;
			ph = (np > 255) ? 0 : (uint8_t)np;
		}
		SEGENV.data[i] = ph;
		uint8_t bri  = (ph == 0) ? 0
		             : (ph < 128) ? (uint8_t)(ph << 1)
		                          : (uint8_t)((255 - ph) << 1);
		uint8_t pidx = (uint8_t)(i * 32 + (millis >> 6));
		vstrip_set(i, palette_lookup((wled_palette_t)SEGMENT.palette, pidx, bri));
	}
	vstrip_render();
}

/* ─── Effect: sinelon (port of WLED mode_sinelon, FX.cpp:3335) ────────── */
static void mode_sinelon(void) {
	/* A palette-colored dot traces a sine path through the strip, leaving
	 * a fade trail.  When the dot moves multiple pixels in one frame, fill
	 * the gap so motion stays smooth (matches WLED behavior). */
	vstrip_fade_to_black_by((uint8_t)((SEGMENT.intensity >> 2) + 16));
	uint8_t  bpm = (uint8_t)((SEGMENT.speed >> 1) | 1);
	uint16_t pos = beatsin8(bpm, 0, SEGLEN - 1, millis);
	if (SEGENV.call == 0) SEGENV.aux0 = pos;
	uint8_t pidx = (uint8_t)((pos * 256) / SEGLEN);
	crgb_t  c    = palette_lookup((wled_palette_t)SEGMENT.palette, pidx, 255);
	uint16_t lo  = (SEGENV.aux0 < pos) ? SEGENV.aux0 : pos;
	uint16_t hi  = (SEGENV.aux0 < pos) ? pos : SEGENV.aux0;
	for (uint16_t i = lo; i <= hi; i++) vstrip_set(i, c);
	SEGENV.aux0 = pos;
	vstrip_render();
}

/* ─── Dispatch table ──────────────────────────────────────────────────── */
typedef void (*wled_mode_fn_t)(void);
static const wled_mode_fn_t mode_table[WLED_FX_COUNT] = {
	mode_breath,            /*  0: breath_wled */
	mode_pride,             /*  1: pride */
	mode_pacifica,          /*  2: pacifica */
	mode_running_lights,    /*  3: running_lights */
	mode_juggle_wled,       /*  4: juggle_wled */
	mode_confetti_wled,     /*  5: confetti_wled */
	mode_rainbow_wled,      /*  6: rainbow_wled */
	mode_palette_flow,      /*  7: palette_flow */
	mode_bpm,               /*  8: bpm */
	mode_glitter,           /*  9: glitter */
	mode_color_wipe,        /* 10: color_wipe */
	mode_two_dots,          /* 11: two_dots */
	mode_lake,              /* 12: lake */
	mode_dancing_shadows,   /* 13: dancing_shadows */
	mode_colortwinkles,     /* 14: colortwinkles */
	mode_sinelon,           /* 15: sinelon */
};

void wled_fx_dispatch(uint8_t mode_id) {
	if (mode_id >= WLED_FX_COUNT) return;
	static uint32_t last_frame = 0;
	uint32_t now = millis;
	if ((now - last_frame) < WLED_FRAME_MS) return;
	last_frame = now;
	mode_table[mode_id]();
	SEGENV.call++;
}

void wled_fx_reset_state(void) {
	wled_seg.aux0 = 0;
	wled_seg.aux1 = 0;
	wled_seg.step = 0;
	wled_seg.call = 0;
	for (uint8_t i = 0; i < sizeof(wled_seg.data); i++) wled_seg.data[i] = 0;
	for (uint16_t i = 0; i < WLED_VSTRIP_LEN; i++) {
		vstrip[i].r = 0; vstrip[i].g = 0; vstrip[i].b = 0;
	}
}
