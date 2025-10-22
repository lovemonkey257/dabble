
import logging
import alsaaudio 
from threading import Lock, current_thread
from . import encoder, exceptions, menus, lcd_ui


logger = logging.getLogger(__name__)

# TODO: Feels wrong here! mmmm
# Lock to protect station changes
# Rapid turns of encoder can result in multiple callbacks
# and strange station choices
station_lock = Lock()

# Ease debugging by changing threadname to the callback name
def change_thread_name(func):
    def wrapper(*args, **kwargs):
        current_thread().name = func.__name__
        result = func(*args, **kwargs)
        return result
    return wrapper

#########################################################
# CALLBACKS
#########################################################
@change_thread_name
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

    elif ui.state.radio_state.selecting_left_menu.is_active:
        # Can only exit if menu being selected or menus active (but nothing selected yet)
        # exit_menu can be called multiple times if button debounce misses double press
        if encoder_position == encoder.EncoderPosition.LEFT:
            logger.info("Exiting left menu")
            ui.state.left_encoder.device.when_rotated_clockwise          = lambda: change_station(ui,player,audio_processor)
            ui.state.left_encoder.device.when_rotated_counter_clockwise  = lambda: change_station(ui,player,audio_processor)
            ui.state.radio_state.exit_left_menu()

    elif ui.state.radio_state.selecting_right_menu.is_active:
        if encoder_position == encoder.EncoderPosition.RIGHT:
            logger.info("Exiting right menu")
            ui.state.right_encoder.device.when_rotated_clockwise         = lambda: ui.state.update("volume",audio_processor.vol_up(ui.state.volume_change_step))
            ui.state.right_encoder.device.when_rotated_counter_clockwise = lambda: ui.state.update("volume",audio_processor.vol_down(ui.state.volume_change_step))
            ui.state.radio_state.exit_right_menu()
    else:
        logging.warning("Exit called. Wrong state: %s", ui.state.radio_state.current_state.id)

@change_thread_name
def next_menu(state, curr_menu):
    ''' Get next menu item, reseting timeout '''
    state.menu_timer.reset()
    state.current_menu_item = curr_menu.get_next_menu()

@change_thread_name
def prev_menu(state, curr_menu):
    ''' Get prev menu item, reseting timeout '''
    state.menu_timer.reset()
    state.current_menu_item = curr_menu.get_prev_menu()

@change_thread_name
def activate_or_run_menu(encoder_position, ui, player, audio_processor):
    '''
    Button pressed to bring up menu
    Change encoders so we now select menus and run actions
    '''
    logging.info("State: %s, Prev State: %s, Button pressed: %s", ui.state.radio_state.current_state.id, ui.state.radio_state.previous_state, encoder_position.name)
    curr_menu               = None
    selected_encoder        = None
    change_encoder_function = False

    if encoder_position == encoder.EncoderPosition.LEFT:
        curr_menu = ui.state.lm
        selected_encoder = ui.state.left_encoder
        if ui.state.radio_state.playing.is_active:
            # If playing then menu is activated
            ui.state.radio_state.activate_left_menu()
            change_encoder_function=True
        elif ui.state.radio_state.left_menu_activated.is_active:
            # Menu activated and now we're doing something with menus
            ui.state.radio_state.left_menu_selection()

    elif encoder_position == encoder.EncoderPosition.RIGHT:
        curr_menu = ui.state.rm
        selected_encoder = ui.state.right_encoder
        if ui.state.radio_state.playing.is_active:
            ui.state.radio_state.activate_right_menu()
            change_encoder_function=True
        elif ui.state.radio_state.right_menu_activated.is_active:
            ui.state.radio_state.right_menu_selection()

    if change_encoder_function:
        selected_encoder.device.when_rotated_clockwise         = lambda: next_menu(ui.state, curr_menu)
        selected_encoder.device.when_rotated_counter_clockwise = lambda: prev_menu(ui.state, curr_menu)
        ui.state.current_menu_item=curr_menu.get_first_menu_item()
        logging.info("Menu currently selected: %s", ui.state.current_menu_item)
        ui.state.menu_timer = menus.PeriodicTask(interval=8, name="menu_timer", callback=lambda:exit_menu(encoder_position, ui, player, audio_processor))
        ui.state.menu_timer.run()

    elif ui.state.radio_state.selecting_left_menu.is_active or \
         ui.state.radio_state.selecting_right_menu.is_active:
        ui.state.menu_timer.reset()
        curr_menu.run_action(ui.state.current_menu_item)

@change_thread_name
def play_new_station(ui,player,audio_processor):
    '''
    New station selected, now play it
    '''
    # Cancel timer
    ui.state.station_timer.terminate()

    # Back to playing
    ui.state.radio_state.toggle_select_station()

    # Don't select currently playing station
    if player.playing == ui.state.station_name:
        logger.info("User selected same station. Will ignore")
        return

    audio_processor.zero_signal()
    logging.info("New Station selected...changing audio")

    # Pause streaming ...
    audio_processor.stream.stop_stream()

    # start playing state.current_station
    player.stop()
    player.play(ui.state.station_name)

    # Resume playing
    audio_processor.stream.start_stream()

    ui.state.update_pad(" ")
    ui.state.dab_type = ""
    ui.state.last_pad_message = ""
    logger.info(f'Now playing {ui.state.station_name}')

@change_thread_name
def change_station(ui,player,audio_processor):
    '''
    User is moving dial to change station
    If dial isn't moved timer is triggered which when expires will
    play that station.

    TODO: Do we need to press encoder to select or auto select or
          is it configurable?
    '''
    with station_lock:
        if ui.state.radio_state.playing.is_active or \
           not ui.state.radio_state.left_menu_activated.is_active and \
           not ui.state.radio_state.right_menu_activated.is_active and \
           not ui.state.radio_state.selecting_a_station.is_active:
            # If we're entering station selection ..
            # Change into select_station state
            ui.state.radio_state.toggle_select_station()
            # Set up timeout timer which changes station once stopped selecting
            ui.state.station_timer = menus.PeriodicTask(interval=4, name="station_select_timer", callback=lambda:play_new_station(ui,player,audio_processor))
            ui.state.station_timer.run()
            logger.info("Start changing station..")

        if ui.state.radio_state.selecting_a_station.is_active:
            # still twiddling so reset timeout
            ui.state.station_timer.reset()
            # Get index of station in list and correct given current station
            left_encoder_value = ui.state.left_encoder.device.steps
            station_index  = player.radio_stations.station_index(player.playing)
            station_number = left_encoder_value + station_index
            logger.info("Left Encoder Steps: %d  Current Station Index: %d, will choose %d", left_encoder_value, station_index, station_number)

            # Get the new station name and details
            (ui.state.station_name, station_details)=player.radio_stations.select_station(station_number)
            ui.state.ensemble     = station_details['ensemble']
            ui.state.current_msg  = lcd_ui.MessageState.STATION
            logger.info(f'New station {station_number} {ui.state.station_name}/{ui.state.ensemble} selected')
            ui.reset_station_name_scroll()

@change_thread_name
def update_msg(msg, sub_msg:str=""):
    ''' 
    Callback to update the UI with a message from the player during scanning 
    '''
    ui.clear_screen()
    ui.reset_station_name_scroll()
    ui.draw_station_name(msg)  
    ui.draw_ensemble(sub_msg)    
    ui.update()

@change_thread_name
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

@change_thread_name
def on_connect(client, userdata, flags, reason_code, properties):
    '''
    Run when connected to MQTT server
    '''
    logger.info(f"MQTT Connected: {reason_code}")
    # Subscribing in on_connect() means that if we lose the connection and
    # reconnect then subscriptions will be renewed.
    client.subscribe("dabble-radio/#")

@change_thread_name
def on_message(client, userdata, msg, ui=None, audio_processor=None, player=None):
    '''
    Callback on msg MQTT topic receive. Currently used to receive
    comms from shairplay-sync (airplay)
    '''
    topic_components = msg.topic.split("/",2)
    if len(topic_components)<2:
        logger.info("Cannot parse MQTT Topic:%s - %s", msg.topic, payload)
        return

    base_topic = topic_components[0]
    cmd        = topic_components[1]
    payload    = msg.payload.decode("utf-8")
    if payload == "1" or payload == "0":
        # Convert payload to boolean
        payload = payload == "1"

    if base_topic=="dabble-radio":
        match cmd:
            case "client_name":
                ui.state.client_name = payload
                logger.info("Inbound Airplay connection from: %s", ui.state.client_name)
            case "playing" | "play_resume":
                logger.info("Airplay playing: %s", "yes" if payload else "no")
                if ui.state.radio_state == menus.PlayerMode.AIRPLAY:
                    logger.info("Airplay already playing or being pausing. Ignore")
                ui.state.radio_state.mode = menus.PlayerMode.AIRPLAY
            case "active_start":
                logger.info("Airplay activated, Radio should shutdown")
                ui.state.radio_state.mode = menus.PlayerMode.AIRPLAY
                # Save the station name
                ui.state.last_station_name = ui.state.station_name 
                player.stop()
            case "active_end":
                logger.info("Airplay deactivated, Radio should start up again. Station: %s", ui.state.last_station_name)
                ui.state.radio_state.mode = menus.PlayerMode.RADIO
                ui.state.station_name = ui.state.last_station_name 
                player.play(ui.state.station_name)
                ui.state.ensemble = player.ensemble
            case "album":
                logger.info("Airplay %s: %s", cmd, payload)
                ui.state.album = payload
            case "track" | "title":
                logger.info("Airplay %s: %s", cmd, payload)
                ui.state.track = payload
                ui.state.update_pad(ui.state.track)
            case "artist":
                logger.info("Airplay %s: %s", cmd, payload)
                ui.state.artist = payload
                ui.state.station_name = ui.state.artist
            case "genre":
                logger.info("Airplay %s: %s", cmd, payload)
                ui.state.genre = payload
            case "volume":
                vol_db_str,_=payload.split(",",1) 
                vol_db = float(vol_db_str)  # Apple gives negative DB (real)
                audio_processor.set_volume(vol_db, units=alsaaudio.VOLUME_UNITS_DB)
                ui.state.update("volume",audio_processor.volume())
                logger.info("Vol DB:%f. Current volume: %d", vol_db, ui.state.volume)
            case _:
                logger.info("Unhandled MQTT Topic:%s - %s", msg.topic, payload)
    else:
        logger.info("Unexpected MQTT Topic:%s - %s", msg.topic, payload)


@change_thread_name
def change_mode(mode, mqtt_client, ui, player):
    if mode == menus.PlayerMode.RADIO:
        logger.info("Telling shairplay to stop playing")
        ui.state.shairport_dbus_interface.Pause()
        logger.info("Radio enabled. Station: %s", ui.state.last_station_name)
        ui.state.radio_state.mode = menus.PlayerMode.RADIO
        ui.state.station_name = ui.state.last_station_name 
        player.play(ui.state.station_name)
        ui.state.ensemble = player.ensemble

    elif mode == menus.PlayerMode.AIRPLAY:
        logger.info("Airplay activated, Radio should shutdown")
        ui.state.radio_state.mode = menus.PlayerMode.AIRPLAY
        # Save the station name
        ui.state.last_station_name = ui.state.station_name 
        player.stop()
        ui.state.shairport_dbus_interface.Play()

@change_thread_name
def pad_update_handler(ui, updates):
    if updates.is_updated('no_signal'):
        ui.state.have_signal = False
        ui.state.awaiting_signal = False

    elif updates.is_updated('dab_type'):
        ui.state.dab_type=updates.get('dab_type').value
        logger.info(f"DAB type: {ui.state.dab_type}")
        ui.state.have_signal     = True
        ui.state.awaiting_signal = False

    elif updates.is_updated('pad_label'):
        pad = updates.get('pad_label').value
        ui.state.update_pad(pad)
        ui.state.awaiting_signal = False
        logger.info(f"PAD msg: \"{pad}\"")

    elif updates.is_updated('media_fmt'):
        ui.state.awaiting_signal = False
        ui.state.audio_format = updates.get('media_fmt').value
        logger.info(f"Audio format: \"{ui.state.audio_format}\"")

    elif updates.is_updated('prog_type'):
        ui.state.awaiting_signal = False
        ui.state.genre = updates.get('prog_type').value
        logger.info(f"Genre: \"{ui.state.genre}\"")
