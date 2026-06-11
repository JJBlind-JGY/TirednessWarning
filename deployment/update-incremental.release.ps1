param(
    [string]$TargetRoot = "",
    [switch]$SkipRestart
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$UpdateRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not $TargetRoot) {
    $TargetRoot = Split-Path -Parent $UpdateRoot
}
$TargetRoot = (Resolve-Path -LiteralPath $TargetRoot).Path
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$backupRoot = Join-Path $TargetRoot ("backups\incremental-{0}" -f $stamp)

function Assert-Path {
    param([string]$Path, [string]$Label)
    if (-not (Test-Path -LiteralPath $Path)) {
        throw "Missing $Label`: $Path"
    }
}

function Ensure-Directory {
    param([string]$Path)
    New-Item -ItemType Directory -Force -Path $Path | Out-Null
}

function Backup-And-Copy {
    param([string]$RelativePath)
    $source = Join-Path $UpdateRoot $RelativePath
    $target = Join-Path $TargetRoot $RelativePath
    $backup = Join-Path $backupRoot $RelativePath
    Assert-Path $source "update file"

    if (Test-Path -LiteralPath $target) {
        Ensure-Directory (Split-Path -Parent $backup)
        Copy-Item -LiteralPath $target -Destination $backup -Recurse -Force
    }

    Ensure-Directory (Split-Path -Parent $target)
    if ((Get-Item -LiteralPath $source).PSIsContainer) {
        Ensure-Directory $target
        Get-ChildItem -LiteralPath $source -Force | ForEach-Object {
            Copy-Item -LiteralPath $_.FullName -Destination $target -Recurse -Force
        }
    } else {
        Copy-Item -LiteralPath $source -Destination $target -Force
    }
    Write-Host "[UPDATED] $RelativePath"
}

Assert-Path (Join-Path $TargetRoot "stop-all.ps1") "target stop script"
Assert-Path (Join-Path $TargetRoot "start-all.ps1") "target start script"
Assert-Path (Join-Path $TargetRoot "config\python-config.yaml") "target Python config"

$pythonExe = Join-Path $TargetRoot "runtime\python\venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $pythonExe)) {
    $pythonExe = Join-Path $TargetRoot "runtime\python\venv\python.exe"
}
Assert-Path $pythonExe "target Python runtime"

Ensure-Directory $backupRoot
Backup-And-Copy "stop-all.ps1"

Write-Host "Stopping existing services..."
& (Join-Path $TargetRoot "stop-all.ps1")

Backup-And-Copy "apps\face-service\face-service.jar"
Backup-And-Copy "apps\face-python\websocket_server.py"
Backup-And-Copy "apps\face-python\models\yawn_model_80_lite.onnx"
Backup-And-Copy "apps\eeg-python\EEG_0417.py"
Backup-And-Copy "config\eeg-devices.json"
Backup-And-Copy "apps\front\dist"
Backup-And-Copy "hardware\esp32-c3-eeg-wifi"
Backup-And-Copy "check-env.ps1"

$configPath = Join-Path $TargetRoot "config\python-config.yaml"
$configBackup = Join-Path $backupRoot "config\python-config.yaml"
Ensure-Directory (Split-Path -Parent $configBackup)
Copy-Item -LiteralPath $configPath -Destination $configBackup -Force
& $pythonExe (Join-Path $UpdateRoot "tools\merge-python-config.py") $configPath
if ($LASTEXITCODE -ne 0) {
    throw "Failed to merge Python configuration."
}

$wheelDir = Join-Path $UpdateRoot "wheels"
Assert-Path $wheelDir "offline wheel directory"
& $pythonExe -m pip install --no-index --find-links $wheelDir "onnxruntime==1.22.0"
if ($LASTEXITCODE -ne 0) {
    throw "Offline onnxruntime installation failed."
}

Push-Location $TargetRoot
try {
    & (Join-Path $TargetRoot "check-env.ps1")
    if ($LASTEXITCODE -ne 0) {
        throw "Release environment check failed."
    }
} finally {
    Pop-Location
}

if (-not $SkipRestart) {
    Write-Host "Starting updated services..."
    & (Join-Path $TargetRoot "start-all.ps1")
}

Write-Host ""
Write-Host "Incremental update completed."
Write-Host ("Backup directory: {0}" -f $backupRoot)
