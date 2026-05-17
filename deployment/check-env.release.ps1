param(
    [int]$FrontPort = 5173
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$checks = @(
    "runtime\java\bin\java.exe",
    "apps\go2rtc\go2rtc.exe",
    "apps\go2rtc\go2rtc.yaml",
    "apps\face-service\face-service.jar",
    "apps\face-python\websocket_server.py",
    "apps\face-python\model.pt",
    "apps\face-python\models\enet_b2_7.onnx",
    "apps\face-python\models\face_detection_yunet_2023mar.onnx",
    "apps\eeg-python\EEG_0417.py",
    "apps\front\dist\index.html",
    "apps\front\static-server\static-server.py",
    "config\application-release.properties",
    "config\go2rtc.yaml",
    "config\python-config.yaml",
    "config\eeg-devices.json"
)

$failed = $false
foreach ($relative in $checks) {
    $path = Join-Path $Root $relative
    if (Test-Path -LiteralPath $path) {
        Write-Host "[OK]   $relative"
    } else {
        Write-Host "[MISS] $relative"
        $failed = $true
    }
}

$venvPython = Join-Path $Root "runtime\python\venv\Scripts\python.exe"
$condaPython = Join-Path $Root "runtime\python\venv\python.exe"
if ((Test-Path -LiteralPath $venvPython) -or (Test-Path -LiteralPath $condaPython)) {
    Write-Host "[OK]   runtime\python\venv python runtime"
} else {
    Write-Host "[MISS] runtime\python\venv\Scripts\python.exe or runtime\python\venv\python.exe"
    $failed = $true
}

function Test-Port {
    param([int]$Port)
    $client = [System.Net.Sockets.TcpClient]::new()
    try {
        $async = $client.BeginConnect("127.0.0.1", $Port, $null, $null)
        if (-not $async.AsyncWaitHandle.WaitOne(300)) {
            return $false
        }
        $client.EndConnect($async)
        return $true
    } catch {
        return $false
    } finally {
        $client.Close()
    }
}

foreach ($port in @(1984, 8765, 8766, 8081, 5000, $FrontPort)) {
    if (Test-Port $port) {
        Write-Host "[WARN] Port $port is already in use."
    } else {
        Write-Host "[OK]   Port $port is available."
    }
}

if ($failed) {
    throw "Release package is incomplete."
}

Write-Host "Environment check completed."
