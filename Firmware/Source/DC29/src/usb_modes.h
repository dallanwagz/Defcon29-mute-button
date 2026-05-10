/*
 * usb_modes.h — F10 boot-time HID class switch.
 *
 * At cold-start, before USB enumeration, we sample the button matrix
 * with a 3-sample debounce and pick a USB descriptor variant:
 *
 *   no button held → MODE_DEFAULT — CDC + HID-Kbd (today's behavior)
 *   B1 held         → MODE_KBD_ONLY — HID-Kbd only (corporate hosts that block composite USB)
 *   B2 held         → reserved (falls back to MODE_DEFAULT; flash B2 LED so the user knows it was sampled)
 *   B3 held         → MODE_CDC_ONLY — CDC only (debug / lockdown)
 *   B4 held         → DFU bootloader (hardware-level, untouched)
 *
 * Each non-default mode rotates `bcdDevice` so Windows treats each as a
 * distinct USB device and re-enumerates fresh on first plug-in.
 *
 * The bootloader's B4-trigger runs in a separate flash region BEFORE
 * any of our code, so DFU recovery is always available regardless of
 * what we do here.
 *
 * Spec deviations from the original F10 design (recorded in tracker):
 *   - Single-button holds (B1/B2/B3) instead of B1+B4 chord for Mode 3.
 *   - Mode 2 (HID-Kbd + HID-Mouse) is reserved, not implemented —
 *     we don't have an HID-Mouse interface (F08 used the keyboard-
 *     wake-pulse fallback specifically to avoid descriptor surgery).
 */

#ifndef USB_MODES_H_
#define USB_MODES_H_

#include <stdbool.h>
#include <stdint.h>

typedef enum {
	USB_MODE_DEFAULT  = 0,   /* CDC + HID-Kbd (today's composite) */
	USB_MODE_KBD_ONLY = 1,   /* HID-Kbd only — drop CDC */
	USB_MODE_RESERVED = 2,   /* B2 reserved for future HID-Mouse */
	USB_MODE_CDC_ONLY = 3,   /* CDC only — drop HID-Kbd */
} usb_mode_t;

/* Sample the button matrix at cold-start with a 3-sample debounce
 * (~10 ms / ~30 ms / ~50 ms after entry).  Returns the mode the user
 * is requesting; defaults to USB_MODE_DEFAULT if no button is held
 * or if the samples disagree (bounce). */
usb_mode_t usb_select_mode_at_boot(void);

/* Patch udc_config so the next udc_start() exposes the chosen mode's
 * descriptor variant.  Must be called BEFORE udc_start(). */
void usb_install_mode(usb_mode_t mode);

/* Flash the LED corresponding to the held button twice white as
 * confirmation of the chosen mode.  Default mode flashes LED 1.
 * Blocking — runs once at boot before USB starts, ~500 ms total. */
void usb_mode_led_feedback(usb_mode_t mode);

#endif /* USB_MODES_H_ */
