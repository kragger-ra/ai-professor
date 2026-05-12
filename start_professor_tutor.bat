@echo off
chcp 65001 >nul
title AI Professor (Tutor) - Starting...

cd /d "%~dp0"

echo [1/2] Starting Vosk TTS server...
curl -s -o nul --max-time 1 http://localhost:22232/health
if errorlevel 1 (
    start "Vosk TTS" /MIN .venv\Scripts\python.exe vosk_tts_server\server.py
    echo       Waiting for TTS (model load can take up to 2 min on first run)...
    set /a TTS_WAIT=0
    :wait_tts
    timeout /t 3 /nobreak >nul
    set /a TTS_WAIT+=3
    curl -s -o nul --max-time 1 http://localhost:22232/health
    if errorlevel 1 (
        if %TTS_WAIT% lss 180 goto wait_tts
        echo       TTS did not start within 3 minutes. Check vosk_tts_server logs.
        exit /b 1
    )
    echo       TTS ready after %TTS_WAIT% sec
) else (
    echo       Already running
)

echo [2/2] Starting AI Professor Tutor (args: %*)...
start "AI Professor Tutor" /MIN .venv\Scripts\python.exe src\main.py %*
echo       Waiting for Gradio...
timeout /t 15 /nobreak >nul

echo.
echo ========================================
echo   AI Professor (Tutor) is ready!
echo   Opening http://localhost:22229
echo ========================================
start http://localhost:22229
exit
