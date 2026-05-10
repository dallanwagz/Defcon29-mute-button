/*
 * usb_webusb.h — F11 stage 1: WebUSB + Microsoft OS 2.0 descriptors.
 *
 * Adds the descriptor surface a WebUSB-capable browser (Chrome, Edge)
 * needs to recognize the badge as a WebUSB device and auto-suggest the
 * landing-page URL on connect.  Stage 1 (this file) is descriptors +
 * vendor-request handler only — no new endpoints, no new interfaces.
 * Existing CDC + HID interfaces continue to enumerate alongside.
 *
 * Stage 2 (deferred): static web app + GitHub Pages deploy + the
 * vendor-class control transfer command for raw protocol bytes.
 *
 * The landing URL is hard-coded at compile time — see WEBUSB_LANDING_URL
 * in usb_webusb.c.  Changing it requires a re-flash.
 */

#ifndef USB_WEBUSB_H_
#define USB_WEBUSB_H_

#include <stdbool.h>

/* Wire our BOS descriptor pointer into udc_config.conf_bos.  Call once
 * after udc_start() in main(). */
void usb_webusb_init(void);

/* Vendor-request handler.  Wired into conf_usb.h via
 * USB_DEVICE_SPECIFIC_REQUEST().  Returns true if the request was
 * handled, false to let the USB stack STALL it.
 *
 * Handles:
 *   bRequest = WEBUSB_VENDOR_CODE (0x21), wIndex = 2 (GET_URL)
 *     → returns the WebUSB URL descriptor (landing page)
 *   bRequest = MS_OS_VENDOR_CODE  (0x22), wIndex = 7 (MS_OS_20_DESCRIPTOR_INDEX)
 *     → returns the MS-OS 2.0 descriptor set (WINUSB compat-id)
 */
bool usb_webusb_specific_request(void);

#endif /* USB_WEBUSB_H_ */
