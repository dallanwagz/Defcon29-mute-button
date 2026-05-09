# F05 — Beat-doubler (audio-reactive buzzer sync)

> Status: **planned** · Risk: **low** · Owner: bridges

## Goal

Sync the buzzer to detected beats from the audio-reactive bridge so the badge becomes a tiny physical kick-drum tap — useful as a pure novelty and as a stress-test of the F04 beep-signature timing path.

## Why this is bridge-only

F04 already exposes the `0x01 'B'` command. This feature is just a Python bridge that consumes the existing audio-feature stream from `AudioCapture` and emits one beep command per beat.

## Success criteria

- [ ] New bridge `dc29.bridges.beat_buzzer.BeatBuzzerBridge` registered in `manifest.py` as `beat-buzzer`.
- [ ] Subscribes to `AudioCapture.on_features` (same hook the strobe bridge uses).
- [ ] On each `features.beat == True`, fires a short `confirm` (or new `kick`) pattern.
- [ ] Throttle: skip beats arriving < 80 ms after the prior fire (avoid buzzer queueing on rapid double-detect).
- [ ] Yields to Teams during meetings (mute-state ≠ NOT_IN_MEETING → bridge idle).
- [ ] Toggleable via TUI bridge tab and `dc29 start --enable beat-buzzer`.
- [ ] No firmware change required if F04 is already shipped.

## Test plan

1. **Pre-req check**: F04 must be signed-off and flashed.
2. **Audio setup**: confirm BlackHole multi-output device is active (`dc29 audio status`).
3. **Smoke**: `dc29 start --enable beat-buzzer`. Play a track with a clear 4-on-the-floor kick (e.g., a house track at 120 BPM). Confirm the buzzer ticks roughly with the kick drum.
4. **Throttle**: play double-time drum-and-bass (~170 BPM). Confirm the buzzer doesn't smear into a continuous tone — the 80 ms guard should drop excess beats.
5. **Teams yield**: start a Teams meeting while the bridge is running. Confirm the buzzer goes silent during the meeting and resumes on call end.
6. **Stack with strobe**: enable `audio-reactive`, `beat-strobe`, and `beat-buzzer` simultaneously. Confirm visual + audible sync without buzzer cutoff.
7. **Disable**: uncheck in TUI. Confirm buzzer falls silent within one frame.

## Design proposal (review before code lands)

> Cross-cutting decisions live in [`DESIGN.md`](../DESIGN.md). F05 has **zero firmware changes** — it's pure Python that emits F04 commands. The interesting design choices are throttling and Teams yield.

### Implementation summary

A new bridge `dc29/bridges/beat_buzzer.py`, mirror-image of `beat_strobe.py`. Subscribes to `AudioCapture.on_features`. On each `features.beat == True`, sends `0x01 'p' <BeepPattern.CONFIRM>` (or a new `KICK` pattern — see below).

```python
class BeatBuzzerBridge(BaseBridge):
    def __init__(self, badge, config=None):
        super().__init__(badge)
        self._last_fire_ms = 0
        # ... (capture setup mirrors beat_strobe.py)

    def _on_features(self, features: AudioFeatures) -> None:
        if not features.beat:
            return
        now_ms = time.monotonic() * 1000
        if now_ms - self._last_fire_ms < 80:
            return  # throttle
        if self._badge.state.mute_state != MuteState.NOT_IN_MEETING:
            return  # yield to Teams
        self._badge.play_beep(BeepPattern.KICK)
        self._last_fire_ms = now_ms
```

### Should we add a dedicated `KICK` pattern?

`CONFIRM` is currently spec'd as `(1200 Hz, 30 ms)` — pleasant, slightly sharp. For beat-syncing, a lower-pitched, shorter "thud" reads better. **Decision: add `BeepPattern.KICK = 8` to the F04 pattern table** as `(180 Hz, 12 ms)`. This is *the only F04 change required by F05* — listed under F04 success criteria as a follow-up (or rolled in if F04 lands first).

### Throttle constant

80 ms guard between fires. At 170 BPM (drum-and-bass) the kick interval is ~350 ms, so we never trip the guard. At 200 BPM × beat-doubling (e.g., audio analysis flagging snares as beats too) we could see 150 ms spacing — still under-guard. Set guard at 80 ms and forget.

### Bridge manifest entry

```python
# dc29/bridges/manifest.py
BridgeSpec(
    name="beat-buzzer",
    description="Audio-driven buzzer kick — fires F04 KICK pattern on each detected beat",
    factory=_make_beat_buzzer,
),
```

Default off; `dc29 start --enable beat-buzzer`. TUI bridge tab shows the checkbox automatically.

### Files touched

**New:**
- `dc29/bridges/beat_buzzer.py` (~80 LOC, mirroring `beat_strobe.py`)

**Modified:**
- `dc29/bridges/manifest.py` — register bridge
- (depends on F04 having shipped) `dc29/protocol.py` — `BeepPattern.KICK`

### Open questions

<a id="f05-q1-kick-pattern-frequency"></a>
#### Q1 — KICK pattern frequency

Add `BeepPattern.KICK = 8` at 180 Hz / 12 ms (proposed) — punchy, mid-range thud?

- [x] ✅ Approve as proposed (180 Hz / 12 ms)
- [ ] ❌ Reject — use 140 Hz / 12 ms (more thump) or 240 Hz / 12 ms (more click)
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

- [ ] Bridge code complete
- [ ] Bridge registered in TUI + manifest
- [ ] Manual hardware test passed (all items in Test plan above)
- [ ] Implementation notes filled in
- [ ] Testing notes filled in

**Implementation reviewed by:** _ _   **Date:** _ _

### Final sign-off

- [ ] Feature accepted

**Final approved by:** _ _   **Date:** _ _   **Verdict:** _ _
