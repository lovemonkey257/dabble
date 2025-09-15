import json
import logging
from pathlib import Path
from dabble import (lcd_ui, menus)

logger = logging.getLogger(__name__)
config_path = Path("dabble_radio.json")

def load_state(state:lcd_ui.UIState):
    logger.info(f'Loading saved state from {config_path}')
    config=dict()
    if config_path.exists():
        with open(config_path, "r") as f:
            config = json.load(f)
            state.volume = config['volume']
            state.station_name = config['station_name']
            state.last_station_name = config['station_name']
            state.ensemble = config['ensemble']
            state.visualiser_enabled = config['enable_visualiser']
            state.visualiser = config['visualiser']
            state.levels_enabled = config['enable_levels']
            state.pulse_left_led_encoder = config['pulse_left_led_encoder']
            state.pulse_right_led_encoder = config['pulse_right_led_encoder']
            state.station_enabled = config['station_enabled'] if 'station_enabled' in config else True
            if "mode" in config:
                if config['mode']=="radio":
                    state.radio_state.mode = menus.PlayerMode.RADIO
                elif config['mode']=="airplay":
                    state.radio_state.mode = menus.PlayerMode.AIRPLAY
            if 'theme' in config:
                state.theme_name = config['theme']
    else:
        state.station_name = "Magic Radio"
    return config

def save_state(state:lcd_ui.UIState):
    logger.info("Saving state")
    mode="radio"
    if state.radio_state.mode == menus.PlayerMode.RADIO:
        mode="radio"
    elif state.radio_state.mode == menus.PlayerMode.AIRPLAY:
        mode="airplay"

    config = {
        "station_name": state.station_name if state.radio_state.mode == menus.PlayerMode.RADIO else state.last_station_name,
        "ensemble": state.ensemble,
        "volume": state.volume,
        "pulse_left_led_encoder": state.pulse_left_led_encoder,
        "pulse_right_led_encoder": state.pulse_right_led_encoder,
        "enable_visualiser": state.visualiser_enabled,
        "visualiser": state.visualiser,
        "enable_levels": state.levels_enabled,
        "station_enabled": state.station_enabled,
        "mode": mode,
        "theme": state.theme.name
    }
    with open(config_path, "w") as f:
        f.write(json.dumps(config))

