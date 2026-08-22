[CmdletBinding()]
param(
    [string]$CodexPath = $env:GOLDHANDBLOG_CODEX_PATH,
    [string]$CodexHome = $(if ($env:CODEX_HOME) { $env:CODEX_HOME } else { Join-Path $HOME ".codex" })
)

$ErrorActionPreference = "Stop"
$PluginName = "goldhand-clinic-blog"
$MarketplaceName = "goldhand-clinic-windows"
$PluginSelector = "$PluginName@$MarketplaceName"
$RepoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$PluginRoot = Join-Path $RepoRoot "plugins\$PluginName"
$ManifestPath = Join-Path $PluginRoot ".codex-plugin\plugin.json"
$SkillPath = Join-Path $PluginRoot "skills\$PluginName\SKILL.md"

function Write-Step([string]$Message) {
    Write-Host "[Goldhand Clinic Blog local edits] $Message" -ForegroundColor Cyan
}

function Test-CodexExecutable([string]$Candidate) {
    if ([string]::IsNullOrWhiteSpace($Candidate)) { return $false }
    $previousErrorActionPreference = $ErrorActionPreference
    try {
        if (-not (Test-Path -LiteralPath $Candidate -PathType Leaf)) { return $false }
        $resolved = (Resolve-Path -LiteralPath $Candidate).Path
        $ErrorActionPreference = "Continue"
        $global:LASTEXITCODE = $null
        & $resolved plugin --help *> $null
        return $LASTEXITCODE -eq 0
    } catch {
        return $false
    } finally {
        $ErrorActionPreference = $previousErrorActionPreference
        $global:LASTEXITCODE = 0
    }
}

function Get-NpmCommand {
    foreach ($name in @("npm.cmd", "npm")) {
        foreach ($command in @(Get-Command $name -All -ErrorAction SilentlyContinue)) {
            if ($command.Source -and (Test-Path -LiteralPath $command.Source -PathType Leaf)) { return $command.Source }
        }
    }
    foreach ($candidate in @(
        $(if ($env:ProgramFiles) { Join-Path $env:ProgramFiles "nodejs\npm.cmd" }),
        $(if (${env:ProgramFiles(x86)}) { Join-Path ${env:ProgramFiles(x86)} "nodejs\npm.cmd" }),
        $(if ($env:LOCALAPPDATA) { Join-Path $env:LOCALAPPDATA "Programs\nodejs\npm.cmd" })
    )) {
        if ($candidate -and (Test-Path -LiteralPath $candidate -PathType Leaf)) { return (Resolve-Path -LiteralPath $candidate).Path }
    }
    return $null
}

function Get-CodexCommand {
    $candidates = @()
    foreach ($candidate in @($CodexPath, $env:GOLDHANDBLOG_CODEX_PATH)) {
        if (-not [string]::IsNullOrWhiteSpace($candidate)) { $candidates += $candidate }
    }
    if ($env:LOCALAPPDATA) { $candidates += (Join-Path $env:LOCALAPPDATA "Programs\OpenAI\Codex\bin\codex.exe") }
    foreach ($name in @("codex.cmd", "codex.exe", "codex")) {
        foreach ($command in @(Get-Command $name -All -ErrorAction SilentlyContinue)) {
            if ($command.Source) { $candidates += $command.Source }
        }
    }
    if ($env:APPDATA) { $candidates += (Join-Path $env:APPDATA "npm\codex.cmd") }
    if ($env:LOCALAPPDATA) { $candidates += (Join-Path $env:LOCALAPPDATA "npm\codex.cmd") }
    $npm = Get-NpmCommand
    if ($npm) {
        $previousErrorActionPreference = $ErrorActionPreference
        try {
            $ErrorActionPreference = "SilentlyContinue"
            $prefixOutput = @(& $npm prefix --global 2>$null)
            if ($LASTEXITCODE -eq 0 -and $prefixOutput.Count -gt 0) {
                $prefix = [string]$prefixOutput[-1]
                if (-not [string]::IsNullOrWhiteSpace($prefix)) { $candidates += (Join-Path $prefix.Trim() "codex.cmd") }
            }
        } catch {
        } finally {
            $ErrorActionPreference = $previousErrorActionPreference
            $global:LASTEXITCODE = 0
        }
    }
    $seen = @{}
    foreach ($candidate in $candidates) {
        if ([string]::IsNullOrWhiteSpace([string]$candidate)) { continue }
        $key = ([string]$candidate).ToLowerInvariant()
        if ($seen.ContainsKey($key)) { continue }
        $seen[$key] = $true
        if (Test-CodexExecutable -Candidate ([string]$candidate)) {
            return (Resolve-Path -LiteralPath ([string]$candidate)).Path
        }
    }
    return $null
}

function Invoke-Codex([string[]]$Arguments, [switch]$Capture) {
    $stderrPath = Join-Path ([IO.Path]::GetTempPath()) ("goldhand-clinic-blog-codex-stderr-" + [Guid]::NewGuid().ToString("N") + ".log")
    $previousNativeErrorActionPreference = $ErrorActionPreference
    try {
        try {
            $ErrorActionPreference = "Continue"
            $global:LASTEXITCODE = $null
            $output = @(& $script:CodexExecutable @Arguments 2>$stderrPath)
            $exitCode = $LASTEXITCODE
        } catch {
            throw "Codex 실행 파일을 시작하지 못했습니다: $script:CodexExecutable. $($_.Exception.Message)"
        }
        $stderr = if (Test-Path -LiteralPath $stderrPath) { Get-Content -LiteralPath $stderrPath -Raw -ErrorAction SilentlyContinue } else { "" }
        if ($null -eq $exitCode) { throw "Codex 실행 파일을 시작하지 못했습니다: $script:CodexExecutable" }
        if ($exitCode -ne 0) {
            $details = if ($stderr) { "`n$stderr" } elseif ($output) { "`n$($output -join [Environment]::NewLine)" } else { "" }
            throw "Codex 명령에 실패했습니다: codex $($Arguments -join ' ') (종료 코드 $exitCode)$details"
        }
        if ($Capture) { return ($output -join [Environment]::NewLine) }
        if ($output) { $output | Write-Output }
    } finally {
        $ErrorActionPreference = $previousNativeErrorActionPreference
        Remove-Item -LiteralPath $stderrPath -Force -ErrorAction SilentlyContinue
        $global:LASTEXITCODE = 0
    }
}

if (-not (Test-Path -LiteralPath $ManifestPath)) {
    throw "플러그인 매니페스트를 찾지 못했습니다: $ManifestPath"
}
if (-not (Test-Path -LiteralPath $SkillPath)) {
    throw "수정할 SKILL.md를 찾지 못했습니다: $SkillPath"
}
if (-not (Test-Path -LiteralPath $CodexHome)) {
    New-Item -ItemType Directory -Path $CodexHome -Force | Out-Null
}
$env:CODEX_HOME = $CodexHome
$script:CodexExecutable = Get-CodexCommand
if (-not $script:CodexExecutable) {
    throw "플러그인 기능이 있는 Codex 실행 파일을 찾지 못했습니다."
}
$env:GOLDHANDBLOG_CODEX_PATH = $script:CodexExecutable

$manifest = Get-Content -LiteralPath $ManifestPath -Raw | ConvertFrom-Json
$baseVersion = ([string]$manifest.version -split "\+", 2)[0]
$cacheBuster = [DateTime]::UtcNow.ToString("yyyyMMddHHmmssfff")
$newVersion = "$baseVersion+codex.local.$cacheBuster.$PID"
$manifest.version = $newVersion
$encoding = New-Object System.Text.UTF8Encoding($false)
[IO.File]::WriteAllText($ManifestPath, ($manifest | ConvertTo-Json -Depth 100) + [Environment]::NewLine, $encoding)

Write-Step "로컬 지침을 재설치합니다: $newVersion"
Invoke-Codex -Arguments @("plugin", "add", $PluginSelector, "--json") -Capture | Out-Null

$plugins = (Invoke-Codex -Arguments @("plugin", "list", "--json") -Capture) | ConvertFrom-Json
$installed = $plugins.installed | Where-Object { $_.pluginId -eq $PluginSelector } | Select-Object -First 1
if (-not $installed -or -not $installed.enabled -or [string]$installed.version -ne $newVersion) {
    throw "수정한 버전의 재설치를 확인하지 못했습니다."
}
if ($installed.marketplaceSource.sourceType -ne "local") {
    throw "로컬 편집본이 아닌 마켓플레이스에 연결되어 있습니다. 편집용 설치기를 다시 실행하세요."
}

Write-Step "적용 완료: ChatGPT에서 새 작업을 열어 테스트하세요."
Write-Step "수정 파일: $SkillPath"
