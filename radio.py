
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
                    radio_player, radio_stations, menu)

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
        "enable_levels": state.levels_enabled
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


#########################################################
# CALLBACKS
#########################################################

def exit_left_menu(ui,player,audio_stream):
    logger.info("Exiting left menu")
    ui.state.left_encoder.device.when_rotated_clockwise          = lambda: change_station(ui,player,audio_stream)
    ui.state.left_encoder.device.when_rotated_counter_clockwise  = lambda: change_station(ui,player,audio_stream)
    ui.state.radio_state.toggle_left_menu()

def exit_right_menu(ui,audio):
    logger.info("Exiting right menu")
    ui.state.right_encoder.device.when_rotated_clockwise         = lambda: ui.state.update("volume",audio.vol_up(2))
    ui.state.right_encoder.device.when_rotated_counter_clockwise = lambda: ui.state.update("volume",audio.vol_down(2))
    ui.state.radio_state.toggle_right_menu()

def update_menu_state(state, encoder_position):
    '''
    Button pressed, select menu and update state
    '''
    logging.info("Menu selected: %s", encoder_position.name)
    menu=None
    selected_encoder=None
    menu_active=False
    change_encoder_function=False

    # TODO: Add in timer to cancel menu if no activity after X seconds
    # periodictimer...
    # need to change rotate lambdas
    if encoder_position == encoder.EncoderPosition.LEFT:
        menu = state.lm
        selected_encoder = state.left_encoder
        if state.radio_state.playing.is_active:
            state.radio_state.toggle_left_menu()
            change_encoder_function=True
        menu_active = state.radio_state.left_menu_activated.is_active

    elif encoder_position == encoder.EncoderPosition.RIGHT:
        menu = state.rm
        selected_encoder = state.right_encoder
        if state.radio_state.playing.is_active:
            state.radio_state.toggle_right_menu()
            change_encoder_function=True
        menu_active = state.radio_state.right_menu_activated.is_active

    if change_encoder_function:
        selected_encoder.device.when_rotated_clockwise         = lambda: state.update("current_menu_item",menu.get_next_menu())
        selected_encoder.device.when_rotated_counter_clockwise = lambda: state.update("current_menu_item",menu.get_prev_menu())
        state.current_menu_item=menu.get_first_menu_item()
        logging.info("Menu currently selected: %s", state.current_menu_item)
    elif menu_active:
        logging.info("Running action for: %s", state.current_menu_item)
        menu.run_action(state.current_menu_item)

def play_new_station(ui,player,audio):
    logging.info("New Station selected...changing audio")
    # Cancel timer
    ui.state.station_timer.event.set()
    # Back to playing
    ui.state.radio_state.toggle_select_station()

    # start playing state.current_station
    player.stop()
    player.play(ui.state.station_name)
    audio_stream.start_stream()
    ui.state.dab_type = ""
    ui.state.last_pad_message = ""
    # ui.draw_interface(reset_scroll=True)
    logger.info(f'Now playing {ui.state.station_name}')
    time.sleep(0.9)

def change_station(ui,player,audio):
    if not ui.state.radio_state.station_selection.is_active:
        # Set up timeout timer which changes station once stopped selecting
        ui.state.station_timer = menu.PeriodicTask(interval=4, callback=lambda:play_new_station(ui,player,audio))
        ui.state.station_timer.run()
        # Change into select_station state
        ui.state.radio_state.toggle_select_station()
        logger.info("Start changing station..")

    if ui.state.radio_state.station_selection.is_active:
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
    ''' Callback to update the UI with a message from the player during scanning '''
    ui.clear_screen()
    ui.reset_station_name_scroll()
    ui.draw_station_name(msg)  
    ui.draw_ensemble(sub_msg)    
    ui.update()

def initiate_scan(ui,player,audio):
    ui.state.radio_state.toggle_scanning_for_stations()
    was_playing = player.playing
    # Scan will reload station list
    player.scan(ui, ui_msg_callback=update_msg)
    player.play(was_playing)
    # Wait for dabble/eti-cmdline to restart
    ui.state.radio_state.toggle_scanning_for_stations()
    exit_right_menu(ui,audio)
    time.sleep(2)


#########################################################
# MAIN
#########################################################

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)
logger.info("Dabble Radio initialising")

ui = None
# TODO: Get rid of keyboard stuff
kb = keyboard.Keyboard()

try:
    ui=lcd_ui.LCDUI(
        base_font_path="noto/NotoSans_SemiCondensed", 
        station_font_style="Bold",
        station_font_size=20
    )
except exceptions.FontException:
    logging.fatal("Cannot load fonts")
    shutdown(ui=ui, kb=kb, left_encoder=left_encoder)
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
ui.state.radio_state = menu.RadioMachine()

# Set up encoders and buttons
ui.state.left_encoder  = encoder.Encoder(
        device_type=encoder.EncoderTypes.FERMION_EC11_BREAKOUT, 
        pin_a=17, pin_b=27, pin_c=23, 
        button_press_callback=lambda:update_menu_state(ui.state, encoder.EncoderPosition.LEFT))

ui.state.right_encoder = encoder.Encoder(
        device_type=encoder.EncoderTypes.FERMION_EC11_BREAKOUT, 
        pin_a=24, pin_b=25, pin_c=22, 
        button_press_callback=lambda:update_menu_state(ui.state, encoder.EncoderPosition.RIGHT))

# Set up menus and callbacks
ui.state.lm = menu.Menu()
ui.state.current_menu_item=""
ui.state.lm.add_menu("Graphic Equaliser").action(lambda: ui.state.update("visualiser","graphic_equaliser"))
ui.state.lm.add_menu("Waveform").action(lambda: ui.state.update("visualiser","waveform"))
ui.state.lm.add_menu("Levels").action(lambda: ui.state.update("levels_enabled",not ui.state.levels_enabled))
ui.state.lm.add_menu("Visualiser").action(lambda: ui.state.update("visualiser_enabled",not ui.state.visualiser_enabled))
ui.state.lm.add_menu("Exit").action(lambda: exit_left_menu(ui,player,audio_stream) )

ui.state.rm = menu.Menu()
ui.state.rm.add_menu("Scan Channels").action(lambda: initiate_scan(ui,player,audio))
ui.state.rm.add_menu("Exit").action(lambda: exit_right_menu(ui,audio) )

logger.info("Setting colour of left encoder")
ui.state.left_encoder.set_colour_by_rgb(ui.state.left_led_rgb)

logger.info(f'Begin playing {ui.state.station_name}')
player.play(ui.state.station_name)
ui.state.station_name = player.playing
ui.state.ensemble     = player.ensemble
ui.update()
time.sleep(5)

logger.info("Audio processing initialising")
audio = audio_processing.AudioProcessing(frame_chunk_size=512)
# Set volume
audio.set_volume(ui.state.volume)
logger.info(f'Volume set to {audio.volume}')
audio_stream = audio.start()

# Set encoder twiddling callbacks
ui.state.left_encoder.device.when_rotated_clockwise          = lambda: change_station(ui,player,audio_stream)
ui.state.left_encoder.device.when_rotated_counter_clockwise  = lambda: change_station(ui,player,audio_stream)
ui.state.right_encoder.device.when_rotated_clockwise         = lambda: ui.state.update("volume",audio.vol_up(2))
ui.state.right_encoder.device.when_rotated_counter_clockwise = lambda: ui.state.update("volume",audio.vol_down(2))

# Lets start the party....
logger.info("Radio main loop starting")
audio_stream.start_stream()
ui.reset_station_name_scroll()

try:
    while True:
        # Get audio data before anything else
        if audio.stream.is_active():
            if audio.get_sample():
                ui.state.signal = audio.signal
                if ui.state.levels_enabled:
                    (ui.state.peak_l, ui.state.peak_r) = audio.get_peaks()

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
                ui.state.last_pad_message = updates.get('pad_label').value
                logger.info(f"PAD msg: \"{ui.state.last_pad_message}\"")

            elif updates.is_updated('media_fmt'):
                ui.state.audio_format = updates.get('media_fmt').value
                logger.info(f"Audio format: \"{ui.state.audio_format}\"")

            elif updates.is_updated('prog_type'):
                ui.state.genre = updates.get('prog_type').value
                logger.info(f"Genre: \"{ui.state.genre}\"")

        # Draw the UI
        # Other states are managing the UI so dont complete
        if ui.state.radio_state.playing.is_active or \
           ui.state.radio_state.left_menu_activated.is_active or \
           ui.state.radio_state.right_menu_activated.is_active:

            # Scroll station name
            ui.scroll_station_name()
            audio_stream.start_stream()
            ui.draw_interface()

        elif ui.state.radio_state.station_selection.is_active:
            # Don't scroll while stations being selected.
            ui.draw_interface()

        ## and .... breathe
        time.sleep(0.005)
    

except (KeyboardInterrupt,SystemExit):
    logging.info("Shutting down")
    shutdown(ui=ui, kb=kb, player=player)
    logger.info("Radio Hard Stop")
