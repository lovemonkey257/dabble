'''
Need: apt-get install python3-alsaaudio

Volume code: https://askubuntu.com/questions/689521/control-volume-using-python-script
'''

import logging
import alsaaudio
import pyaudio
import librosa
import numpy as np
import threading
from copy import copy,deepcopy
from enum import Enum,StrEnum
from scipy.signal import butter, filtfilt, lfilter

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

    Also pulseaudio (or other vitual cards) may present 32 in and out channels with 
    a sample rate (typically 44100 instead of 48000) which means pyaudio will detect
    the wrong number of in channels. Also PA is resampling which is not ideal but 
    sound on linux is a manifestation of magic so .... 

    I make some assumptions: 
    - If in channels is 0 or > 2 then assume virtual and one channel.
    - PA will resample correctly
    - Latency will be high so the FFT will not fully follow the sound

    Also remember this:
    - pyaudio will return variable buffer sizes as latency changes. This is running on a pi and
      using python so latency could be better.
    - If you try and process the full in channel you get 32 channels of "stuff" and your sound
      all interwoven and the FFT will show all sorts of artefacts. This took a long time to figure
      out as linux sound is magic (did I say that). Some is obvious but not all.

    '''

    def __init__(self, 
                 device_selection:DeviceSelection=DeviceSelection.PULSE, 
                 #device_selection:DeviceSelection=DeviceSelection.MANUAL, 
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
                if pulse_dev is None:
                    logger.fatal("Cannot find pulse")
                    raise Exception("Cannot find pulse audio")
                self.record_dev_index = pulse_dev['index']
                self.record_dev = self.p.get_device_info_by_index(self.record_dev_index)
                self.record_dev_name = pulse_dev['name']
            case DeviceSelection.MANUAL: 
                self.record_dev_index = device_index
                self.record_dev = self.p.get_device_info_by_index(device_index)
                self.record_dev_name = self.record_dev['name']

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

        self.frames_chunk_size = frame_chunk_size 

        self.sample_rate  = int(self.record_dev['defaultSampleRate'])
        self.rec_channels = self.record_dev['maxInputChannels']
        if self.rec_channels==0 or self.rec_channels>2:
            # Virtual device with 32 in/out? pulseaudio I'm looking at you
            # TODO: Do I need to identify actual sound card and input channels then 
            #       use that?
            logger.info("This is a virtual device. Limiting to 1 channel/mono but who knows")
            self.rec_channels=1

        logger.info("Using %s (index:%d)", self.record_dev_name, self.record_dev_index)
        logger.info("Sample Rate: %d", self.sample_rate)
        logger.info("Channels:    %d", self.rec_channels)
        logger.info("Chunk Size:  %d", self.frames_chunk_size)

        self.stream:pyaudio.Stream = None

        # Callback updates this so need locking to protect it
        self._signal = np.zeros(4096)
   
        # Store l/r peak values
        self.peak_l  = 0
        self.peak_r  = 0

        # Volume is the % value
        # We assume joined volume which is the natual way to change vol
        volcap = self.mixer.volumecap()
        logger.info("Volume caps: %s", ",".join(volcap))

        db_min,db_max = self.mixer.getrange(pcmtype=alsaaudio.PCM_PLAYBACK, units=alsaaudio.VOLUME_UNITS_DB)
        self.db_min = db_min
        self.db_max = db_min
        logger.info("Mixer DB min: %d, max: %d", self.db_min, self.db_max)

        self.min_volume = 10
        self.max_volume = 90
        self.set_volume()
        logger.info(f'Mixer Volume set to {self.volume()}%')

        self.audio_format   = pyaudio.paInt32
        self.audio_bit_size = np.int32
        self._max_value     = 2**16

        logger.info(f'Audio Format Size: {self.audio_format}')
        logger.info(f'Audio Bit Size:    {self.audio_bit_size}')

        # Lock to protect signal buffer updates
        self._lock = threading.Lock()

        # Create a mel filterbank (set when first used)
        self.mel_filterbank = None
        self._last_melbank_size = 0

        # Set Freq min/max. Max human hearing is around 20-20000
        # Music is a lot less. 30-15000 seems to work well
        # but can be tweaked
        self.mel_filter_fmin = 30
        self.mel_filter_fmax = 15000

    def update(self, prop, value):
        '''
        Thread safe way to update properties e.g. ao.update("mel_filter_fmin",60)
        '''
        with self._lock: 
            setattr(self, prop, value)
        return value

    def signal(self) -> np.ndarray:
        '''
        Return a copy of the current signal buffer to ensure
        thread safety
        '''
        s=None
        with self._lock:
            s=self._signal.copy()
        return s

    def zero_signal(self):
        '''
        Set the signal buffer to zero
        '''
        with self._lock:
            self._signal = np.zeros(4096)

    def magnitude_to_db(self,magnitude:int|float, reference:float=1.0) -> int:
        '''
        Given a magnitude return dB FS (as ref = 1) otherwise return db SPL
        Will return negative numbers
        '''
        return int(20 * log10(magnitude/reference))

    def vol_up(self, inc:int=2) -> int:
        with self._lock:
            v = min(self.volume() + inc, self.max_volume)
            self.set_volume(v)
        return v

    def vol_down(self, inc:int=2) -> int:
        with self._lock:
            v = max(self.volume() - inc, self.min_volume)
            self.set_volume(v)
        return v
   
    def volume(self, db:bool=False) -> int:
        '''
        Return current ALSA playback volume as a % or as DB (-ve)
        '''
        return self.mixer.getvolume(pcmtype=alsaaudio.PCM_PLAYBACK, units=alsaaudio.VOLUME_UNITS_DB)[0]/100 \
                if db \
                else \
                self.mixer.getvolume(pcmtype=alsaaudio.PCM_PLAYBACK, units=alsaaudio.VOLUME_UNITS_PERCENTAGE)[0]

    def set_volume(self, vol:int=20, units:int=alsaaudio.VOLUME_UNITS_PERCENTAGE) -> int:
        '''
        Set the ALSA volume for both stereo channels, using a percentage, or use
        alsaaudio.VOLUME_UNITS_DB to set as DB
        '''
        v=vol
        if units==alsaaudio.VOLUME_UNITS_PERCENTAGE:
            v=int(v)
            if v<self.min_volume:
                v=self.min_volume
            elif v>self.max_volume:
                v=self.max_volume
        elif units==alsaaudio.VOLUME_UNITS_DB:
            v=int(v*100)

        self.mixer.setvolume(v, 
                units=units,
                channel=alsaaudio.MIXER_CHANNEL_ALL)
        logger.debug(f'Setting volume to {v} {self.volume(db=True)}db')
        return v

    def sound_data_avail_callback(self, in_data, frame_count, time_info, status):
        with self._lock:
            # Calc number of frames, based on bit size
            # pyaudio does not guarantee buffer size and can vary based on latency
            n = frame_count * self.rec_channels
            max_count = len(in_data) // np.dtype(self.audio_bit_size).itemsize
            n = min(n, max_count)
            self._signal = np.frombuffer(in_data, dtype=self.audio_bit_size, count=n)
    
            if self.rec_channels==2:
                # Stereo
                self.peak_l  = int(np.abs(np.max(self._signal[0::2]))/self._max_value*100.0)
                self.peak_r  = int(np.abs(np.max(self._signal[1::2]))/self._max_value*100.0)
            else:
                # Mono
                self.peak_l  = int(np.abs(np.max(self._signal))/self._max_value*100.0)
                self.peak_r  = self.peak_l

            logger.debug("Req buffer len:%d in_data len: %d, frame count:%d n:%d", self.frames_chunk_size, len(in_data), frame_count, n)
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

    def fft(self, signal, 
            is_mono:bool=False, 
            low_pass_cutoff:float=0.0, 
            high_pass_cutoff:float=0.0, 
            mel_size:int=32,
            N:int=512):
        '''
        Calc FFT of signal using np.fft routines.
        Windowing (hanning) reduces spectral anomalies
        Use low_pass_cutoff to enhance lower frequencies
        mel_size is the number of "bars"/freqs you want to generate

        Note: The samples from the soundcard need to be correct. See comments at head of file
              re the sound card and issues with pulseaudio

        To test FFT use sox to play pure tones across a range of frequencies which should be
        shown as peak moving left to right. To play from 20Hz to 20KHz (the average human 
        hearing range is less than this). You can do this by putting the radio into airplay 
        mode and not stream anything and run:

        play -n synth 10 sine 20:20000

        If you see artefacts, particularly fixed (or barely moving) bars or repeated bars in the 
        higher frequencies, then check the in channels, sample rate of whatever card pyaudio is
        saying is the default. On my PI the default is pulseaudio.

        '''
        # Convert to mono, unless already mono i.e. 1 channel in
        mono_signal = signal if is_mono or self.rec_channels==1 else (signal[0::2] + signal[1::2] ) / 2

        # Use lowpass filter to enhance lower frequencies so viz has more energy
        if low_pass_cutoff>0.0 and high_pass_cutoff>0:
            nyq_freq = float(self.sample_rate)/2.0
            low_cutoff  = low_pass_cutoff/nyq_freq
            high_cutoff = high_pass_cutoff/nyq_freq
            b, a = butter(order, [low_cutoff, high_cutoff], btype='bandpass')
            mono_signal = filtfilt(b, a, mono_signal)

        # Size/len of mono signal
        mono_signal_size = len(mono_signal)

        # Window to reduce spectral oddities
        mono_signal = mono_signal * np.hanning(mono_signal_size)

        # Calc FFT
        # TODO: Consider FFT from librosa? Need performance details
        fft = np.abs(np.fft.rfft(mono_signal))

        # Create mel filterbank. Update if FFT size changes
        fft_size = len(fft)*2-1
        if fft_size!=self._last_melbank_size:
            self.mel_filterbank = librosa.filters.mel(
                    fmin=self.mel_filter_fmin, 
                    fmax=self.mel_filter_fmax,
                    sr=self.sample_rate,
                    n_fft=fft_size,
                    n_mels=mel_size)
        self._last_melbank_size = fft_size

        # Get magnitudes for the freqs from the mel filterbank
        # Square the FFT to convert amplitude to power/energy
        # which has physical meaning.
        mel_mags = self.mel_filterbank @ (fft ** 2)

        return (fft, mel_mags)
