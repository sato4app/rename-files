@echo off
rem ---------------------------------------------------------------
rem  Batch file rename tool - launcher
rem  Double-click this file to start the app.
rem  You can also drop a folder onto this file to open it directly.
rem ---------------------------------------------------------------
cd /d "%~dp0"

where pythonw.exe >nul 2>nul
if %errorlevel%==0 (
    start "" pythonw.exe "rename_files.py" %*
    exit /b
)

where python.exe >nul 2>nul
if %errorlevel%==0 (
    start "" python.exe "rename_files.py" %*
    exit /b
)

echo Python was not found. Please install Python 3 from https://www.python.org/
pause
