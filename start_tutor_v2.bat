@echo off
chcp 65001 >nul
title AI Professor (Tutor v2)
cd /d "%~dp0"

rem ============================================================
rem  Tutor v2 launcher - kills any previous instance, starts the
rem  Vosk TTS server, then the single-process tutor app.
rem  LM Studio (RAG embeddings, :22227) is a separate prerequisite.
rem ============================================================

echo [1/3] Stopping any previous tutor instance (prevents duplicated audio)...
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"name='python.exe'\" | Where-Object { $_.CommandLine -like '*tutor.app*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"

echo [2/3] Vosk TTS server...
curl -s -o nul --max-time 1 http://localhost:22232/health
if not errorlevel 1 goto vosk_running
powershell -NoProfile -Command "Start-Process -WindowStyle Minimized -FilePath 'scripts\_run_vosk_tts.bat'"
echo       waiting for TTS (model load can take up to 3 min on first run)...
set TTS_WAIT=0
:wait_tts
ping -n 4 127.0.0.1 >nul
set /a TTS_WAIT=TTS_WAIT+3
curl -s -o nul --max-time 1 http://localhost:22232/health
if not errorlevel 1 goto tts_ready
if %TTS_WAIT% lss 180 goto wait_tts
echo       ERROR: TTS did not start within 3 minutes. Check vosk_tts.log
exit /b 1
:tts_ready
echo       TTS ready after %TTS_WAIT% sec
goto check_lms
:vosk_running
echo       already running

:check_lms
curl -s -o nul --max-time 1 http://localhost:22227/v1/models
if not errorlevel 1 (
    echo       LM Studio detected on :22227 - local LLM / local embeddings available
    goto launch
)
echo       LM Studio not running on :22227 - tutor will use cloud
echo       provider from .env ^(OpenAI / Anthropic / DeepSeek / Yandex^).
echo       This is normal for the default setup.

:launch
echo [2.5/3] Starting board UI sidecar (optional, requires PySide6)...
.venv\Scripts\python.exe -c "import PySide6" 2>nul
if errorlevel 1 (
    echo       PySide6 not installed - skipping board. To enable:
    echo           pip install "PySide6~=6.7"
) else (
    start "AI Professor Board" /MIN .venv\Scripts\python.exe -m board
    echo       board launched - window appears once tutor writes first event
)

echo [3/3] Starting AI Professor Tutor v2 - live log below.
echo       Listen for the readiness signal. Press Ctrl+C here to stop.
echo       A copy of this log is also saved to tutor_v2.log
echo.
set PYTHONIOENCODING=utf-8
.venv\Scripts\python.exe -m tutor.app
