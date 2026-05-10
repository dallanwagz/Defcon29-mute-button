/*
 * totp.h — F09 RFC 6238 TOTP (firmware side).
 *
 * Stores ONE 20-byte raw key + 4-char label in EEPROM (the slot
 * pre-reserved by F07's v3 EEPROM bump — see DESIGN.md §3).  Host
 * pushes wall-clock UTC seconds via 0x01 'o' 'T' immediately before
 * firing, so the badge clock is treated as a write-once-per-fire
 * scratch register and we never have to trust the SAMD21 RTC for
 * more than the 30-second TOTP window.
 *
 * Crypto is HMAC-SHA1 + RFC 4226 dynamic-truncation, RFC 6238 time
 * step T = floor(unix / 30), 6-digit output (per F09 Q2 default-accept).
 *
 * Security: EEPROM is plaintext; anyone with physical access can
 * dump the key via UF2.  Use only for low-stakes accounts / demos.
 */

#ifndef TOTP_H_
#define TOTP_H_

#include <stdbool.h>
#include <stdint.h>

#define TOTP_SLOTS         1
#define TOTP_KEY_LEN       20      /* raw post-base32 SHA-1 block-aligned key */
#define TOTP_LABEL_LEN     4       /* 4-char short label, ASCII */
#define TOTP_DIGITS        6
#define TOTP_PERIOD_SECS   30

typedef enum {
	TOTP_OK         = 0,
	TOTP_BAD_SLOT   = 1,
	TOTP_NO_CLOCK   = 2,    /* fire called before time-sync */
	TOTP_BUSY       = 3,    /* hid_burst busy */
	TOTP_EMPTY      = 4,    /* slot label is all-zero (never provisioned) */
} totp_result_t;

/* Wall-clock UTC seconds, set via 0x01 'o' 'T'.  RAM-only — bridge
 * always re-syncs before firing. */
extern volatile uint32_t totp_wall_clock_unix;

/* Provision a slot.  `key` must be exactly TOTP_KEY_LEN bytes; `label`
 * exactly TOTP_LABEL_LEN bytes (ASCII; padding at the host's discretion). */
totp_result_t totp_provision(uint8_t slot, const uint8_t *label, const uint8_t *key);

/* Read the slot's label (TOTP_LABEL_LEN bytes) into `label_out`.
 * NEVER exposes the key — by design, list / preview only echoes the
 * label so the EEPROM secret can't be read back over CDC. */
totp_result_t totp_read_label(uint8_t slot, uint8_t *label_out);

/* Compute the current 6-digit code at totp_wall_clock_unix and type it
 * via hid_burst() (F06).  Returns TOTP_NO_CLOCK if the host hasn't
 * synced time yet, TOTP_EMPTY if the slot was never provisioned. */
totp_result_t totp_fire(uint8_t slot);

/* Test-friendly: compute the code for an explicit (key, unix) pair and
 * write the 6 ASCII digits into `digits_out`.  Used by the firmware-
 * side golden-vector path the host harness exercises via CDC. */
void totp_compute(const uint8_t key[TOTP_KEY_LEN],
                  uint32_t unix_time,
                  uint8_t  digits_out[TOTP_DIGITS]);

#endif /* TOTP_H_ */
