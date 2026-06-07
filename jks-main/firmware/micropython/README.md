# MicroPython OLED Controller

This is the first working firmware path for the ESP32-C3 OLED board.

Detected hardware:

- ESP32-C3
- OLED I2C address: `0x3C`
- OLED I2C pins: `SDA=GPIO4`, `SCL=GPIO5`
- Screen class: external 128x64 I2C OLED module
- Working display driver: `SH1106` page-addressing mode with column offset `2`

The earlier `SSD1306` mode can light the panel but produces random pixels on this module. Keep `main.py` on `SH1106` unless the hardware module changes.

Upload files:

```bash
/tmp/jks-pio/bin/mpremote connect /dev/cu.usbmodem5B900048301 fs cp firmware/micropython/ssd1306_min.py :ssd1306_min.py
/tmp/jks-pio/bin/mpremote connect /dev/cu.usbmodem5B900048301 fs cp firmware/micropython/main.py :main.py
```

Reset and test:

```bash
/tmp/jks-pio/bin/mpremote connect /dev/cu.usbmodem5B900048301 reset
/tmp/jks-pio/bin/mpremote connect /dev/cu.usbmodem5B900048301 exec 'print("alive")'
```

Serial commands:

```text
clear
JKS OLED TEST
{"cmd":"text","text":"JKS OLED TEST"}
{"cmd":"emotion","name":"happy","text":"READY"}
{"cmd":"emotion","name":"thinking","text":"WAIT"}
```
