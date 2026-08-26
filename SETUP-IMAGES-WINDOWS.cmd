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

py.exe -3 --version >nul 2>nul
if not errorlevel 1 goto :run_py

python.exe --version >nul 2>nul
if not errorlevel 1 goto :run_python

echo Automatic image setup did not finish.
echo Run INSTALL-WINDOWS.cmd again, then retry this file.
goto :failed

:run_py
py.exe -3 -X utf8 "%GOLDHAND_SETUP_SCRIPT%"
if errorlevel 1 goto :failed
goto :complete

:run_python
python.exe -X utf8 "%GOLDHAND_SETUP_SCRIPT%"
if errorlevel 1 goto :failed
goto :complete

:complete
echo.
echo AUTOMATIC IMAGE SETUP COMPLETE
if not "%GOLDHANDBLOG_SKIP_PAUSE%"=="1" pause
endlocal
exit /b 0

:failed
echo.
echo AUTOMATIC IMAGE SETUP FAILED
if not "%GOLDHANDBLOG_SKIP_PAUSE%"=="1" pause
endlocal
exit /b 1
