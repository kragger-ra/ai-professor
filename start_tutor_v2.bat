@echo off
chcp 65001 >nul
title AI Professor (Tutor v2)
cd /d "%~dp0"

rem ============================================================
rem  Tutor v2 launcher — brings up the Vosk TTS server, then the
rem  single-process tutor app (python -m tutor.app).
rem  LM Studio (RAG embeddings, :22227) is a separate prerequisite.
rem ============================================================

echo [1/2] Vosk TTS server...
curl -s -o nul --max-time 1 http://localhost:22232/health
if not errorlevel 1 (
    echo       already running
    goto check_lms
)
rem Detach the TTS server into its own minimized console so it
rem survives after this launcher hands off to the foreground app.
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

:check_lms
rem LM Studio embeddings — required for RAG; started separately.
curl -s -o nul --max-time 1 http://localhost:22227/v1/models
if errorlevel 1 (
    echo       WARNING: LM Studio ^(:22227^) not responding — RAG will be
    echo                unavailable. Start LM Studio with the bge-m3 model.
)

echo [2/2] Starting AI Professor Tutor v2...
echo.
set PYTHONIOENCODING=utf-8
.venv\Scripts\python.exe -m tutor.app
