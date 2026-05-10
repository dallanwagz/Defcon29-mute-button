// ==UserScript==
// @name         DC29 badge — Outlook bridge
// @namespace    dallanwagz.dc29
// @version      0.1
// @description  Posts Outlook unread-mail count to the DC29 web config UI via BroadcastChannel.
// @match        https://outlook.office.com/*
// @match        https://outlook.live.com/*
// @run-at       document-idle
// @grant        none
// ==/UserScript==

(function () {
    "use strict";

    const BC = new BroadcastChannel("dc29-bridge-events");
    let lastCount = -1;

    function post(msg) {
        try { BC.postMessage(msg); } catch (e) { console.warn("BC post failed:", e); }
    }

    function readUnreadCount() {
        // Look for the Inbox folder link's badge.  Outlook shows it as
        // a small chip next to the folder name; the aria-label reads
        // like "Inbox 5 unread items".  Best-effort selector chain.
        const candidates = [
            'button[aria-label*="Inbox"][aria-label*="unread"]',
            'div[role="treeitem"][aria-label*="Inbox"][aria-label*="unread"]',
            'a[aria-label*="Inbox"][aria-label*="unread"]',
        ];
        for (const sel of candidates) {
            const el = document.querySelector(sel);
            if (!el) continue;
            const m = (el.getAttribute("aria-label") || "").match(/(\d+)\s+unread/i);
            if (m) return parseInt(m[1], 10);
        }
        // No "X unread" → 0.
        return 0;
    }

    function detect() {
        const c = readUnreadCount();
        if (c !== lastCount) {
            lastCount = c;
            post({ type: "outlook.unreadChanged", count: c });
        }
    }

    let pending = false;
    new MutationObserver(() => {
        if (pending) return;
        pending = true;
        setTimeout(() => { pending = false; detect(); }, 500);
    }).observe(document.body, { childList: true, subtree: true, attributes: true,
                                attributeFilter: ["aria-label"] });

    setTimeout(detect, 2000);
    console.info("[dc29] Outlook bridge userscript active");
})();
