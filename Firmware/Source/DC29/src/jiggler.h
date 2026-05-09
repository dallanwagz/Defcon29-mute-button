/*
 * jiggler.h — F08a-lite Stay Awake (modifier-only HID wake pulses).
 *
 * Path 2 of the F08 design: instead of adding an HID-Mouse interface to
 * the USB composite descriptor (high-risk descriptor surgery — see
 * docs/hardware-features/features/F08-mouse-jiggler.md), we keep the
 * existing HID-Kbd interface and emit a no-op wake pulse:
 *   press LeftShift → release LeftShift
 * macOS treats any HID input as user activity for IOHIDIdleTime
 * accounting, so the host stays awake without any visible side effect
 * (modifier alone with no key produces no character).
 *
 * Same protocol surface as F08a:
 *   0x01 'j' 'M'                       — fire one wake pulse now
 *   0x01 'j' 'I' <duration_le32:4>     — start autonomous mode for N seconds
 *   0x01 'j' 'X'                       — cancel autonomous mode
 *
 * Deviation from spec: 'I' takes a *relative duration* (seconds from now)
 * rather than an absolute UTC end-time.  This sidesteps the F09 wall-clock
 * sync command (not yet implemented) and lets F08a-lite ship standalone.
 * The bridge translates abs/rel at its layer.
 */

#ifndef JIGGLER_H_
#define JIGGLER_H_

#include <stdbool.h>
#include <stdint.h>

#define JIGGLER_AUTONOMOUS_PERIOD_MS 30000u

void jiggler_init(void);

/* Fire one HID wake pulse immediately (press+release LeftShift). */
void jiggler_pulse_now(void);

/* Start autonomous mode for N seconds from now.  Restarts if already
 * active.  Pulses fire every JIGGLER_AUTONOMOUS_PERIOD_MS until end. */
void jiggler_set_autonomous_secs(uint32_t duration_secs);

/* Stop autonomous mode immediately. */
void jiggler_cancel_autonomous(void);

/* Returns true while autonomous mode is active. */
bool jiggler_is_autonomous(void);

/* Called from main loop.  Cheap when idle. */
void jiggler_tick(void);

#endif /* JIGGLER_H_ */
