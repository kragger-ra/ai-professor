@echo off
chcp 65001 >nul
title Stopping AI Professor...

cd /d "%~dp0"

echo Releasing VoiceMeeter audio...
python -c "import sys; sys.path.insert(0,chr(39)+chr(115)+chr(114)+chr(99)+chr(39)); from utils.voicemeeter_control import release_audio; print(release_audio())" 2>nul

echo Stopping processes on ports 22228, 22232...
for /f "tokens=5" %%a in ('netstat -aon ^| findstr :22228 ^| findstr LISTENING') do taskkill /PID %%a /F 2>nul
for /f "tokens=5" %%a in ('netstat -aon ^| findstr :22232 ^| findstr LISTENING') do taskkill /PID %%a /F 2>nul

echo.
echo All stopped.
timeout /t 3 /nobreak >nul
exit
