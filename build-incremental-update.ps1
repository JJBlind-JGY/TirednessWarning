param(
    [string]$UpdateName = "TirednessWarning-Update-20260607",
    [string]$JavaHome = "D:\project_APP\Java\jdk-17.0.12",
    [string]$PythonExe = "D:\project_APP\Anaconda\anaconda\envs\nanwang\python.exe",
    [switch]$SkipBuild,
    [switch]$SkipWheelDownload
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$UpdateDir = Join-Path $Root $UpdateName
$ZipPath = Join-Path $Root ($UpdateName + ".zip")

function Ensure-Directory {
    param([string]$Path)
    New-Item -ItemType Directory -Force -Path $Path | Out-Null
}

function Assert-Path {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) {
        throw "Required path is missing: $Path"
    }
}

function Archive-ExistingPath {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) {
        return
    }
    $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $archive = $Path + ".archived-" + $stamp
    $index = 1
    while (Test-Path -LiteralPath $archive) {
        $archive = $Path + ".archived-" + $stamp + "-" + $index
        $index += 1
    }
    Move-Item -LiteralPath $Path -Destination $archive
    Write-Host ("Archived existing output to {0}" -f $archive)
}

function Copy-UpdatePath {
    param([string]$SourceRelative, [string]$DestinationRelative)
    $source = Join-Path $Root $SourceRelative
    $destination = Join-Path $UpdateDir $DestinationRelative
    Assert-Path $source
    Ensure-Directory (Split-Path -Parent $destination)
    Copy-Item -LiteralPath $source -Destination $destination -Recurse -Force
}

if (-not $SkipBuild) {
    Assert-Path (Join-Path $JavaHome "bin\java.exe")
    $env:JAVA_HOME = $JavaHome
    $env:Path = (Join-Path $JavaHome "bin") + ";" + $env:Path

    Push-Location (Join-Path $Root "faceJavaServer")
    try {
        & mvn.cmd -pl face-service -am clean package -DskipTests
        if ($LASTEXITCODE -ne 0) { throw "Java build failed." }
    } finally {
        Pop-Location
    }

    Push-Location (Join-Path $Root "frontPage\vue-tlias-management")
    try {
        & npm.cmd run test:behavior
        if ($LASTEXITCODE -ne 0) { throw "Behavior regression tests failed." }
        & npm.cmd run build
        if ($LASTEXITCODE -ne 0) { throw "Frontend build failed." }
    } finally {
        Pop-Location
    }
}

Archive-ExistingPath $UpdateDir
Archive-ExistingPath $ZipPath

Ensure-Directory $UpdateDir
Copy-UpdatePath "faceJavaServer\face-service\target\face-service-0.0.1-SNAPSHOT-exec.jar" "apps\face-service\face-service.jar"
Copy-UpdatePath "facePythonServer\websocket_server.py" "apps\face-python\websocket_server.py"
Copy-UpdatePath "facePythonServer\models\yawn_model_80_lite.onnx" "apps\face-python\models\yawn_model_80_lite.onnx"
Copy-UpdatePath "frontPage\vue-tlias-management\dist" "apps\front\dist"
Copy-UpdatePath "deployment\check-env.release.ps1" "check-env.ps1"
Copy-UpdatePath "deployment\stop-all.release.ps1" "stop-all.ps1"
Copy-UpdatePath "deployment\update-incremental.release.ps1" "update.ps1"
Copy-UpdatePath "deployment\merge-python-config.py" "tools\merge-python-config.py"
Copy-UpdatePath "deployment\README-incremental-update.md" "README.md"

$wheelDir = Join-Path $UpdateDir "wheels"
Ensure-Directory $wheelDir
if (-not $SkipWheelDownload) {
    Assert-Path $PythonExe
    & $PythonExe -m pip download `
        --dest $wheelDir `
        --only-binary=:all: `
        --platform win_amd64 `
        --python-version 310 `
        --implementation cp `
        --abi cp310 `
        "onnxruntime==1.22.0"
    if ($LASTEXITCODE -ne 0) {
        throw "Could not download offline Python wheels."
    }
}

$manifestPath = Join-Path $UpdateDir "SHA256SUMS.txt"
Get-ChildItem -LiteralPath $UpdateDir -Recurse -File |
    Where-Object { $_.FullName -ne $manifestPath } |
    Sort-Object FullName |
    ForEach-Object {
        $relative = $_.FullName.Substring($UpdateDir.Length + 1).Replace("\", "/")
        $hash = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        "{0}  {1}" -f $hash, $relative
    } | Set-Content -LiteralPath $manifestPath -Encoding ASCII

Compress-Archive -LiteralPath $UpdateDir -DestinationPath $ZipPath -CompressionLevel Optimal
Write-Host ("Incremental update directory: {0}" -f $UpdateDir)
Write-Host ("Incremental update ZIP: {0}" -f $ZipPath)
