import logging
import time
from PIL import Image, ImageDraw, ImageFont
import st7735
import colorsys
import time
import ioexpander as io
import json
import random
import subprocess
import signal
import sys
import pyaudio
import numpy as np
from pathlib import Path

dablin_proc=None

class Knob():
    def __init__(self):
        self.I2C_ADDR = 0x0F  # 0x18 for IO Expander, 0x0F for the encoder breakout
        self.PIN_RED = 1
        self.PIN_GREEN = 7
        self.PIN_BLUE = 2
        self.POT_ENC_A = 12
        self.POT_ENC_B = 3
        self.POT_ENC_C = 11
        self.BRIGHTNESS = 0.8                # Effectively the maximum fraction of the period that the LED will be on
        self.PERIOD = int(255 / self.BRIGHTNESS)  # Add a period large enough to get 0-255 steps at the desired brightness
        self.ioe = io.IOE(i2c_addr=self.I2C_ADDR, interrupt_pin=4)
        # Swap the interrupt pin for the Rotary Encoder breakout
        if self.I2C_ADDR == 0x0F:
            self.ioe.enable_interrupt_out(pin_swap=True)
        self.ioe.setup_rotary_encoder(1, self.POT_ENC_A, self.POT_ENC_B, pin_c=self.POT_ENC_C)
        self.ioe.set_pwm_period(self.PERIOD)
        self.ioe.set_pwm_control(divider=2)  # PWM as fast as we can to avoid LED flicker
        self.ioe.set_mode(self.PIN_RED, io.PWM, invert=True)
        self.ioe.set_mode(self.PIN_GREEN, io.PWM, invert=True)
        self.ioe.set_mode(self.PIN_BLUE, io.PWM, invert=True)

    def set_colour_by_value(self, colour):
        h = (colour % 360) / 360.0
        r, g, b = [int(c * self.PERIOD * self.BRIGHTNESS) for c in colorsys.hsv_to_rgb(h, 1.0, 1.0)]
        channel_knob.ioe.output(self.PIN_RED, r)
        channel_knob.ioe.output(self.PIN_GREEN, g)
        channel_knob.ioe.output(self.PIN_BLUE, b)
        return (r,g,b)

class UI():
    def __init__(self, station_font_size=18):
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

        self.img = Image.new('RGB', (self.WIDTH, self.HEIGHT), color=(0, 0, 0))
        self.draw = ImageDraw.Draw(self.img)

        self.station_font_size = station_font_size
        self.font_dir=Path("/usr/share/fonts/truetype/")
        self.station_font_file=str(self.font_dir / "/quicksand/Quicksand-Light.ttf")
        self.ensemble_font_file=str(self.font_dir / "/quicksand/Quicksand-Light.ttf")

        self.station_font = ImageFont.truetype(self.station_font_file, station_font_size)
        self.ensemble_font = ImageFont.truetype(self.ensemble_font_file, 12)

        # Set default font
        self.draw.font = self.station_font

        self.station_name_x = self.WIDTH 
        self.station_name_size_x = 0

    def update(self):
        self.disp.display(self.img)

    def clear(self):
        self.draw.rectangle((0, 0, self.WIDTH, self.HEIGHT), (0, 0, 0))
        #self.draw.line((self.WIDTH//2,0,self.WIDTH//2,self.HEIGHT))
        #self.draw.line((0,self.HEIGHT//2,self.WIDTH,self.HEIGHT//2))

    def levels(self,l,r):
        c=self.WIDTH/2
        lx1=c-(l/2)
        lx2=c+(l/2)
        rx1=c-(r/2)
        rx2=c+(r/2)
        self.draw.line((lx1,1,lx2,1),fill=(0, 180, 255), width=1)
        self.draw.line((rx1,6,rx2,6),fill=(0, 180, 255), width=1)
        
    def draw_ensemble(self, t:str):
        (x1,y1,x2,y2) = self.ensemble_font.getbbox(t)
        self.draw.text( (0,self.HEIGHT-(y2-y1)-10), t, font=self.ensemble_font, fill=(49, 117, 194))

    def draw_station_name(self, t:str):
        (x1,y1,x2,y2) = self.station_font.getbbox(t)

        # Center in x and y
        self.station_name_size_x = x2 - x1
        size_y = y2 - y1
        text_x = self.WIDTH - self.station_name_x
        text_y = self.HEIGHT//2 - size_y
        self.draw.text( (text_x, text_y), t, font=self.station_font, fill=(49, 117, 194))

    def scroll_station_name(self, speed=4):
        self.station_name_x += speed
        # Rotate back 
        self.station_name_x %= (self.station_name_size_x + self.WIDTH)

    def reset_scroll(self):
        self.station_name_x = self.WIDTH

class RadioStations():
    def __init__(self):
        self.stations={}
        with open("station-list.json") as j:
            self.stations = json.load(j)
        self.station_list=list(self.stations.keys())
    
    def tuning_details(self, station_name) -> tuple[str,str,str]|None:
        if station_name in self.stations:
            station_sid = self.stations[station_name]['sid']
            station_channel = self.stations[station_name]['channel']
            ensemble = self.stations[station_name]['ensemble']
            return (station_channel, station_sid, ensemble)
        return None

    def select_station(self, i):
        station_i=i%len(self.station_list)
        name=self.station_list[station_i]
        return (name, self.stations[name])


class RadioPlayer():
    def __init__(self, radio_stations:RadioStations=None):
        self.dablin_proc = None
        self.playing = "Not Playing Yet"
        self.ensemble=""
        self.channel=""
        self.sid=""
        self.radio_stations = radio_stations
        signal.signal(signal.SIGINT, self.signal_handler)

    def play(self,name):
        self.playing = name
        (self.channel,self.sid,self.ensemble) = self.radio_stations.tuning_details(name)
        self.dablin_proc=subprocess.Popen(
            ["dablin","-D","eti-cmdline","-d","eti-cmdline-rtlsdr","-c",self.channel,"-s",self.sid,"-I"]
        )

    def stop(self):
        self.currently_playing = None
        if self.dablin_proc is not None:
            self.dablin_proc.terminate()
        time.sleep(1)

    def signal_handler(self, sig, frame):
        print('You pressed Ctrl+C!')
        self.stop()
        time.sleep(1)
        sys.exit(0)

player=RadioPlayer(radio_stations=RadioStations())
player.play("Magic Radio")

channel_knob=Knob()

ui=UI()
ui.clear()
ui.draw_station_name("Dabble Radio")
ui.draw_ensemble("(c)digital-gangsters")
ui.update()

p=pyaudio.PyAudio()
stream=p.open(format=pyaudio.paInt16,
              channels=2,
              rate=44100,
              input=True,
              start=False, # Need to wait for dablin to catch up
              frames_per_buffer=1024)
maxValue=2**16

# Time user started twiddling
rotate_time=time.time()

# True if we are to change channel (after twiddling)
changing_station=False
new_station_name="?"

channel_knob_value=0

while True:

    # scroll text once stopped twiddling know and changed channel?
    if time.time() - rotate_time > 4:
        ui.scroll_station_name()
        if changing_station:
            ui.clear()
            ui.reset_scroll()
            ui.draw_station_name("Retuning..")
            ui.update()
            print("Changing channel to", new_station_name)
            player.stop()
            player.play(new_station_name)

        changing_station=False

    # Changing station? Knob being twiddled?
    if channel_knob.ioe.get_interrupt():
        channel_knob_value = channel_knob.ioe.read_rotary_encoder(1)
        channel_knob.ioe.clear_interrupt()

        (new_station_name, new_station_details)=player.radio_stations.select_station(channel_knob_value)

        print(new_station_name)
        ui.reset_scroll()
        ui.clear()
        ui.draw_station_name(new_station_name)
        rotate_time = time.time()
        changing_station=True
    
    if not changing_station:
        stream.start_stream()
        ui.clear()
        ui.draw_station_name(player.playing)
        ui.draw_ensemble(player.ensemble)

    channel_knob.set_colour_by_value(channel_knob_value)

    d=stream.read(1024,exception_on_overflow=False)
    wav=np.frombuffer(d,dtype='int16')
    ch_l=wav[0::2]
    ch_r=wav[1::2]
    # peakL = np.abs(np.max(ch_l)-np.min(ch_l))/maxValue*100
    peakL = np.abs(np.max(ch_l))/maxValue*100
    #peakR = np.abs(np.max(ch_r)-np.min(ch_r))/maxValue*100
    peakR = np.abs(np.max(ch_r))/maxValue*100

    ui.levels(peakL,peakR)
    ui.update()

    time.sleep(0.01)
