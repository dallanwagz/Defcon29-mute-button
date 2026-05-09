/*
 * jiggler.c — see jiggler.h for design.
 */

#include "jiggler.h"
#include "udi_hid_kbd.h"

extern volatile uint32_t millis;
extern bool wait_for_sof;
extern uint32_t lastUSBSendTime;
extern bool main_b_cdc_enable;

#ifndef HID_MODIFIER_LEFT_SHIFT
#define HID_MODIFIER_LEFT_SHIFT 0x02
#endif

static uint32_t autonomous_end_ms = 0;   /* millis at which to stop */
static uint32_t last_pulse_ms = 0;
static bool     autonomous_active = false;

void jiggler_init(void) {
    autonomous_end_ms = 0;
    last_pulse_ms = 0;
    autonomous_active = false;
}

void jiggler_pulse_now(void) {
    /* Press + release LeftShift with no key.  Same gating as send_keys():
     * only emit while CDC is up (USB enumerated). */
    if (!main_b_cdc_enable) return;

    wait_for_sof = true;
    udi_hid_kbd_modifier_down(HID_MODIFIER_LEFT_SHIFT);
    lastUSBSendTime = millis;
    while (millis - lastUSBSendTime < 10);

    wait_for_sof = true;
    udi_hid_kbd_modifier_up(HID_MODIFIER_LEFT_SHIFT);
    lastUSBSendTime = millis;
    while (millis - lastUSBSendTime < 10);

    last_pulse_ms = millis;
}

void jiggler_set_autonomous_secs(uint32_t duration_secs) {
    if (duration_secs == 0) {
        jiggler_cancel_autonomous();
        return;
    }
    autonomous_end_ms = millis + (duration_secs * 1000u);
    last_pulse_ms = millis;     /* reset cadence so first pulse is in 30s */
    autonomous_active = true;
}

void jiggler_cancel_autonomous(void) {
    autonomous_active = false;
    autonomous_end_ms = 0;
}

bool jiggler_is_autonomous(void) {
    return autonomous_active;
}

void jiggler_tick(void) {
    if (!autonomous_active) return;

    /* End reached? */
    if ((int32_t)(autonomous_end_ms - millis) <= 0) {
        autonomous_active = false;
        autonomous_end_ms = 0;
        return;
    }

    /* Periodic pulse.  Fire on first tick after each interval boundary. */
    if ((millis - last_pulse_ms) >= JIGGLER_AUTONOMOUS_PERIOD_MS) {
        jiggler_pulse_now();    /* updates last_pulse_ms */
    }
}
