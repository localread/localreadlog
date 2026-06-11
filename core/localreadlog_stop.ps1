$ErrorActionPreference = 'SilentlyContinue'

$CoreDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = (Resolve-Path (Join-Path $CoreDir '..')).Path.TrimEnd('\')
$Data = Join-Path $Root 'data'
$Ports = @(8787, 8877, 18787, 28787)
$CurrentPid = $PID
$Ids = New-Object System.Collections.Generic.HashSet[int]

function Add-TargetPid([int]$TargetPid, [string]$Reason) {
    if ($TargetPid -le 0) { return }
    if ($TargetPid -eq $CurrentPid) { return }
    $p = Get-Process -Id $TargetPid -ErrorAction SilentlyContinue
    if (!$p) { return }
    if ($p.ProcessName -match '^(?i)powershell|pwsh$') {
        $proc = Get-CimInstance Win32_Process -Filter "ProcessId=$TargetPid" -ErrorAction SilentlyContinue
        if ($proc -and ([string]$proc.CommandLine) -match 'localreadlog_stop\.ps1|05_Stop_Server\.bat') { return }
    }
    [void]$Ids.Add($TargetPid)
}

function Add-PidFromFile([string]$FileName) {
    $file = Join-Path $Data $FileName
    if (!(Test-Path $file)) { return }
    $txt = (Get-Content $file -ErrorAction SilentlyContinue | Select-Object -First 1)
    $num = 0
    if ([int]::TryParse($txt, [ref]$num)) {
        Add-TargetPid $num "pid-file:$FileName"
    }
}

Write-Host 'Stopping LocalReadLog...'
Write-Host ('Root: ' + $Root)
Write-Host ''

# 1) PIDs written by launcher/server/backup.
Add-PidFromFile 'localreadlog_launcher.pid'
Add-PidFromFile 'localreadlog_server.pid'
Add-PidFromFile 'localreadlog_backup.pid'

# 2) Any process listening on known LocalReadLog ports.
foreach ($conn in (Get-NetTCPConnection -LocalPort $Ports -State Listen -ErrorAction SilentlyContinue)) {
    if ($conn.OwningProcess) { Add-TargetPid ([int]$conn.OwningProcess) ('port:' + $conn.LocalPort) }
}

# 3) Fallback for environments where Get-NetTCPConnection is blocked/unavailable.
foreach ($port in $Ports) {
    $lines = cmd /c "netstat -ano -p tcp | findstr LISTENING | findstr :$port"
    foreach ($line in $lines) {
        $parts = ($line -split '\s+') | Where-Object { $_ }
        if ($parts.Count -ge 5) {
            $num = 0
            if ([int]::TryParse($parts[-1], [ref]$num)) { Add-TargetPid $num ('netstat:' + $port) }
        }
    }
}

# 4) Task-Manager style sweep: kill python/cmd/wscript processes that clearly belong to LocalReadLog.
$All = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue)
$RootRx = [regex]::Escape($Root)
foreach ($proc in $All) {
    $pidNum = [int]$proc.ProcessId
    if ($pidNum -eq $CurrentPid) { continue }

    $name = [string]$proc.Name
    $cmd = [string]$proc.CommandLine
    $exe = [string]$proc.ExecutablePath
    if (!$cmd -and !$exe) { continue }

    # Do not kill this stop command.
    if ($cmd -match '(?i)localreadlog_stop\.ps1|05_Stop_Server\.bat') { continue }

    $belongsToThisCopy = ($cmd -match $RootRx -or $exe -match $RootRx)
    $belongsToAnyLocalReadLog = ($cmd -match '(?i)localreadlog' -or $exe -match '(?i)localreadlog')
    $isRelevantHost = ($name -match '(?i)^(python|pythonw|py|cmd|wscript|cscript|conhost)\.exe$')

    if (($belongsToThisCopy -or $belongsToAnyLocalReadLog) -and $isRelevantHost) {
        Add-TargetPid $pidNum 'process-scan'
    }
}

# 5) Include child processes recursively.
$changed = $true
while ($changed) {
    $changed = $false
    foreach ($proc in $All) {
        $pidNum = [int]$proc.ProcessId
        $parent = [int]$proc.ParentProcessId
        if ($pidNum -eq $CurrentPid) { continue }
        if ($Ids.Contains($parent) -and !$Ids.Contains($pidNum)) {
            [void]$Ids.Add($pidNum)
            $changed = $true
        }
    }
}

if ($Ids.Count -eq 0) {
    Write-Host 'No LocalReadLog process found.'
} else {
    Write-Host ('Found process count: ' + $Ids.Count)
}

# Try graceful Stop-Process first, then taskkill tree-force.
foreach ($target in ($Ids | Sort-Object -Descending)) {
    if ($target -eq $CurrentPid) { continue }
    $p = Get-Process -Id $target -ErrorAction SilentlyContinue
    if ($p) {
        Write-Host ('Stopping PID ' + $target + ' (' + $p.ProcessName + ')')
        Stop-Process -Id $target -Force -ErrorAction SilentlyContinue
    }
}
Start-Sleep -Milliseconds 500
foreach ($target in ($Ids | Sort-Object -Descending)) {
    if ($target -eq $CurrentPid) { continue }
    if (Get-Process -Id $target -ErrorAction SilentlyContinue) {
        Write-Host ('Force killing PID tree ' + $target)
        cmd /c "taskkill /PID $target /T /F" | Out-Host
    }
}

Start-Sleep -Milliseconds 900

# One last pass: if ports still have listeners, kill them even if PID scan missed them.
foreach ($conn in (Get-NetTCPConnection -LocalPort $Ports -State Listen -ErrorAction SilentlyContinue)) {
    if ($conn.OwningProcess -and $conn.OwningProcess -ne $CurrentPid) {
        Write-Host ('Final port kill PID ' + $conn.OwningProcess + ' on port ' + $conn.LocalPort)
        cmd /c "taskkill /PID $($conn.OwningProcess) /T /F" | Out-Host
    }
}

# Clean runtime marker files.
Remove-Item (Join-Path $Data 'localreadlog_launcher.pid') -Force -ErrorAction SilentlyContinue
Remove-Item (Join-Path $Data 'localreadlog_server.pid') -Force -ErrorAction SilentlyContinue
Remove-Item (Join-Path $Data 'localreadlog_server_port.txt') -Force -ErrorAction SilentlyContinue
Remove-Item (Join-Path $Data 'localreadlog_backup.pid') -Force -ErrorAction SilentlyContinue

Write-Host ''
Write-Host 'Remaining LocalReadLog listeners:'
$remain = Get-NetTCPConnection -LocalPort $Ports -State Listen -ErrorAction SilentlyContinue
if ($remain) {
    $remain | Select-Object LocalPort, OwningProcess | Format-Table -AutoSize
    Write-Host ''
    Write-Host 'If anything remains, open Task Manager and end python.exe/pythonw.exe from this folder:'
    Write-Host $Root
} else {
    Write-Host 'None'
}

Write-Host ''
Write-Host 'Done.'
