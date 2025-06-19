import json
import logging
import re
import shlex
import signal
import subprocess
import sys
import time
from copy import copy
from dataclasses import dataclass, field
from io import StringIO
from pathlib import Path
from queue import Empty, Queue
from string import Template
from threading import Event, Lock, Thread

from . import radio_stations

logger = logging.getLogger(__name__)

@dataclass
class UpdateState():
    name:str = ""
    value:str = ""
    updated:bool = False
    empty:bool = True

class MsgUpdates():
    def __init__(self, lookups):
        self._keys = lookups.keys()
        self._values = dict()
        for k in self._keys:
            self._values[k]=UpdateState()

    def __contains__(self, k):
        return k in self._values

    def get(self,k):
        if k in self._values:
            self._values[k].updated = False
            return self._values[k]
        return None

    def update(self,k,v):
        if k in self._values:
            existing_v = self._values[k].value
            if existing_v != v:
                self._values[k].value=v
                self._values[k].updated=True
                return True
            else:
                self._values[k].updated=False
        return False
    
    def is_updated(self,k):
        if k in self._values:
            return self._values[k].updated
              
class DablinLogParser():
    def __init__(self, q:Queue, e:Event):
        self._q = q
        self._end_task = e
        self._lookups = dict()
        self._updates_lock = Lock()
        self._recv_errors = 0

    def _get_line_from_q(self, recd_threshold:int=200):
            s=""
            recd=0
            # Q returns characters not lines!!
            for c in self._q.get_nowait():
                s+=c
                recd+=1
                if c=="\n" or recd>recd_threshold:
                    break
            if recd>recd_threshold:
                self._recv_errors+=1
                logger.error("Buffer overflowed. Possible reception errors")
                logger.error("%s",s)
            logger.debug("Line read from q: %s", s)
            return s
    
    def _parse_dablin_output(self):
        '''
        Parse the dablin log and run regexs to extract info such as
        PAD announcements, DAB type etc. See play method for more
        details.
        '''
        try:
            l=self._get_line_from_q()
            for lu in self._lookups:
                r=self._lookups[lu].search(l)
                if r:
                    return ( lu, r.groupdict()['v'] )
        except Empty:
            pass
        return (None, None)

    def stop(self):
        self._end_task.set()

    def run(self, lookups:dict):
        logger.info(f'Log reader starts')
        self._lookups = lookups
        self._updates = MsgUpdates(self._lookups)
        try:
            while True:
                if self._end_task.is_set():
                    break
                with self._updates_lock:
                    #self._updates = self._parse_dablin_output()
                    k,v = self._parse_dablin_output()
                    if k is not None:
                        self._updates.update(k,v)
                time.sleep(0.1)
        except KeyboardInterrupt as e:
            pass
        return

    def updates(self):
        with self._updates_lock:
            return copy(self._updates)

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
        logger.info("Player starting")

        self.dablin_stderr_q = Queue()
        self._stop_log_parser_event = Event()
        self.dablin_log_parser = DablinLogParser(self.dablin_stderr_q,  self._stop_log_parser_event)

        self._recv_errors=0
        self.playing = name

        (self.channel,self.sid,self.ensemble) = self.radio_stations.tuning_details(name)
        # This is run in parallel so will not block
        # Sound sent straight to sound card
        self.dablin_proc=subprocess.Popen(
            shlex.split(
                self.play_cmdline.substitute({
                    "channel":self.channel,
                    "sid": self.sid
                })
            ),
            stderr=subprocess.PIPE
        )
        '''
        FICDecoder: SId 0xCFE8: audio service (SubChId  4, DAB+, primary)
        FICDecoder: SId 0xC4CD: audio service (SubChId 17, DAB+, primary)
        EnsemblePlayer: playing sub-channel 4 (DAB+)
        FICDecoder: SId 0xC4CD: programme type (static): 'Rock Music'
        FICDecoder: SId 0xC4CD, SCIdS  0: MSC service component (SubChId 17)
        FICDecoder: SId 0xC4CD: programme service label 'Radio X' ('Radio X')
        PADChangeDynamicLabel SId 0xC4CD Label:'Radio X - Get Into the Music'
        PADChangeDynamicLabel SId 0xC4CD Label:'On Air Now on Radio X: Dan Gasser'        
        '''
        self.dablin_stderr_lookups = {
            "dab_type":  re.compile(f"FICDecoder: SId {self.sid}: audio service \(SubChId\s+\d+, (?P<v>.*), primary\)", re.IGNORECASE),
            "prog_type": re.compile(f"^FICDecoder: SId {self.sid}: programme type \(static\): '(?P<v>.*)'", re.IGNORECASE),
            "pad_label": re.compile(f"^PADChangeDynamicLabel SId {self.sid} Label:'(?P<v>.+)'", re.IGNORECASE),
            "media_fmt": re.compile(f"^EnsemblePlayer: format: (?P<v>.*)", re.IGNORECASE)
        }
        # Read dablins log files and populate q
        logger.info("Starting dablin log reader thread")
        self._t_dablin_log_reader=Thread(target=self._read_stream, args=(self.dablin_proc.stderr, self.dablin_stderr_q,))
        self._t_dablin_log_reader.start()

        # Consume q and post updates back to main UI
        logger.info("Starting dablin log parser thread")
        self._t_dablin_log_parser=Thread(target=self.dablin_log_parser.run, args=(self.dablin_stderr_lookups,))
        self._t_dablin_log_parser.start()

        logger.info("Player playing")


    def stop(self):
        self.currently_playing = None
        if self.dablin_proc is not None:
            self.dablin_proc.terminate()
            self.dablin_log_parser.stop()
        time.sleep(1)

    def _get_line_from_q(self, recd_threshold:int=200):
            s=""
            recd=0
            # Q returns characters not lines!!
            for c in self.dablin_stderr_q.get_nowait():
                s+=c
                recd+=1
                if c=="\n" or recd>recd_threshold:
                    break
            if recd>recd_threshold:
                self._recv_errors+=1
                logger.error("Buffer overflowed. Possible reception errors")
                logger.error("%s",s)
            return s
    
    def parse_dablin_output(self):
        '''
        Parse the dablin log and run regexs to extract info such as
        PAD announcements, DAB type etc. See play method for more
        details.
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
        '''
        Load default multiplexes.

        TODO: This could be fragile and what about non-uk?
        '''
        if Path("default-multiplexes.json"):
            with open("default-multiplexes.json") as m:
                s_json = json.load(m)
                self.multiplexes = s_json["uk"]
        return self.multiplexes

    def scan(self, ui_msg_callback=None):

        if ui_msg_callback is not None:
            ui_msg_callback("Starting Scan")

        # Cant scan while RTLSDR is in use
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
                    ui_msg_callback("Done", sub_msg=f"{data['ensemble']} {len(data['stations'])} stations")
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
    
