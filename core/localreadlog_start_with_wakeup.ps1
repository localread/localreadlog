param(
    [string]$Root = ""
)

$ErrorActionPreference = "SilentlyContinue"

if ([string]::IsNullOrWhiteSpace($Root)) {
    $Root = Split-Path -Parent (Split-Path -Parent $PSCommandPath)
}
$Root = (Resolve-Path $Root).Path
$Core = Join-Path $Root "core"
$Updater = Join-Path $Core "localreadlog_update.ps1"
$Wakeup = Join-Path $Core "localreadlog_browser_wakeup_once.ps1"
$Start = Join-Path $Core "localreadlog_start.ps1"

# v0.1.29:
# 01_Start_Background.vbs가 시작 안내 HTML을 먼저 열고,
# 이 스크립트는 업데이트 확인/브라우저 깨우기/서버 실행만 담당한다.
if (Test-Path $Updater) {
    powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File $Updater -Root $Root -Silent | Out-Null
}

if (Test-Path $Wakeup) {
    powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File $Wakeup -Root $Root -WaitSeconds 12 | Out-Null
}

if (Test-Path $Start) {
    powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File $Start -Root $Root
} else {
    Add-Type -AssemblyName PresentationFramework
    [System.Windows.MessageBox]::Show("localreadlog_start.ps1 not found:`n$Start", "LocalReadLog") | Out-Null
}
