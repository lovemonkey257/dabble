#! /bin/bash
#
#
echo "Only run if no record interface on sound card. Will use first sound card so"
echo "you may need to tweak this or disable unneeded soundcards e.g. HDMI on Pi"
echo "Ctrl+C if you dont want to continue, otherwise press return"
read x
sudo modprobe snd-aloop pcm_substreams=1
SRC=$(pactl list sources short | head -1 | cut -f2)
SINK=alsa_output.platform-snd_aloop.0.analog-stereo
echo pactl load-module module-loopback source=$SRC sink=$SINK
pactl load-module module-loopback source=$SRC sink=$SINK channels=2

