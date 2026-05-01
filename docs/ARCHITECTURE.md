# DEF CON 29 Badge — Architecture Reference

This document describes the system architecture at a technical level. It is intended for developers who need to understand data flow, hardware mapping, and module interactions before making changes.

---

## System Block Diagram

```
                         ┌─────────────────────────────────────────┐
                         │           ATSAMD21G16B (CM0+)           │
                         │                                          │
  USB Host ──────────────┤ USB (DP/DM = PA24/PA25)                 │
  (Keyboard + CDC)       │   ├── HID Keyboard (buttons/slider)     │
                         │   └── CDC Serial (terminal menu)        │
                         │                                          │
  Badge (top)  ──────────┤ SERCOM5: PB22(TX) PB23(RX)             │
  Badge (right) ─────────┤ SERCOM1: PA16(TX) PA17(RX)             │
  Badge (bottom) ────────┤ SERCOM2: PA12(TX) PA13(RX)             │
  Badge (left) ──────────┤ SERCOM0: PA08(TX) PA09(RX)             │
  Badge via USB-A ───────┤ SERCOM4: PA14(TX) PA15(RX)             │
  Badge via USB-C ───────┤ SERCOM3: PA24(TX) PA25(RX)  ← SHARED   │
                         │          with USB D+/D-                 │
                         │                                          │
  Button 1 (top-left) ───┤ PA04 (EXTINT4)                          │
  Button 2 (top-right) ──┤ PA05 (EXTINT5)                          │
  Button 3 (bot-left) ───┤ PA06 (EXTINT6)                          │
  Button 4 (bot-right) ──┤ PA07 (EXTINT7)                          │
                         │                                          │
  USB VBUS detect ───────┤ PA01 (EXTINT1, pull-down)               │
  Matrix pin ────────────┤ PA28 (challenge pin, input pull-up)      │
  Max pin ───────────────┤ PA27 (challenge pin, input pull-up)      │
  Aliens pin ─────────────┤ PB02 (challenge pin, input pull-up)     │
                         │                                          │
  LED1 R/G/B ────────────┤ PA22 / PA10 / PB08                      │
  LED2 R/G/B ────────────┤ PA23 / PA11 / PB09                      │
  LED3 R/G/B ────────────┤ PA20 / PA18 / PB10                      │
  LED4 R/G/B ────────────┤ PA21 / PA19 / PB11                      │
  Buzzer ─────────────────┤ PA00 (TCC2/WO0)                        │
                         │                                          │
  Touch Slider ──────────┤ QTouch (multiple pins, closed-source)   │
                         └─────────────────────────────────────────┘
```

---

## Clock Tree

```
OSC8M (8MHz) ──── GCLK3 ──┬── SERCOM0 (UART Left)
                           ├── SERCOM1 (UART Right)
                           ├── SERCOM2 (UART Bottom)
                           ├── SERCOM3 (UART USB-C)
                           ├── SERCOM4 (UART USB-A)
                           ├── SERCOM5 (UART Top)
                           ├── TCC2 (Buzzer)
                           └── RTC (1ms millis timer)

DFLL (48MHz, USB recovery) ── GCLK0 ──┬── USB (requires exactly 48MHz)
                                       ├── TCC0 (LED1R, LED2R, LED3R, LED4R)
                                       ├── TCC1 (LED1G, LED2G)
                                       ├── TC3  (LED3G, LED4G)
                                       ├── TC4  (LED1B, LED2B)
                                       └── TC5  (LED3B, LED4B)
```

**Note**: GCLK3 is configured in `main.c` directly via register writes, not in `conf_clocks.h`. It runs in standby mode to keep UARTs alive during sleep.

---

## Main Loop Execution Flow

```
main()
  │
  ├── Hardware init (clocks, GPIO, UARTs, USB, timer, QTouch, PWM)
  │
  └── while(1) ──────────────────────────────────────────────────┐
        │                                                          │
        ├─ [if IDLE mode && USB active]                           │
        │    ├─ Check button1-4 flags → send_keys()               │
        │    └─ Poll QTouch slider → send_keys(5 or 6)            │
        │                                                          │
        ├─ [if CDC enabled && CDC has data]                        │
        │    └─ updateSerialConsole()                              │
        │                                                          │
        ├─ [if battery power && >1s idle && not SIMON_SOLO]        │
        │    └─ standby_sleep()                                    │
        │         ├─ LEDs off                                      │
        │         ├─ Wait for UART TX to finish                    │
        │         ├─ Stop buzzer                                   │
        │         ├─ Slow RTC to 500ms                             │
        │         ├─ sleepmgr_sleep(STANDBY)  ← CPU halts here    │
        │         ├─ Restore RTC to 1ms                            │
        │         └─ send_heartbeats()                             │
        │                                                          │
        ├─ check_comms()                                           │
        │    ├─ Drain ring buffers → usart_rx_handler(port, byte)  │
        │    ├─ Send heartbeats every 500ms                        │
        │    ├─ Mark ports disconnected after 3 missed heartbeats  │
        │    ├─ Send hello when port transitions to connected      │
        │    └─ Update gamemode based on USBA/USBC connection state│
        │                                                          │
        ├─ run_games()                                             │
        │    └─ Switch on gamemode → switch on gamestate           │
        │         └─ Update LEDs, send/receive Simon packets       │
        │                                                          │
        └─ play_sounds()  ──────────────────────────────────────┘
             └─ Non-blocking state machine for buzzer tunes
```

---

## Interrupt Priority and Sources

The SAMD21 uses the ARM NVIC. Default ASF configuration assigns all peripheral interrupts the same priority unless explicitly changed. Active interrupt sources:

| Source | Handler | Frequency |
|--------|---------|-----------|
| RTC overflow | `rtc_overflow_callback()` | ~1000/sec (1ms period) |
| SERCOM0-5 RX | `usart_*_read_callback()` | Up to 3840 bytes/sec per port at 38400 baud |
| SERCOM0-5 TX | `usart_*_write_callback()` | After each write completes |
| EXTINT1 | `vbus_handler()` | On USB connect/disconnect |
| EXTINT4-7 | `button1-4_handler()` | On button press |
| USB | USB stack (ASF internal) | Each USB frame (1ms) |

**Important**: The RTC overflow callback (`rtc_overflow_callback`) updates `millis` and also handles Simon game button-to-LED feedback. This means LED responses to button presses during Simon mode happen from interrupt context, not the main loop. This is fine on CM0+ since these are register writes, but be aware when debugging timing.

---

## UART Packet State Machine

The `usart_rx_handler(port, byte)` function implements a per-port state machine:

```
rxstate[port] == 0  → Idle, counting sync bytes
                        4× byte(29) received → rxstate = 1
                        
rxstate[port] == 1  → Message type byte
                        byte == 0   → Heartbeat → send ACK → rxstate = 0
                        byte == 1   → Hello → rxstate = 2
                        byte == 255 → ACK → rxstate = 0
                        byte == 200 → Challenge request → send_challenge_status() → rxstate = 0
                        byte == 6   → Badge count req (ports 4-5 only) → rxstate = 6
                        byte == 7   → Badge count resp → rxstate = 7
                        byte == 8   → Simon seq → rxstate = 8
                        byte == 9   → Simon button → rxstate = 9
                        byte == 10  → Simon game over → rxstate = 10
                        
rxstate[port] == 2  → Hello: collecting 4-byte serial number
rxstate[port] == 3  → Hello: badge type byte → update challenge data
rxstate[port] == 4  → Hello: badges_collected byte → check signal sharing
rxstate[port] == 5  → Hello: connections byte → send_hello() reply → rxstate = 0

rxstate[port] == 6  → Badge count: 2 data bytes
rxstate[port] == 7  → Badge count response: 2 data bytes

rxstate[port] == 8  → Simon sequence: 3 data bytes (badge_hi, badge_lo, button)
rxstate[port] == 9  → Simon button press: 3 data bytes
rxstate[port] == 10 → Simon game over: 2 data bytes (score_hi, score_lo)
```

Any unexpected data in a non-sync state resets via the `default:` case: `rxstate[port] = 0`.

---

## Game Mode State Machine

```
                    ┌────────────────┐
       boot         │                │
      ──────────────►     IDLE       │◄───── badge disconnected
                    │                │
                    └───────┬────────┘
                            │
              ┌─────────────┼─────────────────────┐
              │             │                      │
              │ USBC port   │ hold btn1      USBA port
              │ connects    │ at boot        connects
              ▼             ▼                      ▼
     ┌─────────────┐  ┌──────────────┐   ┌──────────────────┐
     │ SELECT_GAME │  │  SIMON_SOLO  │   │  WAIT_FOR_START  │
     │  (left badge│  │  (standalone)│   │  (right/mid badge│
     │   in chain) │  └──────────────┘   └──────────────────┘
     └──────┬──────┘
            │ btn1 pressed → get_badge_count()
            ▼
     ┌──────────────────┐
     │ SIMON_MULTI      │
     │ _PRIMARY         │◄──── badge_count_ready flag set
     └──────────────────┘      by badge count response packet

All secondary badges:  WAIT_FOR_START → SIMON_MULTI_SECONDARY
                       (triggered by receiving game start packet / simon_start_tune)
```

---

## EEPROM Memory Map

```
Offset  Size  Name                          Reset Default
──────────────────────────────────────────────────────────
0       1     FIRMWARE_VERSION              1
1       1     challengedata.badgetypes      0
2       2     challengedata.numconnected    0
4       2     challengedata.numshared       0
6       80    serialnumlist (20×uint32)     all zeros
86      2     simon_solo_high_score         0
88      2     simon_multi_high_score        0
90      2     simon_multi_connections       0
92      2     simon_multi_games_played      0
94      2     wam_solo_high_score           0
96      2     wam_multi_high_score          0
98      2     wam_multi_connections         0
100     2     wam_multi_games_played        0
102     2     wam_multi_wins                0
104     1     LED brightness                255
105     3     led1color [R,G,B]             [255,0,0]
108     3     led2color [R,G,B]             [0,255,0]
111     3     led3color [R,G,B]             [0,0,255]
114     3     led4color [R,G,B]             [127,127,127]
117     3     led1pressedcolor [R,G,B]      [0,127,127]
120     3     led2pressedcolor [R,G,B]      [127,0,127]
123     3     led3pressedcolor [R,G,B]      [127,127,0]
126     3     led4pressedcolor [R,G,B]      [0,0,0]
129     231   keymap (variable length)      default_keymap
──────────────────────────────────────────────────────────
Total max: 360 bytes  (EEPROM emulator limit: 260 bytes)
```

> **Warning**: The EEPROM emulator on this chip supports only 260 bytes total. The table above reaches 360 bytes maximum. The keymap is the variable element — the default is 21 bytes leaving 119 bytes of headroom. Do not exceed 260 total.

---

## LED to PWM Peripheral Mapping

```
LED#  Color  Pin   Peripheral  Channel
────────────────────────────────────────
1     R      PA22  TCC0        WO4 (match[0])
1     G      PA10  TCC1        WO0 (match[0])
1     B      PB08  TC4         WO0 (ch0)

2     R      PA23  TCC0        WO5 (match[1])
2     G      PA11  TCC1        WO1 (match[1])
2     B      PB09  TC4         WO1 (ch1)

3     R      PA20  TCC0        WO6 (match[2])
3     G      PA18  TC3         WO0 (ch0)
3     B      PB10  TC5         WO0 (ch0)

4     R      PA21  TCC0        WO7 (match[3])
4     G      PA19  TC3         WO1 (ch1)
4     B      PB11  TC5         WO1 (ch1)

All use inverted output polarity. Period = 256 counts.
Value 0 = off, value 255 = full brightness.
```

---

## Keymap Binary Format

```
[LENGTH_BYTE]  ← total number of bytes that follow (not including this byte)
 
For each key (1–6):
  [KEY_MARKER]  ← 250 for key1, 251 for key2, ..., 255 for key6
  For each keystroke in this key's sequence:
    [MODIFIER]  ← HID modifier bitmask, OR 240 for media key
    [KEYCODE]   ← HID keycode, OR media keycode if modifier==240
                  OR 0 if this keystroke should be skipped (disabled)

Example — default keymap:
Offset 0:  21   = total length
Offset 1:  250  = key1 marker
Offset 2:  3    = modifier (Left Ctrl | Left Shift)
Offset 3:  16   = HID keycode for 'm'
Offset 4:  251  = key2 marker
Offset 5:  240  = media key marker
Offset 6:  32   = HID_MEDIA_MUTE
Offset 7:  252  = key3 marker
Offset 8:  2    = shift modifier
Offset 9:  51   = ':'
Offset 10: 2    = shift modifier
Offset 11: 39   = ')'
Offset 12: 253  = key4 marker
Offset 13: 240  = media marker
Offset 14: 16   = HID_MEDIA_PLAY
Offset 15: 254  = key5 (slider up) marker
Offset 16: 240  = media marker
Offset 17: 64   = HID_MEDIA_VOL_PLUS
Offset 18: 255  = key6 (slider down) marker
Offset 19: 240  = media marker
Offset 20: 128  = HID_MEDIA_VOL_MINUS
```

---

## Virtual Badge Connection String Format

The 32-character hex string (positions 0–31) encodes two serial numbers:

```
Request string (type "12"):
  [0-1]   = random hex
  [2-3]   = requester serial bits 31-24 (MSB)
  [4-7]   = random hex
  [8-9]   = requester serial bits 23-16
  [10-15] = random hex
  [16-19] = requester serial bits 15-0 (spread as 4 nibbles)
  [20]    = '1'  ← message type first digit
  [21]    = '2'  ← message type second digit
  [22-31] = random hex

Reply string (type "13"):
  [0-1]   = random hex
  [2-3]   = original requester serial bits 31-24
  [4-7]   = responder serial number (4 nibbles = 16 bits)
  [8-9]   = original requester serial bits 23-16
  [10-13] = responder serial (next 4 nibbles)
  [14-15] = responder serial (next 2 nibbles)
  [16-19] = original requester serial bits 15-0
  [20]    = '1'
  [21]    = '3'
  [22-23] = random
  [24-25] = responder's BADGE_TYPE as 2-char hex
  [26-27] = random
  [28-29] = responder's challengedata.badgetypes as 2-char hex
  [30-31] = random
```

---

## Module Dependency Graph

```
main.c ──────────────────────────── includes all modules
  │
  ├── comms.c  (badge-to-badge protocol)
  │     └── calls: led_set_color(), simon_game_over()
  │
  ├── games.c  (game state machines)
  │     └── calls: led_set_color(), send_simon_game_packet(),
  │                send_simon_button_packet(), send_simon_game_over(),
  │                get_badge_count(), send_heartbeats()
  │
  ├── keys.c   (USB HID output)
  │     └── calls: rww_eeprom_emulator_read_buffer()
  │
  ├── pwm.c    (LED + buzzer hardware)
  │     └── calls: ASF TCC/TC driver functions
  │
  └── serialconsole.c (serial terminal menu)
        └── calls: led_set_color(), get_keymap(), reset_user_eeprom(),
                   read_eeprom(), rww_eeprom_emulator_*
```

**Shared global state** (major variables shared across modules via `extern`):

| Variable | Defined In | Used By |
|----------|-----------|---------|
| `millis` | main.c | comms, games, keys, serialconsole |
| `gamemode` | main.c | comms, games |
| `challengedata` | main.c | comms, serialconsole |
| `gamedata` | main.c | comms, games, serialconsole |
| `button1`–`button4` | main.c | games |
| `isconnected[]` | comms.c | comms (internal) |
| `badge_count_ready` | games.c | comms |
| `incoming_badge_number/button` | games.c | comms |
| `gamestate` | games.c | comms |
| `tcc2_instance` | pwm.c | main (RTC callback), games |
| `USBPower` | main.c | pwm, comms |
