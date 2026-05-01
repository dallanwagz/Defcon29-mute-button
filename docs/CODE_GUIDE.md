# DEF CON 29 Badge Firmware — Complete Code Guide

**Target audience**: Someone with 1–2 years of coding experience who wants to understand what this code does and how to safely modify it. You don't need to be an expert in embedded systems, but you should be comfortable reading C code and understand concepts like functions, loops, and variables.

---

## What Is This Project?

This is the firmware (software that runs on the hardware) for the DEF CON 29 conference badge. The badge is a physical wearable device shaped like a keyboard. When you plug it into a computer via USB, it acts as a **USB keyboard** — pressing its buttons sends pre-programmed keystrokes. When not connected to USB, it can **connect to other badges** wirelessly (using physical connectors) to play multiplayer games and participate in a conference-wide scavenger hunt challenge.

The badge is built around a tiny microcontroller chip called the **ATSAMD21G16B**, which has:
- **56KB of program storage** (flash memory — where your code lives permanently)
- **8KB of working memory** (RAM — where your variables live while it runs)
- A built-in **USB interface**, multiple **serial communication ports**, **timers**, and **PWM** (for LEDs and buzzer)

Think of it like a very small computer with extremely limited resources. Running out of storage means the code won't fit and won't compile. Running out of RAM means the program crashes silently.

---

## How The Code Is Organized

All the source files are in `Firmware/Source/DC29/src/`. Each `.c` file has a matching `.h` header file that declares what functions the file provides to the rest of the program.

```
src/
├── main.c / main.h          ← The entry point. Runs everything.
├── comms.c / comms.h        ← Badge-to-badge communication (6 UART ports)
├── games.c / games.h        ← Simon Says and other games
├── keys.c / keys.h          ← USB keyboard functionality
├── pwm.c / pwm.h            ← LED colors and buzzer control
├── serialconsole.c/.h       ← Serial terminal menu (LED config, keymap, etc.)
├── qtouch/touch.c           ← Touch slider on the front of the badge
└── config/                  ← Hardware configuration files
```

There's also a big folder called `ASF/` which is Microchip's pre-written library of hardware drivers. You generally don't edit those files.

---

## The Big Picture: How The Badge Boots Up

When you power on the badge, execution starts at `main()` in `main.c`. Here's what happens in order:

### 1. Read the chip's serial number
```c
serialnum[0] = *(volatile uint32_t *)0x0080A040;
```
Each ATSAMD21 chip has a unique 128-bit serial number burned in at the factory. The badge reads the last 4 bytes (32 bits) and uses them as the badge's identity. This is how badges recognize each other.

### 2. Initialize EEPROM (saved settings storage)
The badge uses a section of its flash memory to simulate EEPROM — persistent storage that survives power-off. It checks if the stored `FIRMWARE_VERSION` matches the current firmware. If not (first boot or firmware update), it resets everything to defaults.

### 3. Read saved settings
Loads LED colors, keymap, challenge progress, and game scores from EEPROM into RAM variables.

### 4. Initialize all hardware
- Enables interrupts
- Sets up the system clock (48MHz for USB, 8MHz for UARTs/buzzer)
- Configures the 4 physical buttons as inputs with pull-up resistors
- Sets up USB VBUS detection (knows if USB power is connected)
- Initializes all 6 UART ports for badge-to-badge communication
- Initializes the millisecond timer (using the RTC peripheral)
- Initializes the touch slider
- Initializes all LED PWM channels

### 5. Run the startup LED animation
The LEDs cycle through colors sequentially (red → green → blue for each LED), making a rainbow sweep effect.

### 6. Check for Simon solo game mode
If Button 1 is held down during startup, the badge enters solo Simon Says mode directly.

### 7. Enter the main loop
```c
while(1){
    // check buttons
    // service USB serial console
    // maybe go to sleep
    // check badge-to-badge messages
    // run game state machine
    // play sound effects
}
```
The badge runs this loop forever until it's powered off.

---

## The Millisecond Timer

Almost all timing in this codebase is done with a single global variable:
```c
volatile uint32_t millis = 0;
```

This variable increments once per millisecond, driven by a hardware timer interrupt (the RTC peripheral in count mode). To check if 500ms has passed since an event:
```c
if((millis - last_event_time) > 500){
    // 500ms has passed
}
```

The subtraction trick (`millis - last_event_time`) works correctly even when `millis` wraps around back to 0 after ~49 days, because unsigned integer math in C handles overflow gracefully.

**Important**: Never use `delay_cycles_ms()` (which completely freezes the chip) when you could use a `millis`-based timer instead. The `delay_cycles_ms()` calls in `main.c` are only used during startup because the USB stack isn't running yet.

---

## Module Deep Dives

### `main.c` — The Control Center

`main.c` is the glue that connects everything. Its key jobs:

**Button handling**: Each of the 4 buttons has a hardware interrupt that fires when pressed. The interrupt handlers (`button1_handler` through `button4_handler`) just set a boolean flag:
```c
void button1_handler(void){
    if(button1 == false){
        if((millis - lastButton1Press) > DEBOUNCE_TIME){  // 200ms debounce
            lastButton1Press = millis;
            button1 = true;       // Set the flag
            uart_event = millis;  // Reset sleep timer
        }
    }
}
```
The main loop then checks these flags and clears them when handled. This is the standard "interrupt sets flag, main loop processes it" pattern.

**Sleep management**: When running on battery (USB not connected) and there's been no activity for 1 second, the badge enters standby sleep:
```c
if (!USBPower && ((millis - uart_event) > 1000) && gamemode != SIMON_SOLO) {
    standby_sleep();
}
```
In standby, LEDs turn off, all UARTs finish transmitting, the buzzer stops, and the processor halts. The RTC wakes it up every 500ms to send heartbeats to neighboring badges. When an interrupt fires (button press, UART activity), the chip wakes up and picks up where it left off.

**EEPROM layout**: All the offsets for where things are stored in EEPROM are defined in `main.h`. They look like:
```c
#define EEP_LED_1_COLOR 105  // 3 BYTES (R, G, B)
```
If you ever change the layout, you must increment `FIRMWARE_VERSION` so the badge knows to reset the EEPROM on next boot.

---

### `comms.c` — Badge-to-Badge Communication

This is the most complex file. The badge has 6 physical connectors (top, right, bottom, left, USB-A, USB-C) that can connect to other badges. Each connector has its own UART (serial port) running at 38,400 baud.

> **What is UART?** A simple 2-wire serial communication protocol. One wire sends (TX), one receives (RX). Data is sent as a series of bits at a fixed speed (baud rate). It's like Morse code but digital.

**Ring buffers**: When a byte arrives over UART, a hardware interrupt fires and stores the byte in a circular buffer (ring buffer). The main loop then reads from that buffer when it's ready. This prevents losing data if bytes arrive faster than the main loop processes them.

Each port has its own 10-byte ring buffer with three tracking variables:
- `rx_top_buffer_write_index` — where the ISR writes next
- `rx_top_buffer_read_index` — where the main loop reads next  
- `rx_top_buffer_length` — how many unread bytes are waiting

**The packet protocol**: Badges communicate using a simple packet format:
1. **4 sync bytes**: `{29, 29, 29, 29}` — tells the receiver "a packet is starting"
2. **1 message type byte**: What kind of message this is (0=heartbeat, 1=hello, 8=Simon sequence, etc.)
3. **Data bytes** depending on message type

The state machine in `usart_rx_handler()` tracks where it is in receiving a packet using a `rxstate[]` array (one state per port).

**Heartbeat system**: Every 500ms, each port sends a heartbeat packet. If 3 heartbeats are missed (~1.5 seconds), the port is marked disconnected (`isconnected[port] = false`). When a port transitions to connected, the badge sends a "hello" packet with its serial number and badge type.

**Port index mapping**: Throughout `comms.c`, ports are referred to by index number:
- `0` = Top connector (SERCOM5)
- `1` = Right connector (SERCOM1)
- `2` = Bottom connector (SERCOM2)
- `3` = Left connector (SERCOM0)
- `4` = USB-C connector (SERCOM3)
- `5` = USB-A connector (SERCOM4)

---

### `games.c` — Simon Says Game

The badge supports three game modes:

**SIMON_SOLO** — classic Simon Says, one badge
**SIMON_MULTI_PRIMARY** — the "first" badge in a chain that generates the sequence
**SIMON_MULTI_SECONDARY** — middle/last badges in the chain that display hints and register button presses

For multiplayer, badges must be physically connected via their USB-A and USB-C ports in a chain. The leftmost badge (connected via USB-C to the badge to its right, but nothing on USB-A) is the primary. All others are secondary.

**Game state machines**: Each mode uses a `gamestate` variable to track progress:

For SIMON_SOLO:
- State 0: Waiting for player to press button 1
- State 1: Setup (seed random number generator, generate sequence)
- State 2: Display sequence (flash LEDs + play tones in order)
- State 3: Wait for player to press buttons in the correct order

**Sequence timing**: LED display speed gets faster as the score increases:
```c
led_on_time = 220;           // Fast: 220ms LED on
if(sequence_progress < 10) led_on_time = 320;  // Medium: 320ms
if(sequence_progress < 5)  led_on_time = 420;  // Slow: 420ms
```
Plus 50ms off-time between each LED (`pause_time = 50`).

**Sound**: The buzzer plays a tone for each button:
- Button 1 (Green) = 415Hz
- Button 2 (Red) = 310Hz
- Button 3 (Yellow) = 252Hz
- Button 4 (Blue) = 209Hz

**The `play_sounds()` function**: Runs every main loop iteration and uses its own internal state machine (`playstate`) to play multi-note sound effects without blocking. It handles: new_connection tune, old_connection tune, new_signal_share tune, simon_start_tune, game_over_tune, challenge_section_finish tune.

---

### `keys.c` — USB Keyboard

When the badge is plugged into a computer, the 4 buttons and the touch slider can be programmed to send keyboard shortcuts or media control commands.

**Keymap format**: Stored in EEPROM as a binary array. The format is:
```
[total_length_byte]
[250]  ← start of key 1 data
[modifier_byte][HID_keycode]  ← one keystroke
[modifier_byte][HID_keycode]  ← optional: another keystroke in the same key
[251]  ← start of key 2 data
... and so on ...
[255]  ← start of key 6 data (key 6 = slider down)
```
There's no end marker — the `total_length_byte` tells you where the array ends.

**HID codes**: USB keyboards communicate using "HID keycodes" — numbers that represent each key. For example, `4` = 'a', `58` = F1. The `ascii_to_hid[]` table in `serialconsole.h` converts regular characters to HID codes.

**Modifier byte**: The modifier byte is a bitmask for modifier keys:
- `0` = no modifier
- `2` = Left Shift
- `4` = Left Alt
- `1` = Left Ctrl
- `8` = Left GUI (Windows/Command key)
- `240` = special marker meaning "this is a media key, not a regular key"

**Default keymap** (from `main.h`):
- Button 1: Ctrl+Shift+M (default: mute on most systems)
- Button 2: Media Mute
- Button 3: `:)` (types a colon then a close-paren)
- Button 4: Play/Pause
- Slider up: Volume Up
- Slider down: Volume Down

---

### `pwm.c` — LED and Buzzer Control

The badge has 4 RGB LEDs. Each LED has 3 color channels (Red, Green, Blue), giving 12 total PWM channels. PWM (Pulse Width Modulation) rapidly switches each LED channel on and off — the percentage of time it's on determines the brightness.

**Hardware mapping**:
- TCC0 (4 channels) → LED1R, LED2R, LED3R, LED4R (all red channels)
- TCC1 (2 channels) → LED1G, LED2G
- TC3 (2 channels) → LED3G, LED4G
- TC4 (2 channels) → LED1B, LED2B
- TC5 (2 channels) → LED3B, LED4B
- TCC2 (1 channel) → Buzzer

All LEDs use **inverted polarity** because they're wired as common-anode (the positive wire is shared). This means writing `0` to a PWM compare register = LED off, and writing `255` = LED full brightness.

**Battery power savings**: When not connected to USB, all LED brightness values are automatically divided by 5 (approximately 20% brightness) to extend battery life:
```c
void led_set_brightness(leds led, uint8_t brightness){
    if(!USBPower){
        brightness = brightness/5;  // 20% power saving
    }
    // ... set hardware register
}
```

**Key functions**:
- `led_set_color(uint8_t led_num, uint8_t color[3])` — sets an LED by number (1-4) and RGB array
- `led_set_brightness(leds channel, uint8_t brightness)` — sets an individual channel (0-11)
- `led_on(leds channel)` / `led_off(leds channel)` — turn a channel fully on or off

**Buzzer**: Uses TCC2 in "match frequency" mode (the output toggles each time the counter hits the compare value). Lower compare value = higher frequency tone. The buzzer is on pin PA00 which is internally also SERCOM5 TX — but the buzzer uses TCC2 which doesn't conflict because these are separate peripheral mux settings.

---

### `serialconsole.c` — The USB Serial Menu

When you open a serial terminal (like PuTTY or screen) and connect to the badge's USB CDC port at any baud rate, you get an interactive text menu. Press Enter to start.

**What you can do from the menu**:
1. Change LED colors (set custom RGB values for each of the 4 LEDs)
2. Remap the 4 buttons and 2 slider directions to different keystrokes
3. Reset EEPROM to factory defaults (keeps game/challenge data)
4. Generate a virtual badge connection request string (share with others over Discord/chat)
5. Enter a virtual badge connection request or reply string

**The state machine**: `serialConsoleState` tracks where you are in the menu:
- State 0: Waiting for Enter to start
- State 1: Main menu
- State 2: EEPROM reset confirmation
- States 4-8: LED color change flow
- States 9-10: Keymap change flow
- State 11: Parse virtual connection string

**Virtual badge connections**: Since not everyone can physically connect badges, the menu supports "virtual connections" over text. The protocol:
1. Person A generates a 32-character hex string (option 4) containing their serial number scrambled at positions 2-3, 8-9, 16-19
2. Person B enters that string (option 5), which generates a reply string containing both serial numbers and both badges' challenge status
3. Person A enters the reply string, and both badges record each other's connection

This is an honor-system implementation — there's no cryptographic verification, just a format check.

**The `decrypt()` function**: Some website URLs in the challenge are obfuscated so they're not visible in the raw binary firmware. They're stored as bytes XOR'd against the "Welcome to DEF CON 29!" string. The `decrypt()` function reverses this to print the real URL only when you've earned it:
```c
void decrypt(const uint8_t *encoded_string, uint8_t length){
    for(int x=0; x<length; x++){
        decoded_string[x] = (encoded_string[x]-128) ^ SERIAL_SPLASH[x];
    }
    udi_cdc_write_buf(decoded_string, length);
}
```

---

## The Challenge System

The conference badge challenge tracks connections between different "badge types" (Human, Goon, Creator, Speaker, Artist, Vendor, Press — each a different bit in a bitmask):

```
challengedata.badgetypes  = bitmask of types you've physically connected with
challengedata.numconnected = total badge connections ever made
challengedata.numshared    = times you've "shared the signal" with others who need it
```

**How badge types are collected**: When two badges physically connect, they exchange their serial number and badge type. If the type is new, the bit gets set in `challengedata.badgetypes`. The goal is to get all 7 bits set (value 127 = `0b01111111`).

**"The Signal" mechanic**: Once you have all 7 badge types (`badgetypes >= 127`), you've "collected the signal." Now, when you connect to someone who doesn't have all types, your badge shares a type with theirs — automatically filling in one of their missing bits. After sharing with 20 people (`numshared >= 20`), you've completed the challenge and unlock the full set of website URLs in the serial console.

---

## Clock System (Simplified)

The chip has multiple independent clock sources. This badge uses two primarily:

**DFLL at 48MHz** → drives the USB stack and the LED PWM timers (TCC0, TCC1, TC3, TC4, TC5). USB requires exactly 48MHz.

**Internal 8MHz oscillator (OSC8M)** → drives GCLK3, which runs the 6 UARTs, the buzzer timer (TCC2), and the RTC millisecond timer.

The UARTs are configured at 38400 baud (not 9600) because of a clock issue the developer didn't have time to debug — the port was running 4× slower than expected with 9600, so they set it to 38400 to compensate.

---

## How to Make Common Changes

### Change a button's default function
Edit the `default_keymap` array in `main.h`:
```c
static const uint8_t default_keymap[21] = { 
    21,         // total length byte
    250,3,16,   // key1: modifier=3 (ctrl+shift), key=16 (m) = Ctrl+Shift+M
    251,240,32, // key2: 240=media marker, 32=MUTE
    ...
};
```
HID keycodes are in `udi_hid_kbd.h` in the ASF. See `ascii_to_hid[]` in `serialconsole.h` for the ASCII-to-HID mapping.

### Change LED startup colors
The startup colors come from EEPROM, but the defaults are set in `reset_eeprom()` in `main.c`. Find the section that writes `EEP_LED_1_COLOR` through `EEP_LED_4_COLOR` and change the RGB values.

### Add a new badge type
Change `#define BADGE_TYPE` in `main.h`. Valid values: `1` (Human), `2` (Goon), `4` (Creator), `8` (Speaker), `16` (Artist), `32` (Vendor), `64` (Press). Do **not** use `128` (UBER) — it breaks other badges' challenge logic.

### Add a new serial console menu option
In `serialconsole.c`, in `updateSerialConsole()`:
1. Add a new `else if(data == 'X')` case in the `case 1:` main menu handler
2. Assign a new `serialConsoleState` number (e.g., 20)
3. Add the corresponding `case 20:` handler further down the switch
4. Add the menu text to `showSplashScreen()` and the string constants to `serialconsole.h`

### Modify game LED timings
In `games.c`, look for the `led_on_time` variables:
```c
led_on_time = 220;           // milliseconds LED stays on at high score
if(sequence_progress < 10) led_on_time = 320;
if(sequence_progress < 5)  led_on_time = 420;
```
Change these numbers to adjust the game speed. `pause_time = 50` in the header controls the off-time between flashes.

---

## Common Pitfalls

**Don't block in an interrupt handler.** The button handlers and UART read callbacks run in interrupt context. Don't call `delay_cycles_ms()`, don't do EEPROM writes, don't do heavy computation. Set a flag and handle it in the main loop.

**Always call `rww_eeprom_emulator_commit_page_buffer()` after writing.** The EEPROM emulator buffers writes in RAM. Until you call commit, nothing is saved to flash. If power is cut, you lose the data.

**Don't make RAM variables larger than necessary.** The `sequence_badges[128]` and `sequence_buttons[128]` arrays already consume 384 bytes. A new large static array could cause stack overflow, which crashes silently.

**Don't change the EEPROM layout without incrementing `FIRMWARE_VERSION`.** If you add a new EEPROM field or move an existing one, change `#define FIRMWARE_VERSION` in `main.h`. This triggers the wipe-and-reinitialize path on next boot.

**Understand the `millis` timing pattern.** All time measurements use `(millis - last_time) > threshold`. Never use `millis > some_absolute_value` because that breaks after the counter resets.

---

## Glossary

| Term | Meaning |
|------|---------|
| UART | Universal Asynchronous Receiver/Transmitter — a simple serial communication protocol |
| SERCOM | Serial Communication interface — the SAMD21's flexible serial hardware block; can be UART, SPI, or I2C |
| PWM | Pulse Width Modulation — rapidly switching a pin on/off to simulate variable brightness/speed |
| TCC | Timer Counter for Control — a timer peripheral that has PWM output capability |
| TC | Timer Counter — a simpler timer peripheral, also has PWM |
| EEPROM | Electrically Erasable Programmable Read-Only Memory — persistent storage (here, emulated in flash) |
| ISR | Interrupt Service Routine — a function that runs automatically when hardware needs attention |
| GCLK | Generic Clock — the SAMD21's flexible clock distribution system |
| DFLL | Digital Frequency Locked Loop — a clock source that locks to 48MHz using USB SOF packets |
| RTC | Real-Time Counter — a peripheral used here as a 1ms timebase |
| HID | Human Interface Device — the USB device class that keyboards/mice use |
| CDC | Communication Device Class — the USB class for virtual serial ports |
| ASF | Advanced Software Framework — Microchip's HAL (Hardware Abstraction Layer) library |
| HAL | Hardware Abstraction Layer — a software layer that provides consistent APIs across hardware variants |
| Baud rate | The speed of a serial communication link, in bits per second |
| Ring buffer | A fixed-size circular data structure that wraps around — used here for UART receive buffering |
| Volatile | A C keyword telling the compiler "this variable can change unexpectedly" — used for ISR-shared variables |
