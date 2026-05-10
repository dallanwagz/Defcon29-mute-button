// bridges.js — in-browser equivalent of the Python Slack/Teams/Outlook
// bridges, for users who want badge integrations without installing the
// dc29 Python package.
//
// Two surfaces:
//
//   1. Manual action buttons in the UI — each fires the same HID
//      keyboard shortcut the Python bridge would (mute toggle, leave
//      call, mark all read, delete email, etc.).  Caller is responsible
//      for focusing the target app first; a 2-second countdown gives
//      time to switch.
//
//   2. BroadcastChannel listener on `dc29-bridge-events` — accepts JSON
//      messages from anywhere in the same browser (other tabs,
//      Tampermonkey userscripts, dev tools console) and translates
//      them to badge actions.  Lets the user automate state changes
//      from inside teams.microsoft.com / slack.com / outlook.office.com
//      without an extension or Python.
//
// Sample userscripts shipped under web/dc29-config/userscripts/.

const BROADCAST_CHANNEL = "dc29-bridge-events";

// Shortcut tables — macOS variants (matching dc29.bridges.{teams,slack,outlook}._SHORTCUTS_MAC).
// Each entry: { label, mods: Set<'ctrl'|'shift'|'alt'|'cmd'>, key: HID Usage ID }.
//
// HID Usage IDs are the same the rest of the app uses (asciiToHidPair etc.).
// Modifier mask bits: ctrl=0x01, shift=0x02, alt=0x04, cmd/gui=0x08.

const HID_M = {
    a: 0x04, b: 0x05, c: 0x06, d: 0x07, e: 0x08, f: 0x09, g: 0x0a, h: 0x0b,
    i: 0x0c, j: 0x0d, k: 0x0e, l: 0x0f, m: 0x10, n: 0x11, o: 0x12, p: 0x13,
    q: 0x14, r: 0x15, s: 0x16, t: 0x17, u: 0x18, v: 0x19, w: 0x1a, x: 0x1b,
    y: 0x1c, z: 0x1d,
    "1": 0x1e, "2": 0x1f, "3": 0x20, "4": 0x21, "5": 0x22, "6": 0x23, "7": 0x24, "8": 0x25, "9": 0x26, "0": 0x27,
    enter: 0x28, esc: 0x29, backspace: 0x2a, tab: 0x2b, space: 0x2c,
    delete: 0x4c, right: 0x4f, left: 0x50, down: 0x51, up: 0x52,
    "?": 0x38,
};

const MOD = { ctrl: 0x01, shift: 0x02, alt: 0x04, cmd: 0x08 };

function modMask(modList) {
    let m = 0;
    for (const name of modList) m |= (MOD[name] || 0);
    return m;
}

export const BRIDGE_ACTIONS = {
    teams: {
        "mute":         { label: "Toggle mute",       mods: ["cmd", "shift"], key: "m" },
        "video":        { label: "Toggle video",      mods: ["cmd", "shift"], key: "o" },
        "hand":         { label: "Raise/lower hand",  mods: ["cmd", "shift"], key: "k" },
        "leave":        { label: "Leave call",        mods: ["cmd", "shift"], key: "h" },
        "background":   { label: "Background blur",   mods: ["cmd", "shift"], key: "p" },
    },
    slack: {
        "all-unreads":  { label: "All unreads",       mods: ["cmd", "shift"], key: "a" },
        "mentions":     { label: "Mentions",          mods: ["cmd", "shift"], key: "m" },
        "quick-switch": { label: "Quick switcher",    mods: ["cmd"],          key: "k" },
        "threads":      { label: "Threads",           mods: ["cmd", "shift"], key: "t" },
        "huddle":       { label: "Toggle huddle",     mods: ["cmd", "shift"], key: "h" },
        "huddle-mute":  { label: "Toggle mute (huddle)", mods: ["cmd", "shift"], key: "space" },
    },
    outlook: {
        "delete":       { label: "Delete email",      mods: ["cmd"],          key: "backspace" },
        "reply":        { label: "Reply",             mods: ["cmd"],          key: "r" },
        "reply-all":    { label: "Reply all",         mods: ["cmd", "shift"], key: "r" },
        "forward":      { label: "Forward",           mods: ["cmd"],          key: "j" },
    },
};

/** Convert a shortcut entry to a single (mod, hidKey) pair. */
export function actionToHidPair(action) {
    const k = action.key;
    const code = HID_M[k];
    if (code === undefined) throw new Error(`unknown HID key '${k}'`);
    return [modMask(action.mods), code];
}


// ─── BridgeListener — BroadcastChannel handler ─────────────────────────

const TEAMS_LED4_RED   = [220, 0, 0];
const TEAMS_LED4_GREEN = [0, 200, 0];
const TEAMS_LED4_OFF   = [0, 0, 0];
const SLACK_LED2_HUDDLE = [0, 200, 200];
const SLACK_LED2_OFF    = [0, 0, 0];

/**
 * Listens on a BroadcastChannel and translates incoming bridge events
 * to badge commands.  Holds onto the badge instance so it can call
 * setLed / hidBurst / etc.
 *
 * Message schema (all fields except `type` optional):
 *
 *   { type: "teams.muteChanged",     muted: bool }
 *   { type: "teams.meetingChanged",  inMeeting: bool }
 *   { type: "slack.huddleChanged",   inHuddle: bool }
 *   { type: "slack.huddleMuteChanged", muted: bool }
 *   { type: "outlook.unreadChanged", count: int }
 *
 *   { type: "action",  app: "teams"|"slack"|"outlook", name: "..." }
 *     // fires the corresponding shortcut from BRIDGE_ACTIONS via hidBurst.
 *
 * Designed to be safe when called from any browser context — if a
 * message looks malformed, log it and continue.
 */
export class BridgeListener {
    constructor(badge, opts = {}) {
        this.badge = badge;
        this.onMessage = opts.onMessage || (() => {});  // optional UI callback for log/badging
        this.channel = null;
        this.messageCount = 0;
        // Tracked state — useful for both LED management and the UI.
        this.state = {
            teamsInMeeting: false,
            teamsMuted:     false,
            slackInHuddle:  false,
            slackMuted:     false,
            outlookUnread:  0,
        };
    }

    start() {
        if (!("BroadcastChannel" in window)) {
            throw new Error("BroadcastChannel not supported in this browser.");
        }
        if (this.channel) return;
        this.channel = new BroadcastChannel(BROADCAST_CHANNEL);
        this.channel.addEventListener("message", (ev) => this._handle(ev.data));
    }

    stop() {
        if (this.channel) {
            this.channel.close();
            this.channel = null;
        }
    }

    /** Manually inject a message — used by tests + UI buttons. */
    inject(msg) { this._handle(msg); }

    async _handle(msg) {
        this.messageCount++;
        try {
            await this._dispatch(msg);
        } catch (err) {
            console.warn("BridgeListener dispatch error:", err, msg);
        }
        try { this.onMessage(msg); } catch {}
    }

    async _dispatch(msg) {
        if (!msg || typeof msg !== "object" || !msg.type) return;

        // Generic action firer.
        if (msg.type === "action" && msg.app && msg.name) {
            await this.fireAction(msg.app, msg.name);
            return;
        }

        // State-tracking translators.
        switch (msg.type) {
            case "teams.muteChanged":
                this.state.teamsMuted = !!msg.muted;
                if (this.state.teamsInMeeting) {
                    await this.badge.setLed(4, ...(this.state.teamsMuted ? TEAMS_LED4_RED : TEAMS_LED4_GREEN));
                }
                return;
            case "teams.meetingChanged":
                this.state.teamsInMeeting = !!msg.inMeeting;
                if (!this.state.teamsInMeeting) {
                    await this.badge.setLed(4, ...TEAMS_LED4_OFF);
                } else {
                    await this.badge.setLed(4, ...(this.state.teamsMuted ? TEAMS_LED4_RED : TEAMS_LED4_GREEN));
                }
                return;
            case "slack.huddleChanged":
                this.state.slackInHuddle = !!msg.inHuddle;
                await this.badge.setLed(2, ...(this.state.slackInHuddle ? SLACK_LED2_HUDDLE : SLACK_LED2_OFF));
                return;
            case "slack.huddleMuteChanged":
                this.state.slackMuted = !!msg.muted;
                if (this.state.slackInHuddle) {
                    await this.badge.setLed(2, ...(this.state.slackMuted ? TEAMS_LED4_RED : SLACK_LED2_HUDDLE));
                }
                return;
            case "outlook.unreadChanged":
                this.state.outlookUnread = msg.count | 0;
                // Brightness on LED 1 indicates unread depth.  0 = off, capped at 25 → full bright.
                const brightness = Math.min(255, this.state.outlookUnread * 10);
                await this.badge.setLed(1, brightness, brightness, 0);
                return;
        }
    }

    /** Fire one of the shortcuts in BRIDGE_ACTIONS via the badge's HID burst. */
    async fireAction(app, name) {
        const action = (BRIDGE_ACTIONS[app] || {})[name];
        if (!action) throw new Error(`unknown action: ${app}.${name}`);
        const pair = actionToHidPair(action);
        await this.badge.hidBurst([pair]);
    }
}
