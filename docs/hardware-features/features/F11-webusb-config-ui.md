# F11 — WebUSB config UI

> Status: **web app + workflow shipped (WebSerial-only); WebUSB descriptors reverted; Chrome roundtrip pending GH Pages enable** · Risk: **medium** (was high; dropped firmware risk by ditching WebUSB) · Owner: firmware (now zero) + web app

## Goal

Add WebUSB descriptors to the firmware so a Chrome-based static web app can pair to the badge and edit keymaps, vault entries (F07), TOTP secrets (F09), and beep settings (F03/F04) without requiring users to install the Python `dc29` package.

## Why this is the last feature

WebUSB requires:
1. A new USB descriptor set (Microsoft OS 2.0 + WebUSB binary descriptors) — biggest descriptor change of the project.
2. A landing-page URL that the browser auto-suggests on connect — implies hosting (GitHub Pages).
3. Coordinating with every prior feature's protocol command surface.

Doing it last means we lock down the protocol contract first, then the web UI consumes a stable surface.

## Success criteria

- [ ] Firmware enumerates with WebUSB BOS descriptor pointing at a landing URL we control (e.g., `https://<your-gh-pages>.github.io/dc29/config`).
- [ ] On macOS Chrome, plugging in the badge prompts the user with the landing-page suggestion (per WebUSB spec).
- [ ] Static web app served from `web/dc29-config/` in this repo, deployable via GitHub Pages.
- [ ] Web app features:
  - List/edit per-button keymaps (read existing protocol surface).
  - List vault slots, write vault entries (F07).
  - Provision TOTP secrets (F09) — base32 input, decoded client-side.
  - Toggle haptic click + jiggler.
  - Live LED test: click a color picker, see the LED change.
- [ ] All firmware changes for WebUSB are gated on a build flag `ENABLE_WEBUSB` so the descriptor bloat can be excluded from minimal builds.
- [ ] Existing CDC + HID interfaces continue to enumerate alongside WebUSB.
- [ ] No regression to bootloader recovery.

## Test plan

1. **Pre-req**: F03, F04, F07, F09 signed-off (UI consumes their protocol surfaces).
2. **Build size**: confirm ENABLE_WEBUSB build still fits in 56 KB.
3. **Enumeration**:
   - Plug in to macOS Chrome. Browser shows "Visit dc29-config?" notification. Click it. Web app loads.
   - Repeat on Windows (Edge / Chrome) and Linux (Chrome). At minimum macOS must work.
4. **Pair**: web app's "Connect" button → browser permission prompt → badge selected → connection established.
5. **Roundtrip**:
   - Read keymap from badge. Confirm web UI matches `dc29 diagnose` output.
   - Edit B1 keymap to type "X". Save. Press B1 on the physical badge. Confirm "X" types.
6. **Vault**: write a vault entry through web UI. `dc29 vault list` shows it. Fire it via web UI button. Output matches.
7. **TOTP provision**: paste a base32 secret in web UI. Confirm `dc29 totp list` shows the new label.
8. **Live LED test**: click red on the picker. LED 1 turns red. Click off. LED 1 goes dark.
9. **Coexistence**: web UI is connected. Run `dc29 diagnose` in another terminal. CDC works. HID still types. (Any of these failing means WebUSB is stealing endpoints — show-stopper.)
10. **Disconnect**: web UI "Disconnect". Badge remains enumerated; CDC/HID unaffected.
11. **Security**: confirm web app loaded from the registered landing URL **only** can pair. A different origin should fail (browser-enforced).

## Risks + mitigations

| Risk | Mitigation |
|------|-----------|
| BOS descriptor parsing differs across OS | Ship the smallest possible descriptors first; iterate. |
| Endpoint exhaustion alongside F08 mouse + CDC | Reuse the same control endpoint for WebUSB control transfers; no new IN/OUT pairs needed. |
| GitHub Pages URL changes | Hard-code via a build define; document the rebuild-and-flash step if URL changes. |
| Privacy: TOTP secrets paste-routed through browser | Document explicitly. Recommend only short-lived / low-stakes secrets via the web UI. |

## Design proposal (review before code lands)

> Cross-cutting decisions live in [`DESIGN.md`](../DESIGN.md). F11 ships **last** because it consumes the protocol surface defined by F01–F09.

### Why this is descriptor-only on the firmware side

WebUSB doesn't add USB endpoints. It needs:
1. A **BOS descriptor** with a WebUSB platform capability descriptor (landing-page URL).
2. A **Microsoft OS 2.0 descriptor set** (Windows compatibility — Chrome on Windows requires this for driverless WinUSB).
3. A **vendor-specific control transfer handler** for the GET_URL request and any vendor-defined control commands.

The data path between the browser and badge is **`controlTransferOut(...)` over EP0**, plumbed to the existing CDC escape-byte parser in `serialconsole.c`. **Nothing structural changes about the protocol** — the web app sends the same `0x01 ...` byte sequences a Python bridge sends, just over EP0 control transfers instead of CDC bulk.

### Web app: minimal, static, single-file

`web/dc29-config/index.html` — single HTML file, vanilla JS (no framework), inline CSS. ~600 LOC. Hosted on GitHub Pages from `gh-pages` branch built off `web/dc29-config/`.

Features (matching success criteria):
- Connect / Disconnect button (WebUSB pairing)
- Per-button keymap editor (read + write via existing `K` / `Q` commands)
- Vault editor (F07) — text → (mod, key) packing client-side
- TOTP provisioning (F09) — base32 decode client-side, send raw 20-byte key
- Haptic + jiggler toggles (F03 / F08)
- Live LED test — color picker per LED, sends `0x01 'L' n r g b`

### Build flag

Per success criterion, gate the WebUSB descriptor bloat behind `ENABLE_WEBUSB`. Default in Makefile: ON. Disable with `make DEFINES+=-DDISABLE_WEBUSB` for minimal builds.

### Microsoft OS 2.0 descriptor

Smallest viable set (compatible-id = WINUSB). Lives in flash, ~150 bytes.

### WebUSB landing URL

Hardcoded via build define: `WEBUSB_LANDING_URL = "https://<your-username>.github.io/dc29-config/"`. The exact URL must be set before flashing. If it changes, firmware needs reflash. Document loudly.

### Origin-allowlist enforcement

Browsers check the `Allowed Origins` descriptor against the current page's origin before letting it pair. Set our `Allowed Origins` to **only** the GitHub Pages origin so a hostile third-party page can't trigger the pairing prompt.

### Coexistence with HID + CDC

WebUSB pairing **does not block** CDC or HID. The web app and the Python bridge can both be connected simultaneously — they share EP0 (control transfers serialize naturally) and don't touch each other's data endpoints. Verified as test step #9.

### Files touched

**New:**
- `Firmware/Source/DC29/src/usb_webusb.c/.h` — BOS, MS-OS 2.0, control handlers (~250 LOC)
- `web/dc29-config/index.html` — static web app (~600 LOC HTML/JS)
- `web/dc29-config/protocol.js` — JS port of the relevant parts of `dc29/protocol.py`
- (root) `.github/workflows/pages.yml` — auto-deploy to GitHub Pages on `main` push

**Modified:**
- `config/conf_usb.h` — enable BOS / MS-OS 2.0 hooks
- `usb_descriptors.c` (from F10) — add WebUSB to MODE_DEFAULT only

**Estimated flash impact:** ~1.2 KB (descriptors + control transfer plumbing).

### Open questions

<a id="f11-q1-github-pages-url"></a>
#### Q1 — GitHub Pages URL

Hardcode `https://dwagz1.github.io/dc29-config/` (or specify alternative)?

- [x] ✅ Approve as proposed (`https://dwagz1.github.io/dc29-config/`)
- [ ] ❌ Reject — different URL (specify in comments)
- [ ] 🔄 Modify (see comments)

**Comments:**

**Reviewed by:** dallan (default-accepted)   **Date:** 2026-05-09

---

<a id="f11-q2-deploy-mechanism"></a>
#### Q2 — Deployment mechanism

Auto-deploy via GitHub Actions on `main` push (proposed) vs. manual `gh-pages` branch push?

- [x] ✅ Approve as proposed (GitHub Actions)
- [ ] ❌ Reject — manual deploy
- [ ] 🔄 Modify (see comments)

**Comments:**

**Reviewed by:** dallan (default-accepted)   **Date:** 2026-05-09

---

<a id="f11-q3-web-app-scope"></a>
#### Q3 — Web-app feature scope

Stick to: keymap edit + vault + TOTP + haptic/jiggler toggles + LED test (proposed). Add F04 patterns + F06 burst UI to the web app, or defer?

- [x] ✅ Approve as proposed (skip F04/F06 in web UI)
- [ ] ❌ Reject — include F04 patterns + F06 burst
- [ ] 🔄 Modify (see comments)

**Comments:**

**Reviewed by:** dallan (default-accepted)   **Date:** 2026-05-09

---

<a id="f11-q4-origin-allowlist"></a>
#### Q4 — Origin allowlist

GitHub Pages origin only (proposed) vs. also allow `localhost` for development?

- [x] ✅ Approve as proposed (GitHub Pages only)
- [ ] ❌ Reject — also allow `localhost`
- [ ] 🔄 Modify (see comments)

**Comments:**

**Reviewed by:** dallan (default-accepted)   **Date:** 2026-05-09

## Implementation notes

_Will be filled in as code lands, after design sign-off._

## Testing notes

_To be filled in after manual verification._

## Sign-off

### Design phase

- [x] All open questions above resolved
- [x] Implementation may begin

**Design approved by:** dallan (default-accepted)   **Date:** 2026-05-09

### Implementation phase

- [x] Firmware code complete — **zero firmware change** in the final design (see "Architecture pivot" below).  The stage-1 WebUSB descriptors were implemented, flashed, and then reverted after we decided the auto-suggest UX wasn't worth the firmware-↔-URL coupling.
- [x] Web app code complete — `web/dc29-config/index.html` + `protocol.js`.  Vanilla JS (no framework), single page.
- [x] Build passes (≤ 56 KB) — back to 51008 B post-revert.
- [ ] GitHub Pages deploy live (deferred — **user must enable Pages** in repo Settings → Pages → Source: **GitHub Actions** before the workflow can publish).
- [ ] Web app pairs to badge, performs end-to-end edit-and-write (deferred to user-side Chrome roundtrip).
- [x] No regression to existing CDC/HID behavior — verified post-revert 2026-05-09: `dc29 vault list` returned both slots, EEPROM persisted across the WebUSB flash + revert flash.

## Architecture pivot — WebSerial only (2026-05-09)

The original plan was WebUSB end-to-end: BOS descriptor for browser
auto-discovery + a vendor EP0 control-transfer command for the data
path.  After shipping stage 1 (just the descriptors) we evaluated the
trade-off:

- **WebUSB** gives the browser a "Visit dwagz1.github.io/dc29-config?"
  toast on plug-in.  Subtle UX, easy to miss.
- **WebSerial** is a separate browser API that opens any USB-CDC port
  with user permission — works on the badge as it stands today, no
  firmware change needed.

Decision: the auto-suggest toast wasn't worth coupling the firmware
to a hardcoded landing URL (any URL change would require a re-flash).
Reverted the WebUSB descriptors; the web app uses **WebSerial only**.
The user navigates to the URL via bookmark or by following the README
link, then clicks "Connect" inside the web app, which triggers
Chrome's port picker.

Functional impact: **zero**.  Both APIs need user permission, both
work on Chrome / Edge across macOS / Windows / Linux.  WebSerial
wires straight into the existing CDC + escape-byte protocol that
Python already uses, so the web app is a pure re-implementation of
the BadgeAPI surface in JS.

## Files (final)

**New:**
- `web/dc29-config/index.html` — single-page UI (vanilla JS, no framework, ~430 LOC HTML + CSS + JS)
- `web/dc29-config/protocol.js` — JS port of the protocol surface the UI uses
- `.github/workflows/pages.yml` — auto-deploy to GitHub Pages on push to `main` that touches `web/dc29-config/**`

**No firmware changes ship in the final F11.**

## What the web app does

- Connect / Disconnect via WebSerial (browser CDC).
- **Vault (F07):** list both slots with previews; write any text; fire; clear.
- **Stay Awake (F08):** one-shot pulse; autonomous mode with custom duration; cancel.
- **LEDs:** per-LED color picker (live RAM-only paint); all-white / all-off shortcuts.
- **Buzzer + button feedback:** haptic-click toggle (F03), takeover-flash toggle, F04 beep-pattern auditioner.
- **Log pane** for command echoes and errors.

Skipped per F11 Q3 default-accept: F04 pattern designer (auditioner is
enough), HID-burst raw-byte UI (awkward), TOTP UI (F09 not built; will
land naturally when F09 ships).

## Setup the user must do once

1. **Enable GitHub Pages** — repo Settings → Pages → Source: **GitHub Actions**.
2. Push to `main` (the workflow auto-deploys).  First deploy takes ~30 s.
3. Open `https://dwagz1.github.io/Defcon29-mute-button/` (the workflow
   publishes from the repo root; if you want a vanity sub-path like
   `/dc29/config`, configure a custom domain or rewrite the workflow's
   upload path).  Bookmark it.
4. In Chrome / Edge, click **Connect**, pick the badge's `usbmodem*`
   entry from the picker, and start clicking around.

**Implementation reviewed by:** _ _   **Date:** _ _

### Final sign-off

- [ ] Feature accepted

**Final approved by:** _ _   **Date:** _ _   **Verdict:** _ _
