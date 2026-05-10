/*
 * usb_modes.c — see usb_modes.h for design.
 *
 * Two main pieces:
 *   1. Boot-time button debounce → usb_mode_t.
 *   2. Variant USB descriptors that we splice into ASF's `udc_config`
 *      before `udc_start()` is called.
 *
 * Default mode (CDC + HID-Kbd) uses the descriptors declared in
 * vendored `udi_composite_desc.c` — we leave `udc_config` untouched
 * for that case.  The two alt modes (KBD-only, CDC-only) are
 * hand-rolled here with hand-set bInterfaceNumber values so they don't
 * need any ASF macro overrides.
 */

#include "usb_modes.h"

#include <string.h>

#include "compiler.h"
#include "main.h"
#include "delay.h"
#include "port.h"
#include "udd.h"
#include "udc.h"
#include "udc_desc.h"
#include "usb_protocol.h"
#include "usb_protocol_cdc.h"
#include "usb_atmel.h"
#include "udi_cdc.h"
#include "udi_hid_kbd.h"
#include "pwm.h"
#include "conf_usb.h"


/* ─── Boot-time button sample (3-sample debounce) ────────────────────── */

static const uint32_t _BUTTON_PINS[4] = { BUTTON1, BUTTON2, BUTTON3, BUTTON4 };

/* Returns a 4-bit bitmap where bit i = 1 means button i (0-based) is
 * pressed (pin reads LOW with pull-up). */
static uint8_t _read_button_bitmap(void){
	uint8_t b = 0;
	for(uint8_t i = 0; i < 4; i++){
		if(!port_pin_get_input_level(_BUTTON_PINS[i])) b |= (1u << i);
	}
	return b;
}

usb_mode_t usb_select_mode_at_boot(void){
	/* 3-sample debounce: take samples at +10 ms, +30 ms, +50 ms; require
	 * all three to agree before committing to a non-default mode.  The
	 * delays use the existing delay_cycles_ms helper which is initialized
	 * earlier in main(). */
	uint8_t s1, s2, s3;
	delay_cycles_ms(10); s1 = _read_button_bitmap();
	delay_cycles_ms(20); s2 = _read_button_bitmap();
	delay_cycles_ms(20); s3 = _read_button_bitmap();
	if(!(s1 == s2 && s2 == s3)) return USB_MODE_DEFAULT;

	uint8_t b = s1;
	if(b == 0)            return USB_MODE_DEFAULT;
	if(b == 0x01)         return USB_MODE_KBD_ONLY;   /* B1 alone */
	if(b == 0x02)         return USB_MODE_RESERVED;   /* B2 alone (reserved) */
	if(b == 0x04)         return USB_MODE_CDC_ONLY;   /* B3 alone */
	/* Anything else (including B4 — handled by bootloader anyway —
	 * or multi-button combos) falls back to default. */
	return USB_MODE_DEFAULT;
}


/* ─── KBD-only mode descriptors ──────────────────────────────────────── */

/* HID-Kbd interface descriptor with bInterfaceNumber forced to 0.
 * The default UDI_HID_KBD_DESC bakes UDI_HID_KBD_IFACE_NUMBER (= 2) in
 * — for KBD-only mode we need it at 0 since it's the sole interface. */
COMPILER_PACK_SET(1)
typedef struct {
	usb_iface_desc_t       iface;
	usb_hid_descriptor_t   hid;
	usb_ep_desc_t          ep;
} _kbd_iface_t;
COMPILER_PACK_RESET()

#ifndef USB_DT_HID
#define USB_DT_HID         0x21
#endif
#ifndef USB_DT_HID_REPORT
#define USB_DT_HID_REPORT  0x22
#endif
#ifndef USB_HID_NUM_DESC
#define USB_HID_NUM_DESC   1
#endif
#ifndef USB_HID_BDC_V1_11
#define USB_HID_BDC_V1_11  0x0111
#endif
#ifndef USB_HID_NO_COUNTRY_CODE
#define USB_HID_NO_COUNTRY_CODE 0
#endif
#ifndef HID_CLASS
#define HID_CLASS                    0x03
#endif
#ifndef HID_SUB_CLASS_NOBOOT
#define HID_SUB_CLASS_NOBOOT         0x00
#endif
#ifndef HID_PROTOCOL_KEYBOARD
#define HID_PROTOCOL_KEYBOARD        0x01
#endif

/* Report-descriptor type from the kbd UDI — declared extern so we can
 * read its size for wDescriptorLength. */
extern udi_hid_kbd_report_desc_t udi_hid_kbd_report_desc;

COMPILER_PACK_SET(1)
typedef struct {
	usb_conf_desc_t  conf;
	_kbd_iface_t     kbd;
} _kbd_only_desc_t;
COMPILER_PACK_RESET()

COMPILER_WORD_ALIGNED
static UDC_DESC_STORAGE _kbd_only_desc_t _desc_kbd = {
	.conf = {
		.bLength             = sizeof(usb_conf_desc_t),
		.bDescriptorType     = USB_DT_CONFIGURATION,
		.wTotalLength        = LE16(sizeof(_kbd_only_desc_t)),
		.bNumInterfaces      = 1,
		.bConfigurationValue = 1,
		.iConfiguration      = 0,
		.bmAttributes        = USB_CONFIG_ATTR_MUST_SET | USB_DEVICE_ATTR,
		.bMaxPower           = USB_CONFIG_MAX_POWER(USB_DEVICE_POWER),
	},
	.kbd = {
		.iface = {
			.bLength            = sizeof(usb_iface_desc_t),
			.bDescriptorType    = USB_DT_INTERFACE,
			.bInterfaceNumber   = 0,         /* HARD-SET to 0 for KBD-only */
			.bAlternateSetting  = 0,
			.bNumEndpoints      = 1,
			.bInterfaceClass    = HID_CLASS,
			.bInterfaceSubClass = HID_SUB_CLASS_NOBOOT,
			.bInterfaceProtocol = HID_PROTOCOL_KEYBOARD,
			.iInterface         = 0,
		},
		.hid = {
			.bLength            = sizeof(usb_hid_descriptor_t),
			.bDescriptorType    = USB_DT_HID,
			.bcdHID             = LE16(USB_HID_BDC_V1_11),
			.bCountryCode       = USB_HID_NO_COUNTRY_CODE,
			.bNumDescriptors    = USB_HID_NUM_DESC,
			.bRDescriptorType   = USB_DT_HID_REPORT,
			.wDescriptorLength  = LE16(sizeof(udi_hid_kbd_report_desc_t)),
		},
		.ep = {
			.bLength         = sizeof(usb_ep_desc_t),
			.bDescriptorType = USB_DT_ENDPOINT,
			.bEndpointAddress = UDI_HID_KBD_EP_IN,
			.bmAttributes    = USB_EP_TYPE_INTERRUPT,
			.wMaxPacketSize  = LE16(UDI_HID_KBD_EP_SIZE),
			.bInterval       = 2,
		},
	},
};

extern udi_api_t udi_api_hid_kbd;
static UDC_DESC_STORAGE udi_api_t *_udi_apis_kbd[1] = { &udi_api_hid_kbd };

static UDC_DESC_STORAGE udc_config_speed_t _config_speed_kbd[1] = {{
	.desc     = (usb_conf_desc_t UDC_DESC_STORAGE *)&_desc_kbd,
	.udi_apis = _udi_apis_kbd,
}};


/* ─── CDC-only mode descriptors ──────────────────────────────────────── */

/* CDC interfaces stay at 0+1 (matches the default), so we can reuse
 * the macro-generated CDC sub-descriptors directly.  Just drop the
 * HID-Kbd block and shrink wTotalLength + bNumInterfaces. */

COMPILER_PACK_SET(1)
typedef struct {
	usb_conf_desc_t       conf;
	usb_iad_desc_t        udi_cdc_iad;
	udi_cdc_comm_desc_t   udi_cdc_comm;
	udi_cdc_data_desc_t   udi_cdc_data;
} _cdc_only_desc_t;
COMPILER_PACK_RESET()

COMPILER_WORD_ALIGNED
static UDC_DESC_STORAGE _cdc_only_desc_t _desc_cdc = {
	.conf = {
		.bLength             = sizeof(usb_conf_desc_t),
		.bDescriptorType     = USB_DT_CONFIGURATION,
		.wTotalLength        = LE16(sizeof(_cdc_only_desc_t)),
		.bNumInterfaces      = 2,            /* CDC = 2 interfaces (comm + data) */
		.bConfigurationValue = 1,
		.iConfiguration      = 0,
		.bmAttributes        = USB_CONFIG_ATTR_MUST_SET | USB_DEVICE_ATTR,
		.bMaxPower           = USB_CONFIG_MAX_POWER(USB_DEVICE_POWER),
	},
	.udi_cdc_iad  = UDI_CDC_IAD_DESC_0,
	.udi_cdc_comm = UDI_CDC_COMM_DESC_0,
	.udi_cdc_data = UDI_CDC_DATA_DESC_0_FS,
};

extern udi_api_t udi_api_cdc_comm;
extern udi_api_t udi_api_cdc_data;
static UDC_DESC_STORAGE udi_api_t *_udi_apis_cdc[2] = {
	&udi_api_cdc_comm,
	&udi_api_cdc_data,
};

static UDC_DESC_STORAGE udc_config_speed_t _config_speed_cdc[1] = {{
	.desc     = (usb_conf_desc_t UDC_DESC_STORAGE *)&_desc_cdc,
	.udi_apis = _udi_apis_cdc,
}};


/* ─── Per-mode device descriptors (rotate bcdDevice) ────────────────── */

extern usb_dev_desc_t udc_device_desc;   /* default, declared in udi_composite_desc.c */

/* Custom device descriptors for each non-default mode — bcdDevice
 * differs so Windows treats each as a distinct device and re-enumerates
 * fresh on first plug-in (matching the F10 spec / DESIGN.md §4 plan). */
COMPILER_WORD_ALIGNED
static UDC_DESC_STORAGE usb_dev_desc_t _device_desc_kbd = {
	.bLength            = sizeof(usb_dev_desc_t),
	.bDescriptorType    = USB_DT_DEVICE,
	.bcdUSB             = LE16(USB_V2_0),
	.bDeviceClass       = 0,             /* HID-only — class on iface, not device */
	.bDeviceSubClass    = 0,
	.bDeviceProtocol    = 0,
	.bMaxPacketSize0    = USB_DEVICE_EP_CTRL_SIZE,
	.idVendor           = LE16(USB_DEVICE_VENDOR_ID),
	.idProduct          = LE16(USB_DEVICE_PRODUCT_ID),
	.bcdDevice          = LE16(0x0101),  /* per F10 mode table */
	.iManufacturer      = 1,
	.iProduct           = 2,
	.iSerialNumber      = 3,
	.bNumConfigurations = 1,
};

COMPILER_WORD_ALIGNED
static UDC_DESC_STORAGE usb_dev_desc_t _device_desc_cdc = {
	.bLength            = sizeof(usb_dev_desc_t),
	.bDescriptorType    = USB_DT_DEVICE,
	.bcdUSB             = LE16(USB_V2_0),
	.bDeviceClass       = 0x02,          /* CDC */
	.bDeviceSubClass    = 0,
	.bDeviceProtocol    = 0,
	.bMaxPacketSize0    = USB_DEVICE_EP_CTRL_SIZE,
	.idVendor           = LE16(USB_DEVICE_VENDOR_ID),
	.idProduct          = LE16(USB_DEVICE_PRODUCT_ID),
	.bcdDevice          = LE16(0x0103),  /* per F10 mode table */
	.iManufacturer      = 1,
	.iProduct           = 2,
	.iSerialNumber      = 3,
	.bNumConfigurations = 1,
};


/* ─── Public install / LED feedback ─────────────────────────────────── */

void usb_install_mode(usb_mode_t mode){
	switch(mode){
		case USB_MODE_KBD_ONLY:
			udc_config.confdev_lsfs = &_device_desc_kbd;
			udc_config.conf_lsfs    = _config_speed_kbd;
			break;
		case USB_MODE_CDC_ONLY:
			udc_config.confdev_lsfs = &_device_desc_cdc;
			udc_config.conf_lsfs    = _config_speed_cdc;
			break;
		case USB_MODE_RESERVED:
		case USB_MODE_DEFAULT:
		default:
			/* Leave udc_config alone — it already points at the default
			 * composite descriptors set up by udi_composite_desc.c. */
			break;
	}
}


/* LED-feedback helper.  Flashes the LED corresponding to the held
 * button twice white (~150 ms each, ~100 ms gap) per F10 success
 * criteria.  Must be called AFTER pwm_init() — runs blocking for ~500 ms. */
void usb_mode_led_feedback(usb_mode_t mode){
	uint8_t led;
	switch(mode){
		case USB_MODE_KBD_ONLY: led = 1; break;   /* B1's LED */
		case USB_MODE_RESERVED: led = 2; break;   /* B2's LED — sampled but no mode */
		case USB_MODE_CDC_ONLY: led = 3; break;   /* B3's LED */
		case USB_MODE_DEFAULT:
		default:                led = 1; break;   /* per spec, default flashes LED 1 */
	}
	uint8_t white[3] = { 200, 200, 200 };
	uint8_t off[3]   = { 0, 0, 0 };
	for(uint8_t i = 0; i < 2; i++){
		led_set_color(led, white);
		delay_cycles_ms(150);
		led_set_color(led, off);
		delay_cycles_ms(100);
	}
}
