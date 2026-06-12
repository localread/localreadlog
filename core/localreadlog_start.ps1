param(
    [string]$Root = ''
)

$ErrorActionPreference = 'SilentlyContinue'

if (!$Root) {
    $Root = (Resolve-Path (Join-Path (Split-Path -Parent $MyInvocation.MyCommand.Path) '..')).Path
} else {
    $Root = (Resolve-Path $Root).Path
}

$Core = Join-Path $Root 'core'
$Data = Join-Path $Root 'data'
$PortFile = Join-Path $Data 'localreadlog_server_port.txt'
$LauncherPidFile = Join-Path $Data 'localreadlog_launcher.pid'
$StartLog = Join-Path $Data 'localreadlog_start.log'
$BackgroundBat = Join-Path $Core 'localreadlog_background.bat'
$FindPortPs1 = Join-Path $Core 'localreadlog_find_server_port.ps1'

New-Item -ItemType Directory -Force -Path $Data | Out-Null

function Write-StartLog([string]$Message) {
    $line = '[' + (Get-Date -Format 'yyyy-MM-dd HH:mm:ss') + '] ' + $Message
    Add-Content -Path $StartLog -Value $line -Encoding UTF8
}

function Find-RunningPort() {
    if (!(Test-Path $FindPortPs1)) { return '' }
    try {
        $out = & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $FindPortPs1 -Root $Root 2>$null
        if ($out) {
            $first = ($out | Select-Object -First 1).ToString().Trim()
            $num = 0
            if ([int]::TryParse($first, [ref]$num)) { return [string]$num }
        }
    } catch {}
    return ''
}

Write-StartLog ('Start requested. Root=' + $Root)

# If this LocalReadLog copy is already running, open the actual port and do not start another copy.
$port = Find-RunningPort
if ($port) {
    Set-Content -Path $PortFile -Value $port -Encoding ASCII
    Write-StartLog ('Already running on port ' + $port + '. Opening existing server.')
    Start-Process ('http://127.0.0.1:' + $port)
    exit 0
}

# Remove stale runtime markers only when no server for this copy is running.
Remove-Item $PortFile -Force -ErrorAction SilentlyContinue
Remove-Item $LauncherPidFile -Force -ErrorAction SilentlyContinue

if (!(Test-Path $BackgroundBat)) {
    Write-StartLog ('Background script not found: ' + $BackgroundBat)
    exit 1
}

try {
    $proc = Start-Process -FilePath 'cmd.exe' -ArgumentList @('/c', '"' + $BackgroundBat + '"') -WorkingDirectory $Root -WindowStyle Hidden -PassThru
    Set-Content -Path $LauncherPidFile -Value $proc.Id -Encoding ASCII
    Write-StartLog ('Background process started. PID=' + $proc.Id)
} catch {
    Write-StartLog ('Failed to start background process: ' + $_.Exception.Message)
    exit 1
}

# Wait until the server writes the actual selected port. Do not fall back to 8787 blindly.
$port = ''
for ($i = 0; $i -lt 180; $i++) {
    Start-Sleep -Seconds 1

    if (Test-Path $PortFile) {
        try {
            $txt = (Get-Content $PortFile -Raw -ErrorAction SilentlyContinue).Trim()
            $num = 0
            if ([int]::TryParse($txt, [ref]$num)) {
                $port = [string]$num
                break
            }
        } catch {}
    }

    if (($i % 3) -eq 0) {
        $found = Find-RunningPort
        if ($found) {
            $port = $found
            Set-Content -Path $PortFile -Value $port -Encoding ASCII
            break
        }
    }

    # If the background command already ended before any server port appeared, stop waiting.
    if ($proc.HasExited -and !(Test-Path $PortFile)) {
        Write-StartLog 'Background process ended before server port was detected.'
        break
    }
}

if ($port) {
    Write-StartLog ('Opening server on port ' + $port)
    Start-Process ('http://127.0.0.1:' + $port)
} else {
    Write-StartLog 'Server port was not detected. Run 02_Run_With_Window_For_Error_Check.bat to see the error.'
}
