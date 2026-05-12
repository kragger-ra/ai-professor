@echo off
chcp 65001 >nul
title AI Professor (Tutor) - Starting...

cd /d "%~dp0"

echo [1/2] Starting Vosk TTS server...
curl -s -o nul --max-time 1 http://localhost:22232/health
if not errorlevel 1 (
    echo       Already running
    goto launch_main
)

start "Vosk TTS" /MIN cmd /c ".venv\Scripts\python.exe vosk_tts_server\server.py 1>vosk_tts.log 2>&1"
echo       Waiting for TTS (model load can take up to 3 min on first run)...
set TTS_WAIT=0

:wait_tts
timeout /t 3 /nobreak >nul
set /a TTS_WAIT=TTS_WAIT+3
curl -s -o nul --max-time 1 http://localhost:22232/health
if not errorlevel 1 goto tts_ready
if %TTS_WAIT% lss 180 goto wait_tts
echo       TTS did not start within 3 minutes. Check vosk_tts.log
exit /b 1

:tts_ready
echo       TTS ready after %TTS_WAIT% sec

:launch_main
echo [2/2] Starting AI Professor Tutor (args: %*)...
start "AI Professor Tutor" /MIN cmd /c ".venv\Scripts\python.exe src\main.py %* 1>tutor.log 2>&1"
echo       Waiting for Gradio...
timeout /t 15 /nobreak >nul

echo.
echo ========================================
echo   AI Professor (Tutor) is ready!
echo   Opening http://localhost:22229
echo ========================================
start http://localhost:22229
exit
