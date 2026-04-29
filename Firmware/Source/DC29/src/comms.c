/*
 * comms.c
 *
 *  Author: compukidmike
 */
#include <asf.h>
#include <stdio.h>
#include "comms.h"


extern volatile uint32_t millis;
extern bool USBPower;

volatile uint32_t uart_event;

struct usart_module usart_top_instance;
struct usart_module usart_right_instance;
struct usart_module usart_bottom_instance;
struct usart_module usart_left_instance;
struct usart_module usart_usba_instance;
struct usart_module usart_usbc_instance;


volatile uint8_t rx_top_buffer[RX_BUFFER_LENGTH];
volatile uint8_t rx_right_buffer[RX_BUFFER_LENGTH];
volatile uint8_t rx_bottom_buffer[RX_BUFFER_LENGTH];
volatile uint8_t rx_left_buffer[RX_BUFFER_LENGTH];
volatile uint8_t rx_usba_buffer[RX_BUFFER_LENGTH];
volatile uint8_t rx_usbc_buffer[RX_BUFFER_LENGTH];

volatile uint8_t rx_top_buffer_length = 0;
volatile uint8_t rx_right_buffer_length = 0;
volatile uint8_t rx_bottom_buffer_length = 0;
volatile uint8_t rx_left_buffer_length = 0;
volatile uint8_t rx_usba_buffer_length = 0;
volatile uint8_t rx_usbc_buffer_length = 0;

volatile uint8_t rx_top_buffer_read_index = 0;
volatile uint8_t rx_right_buffer_read_index = 0;
volatile uint8_t rx_bottom_buffer_read_index = 0;
volatile uint8_t rx_left_buffer_read_index = 0;
volatile uint8_t rx_usba_buffer_read_index = 0;
volatile uint8_t rx_usbc_buffer_read_index = 0;

volatile uint8_t rx_top_buffer_write_index = 0;
volatile uint8_t rx_right_buffer_write_index = 0;
volatile uint8_t rx_bottom_buffer_write_index = 0;
volatile uint8_t rx_left_buffer_write_index = 0;
volatile uint8_t rx_usba_buffer_write_index = 0;
volatile uint8_t rx_usbc_buffer_write_index = 0;

volatile uint16_t rx_top_temp_buffer = 0;
volatile uint16_t rx_right_temp_buffer = 0;
volatile uint16_t rx_bottom_temp_buffer = 0;
volatile uint16_t rx_left_temp_buffer = 0;
volatile uint16_t rx_usba_temp_buffer = 0;
volatile uint16_t rx_usbc_temp_buffer = 0;

volatile uint16_t usart_top_last_msg_time = 0;
volatile uint16_t usart_right_last_msg_time = 0;
volatile uint16_t usart_bottom_last_msg_time = 0;
volatile uint16_t usart_left_last_msg_time = 0;
volatile uint16_t usart_usba_last_msg_time = 0;
volatile uint16_t usart_usbc_last_msg_time = 0;

uint8_t heartbeat_message[5] = {29,29,29,29,0};


void usart_top_read_callback(struct usart_module *const usart_module)
{
	usart_top_last_msg_time = millis;
	if(rx_top_buffer_length == RX_BUFFER_LENGTH){
		return;
	}
	rx_top_buffer[rx_top_buffer_write_index] = rx_top_temp_buffer;
	rx_top_buffer_write_index ++;
	if(rx_top_buffer_write_index == RX_BUFFER_LENGTH) rx_top_buffer_write_index = 0;
	rx_top_buffer_length ++;

	uint32_t try_time = millis;
	while(usart_read_job(&usart_top_instance, (uint16_t *)&rx_top_temp_buffer)){
		if(millis - try_time > 100) break;
	}

	uart_event = millis;
}

void usart_top_write_callback(struct usart_module *const usart_module)
{
}

void usart_right_read_callback(struct usart_module *const usart_module)
{
	usart_right_last_msg_time = millis;
	if(rx_right_buffer_length == RX_BUFFER_LENGTH){
		return;
	}
	rx_right_buffer[rx_right_buffer_write_index] = rx_right_temp_buffer;
	rx_right_buffer_write_index ++;
	if(rx_right_buffer_write_index == RX_BUFFER_LENGTH) rx_right_buffer_write_index = 0;
	rx_right_buffer_length ++;
	uint32_t try_time = millis;
	while(usart_read_job(&usart_right_instance, (uint16_t *)&rx_right_temp_buffer)){
		if(millis - try_time > 100) break;
	}
	uart_event = millis;
}

void usart_right_write_callback(struct usart_module *const usart_module)
{
}

void usart_bottom_read_callback(struct usart_module *const usart_module)
{
	usart_bottom_last_msg_time = millis;
	if(rx_bottom_buffer_length == RX_BUFFER_LENGTH){
		return;
	}
	rx_bottom_buffer[rx_bottom_buffer_write_index] = rx_bottom_temp_buffer;
	rx_bottom_buffer_write_index ++;
	if(rx_bottom_buffer_write_index == RX_BUFFER_LENGTH) rx_bottom_buffer_write_index = 0;
	rx_bottom_buffer_length ++;
	uint32_t try_time = millis;
	while(usart_read_job(&usart_bottom_instance, (uint16_t *)&rx_bottom_temp_buffer)){
		if(millis - try_time > 100) break;
	}
	uart_event = millis;
}

void usart_bottom_write_callback(struct usart_module *const usart_module)
{
}

void usart_left_read_callback(struct usart_module *const usart_module)
{
	usart_left_last_msg_time = millis;
	if(rx_left_buffer_length == RX_BUFFER_LENGTH){
		return;
	}
	rx_left_buffer[rx_left_buffer_write_index] = rx_left_temp_buffer;
	rx_left_buffer_write_index ++;
	if(rx_left_buffer_write_index == RX_BUFFER_LENGTH) rx_left_buffer_write_index = 0;
	rx_left_buffer_length ++;
	uint32_t try_time = millis;
	while(usart_read_job(&usart_left_instance, (uint16_t *)&rx_left_temp_buffer)){
		if(millis - try_time > 100) break;
	}
	uart_event = millis;
}

void usart_left_write_callback(struct usart_module *const usart_module)
{
}

void usart_usba_read_callback(struct usart_module *const usart_module)
{
	usart_usba_last_msg_time = millis;
	if(rx_usba_buffer_length == RX_BUFFER_LENGTH){
		return;
	}
	rx_usba_buffer[rx_usba_buffer_write_index] = rx_usba_temp_buffer;
	rx_usba_buffer_write_index ++;
	if(rx_usba_buffer_write_index == RX_BUFFER_LENGTH) rx_usba_buffer_write_index = 0;
	rx_usba_buffer_length ++;
	uint32_t try_time = millis;
	while(usart_read_job(&usart_usba_instance, (uint16_t *)&rx_usba_temp_buffer)){
		if(millis - try_time > 100) break;
	}
	uart_event = millis;
}

void usart_usba_write_callback(struct usart_module *const usart_module)
{
}

void usart_usbc_read_callback(struct usart_module *const usart_module)
{
	usart_usbc_last_msg_time = millis;
	if(rx_usbc_buffer_length == RX_BUFFER_LENGTH){
		return;
	}
	rx_usbc_buffer[rx_usbc_buffer_write_index] = rx_usbc_temp_buffer;
	rx_usbc_buffer_write_index ++;
	if(rx_usbc_buffer_write_index == RX_BUFFER_LENGTH) rx_usbc_buffer_write_index = 0;
	rx_usbc_buffer_length ++;
	uint32_t try_time = millis;
	while(usart_read_job(&usart_usbc_instance, (uint16_t *)&rx_usbc_temp_buffer)){
		if(millis - try_time > 100) break;
	}
	uart_event = millis;
}

void usart_usbc_write_callback(struct usart_module *const usart_module)
{
}

void usart_top_error_callback(struct usart_module *const usart_module){
	uart_event = millis;
}
void usart_right_error_callback(struct usart_module *const usart_module){
	uart_event = millis;
}
void usart_bottom_error_callback(struct usart_module *const usart_module){
	uart_event = millis;
}
void usart_left_error_callback(struct usart_module *const usart_module){
	uart_event = millis;
}
void usart_usbc_error_callback(struct usart_module *const usart_module){
	uart_event = millis;
}
void usart_usba_error_callback(struct usart_module *const usart_module){
	uart_event = millis;
}

void configure_usart(void)
{
	struct usart_config config_top_usart;
	struct usart_config config_right_usart;
	struct usart_config config_bottom_usart;
	struct usart_config config_left_usart;
	struct usart_config config_usba_usart;
	usart_get_config_defaults(&config_top_usart);
	usart_get_config_defaults(&config_right_usart);
	usart_get_config_defaults(&config_bottom_usart);
	usart_get_config_defaults(&config_left_usart);
	usart_get_config_defaults(&config_usba_usart);

struct port_config pin_conf;
port_get_config_defaults(&pin_conf);
pin_conf.direction  = PORT_PIN_DIR_INPUT;
	pin_conf.input_pull = PORT_PIN_PULL_UP;

		//Top Connector (TX5/RX5/SERCOM5)
		config_top_usart.baudrate    = 38400;
		config_top_usart.mux_setting = USART_RX_3_TX_2_XCK_3;
		config_top_usart.pinmux_pad0 = PINMUX_PB22D_SERCOM5_PAD2;
		config_top_usart.pinmux_pad1 = PINMUX_PB23D_SERCOM5_PAD3;
		config_top_usart.pinmux_pad2 = PINMUX_UNUSED;
		config_top_usart.pinmux_pad3 = PINMUX_UNUSED;
		config_top_usart.run_in_standby = true;
		config_top_usart.generator_source = GCLK_GENERATOR_3;

		while (usart_init(&usart_top_instance, SERCOM5, &config_top_usart) != STATUS_OK) {
		}
		PORT->Group[1].PINCFG[23].bit.PULLEN = 1;
		PORT->Group[1].OUTCLR.reg = 1 << 23;
		usart_enable(&usart_top_instance);

		//Right Connector (TX1/RX1/SERCOM1)
		config_right_usart.baudrate    = 38400;
		config_right_usart.mux_setting = USART_RX_1_TX_0_XCK_1;
		config_right_usart.pinmux_pad0 = PINMUX_PA16C_SERCOM1_PAD0;
		config_right_usart.pinmux_pad1 = PINMUX_PA17C_SERCOM1_PAD1;
		config_right_usart.pinmux_pad2 = PINMUX_UNUSED;
		config_right_usart.pinmux_pad3 = PINMUX_UNUSED;
		config_right_usart.run_in_standby = true;
		config_right_usart.generator_source = GCLK_GENERATOR_3;

		while (usart_init(&usart_right_instance, SERCOM1, &config_right_usart) != STATUS_OK) {
		}
		PORT->Group[0].PINCFG[17].bit.PULLEN = 1;
		PORT->Group[0].OUTCLR.reg = 1 << 17;
		usart_enable(&usart_right_instance);

		//Bottom Connector (TX2/RX2/SERCOM2)
		config_bottom_usart.baudrate    = 38400;
		config_bottom_usart.mux_setting = USART_RX_1_TX_0_XCK_1;
		config_bottom_usart.pinmux_pad0 = PINMUX_PA12C_SERCOM2_PAD0;
		config_bottom_usart.pinmux_pad1 = PINMUX_PA13C_SERCOM2_PAD1;
		config_bottom_usart.pinmux_pad2 = PINMUX_UNUSED;
		config_bottom_usart.pinmux_pad3 = PINMUX_UNUSED;
		config_bottom_usart.run_in_standby = true;
		config_bottom_usart.generator_source = GCLK_GENERATOR_3;

		while (usart_init(&usart_bottom_instance, SERCOM2, &config_bottom_usart) != STATUS_OK) {
		}
		PORT->Group[0].PINCFG[13].bit.PULLEN = 1;
		PORT->Group[0].OUTCLR.reg = 1 << 13;
		usart_enable(&usart_bottom_instance);

		//Left Connector (TX0/RX0/SERCOM0)
		config_left_usart.baudrate    = 38400;
		config_left_usart.mux_setting = USART_RX_1_TX_0_XCK_1;
		config_left_usart.pinmux_pad0 = PINMUX_PA08C_SERCOM0_PAD0;
		config_left_usart.pinmux_pad1 = PINMUX_PA09C_SERCOM0_PAD1;
		config_left_usart.pinmux_pad2 = PINMUX_UNUSED;
		config_left_usart.pinmux_pad3 = PINMUX_UNUSED;
		config_left_usart.run_in_standby = true;
		config_left_usart.generator_source = GCLK_GENERATOR_3;

		while (usart_init(&usart_left_instance, SERCOM0, &config_left_usart) != STATUS_OK) {
		}
		PORT->Group[0].PINCFG[9].bit.PULLEN = 1;
		PORT->Group[0].OUTCLR.reg = 1 << 9;
		usart_enable(&usart_left_instance);


		//USB-A Connector (TX4/RX4/SERCOM4)
		config_usba_usart.baudrate    = 38400;
		config_usba_usart.mux_setting = USART_RX_3_TX_2_XCK_3;
		config_usba_usart.pinmux_pad0 = PINMUX_PA14D_SERCOM4_PAD2;
		config_usba_usart.pinmux_pad1 = PINMUX_PA15D_SERCOM4_PAD3;
		config_usba_usart.pinmux_pad2 = PINMUX_UNUSED;
		config_usba_usart.pinmux_pad3 = PINMUX_UNUSED;
		config_usba_usart.run_in_standby = true;
		config_usba_usart.generator_source = GCLK_GENERATOR_3;

		while (usart_init(&usart_usba_instance, SERCOM4, &config_usba_usart) != STATUS_OK) {
		}
		PORT->Group[0].PINCFG[15].bit.PULLEN = 1;
		PORT->Group[0].OUTCLR.reg = 1 << 15;
		usart_enable(&usart_usba_instance);
}

void configure_usart_top_default(void)
{
}

void configure_usart_top_usb(void)
{
	struct usart_config config_usbc_usart;
	usart_get_config_defaults(&config_usbc_usart);

		//Top Connector (TX3/RX3/SERCOM3)
		config_usbc_usart.baudrate    = 38400;
		config_usbc_usart.mux_setting = USART_RX_3_TX_2_XCK_3;
		config_usbc_usart.pinmux_pad0 = PINMUX_PA24C_SERCOM3_PAD2;
		config_usbc_usart.pinmux_pad1 = PINMUX_PA25C_SERCOM3_PAD3;
		config_usbc_usart.pinmux_pad2 = PINMUX_UNUSED;
		config_usbc_usart.pinmux_pad3 = PINMUX_UNUSED;
		config_usbc_usart.run_in_standby = true;
		config_usbc_usart.generator_source = GCLK_GENERATOR_3;

		while (usart_init(&usart_usbc_instance, SERCOM3, &config_usbc_usart) != STATUS_OK) {
		}
		PORT->Group[0].PINCFG[25].bit.PULLEN = 1;
		PORT->Group[0].OUTCLR.reg = 1 << 25;
		usart_enable(&usart_usbc_instance);
		usart_register_callback(&usart_usbc_instance, usart_usbc_write_callback, USART_CALLBACK_BUFFER_TRANSMITTED);
		usart_register_callback(&usart_usbc_instance, usart_usbc_read_callback, USART_CALLBACK_BUFFER_RECEIVED);
		usart_enable_callback(&usart_usbc_instance, USART_CALLBACK_BUFFER_TRANSMITTED);
		usart_enable_callback(&usart_usbc_instance, USART_CALLBACK_BUFFER_RECEIVED);
		usart_read_buffer_job(&usart_usbc_instance,(uint8_t *)rx_usbc_buffer,1);
		usart_register_callback(&usart_usbc_instance, usart_usbc_error_callback, USART_CALLBACK_ERROR);
		usart_enable_callback(&usart_usbc_instance, USART_CALLBACK_ERROR);
}

void disable_usart_top(void){
	usart_disable(&usart_usbc_instance);
}

void configure_usart_callbacks(void)
{
	usart_register_callback(&usart_top_instance, usart_top_write_callback, USART_CALLBACK_BUFFER_TRANSMITTED);
	usart_register_callback(&usart_top_instance, usart_top_read_callback, USART_CALLBACK_BUFFER_RECEIVED);
	usart_register_callback(&usart_right_instance, usart_right_write_callback, USART_CALLBACK_BUFFER_TRANSMITTED);
	usart_register_callback(&usart_right_instance, usart_right_read_callback, USART_CALLBACK_BUFFER_RECEIVED);
	usart_register_callback(&usart_bottom_instance, usart_bottom_write_callback, USART_CALLBACK_BUFFER_TRANSMITTED);
	usart_register_callback(&usart_bottom_instance, usart_bottom_read_callback, USART_CALLBACK_BUFFER_RECEIVED);
	usart_register_callback(&usart_left_instance, usart_left_write_callback, USART_CALLBACK_BUFFER_TRANSMITTED);
	usart_register_callback(&usart_left_instance, usart_left_read_callback, USART_CALLBACK_BUFFER_RECEIVED);
	usart_register_callback(&usart_usba_instance, usart_usba_write_callback, USART_CALLBACK_BUFFER_TRANSMITTED);
	usart_register_callback(&usart_usba_instance, usart_usba_read_callback, USART_CALLBACK_BUFFER_RECEIVED);

	usart_register_callback(&usart_top_instance, usart_usbc_error_callback, USART_CALLBACK_ERROR);
	usart_register_callback(&usart_right_instance, usart_usbc_error_callback, USART_CALLBACK_ERROR);
	usart_register_callback(&usart_bottom_instance, usart_usbc_error_callback, USART_CALLBACK_ERROR);
	usart_register_callback(&usart_left_instance, usart_usbc_error_callback, USART_CALLBACK_ERROR);
	usart_register_callback(&usart_usba_instance, usart_usbc_error_callback, USART_CALLBACK_ERROR);

	usart_enable_callback(&usart_top_instance, USART_CALLBACK_BUFFER_TRANSMITTED);
	usart_enable_callback(&usart_top_instance, USART_CALLBACK_BUFFER_RECEIVED);
	usart_enable_callback(&usart_right_instance, USART_CALLBACK_BUFFER_TRANSMITTED);
	usart_enable_callback(&usart_right_instance, USART_CALLBACK_BUFFER_RECEIVED);
	usart_enable_callback(&usart_bottom_instance, USART_CALLBACK_BUFFER_TRANSMITTED);
	usart_enable_callback(&usart_bottom_instance, USART_CALLBACK_BUFFER_RECEIVED);
	usart_enable_callback(&usart_left_instance, USART_CALLBACK_BUFFER_TRANSMITTED);
	usart_enable_callback(&usart_left_instance, USART_CALLBACK_BUFFER_RECEIVED);
	usart_enable_callback(&usart_usba_instance, USART_CALLBACK_BUFFER_TRANSMITTED);
	usart_enable_callback(&usart_usba_instance, USART_CALLBACK_BUFFER_RECEIVED);

	usart_enable_callback(&usart_top_instance, USART_CALLBACK_ERROR);
	usart_enable_callback(&usart_right_instance, USART_CALLBACK_ERROR);
	usart_enable_callback(&usart_bottom_instance, USART_CALLBACK_ERROR);
	usart_enable_callback(&usart_left_instance, USART_CALLBACK_ERROR);
	usart_enable_callback(&usart_usba_instance, USART_CALLBACK_ERROR);

	usart_read_buffer_job(&usart_top_instance,(uint8_t *)rx_top_buffer,1);
	usart_read_buffer_job(&usart_right_instance,(uint8_t *)rx_right_buffer,1);
	usart_read_buffer_job(&usart_bottom_instance,(uint8_t *)rx_bottom_buffer,1);
	usart_read_buffer_job(&usart_left_instance,(uint8_t *)rx_left_buffer,1);
	usart_read_buffer_job(&usart_usba_instance,(uint8_t *)rx_usba_buffer,1);
}

void send_heartbeats(void){
	usart_write_buffer_job(&usart_top_instance, heartbeat_message, sizeof(heartbeat_message));
	usart_write_buffer_job(&usart_right_instance, heartbeat_message, sizeof(heartbeat_message));
	usart_write_buffer_job(&usart_bottom_instance, heartbeat_message, sizeof(heartbeat_message));
	usart_write_buffer_job(&usart_left_instance, heartbeat_message, sizeof(heartbeat_message));
	usart_write_buffer_job(&usart_usbc_instance, heartbeat_message, sizeof(heartbeat_message));
	usart_write_buffer_job(&usart_usba_instance, heartbeat_message, sizeof(heartbeat_message));
}
