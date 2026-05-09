/*
 * keys.c
 *
 *  Author: compukidmike
 */ 

#include "keys.h"
#include "udi_hid_kbd.h"
#include "udi_cdc.h"
#include "pwm.h"
#include "rww_eeprom.h"

extern uint8_t keymap[231];
extern uint8_t keymaplength;
extern uint8_t keymapstarts[6];
extern bool main_b_cdc_enable;

extern bool wait_for_sof;
extern bool button_flash_enabled;
extern bool haptic_click_enabled;

extern volatile uint32_t millis;

extern bool udi_hid_kbd_b_report_trans_ongoing;

extern uint8_t ledvalues[12];

uint32_t lastUSBSendTime = 0;

void get_keymap(void){
	rww_eeprom_emulator_read_buffer(EEP_KEY_MAP, keymap, 231);

	keymaplength = keymap[0];
	keymapstarts[0] = 1;
	for(int x=1; x<keymaplength; x++){
		switch (keymap[x]){
			case 251:
				keymapstarts[1] = x;
				break;
			case 252:
				keymapstarts[2] = x;
				break;
			case 253:
				keymapstarts[3] = x;
				break;
			case 254:
				keymapstarts[4] = x;
				break;
			case 255:
				keymapstarts[5] = x;
				break;
			
		}
	}
}

void send_keys(uint8_t key){
	/* Report button press event to host via the escape-byte side-channel. */
	if(main_b_cdc_enable && key >= 1 && key <= 4){
		uint8_t rmod = 0, rkc = 0;
		for(int x = keymapstarts[key-1]+1; x < keymapstarts[key]; x += 2){
			if(keymap[x] != 240 && keymap[x+1] != 0){ rmod = keymap[x]; rkc = keymap[x+1]; break; }
		}
		uint8_t evt[5] = {0x01, 'B', key, rmod, rkc};
		udi_cdc_write_buf(evt, 5);
	}
	if(button_flash_enabled && (key >= 1 && key <= 4)){
		takeover_start((uint8_t)(key - 1));
	}
	if(key < 6){
		if(key == 4){
			wait_for_sof = true;
			udi_hid_kbd_modifier_down(HID_MODIFIER_LEFT_UI);
			lastUSBSendTime = millis;
			while(millis - lastUSBSendTime < 10);
			wait_for_sof = true;
			udi_hid_kbd_modifier_down(HID_MODIFIER_LEFT_SHIFT);
			lastUSBSendTime = millis;
			while(millis - lastUSBSendTime < 10);
			wait_for_sof = true;
			//udi_hid_kbd_down(ascii_to_hid['m']);
			udi_hid_kbd_down(HID_M);
			lastUSBSendTime = millis;
			while(millis - lastUSBSendTime < 10);
			wait_for_sof = true;
			//udi_hid_kbd_up(ascii_to_hid['m']);
			udi_hid_kbd_up(HID_M);
			lastUSBSendTime = millis;
			while(millis - lastUSBSendTime < 10);
			wait_for_sof = true;
			udi_hid_kbd_modifier_up(HID_MODIFIER_LEFT_UI);
			lastUSBSendTime = millis;
			while(millis - lastUSBSendTime < 10);
			wait_for_sof = true;
			udi_hid_kbd_modifier_up(HID_MODIFIER_LEFT_SHIFT);
			lastUSBSendTime = millis;
			while(millis - lastUSBSendTime < 10);
			wait_for_sof = true;
		} else
		for(int x=keymapstarts[key-1]+1; x<keymapstarts[key]; x+=2){
			if(keymap[x] == 240){ //Media key
				wait_for_sof = true; //Needed?? I think the code that tests for this is gone
				udi_hid_media_down(keymap[x+1]);
				lastUSBSendTime = millis;
				while(millis - lastUSBSendTime < 10);
				wait_for_sof = true;
				udi_hid_media_up();
				lastUSBSendTime = millis;
				while(millis - lastUSBSendTime < 10);
				//while(wait_for_sof);
			} else {
				if(keymap[x+1] != 0){ //Don't send key
					wait_for_sof = true;
					udi_hid_kbd_modifier_down(keymap[x]);
					lastUSBSendTime = millis;
					while(millis - lastUSBSendTime < 10);
					wait_for_sof = true;
					udi_hid_kbd_down(keymap[x+1]);
					lastUSBSendTime = millis;
					while(millis - lastUSBSendTime < 10);
					wait_for_sof = true;
					udi_hid_kbd_up(keymap[x+1]);
					lastUSBSendTime = millis;
					while(millis - lastUSBSendTime < 10);
					wait_for_sof = true;
					udi_hid_kbd_modifier_up(keymap[x]);
					lastUSBSendTime = millis;
					while(millis - lastUSBSendTime < 10);
					wait_for_sof = true;
				}
			}
		}
	} else {
		for(int x=keymapstarts[key-1]+1; x<keymaplength; x+=2){
			if(keymap[x] == 240){ //Media key
				wait_for_sof = true;
				udi_hid_media_down(keymap[x+1]);
				lastUSBSendTime = millis;
				while(millis - lastUSBSendTime < 10);
				wait_for_sof = true;
				udi_hid_media_up();
				lastUSBSendTime = millis;
				while(millis - lastUSBSendTime < 10);
			} else {
				if(keymap[x+1] != 0){ //Don't send key
					wait_for_sof = true;
					udi_hid_kbd_modifier_down(keymap[x]);
					lastUSBSendTime = millis;
					while(millis - lastUSBSendTime < 10);
					wait_for_sof = true;
					udi_hid_kbd_down(keymap[x+1]);
					lastUSBSendTime = millis;
					while(millis - lastUSBSendTime < 10);
					wait_for_sof = true;
					udi_hid_kbd_up(keymap[x+1]);
					lastUSBSendTime = millis;
					while(millis - lastUSBSendTime < 10);
					wait_for_sof = true;
					udi_hid_kbd_modifier_up(keymap[x]);
					lastUSBSendTime = millis;
					while(millis - lastUSBSendTime < 10);
				}
			}
		}
	}

	/* F03 — haptic click.  Only fires when:
	 *   - the takeover animation isn't going to (button_flash off → bridge
	 *     owns LEDs → no built-in click), AND
	 *   - no F04 beep pattern is currently playing (per DESIGN.md §2,
	 *     pattern outranks haptic and we don't want to talk over it), AND
	 *   - no F06 hid burst is in flight (would be unbearable at ~100 Hz).
	 * Frequency/duration tuned to match the JOY personality click — proven
	 * audible on this piezo.  The buzzer cv formula is 15625/freq, so
	 * frequencies above ~2 kHz produce cv values too small to drive the
	 * piezo reliably. */
	if(haptic_click_enabled && !button_flash_enabled
	   && key >= 1 && key <= 6
	   && buzzer_current_owner() != BZO_PATTERN
	   && !burst_in_progress){
		buzzer_play_owned(BZO_HAPTIC, 1500, 15);
	}
}


/* ─── F06 — HID burst state machine ─────────────────────────────────────
 * Phases per (mod, key) pair:
 *   0 — modifier down  (10 ms hold)
 *   1 — key down       (10 ms hold)
 *   2 — key up         (10 ms hold)
 *   3 — modifier up    (10 ms hold)  → advance to next pair (or done)
 * For media keys (mod == 240) the 4 phases collapse to 2 (down/up).
 * hid_burst_tick() advances one phase per call when the inter-frame
 * deadline has elapsed, so the main loop continues to render LEDs and
 * poll buttons during a long burst. */

/* Per-frame hold (ms) between HID reports inside a burst.  The HID-Kbd
 * descriptor has bInterval = 2 ms (full-speed USB poll), so anything
 * shorter risks the host missing reports.  Legacy send_keys() uses 10 ms
 * for paranoid stability; F06 bursts are bursty by design and use the
 * descriptor-aligned minimum.  256 pairs × 4 frames × 2 ms ≈ 2.0 s. */
#define BURST_FRAME_MS 2

volatile bool burst_in_progress = false;

static uint8_t  _burst_buf[MAX_BURST_PAIRS * 2];
static uint16_t _burst_n_pairs = 0;
static uint16_t _burst_idx = 0;       /* current pair index */
static uint8_t  _burst_phase = 0;     /* 0..3 */
static uint32_t _burst_phase_end_ms = 0;
static uint8_t  _burst_cur_mod = 0;
static uint8_t  _burst_cur_key = 0;
static bool     _burst_cur_is_media = false;

burst_result_t hid_burst(const uint8_t *pairs, uint16_t n_pairs){
	if(n_pairs == 0){
		hid_burst_cancel();
		return BURST_EMPTY;
	}
	if(n_pairs > MAX_BURST_PAIRS) return BURST_TOO_LONG;
	if(burst_in_progress)         return BURST_BUSY;

	for(uint16_t i = 0; i < n_pairs * 2; i++) _burst_buf[i] = pairs[i];
	_burst_n_pairs       = n_pairs;
	_burst_idx           = 0;
	_burst_phase         = 0;
	_burst_phase_end_ms  = 0;       /* fire first frame immediately */
	burst_in_progress    = true;
	return BURST_OK;
}

void hid_burst_cancel(void){
	if(burst_in_progress){
		/* Release everything we may have left depressed. */
		udi_hid_kbd_up(_burst_cur_key);
		udi_hid_kbd_modifier_up(_burst_cur_mod);
		if(_burst_cur_is_media) udi_hid_media_up();
	}
	burst_in_progress    = false;
	_burst_n_pairs       = 0;
	_burst_idx           = 0;
	_burst_phase         = 0;
	_burst_phase_end_ms  = 0;
	_burst_cur_mod       = 0;
	_burst_cur_key       = 0;
	_burst_cur_is_media  = false;
}

/* ─── F07 vault ─────────────────────────────────────────────────────────
 * EEPROM offsets per main.h.  Each slot: 1-byte length followed by
 * VAULT_PAYLOAD_BYTES bytes of (mod, key) pairs.  Length is the number
 * of *pairs*, not bytes.  Length == 0 = empty slot. */

static uint16_t _vault_slot_len_offset(uint8_t slot){
	return (slot == 0) ? EEP_VAULT_SLOT0_LEN : EEP_VAULT_SLOT1_LEN;
}

static uint16_t _vault_slot_payload_offset(uint8_t slot){
	return (slot == 0) ? EEP_VAULT_SLOT0_PAYLOAD : EEP_VAULT_SLOT1_PAYLOAD;
}

vault_result_t vault_write(uint8_t slot, const uint8_t *pairs, uint8_t n_pairs){
	if(slot >= VAULT_SLOTS) return VAULT_BAD_SLOT;
	if(n_pairs > VAULT_MAX_PAIRS) return VAULT_TOO_LONG;

	uint8_t buf[VAULT_PAYLOAD_BYTES];
	for(uint8_t i = 0; i < VAULT_PAYLOAD_BYTES; i++) buf[i] = 0;
	for(uint8_t i = 0; i < (uint8_t)(n_pairs * 2); i++) buf[i] = pairs[i];

	rww_eeprom_emulator_write_buffer(_vault_slot_len_offset(slot), &n_pairs, 1);
	rww_eeprom_emulator_write_buffer(_vault_slot_payload_offset(slot), buf, VAULT_PAYLOAD_BYTES);
	rww_eeprom_emulator_commit_page_buffer();
	return VAULT_OK;
}

vault_result_t vault_clear(uint8_t slot){
	if(slot >= VAULT_SLOTS) return VAULT_BAD_SLOT;
	uint8_t zero = 0;
	rww_eeprom_emulator_write_buffer(_vault_slot_len_offset(slot), &zero, 1);
	rww_eeprom_emulator_commit_page_buffer();
	return VAULT_OK;
}

vault_result_t vault_fire(uint8_t slot){
	if(slot >= VAULT_SLOTS) return VAULT_BAD_SLOT;
	uint8_t len = 0;
	rww_eeprom_emulator_read_buffer(_vault_slot_len_offset(slot), &len, 1);
	if(len == 0) return VAULT_EMPTY;
	if(len > VAULT_MAX_PAIRS) return VAULT_TOO_LONG;
	uint8_t buf[VAULT_PAYLOAD_BYTES];
	rww_eeprom_emulator_read_buffer(_vault_slot_payload_offset(slot), buf, len * 2);
	burst_result_t r = hid_burst(buf, len);
	if(r == BURST_BUSY) return VAULT_BUSY;
	return VAULT_OK;
}

uint8_t vault_read_preview(uint8_t slot, uint8_t *preview_out, uint8_t preview_max){
	if(slot >= VAULT_SLOTS) return 0;
	uint8_t len = 0;
	rww_eeprom_emulator_read_buffer(_vault_slot_len_offset(slot), &len, 1);
	if(len == 0 || preview_max == 0 || preview_out == NULL) return len;
	uint8_t bytes_to_read = (uint8_t)(len * 2);
	if(bytes_to_read > preview_max) bytes_to_read = preview_max;
	rww_eeprom_emulator_read_buffer(_vault_slot_payload_offset(slot), preview_out, bytes_to_read);
	return len;
}


void hid_burst_tick(void){
	if(!burst_in_progress) return;
	if(_burst_phase_end_ms != 0 && (int32_t)(_burst_phase_end_ms - millis) > 0) return;
	/* The udi_hid_kbd transmit gate: send_report() in the ASF driver
	 * silently drops new reports while a previous one is in flight.
	 * Wait for it to complete before firing the next phase, otherwise
	 * fast bursts of identical keys collapse to a single visible char. */
	if(udi_hid_kbd_b_report_trans_ongoing) return;

	/* Pick up the current pair on phase 0. */
	if(_burst_phase == 0){
		if(_burst_idx >= _burst_n_pairs){
			burst_in_progress = false;
			return;
		}
		_burst_cur_mod      = _burst_buf[_burst_idx * 2 + 0];
		_burst_cur_key      = _burst_buf[_burst_idx * 2 + 1];
		_burst_cur_is_media = (_burst_cur_mod == 240);
	}

	wait_for_sof = true;

	if(_burst_cur_is_media){
		/* Media key: 2 phases collapse to down/up. */
		if(_burst_phase == 0){
			udi_hid_media_down(_burst_cur_key);
		} else if(_burst_phase == 2){
			udi_hid_media_up();
		}
		/* Phases 1 and 3 are no-ops for media keys; we still wait one
		 * frame each so the device-side timing matches the kbd path. */
	} else {
		switch(_burst_phase){
			case 0: udi_hid_kbd_modifier_down(_burst_cur_mod); break;
			case 1: udi_hid_kbd_down(_burst_cur_key);          break;
			case 2: udi_hid_kbd_up(_burst_cur_key);            break;
			case 3: udi_hid_kbd_modifier_up(_burst_cur_mod);   break;
		}
	}

	lastUSBSendTime     = millis;
	_burst_phase_end_ms = millis + BURST_FRAME_MS;

	_burst_phase++;
	if(_burst_phase >= 4){
		_burst_phase = 0;
		_burst_idx++;
		if(_burst_idx >= _burst_n_pairs){
			/* All done — let the final phase delay elapse on the next
			 * tick, then mark idle. */
			burst_in_progress = false;
		}
	}
}