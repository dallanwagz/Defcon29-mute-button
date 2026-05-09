# F04 — Distinct beep signatures per event

> Status: **planned** · Risk: **low** · Owner: firmware + bridges

## Goal

Add a protocol command that fires a named beep pattern from a firmware-side library. Bridges (Teams, CI watchers, build tools) can trigger distinct audible cues without each one inventing a tone-sequence.

## Success criteria

- [ ] Protocol command `0x01 'B' <pattern_id>` where `<pattern_id>` is a single byte (0–255).
- [ ] At least 8 patterns shipped: `silence`, `confirm`, `decline`, `teams-ringing`, `teams-mute-on`, `teams-mute-off`, `ci-passed`, `ci-failed`. Each is a fixed sequence of (frequency_hz, duration_ms) pairs stored in flash (read-only).
- [ ] Patterns play asynchronously — the protocol command returns immediately; pattern continues via timer.
- [ ] A new pattern command interrupts the in-progress pattern cleanly (no overlap, no half-played note carry-over).
- [ ] `0x01 'B' 0` (silence) cancels any running pattern.
- [ ] Patterns yield to button-press click (F03) and to game audio.
- [ ] Documented in `dc29/protocol.py` with a `BeepPattern` enum.
- [ ] Build still fits in 56 KB.

## Test plan

1. **Build + flash + regression**.
2. **Each pattern**: send `0x01 'B' n` for each of the 8 patterns from `dc29 console`. Confirm the audible difference between them (record on phone if needed for sign-off audio archive).
3. **Silence cancels**: start `teams-ringing` (long pattern). Send `0x01 'B' 0` mid-pattern. Buzzer goes silent within 50 ms.
4. **Interrupt cleanly**: start `ci-passed`. Mid-pattern, send `ci-failed`. The "passed" sequence stops, "failed" begins from its first note. No double-tones.
5. **Async dispatch**: the CDC byte sequence returns within < 5 ms (measure via `dc29 console` timestamps). Pattern continues without blocking.
6. **Coexistence with F03**: enable haptic click. Start a long pattern. Tap a button. Confirm the click fires (or document priority — recommend: pattern continues, click suppressed during pattern).
7. **Bridge integration smoke test**: temporarily wire Teams bridge to send `teams-mute-on` on mute. Toggle mute in a meeting. Confirm beep.

## Design proposal (review before code lands)

> Cross-cutting decisions live in [`DESIGN.md`](../DESIGN.md). This section captures only F04-specific bits. **Letter allocation, buzzer arbitration, and beat-doubler interplay are all defined in DESIGN.md §1, §2, and §5.**

### Protocol letter (final)

Per [DESIGN.md §1](../DESIGN.md#1-protocol-command-letter-allocation):

```
0x01 'p' <pattern_id:1>     # play named beep pattern (id 0–255)
```

`pattern_id == 0` → `silence` (cancel any in-progress pattern).

### Pattern definition format

Each pattern is a flat array in flash:

```c
typedef struct {
    uint16_t freq_hz;     // 0 = rest (silence for duration)
    uint16_t dur_ms;      // 0 = end-of-pattern sentinel
} note_t;

static const note_t pat_confirm[]      = { {1200, 30}, {0, 0} };
static const note_t pat_decline[]      = { {300, 60}, {0, 30}, {300, 60}, {0, 0} };
static const note_t pat_teams_ringing[] = { {880, 100}, {0, 50}, {880, 100}, {0, 0} };
// etc.

static const note_t * const PATTERNS[] = {
    [0] = NULL,             // silence sentinel — also handled specially
    [1] = pat_confirm,
    [2] = pat_decline,
    [3] = pat_teams_ringing,
    [4] = pat_teams_mute_on,
    [5] = pat_teams_mute_off,
    [6] = pat_ci_passed,
    [7] = pat_ci_failed,
};
```

Patterns live in `pwm.c` next to the takeover personality tables.

### Pattern engine

Add to `pwm.c`:

```c
static const note_t *pat_cur = NULL;
static uint32_t pat_note_end = 0;

void beep_play_pattern(uint8_t id);   // public — arbitrated via buzzer_owner
static void _pattern_tick(void);       // called from main loop (next to _buzzer_tick)
```

`_pattern_tick` advances `pat_cur` when `millis >= pat_note_end`, calls `buzzer_play()` for the next note, sets the next deadline. `dur_ms == 0` (sentinel) ends the pattern and releases buzzer ownership.

### Coexistence with takeover and F03

Per [DESIGN.md §2](../DESIGN.md#2-buzzer-arbitration), priority is **takeover > pattern > haptic-click**. So a takeover click during a pattern preempts the pattern note for ~30 ms, then the pattern resumes (or restarts the current note — implementation detail, document chosen behavior). F03 haptic clicks are suppressed entirely while a pattern is running.

**Decision: a takeover click does not resume the pattern.** It cancels and the host re-issues if it wants to. Simpler, and patterns are typically a host-driven response to an event the user already saw.

### `BeepPattern` enum in `dc29/protocol.py`

```python
class BeepPattern(IntEnum):
    SILENCE         = 0
    CONFIRM         = 1
    DECLINE         = 2
    TEAMS_RINGING   = 3
    TEAMS_MUTE_ON   = 4
    TEAMS_MUTE_OFF  = 5
    CI_PASSED       = 6
    CI_FAILED       = 7
```

### Files touched

**Modified:**
- `pwm.c` — add patterns + engine. ~120 LOC.
- `pwm.h` — declare `beep_play_pattern()` + `buzzer_owner_t` enum (also referenced by F03).
- `serialconsole.c` — add `'p'` parser branch.
- `dc29/protocol.py` — add `BeepPattern` + `play_beep(pattern)` helper.

**Estimated flash impact:** ~400 bytes (pattern data + engine).

### Open questions

<a id="f04-q1-pattern-resume-behavior"></a>
#### Q1 — Pattern resume after takeover click

Takeover click cancels the in-progress pattern (don't resume) — host re-issues if needed?

- [x] ✅ Approve as proposed (cancel, no resume)
- [ ] ❌ Reject — resume pattern after the click
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

- [ ] Code complete
- [ ] Build passes (≤ 56 KB)
- [ ] Manual hardware test passed (all items in Test plan above)
- [ ] Implementation notes filled in
- [ ] Testing notes filled in

**Implementation reviewed by:** _ _   **Date:** _ _

### Final sign-off

- [ ] Feature accepted

**Final approved by:** _ _   **Date:** _ _   **Verdict:** _ _
