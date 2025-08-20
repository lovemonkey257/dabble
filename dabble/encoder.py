import colorsys
import logging

from enum import Enum

logger = logging.getLogger(__name__)

class EncoderPosition(Enum):
    LEFT  = 1
    RIGHT = 2

class EncoderTypes(Enum):
    PIMORONI_RGB_BREAKOUT = 1
    FERMION_EC11_BREAKOUT = 2

class Encoder():
    def __init__(self, 
                 device_type=EncoderTypes.PIMORONI_RGB_BREAKOUT, 
                 pin_a:int=17, 
                 pin_b:int=27, 
                 pin_c:int=23,
                 button_press_callback=None,
                 button_position:int=EncoderPosition.LEFT,
                 bounce_time:float=0.1):

        self.device_type = device_type
        self.position    = button_position
        if device_type==EncoderTypes.PIMORONI_RGB_BREAKOUT:
            import ioexpander as io
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
            self.button = None
            self.device = None
            self.has_led = True

        elif device_type==EncoderTypes.FERMION_EC11_BREAKOUT:
            from gpiozero import Button, RotaryEncoder
            self.device = RotaryEncoder(a=pin_a,b=pin_b,wrap=True,max_steps=180)
            ## TODO: Validate PIN numbers

            if bounce_time<0:
                bounce_time=0.1
            elif bounce_time>1:
                bounce_time=1

            self.button=Button(pin_c, bounce_time=bounce_time)
            if button_press_callback is not None:
                logger.info("Button callback set")
                self.button.when_released = button_press_callback
            self.has_led = False

    def set_colour_by_value(self, colour):
        if self.device_type==EncoderTypes.PIMORONI_RGB_BREAKOUT:
            h = (colour % 360) / 360.0
            r, g, b = [int(c * self.PERIOD * self.BRIGHTNESS) for c in colorsys.hsv_to_rgb(h, 1.0, 1.0)]
            self.ioe.output(self.PIN_RED, r)
            self.ioe.output(self.PIN_GREEN, g)
            self.ioe.output(self.PIN_BLUE, b)
            return (r,g,b)
        return (0,0,0)

    def set_colour_by_rgb(self, rgb:tuple):
        if self.device_type==EncoderTypes.PIMORONI_RGB_BREAKOUT:
            r,g,b=rgb
            self.ioe.output(self.PIN_RED, r)
            self.ioe.output(self.PIN_GREEN, g)
            self.ioe.output(self.PIN_BLUE, b)
