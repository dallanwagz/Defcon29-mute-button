/**
 * \file
 *
 * \brief Main functions for Keyboard example
 *
 * Copyright (c) 2009-2018 Microchip Technology Inc. and its subsidiaries.
 *
 * \asf_license_start
 *
 * \page License
 *
 * Subject to your compliance with these terms, you may use Microchip
 * software and any derivatives exclusively with Microchip products.
 * It is your responsibility to comply with third party license terms applicable
 * to your use of third party software (including open source software) that
 * may accompany Microchip software.
 *
 * THIS SOFTWARE IS SUPPLIED BY MICROCHIP "AS IS". NO WARRANTIES,
 * WHETHER EXPRESS, IMPLIED OR STATUTORY, APPLY TO THIS SOFTWARE,
 * INCLUDING ANY IMPLIED WARRANTIES OF NON-INFRINGEMENT, MERCHANTABILITY,
 * AND FITNESS FOR A PARTICULAR PURPOSE. IN NO EVENT WILL MICROCHIP BE
 * LIABLE FOR ANY INDIRECT, SPECIAL, PUNITIVE, INCIDENTAL OR CONSEQUENTIAL
 * LOSS, DAMAGE, COST OR EXPENSE OF ANY KIND WHATSOEVER RELATED TO THE
 * SOFTWARE, HOWEVER CAUSED, EVEN IF MICROCHIP HAS BEEN ADVISED OF THE
 * POSSIBILITY OR THE DAMAGES ARE FORESEEABLE.  TO THE FULLEST EXTENT
 * ALLOWED BY LAW, MICROCHIP'S TOTAL LIABILITY ON ALL CLAIMS IN ANY WAY
 * RELATED TO THIS SOFTWARE WILL NOT EXCEED THE AMOUNT OF FEES, IF ANY,
 * THAT YOU HAVE PAID DIRECTLY TO MICROCHIP FOR THIS SOFTWARE.
 *
 * \asf_license_stop
 *
 */
/*
 * Support and FAQ: visit <a href="https://www.microchip.com/support/">Microchip Support</a>
 */

#include <asf.h>
#include <stdbool.h>
#include "main.h"
#include "conf_usb.h"
#include "udi_hid_kbd.h"
#include "ui.h"

#include <pinmux.h>
#include <nvm.h>
#include "pwm.h"
#include <rww_eeprom.h>
#include "keys.h"
#include "input.h"
#include "jiggler.h"
#include "serialconsole.h"
#include "wled_fx.h"



static volatile bool main_b_kbd_enable = false;

enum status_code eepromstatus;

/**
 * RTC Interrupt timing definition
 */
#define TIME_PERIOD_1MSEC 33u
#define TIME_PERIOD_500MSEC 16500u
/**
 * Variables
 */

uint32_t serialnum[4];

bool USBPower = false;


uint8_t rotor_state;
uint8_t rotor_position;
volatile uint8_t PWM_Count;
volatile uint32_t touch_time_counter = 0u;
struct rtc_module rtc_instance;

volatile uint32_t millis = 0;

volatile uint32_t buzzer_counter = 0;
volatile uint32_t buzzer_overflow = 250;
volatile bool buzzer_state = false;
volatile bool buzzer_skip = false;

bool main_b_cdc_enable = false;

uint8_t led1color[3];
uint8_t led2color[3];
uint8_t led3color[3];
uint8_t led4color[3];
uint8_t led1pressedcolor[3];
uint8_t led2pressedcolor[3];
uint8_t led3pressedcolor[3];
uint8_t led4pressedcolor[3];

volatile bool wait_for_sof = false;

volatile bool button1 = false;
volatile bool button2 = false;
volatile bool button3 = false;
volatile bool button4 = false;

#define DEBOUNCE_TIME          200
#define CHORD_SHORT_MS         300   /* min hold (ms) to register a short chord */
#define CHORD_LONG_MS         2000   /* hold (ms) to fire a long chord */
#define EFFECT_CHASE_STEP_MS    150   /* ms per step for rainbow-chase mode */
#define EFFECT_BREATHE_STEP_MS    8   /* ms per step for breathe mode */
#define EFFECT_WIPE_STEP_MS     200   /* ms per step for color-wipe mode */
#define EFFECT_TWINKLE_STEP_MS   60   /* ms per step for twinkle mode */
#define EFFECT_GRADIENT_STEP_MS  40   /* ms per step for gradient mode */
#define EFFECT_THEATER_STEP_MS  120   /* ms per step for theater-chase mode */
#define EFFECT_CYLON_STEP_MS     90   /* ms per step for cylon sweep */
#define EFFECT_PARTICLES_STEP_MS 16   /* ~60 fps physics tick */
#define EFFECT_FIRE_STEP_MS      35   /* heat-cell flicker tick */
#define EFFECT_LIGHTNING_STEP_MS 16   /* state-machine tick for flash bursts */
#define EFFECT_POLICE_STEP_MS    70   /* alternating-side strobe */
#define EFFECT_PLASMA_STEP_MS    25   /* summed-sine plasma */
#define EFFECT_HEARTBEAT_STEP_MS 16   /* time-driven lub-dub */
#define EFFECT_AURORA_STEP_MS    50   /* slow cool-spectrum drift */
#define EFFECT_CONFETTI_STEP_MS  70   /* fade-and-sparkle */
#define EFFECT_STROBE_STEP_MS    60   /* rapid full on/off */
#define EFFECT_METEOR_STEP_MS    70   /* head moves, trail fades */
#define EFFECT_JUGGLE_STEP_MS    25   /* 3 sine dots blended */
volatile uint32_t lastButton1Press = 0;
volatile uint32_t lastButton2Press = 0;
volatile uint32_t lastButton3Press = 0;
volatile uint32_t lastButton4Press = 0;

uint8_t keymap[231];
uint8_t keymaplength;
uint8_t keymapstarts[6];

uint8_t fwversion[1];

extern struct tcc_module tcc2_instance;

bool button_flash_enabled = true;

/* Capacitive touch slider enable.  When false, the slider is still scanned
 * (cheap, debounce keeps the position cache consistent) but the
 * volume-up / volume-down HID injections are suppressed.  Set via
 * 0x01 'S' 0/1 from the host.  RAM-only, default on. */
bool slider_enabled = true;

/* Interactive splash on button press.  When true (default), pressing a
 * button while an effect mode is running fires the ~300 ms firmware splash
 * animation — captures the LED's current displayed color, sprays it
 * outward, settles back to the underlying scene.  Works on battery without
 * USB.  Set via 0x01 'I' 0/1 from the host.  RAM-only, default on. */
bool splash_on_press_enabled = true;

/* F03 — haptic-style click on every macro send.  Fires a short, high-pitch
 * buzzer click at the end of send_keys() so the user gets non-visual
 * confirmation that the keystroke fired (useful when focus is off-screen
 * or LEDs are bridge-managed).  Suppressed when button_flash_enabled is
 * true, since the takeover animation already fires its own click in
 * pwm.c — avoids a double-click.  Set via 0x01 'k' 0/1 from the host.
 * RAM-only, default on. */
bool haptic_click_enabled = true;
uint8_t effect_mode = 0;
typedef enum { CHORD_IDLE, CHORD_PENDING, CHORD_LONG_FIRED } ChordState;
static ChordState chord_state = CHORD_IDLE;
static uint32_t   chord_start = 0;
static uint8_t    effect_step = 0;
static uint8_t    effect_hue  = 0;
static uint32_t   effect_timer = 0;
volatile uint32_t last_usb_comms = 0;

/* ─── Particles physics state (effect mode 8) ────────────────────────────
 *
 * The badge has a 2x2 LED matrix:
 *
 *     LED1  ─  LED2     (top row)
 *      │         │
 *     LED3  ─  LED4     (bottom row)
 *
 * Two virtual particles drift through a 2D box and bounce off the four
 * walls.  Each LED corresponds to a corner of the box; its brightness is
 * the sum of contributions from each particle, falloff with distance.
 * Hue bumps on every wall hit (X and Y bumps use different deltas so the
 * pattern doesn't lock into a periodic loop).
 *
 * Position is plain int16 in [0, 255] each axis — no fixed-point math
 * needed because the grid is so small.  Velocity is per-tick @ 60 fps.
 * ────────────────────────────────────────────────────────────────────── */

#define PARTICLE_RANGE   255
#define PARTICLE_COUNT   2
#define PARTICLE_FALLOFF 200   /* manhattan-distance cutoff for LED contribution */

typedef struct {
	int16_t x, y;      /* in [0, PARTICLE_RANGE] */
	int16_t vx, vy;    /* per-tick velocity */
	uint8_t hue;
	uint8_t bright;
} Particle;

/* LED → corner mapping (matches hardware layout). */
static const uint8_t led_corner_x[4] = {0, PARTICLE_RANGE, 0, PARTICLE_RANGE};  /* L1=TL, L2=TR, L3=BL, L4=BR */
static const uint8_t led_corner_y[4] = {0, 0, PARTICLE_RANGE, PARTICLE_RANGE};

static Particle particles[PARTICLE_COUNT];
static bool particles_initialized = false;

static void particles_init(void){
	/* Two seeds with different speeds so they desynchronize quickly. */
	particles[0].x = 60;  particles[0].y = 80;
	particles[0].vx = 3;  particles[0].vy = 2;
	particles[0].hue = 32;  particles[0].bright = 220;

	particles[1].x = 200; particles[1].y = 180;
	particles[1].vx = -2; particles[1].vy = 4;
	particles[1].hue = 180; particles[1].bright = 220;

	particles_initialized = true;
}

/* Forward declarations for static functions defined later in this file */
static void update_effects(void);
static void hsv_to_rgb(uint8_t h, uint8_t v, uint8_t *r, uint8_t *g, uint8_t *b);

/* Macros */

/**
 * \def GET_SENSOR_STATE(SENSOR_NUMBER)
 * \brief To get the sensor state that it is in detect or not
 * \param SENSOR_NUMBER for which the state to be detected
 * \return Returns either 0 or 1
 * If the bit value is 0, it is not in detect
 * If the bit value is 1, it is in detect
 * Alternatively, the individual sensor state can be directly accessed using
 * p_qm_measure_data->p_sensor_states[(SENSOR_NUMBER/8)] variable.
 */
 #define GET_SELFCAP_SENSOR_STATE(SENSOR_NUMBER) p_selfcap_measure_data-> \
	p_sensor_states[(SENSOR_NUMBER / \
	8)] & (1 << (SENSOR_NUMBER % 8))

/**
 * \def GET_ROTOR_SLIDER_POSITION(ROTOR_SLIDER_NUMBER)
 * \brief To get the rotor angle or slider position.
 * These values are valid only when the sensor state for
 * corresponding rotor or slider shows in detect.
 * \param ROTOR_SLIDER_NUMBER for which the position to be known
 * \return Returns rotor angle or sensor position
 */
#define GET_SELFCAP_ROTOR_SLIDER_POSITION(ROTOR_SLIDER_NUMBER) \
	p_selfcap_measure_data->p_rotor_slider_values[ \
		ROTOR_SLIDER_NUMBER]


/* Interrupt on "pin change" from push button to do wakeup on USB
 * Note:
 * This interrupt is enable when the USB host enable remote wakeup feature
 * This interrupt wakeup the CPU if this one is in idle mode
 */
/*static void ui_wakeup_handler(void)
{
	// It is a wakeup then send wakeup USB 
	udc_remotewakeup();
	//LED_On(PIN_PA19);
}*/

void vbus_handler(void){
	if(port_pin_get_input_level(USB_VBUS_PIN)){
		// Start USB stack to authorize VBus monitoring
		disable_usart_top();
		udc_start();
		USBPower = true;
		//configure_usart_top_default();
	} else {
		//disable_usart_top();
		udc_stop();
		configure_usart_top_usb();
		USBPower = false;
	}
}

/*! \brief Main function. Execution starts here.
 */
int main(void)
{
	//Get chip serial number. We only use the last 4 bytes to save EEPROM space and to make comms faster
	serialnum[0] = *(volatile uint32_t *)0x0080A040;
	serialnum[1] = *(volatile uint32_t *)0x0080A044;
	serialnum[2] = *(volatile uint32_t *)0x0080A048;
	serialnum[3] = *(volatile uint32_t *)0x0080A00C;
	
	eepromstatus = rww_eeprom_emulator_init();
	if(eepromstatus == STATUS_ERR_BAD_FORMAT){
		rww_eeprom_emulator_erase_memory();
		rww_eeprom_emulator_init();
	}

	rww_eeprom_emulator_read_buffer(EEP_FIRMWARE_VERSION, fwversion, 1);
	
	if(fwversion[0] != FIRMWARE_VERSION){ //Clear eeprom and re-init with good values
		reset_eeprom();
	}
	
	read_eeprom();
	
	
	//uint8_t button1_state;
	//uint8_t button2_state;
	uint8_t slider_state;
	uint8_t slider_position;
	uint8_t last_slider_position;
	
	irq_initialize_vectors();
	cpu_irq_enable();

	// Initialize the sleep manager
	//sleepmgr_init();

#if !SAM0
	sysclk_init();
	board_init();
#else
	system_init();
#endif

	//Enable GCLK Generator 3
	SYSCTRL->VREG.bit.RUNSTDBY = 1;
	
	// Configure GCLK3's divider - in this case, no division - so just divide by one /
	GCLK->GENDIV.reg =
	GCLK_GENDIV_ID(3) |
	GCLK_GENDIV_DIV(1);

	// Setup GCLK3 using the internal 8 MHz oscillator /
	GCLK->GENCTRL.reg =
	GCLK_GENCTRL_ID(3) |
	GCLK_GENCTRL_SRC_OSC8M |
	// Improve the duty cycle. /
	GCLK_GENCTRL_IDC |
	GCLK_GENCTRL_GENEN |
	GCLK_GENCTRL_RUNSTDBY;

	// Wait for the write to complete /
	while(GCLK->STATUS.bit.SYNCBUSY) {};
		
	// Connect GCLK3 to SERCOM0 /
	GCLK->CLKCTRL.reg =
	GCLK_CLKCTRL_CLKEN |
	GCLK_CLKCTRL_GEN_GCLK3 |
	GCLK_CLKCTRL_ID_SERCOM0_CORE;

	// Wait for the write to complete. /
	while (GCLK->STATUS.bit.SYNCBUSY) {};
	
	delay_init();
	sleepmgr_init();
	
	
	struct port_config pin_conf;
	port_get_config_defaults(&pin_conf);
	

	/* Set buttons as inputs */
	pin_conf.direction  = PORT_PIN_DIR_INPUT;
	pin_conf.input_pull = PORT_PIN_PULL_UP;
	port_pin_set_config(BUTTON1, &pin_conf);
	port_pin_set_config(BUTTON2, &pin_conf);
	port_pin_set_config(BUTTON3, &pin_conf);
	port_pin_set_config(BUTTON4, &pin_conf);
	
	port_pin_set_config(MATRIX, &pin_conf);
	port_pin_set_config(MAX, &pin_conf);
	port_pin_set_config(ALIENS, &pin_conf);
	
	pin_conf.input_pull = PORT_PIN_PULL_DOWN;
	port_pin_set_config(USB_VBUS_PIN, &pin_conf);
	
	
	//Setup Pin Interrupts
	struct extint_chan_conf config_extint_chan;
	extint_chan_get_config_defaults(&config_extint_chan);
	
	//VBUS pin interrupt
	config_extint_chan.gpio_pin            = PIN_PA01A_EIC_EXTINT1;
	config_extint_chan.gpio_pin_mux        = PINMUX_PA01A_EIC_EXTINT1;
	config_extint_chan.gpio_pin_pull       = EXTINT_PULL_DOWN;
	config_extint_chan.filter_input_signal = true;
	config_extint_chan.detection_criteria  = EXTINT_DETECT_BOTH;
	extint_chan_set_config(1, &config_extint_chan);
	extint_register_callback(vbus_handler, 1, EXTINT_CALLBACK_TYPE_DETECT);
	extint_chan_enable_callback(1,EXTINT_CALLBACK_TYPE_DETECT);

	//Button 1 interrupt
	config_extint_chan.gpio_pin            = PIN_PA04A_EIC_EXTINT4;
	config_extint_chan.gpio_pin_mux        = PINMUX_PA04A_EIC_EXTINT4;
	config_extint_chan.gpio_pin_pull       = EXTINT_PULL_UP;
	config_extint_chan.filter_input_signal = true;
	config_extint_chan.detection_criteria  = EXTINT_DETECT_FALLING;
	extint_chan_set_config(4, &config_extint_chan);
	extint_register_callback(button1_handler, 4, EXTINT_CALLBACK_TYPE_DETECT);
	extint_chan_enable_callback(4,EXTINT_CALLBACK_TYPE_DETECT);
	
	//Button 2 interrupt
	config_extint_chan.gpio_pin            = PIN_PA05A_EIC_EXTINT5;
	config_extint_chan.gpio_pin_mux        = PINMUX_PA05A_EIC_EXTINT5;
	config_extint_chan.gpio_pin_pull       = EXTINT_PULL_UP;
	config_extint_chan.filter_input_signal = true;
	config_extint_chan.detection_criteria  = EXTINT_DETECT_FALLING;
	extint_chan_set_config(5, &config_extint_chan);
	extint_register_callback(button2_handler, 5, EXTINT_CALLBACK_TYPE_DETECT);
	extint_chan_enable_callback(5,EXTINT_CALLBACK_TYPE_DETECT);
	
	//Button 3 interrupt
	config_extint_chan.gpio_pin            = PIN_PA06A_EIC_EXTINT6;
	config_extint_chan.gpio_pin_mux        = PINMUX_PA06A_EIC_EXTINT6;
	config_extint_chan.gpio_pin_pull       = EXTINT_PULL_UP;
	config_extint_chan.filter_input_signal = true;
	config_extint_chan.detection_criteria  = EXTINT_DETECT_FALLING;
	extint_chan_set_config(6, &config_extint_chan);
	extint_register_callback(button3_handler, 6, EXTINT_CALLBACK_TYPE_DETECT);
	extint_chan_enable_callback(6,EXTINT_CALLBACK_TYPE_DETECT);
	
	//Button 4 interrupt
	config_extint_chan.gpio_pin            = PIN_PA07A_EIC_EXTINT7;
	config_extint_chan.gpio_pin_mux        = PINMUX_PA07A_EIC_EXTINT7;
	config_extint_chan.gpio_pin_pull       = EXTINT_PULL_UP;
	config_extint_chan.filter_input_signal = true;
	config_extint_chan.detection_criteria  = EXTINT_DETECT_FALLING;
	extint_chan_set_config(7, &config_extint_chan);
	extint_register_callback(button4_handler, 7, EXTINT_CALLBACK_TYPE_DETECT);
	extint_chan_enable_callback(7,EXTINT_CALLBACK_TYPE_DETECT);
	
	timer_init();
	
	configure_usart();
	configure_usart_callbacks();
	
	
	if(port_pin_get_input_level(USB_VBUS_PIN)){
		// Start USB stack to authorize VBus monitoring
		//disable_usart_top();
		udc_start();
		USBPower = true;
		//configure_usart_top_default();
		} else {
		//disable_usart_top();
		//udc_stop();
		configure_usart_top_usb();
		USBPower = false;
	}
	
	GCLK->GENCTRL.bit.RUNSTDBY = 1;  //GCLK run standby
	
	touch_sensors_init();
	
	pwm_init();
	
	//Startup LED Sequence
	uint8_t delaytime = 40;
	led_on(LED1R);
	delay_cycles_ms(delaytime);
	led_on(LED2R);
	delay_cycles_ms(delaytime);
	led_on(LED3R);
	delay_cycles_ms(delaytime);
	led_on(LED4R);
	delay_cycles_ms(delaytime);
	led_off(LED1R);
	led_on(LED1G);
	delay_cycles_ms(delaytime);
	led_off(LED2R);
	led_on(LED2G);
	delay_cycles_ms(delaytime);
	led_off(LED3R);
	led_on(LED3G);
	delay_cycles_ms(delaytime);
	led_off(LED4R);
	led_on(LED4G);
	delay_cycles_ms(delaytime);
	led_off(LED1G);
	led_on(LED1B);
	delay_cycles_ms(delaytime);
	led_off(LED2G);
	led_on(LED2B);
	delay_cycles_ms(delaytime);
	led_off(LED3G);
	led_on(LED3B);
	delay_cycles_ms(delaytime);
	led_off(LED4G);
	led_on(LED4B);
	delay_cycles_ms(delaytime);
	led_off(LED1B);
	delay_cycles_ms(delaytime);
	led_off(LED2B);
	delay_cycles_ms(delaytime);
	led_off(LED3B);
	delay_cycles_ms(delaytime);
	led_off(LED4B);
	
	uart_event = millis;
	
	led_set_resting_color(1,led1color);
	led_set_resting_color(2,led2color);
	led_set_resting_color(3,led3color);
	led_set_resting_color(4,led4color);


	while(1){
		/* --- 4-button chord detection (works standalone, no USB required) ---
		   Short chord (all 4 held CHORD_SHORT_MS..CHORD_LONG_MS, released):
		     cycles effect mode, sends 0x01 V n and 0x01 C 1.
		   Long chord (all 4 held >= CHORD_LONG_MS):
		     fires immediately, resets to mode 0, sends 0x01 V 0 and 0x01 C 2.
		   While any chord is pending, individual button flags are cleared so no
		   HID keystrokes fire. */
		bool all4 = !port_pin_get_input_level(BUTTON1) &&
		            !port_pin_get_input_level(BUTTON2) &&
		            !port_pin_get_input_level(BUTTON3) &&
		            !port_pin_get_input_level(BUTTON4);

		if(all4){
			button1 = button2 = button3 = button4 = false;
			if(chord_state == CHORD_IDLE){
				chord_state = CHORD_PENDING;
				chord_start = millis;
			} else if(chord_state == CHORD_PENDING){
				if((millis - chord_start) >= CHORD_LONG_MS){
					chord_state = CHORD_LONG_FIRED;
					set_effect_mode(0);
					if(main_b_cdc_enable){
						uint8_t evt[3] = {0x01, 'C', 2};
						udi_cdc_write_buf(evt, 3);
					}
				}
			}
		} else {
			if(chord_state == CHORD_PENDING){
				uint32_t held = millis - chord_start;
				if(held >= CHORD_SHORT_MS){
					set_effect_mode((effect_mode + 1) % NUM_EFFECT_MODES);
					if(main_b_cdc_enable){
						uint8_t evt[3] = {0x01, 'C', 1};
						udi_cdc_write_buf(evt, 3);
					}
				}
			}
			chord_state = CHORD_IDLE;
		}

		/* --- Interactive splash on button press during effect modes ---
		   Fires the ~300 ms firmware "color spray" feedback animation when
		   the user pokes a button while a light show is running.  Works on
		   battery without USB.  Doesn't consume the button flag — the USB
		   branch below still gets its turn to fire send_keys() if connected. */
		if(splash_on_press_enabled && effect_mode != 0){
			if(button1)      splash_start(0);
			else if(button2) splash_start(1);
			else if(button3) splash_start(2);
			else if(button4) splash_start(3);
		}

		/* --- LED effect animation --- */
		update_effects();

		/* --- HID key sending (USB connected only) ---
		 * F01/F02 input state machine consumes button1..button4 flags and
		 * decides single/double/triple/long/chord.  Buttons with no modifier
		 * mapping fast-path to immediate single-tap (legacy behavior). */
		if(USBPower && ((millis - last_usb_comms) < 100)){
			input_tick();
			jiggler_tick();
			beep_pattern_tick();
			hid_burst_tick();

			touch_sensors_measure();
			if(p_selfcap_measure_data->measurement_done_touch == 1u){
				p_selfcap_measure_data->measurement_done_touch = 0u;
				slider_state = GET_SELFCAP_SENSOR_STATE(0);
				if(slider_state){
					slider_position = GET_SELFCAP_ROTOR_SLIDER_POSITION(0);
					if(slider_position > last_slider_position + 10){
						last_slider_position = slider_position;
						if(slider_enabled) send_keys(6);
					}
					if(slider_position < last_slider_position - 10){
						last_slider_position = slider_position;
						if(slider_enabled) send_keys(5);
					}
				}
			}
		}

		if(main_b_cdc_enable){
			if(udi_cdc_get_nb_received_data()){
				updateSerialConsole();
			}
		}

		if(!USBPower && ((millis - uart_event) > 1000)){
			standby_sleep();
		}
	}
}


void main_suspend_action(void)
{
	//ui_powerdown();
}

void main_resume_action(void) 
{
	//ui_wakeup();
}

//void main_sof_action(void)
void user_callback_sof_action(void)
{
	wait_for_sof = false;
	last_usb_comms = millis;
}

void main_remotewakeup_enable(void)
{
	//ui_wakeup_enable();
}

void main_remotewakeup_disable(void)
{
	//ui_wakeup_disable();
}

//bool main_kbd_enable(void)
void user_callback_vbus_action(bool b_vbus_high)
{
	main_b_kbd_enable = b_vbus_high;
	if(main_b_kbd_enable){
		disable_usart_top();
		configure_usart_top_default();
	} else {
		disable_usart_top();
		configure_usart_top_usb();
	}
}

void main_kbd_disable(void)
{
	main_b_kbd_enable = false;
}

/*! \brief Configure the RTC timer overflow callback
 *
 */
void rtc_overflow_callback(void)
{
	millis ++;
	
	/* Do something on RTC overflow here */
	if(touch_time_counter == touch_time.measurement_period_ms)
	{
		touch_time.time_to_measure_touch = 1;
		touch_time.current_time_ms = touch_time.current_time_ms +
		touch_time.measurement_period_ms;
		touch_time_counter = 0u;
	}
	else
	{
		touch_time_counter++;
	}
	
}

/*! \brief Configure the RTC timer callback
 *
 */
void configure_rtc_callbacks(void)
{
	/* register callback */
	rtc_count_register_callback(&rtc_instance,
			rtc_overflow_callback, RTC_COUNT_CALLBACK_OVERFLOW);
	/* Enable callback */
	rtc_count_enable_callback(&rtc_instance,RTC_COUNT_CALLBACK_OVERFLOW);
}

/*! \brief Configure the RTC timer count after which interrupts comes
 *
 */
void configure_rtc_count(void)
{
	struct rtc_count_config config_rtc_count;
	rtc_count_get_config_defaults(&config_rtc_count);

	config_rtc_count.prescaler           = RTC_COUNT_PRESCALER_DIV_1;
	config_rtc_count.mode                = RTC_COUNT_MODE_16BIT;
	config_rtc_count.continuously_update = true;
	/* initialize rtc */
	rtc_count_init(&rtc_instance,RTC,&config_rtc_count);

	/* enable rtc */
	rtc_count_enable(&rtc_instance);
}
/*! \brief Initialize timer
 *
 */

/* 16-entry sine-shaped LUT, period 256, range 0..255.  Used by plasma /
 * aurora / juggle effects.  Stored in flash; ~16 bytes total. */
static const uint8_t sin8_lut[16] = {
	128, 177, 219, 246, 255, 246, 219, 177,
	128,  79,  37,  10,   0,  10,  37,  79
};
static uint8_t fwsin8(uint8_t t){ return sin8_lut[(t >> 4) & 0x0F]; }

/* Full-saturation HSV→RGB. h/v both 0-255. */
static void hsv_to_rgb(uint8_t h, uint8_t v, uint8_t *r, uint8_t *g, uint8_t *b){
	uint8_t region = h / 43;
	uint8_t rem    = (h - region * 43) * 6;
	uint8_t q = (uint16_t)v * (255 - rem) >> 8;
	uint8_t t = (uint16_t)v * rem >> 8;
	switch(region){
		case 0: *r = v; *g = t; *b = 0; break;
		case 1: *r = q; *g = v; *b = 0; break;
		case 2: *r = 0; *g = v; *b = t; break;
		case 3: *r = 0; *g = q; *b = v; break;
		case 4: *r = t; *g = 0; *b = v; break;
		default:*r = v; *g = 0; *b = q; break;
	}
}

/* Set effect mode, reset animation state, restore LEDs when going to 0. */
void set_effect_mode(uint8_t mode){
	effect_mode  = mode;
	effect_step  = 0;
	effect_hue   = 0;
	effect_timer = millis;
	/* Clear WLED-effect SEGENV so each ported effect's `if (SEGENV.call == 0)`
	 * one-time-init block fires on its first frame after a mode change. */
	wled_fx_reset_state();
	if(mode == 0){
		led_set_resting_color(1, led1color);
		led_set_resting_color(2, led2color);
		led_set_resting_color(3, led3color);
		led_set_resting_color(4, led4color);
	}
	if(main_b_cdc_enable){
		uint8_t evt[3] = {0x01, 'V', mode};
		udi_cdc_write_buf(evt, 3);
	}
}

/* Advance LED animation one frame; call every main-loop iteration.
   Animates all 4 LEDs.  Bridges that want exclusive control of an LED
   (e.g. Teams using LED4 for the mute indicator) must call set_effect_mode(0)
   while they hold it — see TeamsBridge / FocusBridge in dc29/bridges/. */
static void update_effects(void){
	if(takeover_tick()) return;
	if(splash_tick()) return;
	if(effect_mode == 0) return;
	uint32_t now = millis;

	if(effect_mode == 1){
		/* Rainbow chase: one LED lit at a time, hue cycles across LEDs and advances. */
		if((now - effect_timer) < EFFECT_CHASE_STEP_MS) return;
		effect_timer = now;
		uint8_t off[3] = {0, 0, 0};
		led_set_color(1, off); led_set_color(2, off); led_set_color(3, off); led_set_color(4, off);
		uint8_t r, g, b;
		hsv_to_rgb(effect_hue + effect_step * 64, 200, &r, &g, &b);
		uint8_t color[3] = {r, g, b};
		led_set_color(effect_step + 1, color);
		effect_step = (effect_step + 1) % 4;
		if(effect_step == 0) effect_hue += 16;

	} else if(effect_mode == 2){
		/* Breathe: all 4 LEDs pulse together with slow hue drift. */
		if((now - effect_timer) < EFFECT_BREATHE_STEP_MS) return;
		effect_timer = now;
		uint8_t brightness = (effect_step < 128) ? effect_step * 2 : (255 - effect_step) * 2;
		uint8_t r, g, b;
		hsv_to_rgb(effect_hue, brightness, &r, &g, &b);
		uint8_t color[3] = {r, g, b};
		led_set_color(1, color); led_set_color(2, color); led_set_color(3, color); led_set_color(4, color);
		if(++effect_step == 0) effect_hue += 8;

	} else if(effect_mode == 3){
		/* Color wipe: a single hue rolls across LEDs 1→2→3→4, then wipes back to off, then new hue.
		   effect_step bits: low 2 bits = LED index (0–3); bit 2 = phase (0=fill, 1=wipe). */
		if((now - effect_timer) < EFFECT_WIPE_STEP_MS) return;
		effect_timer = now;
		uint8_t idx = effect_step & 0x03;
		uint8_t phase = (effect_step >> 2) & 0x01;
		uint8_t r, g, b;
		hsv_to_rgb(effect_hue, 220, &r, &g, &b);
		uint8_t color[3] = {r, g, b};
		uint8_t off[3] = {0, 0, 0};
		led_set_color(idx + 1, phase ? off : color);
		effect_step++;
		if((effect_step & 0x07) == 0){
			/* Completed both phases — bump hue for next cycle. */
			effect_hue += 40;
		}

	} else if(effect_mode == 4){
		/* Twinkle: each tick, randomly fade or sparkle one LED.  Soft random
		   feel — values walk via a tiny LFSR, no globals needed beyond effect_step. */
		if((now - effect_timer) < EFFECT_TWINKLE_STEP_MS) return;
		effect_timer = now;
		/* xorshift8 PRNG seeded with effect_step + millis low byte. */
		uint8_t s = effect_step ^ (uint8_t)now;
		s ^= s << 3; s ^= s >> 5; s ^= s << 1;
		effect_step = s ? s : 1;
		uint8_t which = s & 0x03;
		uint8_t bright = (s >> 2) & 0x7F;
		uint8_t r, g, b;
		hsv_to_rgb(effect_hue + which * 16, bright * 2, &r, &g, &b);
		uint8_t color[3] = {r, g, b};
		led_set_color(which + 1, color);
		if((s & 0x1F) == 0) effect_hue += 4;

	} else if(effect_mode == 5){
		/* Gradient slide: 4 LEDs show a smooth hue gradient, scrolling slowly. */
		if((now - effect_timer) < EFFECT_GRADIENT_STEP_MS) return;
		effect_timer = now;
		for(uint8_t i = 0; i < 4; i++){
			uint8_t r, g, b;
			hsv_to_rgb(effect_hue + i * 32, 220, &r, &g, &b);
			uint8_t color[3] = {r, g, b};
			led_set_color(i + 1, color);
		}
		effect_hue += 2;

	} else if(effect_mode == 6){
		/* Theater chase: every Nth LED lit, others off, pattern shifts each tick.
		   With 4 LEDs and stride 2: pattern alternates {1,3} on / {2,4} on. */
		if((now - effect_timer) < EFFECT_THEATER_STEP_MS) return;
		effect_timer = now;
		uint8_t r, g, b;
		hsv_to_rgb(effect_hue, 220, &r, &g, &b);
		uint8_t color[3] = {r, g, b};
		uint8_t off[3] = {0, 0, 0};
		uint8_t phase = effect_step & 0x01;
		led_set_color(1, (0 == phase) ? color : off);
		led_set_color(2, (1 == phase) ? color : off);
		led_set_color(3, (0 == phase) ? color : off);
		led_set_color(4, (1 == phase) ? color : off);
		effect_step++;
		if((effect_step & 0x07) == 0) effect_hue += 24;

	} else if(effect_mode == 7){
		/* Cylon sweep: a single bright LED bounces back and forth across the 4 LEDs.
		   effect_step low 3 bits = position 0..6 mapping to LED indices 0,1,2,3,2,1,0,(wrap). */
		if((now - effect_timer) < EFFECT_CYLON_STEP_MS) return;
		effect_timer = now;
		uint8_t pos = effect_step & 0x07;
		/* Map 0..7 → LED index using bounce: 0,1,2,3,2,1,0,1 → use abs trick. */
		uint8_t led_idx = (pos < 4) ? pos : (6 - pos);
		if(pos == 7) led_idx = 1;  /* fixup the wrap continuation */
		uint8_t r, g, b;
		hsv_to_rgb(effect_hue, 240, &r, &g, &b);
		uint8_t color[3] = {r, g, b};
		uint8_t dim[3]   = {(uint8_t)(r >> 4), (uint8_t)(g >> 4), (uint8_t)(b >> 4)};
		for(uint8_t i = 0; i < 4; i++){
			led_set_color(i + 1, (i == led_idx) ? color : dim);
		}
		effect_step++;
		if((effect_step & 0x3F) == 0) effect_hue += 16;

	} else if(effect_mode == 8){
		/* Particles: 2D physics-driven bouncing balls on the 2x2 LED grid.
		 * Each LED is a corner of the box; brightness = sum of contributions
		 * from each particle, falling off with manhattan distance.  Hue per
		 * particle bumps on every wall bounce (different deltas per axis to
		 * break out of periodicity). */
		if((now - effect_timer) < EFFECT_PARTICLES_STEP_MS) return;
		effect_timer = now;

		if(!particles_initialized) particles_init();

		/* Step physics: advance positions, bounce off all four walls. */
		for(uint8_t p = 0; p < PARTICLE_COUNT; p++){
			Particle *pt = &particles[p];
			pt->x += pt->vx;
			pt->y += pt->vy;
			if(pt->x < 0){
				pt->x = -pt->x; pt->vx = -pt->vx; pt->hue += 37;
			} else if(pt->x > PARTICLE_RANGE){
				pt->x = 2 * PARTICLE_RANGE - pt->x; pt->vx = -pt->vx; pt->hue += 37;
			}
			if(pt->y < 0){
				pt->y = -pt->y; pt->vy = -pt->vy; pt->hue += 23;
			} else if(pt->y > PARTICLE_RANGE){
				pt->y = 2 * PARTICLE_RANGE - pt->y; pt->vy = -pt->vy; pt->hue += 23;
			}
		}

		/* Render each LED-corner with blended particle contributions. */
		for(uint8_t i = 0; i < 4; i++){
			int16_t cx = led_corner_x[i];
			int16_t cy = led_corner_y[i];
			uint16_t accum_brightness = 0;
			uint16_t hue_weighted = 0;
			uint16_t total_weight = 0;
			for(uint8_t p = 0; p < PARTICLE_COUNT; p++){
				int16_t dx = particles[p].x - cx;
				int16_t dy = particles[p].y - cy;
				if(dx < 0) dx = -dx;
				if(dy < 0) dy = -dy;
				int16_t d = dx + dy;            /* manhattan distance, 0..510 */
				if(d < PARTICLE_FALLOFF){
					uint16_t falloff = (uint16_t)(PARTICLE_FALLOFF - d);   /* 0..200 */
					uint16_t contrib = (falloff * particles[p].bright) / PARTICLE_FALLOFF;
					accum_brightness += contrib;
					hue_weighted += particles[p].hue * (falloff >> 3);     /* /8 to fit u16 */
					total_weight += (falloff >> 3);
				}
			}
			if(accum_brightness > 255) accum_brightness = 255;
			uint8_t color[3] = {0, 0, 0};
			if(total_weight > 0 && accum_brightness > 0){
				uint8_t hue = (uint8_t)(hue_weighted / total_weight);
				uint8_t r, g, b;
				hsv_to_rgb(hue, (uint8_t)accum_brightness, &r, &g, &b);
				color[0] = r; color[1] = g; color[2] = b;
			}
			led_set_color(i + 1, color);
		}

	} else if(effect_mode == 9){
		/* Fire: per-LED "heat" drifts toward a target with a random walk.
		   Bottom row (LED3, LED4) targets hotter than top (LED1, LED2),
		   giving a flame-base feel even on a 2x2 grid.  Heat→color follows
		   the classic black→red→orange→yellow→white ramp. */
		if((now - effect_timer) < EFFECT_FIRE_STEP_MS) return;
		effect_timer = now;
		static uint8_t heat[4] = {0, 0, 0, 0};
		static uint8_t fire_lfsr = 0xA5;
		for(uint8_t i = 0; i < 4; i++){
			fire_lfsr ^= fire_lfsr << 3; fire_lfsr ^= fire_lfsr >> 5; fire_lfsr ^= fire_lfsr << 1;
			if(fire_lfsr == 0) fire_lfsr = 1;
			uint8_t target = (i >= 2) ? 200 : 90;          /* bottom row burns hotter */
			int16_t jitter = (int16_t)(fire_lfsr & 0x3F) - 32;
			int16_t h = (int16_t)heat[i] + jitter;
			h += ((int16_t)target - h) >> 2;                /* drift toward target */
			if(h < 0) h = 0;
			if(h > 255) h = 255;
			heat[i] = (uint8_t)h;
			uint8_t r, g, b;
			if(heat[i] < 85){       r = heat[i] * 3;        g = 0;                       b = 0; }
			else if(heat[i] < 170){ r = 255;                g = (heat[i] - 85)  * 3;     b = 0; }
			else {                  r = 255;                g = 255;                     b = (heat[i] - 170) * 3; }
			uint8_t color[3] = {r, g, b};
			led_set_color(i + 1, color);
		}

	} else if(effect_mode == 10){
		/* Lightning: long dark gaps punctuated by short bursts of bright white
		   flashes on random LEDs.  Time-driven state machine — phase_until
		   tracks when the current ON or OFF segment ends. */
		if((now - effect_timer) < EFFECT_LIGHTNING_STEP_MS) return;
		effect_timer = now;
		static uint32_t next_flash_at = 0;
		static uint32_t phase_until   = 0;
		static uint8_t  flashes_left  = 0;
		static uint8_t  flash_mask    = 0;
		static uint8_t  in_flash      = 0;
		static uint8_t  lit_lfsr      = 0x37;

		lit_lfsr ^= lit_lfsr << 3; lit_lfsr ^= lit_lfsr >> 5; lit_lfsr ^= lit_lfsr << 1;
		if(lit_lfsr == 0) lit_lfsr = 1;

		if(next_flash_at == 0 || (int32_t)(now - next_flash_at) > 60000){
			/* First entry, or stale timestamp from a previous run — reseed. */
			next_flash_at = now + 800 + (lit_lfsr & 0x7F) * 8;
		}
		if(flashes_left == 0 && (int32_t)(now - next_flash_at) >= 0){
			flashes_left = 1 + (lit_lfsr & 0x03);   /* 1..4 flashes per burst */
			in_flash = 0;
			phase_until = now;
		}
		if(flashes_left > 0 && (int32_t)(now - phase_until) >= 0){
			in_flash = !in_flash;
			if(in_flash){
				flash_mask = lit_lfsr & 0x0F;
				if(flash_mask == 0) flash_mask = 1 << (lit_lfsr & 0x03);
				phase_until = now + 30 + (lit_lfsr & 0x1F);    /* 30-61 ms ON */
			} else {
				flashes_left--;
				phase_until = now + 50 + (lit_lfsr & 0x3F);     /* 50-113 ms OFF */
				if(flashes_left == 0){
					next_flash_at = now + 800 + (lit_lfsr & 0x7F) * 8;
				}
			}
		}
		uint8_t off[3]   = {0, 0, 0};
		uint8_t white[3] = {255, 255, 255};
		for(uint8_t i = 0; i < 4; i++){
			led_set_color(i + 1, (in_flash && (flash_mask & (1 << i))) ? white : off);
		}

	} else if(effect_mode == 11){
		/* Police strobe: left half (LED1,LED3) red, right half (LED2,LED4) blue,
		   each side double-flashes before handing off to the other.
		   8-step cycle: phases 0,2 = left red ON; 1,3 = all off; 4,6 = right blue ON; 5,7 = all off. */
		if((now - effect_timer) < EFFECT_POLICE_STEP_MS) return;
		effect_timer = now;
		uint8_t phase = effect_step & 0x07;
		uint8_t red[3]  = {255,   0,   0};
		uint8_t blue[3] = {  0,   0, 255};
		uint8_t off[3]  = {  0,   0,   0};
		uint8_t left  = (phase < 4)  && ((phase & 0x01) == 0);
		uint8_t right = (phase >= 4) && ((phase & 0x01) == 0);
		led_set_color(1, left  ? red  : off);
		led_set_color(3, left  ? red  : off);
		led_set_color(2, right ? blue : off);
		led_set_color(4, right ? blue : off);
		effect_step++;

	} else if(effect_mode == 12){
		/* Plasma: each LED's hue is the average of two sines at different
		   frequencies and per-LED phase offsets.  Smooth, never-quite-repeats. */
		if((now - effect_timer) < EFFECT_PLASMA_STEP_MS) return;
		effect_timer = now;
		static const uint8_t plasma_phase[4] = {0, 64, 192, 128};
		uint8_t t = effect_hue;
		for(uint8_t i = 0; i < 4; i++){
			uint8_t a = fwsin8(t + plasma_phase[i]);
			uint8_t b = fwsin8((t << 1) + plasma_phase[i] + 96);
			uint8_t hue = (uint8_t)(((uint16_t)a + b) >> 1);
			uint8_t cr, cg, cb;
			hsv_to_rgb(hue, 230, &cr, &cg, &cb);
			uint8_t color[3] = {cr, cg, cb};
			led_set_color(i + 1, color);
		}
		effect_hue += 3;

	} else if(effect_mode == 13){
		/* Heartbeat: lub-dub red pulse with rest gap.  Brightness profile is
		   driven from elapsed-time-mod-period so it's frame-rate independent. */
		if((now - effect_timer) < EFFECT_HEARTBEAT_STEP_MS) return;
		effect_timer = now;
		uint16_t t = (uint16_t)(now % 1100);
		uint8_t bright;
		if      (t < 120) bright = (uint8_t)(t * 255 / 120);                 /* lub rise */
		else if (t < 220) bright = (uint8_t)(255 - (t - 120) * 200 / 100);    /* lub fall */
		else if (t < 280) bright = (uint8_t)(55  + (t - 220) * 200 / 60);     /* dub rise */
		else if (t < 400) bright = (uint8_t)(255 - (t - 280) * 255 / 120);    /* dub fall */
		else              bright = 0;                                          /* rest */
		uint8_t cr, cg, cb;
		hsv_to_rgb(0, bright, &cr, &cg, &cb);
		uint8_t color[3] = {cr, cg, cb};
		led_set_color(1, color); led_set_color(2, color);
		led_set_color(3, color); led_set_color(4, color);

	} else if(effect_mode == 14){
		/* Aurora: slow drift through cool-spectrum hues (cyan→blue→purple).
		   Each LED has its own phase offset so colors swirl independently. */
		if((now - effect_timer) < EFFECT_AURORA_STEP_MS) return;
		effect_timer = now;
		static const uint8_t aurora_phase[4] = {0, 80, 160, 40};
		for(uint8_t i = 0; i < 4; i++){
			uint8_t s   = fwsin8(effect_hue + aurora_phase[i]);
			uint8_t hue = 100 + (uint8_t)(((uint16_t)s * 110) >> 8);   /* 100..210 */
			uint8_t bright = 160 + (s >> 2);                            /* gentle modulation */
			uint8_t cr, cg, cb;
			hsv_to_rgb(hue, bright, &cr, &cg, &cb);
			uint8_t color[3] = {cr, cg, cb};
			led_set_color(i + 1, color);
		}
		effect_hue += 1;

	} else if(effect_mode == 15){
		/* Confetti: every tick all LEDs fade slightly; with ~50% probability
		   one random LED gets a fresh full-bright random-hue sparkle.  Local
		   RGB shadow because led_set_color doesn't expose the current value. */
		if((now - effect_timer) < EFFECT_CONFETTI_STEP_MS) return;
		effect_timer = now;
		static uint8_t conf[4][3] = {{0,0,0},{0,0,0},{0,0,0},{0,0,0}};
		static uint8_t conf_lfsr = 0xC3;
		conf_lfsr ^= conf_lfsr << 3; conf_lfsr ^= conf_lfsr >> 5; conf_lfsr ^= conf_lfsr << 1;
		if(conf_lfsr == 0) conf_lfsr = 1;
		for(uint8_t i = 0; i < 4; i++){
			conf[i][0] = (uint8_t)(((uint16_t)conf[i][0] * 232) >> 8);
			conf[i][1] = (uint8_t)(((uint16_t)conf[i][1] * 232) >> 8);
			conf[i][2] = (uint8_t)(((uint16_t)conf[i][2] * 232) >> 8);
		}
		if(conf_lfsr & 0x80){
			uint8_t which = conf_lfsr & 0x03;
			uint8_t hue   = effect_hue + (conf_lfsr & 0x7F);
			hsv_to_rgb(hue, 255, &conf[which][0], &conf[which][1], &conf[which][2]);
		}
		for(uint8_t i = 0; i < 4; i++) led_set_color(i + 1, conf[i]);
		effect_hue += 1;

	} else if(effect_mode == 16){
		/* Strobe: rapid full-on / full-off across all LEDs with slow hue cycle. */
		if((now - effect_timer) < EFFECT_STROBE_STEP_MS) return;
		effect_timer = now;
		uint8_t cr, cg, cb;
		hsv_to_rgb(effect_hue, 255, &cr, &cg, &cb);
		uint8_t on[3]  = {cr, cg, cb};
		uint8_t off[3] = {0, 0, 0};
		uint8_t lit = ((effect_step & 0x01) == 0);
		led_set_color(1, lit ? on : off);
		led_set_color(2, lit ? on : off);
		led_set_color(3, lit ? on : off);
		led_set_color(4, lit ? on : off);
		effect_step++;
		if((effect_step & 0x07) == 0) effect_hue += 13;

	} else if(effect_mode == 17){
		/* Meteor: a bright LED travels 1→2→3→4 leaving a fading trail.
		   After exiting LED 4, 4 more ticks of pure decay let the trail fade,
		   then restart with new hue.  effect_step low 3 bits = position 0..7. */
		if((now - effect_timer) < EFFECT_METEOR_STEP_MS) return;
		effect_timer = now;
		static uint8_t mtrail[4] = {0, 0, 0, 0};
		for(uint8_t i = 0; i < 4; i++){
			mtrail[i] = (uint8_t)(((uint16_t)mtrail[i] * 200) >> 8);   /* ~78% decay */
		}
		uint8_t pos = effect_step & 0x07;
		if(pos < 4) mtrail[pos] = 255;
		uint8_t cr, cg, cb;
		hsv_to_rgb(effect_hue, 240, &cr, &cg, &cb);
		for(uint8_t i = 0; i < 4; i++){
			uint8_t color[3] = {
				(uint8_t)(((uint16_t)cr * mtrail[i]) >> 8),
				(uint8_t)(((uint16_t)cg * mtrail[i]) >> 8),
				(uint8_t)(((uint16_t)cb * mtrail[i]) >> 8),
			};
			led_set_color(i + 1, color);
		}
		effect_step++;
		if((effect_step & 0x07) == 0) effect_hue += 32;

	} else if(effect_mode == 18){
		/* Juggle: 3 sine-wave dots with different speeds and base hues, each
		   projected onto the 4-LED line and blended with linear-falloff weight.
		   Inspired by FastLED's juggle() — layered, never-quite-periodic. */
		if((now - effect_timer) < EFFECT_JUGGLE_STEP_MS) return;
		effect_timer = now;
		static const uint8_t dot_speed[3]    = {3, 5, 7};
		static const uint8_t dot_hue_base[3] = {0, 96, 176};
		uint8_t t = effect_hue;
		uint16_t sum_r[4] = {0, 0, 0, 0};
		uint16_t sum_g[4] = {0, 0, 0, 0};
		uint16_t sum_b[4] = {0, 0, 0, 0};
		for(uint8_t d = 0; d < 3; d++){
			uint8_t pos = fwsin8((uint8_t)(t * dot_speed[d]));   /* 0..255 */
			uint8_t p   = (uint8_t)(((uint16_t)pos * 192) >> 8); /* 0..192 */
			uint8_t cr, cg, cb;
			hsv_to_rgb((uint8_t)(dot_hue_base[d] + t), 255, &cr, &cg, &cb);
			for(uint8_t i = 0; i < 4; i++){
				uint8_t led_p = i * 64;
				uint8_t dist  = (p > led_p) ? (p - led_p) : (led_p - p);
				if(dist < 64){
					uint16_t w = 64 - dist;   /* 1..64 */
					sum_r[i] += ((uint16_t)cr * w) >> 6;
					sum_g[i] += ((uint16_t)cg * w) >> 6;
					sum_b[i] += ((uint16_t)cb * w) >> 6;
				}
			}
		}
		for(uint8_t i = 0; i < 4; i++){
			if(sum_r[i] > 255) sum_r[i] = 255;
			if(sum_g[i] > 255) sum_g[i] = 255;
			if(sum_b[i] > 255) sum_b[i] = 255;
			uint8_t color[3] = {(uint8_t)sum_r[i], (uint8_t)sum_g[i], (uint8_t)sum_b[i]};
			led_set_color(i + 1, color);
		}
		effect_hue += 1;

	} else if(effect_mode >= 19 && effect_mode < 19 + WLED_FX_COUNT){
		/* WLED-ported effect modes 19..(19+WLED_FX_COUNT-1).  See wled_fx.c
		 * for the dispatch table.  The shim handles its own ~60 fps gate
		 * and SEGENV.call counter; we just route the mode index. */
		wled_fx_dispatch((uint8_t)(effect_mode - 19));
	}
}

void timer_init(void)
{
	/* Configure and enable RTC */
	configure_rtc_count();

	/* Configure and enable callback */
	configure_rtc_callbacks();

	/* Set Timer Period */

	rtc_count_set_period(&rtc_instance,TIME_PERIOD_1MSEC);
}

void button1_handler(void){
	if(button1 == false){
		if((millis - lastButton1Press) > DEBOUNCE_TIME){
			lastButton1Press = millis;
			button1 = true;
			uart_event = millis;
		}
	}
}

void button2_handler(void){
	if(button2 == false){
		if((millis - lastButton2Press) > DEBOUNCE_TIME){
			lastButton2Press = millis;
			button2 = true;
		}
	}
}

void button3_handler(void){
	if(button3 == false){
		if((millis - lastButton3Press) > DEBOUNCE_TIME){
			lastButton3Press = millis;
			button3 = true;
		}
	}
}

void button4_handler(void){
	if(button4 == false){
		if((millis - lastButton4Press) > DEBOUNCE_TIME){
			lastButton4Press = millis;
			button4 = true;
		}
	}
}

bool main_cdc_enable(uint8_t port)
{
	main_b_cdc_enable = true;
	// Open communication
	//uart_open(port);
	return true;
}

void main_cdc_disable(uint8_t port)
{
	main_b_cdc_enable = false;
	// Close communication
	//uart_close(port);
}

void main_cdc_set_dtr(uint8_t port, bool b_enable)
{
	if (b_enable) {
		// Host terminal has open COM
		//ui_com_open(port);
		}else{
		// Host terminal has close COM
		//ui_com_close(port);
	}
}

void reset_eeprom(void){
	rww_eeprom_emulator_erase_memory();
	rww_eeprom_emulator_init();
	fwversion[0] = FIRMWARE_VERSION;
	rww_eeprom_emulator_write_buffer(EEP_FIRMWARE_VERSION, fwversion, 1);
	uint8_t leddata[3];
	leddata[0] = 255; //full brightness as default
	rww_eeprom_emulator_write_buffer(EEP_LED_BRIGHTNESS, leddata, 1);
	leddata[0] = 255;
	leddata[1] = 0;
	leddata[2] = 0;
	rww_eeprom_emulator_write_buffer(EEP_LED_1_COLOR, leddata, 3);
	leddata[0] = 0;
	leddata[1] = 255;
	leddata[2] = 0;
	rww_eeprom_emulator_write_buffer(EEP_LED_2_COLOR, leddata, 3);
	leddata[0] = 0;
	leddata[1] = 0;
	leddata[2] = 255;
	rww_eeprom_emulator_write_buffer(EEP_LED_3_COLOR, leddata, 3);
	leddata[0] = 127;
	leddata[1] = 127;
	leddata[2] = 127;
	rww_eeprom_emulator_write_buffer(EEP_LED_4_COLOR, leddata, 3);
	leddata[0] = 0;
	leddata[1] = 127;
	leddata[2] = 127;
	rww_eeprom_emulator_write_buffer(EEP_LED_1_PRESSED_COLOR, leddata, 3);
	leddata[0] = 127;
	leddata[1] = 0;
	leddata[2] = 127;
	rww_eeprom_emulator_write_buffer(EEP_LED_2_PRESSED_COLOR, leddata, 3);
	leddata[0] = 127;
	leddata[1] = 127;
	leddata[2] = 0;
	rww_eeprom_emulator_write_buffer(EEP_LED_3_PRESSED_COLOR, leddata, 3);
	leddata[0] = 0;
	leddata[1] = 0;
	leddata[2] = 0;
	rww_eeprom_emulator_write_buffer(EEP_LED_4_PRESSED_COLOR, leddata, 3);
	
	rww_eeprom_emulator_write_buffer(EEP_KEY_MAP, default_keymap, sizeof(default_keymap));

	/* F07 vault — initialize both slots to empty (length 0). */
	uint8_t zero = 0;
	rww_eeprom_emulator_write_buffer(EEP_VAULT_SLOT0_LEN, &zero, 1);
	rww_eeprom_emulator_write_buffer(EEP_VAULT_SLOT1_LEN, &zero, 1);
	/* Settings flags byte — reserved, default 0. */
	rww_eeprom_emulator_write_buffer(EEP_SETTINGS_FLAGS, &zero, 1);

	rww_eeprom_emulator_commit_page_buffer();
}

void reset_user_eeprom(void){ //Reset the LED and keymap data
	uint8_t leddata[3];
	leddata[0] = 255; //full brightness as default
	rww_eeprom_emulator_write_buffer(EEP_LED_BRIGHTNESS, leddata, 1);
	leddata[0] = 255;
	leddata[1] = 0;
	leddata[2] = 0;
	rww_eeprom_emulator_write_buffer(EEP_LED_1_COLOR, leddata, 3);
	leddata[0] = 0;
	leddata[1] = 255;
	leddata[2] = 0;
	rww_eeprom_emulator_write_buffer(EEP_LED_2_COLOR, leddata, 3);
	leddata[0] = 0;
	leddata[1] = 0;
	leddata[2] = 255;
	rww_eeprom_emulator_write_buffer(EEP_LED_3_COLOR, leddata, 3);
	leddata[0] = 127;
	leddata[1] = 127;
	leddata[2] = 127;
	rww_eeprom_emulator_write_buffer(EEP_LED_4_COLOR, leddata, 3);
	leddata[0] = 0;
	leddata[1] = 127;
	leddata[2] = 127;
	rww_eeprom_emulator_write_buffer(EEP_LED_1_PRESSED_COLOR, leddata, 3);
	leddata[0] = 127;
	leddata[1] = 0;
	leddata[2] = 127;
	rww_eeprom_emulator_write_buffer(EEP_LED_2_PRESSED_COLOR, leddata, 3);
	leddata[0] = 127;
	leddata[1] = 127;
	leddata[2] = 0;
	rww_eeprom_emulator_write_buffer(EEP_LED_3_PRESSED_COLOR, leddata, 3);
	leddata[0] = 0;
	leddata[1] = 0;
	leddata[2] = 0;
	rww_eeprom_emulator_write_buffer(EEP_LED_4_PRESSED_COLOR, leddata, 3);
	
	rww_eeprom_emulator_write_buffer(EEP_KEY_MAP, default_keymap, sizeof(default_keymap));
	rww_eeprom_emulator_commit_page_buffer();
	
	rww_eeprom_emulator_read_buffer(EEP_LED_1_COLOR, led1color, 3);
	led_set_resting_color(1,led1color);
	rww_eeprom_emulator_read_buffer(EEP_LED_2_COLOR, led2color, 3);
	led_set_resting_color(2,led2color);
	rww_eeprom_emulator_read_buffer(EEP_LED_3_COLOR, led3color, 3);
	led_set_resting_color(3,led3color);
	rww_eeprom_emulator_read_buffer(EEP_LED_4_COLOR, led4color, 3);
	led_set_resting_color(4,led4color);
}

void read_eeprom(void){
	rww_eeprom_emulator_read_buffer(EEP_LED_1_COLOR, led1color, 3);
	rww_eeprom_emulator_read_buffer(EEP_LED_2_COLOR, led2color, 3);
	rww_eeprom_emulator_read_buffer(EEP_LED_3_COLOR, led3color, 3);
	rww_eeprom_emulator_read_buffer(EEP_LED_4_COLOR, led4color, 3);
	rww_eeprom_emulator_read_buffer(EEP_LED_1_PRESSED_COLOR, led1pressedcolor, 3);
	rww_eeprom_emulator_read_buffer(EEP_LED_2_PRESSED_COLOR, led2pressedcolor, 3);
	rww_eeprom_emulator_read_buffer(EEP_LED_3_PRESSED_COLOR, led3pressedcolor, 3);
	rww_eeprom_emulator_read_buffer(EEP_LED_4_PRESSED_COLOR, led4pressedcolor, 3);

	get_keymap();
	input_init();
	jiggler_init();
}



RAMFUNC void standby_sleep(void)
{
	led_set_color(1,LED_COLOR_OFF);
	led_set_color(2,LED_COLOR_OFF);
	led_set_color(3,LED_COLOR_OFF);
	led_set_color(4,LED_COLOR_OFF);
	
	while(usart_get_job_status(&usart_top_instance, USART_TRANSCEIVER_TX) == STATUS_BUSY);
	while(usart_get_job_status(&usart_right_instance, USART_TRANSCEIVER_TX) == STATUS_BUSY);
	while(usart_get_job_status(&usart_bottom_instance, USART_TRANSCEIVER_TX) == STATUS_BUSY);
	while(usart_get_job_status(&usart_left_instance, USART_TRANSCEIVER_TX) == STATUS_BUSY);
	while(usart_get_job_status(&usart_usba_instance, USART_TRANSCEIVER_TX) == STATUS_BUSY);
	while(usart_get_job_status(&usart_usbc_instance, USART_TRANSCEIVER_TX) == STATUS_BUSY);
	
	tcc_stop_counter(&tcc2_instance); //Disable buzzer

	//Slow down RTC interrupts
	rtc_count_set_period(&rtc_instance,TIME_PERIOD_500MSEC);

	sleepmgr_sleep(SLEEPMGR_STANDBY);
	
	rtc_count_set_period(&rtc_instance,TIME_PERIOD_1MSEC);
	rtc_count_set_count(&rtc_instance,0);

	millis += 500; //Account for time while sleeping
	
	send_heartbeats();
}

void usba_pin_interrupt_handler(void){
	uart_event = millis;
}

/**
 * \mainpage ASF USB Device HID Keyboard
 *
 * \section intro Introduction
 * This example shows how to implement a USB Device HID Keyboard
 * on Atmel MCU with USB module.
 * The application note AVR4904 http://ww1.microchip.com/downloads/en/appnotes/doc8446.pdf
 * provides information about this implementation.
 *
 * \section startup Startup
 * The example uses the buttons or sensors available on the board
 * to simulate a standard keyboard.
 * After loading firmware, connect the board (EVKxx,Xplain,...) to the USB Host.
 * When connected to a USB host system this application provides a keyboard application
 * in the Unix/Mac/Windows operating systems.
 * This example uses the native HID driver for these operating systems.
 *
 * \copydoc UI
 *
 * \section example About example
 *
 * The example uses the following module groups:
 * - Basic modules:
 *   Startup, board, clock, interrupt, power management
 * - USB Device stack and HID modules:
 *   <br>services/usb/
 *   <br>services/usb/udc/
 *   <br>services/usb/class/hid/
 *   <br>services/usb/class/hid/keyboard/
 * - Specific implementation:
 *    - main.c,
 *      <br>initializes clock
 *      <br>initializes interrupt
 *      <br>manages UI
 *    - specific implementation for each target "./examples/product_board/":
 *       - conf_foo.h   configuration of each module
 *       - ui.c        implement of user's interface (buttons, leds)
 */
