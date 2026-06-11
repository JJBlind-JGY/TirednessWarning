# ESP32-C3 EEG WiFi firmware

1. Install the VS Code PlatformIO extension.
2. Copy `include/wifi_config.example.h` to `include/wifi_config.h`.
3. Set the 2.4 GHz WiFi SSID, password, and a unique `EEG_DEVICE_ID`.
4. Open this directory in PlatformIO, then build and upload the
   `esp32-c3-devkitm-1` environment.
5. Read the assigned IP from the router and create a DHCP reservation for it.
6. Verify `http://DEVICE_IP/api/status`, then configure the same base URL in
   the TirednessWarning device-management page.

After uploading, open PlatformIO **Serial Monitor** at `115200` baud. When the
device connects successfully it prints:

```text
EEG WiFi device is ready
IP address: 192.168.1.50
Base URL: http://192.168.1.50
Status API: http://192.168.1.50/api/status
```

If the monitor was opened after this message appeared, press the board reset
button once to print it again.

The firmware also prints a status line every five seconds, so reconnecting the
monitor later still reveals the current address:

```text
EEG_WIFI_STATUS,connected,ssid=...,ip=192.168.1.50,baseUrl=http://192.168.1.50,rssi=-45,samples=12345
```

TGAM wiring:

- ESP32-C3 GPIO 1 receives TGAM TX.
- ESP32-C3 GPIO 0 connects to TGAM RX when required.
- TGAM baud rate is 57600.

The application reads incremental samples from:

```text
GET /api/eeg?after=0&limit=512
```

The device retains the most recent four seconds of 512 Hz samples. A client
must continue from `returnedUntilIndex`; `overflow=true` means samples were
lost because the client fell behind the ring buffer, and `lostSamples` reports
the number of unavailable points. The original `/api/data` and `/export.csv`
diagnostic endpoints remain available.
