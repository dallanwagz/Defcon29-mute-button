// ==UserScript==
// @name         DC29 badge — Teams bridge
// @namespace    dallanwagz.dc29
// @version      0.1
// @description  Posts Teams meeting + mute state to the DC29 web config UI via BroadcastChannel.
// @match        https://teams.microsoft.com/*
// @match        https://teams.live.com/*
// @run-at       document-idle
// @grant        none
// ==/UserScript==
//
// Install via Tampermonkey / Violentmonkey.  Keep
// https://dallanwagz.github.io/Defcon29-mute-button/ open in another
// tab — the BroadcastChannel listener there picks up our messages and
// drives the badge.
//
// Detection is best-effort DOM observation and may break when Teams
// updates their UI.  If it stops working, inspect a live Teams page,
// find a stable selector for the meeting / mute indicator, and update
// the constants below.

(function () {
    "use strict";

    const BC = new BroadcastChannel("dc29-bridge-events");
    let inMeeting = false;
    let muted = false;

    function post(msg) {
        try { BC.postMessage(msg); } catch (e) { console.warn("BC post failed:", e); }
    }

    function detect() {
        // Heuristics — pick the most stable selectors we can find.
        const muteBtn = document.querySelector(
            '[data-tid="toggle-mute"], button[aria-label*="ute" i], button[title*="ute" i]'
        );
        const callTray = document.querySelector(
            '[data-tid="call-status"], [data-tid="callingScreen"], [class*="call-controls"]'
        );

        const nowInMeeting = !!callTray;
        if (nowInMeeting !== inMeeting) {
            inMeeting = nowInMeeting;
            post({ type: "teams.meetingChanged", inMeeting });
        }

        if (muteBtn) {
            const al = (muteBtn.getAttribute("aria-label") || muteBtn.title || "").toLowerCase();
            // "Mute (Cmd+Shift+M)" → not muted (button offers to mute);
            // "Unmute (Cmd+Shift+M)" → muted.
            const nowMuted = al.startsWith("unmute");
            if (nowMuted !== muted) {
                muted = nowMuted;
                post({ type: "teams.muteChanged", muted });
            }
        }
    }

    // Fire on every DOM change, throttled to ~5 Hz.
    let pending = false;
    new MutationObserver(() => {
        if (pending) return;
        pending = true;
        setTimeout(() => { pending = false; detect(); }, 200);
    }).observe(document.body, { childList: true, subtree: true, attributes: true,
                                attributeFilter: ["aria-label", "title", "class"] });

    // Initial sync.
    setTimeout(detect, 1000);
    console.info("[dc29] Teams bridge userscript active");
})();
