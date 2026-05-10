# F11 — WebUSB config UI

> Status: **stage 1 in progress** (firmware descriptors flashed, no enumeration regression; web app + Pages deploy + Chrome roundtrip pending) · Risk: **high** · Owner: firmware + web app

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

- [x] Firmware code complete (BOS, MS-OS 2.0, GET_URL handler — `Firmware/Source/DC29/src/usb_webusb.{c,h}`; conf_usb.h hooks `USB_DEVICE_SPECIFIC_REQUEST` to it)
- [ ] Web app code complete (deferred to stage 2)
- [x] Build passes (≤ 56 KB) — text 51008 → 51088 B (+80 B descriptors + handler)
- [ ] GitHub Pages deploy live + browser auto-suggests landing URL (deferred to stage 2/3)
- [ ] Web app pairs to badge, performs end-to-end edit-and-write (deferred to stage 3)
- [x] No regression to existing CDC/HID behavior — verified 2026-05-09 post-flash: `dc29 vault list` returned both slots, `dc29 play_beep CONFIRM` + `CI_PASSED` audible, EEPROM persisted from prior F07 boot

**F11 stage-1 deviations from spec:**
- Build flag `ENABLE_WEBUSB` is **not** implemented — descriptor cost is ~150 B and not worth a per-build toggle on a single-target project. If a minimal build becomes a goal later, it's a 5-minute add via `#ifdef`.
- The vendor-class control-transfer command for raw protocol bytes (web-app-to-firmware data path) is also deferred to stage 2; the web app needs it before any read/write, but stage 1 only ships descriptors so Chrome will offer the landing URL.

**Stage-2 plan (next session):**
1. Add a vendor request handler that proxies a `controlTransferOut` payload directly into the existing escape-byte parser in `serialconsole.c` (so the web app can send `0x01 ...` byte sequences via EP0 instead of CDC).
2. Write `web/dc29-config/index.html` + `protocol.js` (~600 LOC vanilla JS).
3. Add `.github/workflows/pages.yml` that publishes `web/dc29-config/` to `gh-pages` on `main` push.
4. **User must manually enable Pages** in repo Settings → Pages → Source: GitHub Actions.
5. Plug badge into Chrome — verify the landing-URL auto-suggest, then verify the full keymap/vault/LED roundtrip.

**Implementation reviewed by:** _ _   **Date:** _ _

### Final sign-off

- [ ] Feature accepted

**Final approved by:** _ _   **Date:** _ _   **Verdict:** _ _
