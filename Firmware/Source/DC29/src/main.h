/**
 * \file
 *
 * \brief Declaration of main function used by HID keyboard example
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

#ifndef _MAIN_H_
#define _MAIN_H_

#include "asf.h"
#include "pwm.h"
#include "comms.h"



#define DEBUG 0 //debug code no longer fits in the available flash :(

#define FIRMWARE_VERSION 2 //Only change if EEPROM layout changes


#define BUTTON1 PIN_PA04
#define BUTTON2 PIN_PA05
#define BUTTON3 PIN_PA06
#define BUTTON4 PIN_PA07

#define LED1RPIN PIN_PA22
#define LED1GPIN PIN_PA10
#define LED1BPIN PIN_PB08
#define LED2RPIN PIN_PA23
#define LED2GPIN PIN_PA11
#define LED2BPIN PIN_PB09
#define LED3RPIN PIN_PA20
#define LED3GPIN PIN_PA18
#define LED3BPIN PIN_PB10
#define LED4RPIN PIN_PA21
#define LED4GPIN PIN_PA19
#define LED4BPIN PIN_PB11

#define BUZZER PIN_PB22

#define MATRIX PIN_PA28
#define MAX PIN_PA27
#define ALIENS PIN_PB02

#define LED_COLOR_OFF (uint8_t[]){0,0,0}
#define LED_COLOR_RED (uint8_t[]){255,0,0}
#define LED_COLOR_GREEN (uint8_t[]){0,255,0}
#define LED_COLOR_BLUE (uint8_t[]){0,0,255}
#define LED_COLOR_YELLOW (uint8_t[]){127,127,0}

//EEPROM Location Offsets
#define	EEP_FIRMWARE_VERSION 0 //1 BYTE

#define EEP_LED_BRIGHTNESS 1 //1 BYTE
#define EEP_LED_1_COLOR 2 //3 BYTES
#define EEP_LED_2_COLOR 5 //3 BYTES
#define EEP_LED_3_COLOR 8 //3 BYTES
#define EEP_LED_4_COLOR 11 //3 BYTES
#define EEP_LED_1_PRESSED_COLOR 14 //3 BYTES
#define EEP_LED_2_PRESSED_COLOR 17 //3 BYTES
#define EEP_LED_3_PRESSED_COLOR 20 //3 BYTES
#define EEP_LED_4_PRESSED_COLOR 23 //3 BYTES

#define EEP_KEY_MAP 26 //MAX 234 BYTES (EEPROM is limited to 260 bytes)


static const uint8_t default_keymap[21] = { 
	21, //length
	250,3,16, //key1 - ctrl-shift-m
	251,240,32, //key2 - Mute
	252,2,51,2,39, //key3 - :)
	253,5,16, //key4 - ctrl+alt+m
	254,240,64,255,240,128 //slider Vol+/-
};
/*! \brief Called by HID interface
 * Callback running when USB Host enable keyboard interface
 *
 * \retval true if keyboard startup is ok
 */
bool main_kbd_enable(void);
//void user_callback_vbus_action(bool b_vbus_high);

/*! \brief Called by HID interface
 * Callback running when USB Host disable keyboard interface
 */
void main_kbd_disable(void);

/*! \brief Called when a start of frame is received on USB line
 */
void main_sof_action(void);
//void user_callback_sof_action(void);

/*! \brief Enters the application in low power mode
 * Callback called when USB host sets USB line in suspend state
 */
void main_suspend_action(void);

/*! \brief Called by UDD when the USB line exit of suspend state
 */
void main_resume_action(void);

/*! \brief Called by UDC when USB Host request to enable remote wakeup
 */
void main_remotewakeup_enable(void);

/*! \brief Called by UDC when USB Host request to disable remote wakeup
 */
void main_remotewakeup_disable(void);

/*! \brief Initialize timer
 *
 */
void timer_init( void );

/*! \brief RTC timer overflow callback
 *
 */
void rtc_overflow_callback(void);

/*! \brief Configure the RTC timer callback
 *
 */
void configure_rtc_callbacks(void);

/*! \brief Configure the RTC timer count after which interrupts comes
 *
 */
void configure_rtc_count(void);

#define NUM_EFFECT_MODES 9   /* 0=off, 1=rainbow-chase, 2=breathe, 3=wipe, 4=twinkle, 5=gradient, 6=theater, 7=cylon, 8=particles */

void set_effect_mode(uint8_t mode);

void vbus_handler(void);

void button1_handler(void);
void button2_handler(void);
void button3_handler(void);
void button4_handler(void);

bool main_cdc_enable(uint8_t port);
void main_cdc_disable(uint8_t port);
void main_cdc_set_dtr(uint8_t port, bool b_enable);

void reset_eeprom(void);
void reset_user_eeprom(void);
void read_eeprom(void);
RAMFUNC void standby_sleep(void);

void usba_pin_interrupt_handler(void);

#endif // _MAIN_H_
