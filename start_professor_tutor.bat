@echo off
chcp 65001 >nul
title AI Professor (Tutor) - Starting...

cd /d "%~dp0"

echo [1/2] Starting Vosk TTS server...
tasklist /FI "WINDOWTITLE eq hVostic TTS*" 2>nul | find /i "python.exe" >nul
if errorlevel 1 (
    start "hVostic TTS" /MIN "N:\exam\hVostic TTS\venv\Scripts\python.exe" "N:\exam\LocalLLMExperement\hVostic TTS\server.py"
    echo       Waiting for TTS...
    timeout /t 10 /nobreak >nul
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
