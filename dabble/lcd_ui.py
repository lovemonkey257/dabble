import logging
from PIL import Image, ImageDraw, ImageFont
import st7735
from pathlib import Path
import colorsys

class LCDUI():
    
    def __init__(self, station_font_size=19, ensemble_font_size=12):
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
        self.station_font_file=str(self.font_dir  / "/quicksand/Quicksand-Regular.ttf")
        self.ensemble_font_file=str(self.font_dir / "/quicksand/Quicksand-Light.ttf")

        self.station_font = ImageFont.truetype(self.station_font_file, station_font_size)
        self.ensemble_font = ImageFont.truetype(self.ensemble_font_file, ensemble_font_size)

        self.station_name_x = self.WIDTH 
        self.station_name_size_x = 0

    def update(self):
        self.disp.display(self.img)

    def clear_screen(self):
        self.draw.rectangle((0, 0, self.WIDTH, self.HEIGHT), (0, 0, 0))
        #self.draw.line((self.WIDTH//2,0,self.WIDTH//2,self.HEIGHT))
        #self.draw.line((0,self.HEIGHT//2,self.WIDTH,self.HEIGHT//2))

    def levels(self,l,r):
        c=self.WIDTH/2
        lx1=c-(l/2)
        lx2=c+(l/2)
        rx1=c-(r/2)
        rx2=c+(r/2)
        l_line_colour_rgb = tuple(int(c*255) for c in colorsys.hsv_to_rgb(l/10, 0.8, 0.9))
        r_line_colour_rgb = tuple(int(c*255) for c in colorsys.hsv_to_rgb(r/10, 0.8, 0.9))
        #print(l,r,line_colour_rgb)
        # (0, 180, 255)
        self.draw.rectangle((0,1, self.WIDTH,6), (0, 0, 0))
        self.draw.line((lx1,1,lx2,1),fill=l_line_colour_rgb, width=1)
        self.draw.line((rx1,6,rx2,6),fill=r_line_colour_rgb, width=1)
        
    def draw_ensemble(self, t:str):
        (x1,y1,x2,y2) = self.ensemble_font.getbbox(t)
        self.draw.rectangle((0,self.HEIGHT-(y2-y1)-12, self.WIDTH, self.HEIGHT), (0, 0, 0))
        self.draw.text( (0,self.HEIGHT-2), t, font=self.ensemble_font, fill=(49, 117, 194),anchor="ld")

    def draw_station_name(self, t:str):
        (x1,y1,x2,y2) = self.station_font.getbbox(t)

        # Center in x and y
        self.station_name_size_x = x2 - x1
        size_y = y2 - y1
        text_x = self.WIDTH - self.station_name_x
        text_y = self.CENTRE_HEIGHT - size_y

        ## +12 is a fix for 
        self.draw.rectangle((0,text_y, self.WIDTH, text_y + size_y + 12), (0, 0, 0))
        self.draw.text( (text_x, self.CENTRE_HEIGHT), t, font=self.station_font, fill=(49, 117, 194), anchor="ls")

    def scroll_station_name(self, speed=2):
        self.station_name_x += speed
        # Rotate back 
        self.station_name_x %= (self.station_name_size_x + self.WIDTH)

    def reset_scroll(self):
        self.station_name_x = self.WIDTH

    def draw_volume(self, vol):
        '''
        Arc starts at 90 (0 pointing at top of screen)
    
        '''
        scaled_vol = int(vol * 3.6) # Now an angle
        s=0
        e=scaled_vol
        print("vol",vol,scaled_vol,s,e)
        x1=self.CENTRE_WIDTH-15
        x2=self.CENTRE_WIDTH+15
        y1=self.CENTRE_HEIGHT-15
        y2=self.CENTRE_HEIGHT+15
        self.draw.arc( [(x1,y1), (x2,y2)], start=s-90, end=e-90, fill=(50, 50, 50), width=5 )
