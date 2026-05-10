// ==UserScript==
// @name         DC29 badge — Slack bridge
// @namespace    dallanwagz.dc29
// @version      0.1
// @description  Posts Slack huddle state to the DC29 web config UI via BroadcastChannel.
// @match        https://app.slack.com/*
// @match        https://*.slack.com/*
// @run-at       document-idle
// @grant        none
// ==/UserScript==

(function () {
    "use strict";

    const BC = new BroadcastChannel("dc29-bridge-events");
    let inHuddle = false;
    let muted = false;

    function post(msg) {
        try { BC.postMessage(msg); } catch (e) { console.warn("BC post failed:", e); }
    }

    function detect() {
        // Slack's huddle UI uses [data-qa~="huddle"] selectors that change
        // periodically — pick whatever sticks.  Best effort.
        const huddleTray = document.querySelector(
            '[data-qa="huddle_active"], [data-qa~="huddle"][aria-label*="uddle"]'
        );
        const nowInHuddle = !!huddleTray;
        if (nowInHuddle !== inHuddle) {
            inHuddle = nowInHuddle;
            post({ type: "slack.huddleChanged", inHuddle });
        }

        // Mute button inside the huddle tray.
        if (huddleTray) {
            const muteBtn = huddleTray.querySelector('[data-qa="huddle_mute"]') ||
                            document.querySelector('[data-qa="huddle_mute"]');
            if (muteBtn) {
                const al = (muteBtn.getAttribute("aria-label") || muteBtn.title || "").toLowerCase();
                const nowMuted = al.includes("unmute");
                if (nowMuted !== muted) {
                    muted = nowMuted;
                    post({ type: "slack.huddleMuteChanged", muted });
                }
            }
        } else if (muted) {
            muted = false;
            post({ type: "slack.huddleMuteChanged", muted: false });
        }
    }

    let pending = false;
    new MutationObserver(() => {
        if (pending) return;
        pending = true;
        setTimeout(() => { pending = false; detect(); }, 200);
    }).observe(document.body, { childList: true, subtree: true, attributes: true,
                                attributeFilter: ["data-qa", "aria-label", "title"] });

    setTimeout(detect, 1500);
    console.info("[dc29] Slack bridge userscript active");
})();
