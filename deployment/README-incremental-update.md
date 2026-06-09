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

Upload the complete update directory or its ZIP file. Do not upload the source
tree, Java runtime, or the full Python environment again.
