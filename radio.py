
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

from dabble import (audio_processing, encoder, exceptions, keyboard, lcd_ui,
                    radio_player, radio_stations, menus, state, callbacks)

def shutdown(ui=None,kb=None,player=None, mqttc=None):
    if mqttc:
        mqttc.loop_stop()

    if ui:
        state.save_state(ui.state)
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
ui.state.radio_state = menus.RadioMachine()

# Initialise stations and player
logger.info("Loading radio stations")
stations=radio_stations.RadioStations()

logger.info("Initialising player")
player=radio_player.RadioPlayer(
        radio_stations=stations, 
        pad_update_handler = lambda updates: callbacks.pad_update_handler(ui,updates))

# Load stations. If none then initiate scan
try:
    stations.load_stations()
except exceptions.NoRadioStations as e:
    player.scan(ui_msg_callback=callbacks.update_msg)

# Load defaults
logger.info("Loading saved state")
current_config = state.load_state(ui.state)

# Load theme and init fonts
try:
    if theme := ui.state.theme.load_theme(ui.state.theme_name):
        ui.state.theme = theme
        ui.init_fonts()
except exceptions.FontException:
    logging.fatal("Cannot load fonts")
    shutdown(mqttc=mqttc)
    sys.exit()

# Display startup message
ui.show_startup()
time.sleep(2)

# Set up encoders and buttons
ui.state.left_encoder  = encoder.Encoder(
        device_type=encoder.EncoderTypes.FERMION_EC11_BREAKOUT, 
        pin_a=17, pin_b=27, pin_c=23, 
        bounce_time=0.1,
        button_press_callback=lambda:callbacks.activate_or_run_menu(encoder.EncoderPosition.LEFT, ui, player, audio_processor))

ui.state.right_encoder = encoder.Encoder(
        device_type=encoder.EncoderTypes.FERMION_EC11_BREAKOUT, 
        pin_a=24, pin_b=25, pin_c=22, 
        bounce_time=0.1,
        button_press_callback=lambda:callbacks.activate_or_run_menu(encoder.EncoderPosition.RIGHT, ui, player, audio_processor))

logger.info("Setting colour of left encoder")
ui.state.left_encoder.set_colour_by_rgb(ui.state.left_led_rgb)

# TODO: What mode are we starting in???
# This assumes mode is radio! Start up in airplay??

if ui.state.radio_state.mode == menus.PlayerMode.RADIO:
    logger.info(f'Begin playing {ui.state.station_name}')
    player.play(ui.state.station_name)
    ui.state.station_name      = player.playing
    ui.state.ensemble          = player.ensemble
elif ui.state.radio_state.mode == menus.PlayerMode.AIRPLAY:
    logger.info('Waiting for user to airplay music')
    ui.state.station_name      = "Waiting for stream.."
    ui.state.ensemble          = "..."
    ui.state.awaiting_signal   = False

ui.update()

logger.info("Audio processing initialising")
audio_processor = audio_processing.AudioProcessing() 
ui.state.audio_processor = audio_processor

# Set volume
audio_processor.set_volume(ui.state.volume)
logger.info(f'Volume set to {audio_processor.volume()}%, adjust by {ui.state.volume_change_step}')

# Start audio processing
audio_processor.start()
audio_processor.stream.start_stream()

# Set encoder twiddling callbacks
if ui.state.radio_state.mode == menus.PlayerMode.RADIO:
    ui.state.left_encoder.device.when_rotated_clockwise          = lambda: callbacks.change_station(ui,player,audio_processor)
    ui.state.left_encoder.device.when_rotated_counter_clockwise  = lambda: callbacks.change_station(ui,player,audio_processor)

ui.state.right_encoder.device.when_rotated_clockwise         = lambda: ui.state.update("volume",audio_processor.vol_up(ui.state.volume_change_step))
ui.state.right_encoder.device.when_rotated_counter_clockwise = lambda: ui.state.update("volume",audio_processor.vol_down(ui.state.volume_change_step))

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

# Set up menus and callbacks
ui.state.lm = menus.Menu()
ui.state.current_menu_item=""
ui.state.lm.add_menu("Equaliser/Full", init_state="On" if ui.state.visualiser=="graphic_equaliser" else "off")\
        .action(lambda: ui.state.update("visualiser","graphic_equaliser"))\
        .change_state(lambda: "On" if ui.state.visualiser=="graphic_equaliser" else "Off")

ui.state.lm.add_menu("Equaliser/Bars", init_state="On" if ui.state.visualiser=="graphic_equaliser_bars" else "off")\
        .action(lambda: ui.state.update("visualiser","graphic_equaliser_bars"))\
        .change_state(lambda: "On" if ui.state.visualiser=="graphic_equaliser_bars" else "Off")

ui.state.lm.add_menu("Waveform", init_state="On" if ui.state.visualiser=="waveform" else "Off")\
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

ui.state.lm.add_menu("Exit").action(lambda: callbacks.exit_menu(encoder.EncoderPosition.LEFT, ui, player, audio_processor))

ui.state.rm = menus.Menu()
ui.state.rm.add_menu("Radio Mode", init_state="On" if ui.state.radio_state.mode == menus.PlayerMode.RADIO  else "Off")\
        .action(lambda: callbacks.change_mode(menus.PlayerMode.RADIO, mqttc, ui, player))\
        .change_state(lambda: "On" if ui.state.radio_state.mode == menus.PlayerMode.RADIO else "Off")
ui.state.rm.add_menu("Airplay Mode", init_state="On" if ui.state.radio_state.mode == menus.PlayerMode.AIRPLAY  else "Off")\
        .action(lambda: callbacks.change_mode(menus.PlayerMode.AIRPLAY, mqttc, ui, player))\
        .change_state(lambda: "On" if ui.state.radio_state.mode == menus.PlayerMode.AIRPLAY else "Off")
ui.state.rm.add_menu("Scan Channels").action(lambda: callbacks.initiate_scan(ui, player, audio_processor))
ui.state.rm.add_menu("Exit").action(lambda: callbacks.exit_menu(encoder.EncoderPosition.RIGHT, ui, player, audio_processor))

# Lets get this party started ...
logger.info("Radio starting")
ui.reset_station_name_scroll()

try:
    # Render loop
    # TODO: Use callbacks perhaps? Will add complexity
    # Calc FPS and Render times
    fps=0
    fps_st=time.time()
    while True:
        t1=time.time_ns()
        ui.draw_interface()
        t2=time.time_ns()
        render_time = ((t2-t1)/1000000)
        fps_et=time.time()
        if fps_et-fps_st>=1:
            fps_st=time.time()
            ui.state.fps = fps
            ui.state.render_time = render_time
            logging.debug("FPS: %d %dms", fps, render_time)
            fps=0
        fps+=1
    # end while

except (KeyboardInterrupt,SystemExit):
    audio_processor.stream.close()
    audio_processor.p.terminate()

    logging.info("Shutting down")
    shutdown(ui=ui,player=player)
    logger.info("Radio Hard Stop")
