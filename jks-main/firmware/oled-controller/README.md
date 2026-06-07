# JKS OLED Controller Firmware

Minimal ESP32-C3 firmware for controlling an onboard SSD1306 OLED over serial.

Default test target:

```bash
/tmp/jks-pio/bin/platformio run -d firmware/oled-controller -e c3_oled_72x40_gpio5_6
```

Upload:

```bash
/tmp/jks-pio/bin/platformio run -d firmware/oled-controller -e c3_oled_72x40_gpio5_6 -t upload --upload-port /dev/cu.usbmodem5B900048301
```

Serial commands:

```text
JKS OLED TEST
clear
{"cmd":"text","text":"JKS OLED TEST"}
{"cmd":"emotion","name":"happy","text":"READY"}
```

Alternative environments:

- `c3_oled_72x40_gpio8_9`
- `c3_oled_128x64_gpio5_6`
- `c3_oled_128x64_gpio8_9`
