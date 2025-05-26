'''
Need: apt-get install python3-alsaaudio

Volume code: https://askubuntu.com/questions/689521/control-volume-using-python-script
'''

import pyaudio
import numpy as np
import alsaaudio

class AudioProcessing():

    def __init__(self):
        self.max_value=2**16
        self.p=pyaudio.PyAudio()
        self.stream=None
        self.mixer = alsaaudio.Mixer()
        self.volume=50 #self.mixer.getvolume()

    def vol_up(self, vinc:int=1):
        self.volume+=vinc
        if self.volume>100:
            self.volume=100
        self.mixer.setvolume(self.volume)

    def vol_down(self, vinc:int=1):
        self.volume-=vinc
        if self.volume<0:
            self.volume=0
        self.mixer.setvolume(self.volume)
    
    def set_volume(self, vol:int):
        if vol>=0 and vol<=100:
            self.volume = vol
            self.mixer.setvolume(self.volume)

    def start(self):
        self.stream=self.p.open(format=pyaudio.paInt16,
                    channels=2,
                    rate=44100,
                    input=True,
                    start=False, # Need to wait for dablin to catch up
                    frames_per_buffer=1024)
        return self.stream

    def get_peaks(self):
        if self.stream is None:
            return (0,0)
        
        d=self.stream.read(1024,exception_on_overflow=False)
        wav=np.frombuffer(d,dtype='int16')
        ch_l=wav[0::2]
        ch_r=wav[1::2]
        # peak_l = np.abs(np.max(ch_l)-np.min(ch_l))/self.max_value*100
        peak_l = np.abs(np.max(ch_l))/self.max_value*100
        #peak_rR = np.abs(np.max(ch_r)-np.min(ch_r))/self.max_value*100
        peak_r = np.abs(np.max(ch_r))/self.max_value*100        
        return (peak_l, peak_r)
