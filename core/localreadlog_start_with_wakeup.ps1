param(
    [string]$Root = ""
)

$ErrorActionPreference = "SilentlyContinue"

if ([string]::IsNullOrWhiteSpace($Root)) {
    $Root = Split-Path -Parent (Split-Path -Parent $PSCommandPath)
}
$Root = (Resolve-Path $Root).Path
$Core = Join-Path $Root "core"
$Wakeup = Join-Path $Core "localreadlog_browser_wakeup_once.ps1"
$Start = Join-Path $Core "localreadlog_start.ps1"

if (Test-Path $Wakeup) {
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File $Wakeup -Root $Root -WaitSeconds 12 | Out-Null
}

if (Test-Path $Start) {
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File $Start -Root $Root
} else {
    Add-Type -AssemblyName PresentationFramework
    [System.Windows.MessageBox]::Show("localreadlog_start.ps1 not found:`n$Start", "LocalReadLog") | Out-Null
}
