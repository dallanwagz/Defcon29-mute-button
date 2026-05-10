// audio_reactive.js — browser-side audio-reactive engine.
//
// Replaces the BlackHole + Multi-Output Device dance the Python
// `dc29 audio-reactive` bridge needs.  Web Audio + getDisplayMedia
// captures system / tab audio directly; a small FFT + bass-energy
// beat detector drives the badge LEDs and (optionally) fires the
// F04 KICK pattern on each beat.
//
// Designed for testability: the AudioReactiveEngine processes a single
// frame of FFT data per .tick(frequencyData) call, so Playwright can
// pump synthetic data without needing a real AudioContext.  The
// `startScreenCapture(engine)` helper handles all the Web Audio +
// getDisplayMedia plumbing for the live use case.

// Color palettes — name → 4 RGB tuples, indexed by FFT-band amplitude.
// All saturated, high-contrast palettes that read well on the badge LEDs.
export const AUDIO_PALETTES = {
    rainbow:  [[255, 0, 0], [255, 128, 0], [128, 255, 0], [0, 128, 255]],
    sunset:   [[255, 64, 0], [255, 128, 32], [200, 32, 96], [80, 0, 128]],
    ocean:    [[0, 64, 128], [0, 128, 200], [0, 200, 255], [128, 240, 255]],
    fire:     [[80, 0, 0], [200, 32, 0], [255, 128, 0], [255, 220, 96]],
    party:    [[255, 0, 128], [255, 200, 0], [0, 255, 128], [0, 128, 255]],
};

const DEFAULT_PALETTE = "rainbow";

// Bass-energy beat detection tunables.
const HISTORY_LEN = 30;       // ~0.5 s at 60 fps — short enough to follow tempo changes
const MIN_BEAT_GAP_MS = 80;   // ignore beats within 80 ms of the previous (matches F05 throttle)


export class AudioReactiveEngine {
    constructor(badge, opts = {}) {
        this.badge = badge;
        this.beatThreshold = opts.beatThreshold ?? 1.5;     // σ above rolling mean
        this.driveLeds     = opts.driveLeds     !== false;
        this.fireBeats     = opts.fireBeats     !== false;
        this.palette       = opts.palette       ?? DEFAULT_PALETTE;
        this._bassHistory  = [];
        this._lastBeatTs   = 0;
        this._lastFftSnapshot = null;   // for the optional UI bar viz
    }

    /**
     * Process one frame of FFT magnitude data.
     *
     * @param {Uint8Array} frequencyData  — output of AnalyserNode.getByteFrequencyData;
     *                                       each bin is 0..255.
     * @param {number} [nowMs]  — overridable timestamp for testability.
     * @returns {Promise<{beat: boolean, bass: number}>}
     */
    async tick(frequencyData, nowMs = Date.now()) {
        if (!frequencyData || frequencyData.length === 0) return { beat: false, bass: 0 };

        this._lastFftSnapshot = frequencyData;

        const bass = computeBassEnergy(frequencyData);
        this._bassHistory.push(bass);
        if (this._bassHistory.length > HISTORY_LEN) this._bassHistory.shift();

        const beat = this._detectBeat(bass, nowMs);

        if (beat && this.fireBeats && this.badge) {
            try { await this.badge.playBeep(8); }    // KICK
            catch (e) { /* swallow — engine shouldn't crash on transient badge errors */ }
        }

        if (this.driveLeds && this.badge) {
            const colors = fftToColors(frequencyData, AUDIO_PALETTES[this.palette] || AUDIO_PALETTES[DEFAULT_PALETTE]);
            try { await this.badge.paintAll(...colors); }
            catch (e) { /* same */ }
        }

        return { beat, bass };
    }

    _detectBeat(bass, nowMs) {
        if (this._bassHistory.length < 8) return false;          // need some history first
        if ((nowMs - this._lastBeatTs) < MIN_BEAT_GAP_MS) return false;

        const mean = average(this._bassHistory);
        const std  = stddev(this._bassHistory, mean);
        if (std < 1) return false;                                // silence: no beat detection

        const isBeat = bass > mean + this.beatThreshold * std;
        if (isBeat) this._lastBeatTs = nowMs;
        return isBeat;
    }

    /** Snapshot the most recent FFT data for an optional UI bar visualization. */
    lastFft() { return this._lastFftSnapshot; }
}


// ─── Helpers (exported for unit testing) ───────────────────────────

export function computeBassEnergy(frequencyData) {
    // Average of the 8 lowest bins — corresponds to <~250 Hz at 44.1 kHz / 256-bin FFT.
    let sum = 0;
    const n = Math.min(8, frequencyData.length);
    for (let i = 0; i < n; i++) sum += frequencyData[i];
    return sum / n;
}

export function fftToColors(frequencyData, palette) {
    // Split the FFT into 4 bands (low/mid-low/mid-high/high), use each
    // band's amplitude to scale the brightness of the corresponding
    // palette color.
    const out = [];
    const len = frequencyData.length;
    const bandSize = Math.floor(len / 8);  // first half of FFT carries usable signal
    for (let i = 0; i < 4; i++) {
        const start = i * bandSize;
        const end = Math.min(start + bandSize, len);
        let sum = 0;
        for (let j = start; j < end; j++) sum += frequencyData[j];
        const amp = sum / Math.max(1, end - start);                  // 0..255
        const scale = Math.min(1, amp / 200);                        // saturate at 200/255
        const [r, g, b] = palette[i] || [0, 0, 0];
        out.push([
            Math.round(r * scale),
            Math.round(g * scale),
            Math.round(b * scale),
        ]);
    }
    return out;
}

function average(arr) {
    let s = 0;
    for (const v of arr) s += v;
    return s / arr.length;
}

function stddev(arr, mean) {
    let s = 0;
    for (const v of arr) s += (v - mean) ** 2;
    return Math.sqrt(s / arr.length);
}


// ─── Live capture wrapper (separate from the engine for testability) ───

/**
 * Start a live audio-reactive session.  Prompts the user via Chrome's
 * screen-capture dialog (they MUST tick "Share audio" — silent video
 * captures are useless for FFT).
 *
 * @returns {Promise<{stop: () => void, stream: MediaStream}>}
 */
export async function startScreenCapture(engine) {
    if (!navigator.mediaDevices?.getDisplayMedia) {
        throw new Error("getDisplayMedia not available — use Chrome / Edge.");
    }

    const stream = await navigator.mediaDevices.getDisplayMedia({
        video: true,    // required by the API even if we discard it
        audio: true,
    });

    const audioTracks = stream.getAudioTracks();
    if (audioTracks.length === 0) {
        stream.getTracks().forEach((t) => t.stop());
        throw new Error("No audio track captured.  Make sure 'Share audio' is checked in the Chrome dialog.");
    }

    const audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    const source   = audioCtx.createMediaStreamSource(stream);
    const analyser = audioCtx.createAnalyser();
    analyser.fftSize = 256;
    analyser.smoothingTimeConstant = 0.5;
    source.connect(analyser);

    const data = new Uint8Array(analyser.frequencyBinCount);
    let rafHandle = 0;
    let stopFlag = false;

    const loop = () => {
        if (stopFlag) return;
        analyser.getByteFrequencyData(data);
        engine.tick(data);
        rafHandle = requestAnimationFrame(loop);
    };
    rafHandle = requestAnimationFrame(loop);

    return {
        stream,
        stop: () => {
            stopFlag = true;
            cancelAnimationFrame(rafHandle);
            stream.getTracks().forEach((t) => t.stop());
            audioCtx.close().catch(() => {});
        },
    };
}
