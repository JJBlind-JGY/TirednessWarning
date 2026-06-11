# TirednessWarning Incremental Update

This update is for a machine that already has `TirednessWarning-Release-Full`.

1. Copy the extracted update directory into the existing Full release root.
2. Run PowerShell as the same user used for the original deployment.
3. Execute:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\TirednessWarning-Update-20260607\update.ps1
```

The script updates the stop helper, stops services, backs up every replaced file under `backups/`, installs
ONNX Runtime from local wheels, preserves existing configuration values, checks
the package, and restarts the services. It does not delete existing files.

This version replaces serial EEG input with local WiFi input. After updating:

1. Flash the firmware under `hardware/esp32-c3-eeg-wifi`.
2. Connect the computer and EEG devices to the same 2.4 GHz WiFi.
3. Edit `config/eeg-devices.json` and set each device `baseUrl`.
4. Reserve each device IP in the router DHCP settings.

The previous `config/eeg-devices.json` is retained in the timestamped backup
directory before the WiFi-format configuration is installed.

Upload the complete update directory or its ZIP file. Do not upload the source
tree, Java runtime, or the full Python environment again.
