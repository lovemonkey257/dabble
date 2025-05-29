import logging
import json
from pathlib import Path

class RadioStations():
    def __init__(self):
        self.stations ={}
        self.station_list = []
        self.station_list_index = {}
        self.total_stations = 0
        
        self.load_stations()

    def load_stations(self):
        with open("station-list.json") as j:
            self.stations = json.load(j)
        self.station_list=sorted(list(self.stations.keys()))
        self.station_list_index={ s:i for i,s in enumerate(self.station_list) }
        self.total_stations = len(self.station_list)

    def tuning_details(self, station_name) -> tuple[str,str,str]|None:
        if station_name in self.stations:
            station_sid = self.stations[station_name]['sid']
            station_channel = self.stations[station_name]['channel']
            ensemble = self.stations[station_name]['ensemble']
            return (station_channel, station_sid, ensemble)
        return None

    def select_station(self, i):
        station_i=i%len(self.station_list)
        name=self.station_list[station_i]
        return (name, self.stations[name])
    
    def station_index(self, station_name:str) -> int:
        if station_name in self.stations:
            return self.station_list_index[station_name]
        return 0

