
'''
'''
import logging
import json
import threading
from dataclasses import dataclass
from statemachine import StateMachine, State, Event
from time import sleep,time
from enum import Enum
from dabble import (audio_processing, encoder, exceptions, keyboard, lcd_ui,
                    radio_player, radio_stations)

logger = logging.getLogger(__name__)

class PeriodicTask:
    def __init__(self, interval, callback, name:str=""):
        '''
        Init the timer. Callback is called every interval seconds.
        Note, callback should be a lambda.
        '''
        self.interval = interval
        self.callback = callback
        self.name     = name
        self._t        = None
        self._terminate = threading.Event()

    def run_callback(self):
        '''
        Run the callback. Check the event to see if 
        timer should terminate?
        '''
        self.callback()
        # Set event to terminate and not repeat
        if self._terminate.is_set():
            logging.info("Timer %s ends", self.name)
            self._t.cancel()
            self._t = None
        else:
            logging.info("Timer %s resetting. Will fire again in %ds", self.name, self.interval)
            self.run()

    def run(self):
        '''
        Call callback every interval seconds
        '''
        self._t = threading.Timer(self.interval, self.run_callback)
        self._t.start()

    def terminate(self):
        self._terminate.set()

    def reset(self):
        '''
        Reset the timer back to zero and start counting again
        '''
        self._t.cancel()
        self.run()


class PlayerMode(Enum):
    RADIO = 0
    AIRPLAY = 1

class RadioMachine(StateMachine):

    previous_state        = None
    mode                  = PlayerMode.RADIO

    playing               = State(initial=True)
    selecting_a_station   = State()
    left_menu_activated   = State()
    right_menu_activated  = State()
    selecting_a_menu      = State()
    scanning_for_stations = State()

    # Events
    activate_left_menu    = playing.to(left_menu_activated) 
    left_menu_selection   = left_menu_activated.to(selecting_a_menu) 
    exit_left_menu        = selecting_a_menu.to(playing)
    left_menu_timeout     = left_menu_activated.to(playing)

    activate_right_menu   = playing.to(right_menu_activated)
    right_menu_selection  = right_menu_activated.to(selecting_a_menu) 
    exit_right_menu       = selecting_a_menu.to(playing)
    right_menu_timeout    = right_menu_activated.to(playing)

    toggle_select_station = playing.to(selecting_a_station) | selecting_a_station.to(playing)
    toggle_scan           = right_menu_activated.to(scanning_for_stations) | scanning_for_stations.to(right_menu_activated) 

    def on_transition(self, event_data, event: Event):
            assert event_data.event == event
            logger.info(
                f"Event {event.name} triggered. Move from {event_data.transition.source.id} to "
                f"{event_data.transition.target.id}"
            )

    def before_transition(self, event, state):
        self.previous_state = state.id
        logger.info("Transition in progress. From state: %s", state.id)

    def update(self, prop, value):
        '''
        Allow state to be changed using <obj>.update("prop",value)
        Means it can be used in lambdas which don't like <obj>.<prop>=<value>
        '''
        setattr(self, prop, value)
        logger.info("Changing %s to %s. Actual set to: %s", prop, value, getattr(self,prop))
        return getattr(self, prop)


@dataclass
class MenuItem():
    menu_id:str = ""  # Unique ID of menu item
    display:str = ""  # What to display
    state:str   = ""  # Is it on/off or a value?

    def dstate(self):
        '''
        Returns what the menu item should be displayed as
        e.g.
        "text: on|off" or "just some text"
        '''
        return f'{self.display}: {self.state}' if self.state else self.display

class Menu():
    '''
    A very simple menuing systen. Nesting not currently supported
    Supports on/off settings or just text
    
    TODO:
    - Add way of selecting value e.g. using encoder to inc/dec value and button to lock in
    '''
    def __init__(self):
        self.menu = dict()
        self.actions = dict()
        self.state_update = dict()
        self.last_menu_add = None
        self.menu_list = None
        self.menu_index = 0

    def add_menu(self, menu_id, display=None, init_state=None):
        if menu_id not in self.menu:
            self.menu[menu_id]=MenuItem(menu_id=menu_id,display=menu_id if display is None else display, state=init_state)
        self.last_menu_add = menu_id
        return self

    def action(self, callback):
        if self.last_menu_add not in self.actions:
            self.actions[self.last_menu_add] = callback
        return self

    def change_state(self, callback):
        self.state_update[self.last_menu_add] = callback

    def run_action(self, menu_item):
        if menu_item.menu_id in self.actions:
            logger.info("Running action for %s",menu_item)
            r = self.actions[menu_item.menu_id]()
        if menu_item.menu_id in self.state_update:
            # Trigger update callbacks for all menus
            logger.info("Running state update for %s",menu_item)
            for menu_id in self.state_update:
                self.menu[menu_id].state = self.state_update[menu_id]()
                logger.info("- Update %s, state now: %s", menu_id, self.menu[menu_id].state)
            logger.info("States updated")
        return r

    def _create_menu_list(self):
        '''
        Returns list of MenuItems
        '''
        if self.menu_list is None:
            self.menu_list = [ self.menu[d] for d in self.menu ]
            self.menu_index = 0
            logger.info(self.menu_list)
        return self.menu_list

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

