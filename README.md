# Dabble Radio

![alt text](docs/radio-interface-animation.gif)

A DAB radio project based on a PI, RTLDSR, a small LCD and some LED encoders. The core software is based on the good work of dablin and eti-stuff and it is very much a work in progress.

This project is targetted to be run on a Raspberry Pi running Raspberry Lite OS (this could change). Assumptions reqarding packages etc rely on this. While the hardware could be run on another system using I2C and I2S I've not tested this.  

## Features
- DAB and DAB+ reception
- Station name scroll
- Ensemble displayed and DAB type
- Stream via Apple Airplay. Displays Album, Track and Artist
- Graphic equaliser works in both Radio and Airplay modes
- Right encoder changes Volume (using log scale) 
- Left encoder changes the station
- Station scanning works, although need to decide how to handle default list of channels to scan
- Also captures audio format and genre but not currently displayed
- Can be themed but functionality not exposed yet
- Power button to power radio off
  
## Current status and missing features
- It works!!
- Some interface issues when selecting stations
- FFT works, but frequency selection needs some work 
- No way to select country/default ensembles to scan
- Themes are implemented but no way to select/update them
- Need to run automatically at boot
- Support for Google Cast audio streaming looks like it may not be possible as this relies
  on proprietary protocols and private crypto. Maybe use: https://github.com/rgerganov/shanocast

# Running
See instructions below on getting it built.

- cd into your dev dir
- `./run-mqtt.sh`
- `uv run radio.py`

The system will restart in whatever mode you left it in, but by default it will start
in Radio mode.

While in Radio mode if you airplay stream to this device it will automatically switch-over 
and play whatever you stream. If you stop streaming, for example no music is selected, then 
the device will automatically switch back to Radio.

However, if you manually switch to Airplay mode the device will stay in that mode until you manually
switch back to Radio mode.

## Display
The top line displays the mode, either Radio or Airplay.

The middle contains four features:
- Station Name alternating with the latest PAD message
- Visualiser in the background
- Volume bar below the visualiser

The bottom line is the ensemble and DAB type (standard DAB or DAB+)

While streaming the display adapts as follows:
- Mode switches to Airplay
- Station Name/PAD are replaced with Track and Artist
- Ensemble and DAB type are replaced by Album Name

Volume changes on your source device, say you phone, will be reflected by the radio player.

## Left Encoder
By default will select a station. Currently once a station is selected it will be used if left
for 4 seconds. This feels more intuitive than then having to press the button to select.

Press the button to bring up the menu which allows you to change a number of dispay settings
such as Equaliser type, Station on/off, Levels on/off.

## Right Encoder
By default will change the volume. This is based on a log scale which feels better than
linear.

Press the button to bring up the menu to allowing you to change the mode or initiate a scan. 

## Menus in detail
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
- If nothing selected revert to play screen after five seconds

### Right Encoder
Default - Station select. No button needed to select. Leave on a station for 3 seconds and
          it will be selected automatically
On click:
- Menu options displayed:
    - Radio Mode
    - Airplay Mode
    - Scan
    - Standby Mode
- If nothing selected for more than 5 secs revert to play screen

# Build

## Components
- Raspberry Pi 5. I tried the Pi Zero 2 but it doesn't have enough processing power if visualisations are used.
- [Pimoroni 0.96" LCD](https://shop.pimoroni.com/products/0-96-spi-colour-lcd-160x80-breakout). I got mine from PiHut.
- 2 x [Fermion EC11 encoders](https://thepihut.com/products/fermion-ec11-rotary-encoder-module-breakout). These work well and I'm using these instead of the pretty one.
- NESDR Nano 2+ (but any RTLSDR should do)
- Tecknet USB sound card. Cheap, functional and sounds "good enough". This isn't a audiophile project.
- Gave up on the Adafruit Speaker Bonnet and now using a USB sound card which is much more reliable. The drivers etc have been updated so may go back to this.
- Aerial, 1m, 7 section with BNC connector
- BNC Female to MCX Male Lowloss Pigtail, 24cm
- No idea about an enclosure yet. I'm rubbish at this....

## Hardware Build
TBD

### Wiring for each device
See [GPIO PIN layout](docs/pin_usage.md)

## Base OS
Install Raspberry Pi Lite, no GUI needed, minimal install.

## Software
- UI and controller written in python
- Modified version of of eti-cmdline from JvanKatwijk to enable scans. Forked here https://github.com/lovemonkey257/eti-stuff. Now accepted upstream so you can use eti-cmdline directly
- Modified version of dablin from Opendigialradio so I can get PAD messages in cli version, https://github.com/lovemonkey257/dablin. PR accepted but not yet merged.
- Shairplay-sync, built from souce. Will try to move back to podman
- Have to use pulse so audiocard can be shared

## Software Builds
Building custom `dablin` needs thought as the build dependencies
add unnecessary bloat. 

### Base config
Ensure Raspberry Pi has SPI and I2C enabled in config. i2s-mmap makes sound
more efficient. Also turn off internal Audio (snd_bcm2935) so bonnet, if being
used, is primary output. USB works by default.

`/boot/firmware/config.txt` 

```
dtparam=i2c_arm=on
dtparam=i2s=on
dtparam=spi=on
dtparam=audio=off

dtoverlay=vc4-kms-v3d,noaudio
dtoverlay=max98357a
dtoverlay=i2s-mmap

# Power button
dtoverlay=gpio-shutdown,debounce=500   
dtoverlay=gpio-led,gpio=3,label=pwrled,trigger=default-on,active_low=0 
```

```
sudo raspi-config nonint do_spi 1
sudo raspi-config nonint do_i2c 1
```

* If using lite no GUI is installed so ensure pipewire-pulse installed:*
```
sudo apt install -y pipewire-pulse pulseaudio-utils
sudo reboot
```

### Build Essentials
`sudo apt install build-essential cmake`

### `dablin`
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

### `eti-cmdline`
This can be installed from Jvan's repo directly. The build is the same.

Dependencies:
- `sudo apt install libfftw3-dev libsndfile1-dev libsamplerate0-dev librtlsdr-dev libboost-dev jq`

Code. Most changes have been accepted upstream (thanks Jvan) so this is probably redundent:
- `git clone https://github.com/lovemonkey257/eti-stuff.git` or `git clone https://github.com/JvanKatwijk/eti-stuff.git`
- `cd eti-stuff\eti-cmdline`
- `mkdir build && cd build`
- `cmake .. -DRTLSDR=ON`
- `make && sudo make install`

This should put `eti-cmdline-rtlsdr` into `/usr/local/bin`

### Test Radio by Scanning

- Ensure RTL device and audio are set up.
- Test `eti-cmdline` can see USB RTL and dump some station params: `eti-cmdline-rtlsdr -J -x`
- Acid test, station selection and audio: `dablin -D eti-cmdline -d eti-cmdline-rtlsdr -c 11D -s 0xc0c6 -I`

Note the channel (11D) and station (0xc0c6) are the params for Magic Radio in the UK. Depending
on your location you will need to tweak these. I'm trying to find sources based on country but
that is for later on, sorry.

### Shairplay-sync
These instructions are based on those detailed in https://github.com/mikebrady/shairport-sync/issues/1970
(thanks to those who figured it out).

- Build dependencies

```
sudo apt install -y --no-install-recommends build-essential git autoconf automake libtool 
sudo apt install -y --no-install-recommends build-essential git autoconf automake libtool libpopt-dev libconfig-dev libasound2-dev avahi-daemon libavahi-client-dev libssl-dev  libsoxr-dev libplist-dev libsodium-dev libavutil-dev libavcodec-dev libavformat-dev uuid-dev libgcrypt-dev xxd jq libpipewire-0.3-dev libspa-0.2-bluetooth python3-dbus libdaemon-dev libmosquitto-dev
```

- Install NQPTP
```
git clone https://github.com/mikebrady/nqptp.git
cd nqptp
autoreconf -fi
./configure --with-systemd-startup
make
sudo make install
sudo systemctl enable nqptp
sudo systemctl start nqptp
```
- Install Shairport-sync
```
git clone https://github.com/mikebrady/shairport-sync.git
cd shairport-sync
autoreconf -fi
./configure --sysconfdir=/etc --with-pw --with-mqtt-client --with-soxr --with-avahi \
            --with-ssl=openssl --with-systemd --with-airplay-2 --with-metadata \
            --with-dbus-interface --with-dbus-test-client --with-alsa --with-pw --with-pa`
make
sudo make install
sudo systemctl disable shairport-sync #disable the system level instance.

```
- Set up user shairport-sync
- Create `~/.config/systemd/user/shairport-sync.service`. You may need to create directories
```
[Unit]
Description=Shairport Sync - AirPlay Audio Receiver
After=sound.target
Wants=network-online.target
After=network.target network-online.target

[Service]
ExecStart=/usr/local/bin/shairport-sync --log-to-syslog

[Install]
WantedBy=default.target
```
Note that the github issue adds in a dependency on avahi-daemon (using requires/After), BUT, user
units cannot rely on system units, there are separate. Go figure but that's how it works at the moment.

- Add config for shairport-sync at `/etc/shairport-sync.conf` e.g.

```
general = {
  name = "Dabble-Radio";
  output_backend="pw";
};
alsa = {
  mixer_control_name = "PCM";
};
metadata = {
        enabled = "yes"; 
        include_cover_art = "no"; 
        cover_art_cache_directory = "/tmp/shairport-sync/.cache/coverart"; 
        pipe_name = "/tmp/shairport-sync-metadata";
        pipe_timeout = 5000; 
};
mqtt = {
        enabled = "yes"; 
        //hostname = "host.containers.internal"; // Hostname of the MQTT Broker if using podman
        hostname = "localhost";
        port = 1883;
        topic = "dabble-radio"; 
        publish_parsed = "yes"; // Whether to publish a small (but useful) subset of metadata under human-understandable topics.
        publish_cover = "no";   // Whether to publish the cover over MQTT in binary form. This may lead to a bit of load on the broker.
        enable_remote = "yes";  // Whether to remote control via MQTT. RC is available under `topic`/remote.
};
```
 
- Enable avahi-daemon `sudo systemctl enable avahi-daemon && sudo systemctl start avahi-daemon` 
- Enable shairport-sync `systemctl --user enable shairport-sync.service && systemctl --user start shairport-sync.service`

### MQTT
Need to run `run-mqtt.sh`

```
#! /bin/bash
echo "Creating storage folders"
mkdir -p $HOME/mqtt/data
mkdir -p $HOME/mqtt/log
mkdir -p $HOME/mqtt/config
mkdir -p $HOME/mqtt/config/conf.d

podman stop mqtt 
podman rm mqtt
podman pull docker.io/eclipse-mosquitto:latest

CONFIG=$HOME/mqtt/config/mosquitto.conf
if [ ! -r $CONFIG ]; then
        echo "Creating MQTT config: $CONFIG"
        cat <<- 'EOF' > $CONFIG
                allow_anonymous true
                listener 1883 0.0.0.0
                persistence true
                persistence_location /mosquitto/data/
                log_dest file /mosquitto/log/mosquitto.log
                log_dest stdout
                include_dir /mosquitto/config/conf.d
EOF
else
        echo "Config found"
fi

podman run -d --name mqtt \
        --label "io.containers.autoupdate=image" \
        --restart=always \
        -p 1883:1883 -p 9001:9001 \
        -v $HOME/mqtt/config:/mosquitto/config:ro \
        -v $HOME/mqtt/data:/mosquitto/data \
        -v $HOME/mqtt/log:/mosquitto/log \
        docker.io/eclipse-mosquitto:latest
```

### Dabble
To install:
- `sudo apt install python3-dev python3-alsaaudio python3-pyaudio`
- `git clone https://github.com/lovemonkey257/dabble.git`
- `cd dabble`
- `uv init`
- `uv sync`

### Config
This is created with a default settings on first run.

Saved state is saved into `dabble_radio.json" e.g.

```  
{
    "station_name": "Heart Dance",
    "ensemble": "D1 National",
    "volume": 34,
    "pulse_left_led_encoder": false,
    "pulse_right_led_encoder": false,
    "enable_visualiser": true,
    "visualiser": "graphic_equaliser",
    "enable_levels": false,
    "theme_name": "default"
}
```
TODO: What else might need external configuration? Other config settings that should
be exposed?

## Font
Install font from https://fonts.google.com/share?selection.family=Noto+Sans:ital,wght@0,100..900;1,100..900 into /usr/share/fonts/truetype/

The zip installs under a dir called `static` which you should rename to `noto`.


## Deprecated - Capture Audio from Adafruit Speaker Bonnet
The driver for the speaker bonnet does not present a recording interface - its playback only so no
way to sample the audio for the visualiser.

Using ALSA and the advice on capturing sound didn't work for me. Even AI gave up so I did it the
old fashioned way and figured-it-out-myself. It took a while...

I've created a script `init-sound-system.sh` to do this but it uses ALSA loopback and some 
pulseaudio magic, which apparantly powers the Linux Sound sub-systems.

The magic incantation is as follows:

- Load the ALSA loop back driver `sudo modprobe snd-aloop pcm_substreams=1`
- Define the source (from `pactl list sources short`) `SRC=alsa_output.platform-soc_107c000000_sound.stereo-fallback.monitor`
- Define the sink i.e. loopback `SINK=alsa_output.platform-snd_aloop.0.analog-stereo`
- Link them together `pactl load-module module-loopback source=$SRC sink=$SINK`

Anything played through the Bonnet is now fed back into the loopback sink which you can then capture
sound from. I found that the SDL sub-system picked this up automatically and I didn't need to set
`AUDIODEV`.

Eventually I gave up on the Bonnet and switched to a USB sound card as I could not control the volume.

