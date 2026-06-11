# powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\build-release.ps1 -ReleaseName "TirednessWarning-Release-Full" -JavaHome "D:\project_APP\Java\JDK" -PythonEnv "D:\project_APP\Anaconda\anaconda\envs\nanwang"
param(
    [string]$ReleaseName = "TirednessWarning-Release",
    [string]$JavaHome = "",
    [string]$PythonExe = "",
    [string]$PythonEnv = "",
    [switch]$SkipRuntime,
    [switch]$SkipBuild,
    [switch]$SkipPythonInstall
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$ReleaseDir = Join-Path $Root $ReleaseName

function Join-Root {
    param([string]$RelativePath)
    return Join-Path $Root $RelativePath
}

function Ensure-Directory {
    param([string]$Path)
    New-Item -ItemType Directory -Force -Path $Path | Out-Null
}

function Assert-Path {
    param([string]$RelativePath)
    $path = Join-Root $RelativePath
    if (-not (Test-Path -LiteralPath $path)) {
        throw "Required path is missing: $RelativePath"
    }
    return $path
}

function Copy-Path {
    param(
        [string]$Source,
        [string]$Destination
    )
    if (-not (Test-Path -LiteralPath $Source)) {
        throw "Copy source is missing: $Source"
    }
    $sourceItem = Get-Item -LiteralPath $Source
    if ($sourceItem.PSIsContainer) {
        Ensure-Directory $Destination
        Get-ChildItem -LiteralPath $Source -Force | ForEach-Object {
            Copy-Item -LiteralPath $_.FullName -Destination $Destination -Recurse -Force
        }
    } else {
        Ensure-Directory (Split-Path -Parent $Destination)
        Copy-Item -LiteralPath $Source -Destination $Destination -Force
    }
}

function Archive-ExistingRelease {
    if (-not (Test-Path -LiteralPath $ReleaseDir)) {
        return
    }

    $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $archive = Join-Path $Root ("{0}.archived-{1}" -f $ReleaseName, $stamp)
    $index = 1
    while (Test-Path -LiteralPath $archive) {
        $archive = Join-Path $Root ("{0}.archived-{1}-{2}" -f $ReleaseName, $stamp, $index)
        $index++
    }
    Rename-Item -LiteralPath $ReleaseDir -NewName (Split-Path -Leaf $archive)
    Write-Host ("Archived existing release directory to {0}" -f $archive)
}

function Find-JavaHome {
    if ($JavaHome -and (Test-Path -LiteralPath (Join-Path $JavaHome "bin\java.exe"))) {
        return $JavaHome
    }

    if ($env:JAVA_HOME -and (Test-Path -LiteralPath (Join-Path $env:JAVA_HOME "bin\java.exe"))) {
        return $env:JAVA_HOME
    }

    $javaCommand = Get-Command java.exe -ErrorAction SilentlyContinue
    if ($javaCommand) {
        $javaBin = Split-Path -Parent $javaCommand.Source
        return Split-Path -Parent $javaBin
    }

    throw "Java runtime was not found. Set JAVA_HOME or use -SkipRuntime."
}

function Find-Python {
    if ($PythonEnv) {
        $envPython = Join-Path $PythonEnv "python.exe"
        $venvPython = Join-Path $PythonEnv "Scripts\python.exe"
        if (Test-Path -LiteralPath $envPython) {
            return $envPython
        }
        if (Test-Path -LiteralPath $venvPython) {
            return $venvPython
        }
        throw "PythonEnv does not contain python.exe or Scripts\python.exe: $PythonEnv"
    }

    if ($PythonExe -and (Test-Path -LiteralPath $PythonExe)) {
        return $PythonExe
    }

    $python = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($python) {
        return $python.Source
    }
    throw "python.exe was not found. Install Python 3.10 on the build machine or use -SkipRuntime."
}

function Get-PythonEnvRoot {
    param([string]$PythonPath)

    if ($PythonEnv) {
        return (Resolve-Path -LiteralPath $PythonEnv).Path
    }

    $pythonDir = Split-Path -Parent $PythonPath
    if ((Split-Path -Leaf $pythonDir).ToLowerInvariant() -eq "scripts") {
        return Split-Path -Parent $pythonDir
    }

    return $pythonDir
}

function Assert-Python310 {
    param([string]$PythonPath)

    $versionText = & $PythonPath -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')"
    if ($LASTEXITCODE -ne 0) {
        throw "Could not inspect Python version: $PythonPath"
    }

    if ($versionText -notmatch "^3\.10\.") {
        throw "Python 3.10 is required for the portable runtime, but $PythonPath is $versionText. Pass -PythonExe with a Python 3.10 interpreter."
    }

    Write-Host ("Using Python {0}: {1}" -f $versionText, $PythonPath)
}

function Invoke-Step {
    param(
        [string]$Name,
        [scriptblock]$Action
    )
    Write-Host ""
    Write-Host ("==> {0}" -f $Name)
    & $Action
}

$ResolvedJavaHome = ""
$ResolvedPythonExe = ""
if (-not $SkipRuntime) {
    $ResolvedJavaHome = Find-JavaHome
    $ResolvedPythonExe = Find-Python
    Assert-Python310 $ResolvedPythonExe
}

Archive-ExistingRelease

Ensure-Directory $ReleaseDir
Ensure-Directory (Join-Path $ReleaseDir "runtime\java")
Ensure-Directory (Join-Path $ReleaseDir "runtime\python")
Ensure-Directory (Join-Path $ReleaseDir "apps\face-service")
Ensure-Directory (Join-Path $ReleaseDir "apps\face-python")
Ensure-Directory (Join-Path $ReleaseDir "apps\eeg-python")
Ensure-Directory (Join-Path $ReleaseDir "apps\go2rtc")
Ensure-Directory (Join-Path $ReleaseDir "apps\front\dist")
Ensure-Directory (Join-Path $ReleaseDir "apps\front\static-server")
Ensure-Directory (Join-Path $ReleaseDir "config")
Ensure-Directory (Join-Path $ReleaseDir "logs")
Ensure-Directory (Join-Path $ReleaseDir "hardware")

if (-not $SkipBuild) {
    Invoke-Step "Build Java service" {
        Push-Location (Join-Root "faceJavaServer")
        try {
            if (Test-Path -LiteralPath ".\mvnw.cmd") {
                & .\mvnw.cmd -pl face-service -am clean package
            } else {
                & mvn.cmd -pl face-service -am clean package
            }
        } finally {
            Pop-Location
        }
    }

    Invoke-Step "Build frontend" {
        Push-Location (Join-Root "frontPage\vue-tlias-management")
        try {
            & npm.cmd run build
        } finally {
            Pop-Location
        }
    }
}

Invoke-Step "Copy application files" {
    Copy-Path (Assert-Path "faceJavaServer\face-service\target\face-service-0.0.1-SNAPSHOT-exec.jar") (Join-Path $ReleaseDir "apps\face-service\face-service.jar")
    Copy-Path (Assert-Path "frontPage\vue-tlias-management\dist") (Join-Path $ReleaseDir "apps\front\dist")
    Copy-Path (Assert-Path "deployment\static-server.py") (Join-Path $ReleaseDir "apps\front\static-server\static-server.py")

    Copy-Path (Assert-Path "faceJavaServer\go2rtc\go2rtc.exe") (Join-Path $ReleaseDir "apps\go2rtc\go2rtc.exe")
    Copy-Path (Assert-Path "faceJavaServer\go2rtc\go2rtc.yaml") (Join-Path $ReleaseDir "apps\go2rtc\go2rtc.yaml")

    Copy-Path (Assert-Path "facePythonServer\websocket_server.py") (Join-Path $ReleaseDir "apps\face-python\websocket_server.py")
    Copy-Path (Assert-Path "facePythonServer\face_emotion_model.py") (Join-Path $ReleaseDir "apps\face-python\face_emotion_model.py")
    Copy-Path (Assert-Path "facePythonServer\model.pt") (Join-Path $ReleaseDir "apps\face-python\model.pt")
    Copy-Path (Assert-Path "facePythonServer\config.yaml") (Join-Path $ReleaseDir "apps\face-python\config.yaml")
    Copy-Path (Assert-Path "facePythonServer\models") (Join-Path $ReleaseDir "apps\face-python\models")
    Copy-Path (Assert-Path "facePythonServer\certs") (Join-Path $ReleaseDir "apps\face-python\certs")

    Copy-Path (Assert-Path "frontPage\vue-tlias-management\src\py\EEG_0417.py") (Join-Path $ReleaseDir "apps\eeg-python\EEG_0417.py")
    Copy-Path (Assert-Path "hardware\esp32-c3-eeg-wifi") (Join-Path $ReleaseDir "hardware\esp32-c3-eeg-wifi")
    if (Test-Path -LiteralPath (Join-Root "frontPage\vue-tlias-management\src\py\config")) {
        Copy-Path (Join-Root "frontPage\vue-tlias-management\src\py\config") (Join-Path $ReleaseDir "apps\eeg-python\config")
    }
}

Invoke-Step "Copy external configuration" {
    Copy-Path (Assert-Path "faceJavaServer\go2rtc\go2rtc.yaml") (Join-Path $ReleaseDir "config\go2rtc.yaml")
    Copy-Path (Assert-Path "facePythonServer\config.yaml") (Join-Path $ReleaseDir "config\python-config.yaml")

    if (Test-Path -LiteralPath (Join-Root "faceJavaServer\config\camera-config.json")) {
        Copy-Path (Join-Root "faceJavaServer\config\camera-config.json") (Join-Path $ReleaseDir "config\camera-config.json")
    } elseif (Test-Path -LiteralPath (Join-Root "faceJavaServer\face-service\config\camera-config.json")) {
        Copy-Path (Join-Root "faceJavaServer\face-service\config\camera-config.json") (Join-Path $ReleaseDir "config\camera-config.json")
    } else {
        "[]" | Set-Content -LiteralPath (Join-Path $ReleaseDir "config\camera-config.json") -Encoding UTF8
    }

    if (Test-Path -LiteralPath (Join-Root "faceJavaServer\config\personnel-config.json")) {
        Copy-Path (Join-Root "faceJavaServer\config\personnel-config.json") (Join-Path $ReleaseDir "config\personnel-config.json")
    } elseif (Test-Path -LiteralPath (Join-Root "faceJavaServer\face-service\config\personnel-config.json")) {
        Copy-Path (Join-Root "faceJavaServer\face-service\config\personnel-config.json") (Join-Path $ReleaseDir "config\personnel-config.json")
    } else {
        "[]" | Set-Content -LiteralPath (Join-Path $ReleaseDir "config\personnel-config.json") -Encoding UTF8
    }

    if (Test-Path -LiteralPath (Join-Root "frontPage\vue-tlias-management\src\py\config\eeg-devices.json")) {
        Copy-Path (Join-Root "frontPage\vue-tlias-management\src\py\config\eeg-devices.json") (Join-Path $ReleaseDir "config\eeg-devices.json")
    } else {
        "[]" | Set-Content -LiteralPath (Join-Path $ReleaseDir "config\eeg-devices.json") -Encoding UTF8
    }

    @"
websocket.modelServer.url=ws://127.0.0.1:8765
web.url=*
websocket.webUser.url=/topic/face_fatigue/
face.camera.sample-interval-ms=1000
app.camera.config-file=config/camera-config.json
app.go2rtc.config-file=apps/go2rtc/go2rtc.yaml
app.go2rtc.api-base=http://127.0.0.1:1984
app.abnormal-sample.eeg-base-url=http://127.0.0.1:5000
app.alert-log.dir=logs/alerts
app.abnormal-sample.dir=data/abnormal-samples
app.normal-sample.dir=data/normal-samples
app.demo-sample.dir=data/demo-samples
app.normal-sample.max-bytes=21474836480
app.normal-inference-log.dir=logs/normal-inference
app.normal-inference-log.retention-days=4
app.personnel.config-file=config/personnel-config.json
spring.application.name=faceservice
server.port=8081
spring.servlet.multipart.enabled=true
spring.servlet.multipart.max-file-size=1000MB
spring.servlet.multipart.max-request-size=1000MB
server.servlet.encoding.charset=UTF-8
server.servlet.encoding.enabled=true
server.servlet.encoding.force=true
server.ssl.enabled=false
"@ | Set-Content -LiteralPath (Join-Path $ReleaseDir "config\application-release.properties") -Encoding UTF8
}

if (-not $SkipRuntime) {
    Invoke-Step "Copy Java runtime" {
        Copy-Path $ResolvedJavaHome (Join-Path $ReleaseDir "runtime\java")
    }

    Invoke-Step "Create Python virtual environment" {
        $venvPath = Join-Path $ReleaseDir "runtime\python\venv"
        if ($PythonEnv) {
            Copy-Path (Get-PythonEnvRoot $ResolvedPythonExe) $venvPath
        } else {
            & $ResolvedPythonExe -m venv $venvPath
        }

        $venvPython = Join-Path $venvPath "Scripts\python.exe"
        if (-not (Test-Path -LiteralPath $venvPython)) {
            $venvPython = Join-Path $venvPath "python.exe"
        }

        if (-not $SkipPythonInstall) {
            & $venvPython -c "import flask, scipy, mediapipe, onnxruntime"
            if ($LASTEXITCODE -ne 0) {
                Write-Host "Python runtime is missing required modules; installing project requirements."
                if (-not $PythonEnv) {
                    & $venvPython -m pip install --upgrade pip
                }
                & $venvPython -m pip install -r (Join-Root "facePythonServer\requirements.txt")
                & $venvPython -m pip install flask scipy
                if ($LASTEXITCODE -ne 0) {
                    throw "Failed to install required Python dependencies."
                }
            }
        }
    }
}

Invoke-Step "Copy release scripts and docs" {
    Copy-Path (Assert-Path "deployment\start-all.release.ps1") (Join-Path $ReleaseDir "start-all.ps1")
    Copy-Path (Assert-Path "deployment\stop-all.release.ps1") (Join-Path $ReleaseDir "stop-all.ps1")
    Copy-Path (Assert-Path "deployment\check-env.release.ps1") (Join-Path $ReleaseDir "check-env.ps1")
    Copy-Path (Assert-Path "deployment\README-release.md") (Join-Path $ReleaseDir "README-部署说明.md")
}

Write-Host ""
Write-Host ("Release package created: {0}" -f $ReleaseDir)
Write-Host "Run check-env.ps1 inside the release directory before copying it to the target computer."
