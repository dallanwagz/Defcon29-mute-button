/*
 * pwm.h
 *
 *  Author: compukidmike
 */ 


#ifndef PWM_H_
#define PWM_H_

typedef enum {
	LED1R,
	LED1G,
	LED1B,
	LED2R,
	LED2G,
	LED2B,
	LED3R,
	LED3G,
	LED3B,
	LED4R,
	LED4G,
	LED4B,
	LEDCOUNT
}
leds;

struct RGB {
	uint8_t red;
	uint8_t green;
	uint8_t blue;
	};

void pwm_init(void);

void led_set_brightness(leds led, uint8_t brightness);

void led_on(leds led);

void led_off(leds led);

void led_toggle(leds led);

void led_set_color(uint8_t led, uint8_t color[3]);

void buzzer_on(void);

void buzzer_off(void);

void buzzer_set_value(uint8_t value);

/* Resting-color shadow — use instead of led_set_color() for persistent state.
 * Updates the shadow; only drives hardware immediately when no takeover is active. */
void led_set_resting_color(uint8_t led, uint8_t color[3]);

/* Non-blocking button-press takeover animation.
 * takeover_start(src_0): src_0 is 0-based button index (0=TL,1=TR,2=BL,3=BR).
 *   Call once on button press; cancels any in-progress animation and restarts.
 * takeover_tick(): call every main-loop iteration (~1 ms).
 *   Returns true while animation is running (caller should skip other LED updates). */
void takeover_start(uint8_t src_0);
bool takeover_tick(void);

/* Non-blocking ~300 ms "splash" animation — the fidget-toy interaction.
 * Captures the source LED's current color, freezes it briefly, then sprays
 * outward to the other LEDs as a localized burst that fades back to the
 * underlying scene.  Designed to be called from the main loop on button
 * press while an effect mode is running, so the user can poke the toy.
 *
 * splash_start(src_0): src_0 is 0-based button index.  Cancels any in-
 *   progress splash and restarts.  Does NOT cancel a running takeover.
 * splash_tick(): call every main-loop iteration.  Returns true while a
 *   splash is rendering (caller should skip other LED updates).  Once it
 *   returns false, the underlying effect/static state resumes. */
void splash_start(uint8_t src_0);
bool splash_tick(void);

/* Non-blocking buzzer. */
void buzzer_play(uint16_t freq_hz, uint8_t duration_ms);
void buzzer_cancel(void);

/* ─── Buzzer arbitration (F04) ──────────────────────────────────────────
 * The buzzer is shared.  Higher-priority owners preempt lower ones; equal
 * or lower-priority requests are dropped while a higher owner plays.
 * Priority order (highest wins):
 *   BZO_GAME      — game audio (reserved; no current callers)
 *   BZO_TAKEOVER  — button-press takeover click + thud
 *   BZO_PATTERN   — F04 named beep patterns
 *   BZO_HAPTIC    — F03 modifier-only macro click
 *   BZO_IDLE      — nothing playing
 * Use buzzer_play_owned() in new code; legacy buzzer_play() is treated as
 * BZO_HAPTIC (lowest priority) so existing callers keep working.
 */
typedef enum {
	BZO_IDLE          = 0,
	BZO_HAPTIC        = 1,
	BZO_PATTERN       = 2,
	BZO_TAKEOVER      = 3,
	BZO_GAME          = 4,
} buzzer_owner_t;

void buzzer_play_owned(buzzer_owner_t owner, uint16_t freq_hz, uint8_t duration_ms);
buzzer_owner_t buzzer_current_owner(void);

/* ─── F04 beep patterns ─────────────────────────────────────────────────
 * Named patterns live in flash (read-only).  Pattern id 0 is reserved
 * for "silence" — calling beep_play_pattern(0) cancels any in-progress
 * pattern.  beep_pattern_tick() must be called from the main loop.
 */
void beep_play_pattern(uint8_t id);
void beep_pattern_tick(void);

#endif /* PWM_H_ */