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

