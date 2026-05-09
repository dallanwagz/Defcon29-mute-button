/*
 * input.h — F01/F02 input state machine.
 *
 * Layered on top of the existing falling-edge ISR + button1..button4 flag
 * pattern in main.c.  Adds tap-count modifiers (double/triple), long-press,
 * and 2-button chords without disturbing existing single-tap behavior for
 * buttons with no modifier mapping (fast path: ISR flag → send_keys() exactly
 * as before).
 *
 * Modifier table is RAM-only on first cut (per F01 design).  Bridges populate
 * it via the 0x01 'm' protocol command after CDC connect.  Cleared on power
 * cycle.
 *
 * Does NOT replace the existing 4-button "all four pressed" chord that cycles
 * effect modes — that runs upstream in the main loop and clears the per-button
 * flags before input_tick() sees them.
 */

#ifndef INPUT_H_
#define INPUT_H_

#include "main.h"
#include <stdbool.h>
#include <stdint.h>

/* Tunable timings (ms).  See docs/hardware-features/features/F01-tap-count-long-press.md */
#define MULTI_TAP_WINDOW_MS   250
#define LONG_PRESS_THRESH_MS  500
#define CHORD_WINDOW_MS        80

/* Event kinds reported back via 0x01 'b' <kind> ... */
typedef enum {
    INPUT_EVT_DOUBLE = '2',
    INPUT_EVT_TRIPLE = '3',
    INPUT_EVT_LONG   = 'L',
    INPUT_EVT_CHORD  = 'C',
} input_evt_t;

/* (mod, key) action.  (0, 0) = "no mapping". */
typedef struct {
    uint8_t mod;
    uint8_t key;
} input_action_t;

/* Public API */

void input_init(void);

/* Called once per main-loop iteration after the existing all-4 chord
 * handler.  Consumes button1..button4 flags + reads pin levels for release
 * detection. */
void input_tick(void);

/* Called by serialconsole.c when 0x01 'm' <subcmd> ... arrives.
 * btn / btn_a / btn_b are 1-based (1..4). */
void input_set_action_double(uint8_t btn, uint8_t mod, uint8_t key);
void input_set_action_triple(uint8_t btn, uint8_t mod, uint8_t key);
void input_set_action_long(uint8_t btn, uint8_t mod, uint8_t key);
void input_set_action_chord(uint8_t btn_a, uint8_t btn_b, uint8_t mod, uint8_t key);
void input_clear_all_actions(void);

#endif /* INPUT_H_ */
