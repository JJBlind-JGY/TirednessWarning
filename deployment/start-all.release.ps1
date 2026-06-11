param(
    [switch]$DryRun,
    [int]$FrontPort = 5173
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$LogDir = Join-Path $Root "logs"
$PidDir = Join-Path $Root "run"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
New-Item -ItemType Directory -Force -Path $PidDir | Out-Null

function Join-Root {
    param([string]$RelativePath)
    return Join-Path $Root $RelativePath
}

function Assert-RequiredPath {
    param([string]$RelativePath)
    $fullPath = Join-Root $RelativePath
    if (-not (Test-Path -LiteralPath $fullPath)) {
        throw "Required file or directory is missing: $RelativePath"
    }
}

function Test-Port {
    param([int]$Port)
    $client = [System.Net.Sockets.TcpClient]::new()
    try {
        $async = $client.BeginConnect("127.0.0.1", $Port, $null, $null)
        if (-not $async.AsyncWaitHandle.WaitOne(500)) {
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

function Wait-Port {
    param([int]$Port, [int]$TimeoutSeconds = 30)
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        if (Test-Port $Port) {
            return $true
        }
        Start-Sleep -Milliseconds 500
    }
    return $false
}

function Start-ReleaseService {
    param(
        [string]$Name,
        [string]$WorkDir,
        [string]$Command,
        [int]$Port,
        [int]$StartupDelaySeconds = 2,
        [string]$HealthUrl = "",
        [string]$ExpectedService = "",
        [string]$ExpectedTransport = ""
    )

    if ($Port -gt 0 -and (Test-Port $Port)) {
        if ($HealthUrl -and $ExpectedService) {
            try {
                $health = Invoke-RestMethod -Uri $HealthUrl -TimeoutSec 2
                if ($health.service -ne $ExpectedService) {
                    throw "unexpected service '$($health.service)'"
                }
                if ($ExpectedTransport -and $health.transport -ne $ExpectedTransport) {
                    throw "unexpected transport '$($health.transport)'"
                }
            } catch {
                throw "$Name cannot start because port $Port is occupied by an incompatible or stale process. Stop that process and run start-all.ps1 again. Details: $($_.Exception.Message)"
            }
        }
        Write-Host "[SKIP] $Name port $Port is already listening."
        return
    }

    $stdout = Join-Path $LogDir "$Name.out.log"
    $stderr = Join-Path $LogDir "$Name.err.log"
    Write-Host "[START] $Name"
    if ($DryRun) {
        Write-Host "       WorkDir: $WorkDir"
        Write-Host "       Command: $Command"
        return
    }

    $runner = Join-Path $LogDir "$Name.cmd"
    @(
        "@echo off",
        ("cd /d ""{0}""" -f $WorkDir),
        ("{0} >> ""{1}"" 2>> ""{2}""" -f $Command, $stdout, $stderr)
    ) | Set-Content -LiteralPath $runner -Encoding ASCII

    $processInfo = [System.Diagnostics.ProcessStartInfo]::new()
    $processInfo.FileName = "cmd.exe"
    $processInfo.WorkingDirectory = $Root
    $processInfo.UseShellExecute = $false
    $processInfo.CreateNoWindow = $true
    $processInfo.Arguments = "/d /c """ + $runner + """"

    $process = [System.Diagnostics.Process]::new()
    $process.StartInfo = $processInfo
    if (-not $process.Start()) {
        throw "Failed to start $Name"
    }
    Set-Content -LiteralPath (Join-Path $PidDir "$Name.pid") -Value $process.Id -Encoding ASCII

    Start-Sleep -Seconds $StartupDelaySeconds
    if ($Port -gt 0) {
        if (Wait-Port -Port $Port -TimeoutSeconds 30) {
            Write-Host "[READY] $Name port $Port is listening."
        } else {
            Write-Host "[WARN] $Name port $Port is not ready. Check logs: $stdout / $stderr"
        }
    }
}

Assert-RequiredPath "apps\go2rtc\go2rtc.exe"
Assert-RequiredPath "apps\go2rtc\go2rtc.yaml"
Assert-RequiredPath "apps\face-python\websocket_server.py"
Assert-RequiredPath "apps\face-python\models\enet_b2_7.onnx"
Assert-RequiredPath "apps\face-service\face-service.jar"
Assert-RequiredPath "apps\eeg-python\EEG_0417.py"
Assert-RequiredPath "apps\front\dist\index.html"
Assert-RequiredPath "apps\front\static-server\static-server.py"
Assert-RequiredPath "runtime\java\bin\java.exe"

$pythonExe = Join-Root "runtime\python\venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $pythonExe)) {
    $pythonExe = Join-Root "runtime\python\venv\python.exe"
}
if (-not (Test-Path -LiteralPath $pythonExe)) {
    throw "Required Python runtime is missing: runtime\python\venv\Scripts\python.exe or runtime\python\venv\python.exe"
}

Copy-Item -LiteralPath (Join-Root "config\go2rtc.yaml") -Destination (Join-Root "apps\go2rtc\go2rtc.yaml") -Force
Copy-Item -LiteralPath (Join-Root "config\python-config.yaml") -Destination (Join-Root "apps\face-python\config.yaml") -Force

$env:EEG_CONFIG_FILE = Join-Root "config\eeg-devices.json"
$javaExe = Join-Root "runtime\java\bin\java.exe"

Start-ReleaseService `
    -Name "go2rtc" `
    -WorkDir (Join-Root "apps\go2rtc") `
    -Command ".\go2rtc.exe -config .\go2rtc.yaml" `
    -Port 1984

Start-ReleaseService `
    -Name "face-python" `
    -WorkDir (Join-Root "apps\face-python") `
    -Command """$pythonExe"" .\websocket_server.py" `
    -Port 8765

Start-ReleaseService `
    -Name "face-java" `
    -WorkDir $Root `
    -Command """$javaExe"" -jar ""$Root\apps\face-service\face-service.jar"" --spring.config.additional-location=""file:$Root\config\application-release.properties""" `
    -Port 8081 `
    -StartupDelaySeconds 6

Start-ReleaseService `
    -Name "eeg-python" `
    -WorkDir (Join-Root "apps\eeg-python") `
    -Command "set ""EEG_CONFIG_FILE=$Root\config\eeg-devices.json"" && ""$pythonExe"" .\EEG_0417.py" `
    -Port 5000 `
    -HealthUrl "http://127.0.0.1:5000/" `
    -ExpectedService "eeg-stream" `
    -ExpectedTransport "wifi-http"

Start-ReleaseService `
    -Name "front" `
    -WorkDir (Join-Root "apps\front\static-server") `
    -Command """$pythonExe"" .\static-server.py --port $FrontPort --web-root ""$Root\apps\front\dist""" `
    -Port $FrontPort

Write-Host ""
Write-Host ("Frontend: http://127.0.0.1:{0}/" -f $FrontPort)
Write-Host "Logs:     $LogDir"
