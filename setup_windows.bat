@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 (
  echo Python Launcher was not found. Install Python 3.12 64-bit from https://www.python.org/downloads/windows/
  pause
  exit /b 1
)
py -3.12 -m venv .venv
if errorlevel 1 (
  echo Could not create the virtual environment. Make sure Python 3.12 is installed.
  pause
  exit /b 1
)
.venv\Scripts\python.exe -m pip install --upgrade pip
if errorlevel 1 goto :fail
.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 goto :fail
echo.
echo Setup complete. Run run_windows.bat to launch the app.
echo FFmpeg is optional unless you want to burn subtitles into the video.
pause
exit /b 0
:fail
echo Setup failed. Read the error above, then check the README troubleshooting section.
pause
exit /b 1
