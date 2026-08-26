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
$LegacyMarketplaceName = "goldhand-clinic"
$LegacyPluginSelector = "$PluginName@$LegacyMarketplaceName"
$LegacyTaskName = "GoldhandClinicPluginUpdate"
$LegacyStartupFileName = "GoldhandClinicPluginUpdate.cmd"
$LegacyRoot = $(if ($env:GOLDHANDBLOG_LEGACY_ROOT) { $env:GOLDHANDBLOG_LEGACY_ROOT } else { Join-Path $HOME "GoldhandClinicPlugin" })
$SourceRoot = (Resolve-Path -LiteralPath $PSScriptRoot).Path
$MinimumVercelCliVersion = [Version]"50.44.0"

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

function Get-BoundedPositiveInteger {
    param(
        [string]$Value,
        [int]$Default,
        [int]$Minimum,
        [int]$Maximum
    )
    $parsed = 0
    if (-not [string]::IsNullOrWhiteSpace($Value) -and [int]::TryParse($Value, [ref]$parsed)) {
        if ($parsed -ge $Minimum -and $parsed -le $Maximum) { return $parsed }
    }
    return $Default
}

function Get-InstallerLogTail([string[]]$Paths) {
    $lines = @()
    foreach ($path in $Paths) {
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { continue }
        try {
            $content = @(Get-Content -LiteralPath $path -Tail 20 -ErrorAction Stop)
            if ($content) { $lines += $content }
        } catch {
        }
    }
    if (-not $lines) { return "" }
    return "`nLast installer output:`n" + (($lines | Select-Object -Last 30) -join [Environment]::NewLine)
}

function Stop-ProcessTreeBestEffort([System.Diagnostics.Process]$Process) {
    if (-not $Process) { return }
    try {
        $Process.Refresh()
        if ($Process.HasExited) { return }
    } catch {
        return
    }
    try {
        $taskkill = Get-Command "taskkill.exe" -ErrorAction SilentlyContinue
        if ($taskkill -and $taskkill.Source) {
            & $taskkill.Source /PID $Process.Id /T /F *> $null
            $global:LASTEXITCODE = 0
        }
    } catch {
    }
    try {
        $Process.Refresh()
        if (-not $Process.HasExited) { $Process.Kill() }
        [void]$Process.WaitForExit(5000)
    } catch {
    }
}

function Install-WingetPackage([string]$Id) {
    $winget = Get-Command winget.exe -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $winget -or -not $winget.Source) {
        throw "Required package $Id is missing and winget is unavailable. Install App Installer from the Microsoft Store, then run this installer again."
    }
    $timeoutSeconds = Get-BoundedPositiveInteger -Value $env:GOLDHANDBLOG_WINGET_TIMEOUT_SECONDS -Default 900 -Minimum 60 -Maximum 3600
    $stallDefaultSeconds = [Math]::Min(240, $timeoutSeconds)
    $stallSeconds = Get-BoundedPositiveInteger -Value $env:GOLDHANDBLOG_WINGET_STALL_SECONDS -Default $stallDefaultSeconds -Minimum 30 -Maximum $timeoutSeconds
    $pollMilliseconds = 2000
    $progressSeconds = 15
    $stdoutPath = Join-Path ([IO.Path]::GetTempPath()) ("goldhand-winget-out-" + [Guid]::NewGuid().ToString("N") + ".log")
    $stderrPath = Join-Path ([IO.Path]::GetTempPath()) ("goldhand-winget-err-" + [Guid]::NewGuid().ToString("N") + ".log")
    $process = $null
    $exitCode = $null
    $details = ""
    Write-Step "Installing required package $Id. This step is limited to $timeoutSeconds seconds."
    try {
        $arguments = @(
            "install", "--id", $Id, "--exact", "--source", "winget",
            "--accept-package-agreements", "--accept-source-agreements",
            "--disable-interactivity", "--silent"
        )
        $process = Start-Process -FilePath $winget.Source -ArgumentList $arguments -NoNewWindow -PassThru -RedirectStandardOutput $stdoutPath -RedirectStandardError $stderrPath
        $startedUtc = [DateTime]::UtcNow
        $lastActivityUtc = $startedUtc
        $lastProgressUtc = $startedUtc
        $lastLogSize = [int64]0
        $failure = ""
        while (-not $process.HasExited) {
            Start-Sleep -Milliseconds $pollMilliseconds
            $nowUtc = [DateTime]::UtcNow
            $logSize = [int64]0
            foreach ($logPath in @($stdoutPath, $stderrPath)) {
                if (Test-Path -LiteralPath $logPath -PathType Leaf) {
                    try { $logSize += (Get-Item -LiteralPath $logPath -ErrorAction Stop).Length } catch {
                    }
                }
            }
            if ($logSize -ne $lastLogSize) {
                $lastLogSize = $logSize
                $lastActivityUtc = $nowUtc
            }
            $elapsedSeconds = [int][Math]::Floor(($nowUtc - $startedUtc).TotalSeconds)
            $idleSeconds = [int][Math]::Floor(($nowUtc - $lastActivityUtc).TotalSeconds)
            if ($elapsedSeconds -ge $timeoutSeconds) {
                $failure = "$Id installation timed out after $timeoutSeconds seconds."
                break
            }
            if ($idleSeconds -ge $stallSeconds) {
                $failure = "$Id installation produced no progress for $stallSeconds seconds and was stopped. Check for a hidden administrator approval or Windows Installer window, then rerun INSTALL-WINDOWS.cmd."
                break
            }
            if (($nowUtc - $lastProgressUtc).TotalSeconds -ge $progressSeconds) {
                Write-Step "$Id installation is still running ($elapsedSeconds seconds elapsed; $idleSeconds seconds since installer output)."
                $lastProgressUtc = $nowUtc
            }
        }
        if ($failure) {
            Stop-ProcessTreeBestEffort -Process $process
            $details = Get-InstallerLogTail -Paths @($stdoutPath, $stderrPath)
            throw "$failure$details"
        }
        $process.WaitForExit()
        $exitCode = $process.ExitCode
        $details = Get-InstallerLogTail -Paths @($stdoutPath, $stderrPath)
    } finally {
        if ($process) { try { $process.Dispose() } catch {
        } }
        Remove-Item -LiteralPath $stdoutPath -Force -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath $stderrPath -Force -ErrorAction SilentlyContinue
        $global:LASTEXITCODE = 0
    }
    $alreadyCurrentExitCodes = @(-1978335189, -1978335153, -1978335135)
    if ($null -eq $exitCode -or ($exitCode -ne 0 -and $alreadyCurrentExitCodes -notcontains $exitCode)) {
        throw "$Id installation failed with winget exit code $exitCode.$details"
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

function Get-VercelCliVersion([string]$Candidate) {
    if ([string]::IsNullOrWhiteSpace($Candidate)) { return $null }
    $previousErrorActionPreference = $ErrorActionPreference
    try {
        if (-not (Test-Path -LiteralPath $Candidate -PathType Leaf)) { return $null }
        $resolved = (Resolve-Path -LiteralPath $Candidate).Path
        $ErrorActionPreference = "Continue"
        $global:LASTEXITCODE = $null
        $output = @(& $resolved --version 2>&1)
        if ($LASTEXITCODE -ne 0) { return $null }
        $match = [regex]::Match(($output -join " "), '(\d+\.\d+\.\d+)')
        if (-not $match.Success) { return $null }
        return [Version]$match.Groups[1].Value
    } catch {
        return $null
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
        $version = Get-VercelCliVersion -Candidate ([string]$candidate)
        if ($version -and $version -ge $MinimumVercelCliVersion) {
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
        $env:GOLDHAND_VERCEL_CLI = $script:VercelExecutable
        Write-Step "Vercel CLI is available at $script:VercelExecutable"
        return
    }

    Ensure-NodeAndNpm
    Write-Step "Installing a supported Vercel CLI."
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
    $env:GOLDHAND_VERCEL_CLI = $script:VercelExecutable
    Write-Step "Vercel CLI is ready at $script:VercelExecutable"
}

function Test-PluginTree([string]$Root) {
    $marketplace = Join-Path $Root ".agents\plugins\marketplace.json"
    $manifest = Join-Path $Root "plugins\$PluginName\.codex-plugin\plugin.json"
    $skill = Join-Path $Root "plugins\$PluginName\skills\$PluginName\SKILL.md"
    $updater = Join-Path $Root "scripts\update-windows.ps1"
    $requirements = Join-Path $Root "requirements-windows.txt"
    $imageSetup = Join-Path $Root "SETUP-IMAGES-WINDOWS.cmd"
    $imageSetupPython = Join-Path $Root "plugins\$PluginName\skills\$PluginName\scripts\setup_image_host.py"
    return ((Test-Path -LiteralPath $marketplace) -and (Test-Path -LiteralPath $manifest) -and (Test-Path -LiteralPath $skill) -and (Test-Path -LiteralPath $updater) -and (Test-Path -LiteralPath $requirements) -and (Test-Path -LiteralPath $imageSetup) -and (Test-Path -LiteralPath $imageSetupPython))
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
        foreach ($file in @("README.md", "INSTALL-WINDOWS.cmd", "SETUP-IMAGES-WINDOWS.cmd", "install-from-download-windows.ps1", "requirements-windows.txt")) {
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

function Remove-LegacyAutoUpdateBestEffort {
    try {
        if (Get-Command "Get-ScheduledTask" -ErrorAction SilentlyContinue) {
            $legacyTask = Get-ScheduledTask -TaskName $LegacyTaskName -ErrorAction SilentlyContinue
            if ($legacyTask) {
                Unregister-ScheduledTask -TaskName $LegacyTaskName -Confirm:$false -ErrorAction Stop
                Write-Step "Removed the legacy scheduled updater $LegacyTaskName."
            }
        }
    } catch {
        Write-Warning "The legacy scheduled updater could not be removed: $($_.Exception.Message)"
    }

    try {
        $startup = [Environment]::GetFolderPath("Startup")
        if (-not [string]::IsNullOrWhiteSpace($startup)) {
            $legacyStartup = Join-Path $startup $LegacyStartupFileName
            if (Test-Path -LiteralPath $legacyStartup -PathType Leaf) {
                Remove-Item -LiteralPath $legacyStartup -Force -ErrorAction Stop
                Write-Step "Removed the legacy Startup-folder updater $LegacyStartupFileName."
            }
        }
    } catch {
        Write-Warning "The legacy Startup-folder updater could not be removed: $($_.Exception.Message)"
    }
}

function Backup-LegacyRootBestEffort {
    if ([string]::IsNullOrWhiteSpace($LegacyRoot) -or -not (Test-Path -LiteralPath $LegacyRoot -PathType Container)) { return $null }
    try {
        $legacyFull = [IO.Path]::GetFullPath($LegacyRoot).TrimEnd('\')
        $currentFull = [IO.Path]::GetFullPath($EditableRoot).TrimEnd('\')
        if ($legacyFull.Equals($currentFull, [StringComparison]::OrdinalIgnoreCase)) {
            Write-Warning "The legacy folder matches the current managed folder and was not moved."
            return $null
        }
        $legacyManifestPath = Join-Path $LegacyRoot ".agents\plugins\marketplace.json"
        if (-not (Test-Path -LiteralPath $legacyManifestPath -PathType Leaf)) {
            Write-Warning "The legacy folder has no Goldhand marketplace marker and was left in place: $LegacyRoot"
            return $null
        }
        $legacyManifest = Get-Content -LiteralPath $legacyManifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
        $legacyPlugin = $legacyManifest.plugins | Where-Object { $_.name -eq $PluginName } | Select-Object -First 1
        if ($legacyManifest.name -ne $LegacyMarketplaceName -or -not $legacyPlugin) {
            Write-Warning "The legacy folder marker does not identify $LegacyPluginSelector and was left in place: $LegacyRoot"
            return $null
        }
        $parent = Split-Path -Parent $LegacyRoot
        $leaf = Split-Path -Leaf $LegacyRoot
        $backup = Join-Path $parent ($leaf + ".legacy-backup." + [DateTime]::UtcNow.ToString("yyyyMMddHHmmss") + "." + [Guid]::NewGuid().ToString("N").Substring(0, 8))
        Move-Item -LiteralPath $LegacyRoot -Destination $backup -ErrorAction Stop
        Write-Step "Preserved the legacy plugin folder as a backup at $backup"
        return $backup
    } catch {
        Write-Warning "The legacy plugin folder was left in place because it could not be backed up: $($_.Exception.Message)"
        return $null
    }
}

function Retire-LegacyInstallationBestEffort {
    if ($env:GOLDHANDBLOG_SKIP_LEGACY_RETIREMENT -eq "1") {
        Write-Step "Legacy plugin retirement was skipped for this test run."
        return
    }
    Write-Step "Checking for the legacy Goldhand Clinic Blog installation."
    $legacyConnectionRetired = $false
    try {
        $beforePlugins = (Invoke-Codex -Arguments @("plugin", "list", "--json") -Capture) | ConvertFrom-Json
        $legacyInstalled = $beforePlugins.installed | Where-Object { $_.pluginId -eq $LegacyPluginSelector } | Select-Object -First 1
        if ($legacyInstalled) {
            Invoke-Codex -Arguments @("plugin", "remove", $LegacyPluginSelector, "--json") -Capture | Out-Null
        }

        $beforeMarketplaces = (Invoke-Codex -Arguments @("plugin", "marketplace", "list", "--json") -Capture) | ConvertFrom-Json
        $legacyMarketplace = $beforeMarketplaces.marketplaces | Where-Object { $_.name -eq $LegacyMarketplaceName } | Select-Object -First 1
        if ($legacyMarketplace) {
            Invoke-Codex -Arguments @("plugin", "marketplace", "remove", $LegacyMarketplaceName, "--json") -Capture | Out-Null
        }

        $afterPlugins = (Invoke-Codex -Arguments @("plugin", "list", "--json") -Capture) | ConvertFrom-Json
        $afterMarketplaces = (Invoke-Codex -Arguments @("plugin", "marketplace", "list", "--json") -Capture) | ConvertFrom-Json
        $legacyStillInstalled = $afterPlugins.installed | Where-Object { $_.pluginId -eq $LegacyPluginSelector } | Select-Object -First 1
        $legacyMarketplaceStillConfigured = $afterMarketplaces.marketplaces | Where-Object { $_.name -eq $LegacyMarketplaceName } | Select-Object -First 1
        $legacyConnectionRetired = (-not $legacyStillInstalled) -and (-not $legacyMarketplaceStillConfigured)
        if ($legacyConnectionRetired -and ($legacyInstalled -or $legacyMarketplace)) {
            Write-Step "Unregistered the legacy $LegacyPluginSelector connection."
        }
    } catch {
        Write-Warning "The legacy plugin connection could not be completely retired: $($_.Exception.Message)"
    }

    Remove-LegacyAutoUpdateBestEffort
    if ($legacyConnectionRetired) {
        [void](Backup-LegacyRootBestEffort)
    } elseif (Test-Path -LiteralPath $LegacyRoot -PathType Container) {
        Write-Warning "The legacy plugin folder remains unchanged because its Codex connection is still present."
    }
}

function Write-ImageSetupDesktopLauncher {
    if ($env:GOLDHANDBLOG_SKIP_DESKTOP_SHORTCUT -eq "1") { return }
    $desktop = [Environment]::GetFolderPath("Desktop")
    if ([string]::IsNullOrWhiteSpace($desktop)) { return }
    if (-not (Test-Path -LiteralPath $desktop -PathType Container)) { return }
    $target = Join-Path $EditableRoot "SETUP-IMAGES-WINDOWS.cmd"
    if (-not (Test-Path -LiteralPath $target -PathType Leaf)) { return }
    $launcher = Join-Path $desktop "Goldhand Image Setup.lnk"
    try {
        $shell = New-Object -ComObject WScript.Shell
        $shortcut = $shell.CreateShortcut($launcher)
        $shortcut.TargetPath = $target
        $shortcut.WorkingDirectory = $EditableRoot
        $shortcut.Description = "Connect automatic GPT image hosting for Goldhand Clinic Blog"
        $shortcut.Save()
        Write-Step "Created the one-click image setup shortcut on the Desktop."
    } catch {
        Write-Warning "The Desktop image setup shortcut could not be created: $($_.Exception.Message)"
    }
}

function Invoke-ImageHostSetupBestEffort {
    if ($env:GOLDHANDBLOG_SKIP_IMAGE_HOST_SETUP -eq "1") {
        Write-Step "Automatic image-host setup was skipped for this test or update run."
        return
    }
    $setupScript = Join-Path $EditableRoot "plugins\$PluginName\skills\$PluginName\scripts\setup_image_host.py"
    if (-not (Test-Path -LiteralPath $setupScript -PathType Leaf)) {
        Write-Warning "The automatic image setup script is missing. Rerun INSTALL-WINDOWS.cmd."
        return
    }
    $python = Get-PythonCommand
    if (-not $python) {
        Write-Warning "Python is unavailable for the automatic image setup. Rerun INSTALL-WINDOWS.cmd."
        return
    }
    Write-Host ""
    Write-Step "One-time image setup is starting. In the browser, sign in and click Allow; do not find or type a code."
    $previousErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        $global:LASTEXITCODE = $null
        & $python -X utf8 $setupScript
        $exitCode = $LASTEXITCODE
    } catch {
        $exitCode = 1
    } finally {
        $ErrorActionPreference = $previousErrorActionPreference
        $global:LASTEXITCODE = 0
    }
    if ($null -eq $exitCode -or $exitCode -ne 0) {
        Write-Warning "Automatic images are not connected yet. Close any blank code page, then double-click Goldhand Image Setup on the Desktop for a fresh approval request."
        return
    }
    Write-Step "Automatic GPT image hosting is connected."
}

function Initialize-OptionalImageToolsBestEffort {
    Write-ImageSetupDesktopLauncher
    try {
        Ensure-VercelCli
    } catch {
        Write-Warning "The core plugin is installed, but optional Node.js or Vercel setup did not finish: $($_.Exception.Message)"
        Write-Warning "You can use the plugin now. Rerun INSTALL-WINDOWS.cmd later, or use Goldhand Image Setup on the Desktop after Node.js is available."
        return $false
    }
    Invoke-ImageHostSetupBestEffort
    return $true
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
    Retire-LegacyInstallationBestEffort
    Remove-LegacyDesktopShortcut
    $imageToolsReady = Initialize-OptionalImageToolsBestEffort
    Write-Host ""
    Write-Step "INSTALLATION COMPLETE"
    Write-Step "Open ChatGPT, start a new task, and select the Goldhand Clinic Blog plugin."
    if ($imageToolsReady) {
        Write-Step "Vercel CLI is installed. After one browser approval, the image project and plugin settings are configured automatically."
    } else {
        Write-Step "The core blog plugin is ready. Optional automatic image hosting can be completed later from Goldhand Image Setup."
    }
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
