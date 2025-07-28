
'''
'''
import logging
import json
import threading
from statemachine import StateMachine, State, Event
from time import sleep,time
from enum import Enum
from dabble import (audio_processing, encoder, exceptions, keyboard, lcd_ui,
                    radio_player, radio_stations)

logger = logging.getLogger(__name__)

class PeriodicTask:
    def __init__(self, interval, callback):
        '''
        Init the timer. Callback is called after interval seconds.

        Note, callback should be a lambda.
        '''
        self.interval = interval
        self.callback = callback
        self.t     = None
        self.event = threading.Event()

    def run_callback(self):
        '''
        Run the callback. Check the event to see if 
        timer should terminate?
        '''
        logging.debug("Timer callback firing")
        self.callback()
        # Set event to terminate this
        if not self.event.is_set():
            self.run()

    def run(self):
        '''
        Call callback every interval seconds
        '''
        self.t = threading.Timer(self.interval, self.run_callback)
        self.t.start()

    def reset(self):
        '''
        Reset the timer back to zero and start counting again
        '''
        self.t.cancel()
        self.run()


class RadioMachine(StateMachine):
    playing              = State(initial=True)
    station_selection    = State()
    left_menu_activated  = State()
    right_menu_activated = State()
    station_scanning     = State()

    toggle_select_station        = playing.to(station_selection)   | station_selection.to(playing)
    toggle_left_menu             = playing.to(left_menu_activated) | left_menu_activated.to(playing)
    toggle_right_menu            = playing.to(right_menu_activated) | right_menu_activated.to(playing)
    toggle_scanning_for_stations = right_menu_activated.to(station_scanning) | station_scanning.to(right_menu_activated) 

    def on_transition(self, event_data, event: Event):
            assert event_data.event == event
            return (
                f"Running {event.name} from {event_data.transition.source.id} to "
                f"{event_data.transition.target.id}"
            )

class Menu():
    '''
    A very simple menuing systen. Nesting not currently supported
    '''
    def __init__(self):
        self.menu = dict()
        self.actions = dict()
        self.last_menu_add = None
        self.menu_list = None
        self.menu_index = 0

    def add_menu(self, menu):
        if menu not in self.menu:
            self.menu[menu]=dict()
        self.last_menu_add = menu
        return self

    def action(self, callback):
        self.actions[self.last_menu_add] = callback
        return self

    def run_action(self, menu):
        if menu in self.actions:
           self.actions[menu]()

    def _create_menu_list(self):
        if self.menu_list is None:
            self.menu_list = list(self.menu.keys())
            self.menu_index = 0

    def get_first_menu_item(self):
        self._create_menu_list()
        return self.menu_list[0]

    def get_next_menu(self):
        self._create_menu_list()
        self.menu_index += 1
        if self.menu_index > len(self.menu_list)-1:
            self.menu_index = 0
        logger.info("Menu selected %s",self.menu_list[self.menu_index])
        return self.menu_list[self.menu_index]

    def get_prev_menu(self):
        self._create_menu_list()
        self.menu_index -= 1
        if self.menu_index < 0:
            self.menu_index = len(self.menu_list)-1 
        logger.info("Menu selected %s",self.menu_list[self.menu_index])
        return self.menu_list[self.menu_index]

