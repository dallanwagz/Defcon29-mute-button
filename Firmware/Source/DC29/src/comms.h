/*
 * comms.h
 *
 *  Author: compukidmike
 */ 


#ifndef COMMS_H_
#define COMMS_H_

#include "main.h"


void usart_top_read_callback(struct usart_module *const usart_module);
void usart_top_write_callback(struct usart_module *const usart_module);
void usart_right_read_callback(struct usart_module *const usart_module);
void usart_right_write_callback(struct usart_module *const usart_module);
void usart_bottom_read_callback(struct usart_module *const usart_module);
void usart_bottom_write_callback(struct usart_module *const usart_module);
void usart_left_read_callback(struct usart_module *const usart_module);
void usart_left_write_callback(struct usart_module *const usart_module);
void usart_usba_read_callback(struct usart_module *const usart_module);
void usart_usba_write_callback(struct usart_module *const usart_module);
void usart_usbc_read_callback(struct usart_module *const usart_module);
void usart_usbc_write_callback(struct usart_module *const usart_module);

void usart_top_error_callback(struct usart_module *const usart_module);
void usart_right_error_callback(struct usart_module *const usart_module);
void usart_bottom_error_callback(struct usart_module *const usart_module);
void usart_left_error_callback(struct usart_module *const usart_module);
void usart_usbc_error_callback(struct usart_module *const usart_module);
void usart_usba_error_callback(struct usart_module *const usart_module);



void configure_usart(void);
void configure_usart_top_default(void);
void configure_usart_top_usb(void);
void disable_usart_top(void);
void configure_usart_callbacks(void);

void send_heartbeats(void);

volatile uint32_t uart_event;


//! [module_inst]
struct usart_module usart_top_instance;
struct usart_module usart_right_instance;
struct usart_module usart_bottom_instance;
struct usart_module usart_left_instance;
struct usart_module usart_usba_instance;
struct usart_module usart_usbc_instance;
//! [module_inst]

//! [rx_buffer_var]
#define RX_BUFFER_LENGTH   10

#define RX_HEARTBEAT_INTERVAL 500
#define RX_HEARTBEAT_TIMEOUT 1000

#endif /* COMMS_H_ */