/*
 * input.c — F01 (tap-count + long-press) + F02 (2-button chords) state machine.
 *
 * See docs/hardware-features/features/F01-tap-count-long-press.md and F02-chords.md.
 *
 * Layered on top of the existing button1..button4 ISR flag pattern:
 *   - Buttons with NO modifier mapping fall through to the legacy fast path —
 *     send_keys(n) fires immediately on flag, just like before.
 *   - Buttons WITH any modifier mapping (double, triple, long, or any chord
 *     involving them) consume the flag and run the SM.  Single-tap fires after
 *     the multi-tap window expires.
 *
 * Release detection is done by polling pin levels (pull-up; LOW = pressed),
 * because the existing EXTINT only fires on falling edge.
 */

#include "input.h"
#include "keys.h"
#include "udi_cdc.h"
#include "asf.h"

extern volatile bool button1, button2, button3, button4;
extern volatile uint32_t millis;
extern bool main_b_cdc_enable;

/* RAM-only modifier table (per F01 design — EEPROM persistence is a follow-up). */
static input_action_t action_double[4];
static input_action_t action_triple[4];
static input_action_t action_long[4];
static input_action_t action_chord[4][4]; /* [a][b], a < b */

/* Per-button SM state. */
typedef enum {
    BSM_IDLE = 0,
    BSM_PRESS_HELD,        /* button currently held; not yet decided */
    BSM_AWAIT_TAPCOUNT,    /* released; counting taps within window */
    BSM_CONSUMED,          /* press consumed (chord or long-press fired); awaiting release */
} bsm_t;

typedef struct {
    bsm_t       state;
    uint32_t    press_start_ms;
    uint32_t    last_release_ms;
    uint8_t     tap_count;       /* 1 = single, 2 = double, etc. */
    bool        was_pressed;     /* edge detection */
} button_state_t;

static button_state_t bs[4];

static const uint32_t BUTTON_PINS[4] = { BUTTON1, BUTTON2, BUTTON3, BUTTON4 };

/* ───────────────────────────────────────────────────────────── helpers */

static bool action_is_set(const input_action_t *a) {
    return a && (a->mod || a->key);
}

/* True if button (0-based) participates in any modifier or chord mapping.
 * Used by the fast path to short-circuit the SM. */
static bool button_has_any_modifier(uint8_t bidx) {
    if (bidx >= 4) return false;
    if (action_is_set(&action_double[bidx])) return true;
    if (action_is_set(&action_triple[bidx])) return true;
    if (action_is_set(&action_long[bidx])) return true;
    for (uint8_t i = 0; i < 4; i++) {
        if (i == bidx) continue;
        uint8_t a = (bidx < i) ? bidx : i;
        uint8_t b = (bidx < i) ? i : bidx;
        if (action_is_set(&action_chord[a][b])) return true;
    }
    return false;
}

/* True if pin level reads LOW (pressed). */
static bool pin_pressed(uint8_t bidx) {
    return !port_pin_get_input_level(BUTTON_PINS[bidx]);
}

/* Fire (mod, key) via existing HID path.  Mirrors the per-pair logic in
 * keys.c:send_keys(), without the EEPROM-keymap walk. */
static void fire_action(const input_action_t *a) {
    if (!a || !a->key) return;
    extern bool wait_for_sof;
    extern uint32_t lastUSBSendTime;
    if (a->mod == 240) { /* media key */
        wait_for_sof = true;
        udi_hid_media_down(a->key);
        lastUSBSendTime = millis;
        while (millis - lastUSBSendTime < 10);
        wait_for_sof = true;
        udi_hid_media_up();
        lastUSBSendTime = millis;
        while (millis - lastUSBSendTime < 10);
    } else {
        wait_for_sof = true;
        udi_hid_kbd_modifier_down(a->mod);
        lastUSBSendTime = millis;
        while (millis - lastUSBSendTime < 10);
        wait_for_sof = true;
        udi_hid_kbd_down(a->key);
        lastUSBSendTime = millis;
        while (millis - lastUSBSendTime < 10);
        wait_for_sof = true;
        udi_hid_kbd_up(a->key);
        lastUSBSendTime = millis;
        while (millis - lastUSBSendTime < 10);
        wait_for_sof = true;
        udi_hid_kbd_modifier_up(a->mod);
        lastUSBSendTime = millis;
        while (millis - lastUSBSendTime < 10);
    }
}

/* Send 0x01 'b' <kind> <btn[, btn_b]> over CDC. */
static void emit_event(input_evt_t kind, uint8_t btn1based, uint8_t btn1based_b) {
    if (!main_b_cdc_enable) return;
    if (kind == INPUT_EVT_CHORD) {
        uint8_t evt[5] = { 0x01, 'b', (uint8_t)kind, btn1based, btn1based_b };
        udi_cdc_write_buf(evt, 5);
    } else {
        uint8_t evt[4] = { 0x01, 'b', (uint8_t)kind, btn1based };
        udi_cdc_write_buf(evt, 4);
    }
}

/* Fire the per-button modifier action and emit the event. */
static void fire_tapcount(uint8_t bidx, uint8_t count) {
    if (count == 2 && action_is_set(&action_double[bidx])) {
        fire_action(&action_double[bidx]);
        emit_event(INPUT_EVT_DOUBLE, bidx + 1, 0);
    } else if (count == 3 && action_is_set(&action_triple[bidx])) {
        fire_action(&action_triple[bidx]);
        emit_event(INPUT_EVT_TRIPLE, bidx + 1, 0);
    } else if (count == 1) {
        /* Single-tap falls through to the legacy keymap-based send_keys. */
        send_keys(bidx + 1);
    }
    /* counts > 3 with no triple binding: ignore (could be configurable later) */
}

static void fire_long(uint8_t bidx) {
    if (action_is_set(&action_long[bidx])) {
        fire_action(&action_long[bidx]);
        emit_event(INPUT_EVT_LONG, bidx + 1, 0);
    } else {
        /* No long mapping: fall through to single-tap behavior. */
        send_keys(bidx + 1);
    }
}

static void fire_chord(uint8_t a, uint8_t b) {
    /* a < b; both 0-based */
    if (action_is_set(&action_chord[a][b])) {
        fire_action(&action_chord[a][b]);
        emit_event(INPUT_EVT_CHORD, a + 1, b + 1);
    }
}

/* ───────────────────────────────────────────────────────────── public API */

void input_init(void) {
    for (uint8_t i = 0; i < 4; i++) {
        bs[i].state = BSM_IDLE;
        bs[i].press_start_ms = 0;
        bs[i].last_release_ms = 0;
        bs[i].tap_count = 0;
        bs[i].was_pressed = false;
        action_double[i] = (input_action_t){ 0, 0 };
        action_triple[i] = (input_action_t){ 0, 0 };
        action_long[i] = (input_action_t){ 0, 0 };
        for (uint8_t j = 0; j < 4; j++) {
            action_chord[i][j] = (input_action_t){ 0, 0 };
        }
    }
}

void input_set_action_double(uint8_t btn, uint8_t mod, uint8_t key) {
    if (btn >= 1 && btn <= 4) action_double[btn - 1] = (input_action_t){ mod, key };
}
void input_set_action_triple(uint8_t btn, uint8_t mod, uint8_t key) {
    if (btn >= 1 && btn <= 4) action_triple[btn - 1] = (input_action_t){ mod, key };
}
void input_set_action_long(uint8_t btn, uint8_t mod, uint8_t key) {
    if (btn >= 1 && btn <= 4) action_long[btn - 1] = (input_action_t){ mod, key };
}
void input_set_action_chord(uint8_t btn_a, uint8_t btn_b, uint8_t mod, uint8_t key) {
    if (btn_a < 1 || btn_a > 4 || btn_b < 1 || btn_b > 4 || btn_a == btn_b) return;
    uint8_t a = btn_a - 1, b = btn_b - 1;
    if (a > b) { uint8_t t = a; a = b; b = t; }
    action_chord[a][b] = (input_action_t){ mod, key };
}
void input_clear_all_actions(void) {
    input_init();
}

/* Per-tick press-edge detection: combines ISR flag and pin level.
 * The ISR sets buttonN=true on falling edge after debounce; we read pin
 * level directly to detect release. */
static bool consume_press_edge(uint8_t bidx) {
    bool ret = false;
    switch (bidx) {
        case 0: if (button1) { button1 = false; ret = true; } break;
        case 1: if (button2) { button2 = false; ret = true; } break;
        case 2: if (button3) { button3 = false; ret = true; } break;
        case 3: if (button4) { button4 = false; ret = true; } break;
    }
    return ret;
}

void input_tick(void) {
    uint32_t now = millis;

    /* Phase 1: per-button state machine update + fast-path fire. */
    for (uint8_t i = 0; i < 4; i++) {
        bool press_edge = consume_press_edge(i);
        bool currently_pressed = pin_pressed(i);
        bool release_edge = bs[i].was_pressed && !currently_pressed;
        bs[i].was_pressed = currently_pressed;

        /* Fast path: no modifier mappings → fire immediately on press flag, exit. */
        if (!button_has_any_modifier(i)) {
            if (press_edge) send_keys(i + 1);
            bs[i].state = BSM_IDLE;
            bs[i].tap_count = 0;
            continue;
        }

        switch (bs[i].state) {
            case BSM_IDLE:
                if (press_edge) {
                    bs[i].state = BSM_PRESS_HELD;
                    bs[i].press_start_ms = now;
                    bs[i].tap_count = 1;
                }
                break;

            case BSM_PRESS_HELD:
                if (release_edge) {
                    uint32_t held = now - bs[i].press_start_ms;
                    if (held >= LONG_PRESS_THRESH_MS) {
                        fire_long(i);
                        bs[i].state = BSM_IDLE;
                        bs[i].tap_count = 0;
                    } else {
                        bs[i].last_release_ms = now;
                        bs[i].state = BSM_AWAIT_TAPCOUNT;
                    }
                }
                break;

            case BSM_AWAIT_TAPCOUNT:
                if (press_edge) {
                    bs[i].tap_count++;
                    bs[i].state = BSM_PRESS_HELD;
                    bs[i].press_start_ms = now;
                } else if ((now - bs[i].last_release_ms) > MULTI_TAP_WINDOW_MS) {
                    fire_tapcount(i, bs[i].tap_count);
                    bs[i].state = BSM_IDLE;
                    bs[i].tap_count = 0;
                }
                break;

            case BSM_CONSUMED:
                if (release_edge) {
                    bs[i].state = BSM_IDLE;
                    bs[i].tap_count = 0;
                }
                break;
        }
    }

    /* Phase 2: chord detection.
     * If two buttons are simultaneously in BSM_PRESS_HELD and their press
     * timestamps are within CHORD_WINDOW_MS, fire the chord (if mapped) and
     * mark both consumed. */
    for (uint8_t a = 0; a < 4; a++) {
        if (bs[a].state != BSM_PRESS_HELD) continue;
        for (uint8_t b = a + 1; b < 4; b++) {
            if (bs[b].state != BSM_PRESS_HELD) continue;
            uint32_t da = (bs[a].press_start_ms > bs[b].press_start_ms)
                              ? bs[a].press_start_ms - bs[b].press_start_ms
                              : bs[b].press_start_ms - bs[a].press_start_ms;
            if (da > CHORD_WINDOW_MS) continue;
            if (!action_is_set(&action_chord[a][b])) continue;
            fire_chord(a, b);
            bs[a].state = BSM_CONSUMED;
            bs[b].state = BSM_CONSUMED;
            bs[a].tap_count = 0;
            bs[b].tap_count = 0;
        }
    }
}
