
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
                    radio_player, radio_stations)

config_path = Path("dabble_radio.json")

class EncoderState(Enum):
    SCANNING=0
    CHANGE_VOLUME=1
    CHANGE_STATION=2

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

def shutdown(ui=None,kb=None,player=None,left_encoder=None):
    if player:
        player.stop()
        time.sleep(1)
    if ui:
        save_state(ui.state)
        ui.clear_screen()
        ui.reset_station_name_scroll()
        ui.draw_station_name("Shutting down")
        ui.update()
        ui.clear_screen()
        ui.update()
    if left_encoder:
        left_encoder.set_colour_by_rgb((0,0,0))
    if kb:
        kb.reset()

def update_msg(msg, sub_msg:str=""):
    ''' Callback to update the UI with a message from the player during scanning '''
    ui.clear_screen()
    ui.reset_station_name_scroll()
    ui.draw_station_name(msg)  
    ui.draw_ensemble(sub_msg)    
    ui.update()


###
# MAIN
###

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)
logger.info("Dabble Radio initialising")

kb           = keyboard.Keyboard()
left_encoder = encoder.Encoder()
ui=None

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

logger.info("Setting colour of left encoder")
left_encoder.set_colour_by_rgb(ui.state.left_led_rgb)

logger.info(f'Begin playing {ui.state.station_name}')
player.play(ui.state.station_name)
ui.state.station_name = player.playing
ui.state.ensemble = player.ensemble
ui.update()
time.sleep(5)

logger.info("Audio processing initialising")
audio = audio_processing.AudioProcessing(frame_chunk_size=512)
audio_stream = audio.start()

# Time user started twiddling
left_encoder_start_rotate_time=0 # time.time()

# True if we are to change channel (after twiddling)
changing_station=False
scroll_station_name=False
new_station_name="?"
new_ensemble="?"
left_encoder_value=0
mode=EncoderState.CHANGE_STATION
last_left_encoder_value = 0

audio.set_volume(ui.state.volume)
logger.info(f'Volume set to {audio.volume}')

logger.info("Radio main loop starting")
try:
    while True:

        # Get audio data before anything else
        if audio.stream.is_active():
            if audio.get_sample():
                ui.state.signal = audio.signal
                if ui.state.levels_enabled:
                    (ui.state.peak_l, ui.state.peak_r) = audio.get_peaks()

        ##
        ## Test code to emulate two encoders
        ## TODO: Get more encoders!!
        ##
        k = kb.get_key()
        if k=="v":
            logging.info("Volume mode")
            mode=EncoderState.CHANGE_VOLUME
        elif k=="s":
            logging.info("Station mode")
            mode=EncoderState.CHANGE_STATION
        elif k=="S":
            logging.info("Scanning initiated")
            mode=EncoderState.SCANNING
        elif k=="V":
            logging.info("Toggling visualiser")
            ui.state.visualiser_enabled = not ui.state.visualiser_enabled
        elif k=="l":
            logging.info("Toggling levels")
            ui.state.levels_enabled = not ui.state.levels_enabled
        elif k=="w":
            ui.state.visualiser_enabled = True
            ui.state.visualiser = lcd_ui.GraphicState.WAVEFORM
            logging.info("Waveform graphic selected: %s", ui.state.visualiser)
        elif k=="g":
            ui.state.visualiser_enabled = True
            ui.state.visualiser = lcd_ui.GraphicState.GRAPHIC_EQUALISER
            logging.info("Graphic Equaliser graphic selected: %s", ui.state.visualiser)

        # Get current encoder value
        if left_encoder.ioe.get_interrupt():
            left_encoder_value = left_encoder.ioe.read_rotary_encoder(1)
            left_encoder.ioe.clear_interrupt()

        # Given state do something
        if mode==EncoderState.SCANNING:
            was_playing = player.playing
            # Scan will reload station list
            player.scan(ui_msg_callback=update_msg)
            mode=EncoderState.CHANGE_STATION
            player.play(was_playing)
            # Wait for dabble/eti-cmdline to restart
            time.sleep(2)

        elif mode==EncoderState.CHANGE_STATION:
            # Changing station? Knob being twiddled?
            if left_encoder_value != last_left_encoder_value:
                # Get index of station in list and correct given current station
                station_number = left_encoder_value + player.radio_stations.station_index(player.playing)

                # Get the new station name and details
                (new_station_name, new_station_details)=player.radio_stations.select_station(station_number)
                new_ensemble = new_station_details['ensemble']
                ui.state.station_name = new_station_name
                ui.state.ensemble = new_ensemble
                ui.state.current_msg = 0
                logger.info(f'New station {new_station_name} {new_ensemble} selected')
                ui.reset_station_name_scroll()

                # Record when we started twiddling the knob and indicate station is changing
                left_encoder_start_rotate_time = time.time()
                changing_station=True

        elif mode==EncoderState.CHANGE_VOLUME:
            if left_encoder_value != last_left_encoder_value:
                # Turning left?
                if left_encoder_value<last_left_encoder_value:
                    ui.state.volume = audio.vol_down(2)
                # Turning right?
                elif left_encoder_value>last_left_encoder_value:
                    ui.state.volume = audio.vol_up(2)

        # scroll text once stopped twiddling know and changed channel?
        left_encoder_stopped_twiddling = time.time() - left_encoder_start_rotate_time > 2

        # Change station!
        if left_encoder_stopped_twiddling and changing_station:
            player.stop()
            player.play(new_station_name)
            ui.state.station_name = new_station_name
            ui.state.dab_type = ""
            ui.state.last_pad_message = ""
            ui.draw_interface(reset_scroll=True)
            logger.info(f'Now playing {new_station_name}')
            time.sleep(0.9)
            changing_station=False
        elif not changing_station:
            # Scroll station name
            ui.scroll_station_name()
            # Make sure audio stream is playing
            audio_stream.start_stream()
            # Set UI state
            ui.state.station_name = player.playing
            ui.state.ensemble = player.ensemble


        if ui.state.pulse_left_led_encoder:
            knob_colour = (ui.state.peak_l + ui.state.peak_r) / 2 
            left_encoder.set_colour_by_value(knob_colour)       
     
        updates = player.dablin_log_parser.updates()
        if updates:
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

        # Record last encoder value
        last_left_encoder_value = left_encoder_value

        # Draw the UI
        ui.draw_interface()

        ## and .... breathe
        time.sleep(0.005)
    

except (KeyboardInterrupt,SystemExit):
    shutdown(ui=ui, kb=kb, player=player, left_encoder=left_encoder)
    logger.info("Radio Hard Stop")
