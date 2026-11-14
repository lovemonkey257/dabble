# GPIO & SPI Pin Assignments

This document tracks the physical and logical pin assignments for the project hardware. 
**Target Hardware:** Raspberry Pi (BCM pin numbering).

> [!WARNING]
> **GPIO Conflict:** By default, the LCD and Speaker Bonnet share **GPIO19**, which causes audio distortion. Ensure you have addressed this conflict in your hardware configuration.

## Component Mapping

### LCD
| Description | BCM Pin | Physical Pin | Physical Column |
| :--- | :--- | :--- | :--- |
| 3.5V | 3V3 | 1 | 1 |
| GND | GND | 5 | 3 |
| CS | GPIO7 / CE1 | 26 | 13 |
| SCK | GPIO11 / SCLK | 23 | 12 |
| MOSI | GPIO10 / MOSI | 19 | 10 |
| DC | GPIO9 / MISO | 21 | 11 |
| BL (Backlight) | GPIO26 | 37 | 19 |

### Left Encoder
| Description | BCM Pin | Physical Pin | Physical Column |
| :--- | :--- | :--- | :--- |
| VCC | 5V | 1 | 1 |
| GND | GND | 9 | 5 |
| A | GPIO17 | 11 | 6 |
| B | GPIO27 | 13 | 7 |
| C | GPIO23 | 16 | 8 |

### Right Encoder
| Description | BCM Pin | Physical Pin | Physical Column |
| :--- | :--- | :--- | :--- |
| VCC | 5V | 4 | 2 |
| GND | GND | 14 | 7 |
| A | GPIO24 | 18 | 9 |
| B | GPIO25 | 22 | 11 |
| C | GPIO22 | 15 | 8 |

### Speaker Bonnet / DAC
| Description | BCM Pin | Physical Pin | Physical Column |
| :--- | :--- | :--- | :--- |
| 5V | 5V | - | - |
| 3V | 3V3 | - | - |
| GND | GND | - | - |
| PWM CLK | GPIO18 | 12 | 6 |
| PCM FS | GPIO19 | 35 | 18 |
| PCM DOUT | GPIO21 | 40 | 20 |

## Power Button Configuration

**Reference:** [lbussy/gpio-shutdown gist](https://gist.github.com/lbussy/9e81cbcc617952f1250e353bd42e7775)

### Required `/boot/config.txt` Overlays
```text
dtoverlay=gpio-shutdown,debounce=500   
dtoverlay=gpio-led,gpio=3,label=pwrled,trigger=default-on,active_low=0
```

### Wiring
| Description | BCM Pin | Physical Pin | Physical Column |
| :--- | :--- | :--- | :--- |
| LED VCC | GPIO3 | 5 | 3 |
| LED GND | GND | 9 | 5 |
| Boot Switch | GPIO16 | 36 | 18 |
| Boot GND | GND | 34 | 17 |
