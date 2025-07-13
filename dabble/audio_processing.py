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

    def __init__(self, sample_rate:int=44100, frame_chunk_size:int=340):
        self._max_value=2**16
        
        self.p=pyaudio.PyAudio()
        self.stream:pyaudio.Stream = None
        self.sample_rate = sample_rate
        self.frames_chunk_size = frame_chunk_size # 160*4 #512

        self.mixer = alsaaudio.Mixer()
        self.volume=2
        self.ch_l = None
        self.ch_r = None
        self.signal = None
        self.channel = alsaaudio.MIXER_CHANNEL_ALL
        self.set_volume(self.volume)
        logger.info("Volume set to %d", self.volume)
        

    def vol_up(self, vinc:int=2):
        self.volume+=vinc
        if self.volume>100:
            self.volume=100
        self.set_volume(self.volume)
        return self.volume        

    def vol_down(self, vinc:int=2):
        self.volume-=vinc
        if self.volume<0:
            self.volume=0
        self.set_volume(self.volume)
        return self.volume
    
    def set_volume(self, vol:int):
        if vol<0:
            vol=0
        elif vol>80:
            vol=80
        self.volume = vol
        self.mixer.setvolume(vol, self.channel)

    def start(self):
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
        return True

    def get_peaks(self) -> tuple[float,float]:
        self.ch_l=self.signal[0::2]
        self.ch_r=self.signal[1::2]
        peak_l = np.abs(np.max(self.ch_l))/self._max_value*100.0
        peak_r = np.abs(np.max(self.ch_r))/self._max_value*100.0        
        logger.debug("Peaks L:%d R:%d", peak_l, peak_r)
        return (peak_l, peak_r)
