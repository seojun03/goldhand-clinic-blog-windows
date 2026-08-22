[CmdletBinding()]
param(
    [string]$CodexPath = $env:GOLDHANDBLOG_CODEX_PATH,
    [string]$EditableRoot = $(if ($env:GOLDHANDBLOG_EDITABLE_ROOT) { $env:GOLDHANDBLOG_EDITABLE_ROOT } else { Join-Path $HOME "GoldhandBlog" })
)

# Keep this file ASCII-only so Windows PowerShell 5.1 can run it reliably.
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$MarketplaceName = "goldhand-clinic-windows"
$PluginName = "goldhand-clinic-blog"
$PluginSelector = "$PluginName@$MarketplaceName"
$TaskName = $(if ($env:GOLDHANDBLOG_AUTO_UPDATE_TASK_NAME) { $env:GOLDHANDBLOG_AUTO_UPDATE_TASK_NAME } else { "GoldhandBlogUpdate" })
$SourceRoot = (Resolve-Path -LiteralPath $PSScriptRoot).Path

function Write-Step([string]$Message) {
    Write-Host "[Goldhand Clinic Blog installer] $Message" -ForegroundColor Cyan
}

function Remove-TempDirectoryBestEffort {
    param(
        [string]$LiteralPath,
        [int[]]$RetryDelaysMilliseconds = @(0, 100, 250, 500)
    )

    if ([string]::IsNullOrWhiteSpace($LiteralPath)) { return $true }
    $lastMessage = "The temporary directory still exists."
    foreach ($delayMs in $RetryDelaysMilliseconds) {
        try {
            if ($delayMs -gt 0) { Start-Sleep -Milliseconds $delayMs }
            if (-not (Test-Path -LiteralPath $LiteralPath -ErrorAction Stop)) { return $true }
            Remove-Item -LiteralPath $LiteralPath -Recurse -Force -ErrorAction Stop
            if (-not (Test-Path -LiteralPath $LiteralPath -ErrorAction Stop)) { return $true }
            $lastMessage = "Remove-Item returned, but the temporary directory still exists."
        } catch {
            $lastMessage = $_.Exception.Message
        }
    }
    try {
        Write-Warning -WarningAction Continue "Temporary directory cleanup was skipped: $LiteralPath ($lastMessage)"
    } catch {
    }
    return $false
}

function Refresh-ProcessPath {
    $machine = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $user = [Environment]::GetEnvironmentVariable("Path", "User")
    $entries = (@($machine, $user, $env:Path) -join ";").Split(";", [System.StringSplitOptions]::RemoveEmptyEntries) |
        Select-Object -Unique
    $env:Path = $entries -join ";"
}

function Get-PythonCommand {
    foreach ($name in @("py.exe", "python.exe")) {
        foreach ($command in @(Get-Command $name -All -ErrorAction SilentlyContinue)) {
            if (-not $command.Source) { continue }
            $previousErrorActionPreference = $ErrorActionPreference
            try {
                $ErrorActionPreference = "Continue"
                $global:LASTEXITCODE = $null
                & $command.Source --version *> $null
                if ($LASTEXITCODE -eq 0) { return $command.Source }
            } catch {
            } finally {
                $ErrorActionPreference = $previousErrorActionPreference
                $global:LASTEXITCODE = 0
            }
        }
    }
    return $null
}

function Test-PythonAvailable {
    return -not [string]::IsNullOrWhiteSpace((Get-PythonCommand))
}

function Install-WingetPackage([string]$Id) {
    if (-not (Get-Command winget.exe -ErrorAction SilentlyContinue)) {
        throw "Required package $Id is missing and winget is unavailable. Install App Installer from the Microsoft Store, then run this installer again."
    }
    Write-Step "Installing required package $Id."
    $previousErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        $global:LASTEXITCODE = $null
        & winget.exe install --id $Id --exact --source winget --accept-package-agreements --accept-source-agreements --silent
        $exitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousErrorActionPreference
        $global:LASTEXITCODE = 0
    }
    $alreadyCurrentExitCodes = @(-1978335189, -1978335153, -1978335135)
    if ($null -eq $exitCode -or ($exitCode -ne 0 -and $alreadyCurrentExitCodes -notcontains $exitCode)) {
        throw "$Id installation failed with winget exit code $exitCode."
    }
    Refresh-ProcessPath
}

function Ensure-Python {
    if (Test-PythonAvailable) {
        Write-Step "Python is available."
        return
    }
    Install-WingetPackage -Id "Python.Python.3.14"
    if (-not (Test-PythonAvailable)) {
        throw "Python was installed but is not available yet. Close this window, reopen PowerShell, and run INSTALL-WINDOWS.cmd again."
    }
}

function Install-PythonRequirements {
    $requirements = Join-Path $SourceRoot "requirements-windows.txt"
    if (-not (Test-Path -LiteralPath $requirements -PathType Leaf)) { throw "The release ZIP is missing requirements-windows.txt." }
    $python = Get-PythonCommand
    if (-not $python) { throw "A working Python command was not found." }
    Write-Step "Installing the plugin's Python requirements."
    $previousErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        $global:LASTEXITCODE = $null
        & $python -m pip install --disable-pip-version-check --quiet --requirement $requirements
        $exitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousErrorActionPreference
        $global:LASTEXITCODE = 0
    }
    if ($null -eq $exitCode -or $exitCode -ne 0) { throw "The plugin's Python requirements could not be installed (exit code $exitCode)." }
}

function Test-VersionCommand([string]$Candidate) {
    if ([string]::IsNullOrWhiteSpace($Candidate)) { return $false }
    $previousErrorActionPreference = $ErrorActionPreference
    try {
        if (-not (Test-Path -LiteralPath $Candidate -PathType Leaf)) { return $false }
        $resolved = (Resolve-Path -LiteralPath $Candidate).Path
        $ErrorActionPreference = "Continue"
        $global:LASTEXITCODE = $null
        & $resolved --version *> $null
        return $LASTEXITCODE -eq 0
    } catch {
        return $false
    } finally {
        $ErrorActionPreference = $previousErrorActionPreference
        $global:LASTEXITCODE = 0
    }
}

function Get-NpmCommand {
    $candidates = @()
    foreach ($name in @("npm.cmd", "npm.exe", "npm")) {
        foreach ($command in @(Get-Command $name -All -ErrorAction SilentlyContinue)) {
            if ($command.Source) { $candidates += $command.Source }
        }
    }
    if ($env:ProgramFiles) { $candidates += (Join-Path $env:ProgramFiles "nodejs\npm.cmd") }
    if (${env:ProgramFiles(x86)}) { $candidates += (Join-Path ${env:ProgramFiles(x86)} "nodejs\npm.cmd") }

    $seen = @{}
    foreach ($candidate in $candidates) {
        if ([string]::IsNullOrWhiteSpace([string]$candidate)) { continue }
        $key = ([string]$candidate).ToLowerInvariant()
        if ($seen.ContainsKey($key)) { continue }
        $seen[$key] = $true
        if (Test-VersionCommand -Candidate ([string]$candidate)) {
            return (Resolve-Path -LiteralPath ([string]$candidate)).Path
        }
    }
    return $null
}

function Get-VercelCommand {
    $candidates = @()
    foreach ($name in @("vercel.cmd", "vercel.exe", "vercel")) {
        foreach ($command in @(Get-Command $name -All -ErrorAction SilentlyContinue)) {
            if ($command.Source) { $candidates += $command.Source }
        }
    }
    if ($env:NPM_CONFIG_PREFIX) { $candidates += (Join-Path $env:NPM_CONFIG_PREFIX "vercel.cmd") }
    if ($env:APPDATA) { $candidates += (Join-Path $env:APPDATA "npm\vercel.cmd") }
    if ($env:LOCALAPPDATA) { $candidates += (Join-Path $env:LOCALAPPDATA "npm\vercel.cmd") }

    $seen = @{}
    foreach ($candidate in $candidates) {
        if ([string]::IsNullOrWhiteSpace([string]$candidate)) { continue }
        $key = ([string]$candidate).ToLowerInvariant()
        if ($seen.ContainsKey($key)) { continue }
        $seen[$key] = $true
        if (Test-VersionCommand -Candidate ([string]$candidate)) {
            return (Resolve-Path -LiteralPath ([string]$candidate)).Path
        }
    }
    return $null
}

function Ensure-NodeAndNpm {
    $script:NpmExecutable = Get-NpmCommand
    if ($script:NpmExecutable) {
        Write-Step "Node.js and npm are available."
        return
    }
    Install-WingetPackage -Id "OpenJS.NodeJS.LTS"
    $script:NpmExecutable = Get-NpmCommand
    if (-not $script:NpmExecutable) {
        throw "Node.js LTS was installed but npm is not available yet. Close this window, reopen PowerShell, and run INSTALL-WINDOWS.cmd again."
    }
}

function Ensure-VercelCli {
    $script:VercelExecutable = Get-VercelCommand
    if ($script:VercelExecutable) {
        Write-Step "Vercel CLI is available at $script:VercelExecutable"
        return
    }

    Ensure-NodeAndNpm
    Write-Step "Installing the Vercel CLI."
    $previousErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        $global:LASTEXITCODE = $null
        $installOutput = @(& $script:NpmExecutable install --global vercel --no-fund --no-audit 2>&1)
        $exitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousErrorActionPreference
        $global:LASTEXITCODE = 0
    }
    if ($null -eq $exitCode -or $exitCode -ne 0) {
        $details = if ($installOutput) { "`n$($installOutput -join [Environment]::NewLine)" } else { "" }
        throw "The Vercel CLI could not be installed with npm (exit code $exitCode).$details"
    }

    Refresh-ProcessPath
    $script:VercelExecutable = Get-VercelCommand
    if (-not $script:VercelExecutable) {
        throw "The Vercel CLI was installed but could not be executed. Close this window, reopen PowerShell, and run INSTALL-WINDOWS.cmd again."
    }
    Write-Step "Vercel CLI is ready at $script:VercelExecutable"
}

function Test-PluginTree([string]$Root) {
    $marketplace = Join-Path $Root ".agents\plugins\marketplace.json"
    $manifest = Join-Path $Root "plugins\$PluginName\.codex-plugin\plugin.json"
    $skill = Join-Path $Root "plugins\$PluginName\skills\$PluginName\SKILL.md"
    $updater = Join-Path $Root "scripts\update-windows.ps1"
    $requirements = Join-Path $Root "requirements-windows.txt"
    return ((Test-Path -LiteralPath $marketplace) -and (Test-Path -LiteralPath $manifest) -and (Test-Path -LiteralPath $skill) -and (Test-Path -LiteralPath $updater) -and (Test-Path -LiteralPath $requirements))
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

function Get-CodexCommand {
    $candidates = @()
    foreach ($candidate in @($CodexPath, $env:GOLDHANDBLOG_CODEX_PATH)) {
        if (-not [string]::IsNullOrWhiteSpace($candidate)) { $candidates += $candidate }
    }
    if ($env:LOCALAPPDATA) {
        $candidates += (Join-Path $env:LOCALAPPDATA "Programs\OpenAI\Codex\bin\codex.exe")
    }
    foreach ($name in @("codex.cmd", "codex.exe", "codex")) {
        foreach ($command in @(Get-Command $name -All -ErrorAction SilentlyContinue)) {
            if ($command.Source) { $candidates += $command.Source }
        }
    }
    if ($env:APPDATA) { $candidates += (Join-Path $env:APPDATA "npm\codex.cmd") }
    if ($env:LOCALAPPDATA) { $candidates += (Join-Path $env:LOCALAPPDATA "npm\codex.cmd") }

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

function Install-OfficialCodexCli {
    Write-Step "Installing the official OpenAI Codex CLI."
    $previousNonInteractive = $env:CODEX_NON_INTERACTIVE
    $previousErrorActionPreference = $ErrorActionPreference
    $tempInstaller = Join-Path ([IO.Path]::GetTempPath()) ("openai-codex-installer-" + [Guid]::NewGuid().ToString("N") + ".ps1")
    try {
        $env:CODEX_NON_INTERACTIVE = "1"
        $source = Invoke-RestMethod -Uri "https://chatgpt.com/codex/install.ps1"
        $encoding = New-Object System.Text.UTF8Encoding($false)
        [IO.File]::WriteAllText($tempInstaller, [string]$source, $encoding)
        $tokens = $null
        $parseErrors = $null
        [System.Management.Automation.Language.Parser]::ParseFile($tempInstaller, [ref]$tokens, [ref]$parseErrors) | Out-Null
        if (@($parseErrors).Count -gt 0) {
            throw "The official OpenAI Codex CLI installer is not valid PowerShell."
        }
        $windowsPowerShell = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
        if (-not (Test-Path -LiteralPath $windowsPowerShell -PathType Leaf)) {
            throw "Windows PowerShell was not found."
        }
        $ErrorActionPreference = "Continue"
        $global:LASTEXITCODE = $null
        $installOutput = @(& $windowsPowerShell -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $tempInstaller 2>&1)
        $installExitCode = $LASTEXITCODE
        if ($null -eq $installExitCode -or $installExitCode -ne 0) {
            $details = if ($installOutput) { "`n$($installOutput -join [Environment]::NewLine)" } else { "" }
            throw "The official OpenAI Codex CLI installer failed with exit code $installExitCode.$details"
        }
    } finally {
        $ErrorActionPreference = $previousErrorActionPreference
        $global:LASTEXITCODE = 0
        if (Test-Path -LiteralPath $tempInstaller) {
            Remove-Item -LiteralPath $tempInstaller -Force -ErrorAction SilentlyContinue
        }
        if ($null -eq $previousNonInteractive) {
            Remove-Item Env:CODEX_NON_INTERACTIVE -ErrorAction SilentlyContinue
        } else {
            $env:CODEX_NON_INTERACTIVE = $previousNonInteractive
        }
    }
    Refresh-ProcessPath
}

function Invoke-Codex([string[]]$Arguments, [switch]$IgnoreFailure, [switch]$Capture) {
    $stderrPath = Join-Path ([IO.Path]::GetTempPath()) ("goldhand-clinic-blog-codex-stderr-" + [Guid]::NewGuid().ToString("N") + ".log")
    $previousNativeErrorActionPreference = $ErrorActionPreference
    try {
        try {
            $ErrorActionPreference = "Continue"
            $global:LASTEXITCODE = $null
            $output = @(& $script:CodexExecutable @Arguments 2>$stderrPath)
            $exitCode = $LASTEXITCODE
        } catch {
            if ($IgnoreFailure) { return $null }
            throw "Could not start Codex at $script:CodexExecutable. $($_.Exception.Message)"
        }
        $stderr = if (Test-Path -LiteralPath $stderrPath) { Get-Content -LiteralPath $stderrPath -Raw -ErrorAction SilentlyContinue } else { "" }
        if ($null -eq $exitCode) {
            if ($IgnoreFailure) { return $null }
            throw "Could not start Codex at $script:CodexExecutable."
        }
        if ($exitCode -ne 0 -and -not $IgnoreFailure) {
            $details = if ($stderr) { "`n$stderr" } elseif ($output) { "`n$($output -join [Environment]::NewLine)" } else { "" }
            throw "Codex command failed: codex $($Arguments -join ' ') (exit code $exitCode)$details"
        }
        if ($Capture) { return ($output -join [Environment]::NewLine) }
        if ($output) { $output | Write-Output }
    } finally {
        $ErrorActionPreference = $previousNativeErrorActionPreference
        Remove-Item -LiteralPath $stderrPath -Force -ErrorAction SilentlyContinue
        $global:LASTEXITCODE = 0
    }
}

function Copy-ManagedTree {
    if (-not (Test-PluginTree -Root $SourceRoot)) {
        throw "Required plugin files are missing. Extract the whole ZIP before running INSTALL-WINDOWS.cmd."
    }
    $sourceFull = [IO.Path]::GetFullPath($SourceRoot).TrimEnd('\')
    $targetFull = [IO.Path]::GetFullPath($EditableRoot).TrimEnd('\')
    if ($sourceFull.Equals($targetFull, [StringComparison]::OrdinalIgnoreCase)) {
        Write-Step "The managed plugin folder is already in place. Reconnecting it."
        return [PSCustomObject]@{ Replaced = $false; BackupRoot = $null }
    }
    $parent = Split-Path -Parent $EditableRoot
    if ($parent -and -not (Test-Path -LiteralPath $parent)) { New-Item -ItemType Directory -Path $parent -Force | Out-Null }
    $leaf = Split-Path -Leaf $EditableRoot
    $staging = Join-Path $parent ($leaf + ".installing." + [Guid]::NewGuid().ToString("N"))
    $backup = Join-Path $parent ($leaf + ".backup." + [DateTime]::UtcNow.ToString("yyyyMMddHHmmss") + "." + [Guid]::NewGuid().ToString("N").Substring(0, 8))
    New-Item -ItemType Directory -Path $staging -Force | Out-Null
    try {
        foreach ($directory in @(".agents", "plugins", "scripts")) {
            $source = Join-Path $SourceRoot $directory
            if (-not (Test-Path -LiteralPath $source -PathType Container)) { throw "The release ZIP is missing the $directory directory." }
            Copy-Item -LiteralPath $source -Destination $staging -Recurse -Force
        }
        foreach ($file in @("README.md", "INSTALL-WINDOWS.cmd", "install-from-download-windows.ps1", "requirements-windows.txt")) {
            $source = Join-Path $SourceRoot $file
            if (Test-Path -LiteralPath $source -PathType Leaf) { Copy-Item -LiteralPath $source -Destination $staging -Force }
        }
        if (-not (Test-PluginTree -Root $staging)) { throw "The staged plugin folder is incomplete." }
        if (Test-Path -LiteralPath $EditableRoot) { Move-Item -LiteralPath $EditableRoot -Destination $backup } else { $backup = $null }
        try { Move-Item -LiteralPath $staging -Destination $EditableRoot } catch {
            if ($backup -and (Test-Path -LiteralPath $backup) -and -not (Test-Path -LiteralPath $EditableRoot)) { Move-Item -LiteralPath $backup -Destination $EditableRoot }
            throw
        }
    } finally {
        try { [void](Remove-TempDirectoryBestEffort -LiteralPath $staging) } catch {
        }
    }
    Write-Step "Replaced the managed plugin tree at $EditableRoot"
    return [PSCustomObject]@{ Replaced = $true; BackupRoot = $backup }
}

function Restore-ManagedTree([string]$BackupRoot, [bool]$Replaced) {
    if (-not $Replaced) { return }
    if (Test-Path -LiteralPath $EditableRoot) {
        if (-not (Remove-TempDirectoryBestEffort -LiteralPath $EditableRoot)) { throw "The failed replacement could not be removed from $EditableRoot." }
    }
    if ($BackupRoot -and (Test-Path -LiteralPath $BackupRoot)) {
        Move-Item -LiteralPath $BackupRoot -Destination $EditableRoot
        Write-Step "Restored the previous managed plugin tree."
    }
}

function Set-UniqueLocalVersion {
    $manifestPath = Join-Path $EditableRoot "plugins\$PluginName\.codex-plugin\plugin.json"
    $manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
    $sourceVersion = [string]$manifest.version
    $baseVersion = ($sourceVersion -split "\+", 2)[0]
    $cacheBuster = [DateTime]::UtcNow.ToString("yyyyMMddHHmmssfff")
    $manifest.version = "$baseVersion+codex.managed.install.$cacheBuster.$PID"
    $encoding = New-Object System.Text.UTF8Encoding($false)
    [IO.File]::WriteAllText($manifestPath, ($manifest | ConvertTo-Json -Depth 100) + [Environment]::NewLine, $encoding)
    $releaseId = if ($env:GOLDHANDBLOG_RELEASE_TAG) { [string]$env:GOLDHANDBLOG_RELEASE_TAG } else { $sourceVersion }
    [IO.File]::WriteAllText((Join-Path $EditableRoot ".goldhand-clinic-blog-managed-release"), $releaseId + [Environment]::NewLine, $encoding)
    return $manifest.version
}

function Remove-LegacyDesktopShortcut {
    $desktop = [Environment]::GetFolderPath("Desktop")
    if (-not $desktop) { return }
    $shortcut = Join-Path $desktop "goldhand-clinic-blog-apply-my-edits.cmd"
    if (Test-Path -LiteralPath $shortcut -PathType Leaf) { Remove-Item -LiteralPath $shortcut -Force -ErrorAction SilentlyContinue }
}

function Register-AutoUpdate {
    if ($env:GOLDHANDBLOG_SKIP_AUTO_UPDATE_REGISTRATION -eq "1") { Write-Step "Automatic update registration was skipped for this test run."; return }
    $updateScript = Join-Path $EditableRoot "scripts\update-windows.ps1"
    if (-not (Test-Path -LiteralPath $updateScript -PathType Leaf)) { throw "The release ZIP is missing scripts\update-windows.ps1." }
    $arguments = '-NoLogo -NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File "' + $updateScript + '" -CodexPath "' + $script:CodexExecutable + '" -EditableRoot "' + $EditableRoot + '"'
    try {
        if (-not (Get-Command "Register-ScheduledTask" -ErrorAction SilentlyContinue)) { throw "Scheduled Tasks commands are unavailable." }
        $action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $arguments
        $logon = New-ScheduledTaskTrigger -AtLogOn
        $periodic = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(10) -RepetitionInterval (New-TimeSpan -Hours 6) -RepetitionDuration (New-TimeSpan -Days 3650)
        Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger @($logon, $periodic) -Description "Update the Goldhand Clinic Blog Codex plugin from the latest validated release." -Force | Out-Null
        Write-Step "Automatic updates are enabled at sign-in and every six hours."
        return
    } catch { Write-Warning "Scheduled Task registration failed. Using the Startup folder fallback: $($_.Exception.Message)" }
    $startup = [Environment]::GetFolderPath("Startup")
    if ([string]::IsNullOrWhiteSpace($startup)) { throw "Automatic updates could not be registered." }
    if (-not (Test-Path -LiteralPath $startup -PathType Container)) { New-Item -ItemType Directory -Path $startup -Force | Out-Null }
    $fallback = Join-Path $startup "GoldhandBlogUpdate.cmd"
    $content = "@echo off`r`nstart `"`" /min powershell.exe $arguments`r`n"
    $encoding = New-Object System.Text.ASCIIEncoding
    [IO.File]::WriteAllText($fallback, $content, $encoding)
    Write-Step "Automatic updates are enabled at Windows sign-in."
}

function Install-DownloadedPlugin {
    Write-Step "Installing the managed plugin without changing the ChatGPT app or Git."
    Ensure-Python
    Install-PythonRequirements
    Ensure-VercelCli

    if ($env:CODEX_HOME -and -not (Test-Path -LiteralPath $env:CODEX_HOME)) {
        New-Item -ItemType Directory -Path $env:CODEX_HOME -Force | Out-Null
    }

    $script:CodexExecutable = Get-CodexCommand
    if (-not $script:CodexExecutable) {
        Install-OfficialCodexCli
        $script:CodexExecutable = Get-CodexCommand
    }
    if (-not $script:CodexExecutable) {
        throw "The official Codex CLI could not be installed or verified."
    }
    $env:GOLDHANDBLOG_CODEX_PATH = $script:CodexExecutable
    Write-Step "Found Codex at $script:CodexExecutable"

    $before = (Invoke-Codex -Arguments @("plugin", "list", "--json") -Capture) | ConvertFrom-Json
    $beforeInstalled = $before.installed | Where-Object { $_.pluginId -eq $PluginSelector } | Select-Object -First 1
    $previousSourceType = if ($beforeInstalled) { [string]$beforeInstalled.marketplaceSource.sourceType } else { "" }
    $previousMarketplaceSource = if ($beforeInstalled) { [string]$beforeInstalled.marketplaceSource.source } else { "" }
    $canRestoreConnection = $beforeInstalled -and (@("local", "git") -contains $previousSourceType) -and (-not [string]::IsNullOrWhiteSpace($previousMarketplaceSource))
    $treeResult = $null
    try {
        $treeResult = Copy-ManagedTree
        $localVersion = Set-UniqueLocalVersion
        Invoke-Codex -Arguments @("plugin", "remove", $PluginSelector, "--json") -IgnoreFailure -Capture | Out-Null
        Invoke-Codex -Arguments @("plugin", "marketplace", "remove", $MarketplaceName, "--json") -IgnoreFailure -Capture | Out-Null
        Invoke-Codex -Arguments @("plugin", "marketplace", "add", $EditableRoot, "--json") -Capture | Out-Null
        Invoke-Codex -Arguments @("plugin", "add", $PluginSelector, "--json") -Capture | Out-Null

        $json = Invoke-Codex -Arguments @("plugin", "list", "--json") -Capture
        $plugins = $json | ConvertFrom-Json
        $installed = $plugins.installed | Where-Object { $_.pluginId -eq $PluginSelector } | Select-Object -First 1
        if (-not $installed -or -not $installed.enabled) {
            throw "The plugin was not enabled after installation."
        }
        if ($installed.marketplaceSource.sourceType -ne "local") {
            throw "The installed plugin is not connected to the managed local copy."
        }
        if ([string]$installed.version -ne [string]$localVersion) {
            throw "The installed version does not match the downloaded local copy."
        }
        Register-AutoUpdate
    } catch {
        $installError = $_.Exception
        Write-Warning "Install failed. Restoring the previous managed version."
        try {
            Invoke-Codex -Arguments @("plugin", "remove", $PluginSelector, "--json") -IgnoreFailure -Capture | Out-Null
            Invoke-Codex -Arguments @("plugin", "marketplace", "remove", $MarketplaceName, "--json") -IgnoreFailure -Capture | Out-Null
            if ($treeResult) { Restore-ManagedTree -BackupRoot ([string]$treeResult.BackupRoot) -Replaced ([bool]$treeResult.Replaced) }
            if ($canRestoreConnection) {
                Invoke-Codex -Arguments @("plugin", "marketplace", "remove", $MarketplaceName, "--json") -IgnoreFailure -Capture | Out-Null
                Invoke-Codex -Arguments @("plugin", "marketplace", "add", $previousMarketplaceSource, "--json") -Capture | Out-Null
                Invoke-Codex -Arguments @("plugin", "add", $PluginSelector, "--json") -Capture | Out-Null
            }
        } catch {
            Write-Warning "Could not completely restore the previous plugin version: $($_.Exception.Message)"
        }
        throw $installError
    }

    if ($treeResult -and $treeResult.BackupRoot) { try { [void](Remove-TempDirectoryBestEffort -LiteralPath ([string]$treeResult.BackupRoot)) } catch {
    } }
    Remove-LegacyDesktopShortcut
    Write-Host ""
    Write-Step "INSTALLATION COMPLETE"
    Write-Step "Open ChatGPT, start a new task, and select the Goldhand Clinic Blog plugin."
    Write-Step "Vercel CLI is installed. Vercel account login and image-project connection remain a one-time user-approved setup."
    Write-Step "Future validated releases will update automatically on Windows."
}

try {
    Install-DownloadedPlugin
} catch {
    Write-Host ""
    Write-Host "[INSTALLATION FAILED] $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "Keep this window open and send a screenshot to the plugin author." -ForegroundColor Yellow
    throw
}
