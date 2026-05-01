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

#endif /* PWM_H_ */