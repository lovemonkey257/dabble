# dabble
A DAB radio project based on a PI, a small LCD and some LED encoders. The core software is based on the good work of dablin and eti-stuff. It is very much a work in progress.

This project is targetted to be run on a Raspberry Pi running Raspberry OS (this could change). Assumptions reqarding packages etc rely on this. While the hardware could be run on another system using I2C and I2S I've not tested this. 

## Current progress and Features
- Forked and fixed dablin cli to output PAD announcements e.g. now playing
- UI seems stable
- The Adafruit speakerbonnet/amp works fine now and can capture audio
- Two encoders work

## Components
- Raspberry Pi 5. I tried the Pi Zero 2 but the speaker bonnet and ALSA/Pulseaudio did not play nicely. I'll come back to this.
- [Pimoroni 0.96" LCD](https://shop.pimoroni.com/products/0-96-spi-colour-lcd-160x80-breakout). I got mine from PiHut.
- 2 x [Fermion EC11 encoders](https://thepihut.com/products/fermion-ec11-rotary-encoder-module-breakout). These work well and I'm using these instead of the pretty one.
- 1 x [Adafruit Speaker Bonnet](https://www.adafruit.com/product/3346). Can use 3W 8Ohm speakers which should be powerful enough
- NESDR Nano 2+ (but any RTLSDR should do)
- No idea about an enclosure yet. Will prototype it in thin MDF

## Software
- UI and controller written in python
- Modified version of of eti-cmdline from JvanKatwijk to enable scans. Forked here https://github.com/lovemonkey257/eti-stuff
- Modified version of dablin from Opendigialradio so I can get PAD messages in cli version, https://github.com/lovemonkey257/dablin

## Capture Audio from Adafruit Speaker Bonnet
The driver for the speaker bonnet does not present a recording interface - its playback only. This
is a problem for me as I sample the sound to display the visualiser.

Using ALSA and any advice on capturing sound didn't work for me. Even AI gave up so I did it the
old fashioned way and figured-it-out-myself. It took a while...

I've created a script `init-sound-system.sh` to do this but it uses ALSA loopback and some 
pulseaudio magic (which apparantly is how the Linux Sound sub-systems work).

This is what I had to do and it works:

- Load the ALSA loop back driver `sudo modprobe snd-aloop pcm_substreams=1`
- Define the source (from `pactl list sources short`) `SRC=alsa_output.platform-soc_107c000000_sound.stereo-fallback.monitor`
- Define the sink i.e. loopback `SINK=alsa_output.platform-snd_aloop.0.analog-stereo`
- Link them together `pactl load-module module-loopback source=$SRC sink=$SINK`

Anything played through the Bonnet is now fed back into the loopback sink which you can then capture
sound from. I found that the SDL sub-system picked this up automatically and I didn't need to set
`AUDIODEV`.

### Features
- DAB and DAB+ reception
- Station name scroll
- Ensemble displayed and DAB type
- Waveform visualiser works
- Graphic equaliser works
- Bar Graphic equaliser works

![alt text](docs/playing.png)
![alt text](docs/waveform.png)

- PAD messages updated

![alt text](docs/pad-msg.png)

- Menus work
- Volume works using log scale (seems more natural)
- Station selection works
- Station scanning works, although need to decide how to handle default list of channels to scan
- Also captures audio format and genre but not currently displayed

## Current problems:
- Proper build perhaps into containers
- Enclosure

## Possibly menu system
Two encoders (left, right) both with built in buttons. We have four entry techniques: twist to search, button to select.

### Left Encoder
Default - Volume
On click:
- List of Visualisations:
    - Graphic Equaliser
    - Waveform
    - Bar Graphic Equaliser
    - Levels On/Off
    - Visualiser On/Off
    - Station name On/Off

- Select and click (if off will enable it)
- If nothing selected revert to play screen after a few seconds

### Right Encoder
Default - Station select. No button needed to select?
On click:
- Menu options displayed:
    - Scan
    - Themes? 
    - Country/Language?? Selects ensemble channels
    - Possibly more
- If nothing selected for more than 5 secs revert to play screen

## Ideas
- Turn this into a mini streamer e.g. run shareport-sync et al?

# Build
Install Raspberry Pi Lite, no GUI needed, minimal install.

Building custom `dablin` and `eti-cmdline` needs thought as the build dependencies
add unnecessary bloat. 

## Base config
Ensure Raspberry Pi has SPI and I2C enabled in config. i2s-mmap makes sound
more efficient. Also turn off internal Audio (snd_bcm2935) so bonnet is primary 
output.

`/boot/firmware/config.txt` 

```
dtparam=i2c_arm=on
dtparam=i2s=on
dtparam=spi=on
dtparam=audio=off

dtoverlay=vc4-kms-v3d,noaudio
dtoverlay=max98357a
dtoverlay=i2s-mmap
```

```
sudo raspi-config nonint do_spi 1
sudo raspi-config nonint do_i2c 1
```

* If using lite so no GUI etc ensure pipewire-pulse installed:*
```
sudo apt install -y pipewire-pulse
sudo reboot
```

## Build Essentials
`sudo apt install build-essential cmake`

## `dablin`
Dependencies first.
- `sudo apt-get install libmpg123-dev libfaad-dev libsdl2-dev libfdk-aac-dev`

Now the code (assumes using my fork. Hopefully they may merge in my PR):
- `sudo apt remove dablin`
- `git clone https://github.com/lovemonkey257/dablin.git`
- `cd dablin`
- `mkdir build && cd build && cmake ..`
- `make dablin && sudo cp src/dablin /usr/local/bin/`

Note that dablin will be installed in /usr/local/bin/. System installed
version is in /usr/bin. Check you've removed system version if you have
problems with PAD.

Also avoid `make install` as that will try to build GTK version. We only want the cli version
so we mv it manually.

## `eti-cmdline`
Dependencies:
- `sudo apt install libfftw3-dev libsndfile1-dev libsamplerate0-dev librtlsdr-dev libboost-dev jq`

Code. Most changes have been accepted upstream (thanks Jvan) so this is probably redundent:
- `git clone https://github.com/lovemonkey257/eti-stuff.git`
- `cd eti-stuff\eti-cmdline`
- `mkdir build && cd build`
- `cmake .. -DRTLSDR=ON`
- `make && sudo make install`

This should put `eti-cmdline-rtlsdr` into `/usr/local/bin`

## Test Radio by Scanning

- Ensure RTL device and audio are set up.
- Test eti-cmdline can see USB RTL and dump some station params: `eti-cmdline-rtlsdr -J -x`
- Acid test. Play a station `dablin -D eti-cmdline -d eti-cmdline-rtlsdr -c 11D -s 0xc0c6 -I`

Note the channel (11D) and station (0xc0c6) are the params for Magic Radio in the UK. Depending
on your location you will need to tweak these. I'm trying to find sources based on country but
that is for later on, sorry.

## Dabble
As this needs system installed packages create requirements as follows:

`pip list --not-required --format=freeze -l > requirements.txt`

To install:
- `sudo apt install python3-dev python3-alsaaudio python3-pyaudio`
- `git clone https://github.com/lovemonkey257/dabble.git`
- `cd dabble`
- Create venv `pip -mvenv venv`
- Edit `./venv/pyvenv.cfg` and ensure `include-system-site-package` is `true`
- `pip install -r requirements.txt`

## Config
Saved state is saved into `dabble_radio.json" e.g.

```  
{
    "station_name": "Heart Dance",
    "ensemble": "D1 National",
    "volume": 34,
    "pulse_left_led_encoder": false,
    "pulse_right_led_encoder": false,
    "enable_visualiser": true,
    "visualiser": "waveform",
    "enable_levels": false
}
```
TODO: What else might need external configuration? Other config settings that should
be exposed?

## Font
Install font from https://fonts.google.com/share?selection.family=Noto+Sans:ital,wght@0,100..900;1,100..900 into /usr/share/fonts/truetype/

The zip installs under a dir called `static` which you should rename to `noto`.

## Running
- cd into your dev dir
- `source ./venv/bin/activate`
- `./init-sound-system.sh`
- `python radio.py`

### Left Encoder
By default will select a station. Currently once a station is selected it will be used if left
for 4 seconds. This feels more intuitive than then having to press the button to select.

Press the button to bring up the menu which allows you to change a number of display settings
such as Equaliser type, Station on/off, Levels on/off.

### Right Encoder
By default will change the volume. This is based on a log scale which feels better than
linear.

Press the button to bring up the menu to allow you to initiate a scan. It doesn't do much
else at the moment.



