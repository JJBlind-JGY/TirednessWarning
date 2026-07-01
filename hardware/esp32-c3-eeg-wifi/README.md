# ESP32-C3 EEG WiFi firmware

This is the application-compatible firmware for the upgraded EEG hardware. Do
not use the vendor /api/snapshot WiFi firmware with TirednessWarning: the
application consumes the incremental /api/eeg protocol defined here.

## Build and upload

1. Install the VS Code PlatformIO extension.
2. Copy include/wifi_config.example.h to include/wifi_config.h.
3. Set the **2.4 GHz** WiFi SSID, password, and a unique EEG_DEVICE_ID.
   wifi_config.h is ignored by Git; never commit real WiFi credentials.
4. Open this directory in PlatformIO, then build and upload the
   esp32-c3-devkitm-1 environment.
5. Open PlatformIO Serial Monitor at 115200 baud and reset the board.
6. Reserve the assigned IP in the router (DHCP reservation), then enter
   http://DEVICE_IP in the TirednessWarning device-management page.

The firmware first tests whether TGAM is already streaming RAW data at 57600
baud. If detection fails, it connects at 9600, sends the RAW-mode command, and
retries at 57600 twice. It accepts TGAM rows 0x80, 0x82, 0x81, and 0x83.

TGAM wiring:

- TGAM TX -> ESP32-C3 GPIO 1
- TGAM RX -> ESP32-C3 GPIO 0
- TGAM GND -> ESP32-C3 GND

A successful WiFi connection prints the device IP and these endpoints:

    Status API: http://DEVICE_IP/api/status
    EEG API: http://DEVICE_IP/api/eeg?after=0&limit=20

The firmware also prints a status line every five seconds:

    EEG_WIFI_STATUS,connected,ssid=...,ip=192.168.1.50,baseUrl=http://192.168.1.50,rssi=-45,samples=12345

## Data protocol

The application reads incremental samples from:

    GET /api/eeg?after=0&limit=512

The device retains the most recent four seconds of 512 Hz samples. Continue
from returnedUntilIndex. If overflow=true, the client fell behind the ring
buffer; lostSamples reports how many samples are unavailable. The response
shape remains compatible whether the TGAM sends integer (0x83) or big-endian
float (0x81) frequency-band values.

The diagnostic /api/data and /export.csv endpoints remain available.

## USB firmware and electrode use

The vendor EEG debug firmware is a transparent USB bridge. Configure its
serial device in TirednessWarning at 460800 baud. Older serial firmware can
still use its original manually selected baud rate.

Before collection, clean the skin with alcohol and keep the wearer still:

- Ear-clip version: place the EEG electrode on the forehead and attach the clip.
- Three-metal-electrode version: press the small ends gently against the scalp
  and adjust position until contact quality is stable.
- If contact impedance remains high, clean and reposition the electrodes before
  calibration or analysis.