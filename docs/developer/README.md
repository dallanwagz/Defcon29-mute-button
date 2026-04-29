# DC29 Badge — Developer Guide

![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![License](https://img.shields.io/badge/license-MIT-lightgrey)
![Status](https://img.shields.io/badge/status-stable-green)

> **Note:** This directory is regenerated from `docs/spine/` by the `/regen-docs` Claude Code skill. Do not hand-edit files here — edit `docs/spine/` instead.

This guide is for Python developers who want to extend the badge tooling, build new integrations, or write custom bridges.

---

## Architecture Overview

```
dc29/protocol.py        Pure-Python protocol constants — no I/O, no dependencies
dc29/tui/               Textual terminal UI application
dc29/bridges/           Bridge implementations (Teams, and yours here)
dc29/cli.py             Typer CLI entry point

tools/
└── teams_mute_indicator.py   Standalone Teams bridge with BadgeWriter and LedAnimator
```

The badge communicates over USB CDC serial at 9600 baud using a binary escape-byte protocol. The Python side manages the serial port, parses events from the badge, and sends commands.

Full protocol specification: [docs/spine/01-protocol.md](../spine/01-protocol.md)

Full architecture description: [docs/spine/02-architecture.md](../spine/02-architecture.md)

---

## Thread Model

The badge reader runs in a **daemon thread** (blocking `serial.read(1)` loop). The application typically runs an **asyncio event loop** in the main thread. Communication between them uses `loop.call_soon_threadsafe(queue.put_nowait, value)`.

```
Main thread (asyncio)
├── Your application coroutines
├── LedAnimator tasks (optional)
└── Effects/state management

BadgeWriter reader thread (daemon)
└── _reader_loop() → _parse_rx() → _dispatch_rx()
    └── Fires: on_button4_press, on_effect_mode, on_chord_long
```

---

## Pages in This Guide

| Page | What's in it |
|------|-------------|
| [api-reference.md](api-reference.md) | BadgeWriter class, all methods, callback signatures |
| [building-bridges.md](building-bridges.md) | How to write a new bridge (Zoom, Slack, OBS, etc.) |
| [cli-extensions.md](cli-extensions.md) | How to add new Typer commands to the dc29 CLI |
| [examples.md](examples.md) | Runnable code examples |

---

## Quick Start: Send a Command

```python
import serial
from dc29.protocol import ESCAPE, CMD_MUTED, CMD_UNMUTED, CMD_CLEAR

with serial.Serial("/dev/tty.usbmodem14201", 9600) as s:
    s.write(bytes([ESCAPE, CMD_MUTED]))    # LED 4 red
    s.write(bytes([ESCAPE, CMD_UNMUTED]))  # LED 4 green
    s.write(bytes([ESCAPE, CMD_CLEAR]))    # LED 4 off
```

For production use, see `BadgeWriter` in `tools/teams_mute_indicator.py` — it handles reconnection, thread safety, and callbacks.
