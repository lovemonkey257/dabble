from dataclasses import dataclass, field
import logging
from PIL import Image, ImageDraw, ImageFont
import st7735
from pathlib import Path
import colorsys
import numpy as np
import math
from enum import StrEnum

class GraphicState(StrEnum):
    WAVEFORM="waveform"
    GRAPHIC_EQUALISER="graphic_equaliser"

@dataclass
class UIState():
    station_name:str     = ""
    ensemble:str         = ""
    last_pad_message:str = ""
    volume:int           = 40
    peak_l:int           = 0
    peak_r:int           = 0
    signal:np.ndarray    = None
    levels_enabled:bool  =  True
    dab_type:str         = ""
    current_msg:int      = 0 # 0=Station, 1=Last PAD
    pulse_left_led_encoder:bool = False
    left_led_rgb         = (255,255,255)
    pulse_right_led_encoder:bool = False
    right_led_rgb        = (255,255,255)
    visualiser_enabled:bool = True
    visualiser:GraphicState = GraphicState.GRAPHIC_EQUALISER

    def get_pad_message(self):
        return self.last_pad_message if self.last_pad_message else ""
    
    def get_current_message(self):
            return self.station_name if self.current_msg==0 else self.get_pad_message()

    def get_next_message(self):
        self.current_msg+=1
        if self.current_msg > 1:
            self.current_msg=0

class LCDUI():
   
    def __init__(self, station_font_size=19, ensemble_font_size=13):
        # Create ST7735 LCD display class.
        self.disp = st7735.ST7735(
            port=0,
            cs=st7735.BG_SPI_CS_FRONT,# BG_SPI_CS_BACK or BG_SPI_CS_FRONT. BG_SPI_CS_FRONT (eg: CE1) for Enviro Plus
            dc="GPIO9",               # "GPIO9" / "PIN21". "PIN21" for a Pi 5 with Enviro Plus
            backlight="GPIO19",       # "PIN18" for back BG slot, "PIN19" for front BG slot. "PIN32" for a Pi 5 with Enviro Plus
            rotation=90,
            spi_speed_hz=4000000
        )

        self.disp.begin()
        self.WIDTH = self.disp.width
        self.HEIGHT = self.disp.height
        self.CENTRE_HEIGHT = self.HEIGHT//2 # 40 (80/2)
        self.CENTRE_WIDTH = self.WIDTH//2   # 80 (160/2)

        self.img = Image.new('RGB', (self.WIDTH, self.HEIGHT), color=(0, 0, 0))
        self.draw = ImageDraw.Draw(self.img)

        self.station_font_size = station_font_size

        self.font_dir=Path("/usr/share/fonts/truetype/")
        self.base_font = "liberation/LiberationSans"  # "quickstand/Quicksand"

        self.station_font_file  = self.get_font_path("Regular") # Regular # str(self.font_dir  / "/quicksand/Quicksand-Bold.ttf")
        self.ensemble_font_file = self.get_font_path("Regular") # Light # str(self.font_dir / "/quicksand/Quicksand-Light.ttf")

        self.station_font = ImageFont.truetype(self.station_font_file, station_font_size)
        self.ensemble_font = ImageFont.truetype(self.ensemble_font_file, ensemble_font_size)
        self.vol_font = ImageFont.truetype(self.ensemble_font_file, ensemble_font_size)

        self.station_name_x = self.WIDTH 
        self.station_name_size_x = 0

        self.colours = {
            "ensemble": '#B8B814', # (251,80, 18),
            "station":  '#FEFE33', # (255, 243,10),
            "volume":   '#EFD4F7', # (203, 186, 237),
            "volume_bg": (0, 102, 0),
            "equaliser_line": 'darkviolet',
            "equaliser_dot":  'deepskyblue'
        }
        self.last_l_level=0
        self.last_r_level=0
        self.last_max_l_level=0
        self.last_max_r_level=0
        self.last_max_signal=np.zeros(1024)

        self.state = UIState()

    def get_font_path(self, style):
        return str(self.font_dir  / f'{self.base_font}-{style}.ttf')
    
    def draw_interface(self, reset_scroll=False):
        '''
        Draw the entire interface
        '''
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

        clear_sn = not  self.state.visualiser_enabled
        # self.draw_station_name(self.state.station_name, clear=clear_sn)
        self.draw_station_name(self.state.get_current_message(), clear=clear_sn)
        self.draw_ensemble(self.state.ensemble, clear=True)
        self.draw_dab_type(self.state.dab_type, clear=True)
        self.draw_volume_bar(self.state.volume, x=0,y=self.HEIGHT-30, height=2)   
        self.update()

    def update(self):
        self.disp.display(self.img)

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
            self.draw.point((c+self.last_max_l_level,1),fill='white')
            self.draw.point((c-self.last_max_l_level,1),fill='white')
            self.last_max_l_level -= 2

        if r>self.last_max_r_level:
            self.last_max_r_level=r
        if self.last_max_l_level>0:
            self.draw.point((c+self.last_max_r_level,6),fill='white')
            self.draw.point((c-self.last_max_r_level,6),fill='white')
            self.last_max_r_level -= 2
        
        
    def draw_ensemble(self, t:str, clear:bool=False):
        (x1,y1,x2,y2) = self.ensemble_font.getbbox(t)
        text_w = self.WIDTH//2
        if clear:
            self.draw.rectangle((0,self.HEIGHT-(y2-y1)-12, text_w, self.HEIGHT), (0, 0, 0))
        self.draw.text( (0,self.HEIGHT-2), t, font=self.ensemble_font, fill=self.colours["ensemble"],anchor="ld")

    def draw_dab_type(self, t:str, clear:bool=False):
        (x1,y1,x2,y2) = self.ensemble_font.getbbox(t)
        text_w = self.draw.textlength(t, font=self.ensemble_font)
        if clear:
            self.draw.rectangle((self.WIDTH//2,self.HEIGHT-(y2-y1)-12, self.WIDTH, self.HEIGHT), (0, 0, 0))
        self.draw.text( (self.WIDTH-text_w,self.HEIGHT-2), t, font=self.ensemble_font, fill=self.colours["ensemble"],anchor="ld")

    def draw_station_name(self, t:str, clear:bool=False):
        (x1,y1,x2,y2) = self.station_font.getbbox(t)

        # Center in x and y
        #self.station_name_size_x = x2 - x1
        self.station_name_size_x = self.draw.textlength(t, font=self.station_font)
        size_y = y2 - y1
        text_x = self.WIDTH - self.station_name_x
        text_y = self.CENTRE_HEIGHT - size_y

        ## TODO: +12 is a fix and make it works. Not sure why. Poss text anchor
        if clear:
            self.draw.rectangle((0,text_y, self.WIDTH, text_y + size_y + 12), (0, 0, 0))
        self.draw.text( (text_x, self.CENTRE_HEIGHT), t, font=self.station_font, fill=self.colours["station"], anchor="ls")

    def scroll_station_name(self, speed=3):
        self.station_name_x += int(speed)

        # Rotate back 
        if self.station_name_x>= self.station_name_size_x + self.WIDTH:
            self.station_name_x = 0
            self.state.get_next_message()
        #self.station_name_x %= int((self.station_name_size_x + self.WIDTH))


    def reset_station_name_scroll(self):
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
            '''
            text = f"{volume}/{max_volume}"
            text_w = self.draw.textlength(text, font=self.vol_font)
            bbox = self.vol_font.getbbox(text)
            text_h = bbox[3] - bbox[1]
            text_x = x + (width - text_w) // 2
            text_y = bar_y + bar_height + 2
            self.draw.text((text_x, text_y), text, fill=self.colours["volume"], font=self.vol_font)
            '''

    def scale_log(self, c, f):
        return c * math.log(float(1 + f),10);

    def graphic_equaliser(self, signal, base_y:int=0, height:int=60, width:int=0, fall_decay:int=2, use_log_scale:bool=False):
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
        if max_mag==0:
            return
       
        # Calc scale
        scale = height/max_mag
        if use_log_scale:
            c = max_mag/math.log(max_mag+1,10)/2;

        # Scale steps
        end_range = len(fft_mag) - 1
        step  = int(len(fft_mag)/width)
        # If too small enforce step size
        if step<=1:
            step=2

        # Clear
        self.draw.rectangle((0,self.HEIGHT-height-base_y,self.WIDTH,self.HEIGHT-base_y), fill="black")

        y1=0
        for i in range(1, end_range, step):
            if use_log_scale:
                v = round(self.scale_log(c, fft_mag[i]));
                y1 = int(v * scale)
            else:
                y1 = int(fft_mag[i] * scale)

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
        scale = height/max_mag

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
