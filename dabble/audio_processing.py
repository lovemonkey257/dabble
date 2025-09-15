'''
Need: apt-get install python3-alsaaudio

Volume code: https://askubuntu.com/questions/689521/control-volume-using-python-script
'''

import logging
import alsaaudio
import numpy as np
import pyaudio
import threading
from copy import copy,deepcopy
from enum import Enum,StrEnum

logger = logging.getLogger(__name__)

class DeviceSelection(Enum):
    DEFAULT = 0
    PULSE = 1
    MANUAL = 2

class AudioProcessing():
    '''
    Process audio being played through sound card so we can do visualisations.

    Not all sound cards are equal. Some Pi bonnets do not present a record interface
    so you will then need to play with loopback. Given Pi uses Alsa with a Pulse Audio
    overlay, you will need pa-utils installed and use loopback e.g. something like this
    worked for the Adafruit speaker bonnet, although I couldn't control volume any more
    and moved to an external USB sound card as it just worked. YMMV. 

    sudo modprobe snd-aloop pcm_substreams=1
    SRC=$(pactl list sources short | head -1 | cut -f2)
    SINK=alsa_output.platform-snd_aloop.0.analog-stereo
    pactl load-module module-loopback source=$SRC sink=$SINK channels=2
    '''

    def __init__(self, 
                 device_selection:DeviceSelection=DeviceSelection.PULSE, 
                 frame_chunk_size:int=1024, 
                 device_index:int=0):

        self.p=pyaudio.PyAudio()
        logger.info("Available Audio Devices:")
        pulse_dev=None
        for i in range(self.p.get_device_count()):
            dev = self.p.get_device_info_by_index(i)
            name = dev['name']
            logger.info("Index: %-2d %-32s MaxI:%3d MaxOut:%3d Sample Rate:%6d", i, name, dev['maxInputChannels'], dev['maxOutputChannels'], dev['defaultSampleRate'])
            if name=="pulse":
                pulse_dev=dev

        match device_selection:
            case DeviceSelection.DEFAULT:
                self.record_dev = self.p.get_default_input_device_info()
                self.record_dev_name  = self.record_dev['name']
                self.record_dev_index = self.record_dev['index']
            case DeviceSelection.PULSE:
                self.record_dev_index = pulse_dev['index']
                self.record_dev = self.p.get_device_info_by_index(self.record_dev_index)
                self.record_dev_name = pulse_dev['name']
            case DeviceSelection.MANUAL: 
                self.record_dev_index = device_index
                self.record_dev = self.p.get_device_info_by_index(device_index)
                self.record_dev_name = self.record_dev['name']
        
        self.sample_rate  = int(self.record_dev['defaultSampleRate'])
        self.rec_channels = self.record_dev['maxInputChannels']
        self.frames_chunk_size = frame_chunk_size 

        logging.info("Using %s (index:%d)", self.record_dev_name, self.record_dev_index)
        logger.info("Sample Rate: %d", self.sample_rate)
        logger.info("Channels:    %d", self.rec_channels)
        logger.info("Chunk Size:  %d", self.frames_chunk_size)

        try:
            # ALSA naming nightmare. Try to pick sensible defaults...
            # Try PCM
            self.mixer = alsaaudio.Mixer('PCM')
            logger.info("Using PCM Mixer")
        except alsaaudio.ALSAAudioError as e:
            logger.info("PCM Unavailable. Trying Default Mixer")
            # Try "default" whatever it is
            self.mixer = alsaaudio.Mixer()
            logger.info("Using default mixer")

        self.stream:pyaudio.Stream = None
        # Callback updates this so need locking to protect it
        self._signal = np.zeros(4096)
        self.volume=2
        self.ch_l = None
        self.ch_r = None
        self.peak_l = 0
        self.peak_r = 0
        self.channel = alsaaudio.MIXER_CHANNEL_ALL
        self.set_volume(self.volume)
        logger.info("Volume set to %d", self.volume)
        self.audio_format   = pyaudio.paInt16 # pyaudio.paFloat32
        self.audio_bit_size = np.int16        # np.float32
        self._max_value     = 2**16           # Unless its a float??
        self._lock = threading.Lock()

    def signal(self) -> np.ndarray:
        s=None
        with self._lock:
            s=self._signal.copy()
            #s=deepcopy(self._signal) # .copy()
        return s

    def zero_signal(self):
        with self._lock:
            self._signal = np.zeros(4096)

    def log_volume(self, level:int, max_steps:int=60) -> int:
        """
        Map linear encoder position to logarithmic volume.
        Uses y = 100 * (x / max)^3 as an approximation for perceptual loudness.
        """
        x = level / max_steps           # Normalize to 0-1
        log_val = max_steps * (x ** 2)  # Cubic curve for logarithmic perception
        return int(log_val)       

    def vol_up(self, inc:int=2):
        with self._lock:
            self.set_volume(vol=self.volume+inc)
            v=self.volume
        return v

    def vol_down(self, inc:int=2):
        with self._lock:
            self.set_volume(vol=self.volume-inc)
            v=self.volume
        return v
    
    def set_volume(self, vol:int=-1, use_log:bool=False):
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

    def sound_data_avail_callback(self, in_data, frame_count, time_info, status):
        with self._lock:
            self._signal = np.frombuffer(in_data, dtype=self.audio_bit_size)
            self.ch_l    = self._signal[0::2]
            self.ch_r    = self._signal[1::2]
            self.peak_l  = np.abs(np.max(self.ch_l))/self._max_value*100.0
            self.peak_r  = np.abs(np.max(self.ch_r))/self._max_value*100.0        
        return (None, pyaudio.paContinue)

    def start(self):
        '''
        Start audio recording so we can get waveform etc

        When using some hardware there is no "record" interface, such as on
        the Adafruit speaker bonnet. Therefore you need to specify the device
        on the command line e.g. AUDIODEV=xx python ..
        '''
        self.stream=self.p.open(
                        format=self.audio_format,
                        channels=self.rec_channels,
                        rate=self.sample_rate,
                        input_device_index=self.record_dev_index,
                        input=True,
                        start=False, # Need to wait for dablin to catch up
                        frames_per_buffer=self.frames_chunk_size,
                        stream_callback = lambda in_data, frame_count, time_info, status:self.sound_data_avail_callback(in_data,frame_count,time_info,status)
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
        
        d = self.stream.read(self.frames_chunk_size, exception_on_overflow=False)
        with self._lock:
            self._signal = np.frombuffer(d,dtype=self.audio_bit_size)
        logging.debug("Latency %0.3fs Frames avail to read: %d", self.stream.get_input_latency(), self.stream.get_read_available())
        return True

    def get_peaks(self) -> tuple[float,float]:
        s=self.signal()
        self.ch_l=s[0::2]
        self.ch_r=s[1::2]
        self.peak_l = np.abs(np.max(self.ch_l))/self._max_value*100.0
        self.peak_r = np.abs(np.max(self.ch_r))/self._max_value*100.0        
        logger.debug("Peaks L:%0.3f R:%0.3f", peak_l, peak_r)
        return (peak_l, peak_r)

