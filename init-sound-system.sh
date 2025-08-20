#! /bin/bash
#
#
sudo modprobe snd-aloop pcm_substreams=1
SRC=alsa_output.platform-soc_107c000000_sound.stereo-fallback.monitor
SINK=alsa_output.platform-snd_aloop.0.analog-stereo
pactl load-module module-loopback source=$SRC sink=$SINK

