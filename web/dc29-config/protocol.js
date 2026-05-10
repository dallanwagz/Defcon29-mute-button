// dc29-config — protocol.js
//
// Mirror of the bits of dc29/protocol.py the web app needs.  Kept in
// sync by hand — when the firmware protocol changes, update both this
// file and protocol.py.

export const ESCAPE = 0x01;

// host → badge
export const CMD_MUTED         = 'M'.charCodeAt(0);
export const CMD_UNMUTED       = 'U'.charCodeAt(0);
export const CMD_CLEAR         = 'X'.charCodeAt(0);
export const CMD_SET_KEY       = 'K'.charCodeAt(0);
export const CMD_QUERY_KEY     = 'Q'.charCodeAt(0);
export const CMD_SET_LED       = 'L'.charCodeAt(0);
export const CMD_PAINT_ALL     = 'P'.charCodeAt(0);
export const CMD_BUTTON_FLASH  = 'F'.charCodeAt(0);
export const CMD_SET_EFFECT    = 'E'.charCodeAt(0);
export const CMD_FIRE_TAKEOVER = 'T'.charCodeAt(0);
export const CMD_SET_SLIDER    = 'S'.charCodeAt(0);
export const CMD_SET_SPLASH    = 'I'.charCodeAt(0);
export const CMD_HAPTIC_CLICK  = 'k'.charCodeAt(0);
export const CMD_BEEP_PATTERN  = 'p'.charCodeAt(0);
export const CMD_HID_BURST     = 'h'.charCodeAt(0);
export const CMD_JIGGLER       = 'j'.charCodeAt(0);
export const CMD_VAULT         = 'v'.charCodeAt(0);

// badge → host event types
export const EVT_BUTTON      = 'B'.charCodeAt(0);
export const EVT_KEY_REPLY   = 'R'.charCodeAt(0);
export const EVT_KEY_ACK     = 'A'.charCodeAt(0);
export const EVT_EFFECT_MODE = 'V'.charCodeAt(0);
export const EVT_CHORD       = 'C'.charCodeAt(0);
export const EVT_BUTTON_EXT  = 'b'.charCodeAt(0);

export const VAULT_SLOTS     = 2;
export const VAULT_MAX_PAIRS = 16;
export const MAX_BURST_PAIRS = 256;

export const TOTP_SLOTS      = 1;
export const TOTP_LABEL_LEN  = 4;
export const TOTP_KEY_LEN    = 20;

// Firmware effect mode IDs (matches dc29.protocol.EffectMode for the
// shipped 0..7 set).
export const EffectMode = {
    OFF:           0,
    RAINBOW_CHASE: 1,
    BREATHE:       2,
    WIPE:          3,
    TWINKLE:       4,
    GRADIENT:      5,
    THEATER:       6,
    CYLON:         7,
};

export const CMD_TOTP        = 'o'.charCodeAt(0);

export const BeepPattern = {
    SILENCE:        0,
    CONFIRM:        1,
    DECLINE:        2,
    TEAMS_RINGING:  3,
    TEAMS_MUTE_ON:  4,
    TEAMS_MUTE_OFF: 5,
    CI_PASSED:      6,
    CI_FAILED:      7,
    KICK:           8,
};

// ASCII → HID Usage ID, mirror of dc29/badge.py _ASCII_UNSHIFTED + _SHIFTED.
const HID_MOD_LSHIFT = 0x02;
const _UNSHIFTED = (() => {
    const m = {};
    "abcdefghijklmnopqrstuvwxyz".split("").forEach((ch, i) => { m[ch] = 4 + i; });
    Object.assign(m, {
        "1": 0x1E, "2": 0x1F, "3": 0x20, "4": 0x21, "5": 0x22,
        "6": 0x23, "7": 0x24, "8": 0x25, "9": 0x26, "0": 0x27,
        "\n": 0x28, "\t": 0x2B, " ": 0x2C,
        "-": 0x2D, "=": 0x2E, "[": 0x2F, "]": 0x30, "\\": 0x31,
        ";": 0x33, "'": 0x34, "`": 0x35, ",": 0x36, ".": 0x37, "/": 0x38,
    });
    return m;
})();
const _SHIFTED = (() => {
    const m = {};
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ".split("").forEach((ch, i) => { m[ch] = 4 + i; });
    Object.assign(m, {
        "!": 0x1E, "@": 0x1F, "#": 0x20, "$": 0x21, "%": 0x22,
        "^": 0x23, "&": 0x24, "*": 0x25, "(": 0x26, ")": 0x27,
        "_": 0x2D, "+": 0x2E, "{": 0x2F, "}": 0x30, "|": 0x31,
        ":": 0x33, '"': 0x34, "~": 0x35, "<": 0x36, ">": 0x37, "?": 0x38,
    });
    return m;
})();

export function asciiToHidPair(ch) {
    if (ch in _UNSHIFTED) return [0, _UNSHIFTED[ch]];
    if (ch in _SHIFTED)   return [HID_MOD_LSHIFT, _SHIFTED[ch]];
    return null;
}

export function textToHidPairs(text) {
    const out = [];
    for (const ch of text) {
        const p = asciiToHidPair(ch);
        if (p) out.push(p);
    }
    return out;
}


// ─── Base32 decode (RFC 4648).  Lenient: strips whitespace + dashes,
// uppercases, pads to a multiple of 8.  Returns Uint8Array.
const _B32_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";

export function base32Decode(s) {
    const cleaned = s.replace(/[\s-]/g, "").toUpperCase().replace(/=+$/, "");
    if (!cleaned) return new Uint8Array(0);
    let bits = 0;
    let value = 0;
    const out = [];
    for (const ch of cleaned) {
        const v = _B32_ALPHABET.indexOf(ch);
        if (v < 0) throw new Error(`invalid base32 character: ${ch}`);
        value = (value << 5) | v;
        bits += 5;
        if (bits >= 8) {
            bits -= 8;
            out.push((value >> bits) & 0xff);
        }
    }
    return new Uint8Array(out);
}


// ─── BadgeAPI — talks to the badge's CDC port via the Web Serial API.
//
// Same byte-level protocol as dc29/badge.py.  Keeps a small RX state
// machine that recognizes the 0x01 'b' event family (currently used by
// vault_list replies; extensible to button_ext events later).
//
// All methods return Promises.

export class BadgeAPI {
    constructor() {
        this.port = null;
        this.reader = null;
        this.writer = null;
        this._rxBuf = [];
        this._readerLoopRunning = false;
        this._vaultListPending = null;  // {entries, expected, resolve, timer}
        this._totpListPending  = null;  // {entries, expected, resolve, timer}

        // RX state machine
        this._rxState = 0;       // 0 = idle, 1 = awaiting cmd, 2 = collecting args
        this._rxCmd = 0;
        this._rxArgs = [];
        this._rxNeed = 0;

        // Public callbacks (assignable from the UI).
        this.onButton    = null;   // (btn, mod, kc) — EVT_BUTTON 'B'
        this.onButtonExt = null;   // (kind, btn_a, btn_b|null) — kinds 'double'/'triple'/'long'/'chord'
        this.onChord     = null;   // (chord_type) — 1=short, 2=long
        this.onEffect    = null;   // (mode_id) — EVT_EFFECT_MODE 'V'
        this.onKeyAck    = null;   // (btn) — EVT_KEY_ACK 'A'
        this.onKeyReply  = null;   // (btn, mod, kc) — EVT_KEY_REPLY 'R'
    }

    get connected() {
        return this.port !== null && this.writer !== null;
    }

    async connect() {
        if (!('serial' in navigator)) {
            throw new Error("Web Serial API not available in this browser.  Use Chrome / Edge.");
        }
        // Always show the picker — gives the user explicit control.
        this.port = await navigator.serial.requestPort();
        await this.port.open({ baudRate: 115200 });   // ignored for USB-CDC, required by API
        this.writer = this.port.writable.getWriter();
        this._startReader();
    }

    async disconnect() {
        try { if (this.reader) await this.reader.cancel(); } catch {}
        try { if (this.writer) this.writer.releaseLock(); } catch {}
        try { if (this.port) await this.port.close(); } catch {}
        this.reader = null;
        this.writer = null;
        this.port = null;
        this._readerLoopRunning = false;
    }

    async _write(bytes) {
        if (!this.writer) throw new Error("not connected");
        await this.writer.write(new Uint8Array(bytes));
    }

    _startReader() {
        if (this._readerLoopRunning) return;
        this._readerLoopRunning = true;
        (async () => {
            this.reader = this.port.readable.getReader();
            try {
                while (true) {
                    const { value, done } = await this.reader.read();
                    if (done) break;
                    if (value) for (const b of value) this._processByte(b);
                }
            } catch (err) {
                console.warn("reader loop ended:", err);
            } finally {
                try { this.reader.releaseLock(); } catch {}
                this.reader = null;
                this._readerLoopRunning = false;
            }
        })();
    }

    _processByte(b) {
        // Mirror of dc29/badge.py _process_rx + _dispatch_rx.
        if (this._rxState === 0) {
            if (b === ESCAPE) { this._rxState = 1; }
            return;
        }
        if (this._rxState === 1) {
            this._rxCmd = b;
            this._rxArgs = [];
            // Default arg counts.
            const COUNTS = {
                [EVT_BUTTON]:      3,
                [EVT_KEY_REPLY]:   3,
                [EVT_KEY_ACK]:     1,
                [EVT_EFFECT_MODE]: 1,
                [EVT_CHORD]:       1,
                [EVT_BUTTON_EXT]:  -1,  // special: first arg is kind, expands count
            };
            const need = COUNTS[b];
            if (need === undefined) { this._rxState = 0; return; }
            if (need === 0) { this._dispatch(); this._rxState = 0; return; }
            this._rxNeed = need;
            this._rxState = 2;
            return;
        }
        if (this._rxState === 2) {
            this._rxArgs.push(b);
            // Variable-length expansion for EVT_BUTTON_EXT.
            if (this._rxCmd === EVT_BUTTON_EXT && this._rxArgs.length === 1) {
                const kind = this._rxArgs[0];
                if      (kind === 'V'.charCodeAt(0))            this._rxNeed = 11; // F07 vault list reply
                else if (kind === 'O'.charCodeAt(0))            this._rxNeed = 6;  // F09 totp list reply
                else if (kind === 'C'.charCodeAt(0))            this._rxNeed = 3;  // F02 chord
                else if ([0x32, 0x33, 0x4C].includes(kind))     this._rxNeed = 2;  // F01 double/triple/long
                else { this._rxState = 0; return; }
            }
            if (this._rxArgs.length >= this._rxNeed) {
                this._dispatch();
                this._rxState = 0;
            }
        }
    }

    _dispatch() {
        const cmd  = this._rxCmd;
        const args = this._rxArgs;

        if (cmd === EVT_BUTTON && args.length === 3) {
            if (this.onButton) { try { this.onButton(args[0], args[1], args[2]); } catch (e) { console.warn(e); } }
            return;
        }
        if (cmd === EVT_KEY_REPLY && args.length === 3) {
            if (this.onKeyReply) { try { this.onKeyReply(args[0], args[1], args[2]); } catch (e) { console.warn(e); } }
            return;
        }
        if (cmd === EVT_KEY_ACK && args.length === 1) {
            if (this.onKeyAck) { try { this.onKeyAck(args[0]); } catch (e) { console.warn(e); } }
            return;
        }
        if (cmd === EVT_EFFECT_MODE && args.length === 1) {
            if (this.onEffect) { try { this.onEffect(args[0]); } catch (e) { console.warn(e); } }
            return;
        }
        if (cmd === EVT_CHORD && args.length === 1) {
            if (this.onChord) { try { this.onChord(args[0]); } catch (e) { console.warn(e); } }
            return;
        }
        if (cmd === EVT_BUTTON_EXT) {
            const kind = args[0];

            // F07 vault list reply.
            if (kind === 'V'.charCodeAt(0) && this._vaultListPending) {
                const slot    = args[1];
                const length  = args[2];
                const preview = args.slice(3, 11);
                this._vaultListPending.entries.push({ slot, length, preview });
                if (this._vaultListPending.entries.length >= this._vaultListPending.expected) {
                    clearTimeout(this._vaultListPending.timer);
                    this._vaultListPending.resolve(
                        this._vaultListPending.entries.sort((a, b) => a.slot - b.slot)
                    );
                    this._vaultListPending = null;
                }
                return;
            }

            // F09 totp list reply.
            if (kind === 'O'.charCodeAt(0) && this._totpListPending) {
                const slot  = args[1];
                const label = args.slice(2, 6);
                this._totpListPending.entries.push({ slot, label });
                if (this._totpListPending.entries.length >= this._totpListPending.expected) {
                    clearTimeout(this._totpListPending.timer);
                    this._totpListPending.resolve(
                        this._totpListPending.entries.sort((a, b) => a.slot - b.slot)
                    );
                    this._totpListPending = null;
                }
                return;
            }

            // F01/F02 modifier events.
            if (this.onButtonExt) {
                const kindMap = {
                    [0x32]: 'double',
                    [0x33]: 'triple',
                    [0x4C]: 'long',
                    [0x43]: 'chord',
                };
                const kindStr = kindMap[kind];
                if (kindStr) {
                    const btn_a = args[1];
                    const btn_b = (kindStr === 'chord' && args.length >= 3) ? args[2] : null;
                    try { this.onButtonExt(kindStr, btn_a, btn_b); } catch (e) { console.warn(e); }
                }
            }
        }
    }

    // ─── Public commands ──────────────────────────────────────────────

    async setLed(n, r, g, b) {
        await this._write([ESCAPE, CMD_SET_LED, n & 0xff, r & 0xff, g & 0xff, b & 0xff]);
    }

    async paintAll(c1, c2, c3, c4) {
        await this._write([ESCAPE, CMD_PAINT_ALL, ...c1, ...c2, ...c3, ...c4]);
    }

    async setEffectMode(n) {
        await this._write([ESCAPE, CMD_SET_EFFECT, n & 0xff]);
    }

    async setHapticClick(enabled) {
        await this._write([ESCAPE, CMD_HAPTIC_CLICK, enabled ? 1 : 0]);
    }

    async setButtonFlash(enabled) {
        await this._write([ESCAPE, CMD_BUTTON_FLASH, enabled ? 1 : 0]);
    }

    async fireTakeover(btn) {
        await this._write([ESCAPE, CMD_FIRE_TAKEOVER, btn & 0xff]);
    }

    async playBeep(patternId) {
        await this._write([ESCAPE, CMD_BEEP_PATTERN, patternId & 0xff]);
    }

    async awakePulse() {
        await this._write([ESCAPE, CMD_JIGGLER, 'M'.charCodeAt(0)]);
    }

    async awakeSetDuration(secs) {
        const d = secs & 0xffffffff;
        await this._write([
            ESCAPE, CMD_JIGGLER, 'I'.charCodeAt(0),
            d & 0xff, (d >> 8) & 0xff, (d >> 16) & 0xff, (d >> 24) & 0xff,
        ]);
    }

    async awakeCancel() {
        await this._write([ESCAPE, CMD_JIGGLER, 'X'.charCodeAt(0)]);
    }

    async vaultWriteText(slot, text) {
        const pairs = textToHidPairs(text);
        if (pairs.length > VAULT_MAX_PAIRS) {
            throw new Error(
                `text packs to ${pairs.length} pairs but vault slot holds only ${VAULT_MAX_PAIRS}`
            );
        }
        const buf = [ESCAPE, CMD_VAULT, 'W'.charCodeAt(0), slot & 0xff, pairs.length & 0xff];
        for (const [m, k] of pairs) { buf.push(m & 0xff, k & 0xff); }
        await this._write(buf);
        return pairs.length;
    }

    async vaultFire(slot) {
        await this._write([ESCAPE, CMD_VAULT, 'F'.charCodeAt(0), slot & 0xff]);
    }

    async vaultClear(slot) {
        await this._write([ESCAPE, CMD_VAULT, 'C'.charCodeAt(0), slot & 0xff]);
    }

    // ─── F06 HID burst (used by the "Type any string" panel) ─────────

    async hidBurst(pairs) {
        // Auto-chunk to MAX_BURST_PAIRS per command; wait between chunks
        // for the firmware to finish (~10 ms per pair × frames).
        let i = 0;
        const total = pairs.length;
        while (i < total) {
            const chunkN = Math.min(MAX_BURST_PAIRS, total - i);
            const buf = [
                ESCAPE, CMD_HID_BURST,
                chunkN & 0xff, (chunkN >> 8) & 0xff,
            ];
            for (let j = 0; j < chunkN; j++) {
                const [m, k] = pairs[i + j];
                buf.push(m & 0xff, k & 0xff);
            }
            await this._write(buf);
            // Per-pair cost: 4 frames × ~10 ms (transmit-flag gated, BURST_FRAME_MS=2).
            // Pad slack so we never collide with BURST_BUSY.
            await new Promise((r) => setTimeout(r, chunkN * 12 + 80));
            i += chunkN;
        }
    }

    async typeString(text) {
        const pairs = textToHidPairs(text);
        if (pairs.length === 0) return 0;
        await this.hidBurst(pairs);
        return pairs.length;
    }

    // ─── Keymap (existing CMD_SET_KEY / CMD_QUERY_KEY) ────────────────

    async setKey(button, modifier, keycode) {
        await this._write([
            ESCAPE, CMD_SET_KEY,
            button & 0xff, modifier & 0xff, keycode & 0xff,
        ]);
    }

    async queryKey(button) {
        // Fire-and-forget; the reply arrives via onKeyReply.  Caller
        // wires its own callback before invoking and unwires after.
        await this._write([ESCAPE, CMD_QUERY_KEY, button & 0xff]);
    }

    // ─── WLED knobs ───────────────────────────────────────────────────

    async wledSet(speed, intensity, palette) {
        await this._write([
            ESCAPE, 'W'.charCodeAt(0),
            speed & 0xff, intensity & 0xff, palette & 0xff,
        ]);
    }

    async setSliderEnabled(enabled) {
        await this._write([ESCAPE, CMD_SET_SLIDER, enabled ? 1 : 0]);
    }

    async setSplashOnPress(enabled) {
        await this._write([ESCAPE, CMD_SET_SPLASH, enabled ? 1 : 0]);
    }

    // ─── F09 TOTP ─────────────────────────────────────────────────────

    async totpProvision(slot, label, base32Secret) {
        if (slot < 0 || slot >= TOTP_SLOTS) {
            throw new Error(`slot must be 0..${TOTP_SLOTS - 1}, got ${slot}`);
        }
        let key = base32Decode(base32Secret);
        if (key.length < TOTP_KEY_LEN) {
            // Pad with zeros to TOTP_KEY_LEN.
            const padded = new Uint8Array(TOTP_KEY_LEN);
            padded.set(key);
            key = padded;
        } else if (key.length > TOTP_KEY_LEN) {
            key = key.slice(0, TOTP_KEY_LEN);
        }
        const lblBytes = new TextEncoder().encode(label).slice(0, TOTP_LABEL_LEN);
        const lbl = new Uint8Array(TOTP_LABEL_LEN);
        lbl.set(lblBytes);
        const buf = [ESCAPE, CMD_TOTP, 'W'.charCodeAt(0), slot & 0xff];
        for (const b of lbl) buf.push(b);
        for (const b of key) buf.push(b);
        await this._write(buf);
    }

    async totpSyncTime(unixSeconds = null) {
        const t = unixSeconds === null ? Math.floor(Date.now() / 1000) : Math.floor(unixSeconds);
        const ts = t >>> 0;
        await this._write([
            ESCAPE, CMD_TOTP, 'T'.charCodeAt(0),
            ts & 0xff, (ts >> 8) & 0xff, (ts >> 16) & 0xff, (ts >> 24) & 0xff,
        ]);
    }

    async totpFire(slot) {
        await this._write([ESCAPE, CMD_TOTP, 'F'.charCodeAt(0), slot & 0xff]);
    }

    async totpList(timeoutMs = 1000) {
        return new Promise(async (resolve) => {
            this._totpListPending = {
                entries: [],
                expected: TOTP_SLOTS,
                resolve,
                timer: setTimeout(() => {
                    if (this._totpListPending) {
                        const entries = this._totpListPending.entries;
                        this._totpListPending = null;
                        resolve(entries.sort((a, b) => a.slot - b.slot));
                    }
                }, timeoutMs),
            };
            try {
                await this._write([ESCAPE, CMD_TOTP, 'L'.charCodeAt(0)]);
            } catch (err) {
                clearTimeout(this._totpListPending.timer);
                this._totpListPending = null;
                resolve([]);
                throw err;
            }
        });
    }

    async vaultList(timeoutMs = 1000) {
        // Synchronously gather VAULT_SLOTS replies from the badge.
        return new Promise(async (resolve) => {
            this._vaultListPending = {
                entries: [],
                expected: VAULT_SLOTS,
                resolve,
                timer: setTimeout(() => {
                    if (this._vaultListPending) {
                        const entries = this._vaultListPending.entries;
                        this._vaultListPending = null;
                        resolve(entries.sort((a, b) => a.slot - b.slot));
                    }
                }, timeoutMs),
            };
            try {
                await this._write([ESCAPE, CMD_VAULT, 'L'.charCodeAt(0)]);
            } catch (err) {
                clearTimeout(this._vaultListPending.timer);
                this._vaultListPending = null;
                resolve([]);
                throw err;
            }
        });
    }
}
