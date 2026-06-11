param(
    [string]$Root = ''
)

$ErrorActionPreference = 'SilentlyContinue'
$Ports = @(8787, 8877, 18787, 28787)
$RootRx = ''
if ($Root) {
    try { $RootRx = [regex]::Escape((Resolve-Path $Root).Path.TrimEnd('\')) } catch { $RootRx = [regex]::Escape($Root.TrimEnd('\')) }
}

foreach ($conn in (Get-NetTCPConnection -LocalPort $Ports -State Listen -ErrorAction SilentlyContinue | Sort-Object LocalPort)) {
    $procId = [int]$conn.OwningProcess
    if ($procId -le 0) { continue }
    $proc = Get-CimInstance Win32_Process -Filter "ProcessId=$procId" -ErrorAction SilentlyContinue
    if (!$proc) { continue }
    $cmd = [string]$proc.CommandLine
    $exe = [string]$proc.ExecutablePath

    $isLocalReadLog = ($cmd -match '(?i)localreadlog_server\.py' -or $cmd -match '(?i)localreadlog')
    if ($RootRx) {
        $isLocalReadLog = $isLocalReadLog -and ($cmd -match $RootRx -or $exe -match $RootRx)
    }

    if ($isLocalReadLog) {
        Write-Output $conn.LocalPort
        exit 0
    }
}

exit 1
