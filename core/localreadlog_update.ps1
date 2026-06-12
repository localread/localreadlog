param(
    [string]$Root = "",
    [switch]$Force,
    [switch]$Silent
)

$ErrorActionPreference = "SilentlyContinue"

if ([string]::IsNullOrWhiteSpace($Root)) {
    $Root = Split-Path -Parent (Split-Path -Parent $PSCommandPath)
}
try {
    $Root = (Resolve-Path $Root).Path
} catch {
    exit 0
}

$Core = Join-Path $Root "core"
$Data = Join-Path $Root "data"
$ConfigJson = Join-Path $Root "localreadlog_config.json"
$VersionFile = Join-Path $Root "VERSION"
$FindPortPs1 = Join-Path $Core "localreadlog_find_server_port.ps1"
$UpdateDir = Join-Path $Data "updates"
$BackupDir = Join-Path $Data "program_backups"
$LogFile = Join-Path $Data "localreadlog_update.log"

New-Item -ItemType Directory -Force -Path $Data | Out-Null
New-Item -ItemType Directory -Force -Path $UpdateDir | Out-Null
New-Item -ItemType Directory -Force -Path $BackupDir | Out-Null

function Write-UpdateLog([string]$Message) {
    $line = '[' + (Get-Date -Format 'yyyy-MM-dd HH:mm:ss') + '] ' + $Message
    Add-Content -Path $LogFile -Value $line -Encoding UTF8
    if (!$Silent) { Write-Host $line }
}

function Read-Config() {
    if (!(Test-Path $ConfigJson)) { return @{} }
    try {
        $raw = Get-Content -Path $ConfigJson -Raw -Encoding UTF8
        if ([string]::IsNullOrWhiteSpace($raw)) { return @{} }
        return $raw | ConvertFrom-Json
    } catch {
        Write-UpdateLog ("설정 파일 읽기 실패. 업데이트 건너뜀: " + $_.Exception.Message)
        return @{}
    }
}

function Get-ConfigValue($Config, [string[]]$Names, $DefaultValue) {
    foreach ($name in $Names) {
        try {
            $value = $Config.$name
            if ($null -ne $value -and ![string]::IsNullOrWhiteSpace([string]$value)) { return $value }
        } catch {}
    }
    return $DefaultValue
}

function To-Bool($Value, [bool]$DefaultValue) {
    if ($null -eq $Value) { return $DefaultValue }
    $s = ([string]$Value).Trim().ToLowerInvariant()
    if ($s -in @('1','true','yes','y','on','enable','enabled','사용','켜기','예')) { return $true }
    if ($s -in @('0','false','no','n','off','disable','disabled','미사용','끄기','아니오')) { return $false }
    return $DefaultValue
}

function Get-CurrentVersion() {
    if (Test-Path $VersionFile) {
        try {
            $v = (Get-Content -Path $VersionFile -Raw -Encoding UTF8).Trim()
            if ($v) { return $v }
        } catch {}
    }
    $readme = Join-Path $Root "README.md"
    if (Test-Path $readme) {
        try {
            $text = Get-Content -Path $readme -Raw -Encoding UTF8
            $m = [regex]::Match($text, 'v\d+\.\d+\.\d+')
            if ($m.Success) { return $m.Value }
        } catch {}
    }
    return "v0.0.0"
}

function Convert-ToVersion([string]$Text) {
    $clean = ([string]$Text).Trim() -replace '^v',''
    try { return [version]$clean } catch { return [version]'0.0.0' }
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

function Find-PackageRoot([string]$ExtractDir) {
    $candidates = @()
    $candidates += Get-Item -LiteralPath $ExtractDir
    try { $candidates += Get-ChildItem -LiteralPath $ExtractDir -Directory -Recurse } catch {}

    foreach ($dir in $candidates) {
        $coreServer = Join-Path $dir.FullName "core\localreadlog_server.py"
        $version = Join-Path $dir.FullName "VERSION"
        if ((Test-Path $coreServer) -or (Test-Path $version)) { return $dir.FullName }
    }
    return $ExtractDir
}

function Backup-CurrentProgram([string]$CurrentVersion, [string]$NewVersion) {
    $stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
    $safeCurrent = ([string]$CurrentVersion) -replace '[^0-9A-Za-z._-]', '_'
    $safeNew = ([string]$NewVersion) -replace '[^0-9A-Za-z._-]', '_'
    $dest = Join-Path $BackupDir ("before_{0}_to_{1}_{2}" -f $safeCurrent, $safeNew, $stamp)
    New-Item -ItemType Directory -Force -Path $dest | Out-Null

    foreach ($name in @('core','README.md','CHANGELOG.md','VERSION','01_Start_Background.vbs','02_Run_With_Window_For_Error_Check.bat','03_Enable_Start_With_Windows.bat','04_Disable_Start_With_Windows.bat','05_Stop_Server.bat','06_Allow_Mobile_Access_Windows_Firewall.bat','07_Remove_Mobile_Access_Windows_Firewall.bat','localreadlog_config.json')) {
        $src = Join-Path $Root $name
        if (Test-Path $src) {
            try { Copy-Item -LiteralPath $src -Destination $dest -Recurse -Force } catch {}
        }
    }

    $dataSnapshot = Join-Path $dest "data_snapshot"
    New-Item -ItemType Directory -Force -Path $dataSnapshot | Out-Null
    foreach ($name in @('localreadlog_db.json','localreadlog_ignore.txt','localreadlog_purged.txt','localreadlog_latest.csv','localreadlog_latest_mobile.html','localreadlog_latest_pc.html')) {
        $src = Join-Path $Data $name
        if (Test-Path $src) {
            try { Copy-Item -LiteralPath $src -Destination $dataSnapshot -Force } catch {}
        }
    }
    return $dest
}

function Apply-Package([string]$PackageRoot, [string]$NewVersion) {
    $skipTop = @('data','.git','.github','localreadlog_config.json')
    foreach ($item in Get-ChildItem -LiteralPath $PackageRoot -Force) {
        if ($skipTop -contains $item.Name) { continue }
        $dst = Join-Path $Root $item.Name
        try {
            Copy-Item -LiteralPath $item.FullName -Destination $dst -Recurse -Force
        } catch {
            throw ("파일 교체 실패: " + $item.FullName + " -> " + $dst + " / " + $_.Exception.Message)
        }
    }
    Set-Content -Path $VersionFile -Value $NewVersion -Encoding UTF8
}

try {
    $config = Read-Config
    $repo = [string](Get-ConfigValue $config @('github_repo','program_update_repo','update_repo') '')
    $repo = $repo.Trim().Trim('/')
    $enabled = To-Bool (Get-ConfigValue $config @('program_auto_update_enabled','software_auto_update_enabled','github_auto_update_enabled') $true) $true
    $assetPattern = [string](Get-ConfigValue $config @('github_asset_pattern','program_update_asset_pattern') 'LocalReadLog*.zip')

    if (!$enabled -and !$Force) {
        Write-UpdateLog "프로그램 자동 업데이트 OFF. 건너뜀."
        exit 0
    }

    if ([string]::IsNullOrWhiteSpace($repo)) {
        Write-UpdateLog "github_repo가 설정되지 않음. 프로그램 업데이트 건너뜀. 예: localreadlog_config.json에 \"github_repo\": \"사용자명/저장소명\" 추가"
        exit 0
    }

    if (!$Force) {
        $runningPort = Find-RunningPort
        if ($runningPort) {
            Write-UpdateLog ("서버가 이미 실행 중이라 업데이트 건너뜀. port=" + $runningPort)
            exit 0
        }
    }

    $currentVersionText = Get-CurrentVersion
    $currentVersion = Convert-ToVersion $currentVersionText
    $api = "https://api.github.com/repos/$repo/releases/latest"

    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    $headers = @{ 'User-Agent' = 'LocalReadLog-Updater'; 'Accept' = 'application/vnd.github+json' }
    Write-UpdateLog ("최신 릴리즈 확인: " + $repo + " / 현재 " + $currentVersionText)
    $release = Invoke-RestMethod -Uri $api -Headers $headers -TimeoutSec 15

    $latestTag = [string]$release.tag_name
    if ([string]::IsNullOrWhiteSpace($latestTag)) {
        Write-UpdateLog "최신 릴리즈 tag_name을 읽지 못함."
        exit 0
    }

    $latestVersion = Convert-ToVersion $latestTag
    if (!$Force -and $latestVersion -le $currentVersion) {
        Write-UpdateLog ("이미 최신 버전임: " + $currentVersionText)
        exit 0
    }

    $asset = $null
    try {
        $asset = $release.assets | Where-Object { $_.name -like $assetPattern } | Select-Object -First 1
        if (!$asset) { $asset = $release.assets | Where-Object { $_.name -like '*.zip' } | Select-Object -First 1 }
    } catch {}

    $downloadUrl = ''
    $assetName = ''
    if ($asset) {
        $downloadUrl = [string]$asset.browser_download_url
        $assetName = [string]$asset.name
    } else {
        $downloadUrl = [string]$release.zipball_url
        $assetName = "source.zip"
    }

    if ([string]::IsNullOrWhiteSpace($downloadUrl)) {
        Write-UpdateLog "다운로드할 ZIP을 찾지 못함. GitHub Release에 LocalReadLog ZIP을 올려야 함."
        exit 0
    }

    $stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
    $zipPath = Join-Path $UpdateDir ("LocalReadLog_update_{0}_{1}.zip" -f (($latestTag -replace '[^0-9A-Za-z._-]','_')), $stamp)
    $extractDir = Join-Path $UpdateDir ("extract_{0}_{1}" -f (($latestTag -replace '[^0-9A-Za-z._-]','_')), $stamp)

    Write-UpdateLog ("다운로드: " + $assetName)
    Invoke-WebRequest -Uri $downloadUrl -OutFile $zipPath -Headers @{ 'User-Agent' = 'LocalReadLog-Updater' } -TimeoutSec 90

    if (Test-Path $extractDir) { Remove-Item -LiteralPath $extractDir -Recurse -Force }
    New-Item -ItemType Directory -Force -Path $extractDir | Out-Null
    Expand-Archive -LiteralPath $zipPath -DestinationPath $extractDir -Force

    $packageRoot = Find-PackageRoot $extractDir
    $serverInPackage = Join-Path $packageRoot "core\localreadlog_server.py"
    if (!(Test-Path $serverInPackage)) {
        Write-UpdateLog "ZIP 안에서 core\localreadlog_server.py를 찾지 못함. 업데이트 중단."
        exit 0
    }

    $backupPath = Backup-CurrentProgram $currentVersionText $latestTag
    Write-UpdateLog ("기존 파일 백업 완료: " + $backupPath)

    Apply-Package $packageRoot $latestTag
    Write-UpdateLog ("프로그램 업데이트 완료: " + $currentVersionText + " -> " + $latestTag)
    exit 0
} catch {
    Write-UpdateLog ("프로그램 업데이트 실패: " + $_.Exception.Message)
    exit 0
}
