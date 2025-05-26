# dabble
A DAB radio project based on a PI, small LCD and some LED encoders. Very much a work in progress.

## Components
- PI3 or greater. I'm currently using a PI5 which is probably overkill. Will probably try a Pi Zero W.
- [Pimoroni 0.96" LCD](https://shop.pimoroni.com/products/0-96-spi-colour-lcd-160x80-breakout). I got mine from PiHut.
- 2 x [LED encoders](https://shop.pimoroni.com/products/rgb-encoder-breakout) although I may change these to ones that include a button. But LEDS....
- RTLSDR (a cheap one will probably do, I'm using an official RTL-SDR.com v3)
- No idea about an enclosure yet. Probably have to 3D print or make out of wood? Will get the basic electronics and code working first.

## Software
- Custom code
- Modififed version of of eti-cmdline from JvanKatwijk. Forked here https://github.com/lovemonkey257/eti-stuff
- dablin, https://github.com/Opendigitalradio/dablin

## Build

### `dablin`
- `sudo apt install dablin`

### `eti-cmdline`
- `git clone https://github.com/lovemonkey257/eti-stuff.git`
- `cd eti-stuff\eti-cmdline`
- `mkdir build && cd build`
- `cmake .. -DRTLSDR=ON`
- `make && sudo make install`

This should put `eti-cmdline-rtlsdr` into `/usr/local/bin`

### Python
- `sudo apt install python3-alsaaudio`
- Create venv `pip -mvenv venv`
- Edit ./venv/pyvenv.cfg and ensure `include-system-site-packages` is `true`
- `pip install -r requirements.txt`

## Config
TODO
