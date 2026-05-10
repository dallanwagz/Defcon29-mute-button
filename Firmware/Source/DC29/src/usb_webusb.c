/*
 * usb_webusb.c — see usb_webusb.h for design.
 *
 * Bytes-level descriptor work.  Spec references:
 *   - WebUSB 1.0:           https://wicg.github.io/webusb/
 *   - Microsoft OS 2.0:     "Microsoft OS 2.0 Descriptors Specification.pdf"
 *   - USB 3.1 BOS:          USB 3.1 spec §9.6.2 (BOS) and §9.6.2.4 (Platform Capability)
 *
 * Total flash cost of this module: ~150 bytes of descriptor data plus
 * ~120 bytes of code.
 */

#include "usb_webusb.h"

#include <stdint.h>
#include <string.h>

#include "compiler.h"
#include "udc.h"
#include "udc_desc.h"
#include "udd.h"
#include "usb_protocol.h"


/* ─── Compile-time configuration ────────────────────────────────────── */

/* Landing URL the browser will offer to open when the badge is plugged
 * in.  Must match the actual GitHub Pages deploy.  Stored in the URL
 * descriptor without the scheme prefix (the bScheme byte indicates
 * https).  Changing this requires a firmware re-flash. */
#define WEBUSB_URL_NO_SCHEME      "dwagz1.github.io/dc29-config/"
#define WEBUSB_URL_NO_SCHEME_LEN  (sizeof(WEBUSB_URL_NO_SCHEME) - 1)
#define WEBUSB_URL_SCHEME_HTTPS   1

/* Vendor codes — chosen freely; the host learns them from the BOS
 * descriptor and uses them in subsequent vendor requests. */
#define WEBUSB_VENDOR_CODE        0x21
#define MS_OS_VENDOR_CODE         0x22

/* Microsoft OS 2.0 descriptor request index. */
#define MS_OS_20_DESCRIPTOR_INDEX 0x07
#define WEBUSB_REQUEST_GET_URL    0x02

/* USB 3.1 §9.6.2.4 device capability type for "Platform".  ASF's
 * usb_protocol.h only defines USB20_EXTENSION (0x02) so we declare
 * this locally. */
#define USB_DC_PLATFORM           0x05


/* ─── BOS descriptor + platform capability descriptors ──────────────── */

/* Sizes are baked into the structs below; if you edit either capability
 * descriptor, update the wTotalLength value too. */
#define BOS_HEADER_LEN            5
#define WEBUSB_PLATFORM_CAP_LEN   24
#define MS_OS_20_PLATFORM_CAP_LEN 28
#define BOS_TOTAL_LEN             (BOS_HEADER_LEN + WEBUSB_PLATFORM_CAP_LEN + MS_OS_20_PLATFORM_CAP_LEN)

/* MS-OS 2.0 descriptor set — minimal: header + WinUSB compat-id. */
#define MS_OS_20_HEADER_LEN       10
#define MS_OS_20_COMPAT_ID_LEN    20
#define MS_OS_20_TOTAL_LEN        (MS_OS_20_HEADER_LEN + MS_OS_20_COMPAT_ID_LEN)

COMPILER_PACK_SET(1)

/* Whole-blob BOS layout — ASF's udc.c sends the entire blob in one
 * payload using wTotalLength from the header. */
typedef struct {
	/* Header (5 bytes) */
	uint8_t  bLength;            /* 5 */
	uint8_t  bDescriptorType;    /* USB_DT_BOS = 0x0F */
	uint16_t wTotalLength;       /* total of header + all device caps (LE) */
	uint8_t  bNumDeviceCaps;     /* 2 */

	/* WebUSB Platform Capability (24 bytes) */
	uint8_t  webusb_bLength;             /* 24 */
	uint8_t  webusb_bDescriptorType;     /* USB_DT_DEVICE_CAPABILITY = 0x10 */
	uint8_t  webusb_bDevCapabilityType;  /* USB_DC_PLATFORM = 0x05 */
	uint8_t  webusb_bReserved;           /* 0 */
	uint8_t  webusb_PlatformCapabilityUUID[16];
	uint16_t webusb_bcdVersion;          /* 0x0100 */
	uint8_t  webusb_bVendorCode;         /* WEBUSB_VENDOR_CODE */
	uint8_t  webusb_iLandingPage;        /* 1 */

	/* Microsoft OS 2.0 Platform Capability (28 bytes) */
	uint8_t  msos_bLength;             /* 28 */
	uint8_t  msos_bDescriptorType;     /* 0x10 */
	uint8_t  msos_bDevCapabilityType;  /* 0x05 */
	uint8_t  msos_bReserved;           /* 0 */
	uint8_t  msos_PlatformCapabilityUUID[16];
	uint32_t msos_dwWindowsVersion;    /* 0x06030000 (Windows 8.1+) */
	uint16_t msos_wMSOSDescriptorSetTotalLength;
	uint8_t  msos_bMS_VendorCode;      /* MS_OS_VENDOR_CODE */
	uint8_t  msos_bAltEnumCode;        /* 0 */
} bos_blob_t;

COMPILER_PACK_RESET()

static const bos_blob_t _bos = {
	/* Header */
	.bLength               = BOS_HEADER_LEN,
	.bDescriptorType       = USB_DT_BOS,
	.wTotalLength          = BOS_TOTAL_LEN,
	.bNumDeviceCaps        = 2,

	/* WebUSB Platform Capability.
	 * UUID = {3408b638-09a9-47a0-8bfd-a0768815b665} (little-endian field
	 * order per RFC 4122 + WebUSB spec §3.1.1).  Hardcoded magic. */
	.webusb_bLength            = WEBUSB_PLATFORM_CAP_LEN,
	.webusb_bDescriptorType    = USB_DT_DEVICE_CAPABILITY,
	.webusb_bDevCapabilityType = USB_DC_PLATFORM,
	.webusb_bReserved          = 0,
	.webusb_PlatformCapabilityUUID = {
		0x38, 0xB6, 0x08, 0x34, 0xA9, 0x09, 0xA0, 0x47,
		0x8B, 0xFD, 0xA0, 0x76, 0x88, 0x15, 0xB6, 0x65,
	},
	.webusb_bcdVersion         = 0x0100,
	.webusb_bVendorCode        = WEBUSB_VENDOR_CODE,
	.webusb_iLandingPage       = 1,

	/* Microsoft OS 2.0 Platform Capability.
	 * UUID = {d8dd60df-4589-4cc7-9cd2-659d9e648a9f}. */
	.msos_bLength            = MS_OS_20_PLATFORM_CAP_LEN,
	.msos_bDescriptorType    = USB_DT_DEVICE_CAPABILITY,
	.msos_bDevCapabilityType = USB_DC_PLATFORM,
	.msos_bReserved          = 0,
	.msos_PlatformCapabilityUUID = {
		0xDF, 0x60, 0xDD, 0xD8, 0x89, 0x45, 0xC7, 0x4C,
		0x9C, 0xD2, 0x65, 0x9D, 0x9E, 0x64, 0x8A, 0x9F,
	},
	.msos_dwWindowsVersion              = 0x06030000,
	.msos_wMSOSDescriptorSetTotalLength = MS_OS_20_TOTAL_LEN,
	.msos_bMS_VendorCode                = MS_OS_VENDOR_CODE,
	.msos_bAltEnumCode                  = 0,
};


/* ─── WebUSB URL descriptor (landing page) ──────────────────────────── */

/* bLength = 3 + URL_LEN, bDescriptorType = 3 (URL), bScheme = 1 (https),
 * then URL bytes WITHOUT the scheme prefix. */
static const uint8_t _url_descriptor[3 + WEBUSB_URL_NO_SCHEME_LEN] = {
	(uint8_t)(3 + WEBUSB_URL_NO_SCHEME_LEN),
	0x03,                       /* bDescriptorType: URL */
	WEBUSB_URL_SCHEME_HTTPS,
	'd','w','a','g','z','1','.','g','i','t','h','u','b','.','i','o',
	'/','d','c','2','9','-','c','o','n','f','i','g','/',
};


/* ─── Microsoft OS 2.0 descriptor set ───────────────────────────────── */

static const uint8_t _msos20_set[MS_OS_20_TOTAL_LEN] = {
	/* MS_OS_20_SET_HEADER_DESCRIPTOR (10 bytes) */
	0x0A, 0x00,                 /* wLength = 10 */
	0x00, 0x00,                 /* wDescriptorType = MS_OS_20_SET_HEADER_DESCRIPTOR */
	0x00, 0x00, 0x03, 0x06,     /* dwWindowsVersion = 0x06030000 (Win 8.1+) */
	(uint8_t)(MS_OS_20_TOTAL_LEN & 0xFF),
	(uint8_t)((MS_OS_20_TOTAL_LEN >> 8) & 0xFF),

	/* MS_OS_20_FEATURE_COMPATIBLE_ID (20 bytes) */
	0x14, 0x00,                 /* wLength = 20 */
	0x03, 0x00,                 /* wDescriptorType = MS_OS_20_FEATURE_COMPATIBLE_ID */
	'W','I','N','U','S','B', 0x00, 0x00,    /* CompatibleID, 8 bytes */
	0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, /* SubCompatibleID, 8 bytes (none) */
};


/* ─── Init + vendor-request handler ──────────────────────────────────── */

void usb_webusb_init(void) {
	udc_config.conf_bos = (usb_dev_bos_desc_t *)&_bos;
}

bool usb_webusb_specific_request(void) {
	/* Direction must be Device-to-Host for both descriptor fetches we
	 * handle.  Vendor type is implicit — we're only invoked when the
	 * standard / class handlers stalled. */
	if (!Udd_setup_is_in()) return false;

	uint8_t  bRequest = udd_g_ctrlreq.req.bRequest;
	uint16_t wIndex   = udd_g_ctrlreq.req.wIndex;

	if (bRequest == WEBUSB_VENDOR_CODE && wIndex == WEBUSB_REQUEST_GET_URL) {
		udd_set_setup_payload((uint8_t *)_url_descriptor, sizeof(_url_descriptor));
		/* udc.c clamps payload_size to wLength after we return. */
		return true;
	}

	if (bRequest == MS_OS_VENDOR_CODE && wIndex == MS_OS_20_DESCRIPTOR_INDEX) {
		udd_set_setup_payload((uint8_t *)_msos20_set, sizeof(_msos20_set));
		return true;
	}

	return false;
}
