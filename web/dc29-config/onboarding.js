// onboarding.js — first-launch tour for the DC29 config UI.
//
// On first visit (no localStorage flag), shows a modal overlay walking
// the user through the main panels.  "Skip" / "Show again later" /
// "Don't show me this again" all close it; the last one persists the
// suppression flag.
//
// Tour steps reference panels by CSS selector — they highlight by
// scrolling the target into view + adding a glow class for ~the duration
// of the step.

const STORAGE_KEY = "dc29.onboardingShown";

const STEPS = [
    {
        target: "#btn-connect",
        title: "Welcome 👋",
        body:
            "This is the DC29 badge config UI.  All controls talk to the badge via " +
            "WebSerial — works in Chrome / Edge on macOS, Windows, and Linux.\n\n" +
            "Click <b>Connect</b> first — Chrome will show a port picker.  Choose " +
            "the badge's <code>usbmodem*</code> entry.",
    },
    {
        target: "#event-log",
        title: "Recent activity",
        body:
            "Once connected, every button press on the badge appears here in real " +
            "time — including F01/F02 modifier kinds (double / triple / long / chord) " +
            "if you've configured them.",
    },
    {
        target: "#led-grid",
        title: "LEDs",
        body:
            "Click any swatch to set that LED immediately.  The change is RAM-only — " +
            "power-cycling reverts to the EEPROM defaults.",
    },
    {
        target: "#vault-slots",
        title: "Vault (F07)",
        body:
            "Two slots × up to 16 keystrokes.  Type a string, click <b>Write</b>, " +
            "then <b>Fire</b> with a focused text editor — the badge types it.\n\n" +
            "<i>Plaintext EEPROM</i> — never use for real credentials.",
    },
    {
        target: "#mod-actions-grid",
        title: "F01/F02 modifier actions",
        body:
            "Assign double-tap, triple-tap, long-press, or chord shortcuts per " +
            "button.  Modifier mappings are RAM-only and need to be re-applied " +
            "after every power cycle.",
    },
    {
        target: "#share-incoming",
        title: "Sharing configs",
        body:
            "Use <b>Generate share link</b> to encode your LED swatches + WLED " +
            "knobs into a URL hash.  Send the link to a friend; their browser " +
            "will offer to apply your config.\n\n" +
            "<i>Vault contents are never included</i> — they're per-user and stay " +
            "on your badge.",
    },
];

function injectStyles() {
    if (document.getElementById("onboarding-style")) return;
    const style = document.createElement("style");
    style.id = "onboarding-style";
    style.textContent = `
        .onboard-backdrop {
            position: fixed; inset: 0;
            background: rgba(0, 0, 0, 0.55);
            z-index: 9998;
            display: flex; align-items: center; justify-content: center;
        }
        .onboard-card {
            background: #1d222c; color: #d6dde7;
            border: 1px solid #4aa6ff; border-radius: 10px;
            padding: 24px 28px; max-width: 460px;
            box-shadow: 0 12px 48px rgba(0, 0, 0, 0.7);
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
            font-size: 14px; line-height: 1.5;
            position: relative; z-index: 9999;
        }
        .onboard-card h3 { margin: 0 0 12px; color: #4aa6ff; font-size: 18px; }
        .onboard-card p { margin: 0 0 18px; white-space: pre-wrap; }
        .onboard-card .progress { color: #8a96a8; font-size: 12px; margin-bottom: 10px; }
        .onboard-card .actions { display: flex; gap: 8px; justify-content: flex-end; }
        .onboard-card button {
            background: #1d222c; color: #d6dde7;
            border: 1px solid #2a3140; border-radius: 6px;
            padding: 6px 14px; font-size: 13px; cursor: pointer;
            font-family: inherit;
        }
        .onboard-card button.primary {
            background: #4aa6ff; color: #07101a; border-color: #4aa6ff; font-weight: 600;
        }
        .onboard-card button.muted { color: #8a96a8; }
        .onboard-glow {
            outline: 3px solid #4aa6ff !important;
            outline-offset: 4px;
            border-radius: 8px;
            transition: outline 0.2s ease-in-out;
        }
    `;
    document.head.appendChild(style);
}

function highlight(selector) {
    document.querySelectorAll(".onboard-glow").forEach((el) => el.classList.remove("onboard-glow"));
    const el = document.querySelector(selector);
    if (el) {
        el.classList.add("onboard-glow");
        el.scrollIntoView({ behavior: "smooth", block: "center" });
    }
}

function clearHighlight() {
    document.querySelectorAll(".onboard-glow").forEach((el) => el.classList.remove("onboard-glow"));
}

function shouldShow() {
    try {
        return localStorage.getItem(STORAGE_KEY) !== "1";
    } catch {
        return true;
    }
}

function markShown() {
    try { localStorage.setItem(STORAGE_KEY, "1"); } catch {}
}

export function resetOnboarding() {
    try { localStorage.removeItem(STORAGE_KEY); } catch {}
}

export function startTour({ force = false } = {}) {
    if (!force && !shouldShow()) return;
    injectStyles();

    let stepIdx = 0;

    const backdrop = document.createElement("div");
    backdrop.className = "onboard-backdrop";
    backdrop.id = "onboard-backdrop";

    const card = document.createElement("div");
    card.className = "onboard-card";
    card.id = "onboard-card";
    backdrop.appendChild(card);

    document.body.appendChild(backdrop);

    function close({ persist = true } = {}) {
        if (persist) markShown();
        clearHighlight();
        backdrop.remove();
    }

    function render() {
        const step = STEPS[stepIdx];
        const isLast = stepIdx === STEPS.length - 1;
        card.innerHTML = `
            <div class="progress">Step ${stepIdx + 1} of ${STEPS.length}</div>
            <h3>${step.title}</h3>
            <p>${step.body}</p>
            <div class="actions">
                <button class="muted" data-action="skip">Skip tour</button>
                ${stepIdx > 0 ? `<button data-action="back">Back</button>` : ""}
                <button class="primary" data-action="next">${isLast ? "Done" : "Next"}</button>
            </div>
        `;
        card.querySelectorAll("button").forEach((b) => {
            b.addEventListener("click", () => {
                const action = b.dataset.action;
                if (action === "skip") return close();
                if (action === "back") { stepIdx--; render(); highlight(STEPS[stepIdx].target); return; }
                if (action === "next") {
                    if (isLast) return close();
                    stepIdx++;
                    render();
                    highlight(STEPS[stepIdx].target);
                }
            });
        });
    }

    render();
    highlight(STEPS[stepIdx].target);
}
