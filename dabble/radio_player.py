import logging
import time
import subprocess
import shlex
import json
import signal
import sys
from string import Template
from pathlib import Path

from . import radio_stations

class RadioPlayer():
    def __init__(self, radio_stations:radio_stations.RadioStations=None):
        self.dablin_proc = None
        self.playing = "Not Playing Yet"
        self.ensemble=""
        self.channel=""
        self.sid=""
        self.radio_stations = radio_stations
        self.multiplexes = list()
        # signal.signal(signal.SIGINT, self.signal_handler)

        self.play_cmdline=Template('/usr/bin/dablin -D eti-cmdline -d eti-cmdline-rtlsdr -c $channel -s $sid -I')
        self.scan_cmdline=Template('/usr/local/bin/eti-cmdline-rtlsdr -J -x -C $block -D $scantime')

    def signal_handler(self, sig, frame):
        print('You pressed Ctrl+C!')
        self.stop()
        time.sleep(1)
        sys.exit(0)

    def play(self,name):
        self.playing = name
        (self.channel,self.sid,self.ensemble) = self.radio_stations.tuning_details(name)
        self.dablin_proc=subprocess.Popen(
            shlex.split(
                self.play_cmdline.substitute({
                    "channel":self.channel,
                    "sid": self.sid
                })
            )
        )

    def stop(self):
        self.currently_playing = None
        if self.dablin_proc is not None:
            self.dablin_proc.terminate()
        time.sleep(1)

    def load_multiplexes(self):
        if Path("multiplex.json").exists():
            # load from radiodns...?
            a=1
            
        elif Path("default-multiplexes.json"):
            with open("default-multiplexes.json") as m:
                s_json = json.load(m)
                self.multiplexes = s_json["uk"]
        print(self.multiplexes)

    def scan(self, ui_msg_callback=None):

        if ui_msg_callback is not None:
            ui_msg_callback("Starting Scan")

        # Cant scan while RTL is in use
        self.stop()

        stations=dict()

        # Get multiplex blocks
        self.load_multiplexes()
        for block in sorted(self.multiplexes):
            print("Scanning", block)
            if ui_msg_callback is not None:
                ui_msg_callback(f'Scanning {block}')

            self.dablin_proc=subprocess.run(shlex.split(
                self.scan_cmdline.substitute({
                    "block":block,
                    "scantime": 8
                }))
            )
            
            ensemble_file = Path(f'ensemble-ch-{block}.json')
            if ensemble_file.exists():
                with open(ensemble_file, 'r') as jfile:
                    data = json.load(jfile)
                    ui_msg_callback("Done", f"{data['ensemble']} {len(data['stations'])} stations")
                    for s,sid in data['stations'].items():
                        if s not in stations:
                            stations[s]={ 'sid':sid, 'ensemble':data['ensemble'], 'channel':data['channel'] }
                        else:
                            stations[s + " " + data['ensemble'] ]={ 'sid':sid, 'ensemble':data['ensemble'], 'channel':data['channel'] }                  
            else:
                ui_msg_callback(f'No stations')    

            time.sleep(1)

        if ui_msg_callback is not None:
            ui_msg_callback(f'Storing Data')

        '''
        ensembles=Path(".")
        for ensemble_json_file in list(ensembles.glob('ensemble-ch-*.json')):
            with open(ensemble_json_file, 'r') as jfile:
                data = json.load(jfile)
                for s,sid in data['stations'].items():
                    if s not in stations:
                        stations[s]={ 'sid':sid, 'ensemble':data['ensemble'], 'channel':data['channel'] }
                    else:
                        stations[s + " " + data['ensemble'] ]={ 'sid':sid, 'ensemble':data['ensemble'], 'channel':data['channel'] }
        '''

        with open("station-list.json","w") as s:
            json.dump(stations,s)

        self.radio_stations.load_stations()

        if ui_msg_callback is not None:
            ui_msg_callback(f'Found {self.radio_stations.total_stations} stations')

       
    


"""
#! /bin/bash
# https://www.radiodns.uk/multiplexes.json
#
#

curl https://www.radiodns.uk/multiplexes.json > multiplexes.json
if [ -s multiplexes.json ]; then
	echo "Getting DAB block info from www.radiodns.uk..."
	blocks=$(jq -r ".[].block" multiplexes.json | sort -r | uniq)
else
	echo "Using default block settings. May be incomplete"
	blocks=$(jq -r ".uk[]" default-multiplexes.json | sort -r | uniq)
fi
for block in $blocks
do
    echo "--------------------------------"
    echo "Scanning $block"
    echo "--------------------------------"
    eti-cmdline-rtlsdr -J -x -C $block -D 10
done
echo "Compiling station list..."
python stations.py
echo "Station list in station-list.json"
num_stations=$(jq "keys[]" station-list.json | wc -l)
echo "Found $num_stations"
echo "Have fun"

"""