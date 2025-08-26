
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

from . import exceptions, menus, encoder

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
    GRAPHIC_EQUALISER_BARS="graphic_equaliser_bars"

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
    pad_queue:list       = field(default_factory=list)
    audio_format:str     = ""
    genre:str            = ""
    dab_type:str         = ""
    current_msg:int      = MessageState.STATION

    volume:int           = 40
    peak_l:int           = 0
    peak_r:int           = 0
    signal:np.ndarray    = None

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

    def update(self, prop, value):
        '''
        Allow state to be changed using <obj>.update("prop",value)
        Means it can be used in lambdas which don't like <obj>.<prop>=<value>
        Returns new value (as returned by method not value passed which may not be the same)
        '''
        setattr(self, prop, value)
        return getattr(self, prop)

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
        # get next pad message (dont change mid display, only on rotate)
        if self.next_pad_message!="":
            self.last_pad_message=self.next_pad_message

class LCDUI():
    '''
    Manage the LCD display and UI
    '''
    def __init__(self, 
                 base_font_path:str="liberation/LiberationSans",
                 station_font_size:int=18, 
                 station_font_style:str="Regular",
                 ensemble_font_size:int=13,
                 ensemble_font_style:str="Regular",
                 menu_font_size:int=20,
                 menu_font_sml_size:int=17,
                 menu_font_style:str="Bold",
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

        self.station_font_file  = self.get_font_path(station_font_style)
        self.ensemble_font_file = self.get_font_path(ensemble_font_style)
        self.menu_font_file     = self.get_font_path(menu_font_style)

        try:
            self.station_font    = ImageFont.truetype(self.station_font_file, station_font_size)
            self.ensemble_font   = ImageFont.truetype(self.ensemble_font_file, ensemble_font_size)
            self.menu_sel_font   = ImageFont.truetype(self.menu_font_file, menu_font_size)
            self.menu_sml_font   = ImageFont.truetype(self.menu_font_file, menu_font_sml_size)
        except OSError as e:
            logging.error("Cannot load font: %s", self.base_font)
            raise exceptions.FontException

        self.station_name_x      = self.WIDTH 
        self.station_name_size_x = 0

        # TODO: Do we do themes???
        self.colours = {
            #"station":  '#FEFE33', 
            "station":  '#FFB703', 
            #"ensemble": '#B8B814', 
            "ensemble": '#023047', 
            "menu":     '#24D111', 
            "menu_sml": '#0B4205', 
            #"volume":   '#EFD4F7',
            "volume":   '#8ECAE6',
            #"volume_bg": (0, 102, 0),
            "volume_bg": '#023047',
            #"equaliser_line": 'darkviolet',
            #"equaliser_dot":  'deepskyblue'
            "viz_line": '#126782',
            "viz_dot":  '#8ECAE6'
        }
        self.last_l_level     = 0
        self.last_r_level     = 0
        self.last_max_l_level = 0
        self.last_max_r_level = 0
        self.last_max_signal  = np.zeros(1024)
        self.state            = UIState()

    def get_font_path(self, style):
        fp=str(self.font_dir  / f'{self.base_font}-{style}.ttf')
        logging.info("Font path: %s", fp)
        return fp
   

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
            # we will get smudges
            clear_sn = not self.state.visualiser_enabled or (self.state.peak_l==0 and self.state.peak_r==0)

            if reset_scroll:
                self.reset_station_name_scroll()

            if self.state.visualiser_enabled:
                if self.state.visualiser == GraphicState.GRAPHIC_EQUALISER:
                    self.graphic_equaliser(self.state.signal, base_y=28, height=35)
                elif self.state.visualiser == GraphicState.GRAPHIC_EQUALISER_BARS:
                    self.graphic_equaliser_bars(self.state.signal, base_y=28, height=35)
                elif self.state.visualiser == GraphicState.WAVEFORM:
                    self.waveform(self.state.signal, base_y=28, height=35)

            if not self.state.levels_enabled:
                self.clear_levels()
            else:
                self.draw_levels(self.state.peak_l, self.state.peak_r)

            vol_bar_y = self.HEIGHT - 27

            if self.state.station_enabled or self.state.radio_state.selecting_a_station.is_active:
                self.draw_station_name(self.state.get_current_message(), clear=clear_sn)
            else:
                self.draw_station_name(" ", clear=clear_sn)

            self.draw_volume_bar(self.state.volume, x=0,y=vol_bar_y, height=4)   
            self.draw_ensemble(self.state.ensemble, clear=True)
            self.draw_dab_type(self.state.dab_type, clear=True)

            if draw_centre_lines:
                self.draw.line((self.CENTRE_WIDTH, 0, self.CENTRE_WIDTH, self.HEIGHT),  fill='gray')
                self.draw.line((0, self.CENTRE_HEIGHT, self.WIDTH, self.CENTRE_HEIGHT), fill='gray')

            # Draw menu over dimmed image
            dimmed_image=None
            if self.state.radio_state.left_menu_activated.is_active or \
               self.state.radio_state.right_menu_activated.is_active or \
               self.state.radio_state.selecting_a_menu.is_active:
                dimmed_image= Image.eval(self.img, lambda x: x/3)
                self.draw_menu(draw=ImageDraw.Draw(dimmed_image))

            self.update(img=dimmed_image)


    def update(self,img=None):
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
        self.draw_ensemble("(c) digital-gangsters 2025")
        self.update()

    def clear_levels(self):
        # Clear the top part of the screen
        self.draw.rectangle((0,1,self.WIDTH,6), (0, 0, 0))

    def draw_levels(self, l:int, r:int, decay:int=2):
        c=self.WIDTH/2
        # logger.info("%d %d",l,r)
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
            self.draw.point((c+self.last_max_l_level,1),fill=self.colours['viz_dot'])
            self.draw.point((c-self.last_max_l_level,1),fill=self.colours['viz_dot'])
            self.last_max_l_level -= 2

        if r>self.last_max_r_level:
            self.last_max_r_level=r

        if self.last_max_l_level>0:
            self.draw.point((c+self.last_max_r_level,6),fill=self.colours['viz_dot'])
            self.draw.point((c-self.last_max_r_level,6),fill=self.colours['viz_dot'])
            self.last_max_r_level -= 2

    def draw_ensemble(self, t:str, clear:bool=True):
        (x1,y1,x2,y2,text_height,text_width) = self._get_text_hw_and_bb(t, font=self.ensemble_font)
        split_point = self.WIDTH//4*3
        if clear:
            self.draw.rectangle((0,self.HEIGHT-text_height-4, split_point, self.HEIGHT), (0, 0, 0))
        self.draw.text( (0,self.HEIGHT), t, font=self.ensemble_font, fill=self.colours["ensemble"],anchor="ld")

    def draw_dab_type(self, t:str, clear:bool=True):
        if t=="" or t is None:
            t="DAB"
        (x1,y1,x2,y2,text_height,text_width) = self._get_text_hw_and_bb(t, font=self.ensemble_font)
        split_point = self.WIDTH//4*3
        if clear:
            self.draw.rectangle((split_point,self.HEIGHT-text_height-4, self.WIDTH, self.HEIGHT), (0, 0, 0))
        self.draw.text( (self.WIDTH,self.HEIGHT), t, font=self.ensemble_font, fill=self.colours["ensemble"],anchor="rd")


    def draw_menu(self, draw=None):
        draw = self.draw if draw is None else draw

        menu_id      = self.state.current_menu_item.menu_id
        display_text = self.state.current_menu_item.dstate()

        (x1,y1,x2,y2,cm_height,cm_width) = self._get_text_hw_and_bb(display_text, font=self.menu_sel_font)
        half_text_height = cm_height // 2

        x=0
        anchor="lt"
        menu_list=[]
        if self.state.radio_state.left_menu_activated.is_active or \
           self.state.radio_state.selecting_a_menu.is_active:
            anchor="lm"
            x=5
            menu_list=self.state.lm.menu_list 
            i=self.state.lm.menu_index
        elif self.state.radio_state.right_menu_activated.is_active or \
           self.state.radio_state.selecting_a_menu.is_active:
            anchor="rm"
            x=self.WIDTH
            menu_list=self.state.rm.menu_list 
            i=self.state.rm.menu_index

        # Get next/prev menu item to display
        if menu_list:
            prev_menu = menu_list[i-1].dstate() if i>0 else menu_list[-1].dstate()
            next_menu = menu_list[i+1].dstate() if i<len(menu_list)-1 else menu_list[0].dstate()

            #draw.arc((-30, 0, 30, self.HEIGHT), start=270, end=90, fill="darkgrey")
            draw.line((0, 0, 0, self.HEIGHT), width=1, fill="darkgrey")
            draw.text( (x, self.CENTRE_HEIGHT-cm_height), prev_menu, font=self.menu_sml_font, fill=self.colours["menu_sml"], anchor='lm')
            draw.text( (x, self.CENTRE_HEIGHT), display_text, font=self.menu_sel_font, fill=self.colours["menu"], anchor=anchor)
            draw.text( (x, self.CENTRE_HEIGHT+cm_height), next_menu, font=self.menu_sml_font, fill=self.colours["menu_sml"], anchor='lm')
       

    def draw_station_name(self, t:str, clear:bool=False):
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
            #self.draw.rectangle((0,y1,self.WIDTH,y2+4), (0, 0, 0))
            # Viz is 35 pixels high starting at 28
            self.draw.rectangle((0,self.HEIGHT-28-35,self.WIDTH,self.HEIGHT-28), (0, 0, 0))
        self.draw.text( (text_x, self.CENTRE_HEIGHT), t, font=self.station_font, fill=self.colours["station"], anchor="lm")


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
        fft_mag = np.abs(np.fft.rfft(mono_signal))
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

            self.draw.line( ( i, self.HEIGHT - base_y, i , self.HEIGHT - y1 - base_y), fill=self.colours['viz_line'])
            self.draw.point( (i , self.HEIGHT - y1 - base_y), fill=self.colours['viz_dot'])

            if y1 > self.last_max_signal[i]:
                self.last_max_signal[i] = y1

            if self.last_max_signal[i]>0:
                self.draw.point(((i , self.HEIGHT - self.last_max_signal[i] - base_y)),fill=self.colours['viz_dot'])
                self.last_max_signal[i] -= fall_decay


    def graphic_equaliser_bars(self, signal, base_y:int=0, height:int=60, width:int=0, fall_decay:int=3, use_log_scale:bool=True, num_bars:int=32):
        '''
        Show frequencies using fft, grouped into num_bars (default 10) bins.
        '''
        if signal is None:
            return
        if width == 0:
            width = self.WIDTH

        # Convert to mono (average l/r channels)
        mono_signal = (signal[0::2] + signal[1::2]) / 2

        # FFT magic
        fft_mag = np.abs(np.fft.rfft(mono_signal))
        max_mag = np.max(fft_mag)
        if max_mag == 0.0:
            return

        # Calc scale
        scale: float = float(height) / max_mag

        # Bin the FFT magnitudes into num_bars
        bin_size = len(fft_mag) // num_bars
        bar_width = width // num_bars

        # Clear area
        self.draw.rectangle((0, self.HEIGHT - height - base_y, self.WIDTH, self.HEIGHT - base_y), fill="black")

        for i in range(num_bars):
            start = i * bin_size
            end = start + bin_size
            if end > len(fft_mag):
                end = len(fft_mag)
            # Aggregate magnitude within the bin (mean or max)
            #bar_value = np.mean(fft_mag[start:end])
            bar_value = np.max(fft_mag[start:end])
            bar_height = int(bar_value * scale)
            x1 = i * bar_width
            x2 = x1 + bar_width - 2

            # Draw the bar (rectangle)
            self.draw.rectangle([x1, self.HEIGHT - base_y - bar_height, x2, self.HEIGHT - base_y], fill=self.colours['viz_line'])

            if bar_height > self.last_max_signal[i]:
                self.last_max_signal[i] = bar_height

            if self.last_max_signal[i]>0:
                self.draw.line([x1, self.HEIGHT - base_y - self.last_max_signal[i], x2, self.HEIGHT - base_y - self.last_max_signal[i]], fill=self.colours['viz_dot'])
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
            self.draw.line( ( i, self.HEIGHT-y1-base_y, i+step , self.HEIGHT-y2-base_y), fill=self.colours['viz_line'])
            self.draw.line( ( i, self.HEIGHT-base_y, i , self.HEIGHT-y1-base_y), fill=self.colours['viz_line'])
            self.draw.point( (i , self.HEIGHT - y1 - base_y), fill=self.colours['viz_dot'])

            if y1 > self.last_max_signal[i]:
                self.last_max_signal[i] = y1

            if self.last_max_signal[i]>0:
                self.draw.point(((i , self.HEIGHT - self.last_max_signal[i] - base_y)),fill=self.colours['viz_dot'])
                self.last_max_signal[i] -= fall_decay

