@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "PYTHONUTF8=1"
set "GOLDHAND_SETUP_SCRIPT=%~dp0plugins\goldhand-clinic-blog\skills\goldhand-clinic-blog\scripts\setup_image_host.py"

if not exist "%GOLDHAND_SETUP_SCRIPT%" (
  echo The Goldhand image setup script is missing.
  echo Run INSTALL-WINDOWS.cmd again before using this file.
  goto :failed
)

where py.exe >nul 2>nul
if not errorlevel 1 (
  py.exe -3 -X utf8 "%GOLDHAND_SETUP_SCRIPT%"
  if not errorlevel 1 goto :complete
)

where python.exe >nul 2>nul
if not errorlevel 1 (
  python.exe -X utf8 "%GOLDHAND_SETUP_SCRIPT%"
  if not errorlevel 1 goto :complete
)

echo Automatic image setup did not finish.
echo Run INSTALL-WINDOWS.cmd again, then retry this file.
goto :failed

:complete
echo.
echo AUTOMATIC IMAGE SETUP COMPLETE
goto :finish

:failed
echo.
echo AUTOMATIC IMAGE SETUP FAILED

:finish
if not "%GOLDHANDBLOG_SKIP_PAUSE%"=="1" pause
endlocal
