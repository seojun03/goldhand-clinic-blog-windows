[CmdletBinding()]
param(
    [string]$CodexPath = $env:GOLDHANDBLOG_CODEX_PATH,
    [string]$EditableRoot = $(if ($env:GOLDHANDBLOG_EDITABLE_ROOT) { $env:GOLDHANDBLOG_EDITABLE_ROOT } else { Join-Path $HOME "GoldhandBlog" })
)

# Keep this file ASCII-only so Windows PowerShell 5.1 can run it reliably.
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$Repository = "seojun03/goldhand-clinic-blog-windows"
$ReleaseAssetName = "goldhand-clinic-blog-plugin.zip"
$StatePath = Join-Path $EditableRoot ".goldhand-clinic-blog-managed-release"
$mutex = New-Object Threading.Mutex($false, "Local\GoldhandBlogUpdate")
$hasLock = $false

function Write-Update([string]$Message) { Write-Host "[Goldhand Clinic Blog updater] $Message" -ForegroundColor Cyan }

function Remove-TempDirectoryBestEffort([string]$LiteralPath) {
    if ([string]::IsNullOrWhiteSpace($LiteralPath)) { return }
    foreach ($delayMs in @(0, 100, 250, 500)) {
        try {
            if ($delayMs -gt 0) { Start-Sleep -Milliseconds $delayMs }
            if (-not (Test-Path -LiteralPath $LiteralPath)) { return }
            Remove-Item -LiteralPath $LiteralPath -Recurse -Force -ErrorAction Stop
            if (-not (Test-Path -LiteralPath $LiteralPath)) { return }
        } catch {
        }
    }
    Write-Warning "Temporary update files could not be removed: $LiteralPath"
}

function Get-LocalArchiveRelease([string]$ArchivePath) {
    $resolved = (Resolve-Path -LiteralPath $ArchivePath).Path
    $hash = (Get-FileHash -LiteralPath $resolved -Algorithm SHA256).Hash.ToLowerInvariant()
    $tag = if ($env:GOLDHANDBLOG_RELEASE_TAG) { [string]$env:GOLDHANDBLOG_RELEASE_TAG } else { "local-$hash" }
    return [PSCustomObject]@{ Tag = $tag; Archive = $resolved; DownloadUrl = $null }
}

function Get-LatestRelease {
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    $headers = @{ "User-Agent" = "GoldhandBlogUpdater"; "Accept" = "application/vnd.github+json" }
    $release = Invoke-RestMethod -UseBasicParsing -Headers $headers -Uri "https://api.github.com/repos/$Repository/releases/latest"
    $asset = @($release.assets | Where-Object { $_.name -eq $ReleaseAssetName }) | Select-Object -First 1
    if (-not $asset) { throw "The latest validated release does not contain $ReleaseAssetName." }
    return [PSCustomObject]@{ Tag = [string]$release.tag_name; Archive = $null; DownloadUrl = [string]$asset.browser_download_url }
}

try {
    $hasLock = $mutex.WaitOne(0)
    if (-not $hasLock) { Write-Update "Another update is already running."; return }
    $release = if ($env:GOLDHANDBLOG_UPDATE_ARCHIVE) { Get-LocalArchiveRelease -ArchivePath $env:GOLDHANDBLOG_UPDATE_ARCHIVE } else { Get-LatestRelease }
    $current = if (Test-Path -LiteralPath $StatePath -PathType Leaf) { (Get-Content -LiteralPath $StatePath -Raw -Encoding UTF8).Trim() } else { "" }
    if ($env:GOLDHANDBLOG_FORCE_UPDATE -ne "1" -and $current -eq $release.Tag) { Write-Update "Already current: $current"; return }

    $tempBase = [Environment]::GetFolderPath("UserProfile")
    if ([string]::IsNullOrWhiteSpace($tempBase)) { $tempBase = [IO.Path]::GetTempPath() }
    $tempRoot = Join-Path $tempBase (".ghbu-" + [Guid]::NewGuid().ToString("N").Substring(0, 8))
    try {
        New-Item -ItemType Directory -Path $tempRoot -Force | Out-Null
        $archive = Join-Path $tempRoot "release.zip"
        if ($release.Archive) { Copy-Item -LiteralPath $release.Archive -Destination $archive -Force } else { Invoke-WebRequest -UseBasicParsing -Uri $release.DownloadUrl -OutFile $archive }
        $expanded = Join-Path $tempRoot "x"
        Expand-Archive -LiteralPath $archive -DestinationPath $expanded
        $installer = Get-ChildItem -LiteralPath $expanded -Filter "install-from-download-windows.ps1" -File -Recurse | Select-Object -First 1
        if (-not $installer) { throw "The validated release ZIP is missing install-from-download-windows.ps1." }
        $previousTag = $env:GOLDHANDBLOG_RELEASE_TAG
        $previousSkip = $env:GOLDHANDBLOG_SKIP_AUTO_UPDATE_REGISTRATION
        try {
            $env:GOLDHANDBLOG_RELEASE_TAG = $release.Tag
            & $installer.FullName -CodexPath $CodexPath -EditableRoot $EditableRoot
        } finally {
            if ($null -eq $previousTag) { Remove-Item Env:GOLDHANDBLOG_RELEASE_TAG -ErrorAction SilentlyContinue } else { $env:GOLDHANDBLOG_RELEASE_TAG = $previousTag }
            if ($null -eq $previousSkip) { Remove-Item Env:GOLDHANDBLOG_SKIP_AUTO_UPDATE_REGISTRATION -ErrorAction SilentlyContinue } else { $env:GOLDHANDBLOG_SKIP_AUTO_UPDATE_REGISTRATION = $previousSkip }
        }
        $installedTag = if (Test-Path -LiteralPath $StatePath -PathType Leaf) { (Get-Content -LiteralPath $StatePath -Raw -Encoding UTF8).Trim() } else { "" }
        if ($installedTag -ne $release.Tag) { throw "The managed release state was not updated to $($release.Tag)." }
        Write-Update "UPDATED TO $($release.Tag)"
    } finally { Remove-TempDirectoryBestEffort -LiteralPath $tempRoot }
} catch {
    Write-Warning "Automatic update was skipped: $($_.Exception.Message)"
    throw
} finally {
    if ($hasLock) { try { $mutex.ReleaseMutex() } catch {
    } }
    $mutex.Dispose()
}
