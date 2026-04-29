/*
 * serialconsole.c
 *
 *  Author: compukidmike
 */

#include "serialconsole.h"
#include "rww_eeprom.h"
#include "pwm.h"
#include "keys.h"

extern bool main_b_cdc_enable;

/* Escape-byte side-channel (0x01 prefix). Commands from host:
     0x01 M          -> LED 4 red  (muted)
     0x01 U          -> LED 4 green (unmuted)
     0x01 X          -> LED 4 off  (clear)
     0x01 K n m k    -> set button n (1-6) to single key: modifier m, keycode k
     0x01 Q n        -> query button n; badge replies 0x01 R n m k
     0x01 L n r g b  -> set LED n (1-4) color immediately (not saved to EEPROM)
     0x01 F 0/1      -> disable/enable button press white flash (RAM only, default on)
     0x01 E 0/1      -> disable/enable idle LED effects (RAM only, default on)
   Commands from badge to host:
     0x01 B n m k    -> button n was pressed; first keymap entry is modifier m, keycode k
     0x01 R n m k    -> reply to Q query
     0x01 A n        -> ACK after K set-keymap command
     0x01 V n        -> effects state changed by long-press (n = 0 off, 1 on)
   0x01 never appears in menu traffic so this channel is safe to use concurrently. */
#define STATUS_ESCAPE 0x01
static uint8_t escape_state = 0;  /* 0=idle 1=awaiting_cmd 2=collecting_args */
static uint8_t escape_cmd = 0;
static uint8_t escape_args[4];    /* max 4 args (L command: n r g b) */
static uint8_t escape_args_count = 0;
static uint8_t escape_args_needed = 0;

extern uint8_t keymaplength;
extern uint8_t keymap[];
extern uint8_t keymapstarts[];
extern bool button_flash_enabled;
extern bool effects_enabled;

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
				if(data == 'M'){ led_set_color(4, LED_COLOR_RED); return; }
				if(data == 'U'){ led_set_color(4, LED_COLOR_GREEN); return; }
				if(data == 'X'){ led_set_color(4, LED_COLOR_OFF); return; }
				if(data == 'K'){ escape_args_needed = 3; escape_state = 2; return; }
				if(data == 'Q'){ escape_args_needed = 1; escape_state = 2; return; }
				if(data == 'L'){ escape_args_needed = 4; escape_state = 2; return; }
				if(data == 'F'){ escape_args_needed = 1; escape_state = 2; return; }
				if(data == 'E'){ escape_args_needed = 1; escape_state = 2; return; }
				return;
			}
			if(escape_state == 2){
				escape_args[escape_args_count++] = (uint8_t)data;
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
						led_set_color(n, color);
					}
				} else if(escape_cmd == 'F'){
					button_flash_enabled = (escape_args[0] != 0);
				} else if(escape_cmd == 'E'){
					effects_enabled = (escape_args[0] != 0);
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
