import logging
import time
import re
import subprocess
import threading
from queue import Queue,Empty
from io import StringIO
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

        # self.play_cmdline=Template('/usr/bin/dablin -D eti-cmdline -d eti-cmdline-rtlsdr -c $channel -s $sid -I')
        self.play_cmdline=Template('/usr/local/bin/dablin -D eti-cmdline -d eti-cmdline-rtlsdr -c $channel -s $sid -I')
        self.scan_cmdline=Template('/usr/local/bin/eti-cmdline-rtlsdr -J -x -C $block -D $scantime')

    def signal_handler(self, sig, frame):
        print('You pressed Ctrl+C!')
        self.stop()
        time.sleep(1)
        sys.exit(0)

    def _read_stream(self, stream, queue:Queue):
        for line in iter(stream.readline, b''):
            queue.put(line.decode().replace("\n",""))
        stream.close()

    def play(self,name):
        self.playing = name
        (self.channel,self.sid,self.ensemble) = self.radio_stations.tuning_details(name)
        self.dablin_proc=subprocess.Popen(
            shlex.split(
                self.play_cmdline.substitute({
                    "channel":self.channel,
                    "sid": self.sid
                })
            ),
            stderr=subprocess.PIPE
        )
        self.dablin_stderr_lookups = {
            "dab_type":  re.compile(f"FICDecoder: SId {self.sid}: audio service \(SubChId \d+, (?P<v>.*), primary\)", re.IGNORECASE),
            "prog_type": re.compile(f"^FICDecoder: SId {self.sid}: programme type \(static\): '(?P<v>.*)'", re.IGNORECASE),
            "pad_label": re.compile(f"^PADChangeDynamicLabel SId {self.sid} Label:'(?P<v>.+)'", re.IGNORECASE),
            "media_fmt": re.compile(f"^EnsemblePlayer: format: (?P<v>.*)", re.IGNORECASE)
        }
        self.dablin_stderr_q = Queue()
        self._t=threading.Thread(target=self._read_stream, args=(self.dablin_proc.stderr, self.dablin_stderr_q))
        self._t.daemon = True
        self._t.start()

    def stop(self):
        self.currently_playing = None
        if self.dablin_proc is not None:
            self.dablin_proc.terminate()
        time.sleep(1)

    def _get_line_from_q(self):
            s=""
            for c in self.dablin_stderr_q.get_nowait():
                s+=c
                if c=="\n":
                    break
            return s
    
    def parse_dablin_output(self):
        '''
        FICDecoder: SId 0xC4CD: audio service (SubChId 17, DAB+, primary)
        FICDecoder: SId 0xC4CD: programme type (static): 'Rock Music'
        FICDecoder: SId 0xC4CD, SCIdS  0: MSC service component (SubChId 17)
        FICDecoder: SId 0xC4CD: programme service label 'Radio X' ('Radio X')
        PADChangeDynamicLabel SId 0xC4CD Label:'Radio X - Get Into the Music'
        PADChangeDynamicLabel SId 0xC4CD Label:'On Air Now on Radio X: Dan Gasser'        
        '''
        try:
            l=self._get_line_from_q()
            for lu in self.dablin_stderr_lookups:
                r=self.dablin_stderr_lookups[lu].search(l)
                if r:
                    return { lu : r.groupdict()['v'] }
        except Empty:
            pass
        return None

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
