param(
    [switch]$WhatIfMode
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$Root = (Split-Path -Parent $MyInvocation.MyCommand.Path).ToLowerInvariant()
$normalizedRoot = $Root -replace "/", "\"
$servicePorts = @(1984, 8765, 8766, 8081, 5000, 5173)
$targetMap = @{}
$PidDir = Join-Path (Split-Path -Parent $MyInvocation.MyCommand.Path) "run"

if (Test-Path -LiteralPath $PidDir) {
    Get-ChildItem -LiteralPath $PidDir -Filter "*.pid" -ErrorAction SilentlyContinue | ForEach-Object {
        try {
            $processId = [int](Get-Content -LiteralPath $_.FullName -Raw)
            if ($processId -ne $PID -and -not $targetMap.ContainsKey($processId)) {
                $process = Get-Process -Id $processId -ErrorAction SilentlyContinue
                if ($process) {
                    $targetMap[$processId] = [pscustomobject]@{
                        ProcessId = $processId
                        CommandLine = ("pid file {0}" -f $_.Name)
                    }
                }
            }
        } catch {
            Write-Host ("[WARN] Could not read pid file {0}: {1}" -f $_.FullName, $_.Exception.Message)
        }
    }
}

function Normalize-CommandLine {
    param([string]$CommandLine)
    if ($null -eq $CommandLine) {
        return ""
    }
    return ($CommandLine.ToLowerInvariant() -replace "/", "\")
}

function Is-ReleaseProcess {
    param($ProcessInfo)

    if ($ProcessInfo.ProcessId -eq $PID) {
        return $false
    }

    $cmd = Normalize-CommandLine $ProcessInfo.CommandLine
    if ($cmd -notlike "*$normalizedRoot*") {
        return $false
    }

    return (
        $cmd -like "*apps\go2rtc\go2rtc.exe*" -or
        $cmd -like "*apps\face-python\websocket_server.py*" -or
        $cmd -like "*apps\face-service\face-service.jar*" -or
        $cmd -like "*apps\eeg-python\eeg_0417.py*" -or
        $cmd -like "*apps\front\static-server\static-server.ps1*"
    )
}

try {
    $commandLineTargets = Get-CimInstance Win32_Process | Where-Object { Is-ReleaseProcess $_ }
    foreach ($target in $commandLineTargets) {
        $targetMap[[int]$target.ProcessId] = $target
    }
} catch {
    Write-Host ("[WARN] Could not inspect process command lines: {0}" -f $_.Exception.Message)
}

try {
    $portTargets = Get-NetTCPConnection -State Listen -ErrorAction Stop |
        Where-Object { $servicePorts -contains $_.LocalPort -and $_.OwningProcess -ne $PID }
    foreach ($connection in $portTargets) {
        $processId = [int]$connection.OwningProcess
        if (-not $targetMap.ContainsKey($processId)) {
            $process = Get-Process -Id $processId -ErrorAction SilentlyContinue
            if ($process) {
                $targetMap[$processId] = [pscustomobject]@{
                    ProcessId = $processId
                    CommandLine = ("{0} listening on port {1}" -f $process.ProcessName, $connection.LocalPort)
                }
            }
        }
    }
} catch {
    Write-Host ("[WARN] Could not inspect listening ports: {0}" -f $_.Exception.Message)
    try {
        $netstatLines = netstat -ano -p tcp
        foreach ($line in $netstatLines) {
            $trimmed = $line.Trim()
            if ($trimmed -notmatch "^TCP\s+\S+:(\d+)\s+\S+\s+LISTENING\s+(\d+)$") {
                continue
            }
            $port = [int]$Matches[1]
            $processId = [int]$Matches[2]
            if (($servicePorts -notcontains $port) -or $processId -eq $PID -or $targetMap.ContainsKey($processId)) {
                continue
            }
            $process = Get-Process -Id $processId -ErrorAction SilentlyContinue
            if ($process) {
                $targetMap[$processId] = [pscustomobject]@{
                    ProcessId = $processId
                    CommandLine = ("{0} listening on port {1}" -f $process.ProcessName, $port)
                }
            }
        }
    } catch {
        Write-Host ("[WARN] Could not inspect ports with netstat: {0}" -f $_.Exception.Message)
    }
}

$targets = @($targetMap.Values)
if (-not $targets) {
    Write-Host "No matching release service processes were found."
    return
}

Write-Host "Matched release service processes:"
$targets | ForEach-Object {
    Write-Host ("  PID {0}: {1}" -f $_.ProcessId, $_.CommandLine)
}

if ($WhatIfMode) {
    Write-Host "WhatIfMode enabled. No processes were stopped."
    return
}

foreach ($target in $targets) {
    try {
        Stop-Process -Id $target.ProcessId -Force
        Write-Host ("Stopped PID {0}" -f $target.ProcessId)
    } catch {
        Write-Host ("[WARN] Failed to stop PID {0}: {1}" -f $target.ProcessId, $_.Exception.Message)
    }
}

if (Test-Path -LiteralPath $PidDir) {
    Get-ChildItem -LiteralPath $PidDir -Filter "*.pid" -ErrorAction SilentlyContinue | ForEach-Object {
        try {
            Set-Content -LiteralPath $_.FullName -Value "" -Encoding ASCII
        } catch {
            Write-Host ("[WARN] Could not clear pid file {0}: {1}" -f $_.FullName, $_.Exception.Message)
        }
    }
}
