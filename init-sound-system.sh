#! /bin/bash
#
#
sudo modprobe snd-aloop pcm_substreams=1
SRC=$(pactl list sources short | head -1 | cut -f2)
SINK=alsa_output.platform-snd_aloop.0.analog-stereo
pactl load-module module-loopback source=$SRC sink=$SINK

