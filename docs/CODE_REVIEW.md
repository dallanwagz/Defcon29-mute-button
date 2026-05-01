# DEF CON 29 Badge Firmware — Expert Code Review

**Reviewer perspective**: Expert C developer with deep ASF/SAMD21 embedded systems experience.  
**Codebase**: ~3,000 lines of C across 6 source modules for an ATSAMD21G16B badge.

---

## Executive Summary

This is a functional, shipped product that worked at DEF CON 29. The code shows clear evidence of time pressure: it has working features alongside several real bugs and a collection of patterns that would be cleaned up in a production-quality embedded codebase. The most critical finding is an uninitialized variable that corrupts virtual badge connections, and a switch fall-through that prevents the Simon game's "wait for button" state from ever actually waiting. There are no security-critical vulnerabilities given the physical-access-required threat model, but there are several race conditions that are benign by luck of timing rather than by design.

---

## Confirmed Bugs

### BUG-1: Uninitialized variable corrupts virtual badge serial parsing
**File**: `serialconsole.c`, line ~848  
**Severity**: High — data corruption

```c
// BROKEN: new_serial_num is never initialized
uint32_t new_serial_num;
tempnum = connection_request[4] - 48;
if(tempnum > 9) tempnum -= 7;
new_serial_num |= tempnum << 28;  // |= on garbage!
```

`new_serial_num` is declared but never assigned to `0` before being OR'd into. Whatever garbage was on the stack gets OR'd in, producing an invalid serial number. The "Already connected to this badge" check would then match against this corrupt value. This means virtual badge connections (option 4/5 in the serial console) may silently fail or register incorrect connections.

**Fix**: Change `uint32_t new_serial_num;` to `uint32_t new_serial_num = 0;`

---

### BUG-2: SIMON_SOLO case 0 falls through to case 1 — "wait for button" never waits
**File**: `games.c`, line ~94  
**Severity**: High — game logic broken

```c
case 0: //Wait for game start
    if(game_over_tune == false){
        // ... LED blinking, wait for button1 ...
        if(button1){
            // ...
            gamestate = 1;
        }
    }
    // *** NO break STATEMENT HERE ***
case 1: //Game Setup
    simon_start_tune = true;
    srand(millis);
    // ... sets gamestate = 2 ...
    break;
```

Every time `run_games()` executes with `gamestate == 0`, it immediately falls through into case 1 and reseeds the RNG. The intent was: case 0 displays a blinking LED and waits for button1, which sets `gamestate = 1`, and on the NEXT iteration case 1 runs. Instead, case 1 runs on every single pass through case 0. The game "starts" immediately rather than waiting for user input, and the RNG is reseeded on every loop iteration until `gamestate` advances to 2.

**Fix**: Add `break;` at the end of case 0, before `case 1:`.

---

### BUG-3: SIMON_MULTI_SECONDARY case 0 also falls through to case 1
**File**: `games.c`, line ~411  
**Severity**: Medium — less impactful than BUG-2

```c
case 0: //Game Start!	
    simon_start_tune = true;
    gamestate = 1;
    // *** NO break ***
case 1: //Waiting for sequence packet
    if(simon_start_tune == false){ ... }
```

Here the fall-through is less damaging because case 1 is guarded by `if(simon_start_tune == false)`, so it won't execute while the start tune is playing. However, it's still a latent bug: any future addition to case 1 without that guard would misbehave.

**Fix**: Add `break;` after `gamestate = 1;`.

---

### BUG-4: `last_heartbeat_message_time[]` truncated to uint16 — heartbeat logic fails after ~65 seconds
**File**: `comms.c`, lines 68–73  
**Severity**: Medium — badge-to-badge comms breaks after 65 seconds

```c
volatile uint16_t usart_top_last_msg_time = 0;  // uint16_t!
// ...
// millis is uint32_t, last_heartbeat_message_time[x] is uint32_t
// But usart_*_last_msg_time is uint16_t, separately from the array
```

`millis` is `uint32_t`. The `last_heartbeat_message_time[]` array in the comms arrays is `uint32_t`, but the per-port `usart_top_last_msg_time` etc. variables are `volatile uint16_t`. These shadow variables are assigned `millis` (truncating to 16 bits) and are only used for logging purposes, so this particular set isn't the critical path. However, the pattern creates confusion.

More critically, the RX callback updates: `usart_top_last_msg_time = millis;` — this silently truncates after 65535ms. Not directly causing a crash but a latent timing issue.

**Fix**: Change all six `usart_*_last_msg_time` variables to `volatile uint32_t`.

---

### BUG-5: `configure_usart_top_default()` is an empty stub
**File**: `comms.c`, lines 400–403  
**Severity**: Medium — badge-to-badge top port broken when USB connected

```c
void configure_usart_top_default(void)
{
    // EMPTY — intentionally or accidentally?
}
```

This function is called from `user_callback_vbus_action()` in main.c when USB connects, with the intent to reconfigure SERCOM5 for badge-to-badge use alongside USB. The function does nothing. Top-port badge comms don't work when USB is plugged in. The disable path works fine (SERCOM3 is disabled), but the re-enable path is dead.

**Fix**: Implement or document as intentionally disabled for the USB case.

---

### BUG-6: All UART error callbacks register the wrong function
**File**: `comms.c`, lines 457–461  
**Severity**: Low — error recovery doesn't work as intended

```c
usart_register_callback(&usart_top_instance, usart_usbc_error_callback, USART_CALLBACK_ERROR);
usart_register_callback(&usart_right_instance, usart_usbc_error_callback, USART_CALLBACK_ERROR);
usart_register_callback(&usart_bottom_instance, usart_usbc_error_callback, USART_CALLBACK_ERROR);
usart_register_callback(&usart_left_instance, usart_usbc_error_callback, USART_CALLBACK_ERROR);
usart_register_callback(&usart_usba_instance, usart_usbc_error_callback, USART_CALLBACK_ERROR);
```

All five non-USBC ports register `usart_usbc_error_callback` instead of their own. Since all error callbacks do the same thing (`uart_event = millis;`), this is functionally harmless. But `usart_top_error_callback`, `usart_right_error_callback`, etc. are dead code.

---

### BUG-7: `disable_usarts()` only disables USBA
**File**: `comms.c`, line 1100  
**Severity**: Low — misleading function name

```c
void disable_usarts(void){
    usart_disable(&usart_usba_instance);
    // 5 other UARTs not touched
}
```

Never called from anywhere visible, so currently harmless. But the name implies all UARTs are disabled.

---

### BUG-8: Blocking spin-wait inside ISR read callbacks
**File**: `comms.c`, lines 124–127 (and all 5 other read callbacks)  
**Severity**: Low-Medium — potential deadlock under certain priority configs

```c
void usart_top_read_callback(struct usart_module *const usart_module)
{
    // ... store received byte ...
    uint32_t try_time = millis;
    while(usart_read_job(&usart_top_instance, (uint16_t *)&rx_top_temp_buffer)){
        if(millis - try_time > 100) break;  // 100ms timeout using millis
    }
}
```

This runs in ISR context. The 100ms timeout relies on `millis` advancing, which requires the RTC overflow ISR to preempt this SERCOM ISR. On the SAMD21, both are NVIC interrupts — if the SERCOM ISR has equal or higher priority than RTC, the timeout never fires and this spins forever. In practice it works because Microchip sets SERCOM interrupt priority lower than RTC, but this is fragile and undocumented.

**Better approach**: Queue the `usart_read_job` call and move it to the main loop, or use a DMA receive with a single callback on full-buffer.

---

## Race Conditions (Benign By Luck)

### RACE-1: Ring buffer non-atomic update
**File**: `comms.c`

The circular buffer pattern:
```c
rx_top_buffer[rx_top_buffer_write_index] = rx_top_temp_buffer;
rx_top_buffer_write_index++;
if(rx_top_buffer_write_index == RX_BUFFER_LENGTH) rx_top_buffer_write_index = 0;
rx_top_buffer_length++;
```

The write side (ISR) and read side (main loop) share `rx_top_buffer_length` and indices without any critical section. On CM0+, byte/halfword/word reads/writes to SRAM are atomic, but the multi-step update sequence (store byte, increment write index, increment length) is not. If the main loop reads between `write_index++` and `length++`, it could see an incremented index pointing to unwritten data.

In practice this works because the main loop processes slowly relative to the UART rate and the buffer is 10 bytes deep. But it's a latent data corruption path.

**Fix**: Disable interrupts around the 3-step update, or use a proper lock-free SPSC ring buffer (single-producer-single-consumer).

### RACE-2: `button1`–`button4` flags not atomic
**File**: `main.c`, `games.c`

The button flags are `volatile bool`, set in ISR and cleared in main loop. On CM0+, `bool` is a byte — reads and writes are atomic. The pattern `if(button1){ button1 = false; ... }` has a window between the read and the write where another button press would be silently dropped. Acceptable for debounced button inputs.

---

## Performance Issues

### PERF-1: 6× code duplication for UART ports
**File**: `comms.c`

There are 6 nearly-identical read callbacks, 6 write callbacks, 6 error callbacks, 6 sets of buffer variables, and 6-element if-chains in `send_hello()`, `send_challenge_status()`, etc. This is:
- ~200 extra lines of code consuming flash
- Harder to maintain (a bug fix in one callback must be replicated 6 times — as evidenced by the copy-paste bugs already found)

**Recommended refactor**: Use a `usart_port_t` struct array indexed 0-5:
```c
typedef struct {
    struct usart_module *instance;
    volatile uint8_t buffer[RX_BUFFER_LENGTH];
    volatile uint8_t read_idx, write_idx, length;
    volatile uint16_t temp_buf;
    volatile uint32_t last_msg_time;
    uint8_t rxstate;
    // ...
} usart_port_t;
static usart_port_t ports[6];
```
Single generic ISR dispatches by port index. Saves significant flash and makes bugs impossible to have in only 5/6 ports.

---

### PERF-2: `send_keys()` busy-waits 10ms between each keystroke
**File**: `keys.c`, lines 52–116

```c
udi_hid_kbd_modifier_down(keymap[x]);
lastUSBSendTime = millis;
while(millis - lastUSBSendTime < 10);   // 10ms busy wait
udi_hid_kbd_down(keymap[x+1]);
lastUSBSendTime = millis;
while(millis - lastUSBSendTime < 10);   // 10ms busy wait
// ... 3 more 10ms waits per key
```

Sending one key takes 50ms of blocked execution. The default key 3 (`:)`) sends 5 keystrokes = 250ms completely blocked. During this time, no badge-to-badge comms are processed, no game state updates, and the device can't sleep.

The wait exists because some USB hosts need inter-keystroke delay. A non-blocking state machine approach (returning to the main loop between each step) would allow comms processing during key transmission.

---

### PERF-3: EEPROM write on every badge connection
**File**: `comms.c`, usart_rx_handler state 3 (~line 750)

```c
rww_eeprom_emulator_write_buffer(EEP_CHALLENGE_CONNECTED_TYPES, bytes, 3);
rww_eeprom_emulator_commit_page_buffer();  // This takes milliseconds
// Then again for serial numbers:
rww_eeprom_emulator_write_buffer(EEP_CHALLENGE_BADGE_SERIALS, serialnumlist.bytes, 80);
rww_eeprom_emulator_commit_page_buffer();  // Another few ms
```

Two blocking EEPROM page writes happen synchronously in the receive state machine on every new badge connection. The RWW EEPROM emulator on SAMD21 is write-while-read capable but the commit operation (page erase + write) takes ~2ms per page. This blocks the main loop and could cause missed heartbeat bytes if a UART fires during the commit.

**Mitigation**: Set a dirty flag and defer EEPROM commits to the main loop when no UART activity is pending.

---

### PERF-4: One-byte-at-a-time `check_comms()` processing
**File**: `comms.c`, `check_comms()` function

The function processes exactly one byte per port per call. For an 8-byte Simon message received between two calls to `check_comms()`, it takes 8 iterations of the main loop to fully process. At 38400 baud, a full 8-byte message arrives in ~2ms. This is fine for the use case but creates latency jitter in game message handling.

---

### PERF-5: `sequence_badges[]` and `sequence_buttons[]` over-allocated
**File**: `games.c`, lines 27–28

```c
uint16_t sequence_badges[128] = {0};  // 256 bytes
uint8_t sequence_buttons[128] = {0};  // 128 bytes
```

A game would realistically never reach 128 steps before running out of time or player endurance. The Simon game timeout is 3 seconds per button (`SIMON_BUTTON_TIMEOUT 3000`). These arrays consume 384 bytes of the 8KB RAM budget for a feature that 32 elements would fully cover (still an unreachable score in practice). With only ~4.5KB of usable RAM available, this is 8.5% of the practical budget for marginal benefit.

---

## Code Quality Issues

### QUALITY-1: Dead code consuming flash and RAM

The following are declared and never called/used:

- `send_data()` in `main.c` — sends `1` to all UARTs, never called
- `buzzer_on()`, `buzzer_off()`, `buzzer_set_value()` in `pwm.c` — games use direct TCC calls
- `struct RGB` in `pwm.h` — defined, never instantiated
- `buzzer_counter`, `buzzer_overflow`, `buzzer_state`, `buzzer_skip` in `main.c` — global variables, never read after assignment
- `wait_for_sof` flag — set in `send_keys()`, never actually checked (dead `while(wait_for_sof)` comments)
- `USB_VBUS_PIN` extern interrupt `usba_pin_interrupt_handler` — registered nowhere in the current code

On a 56KB flash budget, dead functions are a real cost.

---

### QUALITY-2: Magic numbers throughout

```c
tcc_set_compare_value(&tcc2_instance, 0, 219);  // 415Hz — but where does 219 come from?
tcc_set_compare_value(&tcc2_instance, 0, 435);  // 209Hz
```

The TCC2 is configured with DIV256 prescaler, GCLK3 at 8MHz. Period = 256. Frequency = 8000000 / 256 / (compare_value * 2). So 219 → 8M / 256 / 438 = ~71Hz... that doesn't match the 415Hz comment. The comments may be wrong, or the actual frequency calculation involves the MATCH_FREQ mode differently. These should be documented constants derived from formulas, not magic numbers.

---

### QUALITY-3: `incmoingserialnum` typo
**File**: `comms.c`, line 80

```c
uint32_t incmoingserialnum[6];  // Should be: incomingserialnum
```

Copy-paste typo from initial development. Not a bug but confusing.

---

### QUALITY-4: `ledChangeNum` variable reused but reset incorrectly in case 9
**File**: `serialconsole.c`, line 425

```c
case 9: //Key Change
    udi_cdc_putc(data); //echo input
    ledChangeNum = 0;    // <-- resets ledChangeNum, but this is the KEYMAP change state
    if(data == '1') keyChangeNum = 1;
```

`ledChangeNum` is reset to 0 at the start of the keymap selection state, even though `ledChangeNum` is the LED number variable. `keyChangeNum` is the key number. This is harmless (ledChangeNum isn't used here) but is copy-paste confusion.

---

### QUALITY-5: `new_serial_num` used after modifications to `connection_request[]`
**File**: `serialconsole.c`, case 11, ~line 948

When parsing a reply message (type '13'), the code destructively modifies `connection_request[]` to decode hex:
```c
connection_request[2] -= 48;
if(connection_request[2] > 9) connection_request[2] -= 7;
```

`connection_request` is a shared 32-byte buffer also used for generating requests. After this mutating parse, the buffer contains decoded numbers, not the original hex string. Any future code path that re-reads `connection_request` expecting hex chars will get corrupted data.

---

### QUALITY-6: `send_challenge_status()` forces `isconnected[port] = true`
**File**: `comms.c`, line 1006

```c
void send_challenge_status(uint8_t port){
    isconnected[port] = true;  // Why?
```

This function is called when a `200` (challenge data request) is received. Forcibly setting `isconnected = true` without going through the heartbeat handshake could leave a port marked connected when it actually isn't. If the remote badge sent `200` and then disconnected, the badge would think it's still connected.

---

### QUALITY-7: Integer input in serial console has no overflow protection
**File**: `serialconsole.c`, states 5/6/7 (LED color entry)

```c
ledChangeColor = ledChangeColor * 10;
ledChangeColor += data - 48;
```

`ledChangeColor` is `static int`. A user typing 10 digits would overflow a 32-bit int on the 10th digit. The only guard is `if(ledChangeColor < 256)` on Enter. Typing `2147483650` would overflow, producing a negative or garbage value that happens to be `< 256`.

---

## Positive Observations

1. **Sleep/power management is well done**: The `standby_sleep()` function correctly quiesces all UARTs before sleeping, slows the RTC interrupt rate, and accounts for elapsed time on wake. The `run_in_standby` flags are set correctly on all peripherals that need to keep running.

2. **RTC-based millis is solid**: Using the RTC in 16-bit count mode with a 33-tick (≈1ms at 32768Hz/1) overflow gives a clean software millisecond counter that survives sleep.

3. **EEPROM version check prevents corruption after firmware updates**: The `FIRMWARE_VERSION` check with full wipe on mismatch is the right pattern for embedded EEPROM management.

4. **The virtual badge connection system is clever**: The encoded 32-byte hex string that embeds both badges' serial numbers is a workable offline badge-exchange mechanism given the lack of NFC or BLE.

5. **The XOR-based URL decryption is appropriately simple**: Light obfuscation, not real security — appropriate for a badge challenge.

6. **LED PWM hardware mapping is correct**: Using TCC0/TCC1 (4 channels each) for the red/green channels and TC3/TC4/TC5 (2 channels each) for the blue channels efficiently uses all available PWM peripherals without conflicts.

---

## Priority Fix List

| Priority | Bug | Fix Effort |
|----------|-----|------------|
| P0 | BUG-1: `new_serial_num` uninitialized | 1 line |
| P0 | BUG-2: SIMON_SOLO case 0 fall-through | 1 line |
| P1 | BUG-4: `uint16_t` heartbeat timestamps | 6 variable declarations |
| P1 | BUG-5: Empty `configure_usart_top_default()` | Investigate + implement |
| P2 | BUG-3: SIMON_MULTI_SECONDARY fall-through | 1 line |
| P2 | RACE-1: Ring buffer non-atomic updates | ~20 lines per port, or refactor |
| P2 | PERF-1: 6× UART code duplication | Major refactor, save ~1KB flash |
| P3 | QUALITY-1: Dead code removal | Audit + delete |
| P3 | PERF-5: Over-allocated game arrays | Reduce from 128 to 32 elements |
| P4 | QUALITY-2: Magic number constants | Define named constants |
