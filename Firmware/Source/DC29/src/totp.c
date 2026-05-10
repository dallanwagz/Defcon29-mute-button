/*
 * totp.c — see totp.h for design.
 *
 * SHA-1 implementation is from-scratch, byte-aligned, no external crypto
 * library.  Verified against RFC 6238 Appendix B test vectors via the
 * host-side dc29/totp_test.py harness.
 *
 * Total flash footprint: ~1.4 KB (SHA-1 ~700 B, HMAC ~150 B, TOTP +
 * EEPROM glue ~250 B).  Well within the headroom we have post-F11.
 */

#include "totp.h"

#include <stdint.h>
#include <string.h>

#include "main.h"
#include "keys.h"
#include "rww_eeprom.h"


volatile uint32_t totp_wall_clock_unix = 0;


/* ─── SHA-1 (RFC 3174) ──────────────────────────────────────────────── */

#define SHA1_BLOCK_BYTES   64
#define SHA1_DIGEST_BYTES  20

typedef struct {
	uint32_t h[5];
	uint64_t total_bits;
	uint8_t  block[SHA1_BLOCK_BYTES];
	uint8_t  block_len;
} sha1_ctx_t;

static uint32_t _rotl32(uint32_t x, unsigned n){
	return (x << n) | (x >> (32 - n));
}

static void _sha1_block(sha1_ctx_t *c, const uint8_t blk[64]){
	uint32_t w[80];
	for(int i = 0; i < 16; i++){
		w[i] = ((uint32_t)blk[i*4]   << 24)
		     | ((uint32_t)blk[i*4+1] << 16)
		     | ((uint32_t)blk[i*4+2] <<  8)
		     | ((uint32_t)blk[i*4+3]);
	}
	for(int i = 16; i < 80; i++){
		w[i] = _rotl32(w[i-3] ^ w[i-8] ^ w[i-14] ^ w[i-16], 1);
	}

	uint32_t a = c->h[0], b = c->h[1], cc = c->h[2], d = c->h[3], e = c->h[4];
	for(int i = 0; i < 80; i++){
		uint32_t f, k;
		if(i < 20)      { f = (b & cc) | ((~b) & d);            k = 0x5A827999u; }
		else if(i < 40) { f = b ^ cc ^ d;                       k = 0x6ED9EBA1u; }
		else if(i < 60) { f = (b & cc) | (b & d) | (cc & d);    k = 0x8F1BBCDCu; }
		else            { f = b ^ cc ^ d;                       k = 0xCA62C1D6u; }
		uint32_t t = _rotl32(a, 5) + f + e + k + w[i];
		e = d;
		d = cc;
		cc = _rotl32(b, 30);
		b = a;
		a = t;
	}
	c->h[0] += a;
	c->h[1] += b;
	c->h[2] += cc;
	c->h[3] += d;
	c->h[4] += e;
}

static void sha1_init(sha1_ctx_t *c){
	c->h[0] = 0x67452301u;
	c->h[1] = 0xEFCDAB89u;
	c->h[2] = 0x98BADCFEu;
	c->h[3] = 0x10325476u;
	c->h[4] = 0xC3D2E1F0u;
	c->total_bits = 0;
	c->block_len = 0;
}

static void sha1_update(sha1_ctx_t *c, const uint8_t *data, uint32_t len){
	c->total_bits += (uint64_t)len * 8u;
	while(len){
		uint32_t take = SHA1_BLOCK_BYTES - c->block_len;
		if(take > len) take = len;
		memcpy(c->block + c->block_len, data, take);
		c->block_len += take;
		data += take;
		len  -= take;
		if(c->block_len == SHA1_BLOCK_BYTES){
			_sha1_block(c, c->block);
			c->block_len = 0;
		}
	}
}

static void sha1_final(sha1_ctx_t *c, uint8_t out[SHA1_DIGEST_BYTES]){
	c->block[c->block_len++] = 0x80;
	if(c->block_len > 56){
		while(c->block_len < 64) c->block[c->block_len++] = 0;
		_sha1_block(c, c->block);
		c->block_len = 0;
	}
	while(c->block_len < 56) c->block[c->block_len++] = 0;
	uint64_t tb = c->total_bits;
	for(int i = 7; i >= 0; i--) c->block[c->block_len++] = (uint8_t)(tb >> (i*8));
	_sha1_block(c, c->block);
	for(int i = 0; i < 5; i++){
		out[i*4 + 0] = (uint8_t)(c->h[i] >> 24);
		out[i*4 + 1] = (uint8_t)(c->h[i] >> 16);
		out[i*4 + 2] = (uint8_t)(c->h[i] >>  8);
		out[i*4 + 3] = (uint8_t)(c->h[i]      );
	}
}


/* ─── HMAC-SHA1 (RFC 2104) ──────────────────────────────────────────── */

static void hmac_sha1(const uint8_t *key, uint32_t key_len,
                      const uint8_t *msg, uint32_t msg_len,
                      uint8_t out[SHA1_DIGEST_BYTES]){
	uint8_t k0[SHA1_BLOCK_BYTES] = {0};
	uint8_t ipad[SHA1_BLOCK_BYTES];
	uint8_t opad[SHA1_BLOCK_BYTES];
	sha1_ctx_t c;

	if(key_len > SHA1_BLOCK_BYTES){
		sha1_init(&c);
		sha1_update(&c, key, key_len);
		sha1_final(&c, k0);
	} else {
		memcpy(k0, key, key_len);
	}

	for(int i = 0; i < SHA1_BLOCK_BYTES; i++){
		ipad[i] = k0[i] ^ 0x36;
		opad[i] = k0[i] ^ 0x5c;
	}

	uint8_t inner[SHA1_DIGEST_BYTES];
	sha1_init(&c);
	sha1_update(&c, ipad, SHA1_BLOCK_BYTES);
	sha1_update(&c, msg, msg_len);
	sha1_final(&c, inner);

	sha1_init(&c);
	sha1_update(&c, opad, SHA1_BLOCK_BYTES);
	sha1_update(&c, inner, SHA1_DIGEST_BYTES);
	sha1_final(&c, out);
}


/* ─── RFC 4226 dynamic-truncation + RFC 6238 wrapper ─────────────────── */

static uint32_t _hotp_code(const uint8_t key[TOTP_KEY_LEN], uint64_t counter){
	/* Counter is big-endian per RFC 4226. */
	uint8_t msg[8];
	for(int i = 7; i >= 0; i--){
		msg[i] = (uint8_t)(counter & 0xFF);
		counter >>= 8;
	}
	uint8_t hash[SHA1_DIGEST_BYTES];
	hmac_sha1(key, TOTP_KEY_LEN, msg, sizeof(msg), hash);

	uint8_t off = hash[SHA1_DIGEST_BYTES - 1] & 0x0F;
	uint32_t bin = ((uint32_t)(hash[off]     & 0x7F) << 24)
	             | ((uint32_t)(hash[off + 1] & 0xFF) << 16)
	             | ((uint32_t)(hash[off + 2] & 0xFF) <<  8)
	             | ((uint32_t)(hash[off + 3] & 0xFF));
	return bin % 1000000u; /* 6 digits per F09 Q2 */
}

void totp_compute(const uint8_t key[TOTP_KEY_LEN],
                  uint32_t unix_time,
                  uint8_t  digits_out[TOTP_DIGITS]){
	uint64_t t = (uint64_t)unix_time / TOTP_PERIOD_SECS;
	uint32_t code = _hotp_code(key, t);
	for(int i = TOTP_DIGITS - 1; i >= 0; i--){
		digits_out[i] = (uint8_t)('0' + (code % 10));
		code /= 10;
	}
}


/* ─── EEPROM glue ────────────────────────────────────────────────────── */

totp_result_t totp_provision(uint8_t slot, const uint8_t *label, const uint8_t *key){
	if(slot >= TOTP_SLOTS) return TOTP_BAD_SLOT;
	rww_eeprom_emulator_write_buffer(EEP_TOTP_SLOT0_LABEL, (uint8_t *)label, TOTP_LABEL_LEN);
	rww_eeprom_emulator_write_buffer(EEP_TOTP_SLOT0_KEY,   (uint8_t *)key,   TOTP_KEY_LEN);
	rww_eeprom_emulator_commit_page_buffer();
	return TOTP_OK;
}

totp_result_t totp_read_label(uint8_t slot, uint8_t *label_out){
	if(slot >= TOTP_SLOTS) return TOTP_BAD_SLOT;
	rww_eeprom_emulator_read_buffer(EEP_TOTP_SLOT0_LABEL, label_out, TOTP_LABEL_LEN);
	return TOTP_OK;
}

static bool _slot_provisioned(uint8_t slot){
	if(slot >= TOTP_SLOTS) return false;
	uint8_t label[TOTP_LABEL_LEN];
	rww_eeprom_emulator_read_buffer(EEP_TOTP_SLOT0_LABEL, label, TOTP_LABEL_LEN);
	for(uint8_t i = 0; i < TOTP_LABEL_LEN; i++){
		if(label[i] != 0 && label[i] != 0xFF) return true;
	}
	return false;
}


/* ─── Fire path — uses F06 hid_burst ─────────────────────────────────── */

/* ASCII '0'..'9' → HID Usage IDs.  HID 0x1E='1', 0x1F='2', ..., 0x26='9',
 * and 0x27='0' (the zero key follows the nine in the keyboard table). */
static uint8_t _digit_to_hid(uint8_t ascii_digit){
	if(ascii_digit == '0') return 0x27;
	return 0x1E + (ascii_digit - '1');
}

totp_result_t totp_fire(uint8_t slot){
	if(slot >= TOTP_SLOTS)              return TOTP_BAD_SLOT;
	if(totp_wall_clock_unix == 0)       return TOTP_NO_CLOCK;
	if(!_slot_provisioned(slot))        return TOTP_EMPTY;

	uint8_t key[TOTP_KEY_LEN];
	rww_eeprom_emulator_read_buffer(EEP_TOTP_SLOT0_KEY, key, TOTP_KEY_LEN);

	uint8_t digits[TOTP_DIGITS];
	totp_compute(key, totp_wall_clock_unix, digits);

	uint8_t pairs[TOTP_DIGITS * 2];
	for(uint8_t i = 0; i < TOTP_DIGITS; i++){
		pairs[i*2 + 0] = 0;                       /* no modifier */
		pairs[i*2 + 1] = _digit_to_hid(digits[i]);
	}
	burst_result_t r = hid_burst(pairs, TOTP_DIGITS);
	return (r == BURST_BUSY) ? TOTP_BUSY : TOTP_OK;
}
