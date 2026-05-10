@echo off
chcp 65001 >nul
title Stopping AI Professor (Tutor)...

cd /d "%~dp0"

echo Releasing VoiceMeeter audio...
python -c "import sys; sys.path.insert(0,chr(39)+chr(115)+chr(114)+chr(99)+chr(39)); from utils.voicemeeter_control import release_audio; print(release_audio())" 2>nul

echo Stopping processes on port 22229 (Tutor Gradio)...
for /f "tokens=5" %%a in ('netstat -aon ^| findstr :22229 ^| findstr LISTENING') do taskkill /PID %%a /F 2>nul
rem Note: Vosk TTS on :22232 is shared with Lecture build; do not kill it here.

echo.
echo All stopped.
timeout /t 3 /nobreak >nul
exit
