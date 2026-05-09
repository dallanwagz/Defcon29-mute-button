/*
 * pwm.c — LED PWM, buzzer, and button-press takeover animation.
 */

#include <stdint.h>
#include <stdbool.h>
#include <asf.h>
#include "pwm.h"

struct tcc_module tcc0_instance;
struct tcc_module tcc1_instance;
struct tcc_module tcc2_instance;
struct tc_module  tc3_instance;
struct tc_module  tc4_instance;
struct tc_module  tc5_instance;

uint8_t ledvalues[12] = {0};

extern bool              USBPower;
extern volatile uint32_t millis;

/* ─── pwm_init ──────────────────────────────────────────────────────────── */

void pwm_init(void){
	struct tcc_config config_tcc0;
	tcc_get_config_defaults(&config_tcc0, TCC0);
	config_tcc0.counter.period = 256;
	config_tcc0.compare.wave_generation = TCC_WAVE_GENERATION_SINGLE_SLOPE_PWM;
	config_tcc0.compare.match[0] = 0; //LED1R
	config_tcc0.pins.enable_wave_out_pin[4] = true;
	config_tcc0.pins.wave_out_pin[4] = PIN_PA22F_TCC0_WO4;
	config_tcc0.pins.wave_out_pin_mux[4] = PINMUX_PA22F_TCC0_WO4;
	config_tcc0.wave.wave_polarity[0] = TCC_WAVE_POLARITY_1;
	config_tcc0.compare.match[1] = 0; //LED2R
	config_tcc0.pins.enable_wave_out_pin[5] = true;
	config_tcc0.pins.wave_out_pin[5] = PIN_PA23F_TCC0_WO5;
	config_tcc0.pins.wave_out_pin_mux[5] = PINMUX_PA23F_TCC0_WO5;
	config_tcc0.wave.wave_polarity[1] = TCC_WAVE_POLARITY_1;
	config_tcc0.compare.match[2] = 0; //LED3R
	config_tcc0.pins.enable_wave_out_pin[6] = true;
	config_tcc0.pins.wave_out_pin[6] = PIN_PA20F_TCC0_WO6;
	config_tcc0.pins.wave_out_pin_mux[6] = PINMUX_PA20F_TCC0_WO6;
	config_tcc0.wave.wave_polarity[2] = TCC_WAVE_POLARITY_1;
	config_tcc0.compare.match[3] = 0; //LED4R
	config_tcc0.pins.enable_wave_out_pin[7] = true;
	config_tcc0.pins.wave_out_pin[7] = PIN_PA21F_TCC0_WO7;
	config_tcc0.pins.wave_out_pin_mux[7] = PINMUX_PA21F_TCC0_WO7;
	config_tcc0.wave.wave_polarity[3] = TCC_WAVE_POLARITY_1;
	config_tcc0.run_in_standby = true;
	config_tcc0.counter.clock_source = GCLK_GENERATOR_0;
	tcc_init(&tcc0_instance, TCC0, &config_tcc0);
	tcc_enable(&tcc0_instance);

	struct tcc_config config_tcc1;
	tcc_get_config_defaults(&config_tcc1, TCC1);
	config_tcc1.counter.period = 256;
	config_tcc1.compare.wave_generation = TCC_WAVE_GENERATION_SINGLE_SLOPE_PWM;
	config_tcc1.compare.match[0] = 0; //LED1G
	config_tcc1.pins.enable_wave_out_pin[0] = true;
	config_tcc1.pins.wave_out_pin[0] = PIN_PA10E_TCC1_WO0;
	config_tcc1.pins.wave_out_pin_mux[0] = PINMUX_PA10E_TCC1_WO0;
	config_tcc1.wave.wave_polarity[0] = TCC_WAVE_POLARITY_1;
	config_tcc1.compare.match[1] = 0; //LED2G
	config_tcc1.pins.enable_wave_out_pin[1] = true;
	config_tcc1.pins.wave_out_pin[1] = PIN_PA11E_TCC1_WO1;
	config_tcc1.pins.wave_out_pin_mux[1] = PINMUX_PA11E_TCC1_WO1;
	config_tcc1.wave.wave_polarity[1] = TCC_WAVE_POLARITY_1;
	config_tcc1.run_in_standby = true;
	config_tcc1.counter.clock_source = GCLK_GENERATOR_0;
	tcc_init(&tcc1_instance, TCC1, &config_tcc1);
	tcc_enable(&tcc1_instance);

	struct tcc_config config_tcc2;
	tcc_get_config_defaults(&config_tcc2, TCC2);
	config_tcc2.counter.clock_prescaler = TCC_CLOCK_PRESCALER_DIV256;
	config_tcc2.counter.period = 256;
	config_tcc2.compare.wave_generation = TCC_WAVE_GENERATION_MATCH_FREQ;
	config_tcc2.compare.match[0] = 0; //BUZZER
	config_tcc2.pins.enable_wave_out_pin[0] = true;
	config_tcc2.pins.wave_out_pin[0] = PIN_PA00E_TCC2_WO0;
	config_tcc2.pins.wave_out_pin_mux[0] = PINMUX_PA00E_TCC2_WO0;
	config_tcc2.run_in_standby = true;
	config_tcc2.counter.clock_source = GCLK_GENERATOR_3;
	tcc_init(&tcc2_instance, TCC2, &config_tcc2);
	tcc_enable(&tcc2_instance);
	tcc_stop_counter(&tcc2_instance);

	struct tc_config config_tc3;
	tc_get_config_defaults(&config_tc3);
	config_tc3.counter_size = TC_COUNTER_SIZE_8BIT;
	config_tc3.wave_generation = TC_WAVE_GENERATION_NORMAL_PWM_MODE;
	config_tc3.clock_source = GCLK_GENERATOR_0;
	config_tc3.counter_8_bit.period = 255;
	config_tc3.waveform_invert_output = 3;
	config_tc3.pwm_channel[0].enabled = true; //LED3G
	config_tc3.pwm_channel[0].pin_out = PIN_PA18E_TC3_WO0;
	config_tc3.pwm_channel[0].pin_mux = PINMUX_PA18E_TC3_WO0;
	config_tc3.pwm_channel[1].enabled = true; //LED4G
	config_tc3.pwm_channel[1].pin_out = PIN_PA19E_TC3_WO1;
	config_tc3.pwm_channel[1].pin_mux = PINMUX_PA19E_TC3_WO1;
	config_tc3.run_in_standby = true;
	tc_init(&tc3_instance, TC3, &config_tc3);
	tc_enable(&tc3_instance);

	struct tc_config config_tc4;
	tc_get_config_defaults(&config_tc4);
	config_tc4.counter_size = TC_COUNTER_SIZE_8BIT;
	config_tc4.wave_generation = TC_WAVE_GENERATION_NORMAL_PWM_MODE;
	config_tc4.clock_source = GCLK_GENERATOR_0;
	config_tc4.counter_8_bit.period = 255;
	config_tc4.waveform_invert_output = 3;
	config_tc4.pwm_channel[0].enabled = true; //LED1B
	config_tc4.pwm_channel[0].pin_out = PIN_PB08E_TC4_WO0;
	config_tc4.pwm_channel[0].pin_mux = PINMUX_PB08E_TC4_WO0;
	config_tc4.pwm_channel[1].enabled = true; //LED2B
	config_tc4.pwm_channel[1].pin_out = PIN_PB09E_TC4_WO1;
	config_tc4.pwm_channel[1].pin_mux = PINMUX_PB09E_TC4_WO1;
	config_tc4.run_in_standby = true;
	tc_init(&tc4_instance, TC4, &config_tc4);
	tc_enable(&tc4_instance);

	struct tc_config config_tc5;
	tc_get_config_defaults(&config_tc5);
	config_tc5.counter_size = TC_COUNTER_SIZE_8BIT;
	config_tc5.wave_generation = TC_WAVE_GENERATION_NORMAL_PWM_MODE;
	config_tc5.clock_source = GCLK_GENERATOR_0;
	config_tc5.counter_8_bit.period = 255;
	config_tc5.waveform_invert_output = 3;
	config_tc5.pwm_channel[0].enabled = true; //LED3B
	config_tc5.pwm_channel[0].pin_out = PIN_PB10E_TC5_WO0;
	config_tc5.pwm_channel[0].pin_mux = PINMUX_PB10E_TC5_WO0;
	config_tc5.pwm_channel[1].enabled = true; //LED4B
	config_tc5.pwm_channel[1].pin_out = PIN_PB11E_TC5_WO1;
	config_tc5.pwm_channel[1].pin_mux = PINMUX_PB11E_TC5_WO1;
	config_tc5.run_in_standby = true;
	tc_init(&tc5_instance, TC5, &config_tc5);
	tc_enable(&tc5_instance);
}

/* ─── LED primitives ────────────────────────────────────────────────────── */

void led_set_brightness(leds led, uint8_t brightness){
	if(!USBPower){
		brightness = brightness/5;
	}
	ledvalues[led] = brightness;
	switch(led){
		case LED1R: tcc_set_compare_value(&tcc0_instance, 0, brightness); break;
		case LED1G: tcc_set_compare_value(&tcc1_instance, 0, brightness); break;
		case LED1B: tc_set_compare_value(&tc4_instance, 0, brightness);   break;
		case LED2R: tcc_set_compare_value(&tcc0_instance, 1, brightness); break;
		case LED2G: tcc_set_compare_value(&tcc1_instance, 1, brightness); break;
		case LED2B: tc_set_compare_value(&tc4_instance, 1, brightness);   break;
		case LED3R: tcc_set_compare_value(&tcc0_instance, 2, brightness); break;
		case LED3G: tc_set_compare_value(&tc3_instance, 0, brightness);   break;
		case LED3B: tc_set_compare_value(&tc5_instance, 0, brightness);   break;
		case LED4R: tcc_set_compare_value(&tcc0_instance, 3, brightness); break;
		case LED4G: tc_set_compare_value(&tc3_instance, 1, brightness);   break;
		case LED4B: tc_set_compare_value(&tc5_instance, 1, brightness);   break;
		default: break;
	}
}

void led_on(leds led){
	led_set_brightness(led, 255);
	ledvalues[led] = 255;
}

void led_off(leds led){
	led_set_brightness(led, 0);
	ledvalues[led] = 0;
}

void led_toggle(leds led){
	if(ledvalues[led] > 0){
		ledvalues[led] = 0;
		led_set_brightness(led, 0);
	} else {
		ledvalues[led] = 255;
		led_set_brightness(led, 255);
	}
}

void led_set_color(uint8_t led, uint8_t color[3]){
	ledvalues[((led-1)*3)]   = color[0];
	led_set_brightness(((led-1)*3),   color[0]);
	ledvalues[((led-1)*3)+1] = color[1];
	led_set_brightness((((led-1)*3)+1), color[1]);
	ledvalues[((led-1)*3)+2] = color[2];
	led_set_brightness((((led-1)*3)+2), color[2]);
}

/* ─── Resting-color shadow ───────────────────────────────────────────────
 * led_resting[0..3] holds the "non-animation" color for each LED.
 * Updated by led_set_resting_color() only — never by animation rendering.
 * Restored when the takeover animation ends.
 * ────────────────────────────────────────────────────────────────────── */

static uint8_t led_resting[4][3];

/* Forward-declare tk.active so led_set_resting_color can check it. */
static bool takeover_active(void);

/* Public: set LED color and record it as the resting state.
 * If an animation is running the hardware write is deferred to animation-end;
 * the shadow is always updated so restoration is correct. */
void led_set_resting_color(uint8_t led, uint8_t color[3]){
	uint8_t idx = led - 1;
	if(idx > 3) return;
	led_resting[idx][0] = color[0];
	led_resting[idx][1] = color[1];
	led_resting[idx][2] = color[2];
	if(!takeover_active()){
		led_set_color(led, color);
	}
}

/* ─── Buzzer ─────────────────────────────────────────────────────────────
 * TCC2 is MATCH_FREQ mode on GCLK3 (8 MHz) with prescaler DIV256.
 * TCC2 clock = 31 250 Hz.  Output frequency ≈ 15625 / compare_value Hz.
 *
 * Arbitration: every successful buzzer_play() records who's playing in
 * _buz_owner; expiration via _buzzer_tick() returns owner to BZO_IDLE.
 * F04 patterns rely on this to know when to advance to the next note.
 * ─────────────────────────────────────────────────────────────────────── */

static uint32_t _buz_end = 0;
static volatile buzzer_owner_t _buz_owner = BZO_IDLE;

/* Forward decl for pattern engine (defined below). */
static void _pattern_cancel_internal(void);

static void _buzzer_tick(void){
	if(_buz_end && (millis >= _buz_end)){
		tcc_stop_counter(&tcc2_instance);
		_buz_end = 0;
		_buz_owner = BZO_IDLE;
	}
}

/* Internal raw play — assumes the caller already passed the priority gate. */
static void _buzzer_play_raw(uint16_t freq_hz, uint8_t duration_ms){
	if(!freq_hz){
		tcc_stop_counter(&tcc2_instance);
		_buz_end = 0;
		return;
	}
	uint16_t cv = (uint16_t)(15625u / freq_hz);
	if(cv < 1)   cv = 1;
	if(cv > 255) cv = 255;
	tcc_set_compare_value(&tcc2_instance, 0, (uint32_t)cv);
	tcc_restart_counter(&tcc2_instance);
	_buz_end = millis + duration_ms;
}

/* Public arbitrated play.  Higher-priority owners preempt lower ones (and
 * cancel a running pattern); equal/lower-priority requests are dropped if
 * a stronger owner is mid-tone. */
void buzzer_play_owned(buzzer_owner_t owner, uint16_t freq_hz, uint8_t duration_ms){
	if(_buz_owner != BZO_IDLE && _buz_owner > owner){
		return; /* higher-priority owner is mid-tone — drop */
	}
	/* Preempting a pattern from anything else cancels the pattern engine. */
	if(_buz_owner == BZO_PATTERN && owner != BZO_PATTERN){
		_pattern_cancel_internal();
	}
	_buz_owner = owner;
	_buzzer_play_raw(freq_hz, duration_ms);
}

/* Legacy entry point — treated as the lowest-priority owner so existing
 * call sites keep working without source changes. */
void buzzer_play(uint16_t freq_hz, uint8_t duration_ms){
	buzzer_play_owned(BZO_HAPTIC, freq_hz, duration_ms);
}

void buzzer_cancel(void){
	tcc_stop_counter(&tcc2_instance);
	_buz_end = 0;
	_buz_owner = BZO_IDLE;
}

buzzer_owner_t buzzer_current_owner(void){
	return _buz_owner;
}

/* ─── F04 beep patterns ──────────────────────────────────────────────────
 * Each pattern is a flat array of (freq_hz, dur_ms) notes terminated by
 * (any, 0) — dur_ms == 0 is the end-of-pattern sentinel.  freq_hz == 0
 * means "silent rest" (no tone) for dur_ms.  Patterns are read from
 * flash; no RAM cost beyond the engine state. */

typedef struct {
	uint16_t freq_hz;
	uint16_t dur_ms;
} note_t;

/* IDs match dc29.protocol.BeepPattern. */
static const note_t pat_confirm[]        = { {1200, 30}, {0, 0} };
static const note_t pat_decline[]        = { {300, 60}, {0, 30}, {300, 60}, {0, 0} };
static const note_t pat_teams_ringing[]  = { {880, 100}, {0, 50}, {880, 100},
                                             {0, 200}, {880, 100}, {0, 50}, {880, 100}, {0, 0} };
static const note_t pat_teams_mute_on[]  = { {1500, 25}, {0, 30}, {600, 60}, {0, 0} };
static const note_t pat_teams_mute_off[] = { {600, 60}, {0, 30}, {1500, 25}, {0, 0} };
static const note_t pat_ci_passed[]      = { {800, 50}, {0, 30}, {1200, 50},
                                             {0, 30}, {1600, 80}, {0, 0} };
static const note_t pat_ci_failed[]      = { {600, 80}, {0, 40}, {500, 80},
                                             {0, 40}, {400, 150}, {0, 0} };

static const note_t * const PATTERNS[] = {
	[0] = NULL,                   /* silence */
	[1] = pat_confirm,
	[2] = pat_decline,
	[3] = pat_teams_ringing,
	[4] = pat_teams_mute_on,
	[5] = pat_teams_mute_off,
	[6] = pat_ci_passed,
	[7] = pat_ci_failed,
};
#define PATTERN_COUNT (sizeof(PATTERNS)/sizeof(PATTERNS[0]))

static const note_t *_pat_cur = NULL;
static uint16_t       _pat_idx = 0;
static uint32_t       _pat_note_end = 0;

static void _pattern_cancel_internal(void){
	_pat_cur = NULL;
	_pat_idx = 0;
	_pat_note_end = 0;
}

void beep_play_pattern(uint8_t id){
	if(id == 0 || id >= PATTERN_COUNT || PATTERNS[id] == NULL){
		/* Silence / unknown id: cancel any running pattern. */
		_pattern_cancel_internal();
		if(_buz_owner == BZO_PATTERN){
			buzzer_cancel();
		}
		return;
	}
	_pat_cur = PATTERNS[id];
	_pat_idx = 0;
	_pat_note_end = 0; /* fire first note immediately on next tick */
}

void beep_pattern_tick(void){
	if(_pat_cur == NULL) return;

	/* If a higher-priority owner stole the buzzer, the pattern is dead.
	 * (buzzer_play_owned already calls _pattern_cancel_internal in that
	 * case, so this is a belt-and-braces check.) */
	if(_buz_owner != BZO_IDLE && _buz_owner != BZO_PATTERN) return;

	/* Wait for current note to finish before advancing. */
	if(_pat_note_end != 0 && (int32_t)(_pat_note_end - millis) > 0) return;

	const note_t *n = &_pat_cur[_pat_idx];
	if(n->dur_ms == 0){
		/* End of pattern. */
		_pattern_cancel_internal();
		_buz_owner = BZO_IDLE;
		return;
	}

	if(n->freq_hz == 0){
		/* Rest: keep the buzzer silent for dur_ms. */
		buzzer_cancel();
		_buz_owner = BZO_PATTERN;  /* still own the buzzer through the rest */
	} else {
		uint8_t dur = n->dur_ms > 255 ? 255 : (uint8_t)n->dur_ms;
		buzzer_play_owned(BZO_PATTERN, n->freq_hz, dur);
	}
	_pat_note_end = millis + n->dur_ms;
	_pat_idx++;
}

/* Legacy wrappers kept for serialconsole compatibility */
void buzzer_on(void)             { tcc_set_compare_value(&tcc2_instance, 0, 64); tcc_restart_counter(&tcc2_instance); }
void buzzer_off(void)            { buzzer_cancel(); }
void buzzer_set_value(uint8_t v) { tcc_set_compare_value(&tcc2_instance, 0, v); }


/* ─── Takeover animation ─────────────────────────────────────────────────
 *
 * Four-phase button-press animation driven from the main loop via
 * takeover_tick().  Total duration varies ~2.3–2.9 s by personality.
 *
 * Phase 1  IGNITION   300 ms  — source LED flashes twice; buzzer click
 * Phase 2  INVASION  ~1050 ms — 3 victims conquered CW one at a time
 * Phase 3  DOMINANCE  800 ms  — comet chase (2 full rotations)
 * Phase 4  RESOLUTION 350 ms  — crescendo → blackout+thud → resting restore
 *
 * Personality is auto-detected from the invader LED's color at press time.
 * ────────────────────────────────────────────────────────────────────── */

typedef enum { PERS_CLASSIC = 0, PERS_DEVIL, PERS_ZEN, PERS_JOY } Personality;

typedef struct {
	uint16_t vic_dur_ms;   /* per-victim invasion window */
	bool     no_decay;     /* Devil: victim stays 100% across sub-frames */
	bool     ccw;          /* Devil: CCW dominance chase */
	uint8_t  dim_pct;      /* dominance non-comet brightness % (0 = Joy overshoot) */
	bool     white_flick;  /* Devil: white flash mid-crescendo */
	bool     double_pulse; /* Joy: double pulse in crescendo */
	uint16_t click_hz; uint8_t click_ms;
	uint16_t thud_hz;  uint8_t thud_ms;
} PersParams;

static const PersParams PP[4] = {
	/* CLASSIC */ {350, false, false, 40, false, false,  800, 30, 200, 60},
	/* DEVIL   */ {280, true,  true,  20, true,  false, 1200, 25, 120, 80},
	/* ZEN     */ {490, false, false, 40, false, false,  440, 40, 220, 70},
	/* JOY     */ {315, false, false,  0, false, true,  1500, 25, 600, 50},
};

/* Sub-frame cumulative ms within each victim (7 entries, one per sub-frame).
 * Sub-frames: odd index = invader@100%; even index = victim@VIC_PCT. */
static const uint16_t SF_CUM[4][7] = {
	/* CLASSIC */ { 60, 110, 160, 210, 260, 300, 350},
	/* DEVIL   */ { 40,  80, 120, 160, 200, 240, 280},
	/* ZEN     */ { 70, 140, 210, 280, 350, 420, 490},
	/* JOY     */ { 60, 115, 165, 210, 250, 285, 315},
};

/* Victim LED brightness for sub-frames 1, 3, 5 (0-based: indices 1,3,5).
 * Index into this table: sf/2 where sf is 1,3,5 → 0,1,2. */
static const uint8_t VIC_PCT[4][3] = {
	/* CLASSIC */ {100, 60, 20},
	/* DEVIL   */ {100, 100, 100},  /* no decay */
	/* ZEN     */ {100, 60, 20},
	/* JOY     */ {100, 60, 20},
};

/* CW ring: TL(LED1)=0, TR(LED2)=1, BR(LED4)=3, BL(LED3)=2.
 * CW_RING maps ring position (0-3) → 0-based LED index.
 * RING_POS maps 0-based LED index → ring position. */
static const uint8_t CW_RING[4]  = {0, 1, 3, 2};
static const uint8_t RING_POS[4] = {0, 1, 3, 2};

/* For each source LED (0-based): the 3 CW-ordered victim LED indices. */
static const uint8_t INVADE[4][3] = {
	/* src 0 TL/LED1 */ {1, 3, 2},
	/* src 1 TR/LED2 */ {3, 2, 0},
	/* src 2 BL/LED3 */ {0, 1, 3},
	/* src 3 BR/LED4 */ {2, 0, 1},
};

typedef struct {
	bool     active;
	uint32_t start_ms;
	uint8_t  src;            /* 0-based source LED (button index - 1) */
	uint8_t  pers;
	uint8_t  inv_rgb[3];     /* invader color snapshot at press */
	uint8_t  vic_rgb[4][3];  /* all 4 LED colors snapshot at press */
	bool     blackout_buzzed;
	uint32_t p2_end;         /* t-relative: invasion end / dominance start */
	uint32_t p3_end;         /* t-relative: dominance end / resolution start */
	uint32_t p4_end;         /* t-relative: animation end */
} TakeoverAnim;

static TakeoverAnim tk;

static bool takeover_active(void){ return tk.active; }

static Personality personality_for(uint8_t r, uint8_t g, uint8_t b){
	if((int)r > (int)g + (int)b + 30) return PERS_DEVIL;
	if((int)g > (int)r + (int)b + 20) return PERS_JOY;
	if((int)b > (int)r + (int)g + 20) return PERS_ZEN;
	return PERS_CLASSIC;
}

/* Set 0-based LED to rgb at pct% brightness (0-100). */
static void led_pct(uint8_t led_0, const uint8_t rgb[3], uint8_t pct){
	uint8_t c[3] = {
		(uint8_t)((uint16_t)rgb[0] * pct / 100),
		(uint8_t)((uint16_t)rgb[1] * pct / 100),
		(uint8_t)((uint16_t)rgb[2] * pct / 100)
	};
	led_set_color(led_0 + 1, c);
}

static const uint8_t OFF3[3] = {0, 0, 0};

/* ── Phase 1: IGNITION ─────────────────────────────────────────────────── */

static void ignition_render(uint32_t t){
	/* Non-source LEDs hold resting colors throughout ignition. */
	for(int i = 0; i < 4; i++){
		if(i != tk.src) led_set_color(i + 1, (uint8_t *)tk.vic_rgb[i]);
	}
	if(t < 80){
		/* F1: source on — initial pop */
		led_pct(tk.src, tk.inv_rgb, 100);
	} else if(t < 140){
		/* F2: source off — the "silence before the drum hit" */
		led_set_color(tk.src + 1, (uint8_t *)OFF3);
	} else {
		/* F3: source on — re-strikes harder */
		led_pct(tk.src, tk.inv_rgb, 100);
	}
}

/* ── Phase 2: INVASION ─────────────────────────────────────────────────── */

static uint8_t get_subframe(uint32_t t_vic, uint8_t pers){
	const uint16_t *sf = SF_CUM[pers];
	for(int i = 0; i < 7; i++){
		if(t_vic < sf[i]) return (uint8_t)i;
	}
	return 6;
}

static void render_victim_sf(uint8_t vic_0, uint8_t sf, uint8_t pers){
	if(sf % 2 == 0){
		/* Even sub-frame (0,2,4,6): invader@100% */
		led_pct(vic_0, tk.inv_rgb, 100);
	} else {
		/* Odd sub-frame (1,3,5): victim at decaying brightness */
		led_pct(vic_0, tk.vic_rgb[vic_0], VIC_PCT[pers][sf / 2]);
	}
}

static void invasion_render(uint32_t t){
	uint16_t vic_dur = PP[tk.pers].vic_dur_ms;
	uint8_t  vi      = (uint8_t)(t / vic_dur);
	if(vi > 2) vi = 2;
	uint32_t t_vic   = t - (uint32_t)vi * vic_dur;

	/* Source LED: always invader@100% (the conqueror never wavers) */
	led_pct(tk.src, tk.inv_rgb, 100);

	/* Already-conquered victims: hold invader color */
	for(int v = 0; v < vi; v++){
		led_pct(INVADE[tk.src][v], tk.inv_rgb, 100);
	}

	/* Current victim: sub-frame battle */
	uint8_t sf = get_subframe(t_vic, tk.pers);
	render_victim_sf(INVADE[tk.src][vi], sf, tk.pers);

	/* Not-yet-invaded victims: still at resting color */
	for(int v = vi + 1; v < 3; v++){
		uint8_t l = INVADE[tk.src][v];
		led_set_color(l + 1, (uint8_t *)tk.vic_rgb[l]);
	}
}

/* ── Phase 3: DOMINANCE ─────────────────────────────────────────────────── */

static void dominance_render(uint32_t t){
	uint8_t frame    = (uint8_t)(t / 100);           /* 0..7 for 2 full rotations */
	uint8_t rp_src   = RING_POS[tk.src];
	uint8_t comet_rp;
	if(PP[tk.pers].ccw){
		comet_rp = (uint8_t)((rp_src + 8 - frame) % 4);  /* CCW: Devil */
	} else {
		comet_rp = (uint8_t)((rp_src + frame) % 4);       /* CW */
	}
	uint8_t comet = CW_RING[comet_rp];
	uint8_t dim   = PP[tk.pers].dim_pct;

	for(int i = 0; i < 4; i++){
		if(i == comet){
			led_pct(i, tk.inv_rgb, 100);
		} else if(dim == 0){
			/* Joy overshoot: others go dark between steps */
			led_set_color(i + 1, (uint8_t *)OFF3);
		} else {
			led_pct(i, tk.inv_rgb, dim);
		}
	}
}

/* ── Phase 4: RESOLUTION ─────────────────────────────────────────────────── */

static void resolution_render(uint32_t t){
	if(t < 100){
		/* F1: crescendo — all at invader@100% */
		for(int i = 0; i < 4; i++) led_pct(i, tk.inv_rgb, 100);
		if(PP[tk.pers].white_flick && t >= 40 && t < 70){
			/* Devil: white flash mid-hold */
			uint8_t white[3] = {200, 200, 200};
			for(int i = 0; i < 4; i++) led_set_color(i + 1, (uint8_t *)white);
		}
		if(PP[tk.pers].double_pulse && t >= 40 && t < 65){
			/* Joy: quick half-brightness dip for double-pulse feel */
			for(int i = 0; i < 4; i++) led_pct(i, tk.inv_rgb, 50);
		}
	} else if(t < 200){
		/* F2: blackout — the hush; buzzer thud fires here */
		for(int i = 0; i < 4; i++) led_set_color(i + 1, (uint8_t *)OFF3);
	} else {
		/* F3: resting colors snap back */
		for(int i = 0; i < 4; i++) led_set_color(i + 1, led_resting[i]);
	}
}

/* ── Public API ──────────────────────────────────────────────────────────── */

/* Call from keys.c before send_keys() with 0-based button index (key - 1). */
void takeover_start(uint8_t src_0){
	extern bool button_flash_enabled;
	if(!button_flash_enabled) return;

	buzzer_cancel();

	tk.active         = true;
	tk.start_ms       = millis;
	tk.src            = src_0 & 3;
	tk.blackout_buzzed = false;

	/* Snapshot resting colors at press time */
	for(int i = 0; i < 4; i++){
		tk.vic_rgb[i][0] = ledvalues[i * 3];
		tk.vic_rgb[i][1] = ledvalues[i * 3 + 1];
		tk.vic_rgb[i][2] = ledvalues[i * 3 + 2];
	}
	tk.inv_rgb[0] = tk.vic_rgb[src_0][0];
	tk.inv_rgb[1] = tk.vic_rgb[src_0][1];
	tk.inv_rgb[2] = tk.vic_rgb[src_0][2];

	tk.pers = (uint8_t)personality_for(tk.inv_rgb[0], tk.inv_rgb[1], tk.inv_rgb[2]);

	uint32_t vd  = PP[tk.pers].vic_dur_ms;
	tk.p2_end    = 300 + 3 * vd;
	tk.p3_end    = tk.p2_end + 800;
	tk.p4_end    = tk.p3_end + 350;

	/* Immediate ignition flash so press feels instant before key sends */
	led_pct(src_0, tk.inv_rgb, 100);

	buzzer_play_owned(BZO_TAKEOVER, PP[tk.pers].click_hz, PP[tk.pers].click_ms);
}

/* Call once per main-loop tick from update_effects().
 * Returns true while animation is running (caller should skip other effects). */
bool takeover_tick(void){
	_buzzer_tick();
	if(!tk.active) return false;

	uint32_t t = millis - tk.start_ms;

	/* Fire blackout thud at the F1→F2 boundary inside resolution */
	if(!tk.blackout_buzzed && t >= (tk.p3_end + 100)){
		buzzer_play_owned(BZO_TAKEOVER, PP[tk.pers].thud_hz, PP[tk.pers].thud_ms);
		tk.blackout_buzzed = true;
	}

	if(t >= tk.p4_end){
		/* Restore all LEDs to their resting colors */
		for(int i = 0; i < 4; i++) led_set_color(i + 1, led_resting[i]);
		tk.active = false;
		return false;
	} else if(t >= tk.p3_end){
		resolution_render(t - tk.p3_end);
	} else if(t >= tk.p2_end){
		dominance_render(t - tk.p2_end);
	} else if(t >= 300){
		invasion_render(t - 300);
	} else {
		ignition_render(t);
	}
	return true;
}


/* ─── Splash animation — interactive fidget-toy "color spray" ────────────
 *
 * Triggered by a button press while an effect mode is running.  Captures
 * the pressed LED's current displayed color (from ledvalues[]), then
 * renders a short ~300 ms three-phase animation:
 *
 * Phase 1 FREEZE   ( 0– 60 ms): pressed LED brightens to 100% of captured;
 *                                neighbors stay on whatever they were.
 * Phase 2 SPRAY   (60–180 ms): captured color paints outward — adjacent
 *                                LEDs at 90%, opposite LED at 50%.  Source
 *                                holds at 100%.
 * Phase 3 SETTLE (180–300 ms): all LEDs cross-fade back from the splash
 *                                colors to their resting shadow values, so
 *                                the underlying scene/effect can resume
 *                                without a visible discontinuity.
 *
 * Splash takes priority over update_effects() (effect skips while splash
 * is running) but yields to the long takeover animation.
 * ────────────────────────────────────────────────────────────────────── */

#define SPLASH_TOTAL_MS    300
#define SPLASH_FREEZE_END   60
#define SPLASH_SPRAY_END   180

typedef struct {
	bool     active;
	uint32_t start_ms;
	uint8_t  src;            /* 0-based source LED index */
	uint8_t  src_rgb[3];     /* captured displayed color at press time */
} SplashAnim;

static SplashAnim sp;

static void _splash_blend(uint8_t out[3], const uint8_t a[3], const uint8_t b[3], uint8_t mix_pct){
	/* mix_pct = 0 → all a; 100 → all b; linear blend.  Caps at 100. */
	if(mix_pct > 100) mix_pct = 100;
	uint16_t inv = 100 - mix_pct;
	out[0] = (uint8_t)(((uint16_t)a[0] * inv + (uint16_t)b[0] * mix_pct) / 100);
	out[1] = (uint8_t)(((uint16_t)a[1] * inv + (uint16_t)b[1] * mix_pct) / 100);
	out[2] = (uint8_t)(((uint16_t)a[2] * inv + (uint16_t)b[2] * mix_pct) / 100);
}

void splash_start(uint8_t src_0){
	if(src_0 > 3) return;
	sp.src = src_0;
	sp.src_rgb[0] = ledvalues[src_0 * 3 + 0];
	sp.src_rgb[1] = ledvalues[src_0 * 3 + 1];
	sp.src_rgb[2] = ledvalues[src_0 * 3 + 2];
	sp.start_ms = millis;
	sp.active = true;
}

bool splash_tick(void){
	if(!sp.active) return false;

	uint32_t t = millis - sp.start_ms;
	if(t >= SPLASH_TOTAL_MS){
		/* Restore resting colors and exit. */
		for(uint8_t i = 0; i < 4; i++) led_set_color(i + 1, led_resting[i]);
		sp.active = false;
		return false;
	}

	/* Cyclic-distance ring layout: TL(0), TR(1), BR(3), BL(2).
	 * For a given source LED, classify each LED as: 0=source, 1=adjacent, 2=opposite. */
	static const uint8_t ring_pos[4] = {0, 1, 3, 2};   /* led_idx → ring position */
	static const uint8_t pos_to_led[4] = {0, 1, 3, 2}; /* ring position → led_idx */

	uint8_t src_ring = ring_pos[sp.src];
	uint8_t off[3] = {0, 0, 0};
	uint8_t color[3];

	if(t < SPLASH_FREEZE_END){
		/* Phase 1 FREEZE: source at 100% of captured; others untouched
		 * (they keep whatever the underlying effect last wrote, frozen). */
		led_set_color(sp.src + 1, sp.src_rgb);
	} else if(t < SPLASH_SPRAY_END){
		/* Phase 2 SPRAY: source 100%, adjacent 90%, opposite 50%. */
		led_set_color(sp.src + 1, sp.src_rgb);
		uint8_t adj[3] = {(uint8_t)(sp.src_rgb[0] * 9 / 10),
		                  (uint8_t)(sp.src_rgb[1] * 9 / 10),
		                  (uint8_t)(sp.src_rgb[2] * 9 / 10)};
		uint8_t opp[3] = {(uint8_t)(sp.src_rgb[0] / 2),
		                  (uint8_t)(sp.src_rgb[1] / 2),
		                  (uint8_t)(sp.src_rgb[2] / 2)};
		for(uint8_t i = 0; i < 4; i++){
			if(i == sp.src) continue;
			uint8_t r = ring_pos[i];
			uint8_t cyc_dist = (r >= src_ring) ? (r - src_ring) : (src_ring - r);
			if(cyc_dist > 2) cyc_dist = 4 - cyc_dist;
			led_set_color(i + 1, (cyc_dist == 1) ? adj : opp);
		}
		(void)off; (void)pos_to_led;  /* used by SETTLE branch via fall-through; suppress unused warning */
	} else {
		/* Phase 3 SETTLE: cross-fade splash → resting over remaining ms. */
		uint16_t fade_t = t - SPLASH_SPRAY_END;
		uint16_t fade_span = SPLASH_TOTAL_MS - SPLASH_SPRAY_END;
		uint8_t mix = (uint8_t)((fade_t * 100u) / fade_span);   /* 0..100 */
		/* Source: source_rgb → resting */
		_splash_blend(color, sp.src_rgb, led_resting[sp.src], mix);
		led_set_color(sp.src + 1, color);
		/* Others: their splash color → resting */
		uint8_t adj[3] = {(uint8_t)(sp.src_rgb[0] * 9 / 10),
		                  (uint8_t)(sp.src_rgb[1] * 9 / 10),
		                  (uint8_t)(sp.src_rgb[2] * 9 / 10)};
		uint8_t opp[3] = {(uint8_t)(sp.src_rgb[0] / 2),
		                  (uint8_t)(sp.src_rgb[1] / 2),
		                  (uint8_t)(sp.src_rgb[2] / 2)};
		for(uint8_t i = 0; i < 4; i++){
			if(i == sp.src) continue;
			uint8_t r = ring_pos[i];
			uint8_t cyc_dist = (r >= src_ring) ? (r - src_ring) : (src_ring - r);
			if(cyc_dist > 2) cyc_dist = 4 - cyc_dist;
			const uint8_t *splash_c = (cyc_dist == 1) ? adj : opp;
			_splash_blend(color, splash_c, led_resting[i], mix);
			led_set_color(i + 1, color);
		}
	}
	return true;
}
