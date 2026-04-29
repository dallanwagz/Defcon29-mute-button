# DC29 Badge — User Guide

![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![Platform](https://img.shields.io/badge/platform-macOS%20%7C%20Windows-lightgrey)
![Status](https://img.shields.io/badge/status-stable-green)

> **Note:** This directory is regenerated from `docs/spine/` by the `/regen-docs` Claude Code skill. Do not hand-edit files here — edit `docs/spine/` instead and re-run the skill.

Welcome! This guide is for DEF CON 29 badge holders who want to use the badge as a **Microsoft Teams mute indicator** and **USB macro keypad**.

No firmware knowledge required. If you can run `pip install`, you're good.

---

## What Does This Do?

Your DC29 badge plugs into your computer and does two things at once:

1. **USB Keyboard** — the 4 buttons send configurable keystrokes (volume controls, mute shortcuts, whatever you want)
2. **Teams mute indicator** — the bottom-right LED (LED 4) shows your Teams meeting state in real time:
   - Red = muted
   - Green = unmuted
   - Off = not in a meeting

The state comes directly from Teams' API, so it's always accurate — doesn't matter if you muted from the badge button, the Teams UI, a keyboard shortcut, or push-to-talk. The LED follows the actual state.

---

## Quick Start

```bash
pip install dc29-badge
dc29 teams --port /dev/tty.usbmodem14201
```

That's the short version. For full setup, read on.

---

## Pages in This Guide

| Page | What's in it |
|------|-------------|
| [setup.md](setup.md) | Install, connect, run Teams bridge |
| [tui-guide.md](tui-guide.md) | How to use the TUI dashboard |
| [customizing.md](customizing.md) | Change button keymaps and LED colors |
| [faq.md](faq.md) | Troubleshooting common issues |

---

## Feedback and Issues

Found a problem? Something unclear? Open an issue on the repository.

Hackers and developers: see [docs/developer/README.md](../developer/README.md) for the technical details.
