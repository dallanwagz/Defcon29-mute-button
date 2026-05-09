/*
 * serialconsole.c
 *
 *  Author: compukidmike
 */

#include "serialconsole.h"
#include "rww_eeprom.h"
#include "pwm.h"
#include "keys.h"
#include "wled_fx.h"
#include "input.h"
#include "jiggler.h"

extern bool main_b_cdc_enable;

/* Escape-byte side-channel (0x01 prefix). Commands from host:
     0x01 M          -> LED 4 red  (muted)
     0x01 U          -> LED 4 green (unmuted)
     0x01 X          -> LED 4 off  (clear)
     0x01 K n m k    -> set button n (1-6) to single key: modifier m, keycode k
     0x01 Q n        -> query button n; badge replies 0x01 R n m k
     0x01 L n r g b  -> set LED n (1-4) color immediately (not saved to EEPROM)
     0x01 P r1 g1 b1 r2 g2 b2 r3 g3 b3 r4 g4 b4 -> paint all 4 LEDs atomically (12 bytes)
     0x01 F 0/1      -> disable/enable button press takeover animation (RAM only, default on)
     0x01 E n        -> set LED effect mode (0..34; see dc29/protocol.py EffectMode for the full list — modes 1..18 hand-rolled, 19..34 WLED ports)
     0x01 T n        -> trigger takeover ripple animation for button n (1-4) on demand
     0x01 S 0/1      -> disable/enable capacitive touch slider (volume up/down) (RAM only, default on)
     0x01 I 0/1      -> disable/enable interactive splash on button press (RAM only, default on)
     0x01 W s i p    -> set WLED knobs: speed, intensity, palette (3 bytes; affects modes 19+ only; mirrors WLED /win&SX=&IX=&FP=)
   Commands from badge to host:
     0x01 B n m k    -> button n was pressed; first keymap entry is modifier m, keycode k
     0x01 R n m k    -> reply to Q query
     0x01 A n        -> ACK after K set-keymap command
     0x01 V n        -> effect mode changed (n = 0..34)
     0x01 C n        -> chord fired (n=1 short, n=2 long)
   0x01 never appears in menu traffic so this channel is safe to use concurrently. */
#define STATUS_ESCAPE 0x01
static uint8_t escape_state = 0;  /* 0=idle 1=awaiting_cmd 2=collecting_args */
static uint8_t escape_cmd = 0;
static uint8_t escape_args[12];   /* max 12 args (P command: r1 g1 b1 r2 g2 b2 r3 g3 b3 r4 g4 b4) */
static uint8_t escape_args_count = 0;
static uint8_t escape_args_needed = 0;

extern uint8_t keymaplength;
extern uint8_t keymap[];
extern uint8_t keymapstarts[];
extern bool button_flash_enabled;
extern bool haptic_click_enabled;
extern bool slider_enabled;
extern bool splash_on_press_enabled;
extern uint8_t effect_mode;

static uint8_t newKeystroke[230];
static uint8_t newKeymap[2];

static void set_button_keymap(uint8_t button, uint8_t mod, uint8_t keycode) {
	if(button < 1 || button > 6) return;
	newKeymap[0] = mod;
	newKeymap[1] = keycode;
	int x = 0, y = 0;

	if(button == 1){
		newKeystroke[x++] = 250;
		newKeystroke[x++] = newKeymap[0];
		newKeystroke[x++] = newKeymap[1];
		if(keymapstarts[1] > 0)
			for(y = keymapstarts[1]; y < keymaplength; y++) newKeystroke[x++] = keymap[y];
	} else if(button == 2){
		for(y = keymapstarts[0]; y < keymapstarts[1]; y++) newKeystroke[x++] = keymap[y];
		newKeystroke[x++] = 251;
		newKeystroke[x++] = newKeymap[0];
		newKeystroke[x++] = newKeymap[1];
		if(keymapstarts[2] > keymapstarts[1])
			for(y = keymapstarts[2]; y < keymaplength; y++) newKeystroke[x++] = keymap[y];
	} else if(button == 3){
		for(y = keymapstarts[0]; y < keymapstarts[2]; y++) newKeystroke[x++] = keymap[y];
		newKeystroke[x++] = 252;
		newKeystroke[x++] = newKeymap[0];
		newKeystroke[x++] = newKeymap[1];
		if(keymapstarts[3] > keymapstarts[2])
			for(y = keymapstarts[3]; y < keymaplength; y++) newKeystroke[x++] = keymap[y];
	} else if(button == 4){
		for(y = keymapstarts[0]; y < keymapstarts[3]; y++) newKeystroke[x++] = keymap[y];
		newKeystroke[x++] = 253;
		newKeystroke[x++] = newKeymap[0];
		newKeystroke[x++] = newKeymap[1];
		if(keymapstarts[4] > keymapstarts[3])
			for(y = keymapstarts[4]; y < keymaplength; y++) newKeystroke[x++] = keymap[y];
	} else if(button == 5){
		for(y = keymapstarts[0]; y < keymapstarts[4]; y++) newKeystroke[x++] = keymap[y];
		newKeystroke[x++] = 254;
		newKeystroke[x++] = newKeymap[0];
		newKeystroke[x++] = newKeymap[1];
		if(keymapstarts[5] > keymapstarts[4])
			for(y = keymapstarts[5]; y < keymaplength; y++) newKeystroke[x++] = keymap[y];
	} else {
		for(y = keymapstarts[0]; y < keymapstarts[5]; y++) newKeystroke[x++] = keymap[y];
		newKeystroke[x++] = 255;
		newKeystroke[x++] = newKeymap[0];
		newKeystroke[x++] = newKeymap[1];
	}

	uint8_t length[1] = {(uint8_t)x};
	rww_eeprom_emulator_write_buffer(EEP_KEY_MAP, length, 1);
	rww_eeprom_emulator_write_buffer(EEP_KEY_MAP+1, newKeystroke, x);
	rww_eeprom_emulator_commit_page_buffer();
	get_keymap();

	uint8_t ack[3] = {0x01, 'A', button};
	udi_cdc_write_buf(ack, 3);
}

void updateSerialConsole(void){
	if(main_b_cdc_enable){
		if(udi_cdc_get_nb_received_data()){
			int data = udi_cdc_getc();
			/* Escape-byte side-channel dispatcher. */
			if(escape_state == 1){
				escape_state = 0;
				escape_cmd = (uint8_t)data;
				escape_args_count = 0;
				if(data == 'M'){ led_set_resting_color(4, LED_COLOR_RED); return; }
				if(data == 'U'){ led_set_resting_color(4, LED_COLOR_GREEN); return; }
				if(data == 'X'){ led_set_resting_color(4, LED_COLOR_OFF); return; }
				if(data == 'K'){ escape_args_needed = 3; escape_state = 2; return; }
				if(data == 'Q'){ escape_args_needed = 1; escape_state = 2; return; }
				if(data == 'L'){ escape_args_needed = 4; escape_state = 2; return; }
				if(data == 'P'){ escape_args_needed = 12; escape_state = 2; return; }
				if(data == 'F'){ escape_args_needed = 1; escape_state = 2; return; }
				if(data == 'E'){ escape_args_needed = 1; escape_state = 2; return; }
				if(data == 'T'){ escape_args_needed = 1; escape_state = 2; return; }
				if(data == 'S'){ escape_args_needed = 1; escape_state = 2; return; }
				if(data == 'I'){ escape_args_needed = 1; escape_state = 2; return; }
				if(data == 'W'){ escape_args_needed = 3; escape_state = 2; return; }
				/* F01/F02 modifier-action table.  Variable arg count by sub-cmd:
				 *   'D'/'T'/'L' <btn> <mod> <key>          → 4 args after 'm'
				 *   'C' <btn_a> <btn_b> <mod> <key>        → 5 args after 'm'
				 *   'X'                                     → 1 arg after 'm'
				 * First arg is the sub-cmd; we expand args_needed once we see it. */
				if(data == 'm'){ escape_args_needed = 1; escape_state = 2; return; }
				/* F03 — haptic click toggle.  RAM-only, default on. */
				if(data == 'k'){ escape_args_needed = 1; escape_state = 2; return; }
				/* F08a-lite — Stay Awake jiggler.  Variable arg count by sub-cmd:
				 *   'M'                          → 1 arg total (just 'M')
				 *   'I' <duration_le32:4>        → 5 args total
				 *   'X'                          → 1 arg total
				 * First arg is the sub-cmd; we expand args_needed once we see it. */
				if(data == 'j'){ escape_args_needed = 1; escape_state = 2; return; }
				/* F04 — named beep patterns.  1 arg = pattern id (0..255). */
				if(data == 'p'){ escape_args_needed = 1; escape_state = 2; return; }
				return;
			}
			if(escape_state == 2){
				escape_args[escape_args_count++] = (uint8_t)data;
				/* Variable-length expansion for 'm' once sub-cmd byte arrives. */
				if(escape_cmd == 'm' && escape_args_count == 1){
					uint8_t sub = escape_args[0];
					if(sub == 'D' || sub == 'T' || sub == 'L') escape_args_needed = 4;
					else if(sub == 'C') escape_args_needed = 5;
					else if(sub == 'X') escape_args_needed = 1; /* already done */
					else { escape_state = 0; return; } /* unknown sub-cmd */
				}
				/* Variable-length expansion for 'j' once sub-cmd byte arrives. */
				if(escape_cmd == 'j' && escape_args_count == 1){
					uint8_t sub = escape_args[0];
					if(sub == 'M' || sub == 'X') escape_args_needed = 1; /* done */
					else if(sub == 'I') escape_args_needed = 5;          /* sub + 4 LE bytes */
					else { escape_state = 0; return; }
				}
				if(escape_args_count < escape_args_needed) return;
				escape_state = 0;
				if(escape_cmd == 'K'){
					set_button_keymap(escape_args[0], escape_args[1], escape_args[2]);
				} else if(escape_cmd == 'Q'){
					uint8_t btn = escape_args[0];
					if(btn >= 1 && btn <= 6){
						uint8_t qmod = keymap[keymapstarts[btn-1]+1];
						uint8_t qkc  = keymap[keymapstarts[btn-1]+2];
						uint8_t reply[5] = {0x01, 'R', btn, qmod, qkc};
						udi_cdc_write_buf(reply, 5);
					}
				} else if(escape_cmd == 'L'){
					uint8_t n = escape_args[0];
					if(n >= 1 && n <= 4){
						uint8_t color[3] = {escape_args[1], escape_args[2], escape_args[3]};
						led_set_resting_color(n, color);
					}
				} else if(escape_cmd == 'P'){
					/* Atomic 4-LED paint.  All four shadow values + hardware writes
					 * happen in this loop iteration, so animation frames don't tear. */
					for(uint8_t i = 0; i < 4; i++){
						uint8_t color[3] = {
							escape_args[i*3 + 0],
							escape_args[i*3 + 1],
							escape_args[i*3 + 2],
						};
						led_set_resting_color(i + 1, color);
					}
				} else if(escape_cmd == 'F'){
					button_flash_enabled = (escape_args[0] != 0);
				} else if(escape_cmd == 'E'){
					set_effect_mode(escape_args[0] % NUM_EFFECT_MODES);
				} else if(escape_cmd == 'T'){
					uint8_t btn = escape_args[0];
					if(btn >= 1 && btn <= 4){
						takeover_start((uint8_t)(btn - 1));
					}
				} else if(escape_cmd == 'S'){
					slider_enabled = (escape_args[0] != 0);
				} else if(escape_cmd == 'I'){
					splash_on_press_enabled = (escape_args[0] != 0);
				} else if(escape_cmd == 'W'){
					/* WLED knobs: speed, intensity, palette.  Mirrors WLED's
					 * /win&SX=&IX=&FP= API.  Palette wraps modulo WLED_PAL_COUNT
					 * so out-of-range values from the host don't crash effects. */
					wled_seg.speed     = escape_args[0];
					wled_seg.intensity = escape_args[1];
					wled_seg.palette   = (uint8_t)(escape_args[2] % WLED_PAL_COUNT);
				} else if(escape_cmd == 'k'){
					/* F03 — haptic-click toggle (RAM-only). */
					haptic_click_enabled = (escape_args[0] != 0);
				} else if(escape_cmd == 'm'){
					/* F01/F02 modifier-action table.
					 * sub-cmd encoding from docs/hardware-features/DESIGN.md §1. */
					uint8_t sub = escape_args[0];
					if(sub == 'D'){
						input_set_action_double(escape_args[1], escape_args[2], escape_args[3]);
					} else if(sub == 'T'){
						input_set_action_triple(escape_args[1], escape_args[2], escape_args[3]);
					} else if(sub == 'L'){
						input_set_action_long(escape_args[1], escape_args[2], escape_args[3]);
					} else if(sub == 'C'){
						input_set_action_chord(escape_args[1], escape_args[2], escape_args[3], escape_args[4]);
					} else if(sub == 'X'){
						input_clear_all_actions();
					}
				} else if(escape_cmd == 'p'){
					/* F04 — play beep pattern by id (0 = silence/cancel). */
					beep_play_pattern(escape_args[0]);
				} else if(escape_cmd == 'j'){
					/* F08a-lite — Stay Awake jiggler. */
					uint8_t sub = escape_args[0];
					if(sub == 'M'){
						jiggler_pulse_now();
					} else if(sub == 'I'){
						uint32_t secs = (uint32_t)escape_args[1]
						              | ((uint32_t)escape_args[2] << 8)
						              | ((uint32_t)escape_args[3] << 16)
						              | ((uint32_t)escape_args[4] << 24);
						jiggler_set_autonomous_secs(secs);
					} else if(sub == 'X'){
						jiggler_cancel_autonomous();
					}
				}
				return;
			}
			if(data == STATUS_ESCAPE){
				escape_state = 1;
				return;
			}
		}
	}
}
