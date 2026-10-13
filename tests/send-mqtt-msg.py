import paho.mqtt.publish as publish
import argparse

valid_cmds = ["gamma","gfxbars","shutdown","melfmin","melfmax"]

parser = argparse.ArgumentParser(description="Send local MQTT msg")
parser.add_argument("-c", "--channel",type=str, choices=valid_cmds, help="channel to send msg to")
parser.add_argument("-v", "--value",  type=str, help="value to send")
args = parser.parse_args()

ch = args.channel
v  = str(args.value)

if ch in valid_cmds:
    print(f'Sending {v} to dabble-radio/{ch}')
    publish.single(
        topic=f"dabble-radio/{ch}",
        payload=v,
        hostname="localhost",
        port=1883
    )
