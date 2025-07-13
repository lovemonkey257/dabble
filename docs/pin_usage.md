# GPIO/SPI Pin arrangements

## LCD

| Desc | BCM       | PIN | Pin Column |
| ---- | --------- | --- | ---------- |
| 3.5V | 3V3       | 1   | 1  |
| GND  | GND       | 5   | 3  |
| CS   | GPIO7/CE1 | 26  | 13 |
| SCK  | GPIO11/SCLK | 23  | 12 |
| MOSI | GPIO10/MOSI   | 19  | 10 |
| DC   | GPIO9/MISO    | 21  | 11 |
| BL   | GPIO16  | 36  | 18 |

## Left Encoder

| Desc | BCM | PIN | Pin Column |
| - | - | - | - |
| VCC | 5V | 1 | 1 |
| GND | GND | 9 | 5 |
| A   | GPIO17 | 11 | 6 |
| B   | GPIO27 | 13 | 7 |
| C   | GPIO23 | 16 | 8 |

## Right Encoder

| Desc | BCM | PIN | Pin Column |
| - | - | - | - |
| VCC | 5V | 4 | 2 |
| GND | GND | 14 | 7 |
| A   | GPIO24 | 18 | 9 |
| B   | GPIO25 | 22 | 11 |
| C   | GPIO22 | 15 | 8 |

## Speaker Bonnet/DAC

| Desc | BCM | PIN | Pin Column |
| - | - | - | - |
| 5V | | | |
| 5V | | | |
| 3V | | | |
| GND | | | |
| PWM CLK  | GPIO18 | 12 | 6 |
| PCM FS   | GPIO19 | 35 | 18 |
| PCM DOUT | GPIO21 | 40 | 20 |

## Shared Pins

LCD and Bonnet share GPIO19 by default which causes distortion.
