param(
    [string]$Root = "",
    [int]$WaitSeconds = 12,
    [switch]$VerboseLog
)

$ErrorActionPreference = "SilentlyContinue"

function Write-Log($Text) {
    if ($VerboseLog) { Write-Host $Text }
    try {
        if ($script:LogPath) {
            $dir = Split-Path -Parent $script:LogPath
            if (!(Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
            "[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Text | Add-Content -Path $script:LogPath -Encoding UTF8
        }
    } catch {}
}

function Resolve-Root {
    param([string]$Value)
    if ([string]::IsNullOrWhiteSpace($Value)) {
        return (Split-Path -Parent (Split-Path -Parent $PSCommandPath))
    }
    try { return (Resolve-Path $Value).Path } catch { return $Value }
}

function Read-JsonFile {
    param([string]$Path)
    if (!(Test-Path $Path)) { return $null }
    try {
        return Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json
    } catch {
        return $null
    }
}

function Get-ConfigBackupDir {
    param([string]$RootDir)
    $configPath = Join-Path $RootDir "localreadlog_config.json"
    $config = Read-JsonFile $configPath
    if ($null -ne $config -and $config.backup_dir) {
        $p = [Environment]::ExpandEnvironmentVariables([string]$config.backup_dir)
        if (![System.IO.Path]::IsPathRooted($p)) { $p = Join-Path $RootDir $p }
        return $p
    }
    return (Join-Path $RootDir "data")
}

function Get-BrowserEnabledMap {
    param([string]$DataDir)
    $defaults = @{
        whale = $true
        edge = $true
        chrome = $true
        firefox = $true
    }
    $dbPath = Join-Path $DataDir "localreadlog_db.json"
    $db = Read-JsonFile $dbPath
    if ($null -eq $db -or $null -eq $db.settings -or $null -eq $db.settings.browser_enabled) {
        return $defaults
    }
    foreach ($key in @("whale", "edge", "chrome", "firefox")) {
        $value = $db.settings.browser_enabled.$key
        if ($null -ne $value) {
            if ($value -is [string]) {
                $defaults[$key] = !("0", "false", "off", "no", "아니오", "끔" -contains $value.Trim().ToLower())
            } else {
                $defaults[$key] = [bool]$value
            }
        }
    }
    return $defaults
}

function First-ExistingPath {
    param([string[]]$Paths)
    foreach ($p in $Paths) {
        if ([string]::IsNullOrWhiteSpace($p)) { continue }
        $expanded = [Environment]::ExpandEnvironmentVariables($p)
        if (Test-Path $expanded) { return $expanded }
    }
    return $null
}

function Start-And-Close-Browser {
    param(
        [string]$Key,
        [string]$Name,
        [string[]]$ProcessNames,
        [string]$Exe,
        [string]$Arguments,
        [int]$Seconds
    )

    foreach ($procName in $ProcessNames) {
        $running = Get-Process -Name $procName -ErrorAction SilentlyContinue
        if ($running) {
            Write-Log "$Name already running. Skip wakeup."
            return
        }
    }

    if (!(Test-Path $Exe)) {
        Write-Log "$Name exe not found. Skip: $Exe"
        return
    }

    Write-Log "$Name wakeup start: $Exe"

    $before = @{}
    foreach ($procName in $ProcessNames) {
        Get-Process -Name $procName -ErrorAction SilentlyContinue | ForEach-Object { $before[[int]$_.Id] = $true }
    }

    try {
        Start-Process -FilePath $Exe -ArgumentList $Arguments -WindowStyle Minimized | Out-Null
    } catch {
        Write-Log "$Name start failed: $($_.Exception.Message)"
        return
    }

    Start-Sleep -Seconds ([Math]::Max(3, $Seconds))

    $after = @()
    foreach ($procName in $ProcessNames) {
        $after += Get-Process -Name $procName -ErrorAction SilentlyContinue
    }

    foreach ($p in $after) {
        if ($before.ContainsKey([int]$p.Id)) { continue }
        try {
            $p.CloseMainWindow() | Out-Null
            Start-Sleep -Milliseconds 700
            if (!$p.HasExited) { Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue }
        } catch {
            Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue
        }
    }

    Write-Log "$Name wakeup closed."
}

$Root = Resolve-Root $Root
$DataDir = Get-ConfigBackupDir $Root
$script:LogPath = Join-Path $DataDir "localreadlog_browser_wakeup_log.txt"
$enabled = Get-BrowserEnabledMap $DataDir

$local = $env:LOCALAPPDATA
$programFiles = $env:ProgramFiles
$programFilesX86 = ${env:ProgramFiles(x86)}
$appdata = $env:APPDATA

$browsers = @(
    @{
        key = "whale"
        name = "Whale"
        procs = @("whale")
        exe = First-ExistingPath @(
            "$local\Naver\Naver Whale\Application\whale.exe",
            "$programFiles\Naver\Naver Whale\Application\whale.exe",
            "$programFilesX86\Naver\Naver Whale\Application\whale.exe"
        )
        args = "--no-first-run --new-window about:blank"
    },
    @{
        key = "edge"
        name = "Edge"
        procs = @("msedge")
        exe = First-ExistingPath @(
            "$programFilesX86\Microsoft\Edge\Application\msedge.exe",
            "$programFiles\Microsoft\Edge\Application\msedge.exe",
            "$local\Microsoft\Edge\Application\msedge.exe"
        )
        args = "--no-first-run --new-window about:blank"
    },
    @{
        key = "chrome"
        name = "Chrome"
        procs = @("chrome")
        exe = First-ExistingPath @(
            "$programFiles\Google\Chrome\Application\chrome.exe",
            "$programFilesX86\Google\Chrome\Application\chrome.exe",
            "$local\Google\Chrome\Application\chrome.exe"
        )
        args = "--no-first-run --new-window about:blank"
    },
    @{
        key = "firefox"
        name = "Firefox"
        procs = @("firefox")
        exe = First-ExistingPath @(
            "$programFiles\Mozilla Firefox\firefox.exe",
            "$programFilesX86\Mozilla Firefox\firefox.exe",
            "$local\Mozilla Firefox\firefox.exe"
        )
        args = "-new-window about:blank"
    }
)

Write-Log "Wakeup begin. Root=$Root Data=$DataDir WaitSeconds=$WaitSeconds"

foreach ($b in $browsers) {
    if (!$enabled[$b.key]) {
        Write-Log "$($b.name) sync OFF. Skip."
        continue
    }
    if ([string]::IsNullOrWhiteSpace($b.exe)) {
        Write-Log "$($b.name) not installed or path not found. Skip."
        continue
    }
    Start-And-Close-Browser -Key $b.key -Name $b.name -ProcessNames $b.procs -Exe $b.exe -Arguments $b.args -Seconds $WaitSeconds
}

Write-Log "Wakeup done."
