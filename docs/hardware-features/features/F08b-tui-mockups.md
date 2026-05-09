# F08b — Stay Awake TUI mockups (review draft)

> Purpose: pick a layout for the new "Stay Awake" tab before I write the
> ~300 LOC of Textual code.  All three variants below render the same
> session state — they differ only in **density** and **what's shown when
> idle vs. active**.
>
> Reply with **A / B / C** (or annotate one).  I'll implement the chosen
> variant and we can iterate.

## Constraints carried over from F08a-lite

The path-2 firmware deviates from the original spec in three places that
affect the TUI:

1. **No firmware wall-clock** — `'j' 'I'` takes a *relative duration*
   (seconds from now), not a UTC end-time.  The TUI can still show an
   absolute end wall-clock by computing it host-side from
   `session_start + duration` — the firmware just doesn't know about it.
2. **No state-query command** — `'j' 'S'` is not implemented.  The bridge
   is the source of truth for active/idle state.  If the bridge restarts
   while the badge is autonomously jiggling, the TUI shows "idle" until
   the badge timer expires naturally.  This is acceptable per the
   "bridge crash recovery" item in the F08 test plan.
3. **Indefinite is just `2**32 - 1` seconds (~136 years)** — there's no
   special "no end-time" sentinel.  TUI labels it "Indefinite" to the
   user; firmware sees a very large duration.

---

## Variant A — Faithful to spec (adjusted)

Closest to the original mockup in [F08-mouse-jiggler.md][f08].  Same
density, same layout, with the wall-clock end-time computed host-side and
"Indefinite" still labeled but mapped to a max duration internally.

```
┌── Stay Awake ────────────────────────────────────────────────┐
│                                                              │
│   Status:  ▓▓▓▓▓▓▓▓▓▓▓▓▓░░░░░░░░░░░░░░░░░░░  62% elapsed     │
│                                                              │
│   ●  ACTIVE                                                  │
│       Time remaining:  03:42:18                              │
│       Will end at:     4:23 PM today  (host clock)           │
│       Started:         12:41 PM (4 hour session)             │
│                                                              │
│   ┌─ Quick start ─────────────────────────────────────┐      │
│   │ [ 30 min ]  [ 1 hour ]  [ 2 hour ]  [ 4 hour ]    │      │
│   │ [ 8 hour ]  [ Indefinite ]    Custom: [ __:__ ] G │      │
│   └───────────────────────────────────────────────────┘      │
│                                                              │
│   ┌─ While awake, show on LEDs… ──────────────────────┐      │
│   │  ( ) Off (don't touch LEDs)                       │      │
│   │  ( ) Slow cyan pulse on LED 1 only                │      │
│   │  (•) Progress bar across all 4 LEDs               │      │
│   │  ( ) Effect mode  [ rainbow chase ▾ ]             │      │
│   └───────────────────────────────────────────────────┘      │
│                                                              │
│   [ Stop now ]                                               │
│                                                              │
│   Last started:  yesterday at 9:14 AM (8 hour session)       │
└──────────────────────────────────────────────────────────────┘
```

**Idle state** swaps the active block:

```
│   ○  idle                                                    │
│       Click a quick-start above or type a Custom duration.   │
```

**Pros:** preserves the design we already approved; rich at-a-glance status.
**Cons:** dense — eats a full screen on a small terminal; "Will end at"
adds a row that's only a derived value.

---

## Variant B — Compact

Same panels, tighter spacing.  Quick-start as a single row.  LED options
as a dropdown rather than a radio group.  Saves ~10 vertical lines.

```
┌── Stay Awake ────────────────────────────────────────────────┐
│                                                              │
│  ●  ACTIVE  ·  3h 42m 18s left  ·  ends 4:23 PM              │
│  ▓▓▓▓▓▓▓▓▓▓▓▓▓░░░░░░░░░░░░░░░░░░░░░░  62%                    │
│                                                              │
│  Start:  [30m] [1h] [2h] [4h] [8h] [∞]   Custom [____]  Go   │
│                                                              │
│  LED:    [ Progress bar              ▾ ]                     │
│                                                              │
│  [ Stop now ]                          Last: 8 h yesterday   │
└──────────────────────────────────────────────────────────────┘
```

**Idle state:**

```
│  ○  idle                                                     │
│  Start:  [30m] [1h] [2h] [4h] [8h] [∞]   Custom [____]  Go   │
│  LED:    [ Progress bar              ▾ ]                     │
```

**Pros:** fits in 8 rows when active; less scrolling on small TTYs;
keeps every control accessible.
**Cons:** dropdown hides the LED choices behind a click; no large
visible Started/Will-end-at separation; "∞" symbol may not render in
every font.

---

## Variant C — Minimal status-bar style

Treat the Stay Awake tab like a control panel instead of a dashboard.
When idle, only show controls.  When active, the controls collapse and
the countdown takes center stage.

**Active:**

```
┌── Stay Awake ────────────────────────────────────────────────┐
│                                                              │
│                                                              │
│                  ●  03:42:18                                 │
│                  ━━━━━━━━━━━━━━━━━━━━                        │
│                  ends 4:23 PM   ·   62%                      │
│                                                              │
│                  LED: progress bar                           │
│                                                              │
│                                                              │
│                  [ Stop now ]                                │
│                                                              │
│                                                              │
└──────────────────────────────────────────────────────────────┘
```

**Idle:**

```
┌── Stay Awake ────────────────────────────────────────────────┐
│                                                              │
│  Pick a duration                                             │
│  ┌───────────────────────────────────────────────────────┐   │
│  │  [ 30 minutes ]  [ 1 hour ]   [ 2 hours ]            │   │
│  │  [ 4 hours    ]  [ 8 hours ]  [ Indefinite ]         │   │
│  │                                                       │   │
│  │  Or custom:  [ ___ h ___ m ]   [ Start → ]            │   │
│  └───────────────────────────────────────────────────────┘   │
│                                                              │
│  While awake, show on LEDs:                                  │
│    ( ) Off                                                   │
│    ( ) Slow cyan pulse on LED 1                              │
│    (•) Progress bar across all 4 LEDs                        │
│    ( ) Effect mode  [ rainbow chase ▾ ]                      │
│                                                              │
│  Last session:  8 h yesterday at 9:14 AM                     │
└──────────────────────────────────────────────────────────────┘
```

**Pros:** the active state is unmistakable from across the room; idle
state is a clean picker with no live-data clutter.
**Cons:** no LED-mode change without stopping the session first; loses
the "running session config still visible" property.

---

## Recommendation

I'd pick **B** for the everyday-use case (compact, all controls always
reachable, easy to glance at while doing other things), with the option
to revisit C later if we ship a separate "always on top" status widget
for laptops where you want the big countdown visible in another window.

A is the safe choice if you specifically want what was approved in the
original design doc.

[f08]: F08-mouse-jiggler.md
