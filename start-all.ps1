param(
    [switch]$DryRun
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path

function Resolve-PythonCommand {
    $candidates = @()
    $candidates += "D:\project_APP\Anaconda\anaconda\envs\nanwang\python.exe"
    if ($env:CONDA_PREFIX) {
        $candidates += (Join-Path $env:CONDA_PREFIX "python.exe")
    }
    $candidates += "python"

    foreach ($candidate in $candidates) {
        if ($candidate -eq "python") {
            return "python"
        }
        if (Test-Path -LiteralPath $candidate) {
            return "& '$candidate'"
        }
    }
    return "python"
}

$PythonCommand = Resolve-PythonCommand

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
    Write-Host "[OK] $RelativePath"
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
    param(
        [int]$Port,
        [int]$TimeoutSeconds = 20
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        if (Test-Port $Port) {
            return $true
        }
        Start-Sleep -Milliseconds 500
    }
    return $false
}

function Start-ServiceWindow {
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
        Write-Host "[SKIP] $Name appears to be running on port $Port."
        return
    }

    Write-Host "[START] $Name"
    if ($DryRun) {
        Write-Host "       WorkDir: $WorkDir"
        Write-Host "       Command: $Command"
        return
    }

    $windowCommand = "`$Host.UI.RawUI.WindowTitle = 'TirednessWarning - $Name'; $Command"
    Start-Process -FilePath "powershell.exe" `
        -ArgumentList @("-NoExit", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", $windowCommand) `
        -WorkingDirectory $WorkDir `
        -WindowStyle Normal

    Start-Sleep -Seconds $StartupDelaySeconds
    if ($Port -gt 0) {
        if (Wait-Port -Port $Port -TimeoutSeconds 20) {
            Write-Host "[READY] $Name port $Port is listening."
        } else {
            Write-Host "[WARN] $Name port $Port is not ready yet. Check the $Name window logs."
        }
    }
}

Write-Host "Checking project files..."
Assert-RequiredPath "faceJavaServer\go2rtc\go2rtc.exe"
Assert-RequiredPath "faceJavaServer\go2rtc\go2rtc.yaml"
Assert-RequiredPath "facePythonServer\models\enet_b2_7.onnx"
Assert-RequiredPath "facePythonServer\models\face_detection_yunet_2023mar.onnx"
Assert-RequiredPath "facePythonServer\websocket_server.py"
Assert-RequiredPath "faceJavaServer\pom.xml"
Assert-RequiredPath "faceJavaServer\face-service\pom.xml"
Assert-RequiredPath "frontPage\vue-tlias-management\src\py\EEG_0417.py"
Assert-RequiredPath "frontPage\vue-tlias-management\package.json"

Write-Host ""
Write-Host "Starting services in order..."

Start-ServiceWindow `
    -Name "go2rtc" `
    -WorkDir (Join-Root "faceJavaServer\go2rtc") `
    -Command ".\go2rtc.exe -config .\go2rtc.yaml" `
    -Port 1984 `
    -StartupDelaySeconds 2

Start-ServiceWindow `
    -Name "face-python" `
    -WorkDir (Join-Root "facePythonServer") `
    -Command "$PythonCommand .\websocket_server.py" `
    -Port 8765 `
    -StartupDelaySeconds 2

Start-ServiceWindow `
    -Name "face-java" `
    -WorkDir (Join-Root "faceJavaServer") `
    -Command "mvn.cmd -f pom.xml -pl :face-service -am package -DskipTests; if (`$LASTEXITCODE -ne 0) { exit `$LASTEXITCODE }; java -jar .\face-service\target\face-service-0.0.1-SNAPSHOT-exec.jar --app.camera.config-file=config/camera-config.json" `
    -Port 8081 `
    -StartupDelaySeconds 6

Start-ServiceWindow `
    -Name "eeg-python" `
    -WorkDir $Root `
    -Command "$PythonCommand .\frontPage\vue-tlias-management\src\py\EEG_0417.py" `
    -Port 5000 `
    -StartupDelaySeconds 2 `
    -HealthUrl "http://127.0.0.1:5000/" `
    -ExpectedService "eeg-stream" `
    -ExpectedTransport "wifi-http"

Start-ServiceWindow `
    -Name "frontend-vite" `
    -WorkDir (Join-Root "frontPage\vue-tlias-management") `
    -Command "npm.cmd run dev -- --host 127.0.0.1" `
    -Port 5173 `
    -StartupDelaySeconds 2

Write-Host ""
if ($DryRun) {
    Write-Host "Dry run completed. No service windows were started."
} else {
    Write-Host "Startup commands were issued."
    Write-Host "Frontend: http://127.0.0.1:5173/index.html"
    Write-Host "go2rtc:   http://127.0.0.1:1984/"
    Write-Host "If Vite chooses another port, use the URL shown in the frontend-vite window."
}
