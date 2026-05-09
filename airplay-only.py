
'''

Build:
    in venv in pyvenv.cfg set "include-system-site-packages = true"
    also need apt-get install python3-alsaaudio
'''

import json
import logging
import time
import sys
import threading
from enum import Enum
from pathlib import Path
import paho.mqtt.client as mqtt
from systemd.journal import JournalHandler

from dabble import (audio_processing, encoder, exceptions, keyboard, lcd_ui,
                    radio_player, radio_stations, menus, state, callbacks)

def shutdown(ui=None,kb=None,player=None, mqttc=None):
    if mqttc:
        mqttc.loop_stop()

    if ui:
        ui.clear_screen()
        ui.reset_station_name_scroll()
        ui.draw_station_name("Bye!")
        ui.update()
        
    if player:
        player.stop()
        time.sleep(1)
        
    if kb:
        kb.reset()

    if ui:
        if ui.state.left_encoder:
            ui.state.left_encoder.set_colour_by_rgb((0,0,0))
        ui.clear_screen()
        ui.update()
        ui.disp.display_off()
        ui.disp.set_backlight(0)

#########################################################
# MAIN
#########################################################

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(module)s %(threadName)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)
journald_handler = JournalHandler()
logger.addHandler(journald_handler)

logger.info("Dabble Radio initialising")

# Init LCD display and sensible theme defaults
ui = None
try:
    ui=lcd_ui.LCDUI()
    ui.init_fonts()
except exceptions.FontException:
    logging.fatal("Cannot load fonts")
    shutdown(mqttc=mqttc)
    sys.exit()

# Set up state machine
# Default values as we're testing
player=None
ui.state.radio_state = menus.RadioMachine()

# Load theme and init fonts
try:
    if theme := ui.state.theme.load_theme('default'):
        ui.state.theme = theme
        ui.init_fonts()
except exceptions.FontException:
    logging.fatal("Cannot load fonts")
    shutdown(ui=ui)
    sys.exit()

logger.info('Waiting for user to airplay music')
ui.state.radio_state.mode = menus.PlayerMode.AIRPLAY
ui.state.visualiser =  "graphic_equaliser_bars"
ui.state.station_enabled = True
ui.state.levels_enabled = False
ui.state.mode_display_enabled = True
ui.state.volume_display_enabled = True
ui.state.station_name      = ""
ui.state.last_station_name = ""
ui.state.ensemble          = "test"
ui.state.awaiting_signal   = False
ui.update()

logger.info("Audio processing initialising")
try:
    audio_processor = audio_processing.AudioProcessing() 
except Exception as e:
    shutdown(ui=ui, player=player)
    sys.exit()

ui.state.audio_processor = audio_processor

# Set volume
audio_processor.set_volume(ui.state.volume)
logger.info(f'Volume set to {audio_processor.volume()}%, adjust by {ui.state.volume_change_step}')

# Start audio processing
audio_processor.start()
audio_processor.stream.start_stream()

# Start MQTT event loop
mqttc = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
mqttc.on_connect = callbacks.on_connect
mqttc.on_message = lambda client,userdata,msg: callbacks.on_message(client, userdata, msg, ui=ui, audio_processor=audio_processor, player=player)
try:
    mqttc.connect("localhost", 1883, 60)
except ConnectionRefusedError as e:
    logger.fatal("Cannot connect to MQTT")
else:
    mqttc.loop_start()

# Lets get this party started ...
logger.info("Radio starting")
ui.reset_station_name_scroll()

try:
    # Render loop
    # TODO: Use callbacks perhaps? Will add complexity
    # Calc FPS and Render times
    while True:
        ui.draw_interface()
    # end while

except (KeyboardInterrupt,SystemExit):
    audio_processor.stream.close()
    audio_processor.p.terminate()

    logging.info("Shutting down")
    shutdown(ui=ui,player=player)
    logger.info("Radio Hard Stop")
