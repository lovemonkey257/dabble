
'''

Build:
    in venv in pyvenv.cfg set "include-system-site-packages = true"
    also need apt-get install python3-alsaaudio
'''

import json
import logging
import time
import sys
from enum import Enum
from pathlib import Path

from dabble import (audio_processing, encoder, exceptions, keyboard, lcd_ui,
                    radio_player, radio_stations, menus)

config_path = Path("dabble_radio.json")

def load_state(state:lcd_ui.UIState):
    logger.info(f'Loading saved state from {config_path}')
    config=dict()
    if config_path.exists():
        with open(config_path, "r") as f:
            config = json.load(f)
            state.volume = config['volume']
            state.station_name = config['station_name']
            state.ensemble = config['ensemble']
            state.visualiser_enabled = config['enable_visualiser']
            state.visualiser = config['visualiser']
            state.levels_enabled = config['enable_levels']
            state.pulse_left_led_encoder = config['pulse_left_led_encoder']
            state.pulse_right_led_encoder = config['pulse_right_led_encoder']
            state.station_enabled = config['station_enabled'] if 'station_enabled' in config else True
    else:
        state.station_name = "Magic Radio"
    return config

def save_state(state:lcd_ui.UIState):
    logger.info("Saving state")
    config = {
        "station_name": state.station_name,
        "ensemble": state.ensemble,
        "volume": state.volume,
        "pulse_left_led_encoder": state.pulse_left_led_encoder,
        "pulse_right_led_encoder": state.pulse_right_led_encoder,
        "enable_visualiser": state.visualiser_enabled,
        "visualiser": state.visualiser,
        "enable_levels": state.levels_enabled,
        "station_enabled": state.station_enabled
    }
    with open(config_path, "w") as f:
        f.write(json.dumps(config))

def shutdown(ui=None,kb=None,player=None):
    if ui:
        save_state(ui.state)
        ui.clear_screen()
        ui.reset_station_name_scroll()
        ui.draw_station_name("Bye!")
        ui.update()
        
    if player:
        player.stop()
        time.sleep(1)
        
    if ui.state.left_encoder:
        ui.state.left_encoder.set_colour_by_rgb((0,0,0))
    if kb:
        kb.reset()

    if ui:
        ui.clear_screen()
        ui.update()
        ui.disp.display_off()
        ui.disp.set_backlight(0)


#########################################################
# CALLBACKS
#########################################################
def exit_menu(encoder_position, ui, player, audio_processor):
    '''
    User has selected exit from menu...
    '''
    if ui.state.radio_state.playing.is_active:
        # Debounce sometimes triggers exit twice (or more) so ignore
        return

    ui.state.menu_timer.terminate()

    if ui.state.radio_state.left_menu_activated.is_active:
        ui.state.radio_state.left_menu_timeout()

    elif ui.state.radio_state.right_menu_activated.is_active:
        ui.state.radio_state.right_menu_timeout()

    elif ui.state.radio_state.selecting_a_menu.is_active:
        # Can only exit if menu being selected or menus active (but nothing selected yet)
        # exit_menu can be called multiple times if button debounce misses double press
        if encoder_position == encoder.EncoderPosition.LEFT:
            logger.info("Exiting left menu")
            ui.state.left_encoder.device.when_rotated_clockwise          = lambda: change_station(ui,player,audio_processor)
            ui.state.left_encoder.device.when_rotated_counter_clockwise  = lambda: change_station(ui,player,audio_processor)
            ui.state.radio_state.exit_left_menu()

        elif encoder_position == encoder.EncoderPosition.RIGHT:
            logger.info("Exiting right menu")
            ui.state.right_encoder.device.when_rotated_clockwise         = lambda: ui.state.update("volume",audio_processor.vol_up(2))
            ui.state.right_encoder.device.when_rotated_counter_clockwise = lambda: ui.state.update("volume",audio_processor.vol_down(2))
            ui.state.radio_state.exit_right_menu()
    else:
        logging.warning("Exit called. Wrong state: %s", ui.state.radio_state.current_state.id)

def next_menu(state, curr_menu):
    ''' Get next menu item, reseting timeout '''
    state.current_menu_item = curr_menu.get_next_menu()
    state.menu_timer.reset()

def prev_menu(state, curr_menu):
    ''' Get prev menu item, reseting timeout '''
    state.current_menu_item = curr_menu.get_prev_menu()
    state.menu_timer.reset()

def activate_or_run_menu(state, encoder_position):
    '''
    Button pressed to bring up menu
    Change encoders so we now select menus and run actions
    '''
    logging.info("State: %s, Prev State: %s, Button pressed: %s", state.radio_state.current_state.id, state.radio_state.previous_state, encoder_position.name)
    curr_menu               = None
    selected_encoder        = None
    change_encoder_function = False

    if encoder_position == encoder.EncoderPosition.LEFT:
        curr_menu = state.lm
        selected_encoder = state.left_encoder
        if state.radio_state.playing.is_active:
            # If playing then menu is activated
            state.radio_state.activate_left_menu()
            change_encoder_function=True
        elif state.radio_state.left_menu_activated.is_active:
            # Menu activated and now we're doing something with menus
            state.radio_state.left_menu_selection()

    elif encoder_position == encoder.EncoderPosition.RIGHT:
        curr_menu = state.rm
        selected_encoder = state.right_encoder
        if state.radio_state.playing.is_active:
            state.radio_state.activate_right_menu()
            change_encoder_function=True
        elif state.radio_state.right_menu_activated.is_active:
            state.radio_state.right_menu_selection()

    if change_encoder_function:
        selected_encoder.device.when_rotated_clockwise         = lambda: prev_menu(state, curr_menu)
        selected_encoder.device.when_rotated_counter_clockwise = lambda: next_menu(state, curr_menu)
        state.current_menu_item=curr_menu.get_first_menu_item()
        logging.info("Menu currently selected: %s", state.current_menu_item)
        state.menu_timer = menus.PeriodicTask(interval=8, callback=lambda:exit_menu(encoder_position, ui, player, audio_processor))
        state.menu_timer.run()

    elif state.radio_state.selecting_a_menu.is_active:
        state.menu_timer.reset()
        curr_menu.run_action(state.current_menu_item)

def play_new_station(ui,player,audio_processor):
    '''
    New station selected, now play it
    '''
    logging.info("New Station selected...changing audio")
    # Cancel timer
    ui.state.station_timer.terminate()
    # Back to playing
    ui.state.radio_state.toggle_select_station()

    # Pause streaming ...
    audio_processor.stream.stop_stream()

    # start playing state.current_station
    player.stop()
    player.play(ui.state.station_name)

    # Resume playing
    audio_processor.stream.start_stream()

    ui.state.dab_type = ""
    ui.state.last_pad_message = ""
    logger.info(f'Now playing {ui.state.station_name}')

def change_station(ui,player,audio_processor):
    '''
    Use is moving dial to change station
    If dial isn't moved timer is triggered to play that station
    '''
    if ui.state.radio_state.playing.is_active or \
       not ui.state.radio_state.left_menu_activated.is_active and \
       not ui.state.radio_state.right_menu_activated.is_active and \
       not ui.state.radio_state.selecting_a_station.is_active:
        # If we're entering station selection ..
        # Change into select_station state
        ui.state.radio_state.toggle_select_station()
        # Set up timeout timer which changes station once stopped selecting
        ui.state.station_timer = menus.PeriodicTask(interval=4, callback=lambda:play_new_station(ui,player,audio_processor))
        ui.state.station_timer.run()
        logger.info("Start changing station..")

    if ui.state.radio_state.selecting_a_station.is_active:
        # still twiddling so reset timeout
        ui.state.station_timer.reset()
        # Get index of station in list and correct given current station
        left_encoder_value = ui.state.left_encoder.device.steps
        station_number = left_encoder_value + player.radio_stations.station_index(player.playing)

        # Get the new station name and details
        (ui.state.station_name, station_details)=player.radio_stations.select_station(station_number)
        ui.state.ensemble     = station_details['ensemble']
        ui.state.current_msg  = lcd_ui.MessageState.STATION
        logger.info(f'New station {station_number} {ui.state.station_name}/{ui.state.ensemble} selected')
        ui.reset_station_name_scroll()

def update_msg(msg, sub_msg:str=""):
    ''' 
    Callback to update the UI with a message from the player during scanning 
    '''
    ui.clear_screen()
    ui.reset_station_name_scroll()
    ui.draw_station_name(msg)  
    ui.draw_ensemble(sub_msg)    
    ui.update()

def initiate_scan(ui,player,audio_processor):
    '''
    Initiate a scan
    '''
    ui.state.radio_state.toggle_scan()
    was_playing = player.playing
    # Scan will reload station list
    player.scan(ui, ui_msg_callback=update_msg)
    player.play(was_playing)
    # Wait for dabble/eti-cmdline to restart
    ui.state.radio_state.toggle_scan()
    exit_right_menu(ui,audio_processor)
    time.sleep(2)


#########################################################
# MAIN
#########################################################

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(module)s %(threadName)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)
logger.info("Dabble Radio initialising")

ui = None
try:
    ui=lcd_ui.LCDUI(
        base_font_path="noto/NotoSans_SemiCondensed", 
        station_font_style="SemiBold",
        station_font_size=20,
        menu_font_style="SemiBold",
        menu_font_size=18,
        menu_font_sml_size=16
    )
except exceptions.FontException:
    logging.fatal("Cannot load fonts")
    shutdown(ui=ui, left_encoder=left_encoder)
    sys.exit()

# Display startup message
ui.show_startup()

# Initialise stations and player
logger.info("Loading radio stations")
stations=radio_stations.RadioStations()

logger.info("Initialising player")
player=radio_player.RadioPlayer(radio_stations=stations)

# Load stations. If none then initiate scan
try:
    stations.load_stations()
except exceptions.NoRadioStations as e:
    player.scan(ui_msg_callback=update_msg)

# Load defaults
logger.info("Loading defaults")
current_config = load_state(ui.state)

# Set up state machine
ui.state.radio_state = menus.RadioMachine()

# Set up encoders and buttons
ui.state.left_encoder  = encoder.Encoder(
        device_type=encoder.EncoderTypes.FERMION_EC11_BREAKOUT, 
        pin_a=17, pin_b=27, pin_c=23, 
        bounce_time=0.1,
        button_press_callback=lambda:activate_or_run_menu(ui.state, encoder.EncoderPosition.LEFT))

ui.state.right_encoder = encoder.Encoder(
        device_type=encoder.EncoderTypes.FERMION_EC11_BREAKOUT, 
        pin_a=24, pin_b=25, pin_c=22, 
        bounce_time=0.1,
        button_press_callback=lambda:activate_or_run_menu(ui.state, encoder.EncoderPosition.RIGHT))

# Set up menus and callbacks
ui.state.lm = menus.Menu()
ui.state.current_menu_item=""
ui.state.lm.add_menu("Equaliser/Full", init_state="On" if ui.state.visualiser=="graphic_equaliser" else "off")\
        .action(lambda: ui.state.update("visualiser","graphic_equaliser"))\
        .change_state(lambda: "On" if ui.state.visualiser=="graphic_equaliser" else "Off")

ui.state.lm.add_menu("Equaliser/Bars", init_state="On" if ui.state.visualiser=="graphic_equaliser_bars" else "off")\
        .action(lambda: ui.state.update("visualiser","graphic_equaliser_bars"))\
        .change_state(lambda: "On" if ui.state.visualiser=="graphic_equaliser_bars" else "Off")

ui.state.lm.add_menu("Waveform", init_state="on" if ui.state.visualiser=="waveform" else "Off")\
        .action(lambda: ui.state.update("visualiser","waveform"))\
        .change_state(lambda: "On" if ui.state.visualiser=="waveform" else "Off")

ui.state.lm.add_menu("Levels", init_state="On" if ui.state.levels_enabled else "Off")\
        .action(lambda: ui.state.update("levels_enabled",not ui.state.levels_enabled))\
        .change_state(lambda: "On" if ui.state.levels_enabled else "Off")

ui.state.lm.add_menu("Visualiser", init_state="On" if ui.state.visualiser_enabled else "Off")\
        .action(lambda: ui.state.update("visualiser_enabled",not ui.state.visualiser_enabled))\
        .change_state(lambda: "On" if ui.state.visualiser_enabled else "Off")

ui.state.lm.add_menu("Station Name", init_state="On" if ui.state.station_enabled else "Off")\
        .action(lambda: ui.state.update("station_enabled",not ui.state.station_enabled))\
        .change_state(lambda: "On" if ui.state.station_enabled else "Off")

ui.state.lm.add_menu("Exit").action(lambda: exit_menu(encoder.EncoderPosition.LEFT, ui, player, audio_processor))

ui.state.rm = menus.Menu()
ui.state.rm.add_menu("Scan Channels").action(lambda: initiate_scan(ui,player,audio_processor))
ui.state.rm.add_menu("Exit").action(lambda: exit_menu(encoder.EncoderPosition.RIGHT, ui, player, audio_processor))

logger.info("Setting colour of left encoder")
ui.state.left_encoder.set_colour_by_rgb(ui.state.left_led_rgb)

logger.info(f'Begin playing {ui.state.station_name}')
player.play(ui.state.station_name)
ui.state.station_name = player.playing
ui.state.ensemble     = player.ensemble
ui.update()

logger.info("Audio processing initialising")
audio_processor = audio_processing.AudioProcessing(frame_chunk_size=512)
# Set volume
audio_processor.set_volume(ui.state.volume)
logger.info(f'Volume set to {audio_processor.volume}')

# Start audio processing
audio_processor.start()
audio_processor.stream.start_stream()

# Set encoder twiddling callbacks
ui.state.left_encoder.device.when_rotated_clockwise          = lambda: change_station(ui,player,audio_processor)
ui.state.left_encoder.device.when_rotated_counter_clockwise  = lambda: change_station(ui,player,audio_processor)
ui.state.right_encoder.device.when_rotated_clockwise         = lambda: ui.state.update("volume",audio_processor.vol_up(2))
ui.state.right_encoder.device.when_rotated_counter_clockwise = lambda: ui.state.update("volume",audio_processor.vol_down(2))

# Lets start the party....
logger.info("Radio main loop starting")
ui.reset_station_name_scroll()

try:
    while True:
        # Get audio data before anything else
        if audio_processor.stream.is_active():
            if audio_processor.get_sample():
                ui.state.signal = audio_processor.signal
                (ui.state.peak_l, ui.state.peak_r) = audio_processor.get_peaks()

        if ui.state.left_encoder.device_type.PIMORONI_RGB_BREAKOUT:
            if ui.state.pulse_left_led_encoder:
                ui.state.left_encoder.set_colour_by_value(ui.state.peak_l)       
        if ui.state.right_encoder.device_type.PIMORONI_RGB_BREAKOUT:
            if ui.state.pulse_right_led_encoder:
                ui.state.left_encoder.set_colour_by_value(ui.state.peak_r)       
     
        if updates := player.dablin_log_parser.updates():
            if updates.is_updated('dab_type'):
                ui.state.dab_type=updates.get('dab_type').value
                logger.info(f"DAB type: {ui.state.dab_type}")

            elif updates.is_updated('pad_label'):
                #ui.state.last_pad_message = updates.get('pad_label').value
                pad = updates.get('pad_label').value
                if ui.state.last_pad_message == "":
                    ui.state.last_pad_message = pad
                else:
                    ui.state.next_pad_message = pad
                logger.info(f"PAD msg: \"{pad}\"")

            elif updates.is_updated('media_fmt'):
                ui.state.audio_format = updates.get('media_fmt').value
                logger.info(f"Audio format: \"{ui.state.audio_format}\"")

            elif updates.is_updated('prog_type'):
                ui.state.genre = updates.get('prog_type').value
                logger.info(f"Genre: \"{ui.state.genre}\"")

        # Only scroll if we are in certain states
        if ui.state.radio_state.playing.is_active or \
           ui.state.radio_state.left_menu_activated.is_active or \
           ui.state.radio_state.right_menu_activated.is_active:

            # Scroll station name
            ui.scroll_station_name()
            # Ensure we are streaming audio to visualisers
            audio_processor.stream.start_stream()

        # Draw the UI
        ui.draw_interface()

        ## and .... breathe
        #time.sleep(0.001)
    

except (KeyboardInterrupt,SystemExit):
    audio_processor.stream.close()
    audio_processor.p.terminate()

    logging.info("Shutting down")
    shutdown(ui=ui,player=player)
    logger.info("Radio Hard Stop")
