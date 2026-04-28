/*
 * games.c
 *
 * Stripped to stubs for macropad-only firmware variant.
 * Original Simon-says game and inter-badge tunes removed to reclaim flash.
 *
 *  Author: compukidmike
 */

#include "games.h"

bool new_connection = false;
bool old_connection = false;
bool simon_start_tune = false;
bool game_over_tune = false;
bool challenge_section_finish = false;
bool new_signal_share = false;

/* Globals referenced by comms.c USART RX handler. Kept as no-op storage so
   the inter-badge protocol stubs link cleanly without enabling games. */
uint8_t  gamestate = 0;
bool     badge_count_ready = false;
uint16_t incoming_badge_number = 0;
uint8_t  incoming_badge_button = 0;
bool     incoming_button_press_ready = false;
bool     incoming_sequence_packet = false;

void run_games(void){
}

void simon_game_over(uint16_t score){
	(void)score;
}

void new_connection_tune(void){
}

void play_sounds(void){
}
