'''
Need: apt-get install python3-alsaaudio

Volume code: https://askubuntu.com/questions/689521/control-volume-using-python-script
'''

import logging
import alsaaudio
import numpy as np
import pyaudio

logger = logging.getLogger(__name__)

class AudioProcessing():

    def __init__(self, sample_rate:int=44100, frame_chunk_size:int=1535): #340):
        self._max_value=2**16
        
        self.p=pyaudio.PyAudio()
        self.stream:pyaudio.Stream = None
        self.sample_rate = sample_rate
        self.frames_chunk_size = frame_chunk_size # 160*4 #512

        '''
        try:
            # ALSA naming nightmare. Please pick sensible defaults...
            # Try PCM
            logger.info("Trying PCM Mixer")
            self.mixer = alsaaudio.Mixer('PCM')
        except alsaaudio.ALSAAudioError as e:
            logger.info("Nope. Trying Default Mixer")
            # Try "default" whatever it is
        '''
        self.mixer = alsaaudio.Mixer()

        self.volume=2
        self.ch_l = None
        self.ch_r = None
        self.signal = None
        self.channel = alsaaudio.MIXER_CHANNEL_ALL
        self.set_volume(self.volume)
        logger.info("Volume set to %d", self.volume)
       

    def log_volume(self, level:int, max_steps:int=60) -> int:
        """
        Map linear encoder position to logarithmic volume.
        Uses y = 100 * (x / max)^3 as an approximation for perceptual loudness.
        """
        x = level / max_steps           # Normalize to 0-1
        log_val = max_steps * (x ** 2)  # Cubic curve for logarithmic perception
        return int(log_val)       

    def vol_up(self, inc:int=2):
        self.set_volume(vol=self.volume+inc)
        return self.volume        

    def vol_down(self, inc:int=2):
        self.set_volume(vol=self.volume-inc)
        return self.volume
    
    def set_volume(self, vol:int=-1, use_log:bool=True):
        self.volume=vol
        # Make sure it's in range
        if self.volume<10:
            self.volume=10
        elif self.volume>80:
            self.volume=80

        actual_vol = self.log_volume(self.volume) if use_log else self.volume
        if actual_vol<10:
            actual_vol=10
        elif actual_vol>80:
            actual_vol=80
        self.mixer.setvolume(actual_vol, self.channel)

    def start(self):
        '''
        Start audio recording so we can get waveform etc

        When using some hardware there is no "record" interface, such as on
        the Adafruit speaker bonnet. Therefore you need to specify the device
        on the command line e.g. AUDIODEV=xx python ..
        '''
        self.stream=self.p.open(
                        format=pyaudio.paInt16,
                        channels=2,
                        rate=self.sample_rate,
                        input=True,
                        start=False, # Need to wait for dablin to catch up
                        frames_per_buffer=self.frames_chunk_size
        )
        return self.stream

    def get_sample(self) -> bool:
        '''
        Get live sample. Updates self.signal with stereo data
        returns:
            True: sample updated
            False: no sound available
        '''
        if self.stream is None:
            return False
        
        d=self.stream.read(self.frames_chunk_size, exception_on_overflow=False)
        self.signal=np.frombuffer(d,dtype='int16')
        # logging.debug("Latency %0.3fs Frames avail to read: %d", self.stream.get_input_latency(), self.stream.get_read_available())
        return True

    def get_peaks(self) -> tuple[float,float]:
        self.ch_l=self.signal[0::2]
        self.ch_r=self.signal[1::2]
        peak_l = np.abs(np.max(self.ch_l))/self._max_value*100.0
        peak_r = np.abs(np.max(self.ch_r))/self._max_value*100.0        
        # logger.debug("Peaks L:%0.3f R:%0.3f", peak_l, peak_r)
        return (peak_l, peak_r)

