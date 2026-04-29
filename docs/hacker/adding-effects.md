# Adding a New LED Effect Mode

← Back to [Hacker Guide](README.md)

This walkthrough adds a new effect mode called **"police"**: alternates LEDs 1 and 3 (red and blue flashing like police lights). LEDs 2 and 4 are unused (LED 4 is always reserved for mute indicator).

---

## Step 1: Update the constant in `main.h`

```c
// BEFORE:
#define NUM_EFFECT_MODES 3   /* 0=off, 1=rainbow-chase, 2=breathe */

// AFTER:
#define NUM_EFFECT_MODES 4   /* 0=off, 1=rainbow-chase, 2=breathe, 3=police */
```

Also add a step interval constant:

```c
#define EFFECT_POLICE_STEP_MS    100   /* ms per step for police mode */
```

---

## Step 2: Add the animation in `main.c`

Find `update_effects()` and add a new branch at the end:

```c
static void update_effects(void){
    if(effect_mode == 0) return;
    uint32_t now = millis;

    if(effect_mode == 1){
        /* ... existing rainbow-chase ... */
    } else if(effect_mode == 2){
        /* ... existing breathe ... */
    } else if(effect_mode == 3){
        /* Police lights: alternates red/blue on LEDs 1 and 3.
           LED 2 stays off. LED 4 NEVER touched (mute indicator). */
        if((now - effect_timer) < EFFECT_POLICE_STEP_MS) return;
        effect_timer = now;

        uint8_t red[3]  = {200, 0, 0};
        uint8_t blue[3] = {0, 0, 200};
        uint8_t off[3]  = {0, 0, 0};

        if(effect_step % 2 == 0){
            led_set_color(1, red);
            led_set_color(2, off);
            led_set_color(3, blue);
        } else {
            led_set_color(1, blue);
            led_set_color(2, off);
            led_set_color(3, red);
        }
        effect_step++;
    }
}
```

### Rules for writing effect code

1. **Never touch LED 4.** It is reserved for the mute indicator. Any write to LED 4 from an effect will conflict with the Teams bridge.
2. **Always use the timer guard:** `if((now - effect_timer) < STEP_MS) return;`
3. `effect_step` and `effect_hue` are reset to 0 automatically by `set_effect_mode()`. You don't need to reset them in your effect.
4. When `effect_mode` returns to 0, `set_effect_mode(0)` restores LEDs 1–3 to their EEPROM colors. Your effect does not need cleanup code.

---

## Step 3: (Optional) Add a step interval constant to `main.h`

Already done above. If you add it to `main.h` instead of directly in `main.c`, it's easier to tune without digging into the animation code:

```c
#define EFFECT_POLICE_STEP_MS  100
```

---

## Step 4: Update Python constants

In `dc29/protocol.py`:

```python
# BEFORE:
class EffectMode(IntEnum):
    OFF = 0
    RAINBOW_CHASE = 1
    BREATHE = 2

EFFECT_NAMES: dict[int, str] = {
    EffectMode.OFF: "off",
    EffectMode.RAINBOW_CHASE: "rainbow-chase",
    EffectMode.BREATHE: "breathe",
}

# AFTER:
class EffectMode(IntEnum):
    OFF = 0
    RAINBOW_CHASE = 1
    BREATHE = 2
    POLICE = 3

EFFECT_NAMES: dict[int, str] = {
    EffectMode.OFF: "off",
    EffectMode.RAINBOW_CHASE: "rainbow-chase",
    EffectMode.BREATHE: "breathe",
    EffectMode.POLICE: "police",
}
```

---

## Step 5: Build and flash

```bash
# In Microchip Studio: Build → Build Solution (F7)
# Then convert:
python3 uf2conv.py Firmware/Source/DC29/Release/DC29.hex --convert --output DC29.uf2
```

Flash using the normal procedure (hold BUTTON4, plug in, copy UF2).

---

## Step 6: Test

```bash
# Set to police mode
dc29 set-effect 3 --port /dev/tty.usbmodem14201

# Use chord to cycle to your new mode:
# Hold all 4 buttons ~0.5s, release
# Cycle: off → rainbow-chase → breathe → police → off
```

Monitor events to confirm the `V 3` event fires:

```bash
dc29 monitor --port /dev/tty.usbmodem14201
```

---

## Ideas for Other Effects

### Sparkle

Randomly light one LED for one step:

```c
} else if(effect_mode == 3){
    if((now - effect_timer) < 80) return;
    effect_timer = now;
    uint8_t off[3] = {0, 0, 0};
    led_set_color(1, off); led_set_color(2, off); led_set_color(3, off);
    uint8_t which = (effect_step * 37) % 3 + 1;  /* pseudo-random: 1, 2, or 3 */
    uint8_t color[3] = {200, 200, 200};
    led_set_color(which, color);
    effect_step++;
```

### Ping-Pong

Bounce one lit LED back and forth:

```c
} else if(effect_mode == 3){
    if((now - effect_timer) < 120) return;
    effect_timer = now;
    uint8_t off[3] = {0, 0, 0};
    led_set_color(1, off); led_set_color(2, off); led_set_color(3, off);
    /* effect_step 0→1→2→1→0→1→... */
    uint8_t pos = effect_step % 4;
    if(pos == 3) pos = 1;
    uint8_t color[3] = {0, 150, 255};
    led_set_color(pos + 1, color);
    effect_step++;
```

### Color Wipe

Gradually fill LEDs with color, then wipe back to off:

```c
} else if(effect_mode == 3){
    if((now - effect_timer) < 200) return;
    effect_timer = now;
    /* Phase 0-2: fill LEDs 1, 2, 3 with color */
    /* Phase 3-5: wipe LEDs 3, 2, 1 to off */
    uint8_t phase = effect_step % 6;
    uint8_t color[3] = {0, 200, 100};
    uint8_t off[3] = {0, 0, 0};
    if(phase <= 2){
        led_set_color(phase + 1, color);
    } else {
        led_set_color(6 - phase, off);
    }
    effect_step++;
```
