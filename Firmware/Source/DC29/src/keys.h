/*
 * keys.h
 *
 *  Author: compukidmike
 */ 


#ifndef KEYS_H_
#define KEYS_H_

#include "main.h"
#include <stdbool.h>


void get_keymap(void);

void send_keys(uint8_t key);


/* ─── F06 — Hyper-fast HID burst ────────────────────────────────────────
 * Fires a back-to-back sequence of (mod, key) HID reports at the badge's
 * native polling rate (~10 ms/frame).  Public entry point used by the
 * 0x01 'h' protocol command and reusable by F07 / F09 once they land.
 *
 * The state machine is ticked from the main loop via hid_burst_tick();
 * the implementation does NOT busy-wait, so LED rendering and button
 * polling continue while a burst is in flight.
 */

#define MAX_BURST_PAIRS 256

typedef enum {
	BURST_OK = 0,
	BURST_BUSY,        /* a burst is already running */
	BURST_TOO_LONG,    /* n_pairs > MAX_BURST_PAIRS */
	BURST_EMPTY,       /* n_pairs == 0 — used by callers to mean "cancel" */
} burst_result_t;

extern volatile bool burst_in_progress;

/* Copies (n_pairs * 2) bytes from `pairs` into the internal buffer and
 * starts the burst state machine.  Returns BURST_BUSY if a burst is
 * already running, BURST_TOO_LONG if n_pairs > MAX_BURST_PAIRS. */
burst_result_t hid_burst(const uint8_t *pairs, uint16_t n_pairs);

/* Cancel any in-progress burst.  Releases all keys + modifiers cleanly. */
void hid_burst_cancel(void);

/* Advance the burst state machine.  Cheap when idle. */
void hid_burst_tick(void);


#endif /* KEYS_H_ */