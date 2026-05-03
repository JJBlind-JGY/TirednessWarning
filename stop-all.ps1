param(
    [switch]$WhatIfMode
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$Root = (Split-Path -Parent $MyInvocation.MyCommand.Path).ToLowerInvariant()
$normalizedRoot = $Root -replace "/", "\"

function Normalize-CommandLine {
    param([string]$CommandLine)
    if ($null -eq $CommandLine) {
        return ""
    }
    return ($CommandLine.ToLowerInvariant() -replace "/", "\")
}

function Is-ProjectServiceProcess {
    param($ProcessInfo)

    $name = ""
    if ($null -ne $ProcessInfo.Name) {
        $name = $ProcessInfo.Name.ToLowerInvariant()
    }
    $cmd = Normalize-CommandLine $ProcessInfo.CommandLine

    if ($ProcessInfo.ProcessId -eq $PID) {
        return $false
    }

    if ($cmd -notlike "*$normalizedRoot*") {
        return $false
    }

    if ($name -eq "go2rtc.exe" -and $cmd -like "*facejavaserver\go2rtc*") {
        return $true
    }
    if ($cmd -like "*facepythonserver\websocket_server.py*") {
        return $true
    }
    if ($cmd -like "*frontpage\vue-tlias-management\src\py\eeg_0417.py*") {
        return $true
    }
    if ($cmd -like "*spring-boot:run*" -and $cmd -like "*face-service*") {
        return $true
    }
    if ($cmd -like "*vue-tlias-management*" -and ($cmd -like "*vite*" -or $cmd -like "*npm.cmd run dev*" -or $cmd -like "*npm run dev*")) {
        return $true
    }
    if ($name -eq "powershell.exe" -and (
            $cmd -like "*go2rtc.exe -config*" -or
            $cmd -like "*websocket_server.py*" -or
            $cmd -like "*spring-boot:run*" -or
            $cmd -like "*eeg_0417.py*" -or
            $cmd -like "*npm.cmd run dev*"
        )) {
        return $true
    }

    return $false
}

$targetMap = @{}

try {
    $commandLineTargets = Get-CimInstance Win32_Process | Where-Object { Is-ProjectServiceProcess $_ }
    foreach ($target in $commandLineTargets) {
        $targetMap[[int]$target.ProcessId] = $target
    }
} catch {
    Write-Host ("[WARN] Could not inspect process command lines: {0}" -f $_.Exception.Message)
}

$servicePorts = @(1984, 8765, 8081, 5000, 5173)
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
    Write-Host "No matching TirednessWarning service processes were found."
    return
}

Write-Host "Matched service processes:"
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
