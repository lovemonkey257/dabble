
import colorsys
import logging
import math
import functools
import threading
import time
import st7735
import json
import numpy as np
import dbus

from dataclasses import dataclass, field
from enum import Enum,StrEnum
from pathlib import Path
from scipy.signal import butter, filtfilt, lfilter
from PIL import Image, ImageDraw, ImageFont

from . import exceptions, menus, encoder

logger = logging.getLogger(__name__)

# Constants
class Locks:
    INTERFACE = threading.Lock()

class MessageState(Enum):
    STATION  = 0
    LAST_PAD = 1

class GraphicState(StrEnum):
    WAVEFORM               = "waveform"
    GRAPHIC_EQUALISER      = "graphic_equaliser"
    GRAPHIC_EQUALISER_BARS = "graphic_equaliser_bars"

@dataclass
class UITheme():
    name:str                = "default"

    base_font_path:str      = "noto/NotoSans_SemiCondensed" 
    station_font_size:int   = 20 
    station_font_style:str  = "SemiBold"
    ensemble_font_size:int  = 13
    ensemble_font_style:str = "Regular"
    menu_font_size:int      = 18
    menu_font_sml_size:int  = 15
    menu_font_style:str     ="SemiBold"

    mode_hilite:str         = '#FFB703'
    station:str             = '#FFB703' 
    ensemble:str            = '#023047' 
    menu:str                = '#24D111' 
    menu_sml:str            = '#0B4205' 
    volume:str              = '#8ECAE6'
    volume_bg:str           = '#023047'
    viz_line:str            = '#126782'
    viz_dot:str             = '#8ECAE6'

    def load_theme(self, theme_name:str, theme_file:str="themes.json"):
        logger.info(f'Loading theme %s', theme_name)
        theme_path = Path(theme_file)
        theme=None
        if theme_path.exists():
            with open(theme_path, "r") as f:
                try:
                    themes = json.load(f)
                    if theme_name in themes:
                        # Got one...
                        theme = UITheme(**themes[theme_name])
                        theme.name = theme_name
                        logger.info("Theme loaded. Oooooo pretty....")
                    else:
                        logger.info("Theme %s not found", theme_name)
                except Exception as e:
                    logger.warn("Theme file invalid. Check JSON: %s", e)
        else:
            logger.warn("Theme file %s not found",  theme_file)
        return theme


@dataclass
class UIState():
    '''
    This stores the state of the UI.
    Changes here are reflected in the UI
    This should be the only place the UI values are changed
    '''
    station_name:str     = ""
    ensemble:str         = ""
    last_pad_message:str = ""
    next_pad_message:str = ""
    flash_message:str    = "" # Set if want to temp override station msg
    pad_queue:list       = field(default_factory=list)
    audio_format:str     = ""
    genre:str            = ""
    dab_type:str         = ""
    current_msg:int      = MessageState.STATION
    have_signal:bool     = True # Assume signal
    awaiting_signal:bool = True # Awaiting Dablin to catchup

    client_name:str      = ""   # Airplay Client Name
    track:str            = ""   # Airplay Track
    album:str            = ""   # Airplay Album
    artist:str           = ""   # Airplay Artist

    volume:int           = 40
    peak_l:int           = 0
    peak_r:int           = 0
    audio_processor:object = None
    volume_change_step:int = 1  # Vol inc/decs in this value

    left_encoder:encoder.Encoder   = None
    right_encoder:encoder.Encoder  = None
    pulse_left_led_encoder:bool    = False
    pulse_right_led_encoder:bool   = False
    left_led_rgb                   = (255,255,255)
    right_led_rgb                  = (255,255,255)

    radio_state:menus.StateMachine = None
    current_menu_item:str          = None
    lm:menus.Menu                  = None # Left Menu
    rm:menus.Menu                  = None # Right Menu
    station_timer:threading.Thread = None # Station selection timeout
    menu_timer:threading.Thread    = None # Menu exit timeout

    visualiser_enabled:bool        = True
    visualiser:GraphicState        = GraphicState.GRAPHIC_EQUALISER
    levels_enabled:bool            = True
    station_enabled:bool           = True

    colors:dict                    = field(default_factory=dict)
    theme:UITheme                  = field(default_factory=UITheme)

    fps:int                        = 0 # Frames Per Sec
    render_time:int                = 0 # Time (in ms) taken to render LCD display

    shairport_dbus_interface:dbus.Interface  = None                          

    
    def update(self, prop, value):
        '''
        Allow state to be changed using <obj>.update("prop",value)
        Means it can be used in lambdas which don't like <obj>.<prop>=<value>
        Returns new value (as returned by method not value passed which may not be the same)
        '''
        setattr(self, prop, value)
        return getattr(self, prop)

    def update_pad(self, pad):
        '''
        Update PAD message, but don't change current one otherwise
        quickly changing PADs are disconcerting. 
        '''
        if self.last_pad_message == "":
            self.last_pad_message = pad
        else:
            self.next_pad_message = pad

    def get_pad_message(self):
        '''
        Get the PAD message last seen
        '''
        return self.last_pad_message if self.last_pad_message else ""
    
    def get_current_message(self):
        '''
        Get the current message on the UI, either Station or PAD
        '''
        if self.current_msg == MessageState.STATION:
            return self.station_name
        if self.current_msg == MessageState.LAST_PAD:
            return self.get_pad_message()

    def get_next_message(self):
        '''
        Flip message between station name and PAD (if PAD has been received)
        '''
        if self.current_msg == MessageState.STATION and self.last_pad_message!="":
            self.current_msg = MessageState.LAST_PAD
        elif self.current_msg == MessageState.LAST_PAD:
            self.current_msg = MessageState.STATION
        # get next pad message (dont change mid display, only on rotate)
        if self.next_pad_message!="":
            self.last_pad_message=self.next_pad_message

    def __post_init__(self):
        sys_dbus = dbus.SystemBus()
        proxy = sys_dbus.get_object('org.gnome.ShairportSync', '/org/gnome/ShairportSync')
        self.shairport_dbus_interface = dbus.Interface(proxy, 'org.gnome.ShairportSync.RemoteControl')


class Timer():
    '''
    Timer to record elapsed time. No callbacks needed, just calls
    to expired or elapsed.
    '''
    def __init__(self):
        self._start_time = 0
        self._elapsed    = 0
        self._expires    = 0
        self._expired    = False
        self.running     = False

    def _now_ns_to_ms(self):
        return time.time_ns()//1000000

    def start(self, expire_at:int):
        '''
        Start timer. Record time in microseconds
        i.e. 1s = 1000 milliseconds
        '''
        self._expires    = expire_at
        self._start_time = self._now_ns_to_ms()
        self._expired    = False
        self.running     = True

    def elapsed(self):
        self._elapsed = self._now_ns_to_ms() - self._start_time
        self._expired = self._elapsed >= self._expires
        self.running  = self._expired
        return self._elapsed

    def expired(self):
        self.elapsed()
        return self._expired


class LCDUI():
    '''
    Manage the LCD display and UI
    Based on 0.96" ST7735 LCD from Pimoroni

    Origin is top left: (0,0)
    Bottom right:       (WIDTH,HEIGHT)

    TODO: Should be a singleton as only one instance of this should exist!
    '''
    def __init__(self, 
                 dc_gpio:str="GPIO9",
                 backlight_gpio:str="GPIO26"):

        self._lock = Locks.INTERFACE

        # Create ST7735 LCD display class. Taken from Pimoroni docs
        # 160 x 80 full colour
        # Be mindful of GPIO use when using other devices
        logging.info("Initialising LCD display")

        self.disp = st7735.ST7735(
            port=0,
            cs=0,
            dc=dc_gpio,
            backlight=backlight_gpio,
            rotation=90,
            spi_speed_hz=4000000
        )

        self.disp.begin()
        self.WIDTH         = self.disp.width
        self.HEIGHT        = self.disp.height
        self.CENTRE_HEIGHT = self.HEIGHT//2 
        self.CENTRE_WIDTH  = self.WIDTH//2
        logging.info("LCD is %d wide x %d high", self.WIDTH, self.HEIGHT)

        self.img = Image.new('RGB', (self.WIDTH, self.HEIGHT), color=(0, 0, 0))
        self.draw = ImageDraw.Draw(self.img)

        # Use to scroll station/PAD messages
        self.station_name_x       = self.WIDTH 
        self.station_name_size_x  = 0
        self._pause_station_timer = Timer()

        # Scroll status if too large
        self.status_x            = 0
        self.status_size_x       = 0
        self._pause_status_timer = Timer()

        # Levels
        self.last_l_level     = 0
        self.last_r_level     = 0
        self.last_max_l_level = 0
        self.last_max_r_level = 0
        self.last_max_signal  = np.zeros(4096)
    
        # This will also set a default theme just in case
        # any requested theme is broken/not there
        self.state = UIState()


    def get_font_path(self, style):
        fp=str(self.font_dir  / f'{self.base_font}-{style}.ttf')
        logging.info("Font path: %s", fp)
        return fp

    def init_fonts(self):
        '''
        Init Fonts. Need to do this when you want new point size or font style

        Beware of style as it forms part of file name
        '''
        self.station_font_size  = self.state.theme.station_font_size
        self.ensemble_font_size = self.state.theme.ensemble_font_size
        self.menu_font_size     = self.state.theme.menu_font_size

        self.font_dir=Path("/usr/share/fonts/truetype/")
        self.base_font = self.state.theme.base_font_path

        self.station_font_file  = self.get_font_path(self.state.theme.station_font_style)
        self.ensemble_font_file = self.get_font_path(self.state.theme.ensemble_font_style)
        self.menu_font_file     = self.get_font_path(self.state.theme.menu_font_style)

        try:
            self.station_font    = ImageFont.truetype(self.station_font_file, self.state.theme.station_font_size)
            self.ensemble_font   = ImageFont.truetype(self.ensemble_font_file, self.state.theme.ensemble_font_size)
            self.menu_sel_font   = ImageFont.truetype(self.menu_font_file, self.state.theme.menu_font_size)
            self.menu_sml_font   = ImageFont.truetype(self.menu_font_file, self.state.theme.menu_font_sml_size)
        except OSError as e:
            logging.error("Cannot load font: %s", self.base_font)
            raise exceptions.FontException

    def draw_viz(self, with_lock:bool=False):
        '''
        Draw the visualiser

        Inspiration winamp. Halcyon days eh
        '''
        if self.state.visualiser_enabled:
            # Only do something if enabled
            if with_lock:
                self._lock.acquire()
            match self.state.visualiser:
                case GraphicState.GRAPHIC_EQUALISER:
                    self.graphic_equaliser(self.state.audio_processor.signal(), base_y=28, height=35)
                case GraphicState.GRAPHIC_EQUALISER_BARS:
                    self.graphic_equaliser_bars(self.state.audio_processor.signal(), base_y=28, height=35)
                case GraphicState.WAVEFORM:
                    self.waveform(self.state.audio_processor.signal(), base_y=28, height=35)
            if with_lock:
                self._lock.release()


    def draw_interface(self, reset_scroll=False, dim_screen=True, draw_centre_lines:bool=False):
        '''
        Draw the entire interface

        TODO: Fix positions - make them clearer!? Changing one screws the others particularly when
              having to clear portions of the screen and bits are disabled (which then don't get 
              cleared!)

        '''
        with self._lock:
            # Normal display

            # If we have no vis OR no signals then make sure we clear the station name area or
            # we will get smudges as viz doesnt draw when no signal
            clear_sn = not self.state.visualiser_enabled or \
                       (self.state.audio_processor.peak_l==0 and self.state.audio_processor.peak_r==0)

            vol_bar_y = self.HEIGHT - 27

            if reset_scroll:
                self.reset_station_name_scroll()

            # Scroll station name
            if self.state.radio_state.playing.is_active or \
               self.state.radio_state.left_menu_activated.is_active or \
               self.state.radio_state.right_menu_activated.is_active:
                self.scroll_station_name()

            # When waiting for signal set PAD to nothing or status
            if self.state.awaiting_signal:
                self.state.last_pad_message = ""
            elif not self.state.have_signal:
                self.state.last_pad_message = "No Signal"

            # Draw the viz first, so we layer other text on top
            self.draw_viz()

            # Now station name
            if self.state.station_enabled or self.state.radio_state.selecting_a_station.is_active:
                self.draw_station_name(self.state.get_current_message(), clear=clear_sn)
            else:
                self.draw_station_name(" ", clear=clear_sn)

            # Now volume and mode
            self.draw_volume_bar(self.state.volume, x=0,y=vol_bar_y, height=4)   
            self.draw_mode(clear=True)

            # Now Ensemble and DAB type (if in radio mode)
            if self.state.radio_state.mode == menus.PlayerMode.RADIO:
                self.draw_ensemble(self.state.ensemble, clear=True)
                self.draw_dab_type(self.state.dab_type, clear=True)

            # Otherwise draw album name
            # Scroll if too big
            elif self.state.radio_state.mode == menus.PlayerMode.AIRPLAY:
                if len(self.state.album)>20:
                    self.scroll_status()
                    self.scrolling_status=True
                else:
                    self.scrolling_status=False
                self.draw_status(self.state.album)

            # Now levels
            if not self.state.levels_enabled:
                self.clear_levels() # y=vol_bar_y + 6)
            else:
                self.draw_levels(self.state.audio_processor.peak_l, self.state.audio_processor.peak_r) #, y=vol_bar_y + 6)

            if draw_centre_lines:
                self.draw.line((self.CENTRE_WIDTH, 0, self.CENTRE_WIDTH, self.HEIGHT),  fill='gray')
                self.draw.line((0, self.CENTRE_HEIGHT, self.WIDTH, self.CENTRE_HEIGHT), fill='gray')

            # If we're selecting menus then dim background and draw current menu selection
            # if menus are active draw over dimmed background
            dimmed_image=None
            if self.state.radio_state.left_menu_activated.is_active or \
               self.state.radio_state.right_menu_activated.is_active or \
               self.state.radio_state.selecting_left_menu.is_active or \
               self.state.radio_state.selecting_right_menu.is_active:

                dimmed_image= Image.eval(self.img, lambda x: x/4)
                self.draw_menu(draw=ImageDraw.Draw(dimmed_image))

            # Update image on LCD
            self.update(img=dimmed_image)


    def update(self,img=None):
        '''
        Update LCD. Use img or, or if none, the class image
        '''
        if img is None:
            self.disp.display(self.img)
        else:
            self.disp.display(img)


    def _get_text_hw_and_bb(self, t:str, font=None):
        '''
        Get boundingbox, text height and width give text str and font
        '''
        (x1,y1,x2,y2) = font.getbbox(t)
        text_height = abs(y2 - y1)
        text_width  = self.draw.textlength(t, font=font)
        return (x1,y1,x2,y2,text_height,text_width)


    def clear_screen(self):
        self.draw.rectangle((0, 0, self.WIDTH, self.HEIGHT), (0, 0, 0))


    def show_startup(self):
        self.clear_screen()
        self.draw_station_name("Dabble Radio")
        self.draw_ensemble("(c) digital-gangster 2025")
        self.update()


    def clear_levels(self, y:int=1):
        '''
        Clear the levels
        '''
        self.draw.rectangle((0,y,self.WIDTH,y+3), (0, 0, 0))

    def draw_levels(self, l:int, r:int, y:int=1, decay:int=1, rainbow:bool=False):
        '''
        Draw levels
        '''
        c=self.WIDTH/2
        y=self.HEIGHT-1
        lx1=c-l-1
        rx1=c+r+1
        l_line_colour_rgb = self.state.theme.viz_line if not rainbow else tuple(int(c*255) for c in colorsys.hsv_to_rgb(l/10, 0.8, 0.9))
        r_line_colour_rgb = self.state.theme.viz_line if not rainbow else tuple(int(c*255) for c in colorsys.hsv_to_rgb(r/10, 0.8, 0.9))
        self.clear_levels(y=y)
        self.draw.line((c,y,lx1,y),fill=l_line_colour_rgb, width=1)
        self.draw.line((c,y,rx1,y),fill=r_line_colour_rgb, width=1)
        self.draw.point((c,y),fill=self.state.theme.viz_dot)
        if l>self.last_max_l_level:
            self.last_max_l_level=l
        if r>self.last_max_r_level:
            self.last_max_r_level=r
        if self.last_max_l_level>0:
            self.draw.point((c-self.last_max_l_level,y),fill=self.state.theme.viz_dot)
            self.last_max_l_level -= decay
        if self.last_max_r_level>0:
            self.draw.point((c+self.last_max_r_level,y),fill=self.state.theme.viz_dot)
            self.last_max_r_level -= decay

    def draw_mode(self, clear:bool=True):
        '''
        Draw Mode e.g. Airplay or Radio
        '''
        # Calc bounding box for all text
        t = "Radio Airplay"
        (x1,y1,x2,y2,text_height,text_width) = self._get_text_hw_and_bb(t, font=self.ensemble_font)
        if clear:
            self.draw.rectangle((0,0, text_width, text_height), (0, 0, 0))

        ra_col = self.state.theme.mode_hilite if self.state.radio_state.mode==menus.PlayerMode.RADIO   else self.state.theme.ensemble
        ap_col = self.state.theme.mode_hilite if self.state.radio_state.mode==menus.PlayerMode.AIRPLAY else self.state.theme.ensemble
           
        # TODO: ?Calc text width, so no hardcoded x coords?
        # TODO: Themes will break this if the ensemble pt size is changed
        self.draw.text( (0, y1),"Radio" ,  font=self.ensemble_font, fill=ra_col, anchor="lt")
        self.draw.text( (35,y1),"Airplay", font=self.ensemble_font, fill=ap_col, anchor="lt")

    def draw_status(self, t:str, clear:bool=True):
        '''
        Draw Status. Use full bottom line
        For Airplay scroll Album name if too long
        '''
        if t=='' or t is None:
            t=" "
        text_x=0
        if self.scrolling_status:
            text_x = self.WIDTH - self.status_x
        (x1,y1,x2,y2,text_height,text_width) = self._get_text_hw_and_bb(t, font=self.ensemble_font)
        self.status_size_x = text_width
        if clear:
            self.draw.rectangle((0,self.HEIGHT-text_height-4, self.WIDTH, self.HEIGHT), (0, 0, 0))
        self.draw.text( (text_x,self.HEIGHT), t, font=self.ensemble_font, fill=self.state.theme.ensemble, anchor="ld")


    def draw_ensemble(self, t:str, clear:bool=True):
        '''
        Draw Ensemble. Divide bottom into 4. Ensemble text consumes 3/4 of screen
        '''
        (x1,y1,x2,y2,text_height,text_width) = self._get_text_hw_and_bb(t, font=self.ensemble_font)
        split_point = self.WIDTH//4*3
        if clear:
            self.draw.rectangle((0,self.HEIGHT-text_height-4, split_point, self.HEIGHT), (0, 0, 0))
        self.draw.text( (0,self.HEIGHT), t, font=self.ensemble_font, fill=self.state.theme.ensemble, anchor="ld")


    def draw_dab_type(self, t:str, clear:bool=True):
        '''
        Draw DAB Type. Divide bottom into 4. Type text consumes last 1/4 of screen
        ''' 
        if t=="" or t is None:
            t="DAB"
        (x1,y1,x2,y2,text_height,text_width) = self._get_text_hw_and_bb(t, font=self.ensemble_font)
        split_point = self.WIDTH//4*3
        if clear:
            self.draw.rectangle((split_point,self.HEIGHT-text_height-4, self.WIDTH, self.HEIGHT), (0, 0, 0))
        self.draw.text( (self.WIDTH,self.HEIGHT), t, font=self.ensemble_font, fill=self.state.theme.ensemble, anchor="rd")


    def draw_menu(self, draw=None):
        '''
        Draw on-screen menu
        '''
        draw = self.draw if draw is None else draw

        menu_id      = self.state.current_menu_item.menu_id
        display_text = self.state.current_menu_item.dstate()

        (x1,y1,x2,y2,cm_height,cm_width) = self._get_text_hw_and_bb(display_text, font=self.menu_sel_font)
        half_text_height = cm_height // 2

        x=0
        anchor="lt"
        menu_list=[]
        if self.state.radio_state.left_menu_activated.is_active or \
           self.state.radio_state.selecting_left_menu.is_active:
            anchor="lm"
            x=5
            menu_list=self.state.lm.menu_list 
            i=self.state.lm.menu_index
        elif self.state.radio_state.right_menu_activated.is_active or \
             self.state.radio_state.selecting_right_menu.is_active:
            anchor="rm"
            x=self.WIDTH
            menu_list=self.state.rm.menu_list 
            i=self.state.rm.menu_index

        # Get next/prev menu item to display
        if menu_list:
            prev_menu = menu_list[i-1].dstate() if i>0 else menu_list[-1].dstate()
            next_menu = menu_list[i+1].dstate() if i<len(menu_list)-1 else menu_list[0].dstate()

            draw.line((0, 0, 0, self.HEIGHT), width=1, fill="darkgrey")
            draw.text( (x, self.CENTRE_HEIGHT-cm_height), prev_menu, font=self.menu_sml_font, fill=self.state.theme.menu_sml, anchor='lm')
            draw.text( (x, self.CENTRE_HEIGHT), display_text, font=self.menu_sel_font, fill=self.state.theme.menu, anchor=anchor)
            draw.text( (x, self.CENTRE_HEIGHT+cm_height), next_menu, font=self.menu_sml_font, fill=self.state.theme.menu_sml, anchor='lm')
       

    def draw_station_name(self, t:str, clear:bool=False):
        '''
        Draw station name (or PAD) 
        '''
        if t is None or t=="":
            t=" "

        # Calc text x with scroll factor
        text_x = self.WIDTH - self.station_name_x

        (x1,y1,x2,y2) = self.draw.textbbox( (text_x,self.CENTRE_HEIGHT), t,font=self.station_font,anchor="lm")
        text_width  = self.draw.textlength(t, font=self.station_font)
        text_height = abs(y2-y1)
        if text_height==0:
            text_height=14
        half_th = text_height // 2
        self.station_name_size_x = text_width

        if clear:
            # Viz is 35 pixels high starting at 28
            self.draw.rectangle((0,self.HEIGHT-28-35,self.WIDTH,self.HEIGHT-28), (0, 0, 0))
        self.draw.text( (text_x, self.CENTRE_HEIGHT), t, font=self.station_font, fill=self.state.theme.station, anchor="lm")


    def scroll_status(self, speed=1, pause_for:int=900):
        if not self._pause_status_timer.expired():
            return

        if self.status_x == (self.WIDTH-speed):
            self._pause_status_timer.start(pause_for)

        self.status_x += int(speed)
        # Rotate back 
        if self.status_x >= self.status_size_x + self.WIDTH:
            self.status_x = 0


    def reset_status_scroll(self):
        self.status_x = self.WIDTH


    def scroll_station_name(self, speed=2, pause_for:int=900):
        if not self._pause_station_timer.expired():
            return

        if self.station_name_x == (self.WIDTH-speed):
            self._pause_station_timer.start(pause_for)

        self.station_name_x += int(speed)
        # Rotate back 
        if self.station_name_x >= self.station_name_size_x + self.WIDTH:
            self.station_name_x = 0
            self.state.get_next_message()


    def reset_station_name_scroll(self):
        self.station_name_x = self.WIDTH


    def draw_volume_bar(self, volume, max_volume=100, width=160, height=4, x=0, y=0, bar_margin=0):
        '''
        Draws a horizontal volume bar at position (x, y).
        '''
        bar_height = height // 2
        bar_y      = y + (height - bar_height) // 2

        # Bar background
        self.draw.rectangle([
            (x + bar_margin, bar_y), 
            (x + width - bar_margin, bar_y + bar_height)], self.state.theme.volume_bg)

        # Bar fill - ensure volume is +ve
        fill_width = int((width - 2 * bar_margin) * (abs(volume) / max_volume))
        self.draw.rectangle([
            (x + bar_margin, bar_y), 
            (x + bar_margin + fill_width, bar_y + bar_height)], fill=self.state.theme.volume)


    def scale_log(self, c, f):
        return c * math.log(float(1 + f),10);


    def fft(self, signal, is_mono:bool=False, use_window:bool=False, use_db_scale:bool=False, low_pass_cutoff:float=12000.0):
        '''
        Calc FFT of signal and process so we can visualise it.
        This is quick but processor intensive

        TODO: Move to audio_processing
        '''
        # Convert to mono
        if not is_mono:
            mono_signal = (signal[0::2] + signal[1::2]) / 2
        else:
            mono_signal = signal

        # Use lowpass filter to enhance lower frequencies so viz as more energy
        if low_pass_cutoff>0.0:
            nyq_freq = float(self.state.audio_processor.sample_rate)/2.0
            normalised_cutoff = low_pass_cutoff/nyq_freq
            b, a  = butter(4, normalised_cutoff, btype='lowpass', analog=False)
            mono_signal = filtfilt(b, a, mono_signal)

        # FFT magic
        # Window to reduce spectral oddities
        windowed_signal = mono_signal * np.hanning(len(mono_signal)) if use_window else mono_signal
        fft_data        = np.fft.rfft(windowed_signal)

        # FFT spectrum seems to be repeated so take what looks like
        # first "chunk" of repeated data
        fft_spectrum = fft_data[0:256]

        # Normalise fft, as values can be very large so we scale
        fft_spectrum    = np.abs(fft_spectrum/1024)

        if use_db_scale:
            # While accurate, looks rubbish
            fft_spectrum = 20 * np.log10(fft_spectrum + 1e-6)

        # Max value
        max_magnitude = np.max(fft_spectrum)
        return (max_magnitude, fft_spectrum)


    def graphic_equaliser(self, signal, base_y:int=0, height:int=60, width:int=0, fall_decay:int=2, use_log_scale:bool=False, is_mono:bool=False):
        '''
        Show frequencies using fft
        '''
        if signal is None:
            return

        if width==0:
            width=self.WIDTH

        (max_magnitude, fft_spectrum) = self.fft(signal, is_mono=is_mono)
        if max_magnitude==0.0:
            max_magnitude=0.01
        scale:float = float(height)/max_magnitude

        # Clear existing graphics
        self.draw.rectangle([
            (0,self.HEIGHT-height-base_y),
            (self.WIDTH,self.HEIGHT-base_y)], fill="black")

        # Map FFT bins to x-axis
        num_bins = len(fft_spectrum)

        # self.draw.line ( (0, self.HEIGHT - base_y - height, self.WIDTH , self.HEIGHT - base_y - height), fill=self.state.theme.viz_line)
        for x in range(0,self.WIDTH,2):
            # Map x pixel to FFT bin index
            bin_index = int((x / self.WIDTH) * num_bins)
            if bin_index >= num_bins:
                bin_index = num_bins - 1
            y = int(fft_spectrum[bin_index] * scale)
            # Draw line and dot
            self.draw.line ([
                (x, self.HEIGHT - base_y), 
                (x , self.HEIGHT - y - base_y)], 
                            fill=self.state.theme.viz_line, width=1)
            self.draw.point( 
                (x, self.HEIGHT - y - base_y), 
                            fill=self.state.theme.viz_dot)
            # Draw decay point
            if y > self.last_max_signal[x]:
                self.last_max_signal[x] = y

            if self.last_max_signal[x]>0:
                self.draw.point(
                        (x , self.HEIGHT - self.last_max_signal[x] - base_y),
                        fill=self.state.theme.viz_dot)
                self.last_max_signal[x] -= fall_decay


    def graphic_equaliser_bars(self, signal, base_y:int=0, height:int=60, width:int=0, fall_decay:int=3, use_log_scale:bool=True, num_bars:int=32, is_mono:bool=False):
        '''
        Show frequencies using fft, grouped into num_bars (default 32) bins.
        '''
        if signal is None:
            return
        if width == 0:
            width = self.WIDTH

        (max_magnitude, fft_spectrum) = self.fft(signal, is_mono=is_mono)
        if max_magnitude == 0.0:
            max_magnitude=0.01
        scale:float = float(height)/max_magnitude

        # Bin the FFT magnitudes into num_bars
        bin_size  = len(fft_spectrum) // num_bars
        bar_width = width // num_bars

        # Clear area
        self.draw.rectangle([
            (0, self.HEIGHT - height - base_y), 
            (self.WIDTH, self.HEIGHT - base_y)], 
                            fill="black")

        for x in range(0,num_bars):
            start = x * bin_size
            end = start + bin_size
            if end > len(fft_spectrum):
                end = len(fft_spectrum)
            # Aggregate magnitude within the bin
            # For first bar (bass) use mean as it looks better
            bar_value  = np.max(fft_spectrum[start:end]) if x>0 else np.mean(fft_spectrum[start:end])
            bar_height = int(bar_value * scale)
            x1 = x * bar_width
            x2 = x1 + bar_width - 2

            # Draw the bar (rectangle)
            self.draw.rectangle([
                (x1, self.HEIGHT - base_y - bar_height), 
                (x2, self.HEIGHT - base_y)], 
                                 fill=self.state.theme.viz_line, width=1)

            if bar_height > self.last_max_signal[x]:
                self.last_max_signal[x] = bar_height

            if self.last_max_signal[x]>0:
                self.draw.line([
                    (x1, self.HEIGHT - base_y - self.last_max_signal[x]), 
                    (x2, self.HEIGHT - base_y - self.last_max_signal[x])], 
                               fill=self.state.theme.viz_dot, width=1)
                self.last_max_signal[x] -= fall_decay


    def waveform(self, signal, base_y:int=0, height:int=60, width:int=0, fall_decay:int=4, is_mono:bool=False):
        '''
        Show waveform
        '''
        if signal is None:
            return
        if width==0:
            width=self.WIDTH

        if is_mono:
            mono_signal = signal
        else:
            mono_signal = (signal[0::2] + signal[1::2]) // 2

        # Clear area
        self.draw.rectangle([
            (0, self.HEIGHT - height - base_y), 
            (self.WIDTH, self.HEIGHT - base_y)], fill="black")

        max_magnitude = np.max(mono_signal)
        if max_magnitude==0.0:
            max_magnitude=0.01
        scale:float = float(height-2)/max_magnitude

        #num_bins = len(mono_signal)
        bin_size = len(mono_signal) // self.WIDTH
        base_y = self.CENTRE_HEIGHT

        for x in range(0,self.WIDTH,2):
            start = x * bin_size
            end = start + bin_size
            if end > len(mono_signal):
                end = len(mono_signal)
            v  = np.max(mono_signal[start:end])

            #bin_index = int((x / self.WIDTH) * num_bins)
            #if bin_index >= num_bins:
            #    bin_index = num_bins - 1
            #h = (mono_signal[bin_index] * scale) // 2 
            h = (v * scale) // 2 
            self.draw.line( [
                (x, self.HEIGHT - base_y - h) , 
                (x, self.HEIGHT - base_y + h) ], fill=self.state.theme.viz_line, width=1)
            self.draw.point( (x , self.HEIGHT - base_y - h), fill=self.state.theme.viz_dot)
            self.draw.point( (x , self.HEIGHT - base_y + h), fill=self.state.theme.viz_dot)


