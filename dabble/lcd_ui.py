
import colorsys
import logging
import math
import functools
from dataclasses import dataclass, field
from enum import Enum,StrEnum
from pathlib import Path
import threading

import numpy as np
import st7735
from PIL import Image, ImageDraw, ImageFont

from . import exceptions, menu, encoder

logger = logging.getLogger(__name__)

# Constants
class Locks:
    INTERFACE = threading.Lock()

class MessageState(Enum):
    STATION  = 0
    LAST_PAD = 1

class GraphicState(StrEnum):
    WAVEFORM="waveform"
    GRAPHIC_EQUALISER="graphic_equaliser"

@dataclass
class UIState():
    station_name:str     = ""
    ensemble:str         = ""
    last_pad_message:str = ""
    audio_format:str     = ""
    genre:str            = ""
    dab_type:str         = ""
    current_msg:int      = MessageState.STATION

    volume:int           = 40
    peak_l:int           = 0
    peak_r:int           = 0
    signal:np.ndarray    = None

    radio_state:menu.StateMachine  = None
    current_menu_item:str          = None
    lm:menu.Menu                   = None # Left Menu
    rm:menu.Menu                   = None # Right Menu
    station_timer:threading.Thread = None
    left_encoder:encoder.Encoder   = None
    right_encoder:encoder.Encoder  = None

    pulse_left_led_encoder:bool = False
    pulse_right_led_encoder:bool = False
    left_led_rgb         = (255,255,255)
    right_led_rgb        = (255,255,255)

    visualiser_enabled:bool = True
    visualiser:GraphicState = GraphicState.GRAPHIC_EQUALISER
    levels_enabled:bool  = True

    def update(self, prop, value):
        '''
        Allow state to be changed using <obj>.update("prop",value)
        Means it can be used in lambdas which don't like <obj>.<prop>=<value>
        '''
        setattr(self, prop, value)

    def get_pad_message(self):
        '''
        Display next PAD message

        TODO: Sometimes msgs are broadcast in quick succession. Currently I display 
              the last one immediately. Should I queue them and then repeat the last
              message?
        '''
        return self.last_pad_message if self.last_pad_message else ""
    
    def get_current_message(self):
        '''
        Get the current message on the UI
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


class LCDUI():

    def __init__(self, 
                 base_font_path:str="liberation/LiberationSans",
                 station_font_size:int=18, 
                 station_font_style:str="Regular",
                 ensemble_font_size:int=13,
                 ensemble_font_style:str="Regular",
                 menu_font_size:int=20,
                 menu_font_style:str="Regular",
                 dc_gpio:str="GPIO9",
                 backlight_gpio:str="GPIO16"):

        self._lock = Locks.INTERFACE

        # Create ST7735 LCD display class. Taken from Pimoroni docs
        # 160 x 80 full colour
        # Be mindful of GPIO use when using other devices
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
        self.CENTRE_HEIGHT = self.HEIGHT//2 # 40 (80/2)
        self.CENTRE_WIDTH  = self.WIDTH//2  # 80 (160/2)

        self.img = Image.new('RGB', (self.WIDTH, self.HEIGHT), color=(0, 0, 0))
        self.draw = ImageDraw.Draw(self.img)

        ## Fonts!
        # Beware of style as it forms part of file name
        self.station_font_size  = station_font_size
        self.ensemble_font_size = ensemble_font_size
        self.menu_font_size     = menu_font_size

        self.font_dir=Path("/usr/share/fonts/truetype/")
        self.base_font = base_font_path

        self.station_font_file  = self.get_font_path(station_font_style.capitalize())
        self.ensemble_font_file = self.get_font_path(ensemble_font_style.capitalize())
        self.menu_font_file     = self.get_font_path(menu_font_style.capitalize())

        try:
            self.station_font    = ImageFont.truetype(self.station_font_file, station_font_size)
            self.ensemble_font   = ImageFont.truetype(self.ensemble_font_file, ensemble_font_size)
            self.menu_sel_font   = ImageFont.truetype(self.menu_font_file, menu_font_size)
            self.menu_font       = ImageFont.truetype(self.menu_font_file, menu_font_size-2)
        except OSError as e:
            logging.error("Cannot load font: %s", self.base_font)
            raise exceptions.FontException

        self.station_name_x      = self.WIDTH 
        self.station_name_size_x = 0

        self.colours = {
            "ensemble": '#B8B814', # (251, 80, 18),
            "station":  '#FEFE33', # (255, 10,10),
            "menu":     '#00FF00', # (0, 255, 0),
            "volume":   '#EFD4F7', # (203, 186, 237),
            "volume_bg": (0, 102, 0),
            "equaliser_line": 'darkviolet',
            "equaliser_dot":  'deepskyblue'
        }
        self.last_l_level     = 0
        self.last_r_level     = 0
        self.last_max_l_level = 0
        self.last_max_r_level = 0
        self.last_max_signal  = np.zeros(1024)
        self.state            = UIState()

    def get_font_path(self, style):
        return str(self.font_dir  / f'{self.base_font}-{style}.ttf')
   

    def draw_interface(self, reset_scroll=False, dim_screen=True):
        '''
        Draw the entire interface
        '''
        with self._lock:
            # Normal display
            clear_sn = not self.state.visualiser_enabled
            if reset_scroll:
                self.reset_station_name_scroll()

            if self.state.visualiser_enabled:
                if self.state.visualiser == GraphicState.GRAPHIC_EQUALISER:
                    self.graphic_equaliser(self.state.signal, base_y=31, height=35)
                elif self.state.visualiser == GraphicState.WAVEFORM:
                    self.waveform(self.state.signal, base_y=31, height=35)
            if self.state.levels_enabled:
                self.levels(self.state.peak_l, self.state.peak_r) 
            else:
                self.clear_levels()

            self.draw_station_name(self.state.get_current_message(), clear=clear_sn)
            self.draw_volume_bar(self.state.volume, x=0,y=self.HEIGHT-30, height=2)   
            self.draw_ensemble(self.state.ensemble, clear=True)
            self.draw_dab_type(self.state.dab_type, clear=True)

            # Draw menu over dimmed image
            dimmed_image=None
            if self.state.radio_state.left_menu_activated.is_active or \
               self.state.radio_state.right_menu_activated.is_active:
                dimmed_image= Image.eval(self.img, lambda x: x / 2)
                self.draw_menu(draw=ImageDraw.Draw(dimmed_image))

            self.update(img=dimmed_image)


    def update(self,img=None):
        if img is None:
            self.disp.display(self.img)
        else:
            self.disp.display(img)


    def clear_screen(self, draw_center_lines:bool=False):
        self.draw.rectangle((0, 0, self.WIDTH, self.HEIGHT), (0, 0, 0))
        if draw_center_lines:
            self.draw.line((self.WIDTH//2,0,self.WIDTH//2,self.HEIGHT), fill='gray')
            self.draw.line((0,self.HEIGHT//2,self.WIDTH,self.HEIGHT//2), fill='gray')

    def show_startup(self):
        self.clear_screen()
        self.draw_station_name("Dabble Radio")
        self.draw_ensemble("(c) digital-gangsters 2025")
        self.update()

    def clear_levels(self):
        # Clear the top part of the screen
        self.draw.rectangle((0,1,self.WIDTH,6), (0, 0, 0))

    def levels(self,l,r):
        c=self.WIDTH/2
        lx1=c-l
        lx2=c+l
        rx1=c-r
        rx2=c+r
        l_line_colour_rgb = tuple(int(c*255) for c in colorsys.hsv_to_rgb(l/10, 0.8, 0.9))
        r_line_colour_rgb = tuple(int(c*255) for c in colorsys.hsv_to_rgb(r/10, 0.8, 0.9))

        self.clear_levels()

        # Draw the levels
        self.draw.line((lx1,1,lx2,1),fill=l_line_colour_rgb, width=1)
        self.draw.line((rx1,6,rx2,6),fill=r_line_colour_rgb, width=1)

        if l>self.last_max_l_level:
            self.last_max_l_level=l
        if self.last_max_l_level>0:
            self.draw.point((c+self.last_max_l_level,1),fill='blue')
            self.draw.point((c-self.last_max_l_level,1),fill='blue')
            self.last_max_l_level -= 2

        if r>self.last_max_r_level:
            self.last_max_r_level=r
        if self.last_max_l_level>0:
            self.draw.point((c+self.last_max_r_level,6),fill='blue')
            self.draw.point((c-self.last_max_r_level,6),fill='blue')
            self.last_max_r_level -= 2
    

    def _get_text_hw_and_bb(self, t:str, font=None):
        '''
        Get boundingbox, text height and width give text str and font
        '''
        (x1,y1,x2,y2) = font.getbbox(t)
        text_height = y2 - y1
        text_width  = self.draw.textlength(t, font=font)
        return (x1,y1,x2,y2,text_height,text_width)
    

    def draw_ensemble(self, t:str, clear:bool=True):
        (x1,y1,x2,y2,text_height,text_width) = self._get_text_hw_and_bb(t, font=self.ensemble_font)
        mid_point = self.WIDTH//2
        if clear:
            self.draw.rectangle((0,self.HEIGHT-text_height-4, mid_point, self.HEIGHT), (0, 0, 0))
        self.draw.text( (0,self.HEIGHT), t, font=self.ensemble_font, fill=self.colours["ensemble"],anchor="ld")


    def draw_dab_type(self, t:str, clear:bool=True):
        (x1,y1,x2,y2,text_height,text_width) = self._get_text_hw_and_bb(t, font=self.ensemble_font)
        mid_point = self.WIDTH//2
        if clear:
            self.draw.rectangle((mid_point,self.HEIGHT-text_height-4, self.WIDTH, self.HEIGHT), (0, 0, 0))
        self.draw.text( (self.WIDTH,self.HEIGHT), t, font=self.ensemble_font, fill=self.colours["ensemble"],anchor="rd")


    def draw_menu(self, draw=None):
        draw = self.draw if draw is None else draw

        (x1,y1,x2,y2,cm_height,cm_width) = self._get_text_hw_and_bb(self.state.current_menu_item, font=self.menu_sel_font)
        half_text_height = cm_height // 2

        x=0
        anchor="lt"
        menu_list=[]
        if self.state.radio_state.left_menu_activated.is_active:
            anchor="lt"
            x=5
            m=self.state.lm.menu_list 
        elif self.state.radio_state.right_menu_activated.is_active:
            anchor="rt"
            x=self.WIDTH
            m=self.state.rm.menu_list 

        # TODO draw other menu items
        draw.text( (x, self.CENTRE_HEIGHT-half_text_height), self.state.current_menu_item, font=self.menu_sel_font, fill=self.colours["menu"], anchor=anchor)
       

    def draw_station_name(self, t:str, clear:bool=False):
        if t is None:
            t=" "

        (x1,y1,x2,y2,text_height,text_width) = self._get_text_hw_and_bb(t, font=self.station_font)
        half_text_height = text_height // 2
        # Calc text x with scroll factor
        text_x = self.WIDTH - self.station_name_x
        self.station_name_size_x = text_width
        if clear:
            self.draw.rectangle((0, self.CENTRE_HEIGHT-half_text_height, self.WIDTH, self.CENTRE_HEIGHT+half_text_height), (0, 0, 0))
        self.draw.text( (text_x, self.CENTRE_HEIGHT-half_text_height), t, font=self.station_font, fill=self.colours["station"], anchor="lt")

    def scroll_station_name(self, speed=3):
        with self._lock:
            self.station_name_x += int(speed)
            # Rotate back 
            if self.station_name_x >= self.station_name_size_x + self.WIDTH:
                self.station_name_x = 0
                self.state.get_next_message()

    def reset_station_name_scroll(self):
        with self._lock:
            self.station_name_x = self.WIDTH

    def draw_volume_bar(self, volume, max_volume=100, width=160, height=4, x=0, y=0, bar_margin=0):
            """
            Draws a horizontal volume bar at position (x, y).
            :param volume: Current volume (0-max_volume)
            :param max_volume: Maximum volume value
            :param width: Width of the bar
            :param height: Height of the bar
            :param x: X position on the screen
            :param y: Y position on the screen
            """
            bar_height = height // 2
            bar_y = y + (height - bar_height) // 2

            # Bar background
            self.draw.rectangle([x + bar_margin, bar_y, x + width - bar_margin, bar_y + bar_height], self.colours['volume_bg'])

            # Bar fill
            fill_width = int((width - 2 * bar_margin) * (volume / max_volume))
            self.draw.rectangle([x + bar_margin, bar_y, x + bar_margin + fill_width, bar_y + bar_height], fill=self.colours['volume'])

    def scale_log(self, c, f):
        return c * math.log(float(1 + f),10);

    def graphic_equaliser(self, signal, base_y:int=0, height:int=60, width:int=0, fall_decay:int=3, use_log_scale:bool=False):
        '''
        Show frequencies using fft
        '''
        if signal is None:
            return
        if width==0:
            width=self.WIDTH

        # Convert to mono (average l/r channels)
        mono_signal = (signal[0::2] + signal[1::2]) / 2

        # FFT magic
        fft_mag   = np.abs(np.fft.rfft(mono_signal))
        max_mag = np.max(fft_mag)
        if max_mag==0.0:
            return
       
        # Calc scale
        scale:float = float(height)/max_mag
        if use_log_scale:
            c = max_mag/math.log(max_mag+1,10)/2;

        # Scale steps. Does mean we may miss some freq components.
        end_range = len(fft_mag) - 1
        step      = int(len(fft_mag)/width)
        # If too small enforce step size
        if step<=1:
            step=2

        # Clear
        self.draw.rectangle((0,self.HEIGHT-height-base_y,self.WIDTH,self.HEIGHT-base_y), fill="black")

        y1=0
        for i in range(0, end_range, step):
            if i==0:
                continue
            f=fft_mag[i]
            if use_log_scale:
                v = round(self.scale_log(c, f));
                y1 = int(v * scale)
            else:
                y1 = int(f * scale)

            self.draw.line( ( i, self.HEIGHT - base_y, i , self.HEIGHT - y1 - base_y), fill=self.colours['equaliser_line'])
            self.draw.point( (i , self.HEIGHT - y1 - base_y), fill=self.colours['equaliser_dot'])

            if y1 > self.last_max_signal[i]:
                self.last_max_signal[i] = y1

            if self.last_max_signal[i]>0:
                self.draw.point(((i , self.HEIGHT - self.last_max_signal[i] - base_y)),fill='white')
                self.last_max_signal[i] -= fall_decay


    def waveform(self, signal, base_y:int=0, height:int=60, width:int=0, fall_decay:int=4):
        '''
        Show waveform
        '''
        if signal is None:
            return
        if width==0:
            width=self.WIDTH

        mono_signal = np.abs((signal[0::2] + signal[1::2]) / 2)
        max_mag = np.max(mono_signal)
        if max_mag==0:
            return
       
        # Calc scale
        step=int(len(mono_signal)/width)
        end_range = len(mono_signal)-step
        scale:float = float(height)/max_mag

        # Clear
        self.draw.rectangle((0,self.HEIGHT-height-base_y,self.WIDTH,self.HEIGHT-base_y), fill="black")

        # Draw waveform
        for i in range(1,end_range,step):
            y1 = int(mono_signal[i] * scale)
            y2 = int(mono_signal[i+step] * scale)
            self.draw.line( ( i, self.HEIGHT-y1-base_y, i+step , self.HEIGHT-y2-base_y), fill=self.colours['equaliser_dot'])
            self.draw.line( ( i, self.HEIGHT-base_y, i , self.HEIGHT-y1-base_y), fill=self.colours['equaliser_line'])
            self.draw.point( (i , self.HEIGHT - y1 - base_y), fill='white')

            if y1 > self.last_max_signal[i]:
                self.last_max_signal[i] = y1

            if self.last_max_signal[i]>0:
                self.draw.point(((i , self.HEIGHT - self.last_max_signal[i] - base_y)),fill='white')
                self.last_max_signal[i] -= fall_decay



