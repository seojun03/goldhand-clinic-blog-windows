@echo off
setlocal
chcp 65001 >nul
title Goldhand Clinic Blog Plugin Installer

set "LOCAL_INSTALLER=%~dp0install-from-download-windows.ps1"

if exist "%LOCAL_INSTALLER%" (
  powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%LOCAL_INSTALLER%"
) else (
  echo.
  echo Complete ZIP contents were not found next to INSTALL-WINDOWS.cmd.
  echo Downloading and extracting a complete copy before installation...
  powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -Command ^
    "$ErrorActionPreference = 'Stop';" ^
    "$archiveSource = $env:GOLDHANDBLOG_BOOTSTRAP_ARCHIVE;" ^
    "$tempBase = [Environment]::GetFolderPath('UserProfile');" ^
    "if ([string]::IsNullOrWhiteSpace($tempBase)) { $tempBase = [IO.Path]::GetTempPath() };" ^
    "$tempRoot = Join-Path $tempBase ('.ghb-' + [Guid]::NewGuid().ToString('N').Substring(0, 8));" ^
    "try {" ^
    "  New-Item -ItemType Directory -Path $tempRoot -Force | Out-Null;" ^
    "  $archive = Join-Path $tempRoot 'source.zip';" ^
    "  if (-not [string]::IsNullOrWhiteSpace($archiveSource) -and (Test-Path -LiteralPath $archiveSource -PathType Leaf)) {" ^
    "    Copy-Item -LiteralPath $archiveSource -Destination $archive -Force;" ^
    "  } else {" ^
    "    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12;" ^
    "    $cacheBuster = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds();" ^
    "    Invoke-WebRequest -UseBasicParsing -Uri ('https://github.com/seojun03/goldhand-clinic-blog-windows/releases/latest/download/goldhand-clinic-blog-plugin.zip?cachebust=' + $cacheBuster) -OutFile $archive;" ^
    "  };" ^
    "  $expanded = Join-Path $tempRoot 'x';" ^
    "  Expand-Archive -LiteralPath $archive -DestinationPath $expanded;" ^
    "  $installer = Get-ChildItem -LiteralPath $expanded -Filter 'install-from-download-windows.ps1' -File -Recurse | Select-Object -First 1;" ^
    "  if (-not $installer) { throw 'Downloaded ZIP is missing install-from-download-windows.ps1.' };" ^
    "  $installer = $installer.FullName;" ^
    "  & $installer;" ^
    "} finally {" ^
    "  if (Test-Path -LiteralPath $tempRoot) { Remove-Item -LiteralPath $tempRoot -Recurse -Force -ErrorAction SilentlyContinue };" ^
    "}"
)
set "INSTALL_RESULT=%ERRORLEVEL%"

echo.
if not "%INSTALL_RESULT%"=="0" (
  echo Installation failed. Please send a screenshot of this window to the plugin author.
) else (
  echo Installation completed. You can close this window and open ChatGPT.
)
echo.
if not "%GOLDHANDBLOG_SKIP_PAUSE%"=="1" pause
exit /b %INSTALL_RESULT%
